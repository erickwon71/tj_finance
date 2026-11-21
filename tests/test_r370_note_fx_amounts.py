"""R370 - foreign-currency amounts of note cells (fin2/extract/fx_amounts.py)."""
from decimal import Decimal

from fin2.extract.fx_amounts import declared_scale_for, extract_fx_cell


def _one(raw, label="x", col="당기말", decl=None):
    return extract_fx_cell(raw, label=label, col_label=col, declaration=decl)


def test_cell_prefix_code():
    r = _one("USD 2,364,000")
    assert [(x.currency, x.amount_printed, x.evidence) for x in r] == [("USD", Decimal("2364000"), "cell_code")]


def test_won_first_line_then_foreign_tail_keeps_only_foreign():
    r = _one("67,293,600USD 2,364,000")
    assert [(x.currency, x.amount_printed) for x in r] == [("USD", Decimal("2364000"))]
    r = _one("5,789,000 (USD 5,000,000)")
    assert [(x.currency, x.amount_printed) for x in r] == [("USD", Decimal("5000000"))]


def test_two_currencies_in_one_cell_keep_order():
    r = _one("9,933,496&cr;EUR   3,105,815.14&cr;USD      391,053.40")
    assert [(x.seq, x.currency, x.amount_printed) for x in r] == [
        (0, "EUR", Decimal("3105815.14")), (1, "USD", Decimal("391053.40"))]


def test_us_dollar_sign_and_jpy_code_together():
    r = _one("103,080,000US$2,000,000JPY50,000,000")
    assert [(x.currency, x.amount_printed) for x in r] == [("USD", Decimal("2000000")), ("JPY", Decimal("50000000"))]


def test_symbol_evidence_and_unsupported_yen_sign_read_past():
    r = _one("(￥179,312,180) ($4,294,383.44)")
    assert [(x.currency, x.evidence) for x in r] == [("USD", "cell_symbol")]


def test_rmb_is_cny_and_unsupported_code_not_stored():
    assert [x.currency for x in _one("RMB 10,000,000")] == ["CNY"]
    assert _one("SGD 9,000") == []


def test_sentence_cell_is_not_read():
    assert _one("USD 1,000 상당의 계약") == []


def test_three_decimal_number_unresolved():
    assert _one("USD 125.605") == []


def test_negative_forms():
    assert _one("USD (5,000)")[0].amount_printed == Decimal("-5000")
    assert _one("-USD 5,000")[0].amount_printed == Decimal("-5000")
    assert _one("(USD 5,000)")[0].amount_printed == Decimal("5000")       # wrapper, not a sign


def test_header_foreign_with_code():
    r = _one("(1,124,765)", col="(단위 : 원)>전기말>외화금액(USD)")
    assert [(x.currency, x.amount_printed, x.evidence) for x in r] == [("USD", Decimal("-1124765"), "header_foreign")]


def test_row_code_under_foreign_amount_header():
    r = _one("438,006,990", label="JPY", col="당기말>외화금액")
    assert [(x.currency, x.evidence) for x in r] == [("JPY", "row_code")]
    r = _one("154,631,841", label="외화표시화폐성부채>USD", col="당기말>외화금액")
    assert [(x.currency, x.evidence) for x in r] == [("USD", "row_code")]


def test_row_code_without_foreign_header_is_not_enough():
    assert _one("1,000", label="USD", col="당기말") == []


def test_header_and_row_naming_different_codes_is_skipped():
    assert _one("1,000", label="JPY", col="당기말>외화금액(USD)") == []


def test_won_equivalent_row_and_column_are_skipped():
    assert _one("88,883,844", label="원화환산액", col="(원화단위: 천원)>USD") == []
    assert _one("1,000", label="x", col="원화환산액(USD)") == []


def test_bare_code_header_evidence_levels():
    r = _one("75,839,457", label="외화자산>외화금액", col="(원화단위: 천원)>USD")
    assert r[0].evidence == "row_foreign"
    r = _one("153,532", label="현금및현금성자산", col="당기말>USD")
    assert r[0].evidence == "header_code_only"


def test_two_codes_in_header_are_skipped():
    assert _one("1,000", label="x", col="외화금액(USD/EUR)") == []


def test_declared_scale_per_currency():
    d = "(단위 : 천USD, 천JPY, 천EUR, 백만원)"
    assert declared_scale_for("USD", d) == 1000
    assert declared_scale_for("JPY", d) == 1000
    assert declared_scale_for("CNY", d) is None
    assert declared_scale_for("USD", "(단위: USD, EUR, 천원)") == 1
    assert declared_scale_for("USD", "(단위: 백만원, 천달러, 천엔, 천유로)") == 1000
    assert declared_scale_for("USD", "(단위 : 천, USD)") == 1000
    assert declared_scale_for("USD", "(단위: 천원)") is None


def test_scale_is_attached_to_header_based_amount():
    r = _one("7,316", label="단기차입금", col="(단위 : 천USD, 천JPY, 천EUR, 백만원)>당기말>외화금액(USD)")
    assert r[0].declared_scale == 1000 and r[0].amount_printed == Decimal("7316")   # printed, not multiplied


def test_exchange_rate_and_sensitivity_rows_are_skipped():
    assert _one("1,150.20", label="적용환율", col="당기말>USD") == []
    assert _one("1,000", label="외화환율 10% 상승", col="당기말>외화금액(USD)") == []
    assert _one("1,000", label="x", col="환율민감도>USD") == []


class _FakeSession:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))


def test_store_none_leaves_rows_empty_list_clears_rows_are_replaced():
    from decimal import Decimal as D
    from fin2.extract.fx_amounts import FxAmount, NoteFxRow
    from fin2.extract.report_lines import store_note_fx_amounts

    s = _FakeSession()
    assert store_note_fx_amounts(s, "20200101000001", None) == 0
    assert s.calls == []                                    # not read -> untouched
    s = _FakeSession()
    assert store_note_fx_amounts(s, "20200101000001", []) == 0
    assert len(s.calls) == 1 and s.calls[0][0].startswith("DELETE FROM note_fx_amounts")

    s = _FakeSession()
    row = NoteFxRow("00000001", "20200101000001", 2019, "FY", "consolidated", 3, 4, 1,
                    FxAmount(0, "USD", D("5.50"), "cell_code", 1000, "USD 5.50"))
    assert store_note_fx_amounts(s, "20200101000001", [row]) == 1
    assert s.calls[1][1][0]["amount_printed"] == D("5.50") and s.calls[1][1][0]["declared_scale"] == 1000
