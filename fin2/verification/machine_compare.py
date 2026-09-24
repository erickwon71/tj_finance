"""Machine comparison of one filing: DART source XML tables vs DB report_lines.

Design: docs/plans/verification_machine_compare_design_2026-09-24.md

Deliberately independent of the production parser (parser/xml, fin2/extract): it reads the
statement sections of the source XML with simple rules only, so a parser bug cannot make both
sides agree. Anything the simple rules cannot decide becomes a finding and goes to the model
reviewer (web view) - a false "mismatch" costs model time, a false "clean" would hide a defect,
so every rule errs toward "mismatch".

Rules
- Statement tables: only tables inside the '연결재무제표' / '재무제표' sections (not '주석',
  not '요약'). Section basis = consolidated / separate.
- Table grid: rowspan/colspan expanded. Header rows = rows before the first row with an amount.
  A header column containing '주석' is a note-reference column and never an amount.
- Current-period column (BS/IS/CF, DB col_index 0): leftmost amount column; when the header has
  '누적' columns and the DB rows are cumulative, the leftmost '누적' column (3-month when not).
- SCE: DB col_index k = k-th amount column (component order).
- Row alignment: difflib over normalized labels, then re-pair same-label rows out of order.
- Scale per DB group chosen from {1, 1e3, 1e6, 1e8} by majority; per-share rows are always won.
Findings: value (DB != source cell), missing_row (source row with a non-zero current amount and
no DB row), extra_row (DB row not in source), uncovered_cell (SCE non-zero source cell with no
DB cell), unmatched_table (statement-section data table no DB group maps to), no_table (DB group
with no source table).
"""
from __future__ import annotations

import difflib
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

TOOL_VERSION = "mc5"

_CELL_TAGS = {"td", "th", "te", "tu"}
_NUM_RE = re.compile(r"^[\(△▲\-−]?\s*[\d,]+(\.\d+)?\s*\)?$")
_WS_RE = re.compile(r"[\s　\xa0]")
_SCALES = (1, 1_000, 1_000_000, 100_000_000)
_EMPTY = "EMPTY"

# Local SD-card mirror is much faster than the NAS for bulk reads (memory: bulk-read-use-sdcard).
_NAS_PREFIX = str(Path(__file__).resolve().parents[2] / "raw_report")
_SD_PREFIX = os.environ.get("VQ_SD_RAW_REPORT", "/Volumes/dart_data/raw_report")


def resolve_source(path: str) -> str:
    """Prefer the SD mirror when it holds a same-size copy; the mirror may lag the NAS."""
    if path.startswith(_NAS_PREFIX) and os.path.isdir(_SD_PREFIX):
        alt = _SD_PREFIX + path[len(_NAS_PREFIX):]
        try:
            if os.path.getsize(alt) == os.path.getsize(path):
                return alt
        except OSError:
            pass
    return path


def norm_label(s: str) -> str:
    s = (s or "").replace("&cr;", "")
    s = _WS_RE.sub("", s)
    s = re.sub(r"^(\(?[0-9IVXⅠ-Ⅹ가-하]{1,3}[\.\)])+", "", s)
    s = re.sub(r"\(주석[^)]*\)|\(주[\d,\s]*\)", "", s)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s)


def parse_amount(t: str):
    """float, 0 for a dash, EMPTY for a blank cell, None for text.
    '2,564원' reads as 2564; a cell holding several '&cr;'-separated values (supplementary
    reserve amounts under the main figure) reads as its first value."""
    segs = [x for x in re.split(r"&cr;|\n", t or "") if _WS_RE.sub("", x)]
    if len(segs) > 1:
        t = segs[0]
    t = _WS_RE.sub("", (t or "").replace("&cr;", ""))
    if t.endswith("원") and len(t) > 1:
        t = t[:-1]
    if t == "":
        return _EMPTY
    if t in ("-", "−", "–", "—", "0"):
        return 0.0
    if not _NUM_RE.match(t):
        return None
    neg = t.startswith(("(", "△", "▲", "-", "−"))
    try:
        v = float(re.sub(r"[^\d.]", "", t))
    except ValueError:
        return None
    return -v if neg else v


