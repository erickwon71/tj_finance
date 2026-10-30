"""Machine comparison of one filing's financial-statement NOTES: DART source XML vs DB note_lines.

Design: docs/plans/verification_note_biz_expansion_design_2026-10-27.md (scope 'note').

note_lines is not a grid: one row per (row_order, numeric column) holding value_won, the scale
`adecimal` and the printed text only when the number could not be read (value_raw). Blank and
dash cells are not stored. The printed number is therefore recoverable as
    printed = value_won * 10**adecimal          (adecimal <= 0: millions -> -6)
and that is what is compared with the source - a wrong unit shows up as a printed value that is
a power of ten away from the source (`unit_scale`), without trusting the parser's unit logic.

Independent of the production reader (lxml HTML parser, own span expansion, own amount reading
via machine_compare.parse_amount). Per filing:
- the source tables of the '주석' sections give, per table, the list of non-zero integer printed
  amounts in reading order (row-major) with their row label;
- the DB gives, per (basis, table_seq), the same list from note_lines ordered by (row_order,
  col_index);
- a DB table is paired with the source table of an identical amount list when there is one,
  otherwise with the best overlap of the same basis (>= MATCH_MIN, ties by order similarity);
- the two lists are aligned with difflib: 1:1 replacements are `value` findings, source-only
  amounts `missing_cell`, DB-only amounts `extra_cell`; a DB table without a counterpart is
  `extra_table`.
Zero / dash / blank cells and cells with decimals are not compared (the DB stores integers; a
decimal cell is stored in another form) - they are counted. Source numeric tables no stored table
matches are only counted (`unmatched_source_tables`).
Findings err toward "mismatch".
"""
from __future__ import annotations

import difflib
import re
from types import SimpleNamespace
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from fin2.verification import machine_biz as mb
from fin2.verification import machine_compare as mc

# mn1 (2026-10-28): first version.
# mn2 (2026-10-28): amounts below MIN_AMOUNT (ratios, ownership %, note numbers, counts: the DB
# does not keep them as amounts) and per-share rows ('주당...') are counted, not compared; the first
# 25-filing sample showed 229 of 817 "missing cells" were such small integers.
# mn4 (2026-10-28): a merged (rowspan/colspan) amount cell is ONE amount: the source grid no longer
# repeats it in every covered cell (it doubled amounts the DB, correctly, holds once).
# mn3 (2026-10-28): a row with value_won NULL and value_raw set (non-monetary column, R160 broken
# dot cell ...) keeps the PRINTED text in value_raw: it is read with the same amount reader as the
# source cell instead of being skipped (first sample: '(29,990,471)' under a 비현금변동 column).
# mn5 (2026-10-28): the DB treats a merged cell differently from table to table (once at its origin
# in some, repeated in every covered cell in others), so the source gets both readings
# (`amounts` = merged cell once, `alt_*` = repeated) and a table matches when either does; for
# a differing table the reading with fewer findings is used.
# mn6 (2026-10-28): pairing also scores the overlap of row labels: a table with 3-4 amounts and one
# wrong value shares too little of its amounts to pair, and became an extra_table instead of a
# value finding. score = max(amount overlap, mean(amount overlap, label overlap)).
# mn7 (2026-10-28): a bare four-digit 1900-2100 ("2015", no thousands comma) is a year in a period
# header, not an amount: it made 28,196 of the 163,551 remaining "missing" cells of the note batch
# (label '구분', values 2,015 / 2,016 ...). A printed amount of that size carries its comma.
# mn8 (2026-10-29): the year rule is symmetric: a printed 1900-2100 is skipped on BOTH sides, with or
# without a thousands comma. mn7 skipped only a bare '2015' of the source, so a maturity-year column
# the DB keeps as 2016 (value_won / value_raw) became an "extra cell": extra_row went 29,949 -> 41,835
# after R290. Amounts of exactly that size are rare; a year column is not.
# mn9 (2026-10-29): a DB value_raw that prints the amount plus a tail ('258,096,615===========',
# '(5,813)========', '17,572,153USD 8,000,000') is read by its first amount, like the source side reads
# the first '&cr;' segment of such a cell. The columns whose unit is undeclared / non-monetary keep the
# printed text in value_raw with value_won NULL, and the machine called every total of such a table
# missing (about 40% of the 6,912 total-label missing_row issues left after R295).
# mn11 (2026-10-30): the SOURCE side reads a cell the way the loader does: the first amount of a cell with
# an R294 tail ('20,792,401(VND 377,357,546,463)') and a number split by white space inside one cell
# ('<SPAN>12,553,95</SPAN><SPAN>1</SPAN>'). After R294-R296 the DB holds those amounts while the source side
# read nothing, so 1,355 extra_row issues appeared with the full reload of 2026-10-30.
TOOL_VERSION = "mn11"
_BARE_YEAR = re.compile(r"^(19|20)\d\d$")

