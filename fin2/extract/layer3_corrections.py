"""Layer-3 cell corrections computed at load time (R0-2, docs/PARSING_RULES.md, 2026-10-10).

Layer 2 (`report_lines`) stores printed values. The correction rules that used to rewrite layer-2
cells (sign repairs, typo list, inline-XBRL overlays, SCE source defects — `as_printed.STEPS`) now
only produce `layer3_cell_corrections` rows; layer 3 reads `report_lines_l3`.

The rules run here, next to the extraction, because some need the source file (inline XBRL
overlays) and all of them were written against the extractor's in-memory lines. Nothing they
produce reaches `report_lines`.

    lines, corrections = extract_with_corrections(run, rcept_no, is_xbrl=...)
    store_report_lines(session, rcept_no, lines)
    store_layer3_corrections(session, rcept_no, corrections)   # after store_report_lines (ids)
"""
from __future__ import annotations

from typing import Callable

from fin2.extract import as_printed as AP

_KEY_FIELDS = ("statement", "basis", "table_seq", "row_order", "col_index", "is_cumulative", "period_kind")


def _key(l) -> tuple:
    return tuple(getattr(l, f) for f in _KEY_FIELDS) + ((l.label_raw or ""),)


def _body(lines) -> dict:
    from fin2.extract.report_lines import _is_loadable
    out: dict = {}
    for l in lines:
        if l.statement == "note" or not _is_loadable(l):
            continue
        out.setdefault(_key(l), l)
    return out


def _typo_rcepts() -> set:
    from parser.xml.table_extractor import _SOURCE_TYPO_CELL_FIXES
    return {k[0] for k in _SOURCE_TYPO_CELL_FIXES}


def extract_xml_with_corrections(file_path, *, rcept_no, corp_code, report_fiscal_year,
                                 report_fiscal_period, include_notes=True,
                                 prior_balances=None, prior_income=None):
    """`extract_report_lines` (printed) + its layer-3 corrections. The rules-on run skips notes
    (they do not feed the body chain) unless the R159 typo list touches this filing."""
    from fin2.extract.report_lines import extract_report_lines

    def run(repaired: bool):
        return extract_report_lines(
            file_path, rcept_no=rcept_no, corp_code=corp_code,
            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
            include_notes=include_notes if not repaired else rcept_no in _typo_rcepts(),
            prior_balances=prior_balances, prior_income=prior_income)
    return extract_with_corrections(run, rcept_no)


def extract_xbrl_with_corrections(file_path, *, rcept_no, corp_code, report_fiscal_year,
                                  report_fiscal_period, period_end_date):
    """`extract_report_lines_xbrl` (printed) + its layer-3 corrections."""
    from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl

    def run(repaired: bool):
        return extract_report_lines_xbrl(
            file_path, rcept_no=rcept_no, corp_code=corp_code,
            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
            period_end_date=period_end_date)
    return extract_with_corrections(run, rcept_no, is_xbrl=True)


def extract_with_corrections(run: Callable[[bool], list], rcept_no: str, *, is_xbrl: bool = False):
    """Run the extraction twice — rules off (printed) and rules on — and return
    (printed_lines, corrections). `run(repaired)` is the extraction call."""
    last_rule: dict[tuple, str] = {}
    prev: dict[tuple, object] = {}

    def trace(step: str, lines: list) -> None:
        snap = {_key(l): l.value_won for l in lines}
        if step != "_base" and prev:
            for k in set(prev) | set(snap):
                if prev.get(k, "absent") != snap.get(k, "absent"):
                    last_rule[k] = step
        prev.clear()
        prev.update(snap)

    with AP.forced("printed"):
        printed = run(False)
    if not printed:
        return printed, []
    AP.TRACE = trace
    try:
        with AP.forced("repaired"):
            repaired = run(True)
    finally:
        AP.TRACE = None
    if not repaired:
        return printed, []

    fallback = ("R159_typo" if rcept_no in _typo_rcepts()
                else "R176_xbrl_sce_sign" if is_xbrl else "unattributed")
    p, r = _body(printed), _body(repaired)
    out = []
    for k in set(p) | set(r):
        a = p[k].value_won if k in p else "absent"
        b = r[k].value_won if k in r else "absent"
        if a == b:
            continue
        line = p.get(k) or r.get(k)
        kind = "fill" if a == "absent" else "drop" if b == "absent" else "value"
        out.append({
            **dict(zip(_KEY_FIELDS, k[:-1])), "label_raw": k[-1], "col_label": line.col_label,
            "printed_value": None if a == "absent" else a,
            "corrected_value": None if b == "absent" else b,
            "kind": kind, "rule": last_rule.get(k, fallback),
            "row_data": _row_data(r[k]) if kind == "fill" else None,
        })
    return printed, out


def _row_data(line) -> str:
    """The whole report_lines row of a 'fill' correction (JSON text for the jsonb column)."""
    import json
    from fin2.extract.report_lines import _TABLE_LEVEL_COLS
    row = {k: v for k, v in line.as_row().items() if k not in _TABLE_LEVEL_COLS}
    return json.dumps(row, ensure_ascii=False, default=str)


def store_layer3_corrections(session, rcept_no: str, corrections: list[dict]) -> int:
    """Replace this filing's corrections. Call after `store_report_lines` in the same transaction:
    'value'/'drop' rows are linked to the printed row by its natural key (+ label)."""
    from sqlalchemy import text
    session.execute(text("DELETE FROM layer3_cell_corrections WHERE rcept_no = :r"), {"r": rcept_no})
    if not corrections:
        return 0
    ids: dict[tuple, list[int]] = {}
    for row in session.execute(text(f"""
            SELECT id, {', '.join(_KEY_FIELDS)}, label_raw FROM report_lines WHERE rcept_no = :r"""),
            {"r": rcept_no}):
        ids.setdefault(tuple(row[1:-1]) + ((row[-1] or ""),), []).append(row[0])
    rows = []
    for c in corrections:
        rid = None
        if c["kind"] != "fill":
            hit = ids.get(tuple(c[f] for f in _KEY_FIELDS) + (c["label_raw"] or "",), [])
            if len(hit) != 1:
                continue        # printed row not stored (or ambiguous) — nothing to correct
            rid = hit[0]
        rows.append({**c, "report_line_id": rid, "rcept_no": rcept_no})
    if rows:
        session.execute(text(f"""
            INSERT INTO layer3_cell_corrections
                (report_line_id, rcept_no, {', '.join(_KEY_FIELDS)}, label_raw, col_label,
                 printed_value, corrected_value, kind, rule, row_data, created_at)
            VALUES (:report_line_id, :rcept_no, {', '.join(':' + f for f in _KEY_FIELDS)}, :label_raw,
                    :col_label, :printed_value, :corrected_value, :kind, :rule,
                    CAST(:row_data AS jsonb), now())"""), rows)
    return len(rows)
