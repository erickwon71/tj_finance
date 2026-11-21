"""Layer 3 one-off non-operating items (R369, tj_asset request #7).

Five total accounts — impairment loss / reversal, disposal gain / loss, debt forgiveness gain —
exposed through extended_financials. Source order (user-confirmed design): the body income statement
line when the filing prints one, else the note (기타수익·기타비용·금융수익·금융비용 tables).
NULL (no row) when neither names the item: a missing note cannot be told from a zero amount.
A line printed as 0 stays 0.

The chain is the shared layer-3 interpretation chain, no bespoke extractor:
    note_topics.map_topic (OTHER_INCOME_EXPENSE) → note_periods.resolve_periods → note_labels
Rules: docs/rules/20_layer3_map.md R369.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import text

from parser.common.note_labels import classify_oneoff_label
from parser.common.note_periods import resolve_periods
from parser.common.note_topics import OTHER_INCOME_EXPENSE, map_topic

# Only the sections that can hold these lines are read (the whole note set of a filing is large).
_SECTION_RE = r"(기타\s*수익|기타\s*비용|기타\s*이익|기타\s*손실|기타\s*손익|기타\s*영업외|영업외\s*(수익|비용|손익)|금융\s*(수익|비용|손익))"
_ROWS_SQL = text(
    """
    SELECT rt.section_path, n.table_seq, n.row_order, n.col_index, n.col_label,
           n.label_raw, n.value_won
    FROM note_lines n
    JOIN report_tables rt
      ON rt.rcept_no = n.rcept_no AND rt.statement = 'note'
     AND rt.basis = n.basis AND rt.table_seq = n.table_seq
    WHERE n.rcept_no = :rcept AND n.basis = :basis AND n.statement = 'note'
      AND n.value_won IS NOT NULL AND n.header_hint IS NULL
      AND rt.section_path ~ :section_re
    """
)


class _Row:
    __slots__ = ("table_seq", "col_index", "col_label", "label_raw", "value_won", "row_order")

    def __init__(self, r):
        self.table_seq = r.table_seq
        self.col_index = r.col_index
        self.col_label = getattr(r, "col_label", None)
        self.label_raw = r.label_raw
        self.value_won = r.value_won
        self.row_order = r.row_order


def _is_fin_section(section_path: Optional[str]) -> bool:
    s = (section_path or "").replace(" ", "")
    return "금융" in s and "기타" not in s and "영업외" not in s


def oneoff_from_note_rows(rows: Iterable, period: str = "FY") -> dict[str, int]:
    """{account: amount} from note rows (objects with section_path/table_seq/…/value_won).

    Within one table the matching lines are summed (a note lists 유형자산처분이익 and
    무형자산처분이익 as separate lines). Across tables an account is taken from the first table that
    names it — later tables of the same note repeat the figures (prior-period siblings are removed
    by resolve_periods; a detail table restating them would double the amount)."""
    prefer_cum = period != "FY"
    by_section: dict[str, list] = defaultdict(list)
    for r in rows:
        if map_topic(r.section_path) == OTHER_INCOME_EXPENSE:
            by_section[r.section_path].append(_Row(r))
    per_table: dict[tuple[str, int], dict[str, int]] = {}
    for section, srows in by_section.items():
        fin = _is_fin_section(section)
        for cell in resolve_periods(srows, prefer_cumulative=prefer_cum):
            if cell.period_rank != 0:
                continue
            acc_name = classify_oneoff_label(cell.label_raw, fin_note=fin)
            if acc_name is None:
                continue
            acc = per_table.setdefault((section, cell.table_seq), {})
            acc[acc_name] = acc.get(acc_name, 0) + abs(cell.value_won)
    out: dict[str, int] = {}
    first_seq: dict[str, int] = {}
    for (section, seq), acc in sorted(per_table.items(), key=lambda kv: kv[0][1]):
        for name, v in acc.items():
            if name not in first_seq:
                first_seq[name] = seq
                out[name] = v
    return out


def oneoff_from_body_rows(merged: Iterable[dict], basis: str, period: str) -> dict[str, int]:
    """{account: amount} from body income-statement cells of the merged filing lines. A line must
    name a non-financial asset (strict); interim periods read the cumulative cells only."""
    interim = period in ("H1", "Q3")
    out: dict[str, int] = {}
    for r in merged:
        if r["statement"] != "IS" or r["basis"] != basis:
            continue
        if interim and not r.get("is_cumulative"):
            continue
        name = classify_oneoff_label(r.get("label_raw"), strict=True)
        if name is None or r.get("value_won") is None:
            continue
        out[name] = out.get(name, 0) + abs(int(r["value_won"]))
    return out


def oneoff_canonicals(session, merged: list[dict], rcept_no: Optional[str], basis: str,
                      period: str) -> dict[str, int]:
    """Body values first, note values for the accounts the body does not print."""
    out = oneoff_from_body_rows(merged or [], basis, period)
    if rcept_no and period in ("FY", "H1", "Q1", "Q3"):
        rows = session.execute(_ROWS_SQL, {"rcept": rcept_no, "basis": basis,
                                           "section_re": _SECTION_RE}).fetchall()
        for k, v in oneoff_from_note_rows(rows, period).items():
            out.setdefault(k, v)
    return out
