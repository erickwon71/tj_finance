"""Machine comparison of one filing's '사업의 내용' tables: DART source XML vs DB biz_section_tables.

Design: docs/plans/verification_note_biz_expansion_design_2026-10-27.md (scope 'biz').

Independent of the production reader (fin2/extract/biz_section.py reads with an XML parser and
its own span expansion): this module parses the source with lxml's HTML parser and expands
rowspan/colspan itself, so a reader bug cannot make both sides agree. Layer 2 stores the PRINTED
grid (R0-2), so the check is a text comparison of grids; whitespace and the `&cr;` line-break
marker are ignored on both sides, nothing else.

Per stored table (a biz_section_tables row):
- the source table with the best cell overlap (>= MATCH_MIN) is its counterpart;
- equal grids -> clean; otherwise `cell` findings (same shape) or `row_missing` / `row_extra`
  (shape differs, rows aligned with difflib);
- no counterpart -> `extra_table`.
Source numeric tables inside the '사업의 내용' section that no stored table matches are NOT
findings: layer 2 stores a selected subset by design (find_biz_subsections / catalog rules) and
which source tables count as targets is a user decision still open (design doc 6-1). They are
only counted (`unstored_numeric_tables`).
Findings err toward "mismatch": a false mismatch costs review time, a false clean hides a defect.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field

from lxml import etree

from fin2.verification import machine_compare as mc

# mb1 (2026-10-27): first version.
# mb2 (2026-10-27): empty cells are ignored when grids are compared. Layer 2 keeps a leading ''
# cell on single-cell unit tables ("(단위 : 백만원)") that the source does not have (138 row pairs in
# the first 280 mismatching filings); that is a layout trace, not a printed value (R0-2). A table
# that differs only in where its empty cells sit is counted (`empty_shape`), never a finding.
TOOL_VERSION = "mb2"

MATCH_MIN = 0.5            # minimum cell-set Jaccard for a source table to count as counterpart
MAX_FINDINGS = 400         # per filing; more than this is a parser problem, not a list to page

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d")


def norm(s) -> str:
    """Comparison form of a cell: no whitespace, no `&cr;`."""
    return _WS.sub("", str(s if s is not None else "").replace("&cr;", ""))


@dataclass
class SrcGrid:
    idx: int                       # document order of the <table>
    cells: list                    # rows of normalized text, spans expanded
    in_section: bool = False       # inside a '사업의 내용' section
    cellset: frozenset = field(default_factory=frozenset)

    @property
    def numeric(self) -> bool:
        return any(_NUM.search(c) for r in self.cells for c in r)


def load_source_grids(path: str) -> tuple[list[SrcGrid], bool]:
    """All tables of the document as normalized grids + whether a '사업의 내용' section exists."""
    raw = open(path, "rb").read()          # the caller resolves the SD mirror (no NAS stat here)
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("cp949", "replace")
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt, count=1)
    root = etree.fromstring(txt.encode("utf-8"), etree.HTMLParser(recover=True, encoding="utf-8"))
    els = list(root.iter("table"))           # keeps the element proxies alive: id() stays stable
    grids: list[SrcGrid] = []
    by_el: dict[int, SrcGrid] = {}
    for i, tb in enumerate(els):
        rows = [[norm(c[1]) for c in row] for row in mc._grid(tb)]
        if not rows:
            continue
        g = SrcGrid(idx=i, cells=rows, cellset=frozenset(c for r in rows for c in r if c))
        grids.append(g)
        by_el[id(tb)] = g
    found = False
    for sec in root.iter():
        if not (isinstance(sec.tag, str) and sec.tag.lower().startswith("section")):
            continue
        t = sec.find("title")
        title = norm(mc._text(t)) if t is not None else ""
        if "사업의내용" not in title or "주석" in title:
            continue
        found = True
        for tb in sec.iter("table"):
            g = by_el.get(id(tb))
            if g is not None:
                g.in_section = True
    return grids, found


@dataclass
class Result:
    verdict: str = "clean"          # clean / mismatch / no_source / no_structure / error
    findings: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _row_label(row: list) -> str:
    return next((c for c in row if c), "")[:120]


def _drop_empty(grid: list) -> list:
    return [[c for c in row if c] for row in grid]


def _diff_grids(db: list, src: list) -> list[dict]:
    """Cell / row level differences of two normalized grids (db vs source), empty cells ignored
    (so `col` counts non-empty cells of the row)."""
    db, src = _drop_empty(db), _drop_empty(src)
    out: list[dict] = []
    if len(db) == len(src) and all(len(a) == len(b) for a, b in zip(db, src)):
        for r, (a, b) in enumerate(zip(db, src)):
            for c, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    out.append({"kind": "cell", "row": r, "col": c, "label": _row_label(src[r]),
                                "header": src[0][c] if src and c < len(src[0]) else "",
                                "db": x, "src": y})
        return out
    dbt = [tuple(r) for r in db]
    srt = [tuple(r) for r in src]
    sm = difflib.SequenceMatcher(None, dbt, srt, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                a, b = db[i1 + k], src[j1 + k]
                if len(a) == len(b):
                    for c, (x, y) in enumerate(zip(a, b)):
                        if x != y:
                            out.append({"kind": "cell", "row": j1 + k, "col": c,
                                        "label": _row_label(b), "header": "", "db": x, "src": y})
                else:
                    out.append({"kind": "row_missing", "row": j1 + k, "label": _row_label(b),
                                "src": list(b)})
                    out.append({"kind": "row_extra", "row": i1 + k, "label": _row_label(a),
                                "db": list(a)})
            continue
        for k in range(j1, j2):
            if op in ("replace", "insert"):
                out.append({"kind": "row_missing", "row": k, "label": _row_label(src[k]),
                            "src": list(src[k])})
        for k in range(i1, i2):
            if op in ("replace", "delete"):
                out.append({"kind": "row_extra", "row": k, "label": _row_label(db[k]),
                            "db": list(db[k])})
    return out


def compare(db_tables: list[dict], grids: list[SrcGrid], section_found: bool) -> Result:
    """db_tables: [{table_ord, domain, metric, grid}] of one filing."""
    res = Result()
    used: set[int] = set()
    counts = {"db_tables": len(db_tables), "exact": 0, "differs": 0, "extra_table": 0}
    for t in db_tables:
        dbg = [[norm(c) for c in row] for row in (t["grid"] or [])]
        dbset = frozenset(c for r in dbg for c in r if c)
        best, bi = 0.0, None
        for g in grids:
            j = _jaccard(dbset, g.cellset)
            if j > best:
                best, bi = j, g
        if bi is None or best < MATCH_MIN:
            counts["extra_table"] += 1
            res.findings.append({"kind": "extra_table", "table_ord": t["table_ord"],
                                 "domain": t["domain"], "metric": t["metric"], "match": round(best, 2),
                                 "head": [c for r in dbg[:2] for c in r][:8]})
            continue
        used.add(bi.idx)
        if dbg == bi.cells:
            counts["exact"] += 1
            continue
        if _drop_empty(dbg) == _drop_empty(bi.cells):
            counts["exact"] += 1
            counts["empty_shape"] = counts.get("empty_shape", 0) + 1
            continue
        counts["differs"] += 1
        for d in _diff_grids(dbg, bi.cells):
            res.findings.append({**d, "table_ord": t["table_ord"], "domain": t["domain"],
                                 "metric": t["metric"], "match": round(best, 2),
                                 "src_table": bi.idx})
    counts["unstored_numeric_tables"] = sum(1 for g in grids
                                            if g.in_section and g.numeric and g.idx not in used)
    counts["section_numeric_tables"] = sum(1 for g in grids if g.in_section and g.numeric)
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
    """Compare one filing against its source file (conn: SQLAlchemy connection)."""
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT table_ord, domain, metric, grid FROM biz_section_tables "
        "WHERE rcept_no = :r ORDER BY table_ord"), {"r": rcept}).mappings().all()
    grids, found = load_source_grids(xml_path)
    return compare([dict(r) for r in rows], grids, found)


def to_json(res: Result) -> tuple[str, str]:
    return (json.dumps(res.counts, ensure_ascii=False),
            json.dumps(res.findings, ensure_ascii=False, default=str))