def _text(el) -> str:
    return "".join(el.itertext()).strip()


@dataclass
class SrcRow:
    table: int
    key: str            # normalized full label
    alt: str            # normalized last label part (two-level labels)
    label: str
    cells: list         # amounts per amount column


@dataclass
class SrcTable:
    idx: int
    basis: str
    title: str
    headers: list[str]  # header text per amount column (spaces removed)
    rows: list[SrcRow] = field(default_factory=list)
    stype: str | None = None  # BS / IS / SCE / CF, None when undecidable

    @property
    def n_amount_rows(self) -> int:
        return sum(1 for r in self.rows if any(isinstance(x, float) and x for x in r.cells))


def _grid(table) -> list[list[tuple[int, str, bool]]]:
    """Rows of (col, text, is_origin) with spans expanded."""
    occupied: dict[tuple[int, int], str] = {}
    out = []
    for r, tr in enumerate(table.iter("tr")):
        row = []
        col = 0
        for c in tr:
            if not (isinstance(c.tag, str) and c.tag.lower() in _CELL_TAGS):
                continue
            while (r, col) in occupied:
                row.append((col, occupied[(r, col)], False))
                col += 1
            try:
                cs = max(1, int(c.get("colspan") or 1))
                rs = max(1, int(c.get("rowspan") or 1))
            except ValueError:
                cs = rs = 1
            txt = _text(c)
            row.append((col, txt, True))
            for dr in range(rs):
                for dc in range(cs):
                    if dr or dc:
                        occupied[(r + dr, col + dc)] = txt
                        if dr == 0:
                            row.append((col + dc, txt, False))
            col += cs
        while (r, col) in occupied:
            row.append((col, occupied[(r, col)], False))
            col += 1
        if row:
            out.append(sorted(row))
    return out


def _parse_table(idx: int, table, basis: str, title: str) -> SrcTable | None:
    g = _grid(table)
    if not g:
        return None
    first_data = None
    amount_cols: set[int] = set()
    for i, row in enumerate(g):
        nums = [c for c, t, o in row if o and c > 0 and isinstance(parse_amount(t), float)
                and re.search(r"\d", t)]
        if nums and first_data is None:
            first_data = i
        if first_data is not None:
            amount_cols.update(nums)
    if first_data is None:
        return None
    header_rows = g[:first_data]
    note_cols = {c for row in header_rows for c, t, _ in row
                 if _WS_RE.sub("", t) in ("주석", "주석번호", "주")}
    first_amt = min(c for c in amount_cols if c not in note_cols) if amount_cols - note_cols else None
    if first_amt is None:
        return None
    width = max(c for row in g for c, _, _ in row) + 1
    cols = [c for c in range(first_amt, width) if c not in note_cols]
    headers = [_WS_RE.sub("", "".join(t for row in header_rows for cc, t, _ in row if cc == c))
               for c in cols]
    st = SrcTable(idx, basis, title, headers)
    for row in g[first_data:]:
        by_col = {c: t for c, t, o in row if o}
        parts = [by_col[c] for c in sorted(by_col) if c < first_amt and c not in note_cols
                 and by_col[c].strip()]
        label = ">".join(parts)
        cells = [parse_amount(by_col[c]) if c in by_col else _EMPTY for c in cols]
        if not label:
            # an unlabeled row carrying amounts (campaign issue #51) must still surface
            if not any(isinstance(x, float) and x for x in cells):
                continue
            label, parts = "(라벨없음)", ["(라벨없음)"]
        st.rows.append(SrcRow(idx, norm_label(label), norm_label(parts[-1]), label, cells))
    return st


_SECTION_RE = re.compile(r"(연결)?재무제표")
_TITLE_TYPES = (("SCE", re.compile(r"자본변동표")), ("CF", re.compile(r"현금흐름표")),
                ("BS", re.compile(r"재무상태표|대차대조표")), ("IS", re.compile(r"손익계산서")))


