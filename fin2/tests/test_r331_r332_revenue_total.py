"""R331 - a revenue component printed under a revenue total candidate does not win;
R332 - revenue - |cogs| = gross profit picks the top line."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3 import combine  # noqa: E402
from fin2.layer3.combine import _resolve  # noqa: E402


def _c(label, value, stage="exact", path=None):
    return {"label_raw": label, "value": value, "stage": stage, "node_role": "F",
            "section_path": path, "table_seq": 0}


def test_r331_component_under_the_total_does_not_win(monkeypatch):
    cands = {"is.revenue": [_c("1. 영업수익", 19142058515, "normalized", "Ⅰ.영업손익"),
                            _c("수수료수익", 29083528, "exact", "Ⅰ.영업손익>1. 영업수익")]}
    assert _resolve(cands)[0]["is.revenue"] == 19142058515
    monkeypatch.setattr(combine, "_R331_REVENUE_TOTAL_CHILD", False)
    assert _resolve(cands)[0]["is.revenue"] == 29083528


def test_r332_gross_profit_identity_picks_the_top_line(monkeypatch):
    cands = {"is.revenue": [_c("수익(매출액)", 274446518458), _c("영업수익", 348599632)],
             "is.cogs": [_c("매출원가", 146070155446)],
             "is.gross_profit": [_c("매출총이익", 128376363012)]}
    assert _resolve(cands)[0]["is.revenue"] == 274446518458
    monkeypatch.setattr(combine, "_R332_REVENUE_GP_IDENTITY", False)
    assert _resolve(cands)[0]["is.revenue"] == 348599632


def test_r332_keeps_a_revenue_that_already_satisfies_the_identity():
    cands = {"is.revenue": [_c("매출액", 300), _c("영업수익", 300)],
             "is.cogs": [_c("매출원가", 100)], "is.gross_profit": [_c("매출총이익", 200)]}
    assert _resolve(cands)[0]["is.revenue"] == 300


def test_r332_does_not_fill_a_held_revenue_from_another_table():
    """00233653 2025FY separate: a second IS table (table_seq 1) gives cogs / gross profit;
    its '매출액' must not fill the revenue held by the table-0 conflict."""
    def c(label, value, seq, stage="normalized"):
        return {**_c(label, value, stage), "table_seq": seq}
    cands = {"is.revenue": [c("Ⅰ. 매출액", 2436708000000, 1), c("Ⅰ.영업수익", 193914864106, 0),
                            c("1.수수료수익", 97876694814, 0)],
             "is.cogs": [c("Ⅱ. 매출원가", 1827859000000, 1)],
             "is.gross_profit": [c("Ⅲ. 매출총이익", 608849000000, 1)]}
    assert _resolve(cands)[0].get("is.revenue") is None
