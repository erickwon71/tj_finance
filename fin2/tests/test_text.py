"""
Track B 텍스트 추출기 회귀 테스트 (실측 파일, DB 비의존).

실측: 큐로셀(01492651) 2023 사업보고서 — ACONTEXT 없는 Track B(별도만, pre-revenue).
golden(curocell_2023_pre_revenue)과 동일 값 검증:
  별도 자산 104,969,385,964 / 자본 59,099,540,497 / 매출 0(<1억).
또한 무손실(미매핑 행 보존)·합성 acontext 고유성 검증.

실행: python -m fin2.tests.test_text
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.text import extract_facts, _canonical_of  # noqa: E402
from parser.common.account_mapper import MappingResult  # noqa: E402

_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/01492651_큐로셀/annual/2023/20240319000229.xml"
)
_RCEPT = "20240319000229"
_CORP = "01492651"


def _extract():
    return extract_facts(
        _SAMPLE, rcept_no=_RCEPT, corp_code=_CORP,
        report_fiscal_year=2023, report_fiscal_period="FY",
    )


def _col0_canon(facts, code, basis="separate"):
    vals = [
        f.amount_won for f in facts
        if f.canonical_account == code and f.basis == basis and f.col_index == 0
    ]
    return vals


def test_assets_equity_match_golden():
    facts = _extract()
    assert 104_969_385_964 in _col0_canon(facts, "bs.total_assets")
    assert 59_099_540_497 in _col0_canon(facts, "bs.total_equity")


def test_pre_revenue():
    facts = _extract()
    rev = _col0_canon(facts, "is.revenue")
    # 매출 행이 존재하면 1억 미만(큐로셀 2023 매출 0)
    assert all(v < 100_000_000 for v in rev), rev


def test_no_data_loss_unmapped_kept():
    facts = _extract()
    # 미매핑(canonical NULL) 행도 raw acode 와 함께 보존되어야 함
    assert any(f.canonical_account is None and f.acode for f in facts)


def test_synthetic_acontext_unique_per_cell():
    facts = _extract()
    keys = [(f.acode, f.acontext_raw) for f in facts]
    assert len(keys) == len(set(keys)), "합성 acontext 키가 고유하지 않음(셀 충돌)"
    assert all(f.acontext_raw.startswith("text:") for f in facts)
    assert all(f.context_parsed is False for f in facts)


def test_separate_only_no_consolidated():
    # 큐로셀은 FIN_TYPE=B(별도만) → 연결 행이 없어야 함
    facts = _extract()
    assert all(f.basis != "consolidated" for f in facts)


# ── 반기/3분기 누적컬럼 정합 회귀 (Track B interim cumulative) ──
# 제이아이테크 2024 반기: IS 가 [당기[3개월,누적], 전기[3개월,누적]] 2단 헤더.
# 누적컬럼만 채택해 col0=2024 H1 누적=30,488,775,643 / col1=2023 H1 누적=23,273,515,096.
# (버그 시: 3개월 17,044,235,442 을 col0 누적으로 오라벨하고 연도까지 밀림.)
_H1_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/01367586_제이아이테크/half/2024/20240814001863.xml"
)


def test_interim_cumulative_columns():
    if not _H1_SAMPLE.exists():
        return  # 파일 없으면 스킵
    facts = extract_facts(_H1_SAMPLE, rcept_no="20240814001863", corp_code="01367586",
                          report_fiscal_year=2024, report_fiscal_period="H1")
    rev = {(f.col_index, f.context_fiscal_year): f.amount_won
           for f in facts if f.canonical_account == "is.revenue" and f.basis == "separate"}
    assert rev.get((0, 2024)) == 30_488_775_643, f"2024 H1 누적 불일치: {rev}"
    assert rev.get((1, 2023)) == 23_273_515_096, f"2023 H1 누적 불일치: {rev}"
    assert rev.get((0, 2024)) != 17_044_235_442  # 3개월이 col0 으로 새면 안 됨


def test_fuzzy_mapping_gets_no_canonical():
    """퍼지 매치는 canonical 을 받지 못한다(M1/M2, 추측 금지).

    실측 반례(2026-07-17): '금융부채'가 alias '단기금융부채' 와 0.96 유사도로 bs.short_term_debt
    에, '기타무형자산'이 '무형자산'(상위개념!)에 붙었다. 유사도는 개념 동일성의 근거가 아니다.
    """
    fuzzy = MappingResult("bs.short_term_debt", 0.96, "fuzzy", "단기금융부채")
    assert _canonical_of(fuzzy) is None, "퍼지에 canonical 을 주면 안 된다"


def test_exact_and_guard_keep_canonical():
    """정확/정규화 일치와 명시 가드는 canonical 을 유지한다(추측이 아니라 사전·규칙)."""
    assert _canonical_of(MappingResult("bs.cash", 1.0, "exact", "현금및현금성자산")) == "bs.cash"
    assert _canonical_of(MappingResult("is.revenue", 1.0, "normalized", "매출액")) == "is.revenue"
    assert _canonical_of(MappingResult("is.ebt", 0.95, "guard", "법인세비용차감전이익")) == "is.ebt"


def test_unknown_gets_no_canonical_but_row_survives():
    """미매핑은 canonical NULL. 단 행은 acode 로 보존된다(무손실) — 여기선 canonical 만 검증."""
    assert _canonical_of(MappingResult("unknown.무언가", 0.0, "unknown")) is None


def _run():
    if not _SAMPLE.exists():
        print(f"  - SKIP: 실측 파일 없음 {_SAMPLE}")
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
