"""R324 - only the reports of the latest closing date of a period slot are merged (fiscal year end change)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3 import combine  # noqa: E402
from fin2.layer3.combine import build_merged_lines  # noqa: E402


def _bs(values, labels):
    return [("BS", "consolidated", 0, None, lab, val, "S", 0, False, None, False, None, i)
            for i, (lab, val) in enumerate(zip(labels, values))]


class _Result:
    def __init__(self, rows): self._rows = rows
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None


# 00814786 2022 FY: the report closing 2022.06 and the one closing 2022.12 are not amendments of each other
_ROWS = {
    "early": _bs([10, 20, 30, 12, 8, 20, 5, 5, 10, 7], ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계", "자본금", "이익잉여금", "자본총계", "매출액"]),
    "late": _bs([11, 22, 33, 13, 9, 22, 5, 6, 11], ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계", "자본금", "이익잉여금", "자본총계"]),
}


class _Session:
    def __init__(self, dates): self._dates = dates

    def execute(self, stmt, params):
        sql = str(stmt)
        if "period_end_date" in sql:
            return _Result([(r, self._dates[r]) for r in params["r"]])
        if "FROM filings f" in sql:
            return _Result([("early", False), ("late", False)])
        if "bool_or(unit_source = 'xbrl')" in sql:
            return _Result([(False, False)])
        return _Result(_ROWS[params["r"]])


def _merged(dates):
    return {c["label_raw"]: c for c in build_merged_lines(_Session(dates), "X", 2022, "FY")}


def test_report_of_an_earlier_closing_date_is_not_merged(monkeypatch):
    m = _merged({"early": date(2022, 6, 30), "late": date(2022, 12, 31)})
    assert m["자산총계"]["value_won"] == 33 and not m["자산총계"]["amended"]
    assert "매출액" not in m                      # the row only the earlier report prints
    monkeypatch.setattr(combine, "_R324_LATEST_CLOSING_ONLY", False)
    m = _merged({"early": date(2022, 6, 30), "late": date(2022, 12, 31)})
    assert m["자산총계"]["value_won"] == 33 and m["자산총계"]["amended"] and m["매출액"]["value_won"] == 7


def test_same_closing_date_is_an_ordinary_amendment_chain():
    m = _merged({"early": date(2022, 12, 31), "late": date(2022, 12, 31)})
    assert m["자산총계"]["value_won"] == 33 and m["자산총계"]["amended"] and m["매출액"]["value_won"] == 7


def test_filing_without_a_closing_date_is_kept():
    m = _merged({"early": None, "late": date(2022, 12, 31)})
    assert m["매출액"]["value_won"] == 7