def statement_type(t: "SrcTable") -> str | None:
    """From the title table just before it, else from anchor rows."""
    title = _WS_RE.sub("", t.title)
    for code, rx in _TITLE_TYPES:
        if rx.search(title):
            return code
    keys = " ".join(r.key for r in t.rows)
    if re.search(r"기초자본|기말자본", keys):
        return "SCE"
    if re.search(r"영업활동", keys):
        return "CF"
    if re.search(r"자산총계|부채총계", keys):
        return "BS"
    if re.search(r"(당기|분기|반기)순(이익|손실|손익)", keys) and re.search(r"법인세|영업이익|영업손실|매출", keys):
        return "IS"
    return None


def load_statement_tables(path: str) -> list[SrcTable]:
    raw = open(path, "rb").read()
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("cp949", "replace")
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt, count=1)
    root = etree.fromstring(txt.encode("utf-8"), etree.HTMLParser(recover=True, encoding="utf-8"))
    tables: list[SrcTable] = []
    seen: set[int] = set()
    idx = 0
    all_tables = list(root.iter("table"))
    pos = {id(t): i for i, t in enumerate(all_tables)}
    for sec in root.iter():
        if not (isinstance(sec.tag, str) and sec.tag.lower().startswith("section")):
            continue
        t = sec.find("title")
        title = _WS_RE.sub("", _text(t)) if t is not None else ""
        if not _SECTION_RE.search(title) or "주석" in title or "요약" in title:
            continue
        # a statement sub-section (2024+ '2-1. 연결재무상태표') is handled via its parent
        basis = "consolidated" if "연결" in title else "separate"
        prev_title = ""
        for tb in sec.iter("table"):
            if id(tb) in seen:
                continue
            seen.add(id(tb))
            st = _parse_table(pos[id(tb)], tb, basis, prev_title)
            if st is None or not st.rows:
                prev_title = re.sub(r"\s+", " ", _text(tb))[:60]
                continue
            st.stype = statement_type(st)
            tables.append(st)
            idx += 1
    return tables


# Recorded but not blocking a pass: the source's own arithmetic does not close while every DB
# cell equals its source cell - the DB is faithful and the web view would show the same
# numbers (the previous full web-view standard passed these too).
INFO_KINDS = {"sce_arith", "zero_row"}


@dataclass
class Result:
    verdict: str                      # clean | mismatch | no_structure | error
    counts: Counter
    findings: list[dict]

    def summary(self) -> dict:
        return {"verdict": self.verdict, **dict(self.counts)}


def _finding(kind: str, key, **kw) -> dict:
    st, basis, ts = key
    return {"kind": kind, "statement": st, "basis": basis, "table_seq": ts, **kw}


