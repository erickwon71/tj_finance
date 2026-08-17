"""
T22 scope census -- does widening `_NUMBER_PATTERN` to accept bare hyphen negatives
("-N", no parens) change body-statement values, note/SCE header-boundary detection,
or multicol period-layout detection?

Plan: docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md Phase 1.
Read-only -- no DB writes. Raw XML is the only truth; both the "before" (current
production) and "after" (candidate T22 fix) code paths are the real production
functions, toggled via a runtime monkeypatch of `_NUMBER_PATTERN` in both modules
that hold their own binding of it (`parser.xml.table_extractor` defines it,
`fin2.extract.report_lines` imports its own name -- patching only one leaves the
other consumer on the old pattern, see TODO Phase 2-1).

Four independent measurements, one pass per sampled filing:
  (A) body value diff  -- extract_report_lines() twice (before/after), diff BS/IS/CF
      rows. Classifies each row identity into:
        new_value  (i)  -- a column that was missing now has a value, nothing else changed
        corrected  (ii) -- a column that had a value now has a DIFFERENT value (silent
                           contamination, per TODO this is the number that matters most)
        unchanged  (iii)
        other      -- a column present before is now absent (should not happen; the
                       gate only widens, never narrows -- flagged for manual look)
  (B) note/SCE header-split delta -- `_grid_header_split(table)` on every TABLE in the
      document, before/after, count n_header changes.
  (C) multicol flip -- `_detect_period_layout(table)` on the body tables actually
      selected by `extract_report_lines`, before/after, count flips.
  (D) unicode negative-sign frequency (measure only, not part of the T22 fix scope) --
      count cells containing U+2212/U+FF0D/U+2013 across the document.

Usage:
  .venv/bin/python scripts/census_t22_hyphen_negative_2026-08-16.py [N]
  N = target sample size (default 260).
"""
from __future__ import annotations

import csv
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text  # noqa: E402

from collector.db import engine  # noqa: E402
import parser.xml.table_extractor as te  # noqa: E402
import fin2.extract.report_lines as rl  # noqa: E402

RAW_REPORT_NAS = "/Users/taejin/Project/tj_finance/raw_report/"
RAW_REPORT_SD = "/Volumes/dart_data/raw_report/"

OUT_CSV = Path("/Users/taejin/Project/tj_finance/scripts/"
                "census_t22_hyphen_negative_2026-08-16_results.csv")

UNICODE_NEG_CHARS = ("−", "－", "–")  # − (minus) ／－(fullwidth)／–(en dash)

# ── build the candidate ("after") pattern by inserting exactly the Phase 2-1 alternative
# right after the existing "(-)N" alternative, so the census tests the literal planned edit. ──
_INSERT_AFTER = r'^\(-\)[\d,]+\.?\d*$|'
_NEW_ALT = r'^-[\d,]+\.?\d*$|'
_BASE_SRC = te._NUMBER_PATTERN.pattern
assert _INSERT_AFTER in _BASE_SRC, (
    "table_extractor._NUMBER_PATTERN 형식이 바뀌었다 -- census 스크립트도 갱신 필요")
_EXT_SRC = _BASE_SRC.replace(_INSERT_AFTER, _INSERT_AFTER + _NEW_ALT, 1)
EXT_PATTERN = re.compile(_EXT_SRC)
ORIG_TE_PATTERN = te._NUMBER_PATTERN
ORIG_RL_PATTERN = rl._NUMBER_PATTERN


def use_pattern(ext: bool) -> None:
    """Toggle BOTH module bindings -- table_extractor defines it, report_lines imports
    its own name (see module docstring). Patching only one under-tests the real fix."""
    p = EXT_PATTERN if ext else ORIG_TE_PATTERN
    te._NUMBER_PATTERN = p
    rl._NUMBER_PATTERN = p if ext else ORIG_RL_PATTERN


def resolve_path(file_path: str) -> str:
    """Prefer the SD-card mirror (fast, doesn't hammer the NAS -- see memory
    feedback-bulk-read-use-sdcard). Falls back to the DB-recorded (NAS-symlinked) path."""
    if file_path.startswith(RAW_REPORT_NAS):
        sd = RAW_REPORT_SD + file_path[len(RAW_REPORT_NAS):]
        if Path(sd).exists():
            return sd
    return file_path


