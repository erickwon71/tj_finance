"""R256 - SCE label region follows the header's first-cell span when a blank cell after an anchor label
makes the value-based region one column short (두산밥캣 20170512000497).
R257 - a USD face statement printed beside the won one is not a duplicate of the 2-tier won table
(두산밥캣 20180515001448 / 20210514001579).
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "raw_report" / "KOSPI" / "01032486_두산밥캣" / "quarter"
CORP = "01032486"


def _lines(year, rcept, fp="Q1"):
    from fin2.extract.report_lines import extract_report_lines
    path = ROOT / str(year) / f"{rcept}.xml"
    if not path.exists():
        pytest.skip("raw report not available")
    return extract_report_lines(path, rcept_no=rcept, corp_code=CORP, report_fiscal_year=year,
                                report_fiscal_period=fp, include_notes=False)


def test_r256_sce_rows_keep_their_own_labels():
    labels = {l.label_raw for l in _lines(2017, "20170512000497")
              if l.statement == "SCE" and l.basis == "consolidated"}
    assert {"연결 당기순이익(손실)", "확정급여제도의 재측정요소", "유상감자"} <= labels
    assert "자본의 변동" not in labels


@pytest.mark.parametrize("year,rcept", [(2018, "20180515001448"), (2021, "20210514001579")])
def test_r257_usd_income_statement_is_loaded(year, rcept):
    usd = [l for l in _lines(year, rcept)
           if l.statement == "IS" and l.basis == "consolidated" and l.unit_source == "fx_declared"]
    assert len(usd) >= 20
    assert {l.currency for l in usd} == {"USD"}
