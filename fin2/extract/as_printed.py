"""R0-2 migration switch — layer 2 stores printed values only (docs/PARSING_RULES.md R0-2).

Every layer-2 step that writes a value different from the printed one (sign repair, typo fix,
row move/drop, overlay from another source) asks `repair_on(step)` before it runs.

- Default (stage 2 of docs/plans/layer2_as_printed_migration_2026-10-10.md): all steps off —
  layer 2 = printed values. The loaders get the steps' results as layer-3 corrections
  (`fin2/extract/layer3_corrections.py`), not as layer-2 values.
- `TJF_LAYER2_AS_PRINTED=0`: all steps on (old behaviour; kept one release for comparison).
- `DISABLED`: per-step off switch for on/off measurement (stage 0).
- `TRACE`: optional callback(step, lines) the extractor calls after each step, so a
  measurement can attribute every changed cell to the step that changed it.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable, Optional

ENV = "TJF_LAYER2_AS_PRINTED"

# Step names (one per value-changing call site).
STEPS = (
    "R18_dividends_overlay",   # CF dividends sign from inline XBRL tag
    "tax_overlay",             # IS tax expense value from inline XBRL tag
    "R183_source_defects",     # SCE row move/drop, value fix, cell fill (XML + XBRL)
    "R162_sign_loss",          # SCE column roll-forward sign repair (+ R185~R193, R215 inside)
    "R162_manual",             # SCE per-rcept manual sign list
    "R162d_row_identity",      # SCE row identity sign repair (+ R162-e2 rerun)
    "R163_cf_cash",            # CF cash reconciliation sign repair
    "R188_balance_tolerance",  # SCE balance cell within tolerance
    "R189_sibling_cells",      # SCE sibling cells
    "R190d_dated_balance",     # SCE balance takes dated BS sign
    "R159_typo",               # cell digit typo list (table_extractor)
    "R170d_tax_sign",          # XBRL IS tax sign settled by identity (+ R227)
    "xbrl_manual_is_sign",     # XBRL IS per-rcept manual sign list
    "R176_xbrl_sce_sign",      # XBRL SCE roll-forward sign settlement (+ R200)
)

DISABLED: set[str] = set()
TRACE: Optional[Callable[[str, list], None]] = None


_FORCED: Optional[str] = None     # "printed" | "repaired" — set by forced()


@contextmanager
def forced(mode: str):
    """Run a block with the rules forced off ("printed") or on ("repaired"), whatever the env —
    `layer3_corrections.extract_with_corrections` runs both."""
    global _FORCED
    assert mode in ("printed", "repaired"), mode
    saved, _FORCED = _FORCED, mode
    try:
        yield
    finally:
        _FORCED = saved


def as_printed() -> bool:
    if _FORCED is not None:
        return _FORCED == "printed"
    return os.environ.get(ENV, "1") != "0"


def repair_on(step: str) -> bool:
    assert step in STEPS, step
    return not as_printed() and step not in DISABLED


def checkpoint(step: str, lines: list) -> None:
    if TRACE is not None:
        TRACE(step, lines)