def compare(db_rows: list[dict], tables: list[SrcTable]) -> Result:
    """db_rows: report_lines dicts (statement, basis, table_seq, row_order, label_raw,
    col_index, value_won, is_cumulative)."""
    counts: Counter = Counter()
    findings: list[dict] = []
    if not tables:
        return Result("no_structure", counts, [{"kind": "no_structure"}])
    groups: dict[tuple, list[dict]] = {}
    for r in db_rows:
        if r["statement"] in ("BS", "IS", "CF", "SCE"):
            groups.setdefault((r["statement"], r["basis"], r["table_seq"]), []).append(r)
    used_tables: set[int] = set()
    for key, items in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        st_code, basis, _ = key
        seq, seen = [], set()
        for r in sorted(items, key=lambda r: (r["row_order"] is None, r["row_order"] or 0)):
            k = (r["row_order"], r["label_raw"])
            if k not in seen:
                seen.add(k)
                seq.append(k)
        dkeys = [norm_label(l) for _, l in seq]
        cand = [t for t in tables if t.basis == basis and t.stype in (st_code, None)] \
            or [t for t in tables if t.basis == basis] or tables
        dset = set(dkeys)
        score = {t.idx: sum(1 for r in t.rows if r.key in dset or r.alt in dset) for t in cand}
        if not score or max(score.values()) == 0:
            findings.append(_finding("no_table", key, rows=len(seq)))
            counts["no_table"] += 1
            continue
        top = max(score.values())
        dvals = {abs(int(r["value_won"])) for r in items if r["value_won"]}

        def vhits(t: SrcTable) -> int:
            n = 0
            for row in t.rows:
                for x in row.cells:
                    if isinstance(x, float) and x and any(round(abs(x) * s) in dvals for s in _SCALES):
                        n += 1
            return n
        best = max((t for t in cand if score[t.idx] >= 0.8 * top), key=lambda t: (vhits(t), score[t.idx]))
        bpos = cand.index(best)
        win_tables = [best]
        # split statements: the neighbours inside the same section that also match
        for nb in cand[bpos + 1: bpos + 3]:
            if score[nb.idx] >= 2 and score[nb.idx] >= 0.5 * len(nb.rows):
                win_tables.append(nb)
            else:
                break
        for t in win_tables:
            used_tables.add(t.idx)
        win = [r for t in win_tables for r in t.rows]
        wkeys = [r.key for r in win]
        sm = difflib.SequenceMatcher(None, dkeys, wkeys, autojunk=False)
        d2s: dict[int, int] = {}
        for a, b, n in sm.get_matching_blocks():
            for k in range(n):
                d2s[a + k] = b + k
        taken = set(d2s.values())
        free: dict[str, list[int]] = {}
        for j, r in enumerate(win):
            if j not in taken:
                free.setdefault(r.key, []).append(j)
                if r.alt != r.key:
                    free.setdefault(r.alt, []).append(j)
        for i in range(len(seq)):
            if i in d2s:
                continue
            for j in free.get(dkeys[i], []):
                if j not in taken:
                    d2s[i] = j
                    taken.add(j)
                    break
        rowmap = {seq[i]: win[j] for i, j in d2s.items()}

        # expected source column(s) per DB col_index
        def col_for(ci: int, cumulative: bool | None, t_headers: list[str]) -> list[int]:
            if st_code == "SCE" or ci != 0:
                return [ci]
            groups = period_groups(t_headers)
            if any("누적" in h for h in t_headers):
                want = "누적" if cumulative else "3개월"
                for g in groups:
                    if want in t_headers[g[0]]:
                        return g
            return groups[0] if groups else [0]

        headers_of = {t.idx: t.headers for t in win_tables}
        cand_s: Counter = Counter()
        for r in items:
            row = rowmap.get((r["row_order"], r["label_raw"]))
            if not row or not r["value_won"] or "주당" in r["label_raw"]:
                continue
            for k in col_for(r["col_index"] or 0, r.get("is_cumulative"), headers_of[row.table]):
                x = row.cells[k] if k < len(row.cells) else None
                if isinstance(x, float) and x:
                    for s in _SCALES:
                        if abs(x * s - r["value_won"]) < 1:
                            cand_s[s] += 1
        scale = cand_s.most_common(1)[0][0] if cand_s else 1

        # Value-assisted re-pairing: a label repeated in every year block ('Ⅲ. 반기순이익')
        # can be aligned to the wrong block. When a DB row's cells disagree with its source
        # row, move it to another same-label source row where every DB cell agrees.
        cells_of: dict[tuple, list[dict]] = {}
        for r in items:
            if r["value_won"] is not None:
                cells_of.setdefault((r["row_order"], r["label_raw"]), []).append(r)

        def agrees(rs: list[dict], row: SrcRow) -> bool:
            for r in rs:
                sc_ = 1 if "주당" in r["label_raw"] else scale
                ks = col_for(r["col_index"] or 0, r.get("is_cumulative"), headers_of[row.table])
                xs = [row.cells[k] for k in ks if k < len(row.cells)]
                if not any(isinstance(x, float) and abs(x * sc_ - r["value_won"]) <= (1.0 if sc_ == 1 else 0.5)
                           for x in xs) and not (r["value_won"] == 0 and all(x in (0.0, _EMPTY) for x in xs)):
                    return False
            return True

        # 1) release every pairing that disagrees, 2) give each released row the first free
        # same-label source row that agrees (a wrong pairing may hold the right row hostage)
        bad = [i for i, k in enumerate(seq) if cells_of.get(k) and i in d2s
               and not agrees(cells_of[k], win[d2s[i]])]
        bad += [i for i, k in enumerate(seq) if cells_of.get(k) and i not in d2s]
        old_pair = {i: d2s.pop(i) for i in bad if i in d2s}
        used = set(d2s.values())
        for i in bad:
            key_i = dkeys[i]
            for j, row in enumerate(win):
                if j not in used and (row.key == key_i or row.alt == key_i) and agrees(cells_of[seq[i]], row):
                    d2s[i] = j
                    used.add(j)
                    break
        for i, j in old_pair.items():  # no agreeing row: keep the original pairing if still free
            if i not in d2s and j not in used:
                d2s[i] = j
                used.add(j)
        rowmap = {seq[i]: win[j] for i, j in d2s.items()}
        counts["rows"] += len(seq)
        covered: dict[tuple, set[int]] = {}
        for r in items:
            rk = (r["row_order"], r["label_raw"])
            row = rowmap.get(rk)
            if row is None or r["value_won"] is None:
                continue
            counts["cells"] += 1
            per_share = "주당" in r["label_raw"]
            s = 1 if per_share else scale
            tol = 1.0 if per_share else 0.5
            ks = col_for(r["col_index"] or 0, r.get("is_cumulative"), headers_of[row.table])
            covered.setdefault(rk, set()).update(ks)
            xs = [row.cells[k] if k < len(row.cells) else "OOR" for k in ks]
            ok = any(isinstance(x, float) and abs(x * s - r["value_won"]) <= tol for x in xs)
            if not ok and r["value_won"] == 0 and all(x in (0.0, _EMPTY) for x in xs):
                ok = True
            k = ks[0]
            x = next((y for y in xs if isinstance(y, float)), xs[0])
            if not ok:
                found = [c for c, y in enumerate(row.cells)
                         if isinstance(y, float) and abs(y * s - r["value_won"]) <= tol]
                flipped = [c for c, y in enumerate(row.cells)
                           if isinstance(y, float) and y and abs(-y * s - r["value_won"]) <= tol]
                findings.append(_finding(
                    "value", key, label=r["label_raw"][:200], row_order=r["row_order"],
                    col_index=r["col_index"], db=r["value_won"],
                    src=x if isinstance(x, float) else str(x), src_col=k,
                    header=(headers_of[row.table][k] if k < len(headers_of[row.table]) else None),
                    found_at=found, flipped_at=flipped, scale=s))
                counts["value"] += 1
        matched = set(d2s.values())
        lo, hi = (min(matched), max(matched)) if matched else (0, -1)
        for j in range(lo, hi + 1):
            if j in matched:
                continue
            r = win[j]
            ks = col_for(0, True, headers_of[r.table]) if st_code != "SCE" else []
            dash_only = (any(x == 0.0 for x in r.cells if isinstance(x, float))
                         and not any(isinstance(x, float) and x for x in r.cells))
            if dash_only:
                # all-dash row absent from the DB: value-neutral, but the campaign has been
                # registering these (issues #103~) - surface it and let the reviewer decide
                findings.append(_finding("zero_row", key, label=r.label[:200]))
                counts["zero_row"] += 1
            elif st_code == "SCE":
                if any(isinstance(x, float) and x for x in r.cells):
                    findings.append(_finding("missing_row", key, label=r.label[:200], cells=r.cells[:12]))
                    counts["missing_row"] += 1
            else:
                if any(isinstance(r.cells[k], float) and r.cells[k] for k in ks if k < len(r.cells)):
                    findings.append(_finding("missing_row", key, label=r.label[:200], cells=r.cells[:6]))
                    counts["missing_row"] += 1
                elif any(isinstance(x, float) and x for x in r.cells):
                    counts["prior_only"] += 1
        for i in range(len(seq)):
            if i not in d2s:
                findings.append(_finding("extra_row", key, label=str(seq[i][1])[:200], row_order=seq[i][0]))
                counts["extra_row"] += 1
        if st_code == "SCE":
            eff = {id(r): list(r.cells) for r in win}
            for r in items:
                row = rowmap.get((r["row_order"], r["label_raw"]))
                ci = r["col_index"] or 0
                if row is not None and r["value_won"] is not None and ci < len(row.cells):
                    eff[id(row)][ci] = r["value_won"] / scale
            eff_rows = [SrcRow(r.table, r.key, r.alt, r.label, eff[id(r)]) for r in win]
            bad_cols = set()
            for f in sce_identity(eff_rows):
                bad_cols.add(f["col"])
                kind = {"sign": "sign_omitted", "shift": "sce_identity"}.get(f["explain"], "sce_arith")
                f["header"] = next((t.headers[f["col"]] for t in win_tables if f["col"] < len(t.headers)), None)
                f["scale"] = scale
                findings.append(_finding(kind, key, **f))
                counts[kind] += 1
            # DB = -source on a cell and the arithmetic holds with the DB sign: the loader
            # restored a sign the source dropped (R162) - proven, not a defect.
            for f in [f for f in findings if f.get("kind") == "value" and f["statement"] == "SCE"
                      and f["basis"] == basis and f["table_seq"] == key[2]]:
                if f["src_col"] in f.get("flipped_at", []) and f["src_col"] not in bad_cols:
                    findings.remove(f)
                    counts["value"] -= 1
                    counts["sign_restored"] += 1
        if st_code == "BS":
            f = bs_identity(items, scale)
            if f:
                findings.append(_finding("bs_identity", key, **f))
                counts["bs_identity"] += 1
        if st_code == "SCE":
            for rk, row in rowmap.items():
                for c, x in enumerate(row.cells):
                    if isinstance(x, float) and x and c not in covered.get(rk, set()):
                        findings.append(_finding("uncovered_cell", key, label=row.label[:200], src_col=c,
                                                 header=row_table_header(win_tables, row, c), src=x))
                        counts["uncovered_cell"] += 1
    for t in tables:
        # only tables recognisably a statement: banks/insurers put income breakdowns
        # (예치금이자·증권이자 …) in the statement section too, and those are not loaded
        if t.idx not in used_tables and t.n_amount_rows >= 3 and t.stype is not None \
                and not _is_appropriation(t):
            findings.append({"kind": "unmatched_table", "basis": t.basis, "table": t.idx,
                             "title": t.title, "first_rows": [r.label[:40] for r in t.rows[:4]]})
            counts["unmatched_table"] += 1
    blocking = [f for f in findings if f["kind"] not in INFO_KINDS]
    return Result("clean" if not blocking else "mismatch", counts, findings)


