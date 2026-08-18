"""Gate B face_audit 단위 테스트 — 독립 숫자 파서 + 범위 게이팅 + 행 롤업.

실행: python -m fin2.tests.test_face_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit.face_audit import (  # noqa: E402
    parse_displayed, FaceLine, audit_std_row, STATUS_PASS, STATUS_FAIL, STATUS_PENDING,
    RowAudit, gate_status_for_row, GATE_PASS, GATE_FAIL_A, GATE_FAIL_B, GATE_PENDING,
    read_report_face_xbrl, _adecimal_signals,
    EVIDENCE_E1_EXACT, EVIDENCE_E2_SIGN, EVIDENCE_E3_ROUNDING, EVIDENCE_E4_IDENTITY,
    EVIDENCE_E5_HEURISTIC, EVIDENCE_M1_STRONG, EVIDENCE_M2_WEAK,
)


def test_parse_displayed_basic():
    assert parse_displayed("1,234,567") == 1234567
    assert parse_displayed("(1,234)") == -1234        # 괄호 음수
    assert parse_displayed("△500") == -500            # 삼각형 음수
    assert parse_displayed("-12") == -12
    assert parse_displayed("0") == 0
    assert parse_displayed("") is None
    assert parse_displayed("   ") is None
    assert parse_displayed("N/A") is None
    assert parse_displayed("1,234.6") == 1235          # 소수 반올림


def _bs_line(canon, won, basis="consolidated", ade=0):
    # adecimal=0 이면 amount_won == displayed
    return FaceLine(statement="BS", basis=basis, acode="x", canonical=canon,
                    label="x", displayed_value=won, adecimal=ade)


def test_row_pass_when_all_inscope_match():
    db = {"total_assets": 1000, "total_liabilities": 600, "total_equity": 400}
    bs = [_bs_line("bs.total_assets", 1000), _bs_line("bs.total_liabilities", 600),
          _bs_line("bs.total_equity", 400)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.n_fail == 0 and ra.n_pending == 0


def test_row_fail_on_value_diff():
    db = {"total_assets": 900}  # 보고서 1000 (표시단위 1단위 초과 = 실오류)
    bs = [_bs_line("bs.total_assets", 1000)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_FAIL
    assert ra.fail_fields == ["total_assets"]


def test_display_unit_tolerance():
    # 천원(ade=-3) 1단위(1,000원) 이내 = 발행사 반올림 → PASS.
    ra = audit_std_row({"total_assets": 1_234_000}, basis="consolidated",
                       bs_face=[_bs_line("bs.total_assets", 1235, ade=-3)],
                       is_face=[], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    # 2단위(2,000원) 차이 = 실오류 → FAIL.
    ra2 = audit_std_row({"total_assets": 1_233_000}, basis="consolidated",
                        bs_face=[_bs_line("bs.total_assets", 1235, ade=-3)],
                        is_face=[], cf_face=[], is_comparative=False)
    assert ra2.status == STATUS_FAIL


def test_net_income_matches_attribution_sum():
    # 본문 당기순이익 라인이 불일치(3개월만)해도 지배+비지배 귀속 합과 일치 → PASS.
    is_face = [_bs_line("is.net_income", -502_592_034),
               _bs_line("is.controlling_ni", -1_903_963_591),
               _bs_line("is.noncontrolling_ni", -3_177_661)]
    ra = audit_std_row({"net_income": -1_907_141_252}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.n_fail == 0, ra.fields


def test_comparative_row_unmatched_is_pending_not_fail():
    # 비교행 값이 보고서 face(전 컬럼)에 없으면 → PENDING(절대 fail 아님: fail=0 보존).
    db = {"total_assets": 777}
    bs = [_bs_line("bs.total_assets", 1000), _bs_line("bs.total_assets", 1200)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=True)
    assert ra.status == STATUS_PENDING
    assert ra.n_fail == 0


def test_comparative_row_matched_is_pass():
    # 비교행 값이 보고서 전 컬럼(all_cols face) 중 하나와 일치하면 → PASS(검증, 커버리지 확장).
    db = {"total_assets": 1200}
    bs = [_bs_line("bs.total_assets", 1000), _bs_line("bs.total_assets", 1200)]  # 전기 컬럼 1200
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=True)
    assert ra.status == STATUS_PASS, ra.fields
    assert ra.n_fail == 0


def test_track_b_source_is_pending():
    db = {"total_assets": 1000}
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PENDING  # face 비어있음 = Track B/미수록


def test_unit_scaled_match():
    # 천원 단위 표시(adecimal=-3): displayed 1234 → amount_won 1,234,000
    line = _bs_line("bs.total_assets", 1234, ade=-3)
    assert line.amount_won == 1234000
    db = {"total_assets": 1234000}
    ra = audit_std_row(db, basis="consolidated", bs_face=[line], is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS


def test_pending_blocks_pass():
    # 하나는 통과, 하나는 Track B(pending) → 행은 100% 인증 불가 → pending
    db = {"total_assets": 1000, "cfo": 500}
    bs = [_bs_line("bs.total_assets", 1000)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)  # cf_face 비어있음 → cfo pending
    assert ra.status == STATUS_PENDING
    assert ra.n_pass == 1 and ra.n_pending == 1


def test_sign_flip_is_pass():
    # std 는 비용을 양수화(매출원가 +), 보고서는 괄호 음수(-). 절대값 충실 → PASS.
    db = {"cogs": 27747335376}
    is_line = FaceLine(statement="IS", basis="separate", acode="매출원가", canonical="is.cogs",
                       label="매출원가", displayed_value=-27747335376, adecimal=0)
    ra = audit_std_row(db, basis="separate", bs_face=[], is_face=[is_line], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.n_fail == 0


def _ra(status, fail_fields=()):
    return RowAudit(status=status, n_pass=0, n_fail=len(fail_fields), n_pending=0,
                    fields=[], fail_fields=list(fail_fields))


def test_gate_pass_pending_passthrough():
    assert gate_status_for_row(_ra(STATUS_PASS), {}) == GATE_PASS
    assert gate_status_for_row(_ra(STATUS_PENDING), {}) == GATE_PENDING


def test_gate_track_a_fail_is_fail_a():
    # Track A 출처 실패 = 확정버그 → fail_a(차단)
    ra = _ra(STATUS_FAIL, ["total_assets"])
    assert gate_status_for_row(ra, {"total_assets": "A"}) == GATE_FAIL_A


def test_gate_track_b_fail_is_fail_b():
    # 전 실패필드가 Track B = 휴리스틱 → fail_b(REVIEW, 메인뷰 노출)
    ra = _ra(STATUS_FAIL, ["cash"])
    assert gate_status_for_row(ra, {"cash": "B"}) == GATE_FAIL_B


def test_gate_mixed_fail_blocks_on_any_track_a():
    ra = _ra(STATUS_FAIL, ["cash", "total_assets"])
    assert gate_status_for_row(ra, {"cash": "B", "total_assets": "A"}) == GATE_FAIL_A


def test_gate_unknown_track_is_conservative_fail_a():
    # track 미상(None/누락)은 보수적으로 차단(fail_a)
    ra = _ra(STATUS_FAIL, ["revenue"])
    assert gate_status_for_row(ra, {"revenue": None}) == GATE_FAIL_A
    assert gate_status_for_row(ra, {}) == GATE_FAIL_A


def test_revenue_derived_verified_by_cogs_plus_gross_profit():
    # 매출액 단일 라인 부재 + std 가 cogs+gross_profit 로 파생 → 항등식 합 일치 시 PASS.
    is_face = [_bs_line("is.cogs", 800), _bs_line("is.gross_profit", 200)]
    ra = audit_std_row({"revenue": 1000}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    # 괄호 음수 cogs(=양수화 안 된 face)도 abs 로 일치.
    is_face2 = [_bs_line("is.cogs", -800), _bs_line("is.gross_profit", 200)]
    ra2 = audit_std_row({"revenue": 1000}, basis="consolidated",
                        bs_face=[], is_face=is_face2, cf_face=[], is_comparative=False)
    assert ra2.status == STATUS_PASS, ra2.fields


def test_net_income_label_unmatched_falls_back_to_attribution():
    # IS face 에 총 당기순이익 라인 부재(LABEL_UNMATCHED 상황)여도 지배+비지배 귀속 합과
    # 일치하면 PASS(보고서에 값 실재 검증). fail 아님·pending 아님.
    is_face = [_bs_line("is.controlling_ni", 900), _bs_line("is.noncontrolling_ni", 100)]
    ra = audit_std_row({"net_income": 1000}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    assert ra.n_fail == 0


def test_net_income_label_unmatched_falls_back_to_cf_line():
    # IS face 에 net_income 라인 부재여도 CF 간접법 시작 '당기순이익'(cf.net_income_cf)과
    # 일치하면 PASS(동일 file 의 CF face 가 병합돼 있는 경우).
    face = [_bs_line("cf.net_income_cf", 1000)]
    ra = audit_std_row({"net_income": 1000}, basis="consolidated",
                       bs_face=[], is_face=face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


def test_net_income_label_unmatched_no_alt_stays_pending_not_fail():
    # 보조 라인도 불일치면 LABEL_UNMATCHED(pending) 유지 — 절대 fail 아님(fail=0 보존).
    face = [_bs_line("is.controlling_ni", 900), _bs_line("is.noncontrolling_ni", 50)]  # 합 950≠1000
    ra = audit_std_row({"net_income": 1000}, basis="consolidated",
                       bs_face=[], is_face=face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PENDING
    assert ra.n_fail == 0


def _write_xbrl_fixture(*te_specs: tuple[str, str, str, str]) -> str:
    """(acode, acontext, adecimal_attr_or_None, text) 목록 → 임시 DART XML 파일 경로."""
    import tempfile
    tes = []
    for acode, acontext, adecimal, txt in te_specs:
        ade_attr = f' ADECIMAL="{adecimal}"' if adecimal is not None else ""
        tes.append(f'<TE ACODE="{acode}" ACONTEXT="{acontext}"{ade_attr}>{txt}</TE>')
    xml = ("<DOCUMENT><BODY><TABLE><TR>" + "".join(tes) + "</TR></TABLE></BODY></DOCUMENT>")
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8")
    f.write(xml)
    f.close()
    return f.name


# 노루페인트(00583442) 실측 구조(§8-A, 2026-08-12) 축약: 무차원 합계 fact 만 ADECIMAL=0으로
# 잘못 태깅, 차원분해(카테고리) 형제는 정확히 -3(천원).
_HOME_CTX = ("CFY2025eFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis"
             "_ifrs-full_ConsolidatedMember")
_DIM_CTX = (_HOME_CTX + "_ifrs-full_CategoriesOfFinancialLiabilitiesAxis"
            "_ifrs-full_FinancialLiabilitiesAtAmortisedCostCategoryMember")
_DIM_CTX2 = (_HOME_CTX + "_ifrs-full_CategoriesOfFinancialLiabilitiesAxis"
             "_ifrs-full_FinancialLiabilitiesAtFairValueThroughProfitOrLossCategoryMember")


def test_component_sum_identity_override_fixes_home_fact():
    """§8-A: 무차원 홈 fact 의 잘못된 ADECIMAL=0 을, 같은 축의 차원분해 멤버 2개를 각자
    ADECIMAL 로 합산한 값이 실제로 그 합계와 일치할 때만(항등식) override(-3)."""
    path = _write_xbrl_fixture(
        ("dart_ShortTermTradePayables", _HOME_CTX, "0", "111,249,978"),
        ("dart_ShortTermTradePayables", _DIM_CTX, "-3", "111,249,978"),   # amortised cost
        ("dart_ShortTermTradePayables", _DIM_CTX2, "-3", "0"),            # fair value(0)
    )
    lines = read_report_face_xbrl(path)
    matches = [l for l in lines if l.canonical == "bs.trade_payables"]
    assert len(matches) == 1, matches
    assert matches[0].adecimal == -3, matches[0]
    assert matches[0].amount_won == 111249978000, matches[0]


def test_single_dimensional_member_is_insufficient_evidence():
    """구성요소가 1개뿐이면(합산 항등식으로 검증 불가) override 보류 — 짐작 금지."""
    path = _write_xbrl_fixture(
        ("dart_ShortTermTradePayables", _HOME_CTX, "0", "111,249,978"),
        ("dart_ShortTermTradePayables", _DIM_CTX, "-3", "111,249,978"),
    )
    lines = read_report_face_xbrl(path)
    matches = [l for l in lines if l.canonical == "bs.trade_payables"]
    assert len(matches) == 1, matches
    assert matches[0].adecimal == 0, matches[0]   # 증거 부족 → 원래 값 그대로


def test_component_sum_mismatch_blocks_override():
    """구성요소가 2개 있어도 합이 합계와 안 맞으면(=진짜 구성요소가 아님) override 보류."""
    path = _write_xbrl_fixture(
        ("dart_ShortTermTradePayables", _HOME_CTX, "0", "111,249,978"),
        ("dart_ShortTermTradePayables", _DIM_CTX, "-3", "500"),
        ("dart_ShortTermTradePayables", _DIM_CTX2, "-3", "700"),
    )
    lines = read_report_face_xbrl(path)
    matches = [l for l in lines if l.canonical == "bs.trade_payables"]
    assert len(matches) == 1, matches
    assert matches[0].adecimal == 0, matches[0]


def test_adecimal_signals_verified_map_requires_component_sum_identity():
    from lxml import etree
    xml = (f'<DOCUMENT><BODY><TABLE><TR>'
           f'<TE ACODE="dart_x" ACONTEXT="{_HOME_CTX}" ADECIMAL="0">1000</TE>'
           f'<TE ACODE="dart_x" ACONTEXT="{_DIM_CTX}" ADECIMAL="-3">600</TE>'
           f'<TE ACODE="dart_x" ACONTEXT="{_DIM_CTX2}" ADECIMAL="-3">400</TE>'
           f'</TR></TABLE></BODY></DOCUMENT>')
    root = etree.fromstring(xml)
    verified, ambiguous = _adecimal_signals(root)
    assert verified == {("dart_x", "consolidated", 0, False): -3}
    assert ambiguous == set()


def test_duplicate_home_fact_with_conflicting_values_blocks_override():
    """★회귀재현 #1(2026-08-12, 00583442 cash) — 같은 concept 가 본문표(전체정밀도)와 주석표
    (천원 반올림, ADECIMAL 오태깅)에 무차원으로 중복 등장하면, dedup 이 이미 정답(본문표,
    ADECIMAL=0·전체정밀도)을 골랐어도 override 를 절대 적용하지 않는다."""
    path = _write_xbrl_fixture(
        # 본문 재무상태표 표 — 이미 정답(전체 정밀도, ADECIMAL=0 이 맞음).
        ("ifrs-full_CashAndCashEquivalents", _HOME_CTX, "0", "111,779,270,286"),
        # 위험관리 주석표 — 같은 acode+context 로 재등장, 천원 반올림(ADECIMAL 오태깅=0).
        ("ifrs-full_CashAndCashEquivalents", _HOME_CTX, "0", "111,779,270"),
        ("ifrs-full_CashAndCashEquivalents", _DIM_CTX, "-3", "111,779,270"),
        ("ifrs-full_CashAndCashEquivalents", _DIM_CTX2, "-3", "0"),
    )
    lines = read_report_face_xbrl(path)
    matches = [l for l in lines if l.canonical == "bs.cash"]
    assert len(matches) == 1, matches
    # dedup 은 문서상 첫 occurrence(본문표, 이미 정답)를 고르고, override 는 적용되지 않는다.
    assert matches[0].amount_won == 111779270286, matches[0]


def test_unrelated_reused_tag_with_conflicting_duplicate_member_blocks_override():
    """★회귀재현 #2(2026-08-12, 00146861 cash) — 무차원 fact 는 유일(정답)했지만, 같은
    축·같은 멤버조합이 서로 다른 값으로 중복 등장하는 "형제"는 사실 합계의 구성요소가
    아니라 무관한 다른 주석의 재태깅이었다 — 그 멤버는 폐기하고 override 하지 않는다."""
    path = _write_xbrl_fixture(
        ("ifrs-full_CashAndCashEquivalents", _HOME_CTX, "0", "42,037,894,798"),   # 정답, 유일
        ("ifrs-full_CashAndCashEquivalents", _DIM_CTX, "-3", "42,037,895"),
        ("ifrs-full_CashAndCashEquivalents", _DIM_CTX, "-3", "-42,037,895"),   # 같은 멤버조합, 값 충돌
    )
    lines = read_report_face_xbrl(path)
    matches = [l for l in lines if l.canonical == "bs.cash"]
    assert len(matches) == 1, matches
    assert matches[0].amount_won == 42037894798, matches[0]


def test_trade_payables_zero_candidate_excluded_for_curated_key():
    # R23 — 아이텍(00626011) 2025FY separate: db=0(실제 버그), 후보 중 하나가 우연히 값=0.
    # curated 키에 걸리면 값=0 후보를 제외해 진짜 VALUE_DIFF(fail)가 가려지지 않아야 한다.
    db = {"corp_code": "00626011", "fiscal_year": 2025, "fiscal_period": "FY",
          "trade_payables": 0}
    bs = [_bs_line("bs.trade_payables", 5_068_265_299, basis="separate"),
          _bs_line("bs.trade_payables", 0, basis="separate")]
    ra = audit_std_row(db, basis="separate", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_FAIL, ra.fields
    assert ra.fail_fields == ["trade_payables"]


def test_trade_payables_zero_candidate_matches_for_non_curated_key():
    # 다른 회사/기간은 값=0 후보가 그대로 남아(정상 매칭 로직) db=0 이면 PASS.
    db = {"corp_code": "99999999", "fiscal_year": 2025, "fiscal_period": "FY",
          "trade_payables": 0}
    bs = [_bs_line("bs.trade_payables", 0, basis="separate")]
    ra = audit_std_row(db, basis="separate", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


# ── ★R32(2026-08-17) 업종 프로파일 파생 revenue (Gate B ① Phase 2) ──────────────────

def _is_line(canon, won, basis="consolidated", ade=0):
    # _bs_line 은 statement 를 "BS" 로 고정해 실제 리더 동작(canonical 접두어로 파생, 위
    # _statement_of)과 다르다 — _recompute_profile_revenue 의 raw-value 우회 경로가
    # ln.statement=="IS" 를 요구하므로 여기선 정확히 태깅한다.
    return FaceLine(statement="IS", basis=basis, acode="x", canonical=canon,
                    label="x", displayed_value=won, adecimal=ade)


def test_securities_profile_derived_revenue_pass():
    # 증권 순영업수익 = 영업이익+판관비. face 에 원문 성분(operating_income/sga)만 있고
    # 파생 총계(revenue) 라인 자체는 없어도, 성분 재계산이 std 값과 일치하면 PASS.
    db = {"revenue": 1_624_073, "industry_lines": {"profile": "securities",
          "operating_income": 1_375_040, "sga": 249_033}}
    is_face = [_is_line("is.operating_income", 1_375_040), _is_line("is.sga", 249_033)]
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=is_face, cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


def test_securities_profile_derived_revenue_value_diff_stays_fail():
    # 성분은 face 에서 다 찾았지만 합이 std 값과 다르면(진짜 버그) 여전히 FAIL — 면제로
    # 퇴화하지 않는다(설계 §6-F 필수 항목).
    db = {"revenue": 999_999, "industry_lines": {"profile": "securities",
          "operating_income": 1_375_040, "sga": 249_033}}
    is_face = [_is_line("is.operating_income", 1_375_040), _is_line("is.sga", 249_033)]
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=is_face, cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_FAIL, ra.fields
    assert ra.fail_fields == ["revenue"]


def test_profile_derived_revenue_missing_component_is_pending_not_fail():
    # 성분(sga) 을 face 에서 못 찾으면 검증 불가 → DERIVED_COMPONENTS_UNVERIFIED(pending),
    # fail 아님(§3-B).
    db = {"revenue": 1_624_073, "industry_lines": {"profile": "securities",
          "operating_income": 1_375_040, "sga": 249_033}}
    is_face = [_is_line("is.operating_income", 1_375_040)]  # sga 라인 없음
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=is_face, cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PENDING, ra.fields
    assert ra.n_fail == 0
    reasons = [f.reason for f in ra.fields if f.field == "revenue"]
    assert reasons == ["DERIVED_COMPONENTS_UNVERIFIED"], reasons


def test_gross_fallback_row_skips_derived_path():
    # revenue_basis='gross_fallback' 행은 일반경로(공시 총계 그대로)로 이미 통과 대상이라
    # 파생검증을 타지 않는다(§3-D) — op_revenue_total 라인이 없어도 is.revenue 직접 라인이
    # 있으면 정상 매칭으로 PASS, 성분 부재로 pending 되지 않아야 한다.
    db = {"revenue": 5000, "industry_lines": {"profile": "securities",
          "op_revenue_total": 5000, "revenue_basis": "gross_fallback"}}
    is_face = [_is_line("is.revenue", 5000)]
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=is_face, cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


def test_bank_profile_collision_components_verified_by_raw_value():
    # fee_revenue/interest_revenue 는 canonical 없이(Track B 라벨 충돌 회피, §Phase1 주석)
    # face 의 아무 라인에나 값으로 있으면 검증된다 — canonical 태그와 무관.
    db = {"revenue": 160_923_000_000, "industry_lines": {"profile": "bank",
          "interest_revenue": 140_216_000_000, "fee_revenue": 20_707_000_000}}
    is_face = [_is_line("is.finance_income", 140_216_000_000),  # 이자수익, 다른 canonical
               _is_line("is.revenue", 20_707_000_000)]           # 수수료수익, 다른 canonical
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=is_face, cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


def test_insurance_revenue_component_accepts_operating_revenue_ins_alias():
    # dart_OperatingIncomeInsurance 는 기존에 is.operating_revenue_ins 로 매핑돼 있다
    # (재매핑하지 않음, concept_map.py 주석) — insurance_revenue 성분은 그 canonical 도 받는다.
    db = {"revenue": 900, "industry_lines": {"profile": "insurance",
          "insurance_revenue": 700, "investment_revenue": 200}}
    is_face = [_is_line("is.operating_revenue_ins", 700), _is_line("is.investment_revenue", 200)]
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=is_face, cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


def test_account_mapper_unchanged_for_fuzzy_matched_revenue_labels():
    # ★회귀고정(2026-08-17, 동양생명 00117267 2023Q1 실사고) — "투자영업수익"/"기타영업수익"에
    # is.investment_revenue/is.other_op_revenue exact alias 를 account_maps/is_accounts.py 에
    # 걸었더니, 그 라벨이 "영업수익"의 부분문자열이라 원래 fuzzy 매칭으로 is.revenue 에 잡히던
    # 회사의 매핑이 뒤바뀌어 pass→fail 회귀가 났다(이 사전은 Gate B 전용이 아니라 layer2/3
    # 표준화 본체도 쓰는 공용 사전이라 std_v3 실값까지 흔들 수 있음). 두 canonical 은 다시
    # 추가하지 않기로 했고(§_PROFILE_VALUE_FALLBACK_KEYS 주석), 이 테스트가 그 상태를 고정한다.
    from parser.common.account_mapper import get_mapper
    mapper = get_mapper()
    r1 = mapper.map("1. 투자영업수익", fs_section="is")
    assert r1.account_code != "is.investment_revenue", r1
    r2 = mapper.map("1.기타영업수익", fs_section="is")
    assert r2.account_code != "is.other_op_revenue", r2


def test_no_profile_row_unaffected_by_derived_path():
    # industry_lines 없는 일반 회사는 기존 cogs+gp 파생 경로가 그대로 동작(무영향, 회귀 방지).
    is_face = [_bs_line("is.cogs", 800), _bs_line("is.gross_profit", 200)]
    ra = audit_std_row({"revenue": 1000}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


# ── ② Gate B 증거강도 재정의 Phase 1 — 축2(evidence) 단위 테스트
# (docs/plans/gateb_evidence_grade_redesign_2026-08-17.md §7-C: 각 경로가 의도한 등급을
# 받는지 고정). §1-B 표의 match=True 경로 1~9 를 전부 커버하지는 않지만(항등식 3종은
# 전부 E4_IDENTITY 로 같은 등급이라 하나만 대표), 각기 다른 *등급*을 만드는 코드 분기는
# 전부 덮는다: 정확일치/부호반전/반올림관용/항등식/휴리스틱(E1~E5) + 불일치(M1/M2).

def test_evidence_exact_match_is_e1_exact():
    line = _bs_line("bs.total_assets", 1000)
    ra = audit_std_row({"total_assets": 1000}, basis="consolidated", bs_face=[line],
                       is_face=[], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.fields[0].evidence == EVIDENCE_E1_EXACT


def test_evidence_sign_flip_is_e2_sign():
    is_line = FaceLine(statement="IS", basis="separate", acode="매출원가", canonical="is.cogs",
                       label="매출원가", displayed_value=-27747335376, adecimal=0)
    ra = audit_std_row({"cogs": 27747335376}, basis="separate", bs_face=[], is_face=[is_line],
                       cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.fields[0].evidence == EVIDENCE_E2_SIGN


def test_evidence_rounding_tolerance_is_e3_rounding():
    ra = audit_std_row({"total_assets": 1_234_000}, basis="consolidated",
                       bs_face=[_bs_line("bs.total_assets", 1235, ade=-3)],
                       is_face=[], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.fields[0].evidence == EVIDENCE_E3_ROUNDING


def test_evidence_net_income_identity_is_e4_identity():
    # 지배+비지배 귀속 합으로 복원 대조(±1 관용 경로 안의 항등식 서브분기).
    is_face = [_bs_line("is.net_income", -502_592_034),
               _bs_line("is.controlling_ni", -1_903_963_591),
               _bs_line("is.noncontrolling_ni", -3_177_661)]
    ra = audit_std_row({"net_income": -1_907_141_252}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    ni = next(f for f in ra.fields if f.field == "net_income")
    assert ni.evidence == EVIDENCE_E4_IDENTITY


def test_evidence_revenue_cogs_gp_identity_is_e4_identity():
    # cands 없음(is.revenue 라인 자체가 face 에 없음) 분기의 항등식 서브분기.
    is_face = [_bs_line("is.cogs", 800), _bs_line("is.gross_profit", 200)]
    ra = audit_std_row({"revenue": 1000}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.fields[0].evidence == EVIDENCE_E4_IDENTITY


def test_evidence_gapfill_exact_candidate_is_e5_heuristic():
    # 유일한 후보가 from_gapfill(텍스트 보충, 휴리스틱)인 채로 정확 일치 → 등급은 E5, PASS는 유지.
    line = FaceLine(statement="IS", basis="consolidated", acode="x", canonical="is.revenue",
                    label="x", displayed_value=5000, adecimal=0, from_gapfill=True)
    ra = audit_std_row({"revenue": 5000}, basis="consolidated",
                       bs_face=[], is_face=[line], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.fields[0].evidence == EVIDENCE_E5_HEURISTIC


def test_evidence_gapfill_rounding_candidate_is_e5_heuristic():
    # 반올림 관용(±1)으로 매칭됐지만 그 후보가 gapfill → E3(관용)이 아니라 E5(휴리스틱).
    line = FaceLine(statement="BS", basis="consolidated", acode="x", canonical="bs.total_assets",
                    label="x", displayed_value=1235, adecimal=-3, from_gapfill=True)
    ra = audit_std_row({"total_assets": 1_234_000}, basis="consolidated", bs_face=[line],
                       is_face=[], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.fields[0].evidence == EVIDENCE_E5_HEURISTIC


def test_evidence_mismatch_nongapfill_nearest_is_m1_strong():
    line = _bs_line("bs.total_assets", 1000)  # non-gapfill, |1000-900|=100 > tol
    ra = audit_std_row({"total_assets": 900}, basis="consolidated", bs_face=[line],
                       is_face=[], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_FAIL
    assert ra.fields[0].evidence == EVIDENCE_M1_STRONG


def test_evidence_mismatch_gapfill_nearest_is_m2_weak():
    # 후보가 gapfill/non-gapfill 섞여 있고(→ GAPFILL_UNVERIFIED 로 안 빠짐), 최근접이 gapfill.
    far_nongapfill = _bs_line("bs.total_assets", 100_000)
    near_gapfill = FaceLine(statement="BS", basis="consolidated", acode="x",
                            canonical="bs.total_assets", label="x", displayed_value=950,
                            adecimal=0, from_gapfill=True)
    ra = audit_std_row({"total_assets": 900}, basis="consolidated",
                       bs_face=[far_nongapfill, near_gapfill], is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_FAIL
    assert ra.fields[0].evidence == EVIDENCE_M2_WEAK


def test_evidence_grade_exclusivity():
    # §7-B: pass/fail(VALUE_DIFF) 필드는 정확히 하나의 등급을 받고, pending 필드는 등급이 없다.
    db = {"total_assets": 1000, "cogs": 900, "cfo": 500}
    bs = [_bs_line("bs.total_assets", 1000)]      # pass -> E1
    is_face = [_bs_line("is.cogs", 800)]           # |900-800|=100>tol -> M1
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=is_face, cf_face=[],
                       is_comparative=False)        # cfo: cf_face 비어있음 -> pending
    graded = {f.field: f.evidence for f in ra.fields if f.evidence is not None}
    assert graded == {"total_assets": EVIDENCE_E1_EXACT, "cogs": EVIDENCE_M1_STRONG}
    cfo = next(f for f in ra.fields if f.field == "cfo")
    assert cfo.evidence is None and cfo.reason == "SOURCE_NOT_TRACK_A"


def _run():
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
