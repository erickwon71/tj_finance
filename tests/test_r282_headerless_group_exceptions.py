"""batch 213 - headerless 3개월/누적 IS groups (R120 list) and the SBI duplicated group label (R118 list)."""
import glob
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def _is_rows(corp, rc, year, period, basis):
    from fin2.extract.report_lines import extract_report_lines
    g = glob.glob(str(ROOT / "*" / f"{corp}*" / "*" / "*" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code=corp, report_fiscal_year=year,
                              report_fiscal_period=period, include_notes=False)
    return {(l.label_raw.replace("\n", ""), l.col_index): l.value_won
            for l in ls if l.statement == "IS" and l.basis == basis}


@pytest.mark.parametrize("corp,rc,year,period,basis,label,cur,prior", [
    ("00136101", "20170214000618", 2017, "Q3", "separate", "1. 영업수익", 6_466_938_938, 9_266_859_057),
    ("00136101", "20170214000618", 2017, "Q3", "consolidated", "1. 영업수익", 17_106_906_275, 19_560_411_510),
    ("00136101", "20191114001024", 2020, "H1", "separate", "Ⅲ.법인세차감전순이익(손실)", -694_900_758, -173_251_260),
    ("00136101", "20201116000320", 2021, "H1", "separate", "Ⅲ.법인세차감전순이익(손실)", 1_163_666_286, -694_900_758),
    ("00156910", "20161114000977", 2016, "Q3", "consolidated", "V. 법인세비용차감전순이익(손실)",
     1_176_019_780, 2_224_086_390),
])
def test_cumulative_columns_are_loaded(corp, rc, year, period, basis, label, cur, prior):
    rows = _is_rows(corp, rc, year, period, basis)
    assert rows.get((label, 0)) == cur
    assert rows.get((label, 1)) == prior
