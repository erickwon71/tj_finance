"""`fin2/extract/review_csv.py` 순수 로직 단위 테스트(DB 비의존).

검토 CSV 는 사용자가 DART 원문과 **자릿수까지 그대로** 비교하는 물건이라, 금액 환산과
행 순서가 틀리면 캠페인 전체가 무의미해진다. 그 두 가지를 여기서 고정한다.

실행: pytest fin2/tests/test_review_csv.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit.layer2_selfcheck import CheckResult, GRADE_BLOCKING  # noqa: E402
from fin2.extract import review_csv as rc  # noqa: E402


def row(stmt, basis, label, won, *, seq=0, order=0, depth=0, adecimal=-6,
        unit_source="declared", value_raw=None, currency=None, header_hint=None,
        declared_unit=None):
    return {"statement": stmt, "basis": basis, "table_seq": seq, "row_order": order,
            "depth": depth, "node_role": None, "section_path": None,
            "label_raw": label, "value_won": won, "value_raw": value_raw,
            "adecimal": adecimal, "unit_source": unit_source, "header_hint": header_hint,
            "unit_decl_raw": None, "declared_unit": declared_unit, "currency": currency,
            "table_title": None}


# ── 금액 환산 ────────────────────────────────────────────────────────────────
def test_amount_is_printed_as_in_the_report():
    """원문이 백만원으로 인쇄됐으면 CSV 도 백만원 숫자여야 한다(= value_won × 10^adecimal)."""
    out = rc.build_rows([row("BS", "separate", "유동자산", 207_955_077_000_000, adecimal=-6)])
    assert out[0][5] == 207_955_077
    assert out[0][1] == "백만원"


def test_unit_label_comes_from_row_adecimal_not_table_declared_unit():
    """★`report_tables.declared_unit` 은 IS 에서 EPS 행 때문에 1(원)로 오염된다
    (`store_report_tables` 가 표의 첫 행 adecimal 로 유도). 그걸 찍으면 '금액은 백만원인데
    단위는 원'이라고 적혀 사용자를 정확히 틀리게 안내한다."""
    out = rc.build_rows([row("IS", "separate", "매출액", 258_550_894_000_000,
                             adecimal=-6, declared_unit=1)])
    assert out[0][1] == "백만원" and out[0][5] == 258_550_894


def test_eps_row_keeps_won_unit_in_the_same_statement():
    out = rc.build_rows([
        row("IS", "separate", "매출액", 258_550_894_000_000, order=1, adecimal=-6),
        row("IS", "separate", "기본주당이익(손실)", 10_211, order=2, adecimal=0)])
    assert [(r[1], r[5]) for r in out] == [("백만원", 258_550_894), ("원", 10_211)]


def test_null_value_falls_back_to_value_raw_and_leaves_amount_blank():
    """R4 의 NULL 규약 — 단위 미확정은 유실이지 오염이 아니다. 지어내지 않고 원문만 보인다."""
    out = rc.build_rows([row("BS", "separate", "기타자산", None, adecimal=None,
                             unit_source="undetermined", value_raw="1,234")])
    assert out[0][5] == "" and out[0][6] == "1,234"
    assert out[0][1] == "", "단위를 모르면 단위 칸도 비운다"


def test_fx_declared_is_not_converted_and_shows_currency():
    out = rc.build_rows([row("BS", "separate", "Cash", 1_500, adecimal=0,
                             unit_source="fx_declared", currency="USD")])
    assert out[0][1] == "USD" and out[0][5] == 1_500
    assert "표시통화" in out[0][7]


def test_header_hint_rows_are_shown_not_hidden():
    """계층3 는 거르지만(R5) 원문에는 인쇄된 행이므로 대조 대상이다."""
    out = rc.build_rows([row("BS", "separate", "제 55 기 반기말", 0, header_hint="기간라벨")])
    assert len(out) == 1 and "header_hint:기간라벨" in out[0][7]


# ── 순서 ─────────────────────────────────────────────────────────────────────
def test_scope_order_is_separate_then_consolidated_bs_is_cf():
    rows = [row("CF", "consolidated", "c-cf", 1), row("BS", "consolidated", "c-bs", 1),
            row("IS", "separate", "s-is", 1), row("CF", "separate", "s-cf", 1),
            row("BS", "separate", "s-bs", 1), row("IS", "consolidated", "c-is", 1)]
    assert [r[4] for r in rc.build_rows(rows)] == [
        "s-bs", "s-is", "s-cf", "c-bs", "c-is", "c-cf"]