MIN_AMOUNT = 1000                 # |printed| below this is not compared (see mn2)
_PER_SHARE = re.compile(r"주당")

MATCH_MIN = 0.5
MAX_FINDINGS = 400
_WS = re.compile(r"\s+")


@dataclass
class SrcTable:
    idx: int
    basis: str                       # consolidated / separate
    amounts: list = field(default_factory=list)    # [(printed_int, row_label, col)]
    n_skipped: int = 0               # zero / decimal / unreadable numeric-looking cells
    values: tuple = ()
    valueset: Counter = field(default_factory=Counter)
    alt_amounts: list = field(default_factory=list)     # merged cells repeated in every covered cell
    alt_values: tuple = ()
    labels: frozenset = frozenset()


@dataclass
class Result:
    verdict: str = "clean"
    findings: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def _clean(s: str) -> str:
    return (s or "").strip()


def _read_amount(cell: str):
    """Printed integer of a cell, None when it is not a non-zero integer amount."""
    v = mc.parse_amount(cell)
    if not isinstance(v, float) or v == 0 or v != int(v):
        return None
    if _is_year(int(v)):
        return None
    return int(v)


_SPLIT_DIGITS = re.compile(r"^[\d,()\-\s]+$")


def _read_source_cell(cell: str):
    """mn11 - `_read_amount` of a source cell, else of what the loader reads from it: the first amount in front
    of an R294 tail, or a number whose digits are split by white space (R150 / `parse_amount`)."""
    v = _read_amount(cell)
    if v is not None or not cell:
        return v
    from fin2.extract.report_lines import parse_amount as rl_parse, split_amount_with_tail
    first = split_amount_with_tail(cell)
    if first:
        return _read_amount(first)
    if _WS.search(cell) and _SPLIT_DIGITS.match(cell):
        joined = rl_parse(cell)
        if isinstance(joined, (int, float)) and joined == int(joined) and joined != 0 and not _is_year(int(joined)):
            return int(joined)
    return None


_RAW_CAP = 64                                   # note_lines.value_raw is stored cut at 64 characters
_TRAILING_ITEM = re.compile(r"\(?(?:[A-Z]{2,4}|(?:US|U)?[$＄￥¥€£])?\s*[\d,.\-]*\)?$")


def _read_db_raw(raw: str):
    """mn9 - `_read_amount` of a stored value_raw, else of its first amount when what follows is only a
    currency / symbol / dash tail (R294 `split_amount_with_tail`)."""
    v = _read_amount(raw)
    if v is not None:
        return v
    from fin2.extract.report_lines import split_amount_with_tail
    first = split_amount_with_tail(raw)
    if not first and len(raw) >= _RAW_CAP:
        # mn10: the loader stores value_raw cut at 64 characters, so the last tail item can be half
        # printed ('...CNY 28,500,000EUR 8' for 'EUR 89,931'); drop that item and read the rest
        first = split_amount_with_tail(_TRAILING_ITEM.sub("", raw))
    return _read_amount(first) if first else None


def _is_year(v: int) -> bool:
    return 1900 <= abs(v) <= 2100


