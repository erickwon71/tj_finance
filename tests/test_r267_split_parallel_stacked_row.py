"""R267 - k label lines + k amount lines in every cell are k rows printed in one."""
import glob
from pathlib import Path

import pytest

from parser.xml.table_extractor import _split_parallel_stacked_row as split

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_label_without_line_break_is_cut_at_item_markers():
    got = split("1. 보통주자본금2. 우선주자본금", ["55,225,000\n-", "62,410,000\n-", "561,690,000\n91,863,000"])
    assert got == [("1. 보통주자본금", ["55,225,000", "62,410,000", "561,690,000"]),
                   ("2. 우선주자본금", ["-", "-", "91,863,000"])]


def test_not_split_when_line_counts_differ_or_cell_is_not_numeric():
    assert split("1. 가2. 나", ["1\n2\n3", "4\n5\n6"]) is None
    assert split("1. 가2. 나", ["1,000\nabc", "4,000\n5,000"]) is None
    assert split("1. 가", ["1,000\n2,000"]) is None


def test_everybot_separate_bs_common_and_preferred_capital():
    from fin2.extract.report_lines import extract_report_lines
    rc = "20180402004986"
    g = glob.glob(str(ROOT / "*" / "01201590*" / "annual" / "2017" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="01201590", report_fiscal_year=2017,
                              report_fiscal_period="FY", include_notes=False)
    got = {(l.label_raw, l.col_index): l.value_won for l in ls if l.statement == "BS" and l.basis == "separate"}
    assert got[("1. 보통주자본금", 2)] == 55225000
    assert got[("2. 우선주자본금", 0)] == 91863000
