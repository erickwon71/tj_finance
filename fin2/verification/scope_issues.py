"""Issues for the table scopes ('biz'; 'note' later) from machine findings.

A finding of machine_biz is a literal difference between the printed source grid and the stored
grid, so unlike the report_lines identity findings it needs no judgement and the machine
registers it itself (evidence prefix "[machine mb1]"). One issue per cell / row / table:
- scope 'biz', statement 'BIZ', table_ref = biz_section_tables.table_ord, no basis;
- account_label = row label (a repeated label gets " (#n)"), column_label = "<header> [r<row>c<col>]"
  for cells, db_label / source_value_raw carry the two texts.
"""
from __future__ import annotations

import re

from sqlalchemy import text

from fin2.verification import ops

_DIGITS = re.compile(r"\D+")
_CELL_TYPES = {"cell": None, "row_missing": "missing_row", "row_extra": "extra_row",
               "extra_table": "extra_table"}


def _cell_type(db: str, src: str) -> str:
    """value_mismatch when the digits differ, label_mismatch when only the text does."""
    return "value_mismatch" if _DIGITS.sub("", db or "") != _DIGITS.sub("", src or "") else "label_mismatch"


def findings_to_items(scope: str, findings: list[dict], prefix: str,
                      select: list[int] | None = None) -> list[dict]:
    """Issue items for the findings of one filing. `select` = 1-based finding numbers
    (as listed by `vq.py scope show`); None = all. The "(#n)" suffix is assigned over all
    findings first so the same cell gets the same key whichever subset is registered."""
    wanted = set(select) if select is not None else None
    items, seen = [], set()
    for no, f in enumerate(findings, 1):
        kind = f["kind"]
        if kind not in _CELL_TYPES:
            continue
        ref = str(f["table_ord"])
        if kind == "extra_table":
            label = f"표 {f['table_ord']} ({f.get('domain')}/{f.get('metric')})"
            col = None
            item = {"error_type": "extra_table",
                    "db_label": " | ".join(f.get("head") or [])[:300],
                    "evidence": f"{prefix} DB 표(table_ord {f['table_ord']})에 대응하는 원문 표가 없다 "
                                f"(최고 겹침 {f.get('match')})"}
        elif kind == "cell":
            label = (f.get("label") or f"행 {f['row']}")[:280]
            col = f"{f.get('header') or '열'} [r{f['row']}c{f['col']}]"[:200]
            item = {"error_type": _cell_type(f["db"], f["src"]),
                    "db_label": (f["db"] or "")[:300], "source_value_raw": (f["src"] or "")[:200],
                    "evidence": f"{prefix} 표 {f['table_ord']} 행 {f['row']} 열 {f['col']}: "
                                f"DB '{f['db']}' ≠ 원문 '{f['src']}' (공백·&cr; 무시 비교)"}
        else:
            label = (f.get("label") or f"행 {f['row']}")[:280]
            col = f"[r{f['row']}]"
            row = f.get("src") if kind == "row_missing" else f.get("db")
            item = {"error_type": _CELL_TYPES[kind],
                    "db_label": " | ".join(f.get("db") or [])[:300] if kind == "row_extra" else None,
                    "source_value_raw": " | ".join(f.get("src") or [])[:200] if kind == "row_missing" else None,
                    "evidence": f"{prefix} 표 {f['table_ord']} 행 {f['row']}: "
                                + ("원문 행이 DB 에 없음" if kind == "row_missing" else "DB 행이 원문 표에 없음")
                                + f" ({' | '.join(row or [])[:120]})"}
        base = label
        key = (ref, label, col)
        n = 2
        while key in seen:
            label = f"{base[:270]} (#{n})"
            key = (ref, label, col)
            n += 1
        seen.add(key)
        if wanted is not None and no not in wanted:
            continue
        items.append({"scope": scope, "table_ref": ref, "statement": scope.upper(),
                      "account_label": label, "column_label": col, **item})
    return items


