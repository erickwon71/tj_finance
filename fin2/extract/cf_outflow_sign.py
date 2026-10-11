"""R232 — CF "현금유출액" sections printed as magnitudes: layer-3 sign (2026-10-11).

Many cash-flow statements split investing / financing into `…현금유입액` and `…현금유출액`
sections and print the outflow items without parentheses — the printed number is the size of
the outflow, not a signed flow (the section header may or may not carry parentheses):

    재무활동으로 인한 현금유출액     (6,166,384,260)
      배당금의 지급                     413,409,970     ← an outflow of 413,409,970

Layer 2 keeps the printed positive (R0-2). This rule is layer 3: it writes the signed value as a
`layer3_cell_corrections` row (via the extractor's rules-on run, `as_printed.STEPS`).

## Proof (docs/PARSING_RULES.md R232, docs/plans/r232_cf_outflow_section_sign_2026-10-11.md)

Section = the CF rows of one (basis, table_seq, col_index) whose section_path ends with an
outflow header. S = sum of its children, H = the header row's value, T = the activity total,
I = the sum of the sibling inflow section.

- magnitude convention: (H<0 and S≈−H) or (H>0 and S≈H) or (T≈I−S and not T≈I+S)
- signed convention:    (H<0 and S≈H) or (T≈I+S and not T≈I−S)

Only the magnitude convention is proven → every child and the header become −|value|: the
section's name says outflow (R232-c, user decision 2026-10-11 — a parenthesised dividend inside
such a section is still money paid out; 20150515002674 subtracted it in its own subtotal, a
source arithmetic slip, not a reduction of the outflow). (R232-b — flip without a proof when H<0 and every child is positive — was rejected: in
pre-2015 tables H itself is often wrong, docs/PARSING_RULES.md R232.)

## Untouched (R6 — leave missing / as printed rather than guess)

- signed convention proven, or both conventions proven;
- magnitude proven but every non-zero child is negative (inflows printed negative too — a
  table we do not understand);
- no proof and not the R232-b shape;
- non-cash adjustment sections (`현금유출이 없는 비용`, `현금유출입이 없는 손익`) and headers
  without an activity word (영업/투자/재무) in the header or its parent;
- grandchildren (detail rows under an outflow item); XBRL rows (taxonomy signs, not print);
- sections with a `frozen` line (a cell another rule already corrected — the DB backfill) whose
  corrected sign is not the sign this rule would give. (Same sign, other magnitude — R18 takes the
  tag amount within 1% — keeps that row: in the extractor R18 runs after this rule and wins.)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, List, NamedTuple, Optional

from loguru import logger

_OUT_RE = re.compile(r"현\s*금\s*유\s*출(?!\s*입)")
_IN_RE = re.compile(r"현\s*금\s*유\s*입")
_NONCASH_RE = re.compile(r"없|업\s*는|않|아\s*니|수\s*반|유\s*출\s*입")
_ACTIVITY_RE = re.compile(r"영\s*업|투\s*자|재\s*무")
_PREFIX_RE = re.compile(r"^[\s\dⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX.()]+")
_SPACE_RE = re.compile(r"[\s:：]")

RULE = "R232_cf_outflow_sign"


class OutflowCorrection(NamedTuple):
    basis: Optional[str]
    table_seq: Optional[int]
    row_order: Optional[int]
    col_index: Optional[int]
    label_raw: str
    old_value: int
    new_value: int
    proof: str             # which identity proved the convention (human-checkable)


def _norm(label: Optional[str]) -> str:
    return _SPACE_RE.sub("", _PREFIX_RE.sub("", label or ""))


def is_outflow_header(segment: str, parent: str = "") -> bool:
    return (bool(_OUT_RE.search(segment)) and not _NONCASH_RE.search(segment)
            and bool(_ACTIVITY_RE.search(segment) or _ACTIVITY_RE.search(parent)))


def _is_inflow_header(segment: str) -> bool:
    return (bool(_IN_RE.search(segment)) and not _NONCASH_RE.search(segment)
            and not _OUT_RE.search(segment))


def _split(path: Optional[str]) -> list[str]:
    return path.split(">") if path else []


def _join(segs: list[str]) -> str:
    return ">".join(segs)


def _unit(values: Iterable[int]) -> int:
    vals = [v for v in values if v]
    u = 1
    for p in (10, 100, 1_000, 10_000, 100_000, 1_000_000):
        if vals and all(v % p == 0 for v in vals):
            u = p
    return u


def _close(a: int, b: int, tol: int) -> bool:
    return abs(a - b) <= tol


def _eligible(ln) -> bool:
    return (getattr(ln, "statement", None) == "CF"
            and getattr(ln, "value_won", None) is not None
            and getattr(ln, "header_hint", None) is None
            and getattr(ln, "unit_source", None) != "xbrl")


def repair_cf_outflow_section_signs(lines: List, *,
                                    frozen: Optional[dict] = None) -> List[OutflowCorrection]:
    """Sign outflow-section cells in place (R232).

    `frozen` = {id(line): corrected value} of cells another rule already corrected (DB backfill).
    They count in the proof with their printed value and are never changed here; a section is
    skipped when such a cell's corrected sign is not the one this rule would give.
    """
    frozen = frozen or {}
    by_col: dict[tuple, list] = defaultdict(list)
    for ln in lines:
        if _eligible(ln):
            by_col[(ln.basis, getattr(ln, "table_seq", None), ln.col_index)].append(ln)

    out: List[OutflowCorrection] = []
    for rows in by_col.values():
        sections: dict[str, list] = defaultdict(list)
        inflows: set[str] = set()
        for ln in rows:
            segs = _split(ln.section_path)
            if segs and is_outflow_header(segs[-1], segs[-2] if len(segs) > 1 else ""):
                sections[ln.section_path].append(ln)
            elif segs and _is_inflow_header(segs[-1]):
                inflows.add(ln.section_path)
        for path, children in sections.items():
            out.extend(_repair_section(rows, inflows, path, _split(path), children, frozen))
    if out:
        logger.debug(f"[report_lines/R232] CF 유출 구간 부호 {len(out)}셀")
    return out


def _row_before(rows, parent: str, label: str, before: int):
    """The nearest row above `before` whose path is `parent` and whose label is `label`."""
    hits = [r for r in rows
            if (r.section_path or "") == parent and _norm(r.label_raw) == label
            and (r.row_order if r.row_order is not None else 0) < before]
    return max(hits, key=lambda r: r.row_order or 0) if hits else None


def _repair_section(rows, inflows, path, segs, children, frozen):
    values = [c.value_won for c in children]
    nonzero = [v for v in values if v]
    if not nonzero:
        return []
    s = sum(values)
    first = min((c.row_order if c.row_order is not None else 0) for c in children)
    parent = _join(segs[:-1])
    header = _row_before(rows, parent, _norm(segs[-1]), first)
    h = header.value_won if header is not None else None
    total = inflow = None
    if len(segs) >= 2:
        t_row = _row_before(rows, _join(segs[:-2]), _norm(segs[-2]), first)
        total = t_row.value_won if t_row is not None else None
        sibs = [p for p in inflows if _split(p)[:-1] == segs[:-1]]
        if len(sibs) == 1:
            inflow = sum(r.value_won for r in rows if r.section_path == sibs[0])
    extra = [x for x in (h, total, inflow) if x]
    tol = max(1_000, _unit(nonzero + extra) * len(children))

    mag, sig = [], []
    if h is not None and h < 0 and _close(s, -h, tol):
        mag.append(f"header {h:,} = -({s:,})")
    if h is not None and h > 0 and _close(s, h, tol):
        mag.append(f"header {h:,} = {s:,}")
    if h is not None and h < 0 and _close(s, h, tol):
        sig.append("header")
    if total is not None and inflow is not None:
        minus, plus = _close(total, inflow - s, tol), _close(total, inflow + s, tol)
        if minus and not plus:
            mag.append(f"activity {total:,} = {inflow:,} - {s:,}")
        if plus and not minus:
            sig.append("activity")

    if not mag or sig or all(v < 0 for v in nonzero):
        return []
    proof = "; ".join(mag)

    targets = [c for c in children if c.value_won > 0]
    if h is not None and h > 0:
        targets.append(header)
    if any(id(ln) in frozen and (frozen[id(ln)] is None or (frozen[id(ln)] > 0) != (ln.value_won < 0))
           for ln in targets):
        return []           # another rule decided the other sign (or a drop) for a cell here
    out = []
    for ln in targets:
        if id(ln) in frozen:
            continue
        old = ln.value_won
        ln.value_won = -old
        out.append(OutflowCorrection(ln.basis, getattr(ln, "table_seq", None), ln.row_order,
                                     ln.col_index, (ln.label_raw or "").strip(), old, -old, proof))
    return out