_OPEN_RE = re.compile(r"기초|期初")
_CLOSE_RE = re.compile(r"기말|期末")
# Matched against normalized labels (no spaces/parentheses).
_SUBTOTAL_STRONG = re.compile(r"^총|합계|소계|총계")
_SUBTOTAL_LOOSE = re.compile(
    r"^총|합계|소계|총계|계$|총포괄|자본의?변동|자본증가|증가감소$|^기타포괄손익$|^소유주와의거래")


def _num(x) -> float:
    return x if isinstance(x, float) else 0.0


def _kept_sum(vals: list[float], totals: list[bool], start: float, tol: float,
              forward: bool, backward: bool) -> float:
    """Sum of the change rows of one column, leaving out
    - subtotals: a value equal to the sum of a run of kept rows right before it (backward) or of
      the rows right after it (forward, parent row first) - 2+ rows, or 1 row when the label
      looks like a total. Decided by value because total labels vary too much;
    - balance rows: a value equal to the running balance (restated opening, interim balance)."""
    n = len(vals)
    fwd = [False] * n
    if forward:
        for i in range(n):
            if not vals[i]:
                continue
            acc, k = 0.0, 0
            for j in range(i + 1, n):
                if not vals[j]:
                    continue
                acc += vals[j]
                k += 1
                if (k >= 2 or totals[i]) and abs(acc - vals[i]) <= tol:
                    fwd[i] = True
                    break
    kept: list[float] = []
    for i, v in enumerate(vals):
        if not v or fwd[i]:
            continue
        if abs(start + sum(kept) - v) <= tol and (kept or abs(v - start) <= tol):
            continue
        if backward:
            acc, is_sub = 0.0, False
            for k in range(1, len(kept) + 1):
                acc += kept[-k]
                if (k >= 2 or totals[i]) and abs(acc - v) <= tol:
                    is_sub = True
                    break
            if is_sub:
                continue
        kept.append(v)
    return sum(kept)


