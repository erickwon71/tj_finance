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


def test_note_ref_residue_stripped_to_exact_match():
    """<주석N/> 잔재를 뗀 뒤 **정확일치**로 매핑된다(퍼지에 기대지 않는다).

    실측 원문(DB손해보험 20230927000457):
      <TD>Ⅵ. 이익잉여금<주석19/>,39&gt;</TD>
    DART 편집기가 '<주석19,39>' 를 엘리먼트+꼬리텍스트로 저장해 itertext 가 '이익잉여금,39>' 를
    만든다. 이건 유사한 이름이 아니라 정제 실패이므로 **파서가 고칠 일**이다(계획 §2 원칙 4).
    이 테스트가 깨지면 8.5경 사고의 그 계정이 다시 canonical 을 잃는다.
    """
    from parser.common.amount_normalizer import normalize_account_name
    assert normalize_account_name("이익잉여금,39>") == "이익잉여금"
    assert normalize_account_name("4. 기타포괄손익-공정가치측정금융자산,22,32,42,44>") \
        == "기타포괄손익-공정가치측정금융자산"
    assert normalize_account_name("Ⅰ.현금및현금성자산(주석 9,37)") == "현금및현금성자산"
    # 무관한 라벨은 건드리지 않는다(괄호 보존).
    assert normalize_account_name("당기순이익(손실)") == "당기순이익(손실)"


def test_db_insurance_retained_earnings_canary():
    """★ 8.5경 사고 카나리아: DB손해보험 별도 이익잉여금이 정상 규모 + 정확매핑이어야 한다."""
    p = Path(__file__).resolve().parents[2] / (
        "raw_report/KOSPI/00159102_DB손해보험/half/2023/20230927000457.xml")
    if not p.exists():
        return
    facts = extract_facts(p, rcept_no="20230927000457", corp_code="00159102",
                          report_fiscal_year=2023, report_fiscal_period="H1")
    got = [f for f in facts if f.canonical_account == "bs.retained_earnings"
           and f.basis == "separate" and f.col_index == 0]
    assert got, "별도 이익잉여금이 canonical 로 잡히지 않음(주석잔재 정제 회귀?)"
    assert got[0].amount_won == 8_564_682_463_043, got[0].amount_won   # 구버전: ×10⁶ 오염
    assert got[0].mapping_stage in ("exact", "normalized"), got[0].mapping_stage
    assert got[0].unit_source == "declared"
    assert got[0].section_kind == "재무제표"


# ── §5.4 classB 유형1 회귀(2026-08-29): 선두 None 절삭에 ACONTEXT 유무 신호 반영 ──
# 근거: docs/plans/gateb_trade_payables_classB_stale_column_investigation_2026-08-29.md §5~7.

def test_hanwha_insurance_net_income_no_regression():
    """f4819b8(2026-06-21)의 원 동기 사례 — 이 신호 도입으로 회귀하면 안 된다.

    한화손해보험 2020FY 연결 IS 'VIII.당기순이익(손실)' 행은 `<TD>`(비XBRL) 표라
    acontext_missing 신호가 전혀 없다(항상 False) — R19(2026-08-24)가 이미 이 표의
    빈 주석 컬럼을 원천 제거해 선두 None 자체가 안 생긴다. §5.4 변경은 이 분기(TD,
    신호 없음)를 전혀 건드리지 않으므로 값이 그대로여야 한다.
    """
    p = Path(__file__).resolve().parents[2] / (
        "raw_report/KOSPI/00135917_한화손해보험/annual/2020/20210310000259.xml")
    if not p.exists():
        return
    facts = extract_facts(p, rcept_no="20210310000259", corp_code="00135917",
                          report_fiscal_year=2020, report_fiscal_period="FY")
    got = [f for f in facts if f.canonical_account == "is.net_income"
           and f.basis == "consolidated" and f.col_index == 0]
    assert got, "연결 당기순이익이 canonical 로 잡히지 않음(회귀?)"
    assert got[0].amount_won == 48_250_117_187, got[0].amount_won


def test_classB_genuine_current_period_gap_not_misattributed():
    """classB 유형1 실제 수정 확인 — 홈캐스트(00385336) 2026Q1 별도 매입채무.

    원문(TE ACODE=dart_ShortTermTradePayables): 당기 셀은 ACONTEXT 속성 자체가 없다
    (=DART 원문이 명시한 '이 기간 미공시', 결합라벨 재편 등으로 추정) — 전기 셀만
    ACONTEXT 있는 정상 값. 수정 전에는 이 선두 None이 무조건 절삭돼 전기값
    203,341,500이 당기(col0)로 오귀속됐다(§5 원문대조). 수정 후에는 col0 이 아예
    나오지 않고 col1(전기)에만 정확히 슬롯돼야 한다.
    """
    p = Path(__file__).resolve().parents[2] / (
        "raw_report/KOSDAQ/00385336_홈캐스트/quarter/2026/20260515002885.xml")
    if not p.exists():
        return
    facts = extract_facts(p, rcept_no="20260515002885", corp_code="00385336",
                          report_fiscal_year=2026, report_fiscal_period="Q1")
    sep = [f for f in facts if f.canonical_account == "bs.trade_payables"
           and f.basis == "separate"]
    assert not any(f.col_index == 0 for f in sep), \
        f"당기(col0)가 나오면 안 됨(진짜 미공시가 전기값으로 오염) — got {sep}"
    c1 = [f for f in sep if f.col_index == 1]
    assert c1 and c1[0].amount_won == 203_341_500, sep


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