def load_source_tables(path: str) -> tuple[list[SrcTable], bool]:
    root = mb.parse_source_root(path)
    els = list(root.iter("table"))              # keep the element proxies alive: id() stays stable
    out: list[SrcTable] = []
    seen: set = set()
    found = False
    for sec in root.iter():
        if not (isinstance(sec.tag, str) and sec.tag.lower().startswith("section")):
            continue
        t = sec.find("title")
        title = mb.norm(mc._text(t)) if t is not None else ""
        if "주석" not in title or "재무제표" not in title:
            continue
        found = True
        basis = "consolidated" if "연결" in title else "separate"
        for tb in sec.iter("table"):
            if id(tb) in seen:
                continue
            seen.add(id(tb))
            st = SrcTable(idx=len(out), basis=basis)
            for copies, target in ((False, st.amounts), (True, st.alt_amounts)):
                for row in mb._own_grid(tb, clean=_clean, copies=copies):
                    label = next((c for c in row if c and mc.parse_amount(c) is None), "")
                    for col, cell in enumerate(row):
                        if not cell or cell == label:
                            continue
                        v = _read_source_cell(cell)
                        if v is None or abs(v) < MIN_AMOUNT or _PER_SHARE.search(label):
                            if not copies and mc.parse_amount(cell) not in (None, mc._EMPTY):
                                st.n_skipped += 1
                            continue
                        target.append((v, mb.norm(label)[:80], col))
            if st.amounts or st.alt_amounts:
                st.values = tuple(a[0] for a in st.amounts)
                st.alt_values = tuple(a[0] for a in st.alt_amounts)
                st.valueset = Counter(st.alt_values)           # superset: overlap scoring
                st.labels = frozenset(a[1] for a in st.alt_amounts if a[1])
                out.append(st)
    return out, found


@dataclass
class DbTable:
    basis: str
    seq: int
    amounts: list = field(default_factory=list)    # [(printed_int, label_raw, col_label, row_order, col_index)]
    n_skipped: int = 0
    values: tuple = ()
    valueset: Counter = field(default_factory=Counter)
    labels: frozenset = frozenset()


def load_db_tables(conn, rcept: str) -> list[DbTable]:
    from sqlalchemy import text
    return tables_from_rows(conn.execute(text("""
            SELECT basis, table_seq, row_order, label_raw, col_index, col_label, value_won,
                   adecimal, value_raw
            FROM note_lines WHERE rcept_no = :r
            ORDER BY basis, table_seq, row_order, col_index"""), {"r": rcept}))


def tables_from_rows(rows) -> list[DbTable]:
    """DbTables from note_lines rows (anything with those attributes: DB rows, or freshly
    extracted ReportLineRow objects - `vq.py`/scripts use that to see what a reload would change)."""
    tabs: dict[tuple, DbTable] = {}
    for r in rows:
        t = tabs.setdefault((r.basis, r.table_seq), DbTable(r.basis or "", r.table_seq))
        if _PER_SHARE.search(r.label_raw or ""):
            t.n_skipped += 1
            continue
        if r.value_won is None:
            v = _read_db_raw(r.value_raw) if r.value_raw else None
            if v is None or abs(v) < MIN_AMOUNT:
                t.n_skipped += 1
                continue
            t.amounts.append((v, r.label_raw or "", r.col_label or "", r.row_order, r.col_index))
            continue
        if r.value_won == 0:
            continue
        scale = r.adecimal or 0
        if scale > 0:
            printed = r.value_won * 10 ** scale
        else:
            q, rem = divmod(abs(r.value_won), 10 ** (-scale))
            if rem:                         # the printed number had decimals
                t.n_skipped += 1
                continue
            printed = q if r.value_won > 0 else -q
        if abs(printed) < MIN_AMOUNT or _is_year(int(printed)):
            t.n_skipped += 1
            continue
        t.amounts.append((int(printed), r.label_raw or "", r.col_label or "", r.row_order, r.col_index))
    out = []
    for t in tabs.values():
        if t.amounts:
            t.values = tuple(a[0] for a in t.amounts)
            t.valueset = Counter(t.values)
            t.labels = frozenset(mb.norm(a[1].split(">")[-1])[:80] for a in t.amounts if a[1])
            out.append(t)
    return out


def _pair_score(t: "DbTable", s: "SrcTable") -> float:
    v = _jaccard(t.valueset, s.valueset)
    if not t.labels or not s.labels:
        return v
    lab = len(t.labels & s.labels) / len(t.labels | s.labels)
    return max(v, (v + lab) / 2)