def sce_identity(rows: list[SrcRow]) -> list[dict]:
    """Per column: opening + changes = closing within each year block, and closing + rows up
    to the next opening (restatements) = that opening when the dates are adjacent. Catches
    sign errors the source itself carries (R162), which a cell-by-cell comparison cannot see
    when the DB follows the source. `rows` should carry DB values where the DB has the cell,
    so a sign the loader already restored is judged on the loaded value."""
    marks = []
    for i, r in enumerate(rows):
        lab = _WS_RE.sub("", r.label)
        if _OPEN_RE.search(lab) and not _CLOSE_RE.search(lab):
            marks.append(("open", i))
        elif _CLOSE_RE.search(lab):
            marks.append(("close", i))
    out = []
    width = max((len(r.cells) for r in rows), default=0)

    def check(a: int, b: int, kind: str) -> None:
        mids = rows[a + 1: b]
        tol = len(mids) + 2
        totals = [bool(_SUBTOTAL_LOOSE.search(r.key) or _SUBTOTAL_LOOSE.search(r.alt)) for r in mids]
        for c in range(width):
            start = _num(rows[a].cells[c]) if c < len(rows[a].cells) else 0.0
            end = _num(rows[b].cells[c]) if c < len(rows[b].cells) else 0.0
            vals = [_num(r.cells[c]) if c < len(r.cells) else 0.0 for r in mids]
            if not start and not end and not any(vals):
                continue
            def closes(st: float, vs: list[float], en: float) -> bool:
                return any(abs(st + _kept_sum(vs, totals, st, tol, f, bk) - en) <= tol
                           for f, bk in ((True, True), (False, True), (True, False)))

            if closes(start, vals, end):
                continue
            total = start + _kept_sum(vals, totals, start, tol, True, True)
            f = {"check": kind, "col": c, "from": rows[a].label[:60], "to": rows[b].label[:60],
                 "start": start, "end": end, "sum": total, "diff": end - total}
            # Which single change closes the column? A sign on one cell (R162: the source
            # dropped parentheses) or one row whose values sit one column off (shifted cells).
            signs = []
            if start and closes(-start, vals, end):
                signs.append((rows[a].label, start))
            if end and closes(start, vals, -end):
                signs.append((rows[b].label, end))
            for i, v in enumerate(vals):
                if v and closes(start, vals[:i] + [-v] + vals[i + 1:], end):
                    signs.append((mids[i].label, v))
            shifts = []
            for i, r in enumerate(mids):
                for dc in (-1, 1):
                    k = c + dc
                    if 0 <= k < len(r.cells) and _num(r.cells[k]) and _num(r.cells[k]) != vals[i]:
                        if closes(start, vals[:i] + [_num(r.cells[k])] + vals[i + 1:], end):
                            shifts.append((r.label, dc))
            if len(signs) == 1 and not shifts:
                f.update(explain="sign", row=signs[0][0][:80], value=signs[0][1])
            elif shifts:
                f.update(explain="shift", row=shifts[0][0][:80], shift=shifts[0][1])
            else:
                f.update(explain="source_arithmetic")
            out.append(f)

    for (k1, i1), (k2, i2) in zip(marks, marks[1:]):
        if k1 == "open" and k2 == "close":
            check(i1, i2, "flow")
        elif k1 == "close" and k2 == "open" and _consecutive(rows[i1].label, rows[i2].label):
            check(i1, i2, "carry")
    return out


