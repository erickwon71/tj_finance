"""R390 - an EPS row whose own label declares won keeps its printed value whatever its size."""
import glob

import pytest

from fin2.extract.report_lines import _eps_row_declares_won, extract_report_lines


def test_label_declares_won():
    assert _eps_row_declares_won("보통주 기본주당계속영업이익(손실)(단위:원) (단위 : 원)", "declared")
    assert not _eps_row_declares_won("기본주당이익", "declared")
    assert not _eps_row_declares_won("당기순이익 (단위 : 원)", "declared")
    assert not _eps_row_declares_won("기본주당이익 (단위 : 원)", "fx")


_FOUND = glob.glob("/Users/taejin/Project/tj_finance/raw_report/KOSPI/00131780_*/annual/2018/20190401003606.xml")


@pytest.mark.skipif(not _FOUND, reason="source file not on disk")
def test_sk_networks_2018_large_printed_eps_is_kept_as_printed():
    rows = extract_report_lines(_FOUND[0], rcept_no="20190401003606", corp_code="00131780",
                                report_fiscal_year=2018, report_fiscal_period="FY")
    def val(basis, needle, col):
        hits = [r.value_won for r in rows if r.statement == "IS" and r.basis == basis
                and needle in r.label_raw and r.col_index == col]
        assert len(hits) == 1, (basis, needle, col, hits)
        return hits[0]

    assert val("consolidated", "보통주 기본주당계속영업이익", 0) == 99_000_000
    assert val("separate", "우선주 기본주당이익", 1) == -87_000_000
    assert val("consolidated", "보통주 기본주당이익", 0) == 30
    assert all(r.adecimal == 0 for r in rows if r.statement == "IS" and "주당" in r.label_raw)
