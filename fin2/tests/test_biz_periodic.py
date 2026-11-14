"""R288 / R289 — quarterly and half-year '사업의 내용' segment results: what layer 2 keeps, and that
layer 3 writes its own (corp, fiscal_year, fiscal_period) tables without touching the annual ones.
No database: the session and the filing lookup are faked."""
from __future__ import annotations

from types import SimpleNamespace

from collector import biz_metrics_periodic as bp
from collector.filing_select import SourceFiling
from fin2.layer2.biz_raw_tables import keep_for_periodic


def test_periodic_keeps_segment_results_only():
    keep = [{"domain": "sales", "metric": "sales"}, {"domain": "production", "metric": "capacity"},
            {"domain": "production", "metric": "output+utilization"},
            {"domain": "order_backlog", "metric": "order_backlog"},
            {"domain": "catalog", "metric": "product_status"}]
    drop = [{"domain": "catalog", "metric": m} for m in
            ("facility", "material_status", "ip_right", "rd_staff", "derivative", "product_price")]
    assert all(keep_for_periodic(r) for r in keep)
    assert not any(keep_for_periodic(r) for r in drop)


def _filing(rcept, fy, fp):
    return SourceFiling(rcept_no=rcept, file_path="/x", fiscal_year=fy, fiscal_period=fp,
                        report_nm="", is_final=True)


def test_latest_only_keeps_every_period_of_the_latest_year(monkeypatch):
    """period_groups sorts fiscal_period ascending, so its own latest_only would keep Q1 and the
    daily run would never refresh Q3."""
    data = {"quarter": [[_filing("a", 2025, "Q1")], [_filing("b", 2025, "Q3")], [_filing("c", 2024, "Q3")]],
            "half": [[_filing("d", 2025, "H1")]]}
    monkeypatch.setattr(bp, "period_groups", lambda s, c, rtype, year=None, latest_only=False: data[rtype])
    got = bp._groups(None, "00000001", "quarter", None, True)
    assert [g[0].rcept_no for g in got] == ["a", "b"]
    assert [g[0].rcept_no for g in bp._groups(None, "00000001", "quarter", None, False)] == ["a", "b", "c"]
    assert [g[0].rcept_no for g in bp._groups(None, "00000001", "quarter", None, False, 2025)] == ["a", "b"]


class _FakeSession:
    def __init__(self, tables):
        self.tables, self.calls = tables, []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if "FROM biz_section_tables" in sql:
            return SimpleNamespace(fetchall=lambda: self.tables[params["r"]])
        return SimpleNamespace(fetchall=lambda: [])


def test_sync_writes_the_periodic_table_keyed_by_period(monkeypatch):
    grid = [["부문", "제56기 1분기"], ["DX 부문", "100"]]
    rows = {"R1": [SimpleNamespace(table_ord=0, domain="sales", metric="sales",
                                   narrative="(단위 : 억원)", grid=grid)]}
    monkeypatch.setattr(bp, "period_groups", lambda s, c, rtype, year=None, latest_only=False:
                        [[_filing("R1", 2024, "Q1")]] if rtype == "quarter" else [])
    monkeypatch.setattr(bp, "ensure_biz_raw_tables", lambda *a, **k: False)
    seen = {}
    monkeypatch.setattr(bp, "_map_row", lambda d, m, n, g, fy: [
        {"metric": "sales", "channel": None, "segment": "DX 부문", "item": None,
         "period_label": "제56기", "period_year": fy, "value": 100.0, "unit": "억원",
         "is_ratio": False}])
    s = _FakeSession(rows)
    agg = bp.sync_biz_metrics_periodic_corp(s, "00126380")
    deletes = [(sql, p) for sql, p in s.calls if sql.lstrip().startswith("DELETE")]
    assert len(deletes) == 1
    assert "biz_metrics_periodic" in deletes[0][0] and "fiscal_period" in deletes[0][0]
    assert deletes[0][1] == {"c": "00126380", "y": 2024, "p": "Q1"}
    inserts = [p for sql, p in s.calls if "INSERT INTO biz_metrics_periodic" in sql]
    assert len(inserts) == 1 and inserts[0][0]["fiscal_period"] == "Q1"
    assert agg["metric_rows"] == 1
    # the annual table is never named
    assert not any("biz_metrics " in sql and "periodic" not in sql for sql, _ in s.calls)


def test_ensure_receives_the_report_type(monkeypatch):
    seen = []
    monkeypatch.setattr(bp, "period_groups", lambda s, c, rtype, year=None, latest_only=False:
                        [[_filing("R9", 2023, "H1")]] if rtype == "half" else [])
    monkeypatch.setattr(bp, "ensure_biz_raw_tables", lambda s, r, fp, c, fy, rt=None: seen.append(rt))
    bp.sync_biz_metrics_periodic_corp(_FakeSession({"R9": []}), "00000009")
    assert seen == ["half"]