_DATE_RE = re.compile(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})")


def _consecutive(close_label: str, open_label: str) -> bool:
    """Closing and opening dates are adjacent (2023.12.31 -> 2024.01.01). Blocks of a quarterly
    SCE (prior-year quarter, then current year) or reversed order do not carry over."""
    import datetime as _dt
    a, b = _DATE_RE.search(close_label), _DATE_RE.search(open_label)
    if not (a and b):
        return False
    try:
        d1 = _dt.date(*map(int, a.groups()))
        d2 = _dt.date(*map(int, b.groups()))
    except ValueError:
        return False
    return (d2 - d1).days == 1


def bs_identity(items: list[dict], scale: int) -> dict | None:
    """자산총계 = 부채총계 + 자본총계 on the DB's current values (one rounding unit per term)."""
    cur = {}
    for r in items:
        if r["col_index"] in (0, None) and r["value_won"] is not None:
            k = norm_label(r["label_raw"])
            for name in ("자산총계", "부채총계", "자본총계"):
                # '자본과부채총계' / '부채와자본총계' are the grand total, not either side
                other = "자본" if name == "부채총계" else "부채" if name == "자본총계" else None
                if k.endswith(name) and name not in cur and not (other and other in k):
                    cur[name] = r["value_won"]
    if len(cur) < 3:
        return None
    diff = cur["자산총계"] - cur["부채총계"] - cur["자본총계"]
    if abs(diff) > 3 * scale:
        return {"assets": cur["자산총계"], "liabilities": cur["부채총계"], "equity": cur["자본총계"], "diff": diff}
    return None


