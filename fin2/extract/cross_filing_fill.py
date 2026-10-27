"""R286 - layer-3 fill of a statement the filing itself does not print, from a later filing's comparative column.

Some filings omit a whole statement (the cash flow statement, a body balance sheet) or print its current-period
columns blank. Layer 2 keeps that as it is (R0-2: printed values only, no statement rows). Layer 3 may bring in
another source (R0-2), so a listed (target, statement, basis) takes the donor filing's prior-year column - the
same period, as the donor prints it - as `layer3_cell_corrections` 'fill' rows.

    CROSS_FILING_FILLS[target_rcept] = ((statement, basis, donor_rcept), ...)

The list is explicit: every entry was checked by hand (donor = the next year's report of the same period, the
donor's comparative column carries the target's fiscal year). The donor prints the period again after possible
restatement, so these cells can differ from what the target filing would have printed.

Nothing is filled when layer 2 already has a current-period (col_index 0) line of that statement and basis.

This is the one use of a later filing's comparative column: layer 2 loads only the current period
(`report_lines._is_loadable`, user decision 2026-07-30) so that a restated comparative never overwrites a
filing's own value. Here the filing has no value at all, so there is nothing to overwrite.
Docs: docs/rules/20_layer3_map.md R286.
"""
from __future__ import annotations

import json
from typing import Callable

RULE = "R286_cross_filing_fill"
_SOURCE_REF_MAX = 180

# target rcept -> ((statement, basis, donor rcept), ...)
CROSS_FILING_FILLS: dict[str, tuple[tuple[str, str, str], ...]] = {
    # Each entry passed two checks against the target's own printed statements: the filled CF ends on the
    # target's balance-sheet cash, and (where the target prints a net income and the CF a matching row) the
    # CF net income equals the target's income statement.
    # CF printed no current-period column (only prior years) or no table at all:
    "20150817000863": (("CF", "separate", "20160812000598"),),     # 카페24 2015 H1
    "20161114002628": (("CF", "separate", "20171114002065"),),     # 아이패밀리에스씨 2016 Q3
    "20211109000077": (("CF", "separate", "20220616000321"),),     # 핀텔 2020 FY (amendment)
    "20200330001006": (("CF", "consolidated", "20210311001187"),),  # 에프알텍 2019 FY
    "20200330002894": (("CF", "separate", "20210319000131"),),     # 램테크놀러지 2019 FY
    "20230515000670": (("CF", "separate", "20240516000334"),),     # 삼륭물산 2023 Q1
    "20240314000617": (("CF", "separate", "20240315000757"),),     # 이화산업 2019 FY (amendment)
    "20200330004128": (("CF", "consolidated", "20210331003114"),
                       ("CF", "separate", "20210331003114")),      # 이노시뮬레이션 2019 FY
}


def _donor_lines(donor_rcept: str) -> list:
    """The donor's printed lines (layer 2, no corrections), read from its source file."""
    from sqlalchemy import text

    from collector.db import get_session
    from fin2.extract.report_lines import extract_report_lines

    with get_session() as s:
        t = s.execute(text("""
            SELECT CASE WHEN dt.status = 'completed' AND dt.file_type = 'xml' THEN dt.file_path
                        WHEN dt.viewer_xml_path IS NOT NULL THEN dt.viewer_xml_path
                        ELSE dt.file_path END AS file_path,
                   f.corp_code, f.fiscal_year, f.fiscal_period
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            WHERE dt.rcept_no = :r
              AND ((dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL)
                   OR dt.viewer_xml_path IS NOT NULL)
            LIMIT 1"""), {"r": donor_rcept}).fetchone()
    if t is None:
        raise RuntimeError(f"R286 donor {donor_rcept}: no XML source")
    return extract_report_lines(
        t.file_path, rcept_no=donor_rcept, corp_code=t.corp_code,
        report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period)


def _loadable(line) -> bool:
    from fin2.extract.report_lines import _is_loadable
    return line.statement != "note" and _is_loadable(line)


def cross_filing_fill_corrections(
        rcept_no: str, printed_lines: list, *, report_fiscal_year: int, report_fiscal_period: str,
        donor_lines: Callable[[str], list] | None = None) -> list[dict]:
    """'fill' corrections for the listed statements of `rcept_no` (empty for an unlisted filing)."""
    from fin2.extract.report_lines import _TABLE_LEVEL_COLS

    entries = CROSS_FILING_FILLS.get(rcept_no)
    if not entries:
        return []
    load = donor_lines or _donor_lines
    have = {(l.statement, l.basis) for l in printed_lines if _loadable(l) and l.col_index == 0}
    out: list[dict] = []
    for statement, basis, donor in entries:
        if (statement, basis) in have:
            continue
        rows = [l for l in load(donor)
                if l.statement == statement and l.basis == basis and l.col_index == 1
                and l.value_won is not None]
        for l in rows:
            # the comparative column must be this filing's own period, not an older one
            if l.context_fiscal_year != report_fiscal_year:
                raise ValueError(
                    f"R286 {rcept_no}: donor {donor} {statement} {basis} comparative column is "
                    f"fiscal year {l.context_fiscal_year}, expected {report_fiscal_year}")
        for l in rows:
            row = {k: v for k, v in l.as_row().items() if k not in _TABLE_LEVEL_COLS}
            row["report_fiscal_year"] = report_fiscal_year
            row["report_fiscal_period"] = report_fiscal_period
            row["rcept_no"] = rcept_no
            row["col_index"] = 0
            row["source_ref"] = f"xfill:{donor};{l.source_ref or ''}"[:_SOURCE_REF_MAX]
            out.append({
                "statement": statement, "basis": basis, "table_seq": l.table_seq,
                "row_order": l.row_order, "col_index": 0, "is_cumulative": l.is_cumulative,
                "period_kind": l.period_kind, "label_raw": l.label_raw, "col_label": l.col_label,
                "printed_value": None, "corrected_value": l.value_won, "kind": "fill", "rule": RULE,
                "row_data": json.dumps(row, ensure_ascii=False, default=str),
            })
    return out