def test_consolidated_absent_yields_separate_only():
    rows = [row("BS", "separate", "s-bs", 1), row("IS", "separate", "s-is", 1)]
    labels = {r[0] for r in rc.build_rows(rows)}
    assert labels == {"[별도] 재무상태표", "[별도] 손익계산서"}


def test_row_order_follows_table_seq_then_row_order():
    """2표식(손익계산서+포괄손익계산서)에서 row_order 가 표마다 0 부터 다시 시작한다."""
    rows = [row("IS", "separate", "포괄-1", 1, seq=1, order=1),
            row("IS", "separate", "손익-2", 1, seq=0, order=2),
            row("IS", "separate", "손익-1", 1, seq=0, order=1)]
    assert [r[4] for r in rc.build_rows(rows)] == ["손익-1", "손익-2", "포괄-1"]


def test_sequence_column_restarts_per_scope():
    rows = [row("BS", "separate", "a", 1, order=1), row("BS", "separate", "b", 1, order=2),
            row("IS", "separate", "c", 1, order=1)]
    assert [(r[0], r[2]) for r in rc.build_rows(rows)] == [
        ("[별도] 재무상태표", 1), ("[별도] 재무상태표", 2), ("[별도] 손익계산서", 1)]


# ── 경로 / 프리앰블 ──────────────────────────────────────────────────────────
def test_csv_path_mirrors_raw_report_tree():
    p = rc.csv_path_for(market="KOSPI", corp_code="00126380", corp_name="삼성전자",
                        report_type="half", fiscal_year=2026, rcept_no="20260814003699",
                        root=Path("layer2_review"))
    assert p == Path("layer2_review/KOSPI/00126380_삼성전자/half/2026/"
                     "20260814003699_review.csv")


def test_csv_path_sanitises_corp_name():
    p = rc.csv_path_for(market=None, corp_code="00000001", corp_name="A/B:C",
                        report_type=None, fiscal_year=None, rcept_no="1", root=Path("r"))
    assert p == Path("r/UNKNOWN/00000001_A_B_C/unknown/unknown/1_review.csv")


def test_rcept_no_is_wrapped_against_excel_scientific_notation():
    """엑셀이 14자리 접수번호를 2.02E+13 으로 바꿔버리는 것을 막는다."""
    from fin2.extract.manual_report_lines import unwrap_excel_text
    wrapped = rc.excel_text("20260814003699")
    assert wrapped == '="20260814003699"'
    assert unwrap_excel_text(wrapped) == "20260814003699"


def test_preamble_carries_dart_link_and_checks():
    pre = rc.build_preamble(
        corp_name="삼성전자", corp_code="00126380", market="KOSPI", corp_rank=1,
        report_nm="반기보고서", fiscal_year=2026, fiscal_period="H1",
        rcept_no="20260814003699", filed_at=date(2026, 8, 14), source_kind="xml",
        reloaded_at=datetime(2026, 9, 9, 0, 0, 0),
        checks=[CheckResult("bs_balance", "[별도] 재무상태표", GRADE_BLOCKING, "FAIL", "차 1원")],
        counts={"separate": {"BS": 43, "IS": 21, "CF": 31}})
    flat = ["|".join(str(c) for c in line) for line in pre]
    assert any("dsaf001/main.do?rcpNo=20260814003699" in l for l in flat)
    assert any("bs_balance" in l and "FAIL" in l for l in flat)
    assert all(line[0].startswith("#") for line in pre), "프리앰블은 모두 # 로 시작한다"


def test_preamble_warns_on_pdf_recovery_source():
    pre = rc.build_preamble(
        corp_name="X", corp_code="1", market=None, corp_rank=None, report_nm=None,
        fiscal_year=2002, fiscal_period="H1", rcept_no="2", filed_at=None,
        source_kind="pdf", reloaded_at=datetime(2026, 9, 9), checks=[], counts={})
    assert any("PDF/HTML 복구 경로" in "|".join(map(str, line)) for line in pre)


def test_scope_counts_only_counts_body_statements():
    rows = [row("BS", "separate", "a", 1), row("SCE", "separate", "b", 1),
            row("IS", "consolidated", "c", 1)]
    assert rc.scope_counts(rows) == {"separate": {"BS": 1}, "consolidated": {"IS": 1}}
