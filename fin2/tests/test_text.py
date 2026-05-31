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

from fin2.extract.text import extract_facts  # noqa: E402

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
