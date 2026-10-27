"""R286 - a statement the filing does not print is filled in layer 3 from the donor's prior-year column."""
import json
from types import SimpleNamespace

import pytest

from fin2.extract import cross_filing_fill as X


def _line(statement, basis, col, ctx, value, label="영업활동현금흐름", row=1):
    return SimpleNamespace(
        statement=statement, basis=basis, col_index=col, context_fiscal_year=ctx, value_won=value,
        label_raw=label, row_order=row, table_seq=0, is_cumulative=True, period_kind="duration", col_label="",
        source_ref="ref", as_row=lambda: {"corp_code": "c", "rcept_no": "donor", "report_fiscal_year": 2017,
                                          "report_fiscal_period": "H1", "statement": statement, "basis": basis,
                                          "col_index": col, "table_title": "t", "parsed_at": "x",
                                          "context_fiscal_year": ctx, "value_won": value, "source_ref": "ref"})


@pytest.fixture
def listed(monkeypatch):
    monkeypatch.setitem(X.CROSS_FILING_FILLS, "target", (("CF", "separate", "donor"),))


def test_fill_takes_the_prior_year_column_as_current_period(listed):
    donor = [_line("CF", "separate", 0, 2017, 111), _line("CF", "separate", 1, 2016, 222)]
    out = X.cross_filing_fill_corrections("target", [], report_fiscal_year=2016, report_fiscal_period="H1",
                                          donor_lines=lambda r: donor)
    assert len(out) == 1
    c = out[0]
    assert (c["kind"], c["rule"], c["col_index"], c["corrected_value"], c["printed_value"]) == \
        ("fill", "R286_cross_filing_fill", 0, 222, None)
    row = json.loads(c["row_data"])
    assert row["rcept_no"] == "target" and row["report_fiscal_year"] == 2016 and row["report_fiscal_period"] == "H1"
    assert row["col_index"] == 0 and row["source_ref"].startswith("xfill:donor;")
    assert "table_title" not in row and "parsed_at" not in row


def test_nothing_is_filled_when_layer_two_has_the_statement(listed):
    printed = [_line("CF", "separate", 0, 2016, 5)]
    out = X.cross_filing_fill_corrections("target", printed, report_fiscal_year=2016, report_fiscal_period="H1",
                                          donor_lines=lambda r: [_line("CF", "separate", 1, 2016, 9)])
    assert out == []


def test_donor_comparative_of_another_year_stops_the_fill(listed):
    with pytest.raises(ValueError):
        X.cross_filing_fill_corrections("target", [], report_fiscal_year=2016, report_fiscal_period="H1",
                                        donor_lines=lambda r: [_line("CF", "separate", 1, 2015, 9)])


def test_unlisted_filing_and_blank_donor_cells_give_nothing(listed):
    assert X.cross_filing_fill_corrections("other", [], report_fiscal_year=2016, report_fiscal_period="H1",
                                           donor_lines=lambda r: 1 / 0) == []
    out = X.cross_filing_fill_corrections("target", [], report_fiscal_year=2016, report_fiscal_period="H1",
                                          donor_lines=lambda r: [_line("CF", "separate", 1, 2016, None)])
    assert out == []


def test_registered_pairs_are_well_formed():
    for target, entries in X.CROSS_FILING_FILLS.items():
        assert len(target) == 14 and entries
        for statement, basis, donor in entries:
            assert statement in ("BS", "IS", "CF") and basis in ("consolidated", "separate") and len(donor) == 14
            assert donor > target       # the donor is the later report