def register(scope: str, rcept: str, items: list[dict]) -> list[int]:
    """Insert the issues (verify/admin role). A cell that already has a not-closed issue is skipped."""
    ops._require("verify")
    ids = []
    with ops._Tx() as conn:
        f = conn.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period FROM filings WHERE rcept_no = :r"""),
            {"r": rcept}).mappings().one()
        for it in items:
            dup = conn.execute(text("""
                SELECT 1 FROM verification.issues
                 WHERE rcept_no = :r AND scope = :sc AND statement = :st
                   AND coalesce(table_ref, '') = :tr AND account_label = :al
                   AND coalesce(column_label, '') = coalesce(:cl, '') AND status <> 'closed'"""),
                {"r": rcept, "sc": scope, "st": it["statement"], "tr": it["table_ref"],
                 "al": it["account_label"], "cl": it.get("column_label")}).scalar()
            if dup:
                continue
            ids.append(conn.execute(text("""
                INSERT INTO verification.issues
                    (corp_code, fiscal_year, fiscal_period, rcept_no, scope, table_ref, basis,
                     statement, account_label, column_label, db_label, source_value_raw,
                     error_type, evidence)
                VALUES (:c, :y, :p, :r, :sc, :tr, NULL, :st, :al, :cl, :dl, :sv, :et, :ev)
                RETURNING issue_id"""),
                {"c": f["corp_code"], "y": f["fiscal_year"], "p": f["fiscal_period"], "r": rcept,
                 "sc": scope, "tr": it["table_ref"], "st": it["statement"],
                 "al": it["account_label"], "cl": it.get("column_label"),
                 "dl": it.get("db_label"), "sv": it.get("source_value_raw"),
                 "et": it["error_type"], "ev": it["evidence"][:2000]}).scalar())
    return ids


def recheck(scope: str, dry_run: bool = False) -> dict:
    """Verify side of a fix: for every `fixed` issue of the scope, compare its (reloaded) filing
    with the source again. The issue is closed when no current finding describes the same cell
    (same table, column label and the same DB / source texts), otherwise reopened."""
    from fin2.verification import machine_pass_scope as mps
    _source_path = mps._source_path
    from collector.db import engine

    ops._require("verify")
    mod = mps.MODULES[scope]
    with engine.connect() as conn:
        fixed = [dict(r) for r in conn.execute(text("""
            SELECT issue_id, rcept_no, table_ref, column_label, db_label, source_value_raw
            FROM verification.issues WHERE scope = :sc AND status = 'fixed' ORDER BY issue_id"""),
            {"sc": scope}).mappings()]
    by_rcept: dict[str, list[dict]] = {}
    for i in fixed:
        by_rcept.setdefault(i["rcept_no"], []).append(i)
    out = {"closed": [], "reopened": [], "no_source": [], "dry_run": dry_run}
    for rcept, issues in by_rcept.items():
        with engine.connect() as conn:
            path = _source_path(conn, rcept)
            res = mod.compare_filing(conn, rcept, path) if path else None
        if res is None:
            out["no_source"] += [i["issue_id"] for i in issues]
            continue
        now = {(it["table_ref"], it.get("column_label"), it.get("db_label"), it.get("source_value_raw"))
               for it in findings_to_items(scope, res.findings, "x")}
        for i in issues:
            still = (i["table_ref"], i["column_label"], i["db_label"], i["source_value_raw"]) in now
            key = "reopened" if still else "closed"
            out[key].append(i["issue_id"])
            if dry_run:
                continue
            if still:
                ops.transition(i["issue_id"], "reopened",
                               f"[machine recheck {mod.TOOL_VERSION}] 재적재 후에도 같은 셀이 원문과 다르다")
            else:
                ops.transition(i["issue_id"], "closed",
                               f"[machine recheck {mod.TOOL_VERSION}] 재적재 후 원문과 일치 확인")
    return out
