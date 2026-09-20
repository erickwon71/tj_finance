"""`fin2/audit/layer2_selfcheck.py` 순수 로직 단위 테스트(DB 비의존).

★여기 고정된 케이스는 대부분 **표본 스윕에서 실제로 나온 거짓양성**이다(2026-09-09,
검산 민감도 검증). 검산의 가치는 "깨진 걸 잡는다"보다 "안 깨진 걸 안 잡는다"에 더 크게
달려 있다 — 사람이 원문을 다시 여는 비용이 이 도구의 유일한 비용이기 때문. 그래서
거짓양성 패턴 하나하나를 회귀로 박아둔다.

실행: pytest fin2/tests/test_layer2_selfcheck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit import layer2_selfcheck as sc  # noqa: E402


def row(stmt, basis, label, won, *, seq=0, order=0, depth=0, adecimal=0,
        section_path=None, unit_source="declared", value_raw=None, currency=None):
    """기본 단위는 **원**(adecimal=0) — 그래야 반올림 허용오차가 2원이라 테스트가
    작은 숫자로도 FAIL 을 만들 수 있다. 허용오차 자체를 보는 테스트만 adecimal=-6 을 준다."""
    return {"statement": stmt, "basis": basis, "table_seq": seq, "row_order": order,
            "depth": depth, "node_role": None, "section_path": section_path,
            "label_raw": label, "value_won": won, "value_raw": value_raw,
            "adecimal": adecimal, "unit_source": unit_source, "header_hint": None,
            "unit_decl_raw": None, "declared_unit": None, "currency": currency,
            "table_title": None}


def verdicts(results, code):
    return [r.verdict for r in results if r.code == code]


# ── bs_balance ───────────────────────────────────────────────────────────────
def test_bs_balance_pass():
    rows = [row("BS", "separate", "자산총계", 300, order=1),
            row("BS", "separate", "부채총계", 100, order=2),
            row("BS", "separate", "자본총계", 200, order=3)]
    assert verdicts(sc.check_bs_balance(rows), "bs_balance") == ["PASS"]


def test_bs_balance_fail():
    rows = [row("BS", "separate", "자산총계", 300, order=1),
            row("BS", "separate", "부채총계", 100, order=2),
            row("BS", "separate", "자본총계", 150, order=3)]
    assert verdicts(sc.check_bs_balance(rows), "bs_balance") == ["FAIL"]


def test_bs_balance_uses_combined_label_when_split_absent():
    """'부채와자본총계' 하나만 쓰는 서식."""
    rows = [row("BS", "separate", "자산총계", 300, order=1),
            row("BS", "separate", "부채와자본총계", 300, order=2)]
    assert verdicts(sc.check_bs_balance(rows), "bs_balance") == ["PASS"]


def test_bs_balance_na_when_anchor_missing():
    """R6 — 근거 라벨이 없으면 FAIL 이 아니라 판정불가."""
    rows = [row("BS", "separate", "유동자산", 100, order=1)]
    assert verdicts(sc.check_bs_balance(rows), "bs_balance") == ["NA"]


def test_bs_balance_na_when_same_label_has_conflicting_values():
    """동명 총계가 서로 다른 값이면 고르지 않는다(R6)."""
    rows = [row("BS", "separate", "자산총계", 300, order=1),
            row("BS", "separate", "자산총계", 999, order=5),
            row("BS", "separate", "부채총계", 100, order=2),
            row("BS", "separate", "자본총계", 200, order=3)]
    assert verdicts(sc.check_bs_balance(rows), "bs_balance") == ["NA"]


def test_bs_balance_tolerates_display_unit_rounding():
    """백만원 단위로 반올림 인쇄된 원문은 총계가 몇 백만원 어긋날 수 있다 — 원문이 그런 것."""
    rows = [row("BS", "separate", "자산총계", 300_000_000, order=1, adecimal=-6),
            row("BS", "separate", "부채총계", 100_000_000, order=2, adecimal=-6),
            row("BS", "separate", "자본총계", 201_000_000, order=3, adecimal=-6)]
    assert verdicts(sc.check_bs_balance(rows), "bs_balance") == ["PASS"]


# ── unit_sanity ──────────────────────────────────────────────────────────────
def test_unit_sanity_allows_mixed_units_within_a_statement():
    """★거짓양성 회귀 — 삼성전자 20260814003699.

    IS 는 본문이 백만원(adecimal=-6), EPS 행이 원(adecimal=0)이다. 실제 서식이
    '(단위: 백만원, 주당손익: 원)' 이고 R4 자체가 단위를 **열 단위**로 판정한다.
    이걸 '단위 혼재'로 FAIL 내면 정상 보고서의 대부분이 걸린다.
    """
    rows = [row("IS", "separate", "매출액", 258_550_894_000_000, order=1, adecimal=-6),
            row("IS", "separate", "기본주당이익(손실) (단위 : 원)", 10_211, order=2, adecimal=0)]
    assert verdicts(sc.check_unit_sanity(rows), "unit_sanity") == ["PASS"]


def test_unit_sanity_flags_undetermined_rows():
    rows = [row("BS", "separate", "자산총계", 300, order=1),
            row("BS", "separate", "기타자산", None, order=2, adecimal=None,
                unit_source="undetermined", value_raw="1,234")]
    assert verdicts(sc.check_unit_sanity(rows), "unit_sanity") == ["FAIL"]


# ── duplicate_rows ───────────────────────────────────────────────────────────
def test_duplicate_rows_allows_same_label_at_different_positions():
    """★거짓양성 회귀 — 20140530001276.

    '매도가능금융자산' 300,000,000 이 유동/비유동에 각각 인쇄된다. 계층2 는 위치가 다르면
    다른 행으로 두는 것이 설계이므로(`models.ReportLine` docstring) 중복이 아니다.
    """
    rows = [row("BS", "separate", "매도가능금융자산", 300_000_000, order=5,
                section_path="자산>유동자산"),
            row("BS", "separate", "매도가능금융자산", 300_000_000, order=16,
                section_path="자산>비유동자산")]
    assert verdicts(sc.check_duplicate_rows(rows), "duplicate_rows") == ["PASS"]


def test_duplicate_rows_catches_real_double_append():
    """진짜 이중 append 는 표가 통째로 반복돼 section_path 까지 같다(R4-2 함정)."""
    rows = [row("BS", "separate", "유동자산", 100, order=1, section_path="자산"),
            row("BS", "separate", "유동자산", 100, order=9, section_path="자산")]
    assert verdicts(sc.check_duplicate_rows(rows), "duplicate_rows") == ["FAIL"]


# ── cf_closing_cash ──────────────────────────────────────────────────────────
def _cf(*specs):
    return [row("CF", "separate", label, won, order=i)
            for i, (label, won) in enumerate(specs, start=1)]


def test_cf_net_change_identity_with_fx_already_included():
    """★삼성전자형 — 순증감 소계가 이미 '환율변동 효과 적용 후' 다.

    소계 **앞**에 있는 '외화환산으로 인한 현금의 변동' 은 이미 소계에 포함돼 있으므로
    또 더하면 안 된다.
    """
    rows = _cf(("영업활동현금흐름", 40), ("투자활동현금흐름", -10),
               ("재무활동현금흐름", -30),
               ("외화환산으로 인한 현금의 변동", -1),
               ("환율변동 효과 적용 후 현금및현금성자산의 증가(감소)", 3_180_600_000_000),
               ("기초현금및현금성자산", 12_581_632_000_000),
               ("반기말의 현금및현금성자산", 15_762_232_000_000))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["PASS"]


def test_cf_net_change_identity_adds_fx_printed_after_subtotal():
    """★거짓양성 회귀 — 20201116002012 / 20260813001767.

    순증감 소계가 **환율효과 반영 전**이고, 환율효과가 소계와 기말 사이에 따로 찍힌 서식.
    (기초가 그 사이에 끼는 배치도 있어 상한은 기말 위치로 잡는다.)
    """
    rows = _cf(("현금및현금성자산의순증가(감소)", 137_203_898_133),
               ("기초현금및현금성자산", 177_672_685_267),
               ("외화표시 현금및현금성자산의 환율변동 효과", 168_315_729),
               ("기말현금및현금성자산", 315_044_899_129))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["PASS"]


def test_cf_ignores_causal_adjustment_rows_as_net_change():
    """★거짓양성 회귀 — 20220516002148 / 20251114002182.

    '외화환산으로 인한 현금의 증감'·'연결범위 변동에 따른 현금감소분' 은 조정행이지
    총증감 소계가 아니다. 이걸 소계로 오인하면 그 금액만큼 어긋난 FAIL 이 난다.
    여기서는 소계가 아예 없으므로 성분합 폴백(의심 등급)으로 내려가야 한다.
    """
    rows = _cf(("영업활동현금흐름", 100), ("투자활동현금흐름", -40),
               ("재무활동현금흐름", -20),
               ("외화환산으로 인한 현금의 증감", 0),
               ("기초의 현금및현금성자산", 1_000),
               ("기말의 현금및현금성자산", 1_040))
    res = [r for r in sc.check_cf_closing_cash(rows) if r.code == "cf_closing_cash"]
    assert [r.verdict for r in res] == ["PASS"]
    assert res[0].grade == sc.GRADE_SUSPECT, "소계 없는 성분합 폴백은 의심 등급으로 낮춘다"


def test_cf_component_fallback_is_suspect_grade_not_blocking():
    rows = _cf(("영업활동현금흐름", 100), ("투자활동현금흐름", -40),
               ("재무활동현금흐름", -20),
               ("기초의 현금", 1_000), ("기말의 현금", 9_999))
    res = [r for r in sc.check_cf_closing_cash(rows) if r.code == "cf_closing_cash"]
    assert res[0].verdict == "FAIL" and res[0].grade == sc.GRADE_SUSPECT


def test_cf_na_when_opening_or_closing_missing():
    rows = _cf(("영업활동현금흐름", 100))
    res = [r for r in sc.check_cf_closing_cash(rows) if r.code == "cf_closing_cash"]
    assert [r.verdict for r in res] == ["NA"]


def test_cf_net_change_identity_adds_held_for_sale_reclass_after_subtotal():
    """★거짓양성 회귀 — SK스퀘어 20260514001477(연결, 2026-09-12 발견).

    순증감 소계와 기말 사이에 환율효과 **와** IFRS5 매각예정(처분자산군) 현금
    재분류행이 나란히 인쇄되는 서식. 재분류행을 안 더하면 정확히 그 금액만큼
    어긋난 거짓 FAIL 이 난다.
    """
    rows = _cf(("현금및현금성자산의 순증감", -160_570),
               ("기초현금및현금성자산", 1_310_718),
               ("외화표시 현금및현금성자산의 환율변동효과", 13_003),
               ("매각예정자산에 포함된 현금및현금성자산", 50_934),
               ("분기말의 현금및현금성자산", 1_214_085))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["PASS"]


def test_cf_closing_label_variants_are_recognised():
    """'반기말의'·'분기말의' 접두가 붙어도 기말 잔액이다(초기 구현이 여기서 판정불가를 냈다)."""
    for closing in ("반기말의 현금및현금성자산", "분기말의 현금및현금성자산",
                    "기말현금및현금성자산", "현금및현금성자산의 기말잔액"):
        rows = _cf(("현금및현금성자산의 증감", 40),
                   ("기초의 현금및현금성자산", 1_000), (closing, 1_040))
        res = [r for r in sc.check_cf_closing_cash(rows) if r.code == "cf_closing_cash"]
        assert [r.verdict for r in res] == ["PASS"], closing


# ── scope_presence ───────────────────────────────────────────────────────────
def test_scope_presence_na_without_siblings():
    rows = [row("BS", "separate", "자산총계", 1)]
    assert verdicts(sc.check_scope_presence(rows, None), "scope_presence") == ["NA"]


def test_scope_presence_pass_when_matching_siblings():
    rows = [row("BS", "separate", "자산총계", 1), row("IS", "separate", "매출액", 1)]
    expected = {("BS", "separate"), ("IS", "separate")}
    assert verdicts(sc.check_scope_presence(rows, expected), "scope_presence") == ["PASS"]


def test_scope_presence_fail_when_sibling_scope_missing():
    rows = [row("IS", "separate", "매출액", 1)]
    expected = {("BS", "separate"), ("IS", "separate")}
    assert verdicts(sc.check_scope_presence(rows, expected), "scope_presence") == ["FAIL"]


# ── row_unit / rollup ────────────────────────────────────────────────────────
def test_row_unit_from_adecimal_not_declared_unit():
    """★`report_tables.declared_unit` 을 믿지 않는다 — IS 는 EPS 행 때문에 1(원)로 잘못 적힌다."""
    r = row("IS", "separate", "매출액", 1, adecimal=-6)
    r["declared_unit"] = 1          # 오염된 표 단위
    assert sc.row_unit(r) == 1_000_000


def test_rollup_only_blocking_grade_drives_suspect():
    ok = [sc.CheckResult("bs_balance", "s", sc.GRADE_BLOCKING, "PASS", "")]
    noisy = ok + [sc.CheckResult("row_count_outlier", "s", sc.GRADE_SUSPECT, "FAIL", "")]
    assert sc.rollup(ok) == "ok"
    assert sc.rollup(noisy) == "ok", "의심 등급은 롤업을 suspect 로 만들지 않는다"
    bad = [sc.CheckResult("bs_balance", "s", sc.GRADE_BLOCKING, "FAIL", "")]
    assert sc.rollup(bad) == "suspect"
    assert sc.rollup([sc.CheckResult("bs_balance", "s", sc.GRADE_BLOCKING, "NA", "")]) == "na"


# ── 2026-09-20 캠페인 거짓양성 일괄 회귀 ─────────────────────────────────────
# 근거: docs/qa/layer2_review_campaign_issues_2026-09-20.md 이슈 3~8·17~19·21~22.
# 셋 다 "원문 서식 변형을 검산식이 못 따라간" 것이고 파서 결함은 하나도 없었다.


def test_is_waterfall_accepts_cogs_stored_negative():
    """★거짓양성 회귀 — POSCO홀딩스 20251114002479 / LG화학 20240315000957 등.

    원문이 매출원가를 괄호(음수)로 인쇄하면 `value_won` 이 음수로 적재된다. 이때
    `매출액 − 매출원가` 를 곧이곧대로 빼면 원가를 **더해** 버려 정확히 `2 × 매출원가`
    만큼 어긋난 FAIL 이 난다(이슈 3·6의 공통 서명).
    """
    rows = [row("IS", "separate", "매출액", 1_000, order=1),
            row("IS", "separate", "매출원가", -700, order=2),
            row("IS", "separate", "매출총이익", 300, order=3)]
    assert verdicts(sc.check_is_waterfall(rows), "is_waterfall") == ["PASS"]


def test_is_waterfall_still_catches_real_mismatch():
    rows = [row("IS", "separate", "매출액", 1_000, order=1),
            row("IS", "separate", "매출원가", -700, order=2),
            row("IS", "separate", "매출총이익", 250, order=3)]
    assert verdicts(sc.check_is_waterfall(rows), "is_waterfall") == ["FAIL"]


def test_bs_rollup_accepts_third_top_level_group():
    """★거짓양성 회귀 — HD한국조선해양 20170515004618.

    유동/비유동과 **나란히** '소유주분배예정자산집단' 이 인쇄되는 서식. 2항만 더하면
    딱 그 금액만큼 모자란 FAIL 이 난다.
    """
    rows = [row("BS", "separate", "유동자산", 100, order=1, depth=1, section_path="자산"),
            row("BS", "separate", "비유동자산", 200, order=2, depth=1, section_path="자산"),
            row("BS", "separate", "소유주분배예정자산집단", 50, order=3, depth=1,
                section_path="자산"),
            row("BS", "separate", "자산총계", 350, order=4, depth=1, section_path="자산")]
    assert verdicts(sc.check_bs_rollup(rows), "bs_rollup") == ["PASS"]


def test_bs_rollup_does_not_double_count_nested_held_for_sale():
    """'매각예정비유동자산' 이 **유동자산 안**에 들어간 서식은 더하면 이중계상이다.

    depth·section_path 가 유동자산과 다르므로 제3의 대분류로 줍지 않아야 한다.
    """
    rows = [row("BS", "separate", "유동자산", 100, order=1, depth=1, section_path="자산"),
            row("BS", "separate", "매각예정비유동자산", 30, order=2, depth=2,
                section_path="자산>유동자산"),
            row("BS", "separate", "비유동자산", 200, order=3, depth=1, section_path="자산"),
            row("BS", "separate", "자산총계", 300, order=4, depth=1, section_path="자산")]
    assert verdicts(sc.check_bs_rollup(rows), "bs_rollup") == ["PASS"]


def test_cf_net_change_identity_without_any_adjustment_row():
    """★거짓양성 회귀 — 레인보우로보틱스 20230323000602.

    환율효과 행이 소계와 기말 사이에 있어도 **소계에 이미 반영된** 서식이 있다.
    '무조건 더한다' 로 고정하면 그 금액만큼 어긋난다 — 안 더한 식이 먼저 맞으면 그걸 쓴다.
    """
    rows = _cf(("현금및현금성자산의 순증가", 40),
               ("기초 현금및현금성자산", 1_000),
               ("현금및현금성자산에 대한 환율변동효과", 7),
               ("기말 현금및현금성자산", 1_040))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["PASS"]


def test_cf_net_change_identity_adds_all_intermediate_rows():
    """★거짓양성 회귀 — 한국전력 20180515002408 / 대한항공 20201116001718 / LS 20190401004913.

    소계와 기말 사이에 환율효과 말고도 연결범위변동·대체 등 여러 조정행이 찍히는 서식.
    화이트리스트로 쫓지 말고 그 구간 전체를 더한 식도 후보로 둔다.
    """
    rows = _cf(("현금및현금성자산의 증가", 40),
               ("기초 현금및현금성자산", 1_000),
               ("외화환산으로 인한 현금의 변동", 7),
               ("연결범위 변동으로 인한 현금의 증가", 3),
               ("기말 현금및현금성자산", 1_050))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["PASS"]


def test_cf_adjustment_row_sign_can_live_in_the_label():
    """★거짓양성 회귀 — SK이노베이션 20250318000862 / HMM 20161114002386.

    '…의 감소' 행을 **양수 절대값**으로 인쇄하는 발행사가 있다(원문 확인:
    `ENG="Decrease in cash due to replacement of assets held for sale"` + `<P>9,137,925</P>`).
    라벨에 부호가 있으면 라벨을 따른다 — 단 '증감'·'증가' 가 함께 있으면 금액 부호를 믿는다.
    """
    rows = _cf(("현금및현금성자산의 증가", 40),
               ("기초 현금및현금성자산", 1_000),
               ("매각예정자산 대체로 인한 현금의 감소", 9),
               ("기말 현금및현금성자산", 1_031))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["PASS"]


def test_cf_still_fails_when_no_variant_balances():
    """세 식 어느 것도 안 맞으면 여전히 FAIL — 관대해진 것이지 꺼진 게 아니다."""
    rows = _cf(("현금및현금성자산의 증가", 40),
               ("기초 현금및현금성자산", 1_000),
               ("외화환산으로 인한 현금의 변동", 7),
               ("기말 현금및현금성자산", 5_000))
    assert verdicts(sc.check_cf_closing_cash(rows), "cf_closing_cash") == ["FAIL"]


def test_duplicate_rows_ignores_zero_and_null_values():
    """★거짓양성 회귀 — 값 0 인 행은 같은 표에서 얼마든지 반복된다(빈칸/해당없음).

    0 을 중복으로 세면 정상 보고서 대부분이 걸린다.
    """
    rows = [row("BS", "separate", "기타자본조정", 0, order=3, section_path="자본"),
            row("BS", "separate", "기타자본조정", 0, order=8, section_path="자본"),
            row("BS", "separate", "기타포괄손익누계액", None, order=9, section_path="자본")]
    assert verdicts(sc.check_duplicate_rows(rows), "duplicate_rows") == ["PASS"]


def test_duplicate_rows_message_reports_share_for_triage():
    """이슈 18(한진칼 20230515002432)은 **현재열만 적재**라 원문 라벨 반복과 진짜 이중
    append 를 구분할 수 없다 — 그래서 끄지 않고, 대신 '몇 행 중 몇 행' 을 메시지에 실어
    검토자가 즉시 분류할 수 있게 한다(진짜 이중 append 는 표가 통째로 반복된다).
    """
    rows = [row("BS", "separate", "유동자산", 100, order=1, section_path="자산"),
            row("BS", "separate", "유동자산", 100, order=9, section_path="자산"),
            row("BS", "separate", "비유동자산", 200, order=2, section_path="자산")]
    res = [r for r in sc.check_duplicate_rows(rows) if r.code == "duplicate_rows"]
    assert res[0].verdict == "FAIL"
    assert "3행" in res[0].message, res[0].message
