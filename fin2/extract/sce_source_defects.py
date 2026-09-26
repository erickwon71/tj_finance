"""R183 — SCE cells that are wrong **in the DART source itself**, corrected per rcept
and only when the statement's own identities prove the correction (2026-09-26,
verification fix batch #29, user-confirmed per filing).

Same family as R159 (`parser/xml/table_extractor.py::_SOURCE_TYPO_CELL_FIXES`) and
R162-manual (`sce_sign_repair._MANUAL_SIGN_FIXES`): a filer's typo follows no rule, so
it is listed by rcept rather than generalised. What is new here is the **load-time
guard** — every listed correction is re-proved against the table on every reload and
silently skipped (with a warning) when the proof no longer holds, so a changed source
or parser never gets overwritten with a stale "fix".

Three kinds of source defect:

1. `_VALUE_FIXES` — a printed cell value is wrong (typo / opening+closing summed).
   Guard: with the new value BOTH (a) the column roll-forward of its block
   (opening + Σmovements = closing) and (b) the row identity (Σ child columns =
   parent column, XBRL `col_label` hierarchy) close exactly, and with the old value
   neither does.
2. `_ROW_MOVES` — a movement row printed inside the wrong fiscal-year block. SCE rows
   carry their period only through their block position (row_order between an
   opening and a closing row), so the fix is a row_order change.
   Guard: for every component column the row fills (total columns excluded — they
   can carry unrelated sign defects), the source block and the target block both fail
   to close before the move and both close exactly after it.
3. `_ROW_DROPS` — a movement row printed in a block where the transaction did not
   happen (duplicated from the next block). The row is removed.
   Guard (post-check): it runs BEFORE the sign-repair chain (R162…R163), because the
   spurious row is what keeps that chain from closing the column; after the chain,
   `verify_row_drops()` requires the block to close exactly in every component column
   the row filled, and otherwise puts the row back.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from loguru import logger

from fin2.extract.sce_sign_repair import (
    _Cell, _blocks, _proven_subtotals, concept_of_col_label,
)

_TOTAL_COL_RE = re.compile(r"합\s*계|총\s*계")


# ── 1. value fixes: (rcept, basis, label_raw, col_label, row_order) → (old, new) ──
_VALUE_FIXES: Dict[Tuple[str, str, str, str, int], Tuple[int, int]] = {
    # 동진쎄미켐 00118804 2017Q1 20170515004289 (XBRL). The SCE closing-balance facts
    # disagree with the same-date BS facts; roll-forward and row identity both prove
    # the BS values (issues #85226-#85228, user-confirmed 2026-09-26):
    #   consolidated NCI: 6,708,169,143 + 90,585,596 - 29,865,446 = 6,768,889,293
    #     (source prints ...899...; BS NoncontrollingInterests = 6,768,889,293;
    #      200,033,370,576 + 6,768,889,293 = 206,802,259,869 printed total)
    #   separate 기타불입자본: 61,191,597,597 + 9,871,658,837 - 1,233,655,389
    #     = 69,829,601,045 (source prints that + the opening 61,191,597,597)
    #   separate 기타자본잉여금: 20,743,089,545 - 1,285,950,900 = 19,457,138,645
    #     (source prints that + the opening 20,743,089,545)
    ("20170515004289", "consolidated", "기말자본 (기말) (2017-03-31)",
     "자본 [member]>비지배지분 [member]", 10):
        (6_768_899_293, 6_768_889_293),
    ("20170515004289", "separate", "기말자본 (기말) (2017-03-31)",
     "자본 [member]>기타불입자본", 11):
        (131_021_198_642, 69_829_601_045),
    ("20170515004289", "separate", "기말자본 (기말) (2017-03-31)",
     "자본 [member]>기타자본잉여금 [member]", 11):
        (40_200_228_190, 19_457_138_645),
}

# ── 2. row moves: (rcept, basis, label_raw, from_row_order) → to_row_order ──────
# 에코프로 00536541 2017FY 20180402002079 (+ amendment 20181206000084, table
# byte-identical). Consolidated SCE prints '전환상환우선주행사' (534,187,500 /
# 7,897,249,244 / 8,431,436,744) in the 2016 block; the 2015 block has the same
# row empty. Capital column: 2015 block short by exactly 534,187,500, 2016 block over
# by exactly 534,187,500 (surplus column likewise 7,897,249,244). The separate SCE
# of the same filing books the identical amounts in its 2015 block ('유상증자').
# Target row_order 5 = the empty 2015 '전환상환우선주행사' slot (source row 8 minus
# 3 header rows). Issues #85145-#85148 / #85160-#85163, user-confirmed 2026-09-26.
_ROW_MOVES: Dict[Tuple[str, str, str, int], int] = {
    ("20180402002079", "consolidated", "전환상환우선주행사", 24): 5,
    ("20181206000084", "consolidated", "전환상환우선주행사", 24): 5,
}

# ── 3. row drops: (rcept, basis, label_raw, row_order) → {col_index: value} ─────
# 에코프로 2017FY (same two rcepts), separate SCE 2015 block '지분법이익잉여금변동'
# 104,092,712. The separate statement of comprehensive income prints this line
# only for 제19기 (2016, (104,092,712)); 제18기 (2015) is blank. The 2016 SCE block
# carries its own (104,092,712) row. Without the 2015 row the retained-earnings
# column closes (5,831,180,301 + 189,521,071 - 475,719,069 = 5,544,982,303).
# Issues #85153/#85154 / #85168/#85169, user-confirmed 2026-09-26.
_ROW_DROPS: Dict[Tuple[str, str, str, int], Dict[int, int]] = {
    ("20180402002079", "separate", "지분법이익잉여금변동", 3): {2: 104_092_712, 3: 104_092_712},
    ("20181206000084", "separate", "지분법이익잉여금변동", 3): {2: 104_092_712, 3: 104_092_712},
}


def _is_total_col(col_label: Optional[str]) -> bool:
    return bool(_TOTAL_COL_RE.search(concept_of_col_label(col_label)))


def _sce(lines: Sequence) -> List:
    return [ln for ln in lines if getattr(ln, "statement", None) == "SCE"
            and getattr(ln, "value_won", None) is not None]


def _column_entries(lines: Sequence, basis: str, table_seq, col_index: int,
                    override: Optional[Dict[int, Tuple[int, int]]] = None
                    ) -> List[Tuple[int, str, int]]:
    """`(row_order, label_raw, value)` of one SCE column, row-sorted.

    `override` maps `id(line)` → `(row_order, value)` so a hypothetical move/value can
    be evaluated without touching the lines.
    """
    out = []
    for ln in _sce(lines):
        if (ln.basis, getattr(ln, "table_seq", None), ln.col_index) != (basis, table_seq, col_index):
            continue
        ro, val = (override or {}).get(id(ln), (ln.row_order, ln.value_won))
        if ro is None:
            continue
        out.append((ro, (ln.label_raw or ""), int(val)))
    out.sort(key=lambda e: e[0])
    return out


def _residual_at(entries: Sequence[Tuple[int, str, int]], row_order: int) -> Optional[int]:
    """Roll-forward residual (opening + Σmovements − closing) of the block that spans
    `row_order`; proven subtotal rows are left out (R162-c). None = no such block."""
    cells = [_Cell(line=None, basis="", label_raw=lab, col_label=None, value=val)
             for _ro, lab, val in entries]
    for open_i, move_i, close_i in _blocks(cells):
        if not entries[open_i][0] <= row_order <= entries[close_i][0]:
            continue
        subtotals = set(_proven_subtotals(cells, move_i))
        return (cells[open_i].value
                + sum(cells[m].value for m in move_i if m not in subtotals)
                - cells[close_i].value)
    return None


def _row_identity_holds(lines: Sequence, target, values: Dict[int, int]) -> bool:
    """Σ direct children == parent for the `col_label` path holding `target`
    (XBRL hierarchy, e.g. '자본 [member]>비지배지분 [member]'). `values` maps
    `id(line)` → value to evaluate instead of the stored one (every listed fix of the
    row at once — two wrong cells in one row only close together)."""
    path = target.col_label or ""
    if ">" not in path:
        return False
    parent = path.rsplit(">", 1)[0]
    row = {ln.col_label: values.get(id(ln), int(ln.value_won))
           for ln in _sce(lines)
           if ln.basis == target.basis
           and getattr(ln, "table_seq", None) == getattr(target, "table_seq", None)
           and ln.row_order == target.row_order and ln.col_label}
    if parent not in row:
        return False
    children = [v for k, v in row.items()
                if k.startswith(parent + ">") and ">" not in k[len(parent) + 1:]]
    return bool(children) and sum(children) == row[parent]


def _apply_value_fixes(lines: List, rcept_no: str) -> int:
    hits = []
    for ln in _sce(lines):
        key = (rcept_no, ln.basis, (ln.label_raw or "").strip(), ln.col_label or "", ln.row_order)
        fix = _VALUE_FIXES.get(key)
        if fix is not None and ln.value_won == fix[0]:
            hits.append((ln, fix))
    olds = {id(ln): fix[0] for ln, fix in hits}
    news = {id(ln): fix[1] for ln, fix in hits}
    passed = []
    for ln, (old, new) in hits:
        seq = getattr(ln, "table_seq", None)
        res_old = _residual_at(_column_entries(lines, ln.basis, seq, ln.col_index), ln.row_order)
        res_new = _residual_at(_column_entries(lines, ln.basis, seq, ln.col_index,
                                               {id(ln): (ln.row_order, new)}), ln.row_order)
        ok = (res_old not in (None, 0) and res_new == 0
              and not _row_identity_holds(lines, ln, olds)
              and _row_identity_holds(lines, ln, news))
        if not ok:
            logger.warning(f"[R183] {rcept_no} {ln.basis} '{ln.label_raw}' {ln.col_label}: "
                           f"guard failed (roll-forward {res_old}->{res_new}) — value fix skipped")
            continue
        passed.append((ln, new))
    # Write only after every cell has been judged against the original table.
    for ln, new in passed:
        ln.value_won = new
    return len(passed)


def _apply_row_moves(lines: List, rcept_no: str) -> int:
    n = 0
    for (rcept, basis, label, src_ro), dst_ro in _ROW_MOVES.items():
        if rcept != rcept_no:
            continue
        row = [ln for ln in _sce(lines) if ln.basis == basis
               and (ln.label_raw or "").strip() == label and ln.row_order == src_ro]
        if not row:
            continue
        seqs = {getattr(ln, "table_seq", None) for ln in row}
        occupied = any(ln.basis == basis and getattr(ln, "table_seq", None) in seqs
                       and ln.row_order == dst_ro for ln in _sce(lines))
        ok = not occupied and len(seqs) == 1
        for ln in row:
            if not ok:
                break
            if _is_total_col(ln.col_label):
                continue
            seq = getattr(ln, "table_seq", None)
            before = _column_entries(lines, basis, seq, ln.col_index)
            after = _column_entries(lines, basis, seq, ln.col_index,
                                    {id(ln): (dst_ro, ln.value_won)})
            src_before, dst_before = _residual_at(before, src_ro), _residual_at(before, dst_ro)
            src_after, dst_after = _residual_at(after, src_ro), _residual_at(after, dst_ro)
            ok = (src_before not in (None, 0) and dst_before not in (None, 0)
                  and src_after == 0 and dst_after == 0)
        if not ok:
            logger.warning(f"[R183] {rcept_no} {basis} '{label}' row {src_ro}->{dst_ro}: "
                           f"guard failed — row move skipped")
            continue
        for ln in row:
            ln.row_order = dst_ro
        n += 1
    return n


def _apply_row_drops(lines: List, rcept_no: str) -> List[Tuple[Tuple, List]]:
    dropped: List[Tuple[Tuple, List]] = []
    for key, expected in _ROW_DROPS.items():
        rcept, basis, label, ro = key
        if rcept != rcept_no:
            continue
        row = [ln for ln in _sce(lines) if ln.basis == basis
               and (ln.label_raw or "").strip() == label and ln.row_order == ro]
        if not row or {ln.col_index: ln.value_won for ln in row} != expected:
            continue
        ids = {id(ln) for ln in row}
        lines[:] = [ln for ln in lines if id(ln) not in ids]
        dropped.append((key, row))
    return dropped


def apply_source_defect_fixes(lines: List, rcept_no: Optional[str]) -> List[Tuple[Tuple, List]]:
    """Apply value fixes, row moves and row drops in place. Call BEFORE the SCE sign
    repair chain. Returns the dropped rows, which `verify_row_drops()` must check after
    the chain."""
    if not rcept_no:
        return []
    n_val = _apply_value_fixes(lines, rcept_no)
    n_mov = _apply_row_moves(lines, rcept_no)
    dropped = _apply_row_drops(lines, rcept_no)
    if n_val or n_mov or dropped:
        logger.debug(f"[R183] {rcept_no}: value {n_val} · row move {n_mov} · "
                     f"row drop {len(dropped)}")
    return dropped


def verify_row_drops(lines: List, dropped: Sequence[Tuple[Tuple, List]]) -> int:
    """Post-check for `_ROW_DROPS`: keep a drop only if, after the sign-repair chain,
    the block closes exactly in every component column the dropped row filled.
    Otherwise the row goes back. Returns the number of drops kept."""
    kept = 0
    for (rcept, basis, label, ro), row in dropped:
        ok = True
        for ln in row:
            if _is_total_col(ln.col_label):
                continue
            entries = _column_entries(lines, basis, getattr(ln, "table_seq", None), ln.col_index)
            if _residual_at(entries, ro) != 0:
                ok = False
                break
        if ok:
            kept += 1
            continue
        logger.warning(f"[R183] {rcept} {basis} '{label}' row {ro}: block does not close "
                       f"after the drop — row restored")
        lines.extend(row)
    return kept