def stratified_sample(target: int, seed: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, dt.file_path
            FROM filings f JOIN download_tasks dt USING (rcept_no)
            WHERE dt.file_type = 'xml' AND dt.status = 'completed'
              AND dt.file_path IS NOT NULL AND f.is_final
        """)).fetchall()
    strata: dict[tuple, list[dict]] = {}
    for r in rows:
        bucket = (r.fiscal_year // 5) * 5
        strata.setdefault((bucket, r.fiscal_period), []).append(dict(
            rcept_no=r.rcept_no, corp_code=r.corp_code,
            fiscal_year=r.fiscal_year, fiscal_period=r.fiscal_period,
            file_path=r.file_path))
    rng = random.Random(seed)
    per_stratum = max(1, target // max(1, len(strata)))
    sample = []
    for key, pool in strata.items():
        sample.extend(rng.sample(pool, min(per_stratum, len(pool))))
    rng.shuffle(sample)
    return sample[:target] if len(sample) > target else sample


def row_identity(line) -> tuple:
    if line.row_order is not None:
        return (line.statement, line.basis, line.table_seq, "R", line.row_order)
    return (line.statement, line.basis, line.table_seq, "L", (line.label_raw or "")[:40])


def value_diff(file_path: str, meta: dict) -> tuple[Counter, list[dict]]:
    """(A) full extract_report_lines() before/after, diffed on BS/IS/CF rows only
    (SCE/note values are grid-based -- unaffected by this gate, see module docstring)."""
    cnt = Counter()
    examples = []
    use_pattern(False)
    before = rl.extract_report_lines(
        file_path, rcept_no=meta["rcept_no"], corp_code=meta["corp_code"],
        report_fiscal_year=meta["fiscal_year"], report_fiscal_period=meta["fiscal_period"],
        include_notes=False)
    use_pattern(True)
    after = rl.extract_report_lines(
        file_path, rcept_no=meta["rcept_no"], corp_code=meta["corp_code"],
        report_fiscal_year=meta["fiscal_year"], report_fiscal_period=meta["fiscal_period"],
        include_notes=False)
    use_pattern(False)

    def maps_by_identity(lines):
        out: dict[tuple, dict[int, int]] = {}
        labels: dict[tuple, str] = {}
        for ln in lines:
            if ln.statement not in ("BS", "IS", "CF"):
                continue
            ident = row_identity(ln)
            out.setdefault(ident, {})[ln.col_index] = ln.value_won
            labels[ident] = ln.label_raw
        return out, labels

    before_map, before_labels = maps_by_identity(before)
    after_map, after_labels = maps_by_identity(after)

    for ident in set(before_map) | set(after_map):
        b = before_map.get(ident, {})
        a = after_map.get(ident, {})
        if b == a:
            cls = "unchanged"
        else:
            common_diff = any(c in a and a[c] != v for c, v in b.items())
            lost = any(c not in a for c in b)
            if common_diff or lost:
                cls = "corrected" if common_diff else "other_lost"
            else:
                cls = "new_value"
        cnt[cls] += 1
        if cls in ("corrected", "other_lost"):
            examples.append({
                "corp_code": meta["corp_code"], "rcept_no": meta["rcept_no"],
                "statement": ident[0], "basis": ident[1], "table_seq": ident[2],
                "row_order": ident[4] if ident[3] == "R" else None,
                "label_raw": (after_labels.get(ident) or before_labels.get(ident) or "")[:60],
                "classification": cls, "before": b, "after": a,
            })
    return cnt, examples


def header_split_delta(root) -> Counter:
    """(B) n_header before/after over every TABLE in the document (body+note+SCE all
    share this one function -- see report_lines.py:548 docstring)."""
    cnt = Counter()
    tables = list(root.iter("TABLE"))
    use_pattern(False)
    before = []
    for t in tables:
        try:
            _, n_header, _, _ = rl._grid_header_split(t)
        except Exception:
            n_header = None
        before.append(n_header)
    use_pattern(True)
    after = []
    for t in tables:
        try:
            _, n_header, _, _ = rl._grid_header_split(t)
        except Exception:
            n_header = None
        after.append(n_header)
    use_pattern(False)
    for b, a in zip(before, after):
        cnt["tables"] += 1
        if b == a:
            cnt["unchanged"] += 1
        else:
            cnt["changed"] += 1
    return cnt


def multicol_flip(root, meta: dict) -> Counter:
    """(C) multicol flips on the exact body tables extract_report_lines() would select."""
    cnt = Counter()
    fin_type = rl._detect_fin_type(root)
    if meta["fiscal_year"] <= rl._PRE2015_ROUTING_MAX_FY:
        groups = rl._detect_pre2015_body_statement_tables_merged(root, fin_type)
    else:
        groups = rl._detect_body_statement_tables(root, fin_type, include_sce=True)
    tables = []
    for code, tws in groups.items():
        if code.startswith("SCE"):
            continue
        tables.extend(t for t, _, _ in tws)
    tables = list(dict.fromkeys(tables))
    for t in tables:
        use_pattern(False)
        _, m1 = rl._detect_period_layout(t)
        use_pattern(True)
        _, m2 = rl._detect_period_layout(t)
        use_pattern(False)
        cnt["tables"] += 1
        if m1 != m2:
            cnt["flipped"] += 1
    return cnt


def unicode_freq(root) -> Counter:
    """(D) measure-only -- unicode negative-sign cell frequency (not fixed by T22)."""
    cnt = Counter()
    from parser.xml.table_extractor import _get_cells
    for tr in root.iter("TR"):
        for cell in _get_cells(tr):
            cnt["cells"] += 1
            if any(ch in cell for ch in UNICODE_NEG_CHARS):
                cnt["cells_with_unicode_neg"] += 1
    return cnt


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 260
    sample = stratified_sample(target, seed=20260816)
    print(f"stratified sample: {len(sample)} filings")

    totals = Counter()
    header_totals = Counter()
    multicol_totals = Counter()
    unicode_totals = Counter()
    all_examples = []
    parse_err = 0

    for i, meta in enumerate(sample, 1):
        path = resolve_path(meta["file_path"])
        if not Path(path).exists():
            parse_err += 1
            continue
        try:
            root = rl._parse_xml_file(Path(path))
            if root is None:
                parse_err += 1
                continue
            vcnt, examples = value_diff(path, meta)
            totals.update(vcnt)
            all_examples.extend(examples)
            header_totals.update(header_split_delta(root))
            multicol_totals.update(multicol_flip(root, meta))
            unicode_totals.update(unicode_freq(root))
        except Exception as e:
            parse_err += 1
            print(f"  !! {meta['rcept_no']}: {type(e).__name__}: {e}")
        if i % 25 == 0:
            print(f"  ... {i}/{len(sample)} processed")

    print("=" * 70)
    print(f"filings sampled : {len(sample)}  (errors {parse_err})")
    print("-- (A) body value diff (BS/IS/CF row identities) --")
    n_rows = sum(totals.values())
    for k in ("unchanged", "new_value", "corrected", "other_lost"):
        v = totals.get(k, 0)
        print(f"  {k:12s}: {v:8,d}  ({v / max(1, n_rows) * 100:.4f}%)")
    print(f"  total identities: {n_rows:,}")
    print("-- (B) note/SCE header-split (_grid_header_split n_header) delta --")
    print(f"  tables measured : {header_totals['tables']:,}")
    print(f"  n_header changed: {header_totals['changed']:,} "
          f"({header_totals['changed'] / max(1, header_totals['tables']) * 100:.4f}%)")
    print("-- (C) multicol flip (_detect_period_layout) on body tables --")
    print(f"  tables measured : {multicol_totals['tables']:,}")
    print(f"  flipped         : {multicol_totals['flipped']:,} "
          f"({multicol_totals['flipped'] / max(1, multicol_totals['tables']) * 100:.4f}%)")
    print("-- (D) unicode negative-sign cell frequency (measure only) --")
    print(f"  cells total     : {unicode_totals['cells']:,}")
    print(f"  cells w/ unicode neg: {unicode_totals['cells_with_unicode_neg']:,} "
          f"({unicode_totals['cells_with_unicode_neg'] / max(1, unicode_totals['cells']) * 100:.4f}%)")

    if all_examples:
        print("=" * 70)
        print(f"corrected/other_lost examples ({len(all_examples)} total, showing up to 15):")
        for ex in all_examples[:15]:
            print(f"  {ex['rcept_no']} {ex['statement']}/{ex['basis']} tseq={ex['table_seq']} "
                  f"row={ex['row_order']} [{ex['classification']}] {ex['label_raw']!r}")
            print(f"    before={ex['before']}  after={ex['after']}")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "corp_code", "rcept_no", "statement", "basis", "table_seq", "row_order",
            "label_raw", "classification", "before", "after"])
        w.writeheader()
        for ex in all_examples:
            w.writerow(ex)
    print(f"\nCSV (corrected/other_lost rows only): {OUT_CSV}")


if __name__ == "__main__":
    main()