def period_groups(headers: list[str]) -> list[list[int]]:
    """Consecutive amount columns sharing one header text form one period (detail/subtotal
    sub-columns under '제65(당)기'). Without header text every column is its own period."""
    groups: list[list[int]] = []
    for k, h in enumerate(headers):
        if groups and h.strip() and headers[groups[-1][-1]] == h:
            groups[-1].append(k)
        else:
            groups.append([k])
    return groups


_APPROPRIATION_RE = re.compile(r"처분계산서|처리계산서|미처분이익잉여금|미처리결손금|처분전이익잉여금|처분예정")


def _is_appropriation(t: SrcTable) -> bool:
    """Statement of appropriation of retained earnings: in the statement section, not loaded."""
    first = t.rows[0].key if t.rows else ""
    return bool(_APPROPRIATION_RE.search(_WS_RE.sub("", t.title)) or _APPROPRIATION_RE.search(first))


def row_table_header(win_tables: list[SrcTable], row: SrcRow, c: int) -> str | None:
    for t in win_tables:
        if t.idx == row.table:
            return t.headers[c] if c < len(t.headers) else None
    return None


DB_SQL = """
    SELECT statement, basis, table_seq, row_order, label_raw, col_index, value_won, is_cumulative
    FROM report_lines WHERE rcept_no = :r AND statement IN ('BS', 'IS', 'CF', 'SCE')"""


def compare_filing(conn, rcept: str, xml_path: str) -> Result:
    from sqlalchemy import text
    rows = [dict(r) for r in conn.execute(text(DB_SQL), {"r": rcept}).mappings()]
    try:
        tables = load_statement_tables(resolve_source(xml_path))
    except Exception as exc:  # unreadable source: the model looks at it
        return Result("error", Counter(), [{"kind": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}])
    return compare(rows, tables)
