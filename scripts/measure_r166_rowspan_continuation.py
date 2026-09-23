#!/usr/bin/env python
"""R166 scale - how often does a ROWSPAN label's second physical row carry values?

`_grid_body_rows` used to discard any body row with no physical cell in the
label region (its label column being occupied by a ROWSPAN from the row above),
because `physical[0]` was then the first AMOUNT cell and its empty text tripped
`if not label: continue`. R166 merges such a row into the preceding logical row,
filling ONLY its empty columns.

That function is shared by SCE and the notes, so the blast radius has to be
measured rather than argued. This measures the TRIGGER directly - no before/after
code swap needed, because the condition is exactly computable:

  trigger   a body row with no physical cell at grid_col < offset
  filled    such a row's non-empty amount columns that the preceding row left empty
            -> these are the values R166 recovers
  declined  columns the preceding row already filled
            -> R166 deliberately does NOT touch these (the 2021 SK이노베이션
               case, where the value closes no identity and its meaning is
               unknown - R6)

Read-only. Resumable: pass --checkpoint and re-run after any interruption.

Usage:
    python scripts/measure_r166_rowspan_continuation.py --workers 6 \
        --checkpoint /path/ck.jsonl --out /path/affected.txt
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (
    _detect_fin_type, _grid_header_split, _parse_xml_file)
from fin2.extract.text import _detect_body_statement_tables
from parser.common.amount_normalizer import parse_amount

_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _scan_table(tbl) -> tuple[int, int, int, int]:
    """(trigger_rows, fillable, zero_replaced, declined) for one table.

    ★`zero_replaced` is separated out because R166-b treats a preceding
    EXPLICIT '0' as a placeholder that a non-zero continuation value may
    replace (한미반도체 20230814001921, issue #35). That is the only case where
    the merge changes an existing value rather than filling a gap, so it is the
    one number that carries real risk and must be reported on its own.
    `declined` = the preceding row holds a real non-zero value -> untouched
    (SK이노베이션 2021, where the incoming figure closes no identity - R6).
    """
    grid_rows, n_header, offset, _w = _grid_header_split(tbl)
    if not grid_rows or not offset:
        return 0, 0, 0, 0
    trigger = fillable = zero_replaced = declined = 0
    prev: dict = {}          # col_idx -> raw text of the preceding logical row
    for row in grid_rows[n_header:]:
        physical = [c for c in row if not c.inherited]
        if not physical:
            continue
        if any(c.grid_col < offset for c in physical):
            prev = {c.grid_col - offset: c.text.strip()
                    for c in physical
                    if c.grid_col >= offset and c.text.strip()}
            continue
        cells = {c.grid_col - offset: c.text.strip()
                 for c in physical
                 if c.grid_col >= offset and c.text.strip()}
        if not cells:
            continue
        trigger += 1
        for idx, txt in cells.items():
            if idx not in prev:
                fillable += 1
                prev[idx] = txt
                continue
            prev_val = parse_amount(prev[idx], 1)
            inc = parse_amount(txt, 1)
            if prev_val == 0 and inc is not None and inc != 0:
                zero_replaced += 1
                prev[idx] = txt
            else:
                declined += 1
    return trigger, fillable, zero_replaced, declined


def _one(job: dict) -> dict:
    out = {"rcept_no": job["rcept_no"], "corp_name": job["corp_name"],
           "fy": job["fiscal_year"], "trigger": 0, "fillable": 0,
           "zero_replaced": 0, "declined": 0, "codes": [], "status": "ok"}
    path = Path(job["path"])
    if not path.exists():
        out["status"] = "missing"
        return out
    try:
        root = _parse_xml_file(path)
        if root is None:
            out["status"] = "missing"
            return out
        fin_type = _detect_fin_type(root, file_path=str(path))
        groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    except Exception as exc:                            # noqa: BLE001
        out["status"] = "error"
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        return out

    for code, entries in groups.items():
        for tbl, _u, _k in entries:
            try:
                t, f, z, d = _scan_table(tbl)
            except Exception:                           # noqa: BLE001
                continue
            if t:
                out["trigger"] += t
                out["fillable"] += f
                out["zero_replaced"] += z
                out["declined"] += d
                out["codes"].append(code)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--checkpoint")
    ap.add_argument("--out")
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, c.corp_name, f.fiscal_year
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            JOIN corporations c USING (corp_code)
            WHERE dt.file_type='xml' AND dt.status='completed'
              AND f.fiscal_year >= 2015
            ORDER BY dt.rcept_no""")).mappings().all()
    rows = [dict(r) for r in rows]
    print("population: %d" % len(rows))
    if args.limit:
        rows = rows[:args.limit]

    done: dict = {}
    ck = Path(args.checkpoint) if args.checkpoint else None
    if ck and ck.exists():
        for line in ck.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    done[r["rcept_no"]] = r
                except ValueError:
                    pass
        print("checkpoint: %d done -> resuming" % len(done))

    todo = []
    for r in rows:
        if r["rcept_no"] in done:
            continue
        r["path"] = (_SD + r["file_path"][len(_LINK):]
                     if r["file_path"].startswith(_LINK) else r["file_path"])
        todo.append(r)
    print("to measure: %d  workers=%d" % (len(todo), args.workers), flush=True)

    results = list(done.values())
    t0 = time.time()
    fh = ck.open("a") if ck else None
    try:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(_one, j) for j in todo]
            for i, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                results.append(r)
                if fh:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    if i % 100 == 0:
                        fh.flush()
                if i % 500 == 0:
                    el = time.time() - t0
                    rate = i / el if el else 0
                    hit = sum(1 for x in results if x.get("trigger"))
                    print("  ... %d/%d  %.1f/s  eta %.1fh  affected=%d"
                          % (i, len(todo), rate,
                             (len(todo) - i) / rate / 3600 if rate else 0, hit),
                          flush=True)
    finally:
        if fh:
            fh.close()

    hits = [r for r in results if r.get("trigger")]
    n_err = sum(1 for r in results if r.get("status") != "ok")
    print("\nmeasured=%d  affected filings=%d  unreadable/error=%d"
          % (len(results), len(hits), n_err))
    print("  trigger rows   : %d" % sum(r["trigger"] for r in hits))
    print("  ★cells filled into an EMPTY column   : %d"
          % sum(r["fillable"] for r in hits))
    print("  ★★cells REPLACING an explicit '0'     : %d   (R166-b - the only "
          "case that changes an existing value)"
          % sum(r.get("zero_replaced", 0) for r in hits))
    print("  cells declined (real value present)  : %d"
          % sum(r["declined"] for r in hits))

    from collections import Counter
    codes = Counter()
    for r in hits:
        for c in r["codes"]:
            codes[c] += 1
    print("\n  by statement code (filings):")
    for k, v in codes.most_common():
        print("    %-8s %d" % (k, v))

    print("\n  top filings by cells filled:")
    for r in sorted(hits, key=lambda x: -(x["fillable"] + x.get("zero_replaced", 0)))[:20]:
        print("    %s %-16s %s  fill=%-4d zero=%-3d decline=%-3d %s" % (
            r["rcept_no"], (r["corp_name"] or "")[:14], r["fy"],
            r["fillable"], r.get("zero_replaced", 0), r["declined"], ",".join(sorted(set(r["codes"])))))

    if args.out and hits:
        Path(args.out).write_text(
            "\n".join(r["rcept_no"] for r in hits if r["fillable"] or r.get("zero_replaced")) + "\n")
        print("\n  affected list -> %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