def _jaccard(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    inter = sum((a & b).values())
    union = sum((a | b).values())
    return inter / union if union else 0.0


def _align(db: DbTable, src_values: tuple, src_amounts: list) -> list[dict]:
    out: list[dict] = []
    src = SimpleNamespace(values=src_values, amounts=src_amounts)
    sm = difflib.SequenceMatcher(None, db.values, src.values, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        n = min(i2 - i1, j2 - j1) if op == "replace" else 0
        for k in range(n):
            d, s = db.amounts[i1 + k], src.amounts[j1 + k]
            out.append({"kind": "value", "db": d[0], "src": s[0], "label": d[1][:120],
                        "col_label": d[2][:80], "src_label": s[1], "row_order": d[3],
                        "col_index": d[4]})
        for k in range(i1 + n, i2):
            d = db.amounts[k]
            out.append({"kind": "extra_cell", "db": d[0], "label": d[1][:120],
                        "col_label": d[2][:80], "row_order": d[3], "col_index": d[4]})
        for k in range(j1 + n, j2):
            s = src.amounts[k]
            out.append({"kind": "missing_cell", "src": s[0], "label": s[1], "src_col": s[2],
                        "prev_db_row": db.amounts[max(0, min(i2, len(db.amounts)) - 1)][3]
                        if db.amounts else None})
    return out


def compare(db_tables: list[DbTable], src_tables: list[SrcTable], section_found: bool) -> Result:
    res = Result()
    by_basis: dict[str, list[SrcTable]] = defaultdict(list)
    exact: dict[tuple, list[SrcTable]] = defaultdict(list)
    for s in src_tables:
        by_basis[s.basis].append(s)
        exact[(s.basis, s.values)].append(s)
        if s.alt_values != s.values:
            exact[(s.basis, s.alt_values)].append(s)
    used: set[int] = set()
    counts = {"db_tables": len(db_tables), "exact": 0, "differs": 0, "extra_table": 0}
    for t in db_tables:
        cands = [s for s in exact.get((t.basis, t.values), []) if s.idx not in used] \
            or exact.get((t.basis, t.values), [])
        if cands:
            used.add(cands[0].idx)
            counts["exact"] += 1
            continue
        pool = by_basis.get(t.basis) or src_tables
        scored = sorted(((_pair_score(t, s), s) for s in pool), key=lambda x: -x[0])
        if not scored or scored[0][0] < MATCH_MIN:
            counts["extra_table"] += 1
            res.findings.append({"kind": "extra_table", "basis": t.basis, "table_seq": t.seq,
                                 "match": round(scored[0][0], 2) if scored else 0.0,
                                 "head": [a[1][:40] for a in t.amounts[:2]]})
            continue
        top = [x for x in scored[:6] if x[0] >= scored[0][0] - 0.05]
        best = max(top, key=lambda x: (x[0], difflib.SequenceMatcher(
            None, t.values, x[1].alt_values, autojunk=False).ratio() if len(t.values) < 600 else 0))[1]
        used.add(best.idx)
        counts["differs"] += 1
        a = _align(t, best.values, best.amounts)
        b = _align(t, best.alt_values, best.alt_amounts) if best.alt_values != best.values else a
        for f in (a if len(a) <= len(b) else b):
            res.findings.append({**f, "basis": t.basis, "table_seq": t.seq, "src_table": best.idx})
    counts["source_numeric_tables"] = len(src_tables)
    counts["unmatched_source_tables"] = sum(1 for s in src_tables if s.idx not in used)
    counts["skipped_db_cells"] = sum(t.n_skipped for t in db_tables)
    res.counts = counts
    if not section_found and not db_tables:
        res.verdict = "no_structure"
    elif res.findings:
        res.verdict = "mismatch"
    else:
        res.verdict = "clean"
    if len(res.findings) > MAX_FINDINGS:
        counts["findings_total"] = len(res.findings)
        res.findings = res.findings[:MAX_FINDINGS]
    return res


def compare_filing(conn, rcept: str, xml_path: str) -> Result:
    src, found = load_source_tables(xml_path)
    return compare(load_db_tables(conn, rcept), src, found)
