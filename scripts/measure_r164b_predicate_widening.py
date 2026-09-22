#!/usr/bin/env python
"""R164-b impact measurement - widening `_looks_like_equity_changes_header`.

That predicate is POSITIVE SCE evidence shared by four rules:

  R127   a CF/IS/BS caption sitting on an SCE data table -> distrust the caption
  R127b  same, in the split title/data forward scan
  R148   headerless SCE continuation table -> inherit the previous statement
  R164   exempt a confirmed SCE from the appropriation-statement guard

So loosening it changes where all four fire. This script runs the real detector
TWICE per filing - once with the old predicate restored, once with the new one -
and diffs the resulting table assignments, so the change is judged by what it
actually does to the corpus rather than by argument.

Reported per filing:
  gained   a (basis, statement) code that only the new predicate produces
  lost     one that only the old predicate produces        <- MUST be 0
  moved    the same physical table assigned to another statement

## Operational history - read before changing the concurrency

★2026-09-22, three self-inflicted failures, recorded so they are not repeated:

1. Keying tables by `id(tbl)` reported 25 phantom "moved" cases.
   `_split_headed_multi_statement_table` deep-copies rows into synthetic
   tables, so those objects get a fresh id on every run. Fixed by hashing table
   CONTENT (`_table_sig`).

2. Storage benchmarks were wrong twice - first reading the same files twice
   (page cache, "23 GB/s"), then comparing the two devices on DIFFERENT file
   sets (file-size variance picked the winner). Measured properly on one list
   with both copies cold: SD 5.33 files/s, NAS 5.66 files/s - equivalent.

3. ★A 32-worker `multiprocessing.Pool` run DIED: after ~8,000 filings every
   worker was gone while the parent sat in `imap_unordered` for four hours
   having burned 1.19s of CPU. `Pool` hangs forever when a worker dies. And 32
   was reckless to begin with - this project already hit memory exhaustion at
   EIGHT workers during a full re-load (memory note
   `held-zero-line-filing-triage-sibling-check-2026-09-12`).

   Hence this design: few workers, `ProcessPoolExecutor` (raises
   `BrokenProcessPool` instead of hanging), a JSONL checkpoint so a restart
   resumes instead of starting over, and a heartbeat printing the rate and ETA
   so a stall shows up within a minute instead of after four hours.

Storage: SD by default. The NAS is fine in short bursts but a sustained full
scan over SMB is a known failure mode (`feedback-bulk-read-use-sdcard`).

Usage:
    python scripts/measure_r164b_predicate_widening.py --workers 6 \
        --checkpoint /path/ck.jsonl --out /path/changed.txt
    python scripts/measure_r164b_predicate_widening.py --limit 500 --sample
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract import text as T
from fin2.extract.report_lines import _detect_fin_type, _parse_xml_file
from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, assign_tables_to_dart_sections,
)

# `download_tasks.file_path` is written with this prefix; the symlink points at
# the NAS share.
_LINK_PREFIX = "/Users/taejin/Project/tj_finance/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"
_NAS_PREFIX = "/Volumes/tj_finance_data/raw_report"

# Pre-R164-b behaviour, verbatim: first TWO rows, original token list.
_OLD_TOKENS = re.compile(
    r"자본금|자본잉여금|이익잉여금|자본조정|기타포괄손익누계액|비지배지분|주식발행초과금")


def _old_predicate(tbl) -> bool:
    rows = T.table_direct_rows(tbl)
    if not rows:
        return False
    cells = T._get_cells(rows[0]) + (T._get_cells(rows[1]) if len(rows) > 1 else [])
    joined = re.sub(r"\s+", "", "".join(cells))
    return len(_OLD_TOKENS.findall(joined)) >= 3


def _table_sig(tbl) -> str:
    """Content signature - stable across runs, unlike id(tbl). See history (1)."""
    txt = re.sub(r"\s+", "", "".join(tbl.itertext()))
    return "%d:%s" % (len(list(tbl.iter("TR"))),
                      hashlib.md5(txt.encode("utf-8")).hexdigest()[:16])


def _assign(root, fin_type) -> dict:
    groups = T._detect_body_statement_tables(root, fin_type, include_sce=True)
    out = {}
    for code, entries in groups.items():
        for tbl, _u, _k in entries:
            out[(code, _table_sig(tbl))] = len(list(tbl.iter("TR")))
    return out


def _resolve(p: str, storage: str, seq: int) -> Path:
    if not p or not p.startswith(_LINK_PREFIX):
        return Path(p)
    rel = p[len(_LINK_PREFIX):]
    if storage == "nas":
        return Path(_NAS_PREFIX + rel)
    if storage == "both":
        return Path((_SD_PREFIX if seq % 2 == 0 else _NAS_PREFIX) + rel)
    return Path(_SD_PREFIX + rel)


def _measure_one(m: dict) -> dict:
    """Run the detector twice on one filing and return the diff."""
    out = {"rcept_no": m["rcept_no"], "corp_name": m["corp_name"],
           "fy": m["fiscal_year"], "fp": m["fiscal_period"],
           "status": "same", "gained": [], "lost": [], "moved": [],
           "gained_rows": 0, "lost_rows": 0}
    path = _resolve(m["file_path"], m.get("_storage", "sd"), m.get("_seq", 0))
    if not path.exists():
        out["status"] = "unreadable"
        return out
    real = T._looks_like_equity_changes_header
    try:
        root = _parse_xml_file(path)
        if root is None:
            out["status"] = "unreadable"
            return out
        fin_type = _detect_fin_type(root, file_path=str(path))
        # ★Cheap provable early exit. The detector's ONLY dependence on this
        #   predicate is the predicate itself, and it is only ever applied to
        #   tables inside the two body FS sections. So if old and new agree on
        #   every one of those tables, both detector runs take identical
        #   branches and the output is identical by construction - no need to
        #   run the detector at all. This matters because the machine is shared
        #   with the campaign session (camp_run), so each filing should cost as
        #   little as possible.
        sec = assign_tables_to_dart_sections(root)
        flipped = False
        for key in (SEC_CONSOL_FS, SEC_SEP_FS):
            for tbl in sec.get(key, []):
                if _old_predicate(tbl) != real(tbl):
                    flipped = True
                    break
            if flipped:
                break
        if not flipped:
            return out                      # status stays "same"

        T._looks_like_equity_changes_header = _old_predicate
        before = _assign(root, fin_type)
        T._looks_like_equity_changes_header = real
        after = _assign(root, fin_type)
    except Exception as exc:                            # noqa: BLE001
        out["status"] = "error"
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        return out
    finally:
        T._looks_like_equity_changes_header = real

    if before == after:
        return out
    out["status"] = "changed"
    b_codes = {c for c, _ in before}
    a_codes = {c for c, _ in after}
    out["gained"] = sorted(a_codes - b_codes)
    out["lost"] = sorted(b_codes - a_codes)
    out["gained_rows"] = sum(v for (cc, _t), v in after.items()
                             if cc in out["gained"])
    out["lost_rows"] = sum(v for (cc, _t), v in before.items()
                           if cc in out["lost"])
    b_by_tbl = {t: c for c, t in before}
    a_by_tbl = {t: c for c, t in after}
    for t, c in a_by_tbl.items():
        if t in b_by_tbl and b_by_tbl[t] != c:
            out["moved"].append([b_by_tbl[t], c, after[(c, t)]])
    return out


def _population(session, rcept_file):
    if rcept_file:
        rcepts = [l.strip() for l in open(rcept_file) if l.strip()]
        return session.execute(text("""
            SELECT dt.rcept_no, dt.file_path, c.corp_name, f.fiscal_year,
                   f.fiscal_period
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            JOIN corporations c USING (corp_code)
            WHERE dt.rcept_no = ANY(:r) AND dt.file_type='xml'
              AND dt.status='completed'"""), {"r": rcepts}).mappings().all()
    return session.execute(text("""
        SELECT dt.rcept_no, dt.file_path, c.corp_name, f.fiscal_year,
               f.fiscal_period
        FROM download_tasks dt JOIN filings f USING (rcept_no)
        JOIN corporations c USING (corp_code)
        WHERE dt.file_type='xml' AND dt.status='completed'
          AND f.fiscal_year >= 2015
        ORDER BY dt.rcept_no""")).mappings().all()


def _report(results: list, out_path) -> None:
    n_same = sum(1 for r in results if r["status"] == "same")
    n_err = sum(1 for r in results if r["status"] in ("unreadable", "error"))
    changed = [r for r in results if r["status"] == "changed"]
    gained: dict = {}
    lost: dict = {}
    moved_detail: list = []
    gained_rows = lost_rows = 0
    for r in changed:
        for c in r["gained"]:
            gained[c] = gained.get(c, 0) + 1
        for c in r["lost"]:
            lost[c] = lost.get(c, 0) + 1
        gained_rows += r["gained_rows"]
        lost_rows += r["lost_rows"]
        for b, a, n in r["moved"]:
            moved_detail.append((r["rcept_no"], r["corp_name"], b, a, n))

    print("\nmeasured=%d  unchanged=%d  changed=%d  unreadable/error=%d"
          % (len(results), n_same, len(changed), n_err))
    print("\nGAINED statement codes (new predicate only):")
    for k in sorted(gained):
        print("  %-8s %d filing(s)" % (k, gained[k]))
    print("  source rows gained: %d" % gained_rows)
    print("\nLOST statement codes (old predicate only) - MUST be empty:")
    if not lost:
        print("  none")
    for k in sorted(lost):
        print("  %-8s %d filing(s)   *** REGRESSION ***" % (k, lost[k]))
    print("  source rows lost: %d" % lost_rows)
    print("\nsame table reassigned to another statement: %d" % len(moved_detail))
    for rcept, name, b, a, n in moved_detail[:40]:
        print("    %s %-14s %-7s -> %-7s  %d rows" % (
            rcept, (name or "")[:12], b, a, n))
    if moved_detail:
        agg: dict = {}
        for _r, _n, b, a, _rows in moved_detail:
            key = "%s -> %s" % (b, a)
            agg[key] = agg.get(key, 0) + 1
        print("  transition tally:")
        for k in sorted(agg, key=lambda x: -agg[x]):
            print("    %-20s %d" % (k, agg[k]))
    print("\nexamples:")
    for r in changed[:40]:
        print("  %s %-14s %s%-4s  +%s  -%s" % (
            r["rcept_no"], (r["corp_name"] or "")[:12], r["fy"], r["fp"] or "",
            ",".join(r["gained"]) or "-", ",".join(r["lost"]) or "-"))
    if out_path and changed:
        Path(out_path).write_text(
            "\n".join(r["rcept_no"] for r in changed) + "\n")
        print("\nchanged filing list -> %s" % out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--rcept-file")
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--workers", type=int, default=4,
                    help="keep this small - 8 already exhausted memory on a "
                         "full re-load in this project, 32 killed the workers "
                         "outright, and the machine is shared with the "
                         "campaign session (camp_run) which reads the same SD "
                         "card and DB. Run it under `nice` too.")
    ap.add_argument("--storage", choices=("sd", "nas", "both"), default="sd")
    ap.add_argument("--checkpoint", default=None,
                    help="JSONL of finished filings; re-running resumes from it")
    ap.add_argument("--out", help="write changed rcept_no list here")
    args = ap.parse_args()

    with get_session() as s:
        rows = list(_population(s, args.rcept_file))
    print("population: %d" % len(rows))
    if args.limit and len(rows) > args.limit:
        if args.sample:
            random.Random(args.seed).shuffle(rows)
        rows = rows[:args.limit]

    done: dict = {}
    ck = Path(args.checkpoint) if args.checkpoint else None
    if ck and ck.exists():
        for line in ck.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            done[r["rcept_no"]] = r
        print("checkpoint: %d already measured -> resuming" % len(done))

    todo = []
    for seq, r in enumerate(rows):
        if r["rcept_no"] in done:
            continue
        d = dict(r)
        d["_storage"] = args.storage
        d["_seq"] = seq
        todo.append(d)
    print("to measure: %d   storage=%s   workers=%d"
          % (len(todo), args.storage, args.workers), flush=True)

    results = list(done.values())
    t0 = time.time()
    fh = ck.open("a") if ck else None
    try:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_measure_one, m): m["rcept_no"] for m in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                res = fut.result()      # BrokenProcessPool raises here
                results.append(res)
                if fh:
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                    if i % 100 == 0:
                        fh.flush()
                if i % 250 == 0:
                    el = time.time() - t0
                    rate = i / el if el else 0
                    left = (len(todo) - i) / rate if rate else 0
                    n_lost = sum(1 for r in results
                                 if r["status"] == "changed" and r["lost"])
                    print("  ... %d/%d  %.2f files/s  eta %.1fh  lost_so_far=%d"
                          % (i, len(todo), rate, left / 3600.0, n_lost),
                          flush=True)
    finally:
        if fh:
            fh.close()

    _report(results, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
