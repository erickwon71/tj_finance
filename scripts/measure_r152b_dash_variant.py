#!/usr/bin/env python
"""R152-b scale - how many filings lost a row to the dash zero-placeholder?

R152 pulls the leading main-item amount out of a compacted supplementary-reserve
cell. Its head regex required the amount to be followed directly by `(`. When
the first supplementary figure is zero the source prints it as `-`
('623,930- (692)(692)'), the regex missed, the cell became missing, and - since
BS loads only the current column - the whole row vanished.

Population: filings whose XML mentions 대손준비금/비상위험준비금 (SD-mirror grep;
that is what the SD card is fast at). For each, extract with the OLD regex and
the NEW one and diff the rows that carry a value.

Read-only.

Usage:
    python scripts/measure_r152b_dash_variant.py --file-list <grep output>
"""
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml import table_extractor as TE
from fin2.extract.report_lines import extract_report_lines

_SD = "/Volumes/dart_data/raw_report"

# The pre-R152-b head regex, verbatim.
_OLD_HEAD = re.compile(r"^([-−△▲]?\s*(?:\d{1,3}(?:,\d{3})+|\d{4,}))\s*\(")


def _keys(path: Path, meta: dict) -> set:
    rows = extract_report_lines(
        path, rcept_no=meta["rcept_no"], corp_code=meta["corp_code"],
        report_fiscal_year=meta["fiscal_year"],
        report_fiscal_period=meta["fiscal_period"])
    return {(l.statement, l.basis, (l.label_raw or "").strip(),
             l.col_index, l.value_won)
            for l in rows if l.value_won is not None}


def _one(job: dict) -> dict:
    out = {"rcept_no": job["rcept_no"], "corp_name": job["corp_name"],
           "status": "same", "gained": 0, "lost": 0, "labels": []}
    path = Path(job["path"])
    if not path.exists():
        out["status"] = "missing"
        return out
    real = TE._COMPACTED_PAREN_HEAD_RE
    try:
        TE._COMPACTED_PAREN_HEAD_RE = _OLD_HEAD
        before = _keys(path, job)
        TE._COMPACTED_PAREN_HEAD_RE = real
        after = _keys(path, job)
    except Exception as exc:                            # noqa: BLE001
        out["status"] = "error"
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        return out
    finally:
        TE._COMPACTED_PAREN_HEAD_RE = real

    only_after = after - before
    only_before = before - after
    if not only_after and not only_before:
        return out
    out["status"] = "changed"
    out["gained"] = len(only_after)
    out["lost"] = len(only_before)
    out["labels"] = sorted({"%s/%s %s" % (s, b, l[:34])
                            for s, b, l, _c, _v in only_after})[:4]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file-list", required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    rels = [l.strip().lstrip("./") for l in open(args.file_list) if l.strip()]
    rcepts = [Path(r).stem for r in rels]
    print("candidate filings (grep): %d" % len(rels))

    with get_session() as s:
        meta = {r["rcept_no"]: dict(r) for r in s.execute(text("""
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period,
                   c.corp_name
            FROM filings f JOIN corporations c USING (corp_code)
            WHERE f.rcept_no = ANY(:r) AND f.fiscal_year >= 2015"""),
            {"r": rcepts}).mappings()}
    print("with 2015+ metadata: %d" % len(meta))

    jobs = []
    for rel in rels:
        rc = Path(rel).stem
        m = meta.get(rc)
        if not m:
            continue
        j = dict(m)
        j["path"] = "%s/%s" % (_SD, rel)
        jobs.append(j)
    print("to measure: %d" % len(jobs), flush=True)

    changed = []
    n_err = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_one, j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r["status"] in ("error", "missing"):
                n_err += 1
            elif r["status"] == "changed":
                changed.append(r)
            if i % 200 == 0:
                print("  ... %d/%d  changed=%d" % (i, len(jobs), len(changed)),
                      flush=True)

    tot_gained = sum(c["gained"] for c in changed)
    tot_lost = sum(c["lost"] for c in changed)
    print("\nmeasured=%d  changed=%d  unreadable/error=%d"
          % (len(jobs), len(changed), n_err))
    print("  rows gained: %d" % tot_gained)
    print("  rows lost  : %d   <- must be 0" % tot_lost)
    for c in sorted(changed, key=lambda x: -x["gained"])[:25]:
        print("  %s %-16s +%d -%d  %s" % (
            c["rcept_no"], (c["corp_name"] or "")[:14], c["gained"], c["lost"],
            "; ".join(c["labels"])[:90]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
