#!/usr/bin/env python
"""R152 residual - supplementary-reserve cells that STILL do not parse.

R152 (+R152-b) pulls the leading main-item amount out of a compacted
supplementary-reserve cell. Two source shapes are handled: space-separated and
paren-joined, with an optional dash zero-placeholder. There may be others, and
each one silently deletes a face row (BS loads only the current column, so the
row disappears rather than going null).

This finds them before the campaign does: for every filing that mentions
대손준비금/비상위험준비금, extract the tables and report any row whose label
matches the reserve pattern but whose amount cell is non-empty and still yields
no value. Those are the shapes the rule does not cover yet.

Read-only.

Usage:
    python scripts/scan_r152_unparsed_variants.py --file-list <grep output>
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import _detect_fin_type, _parse_xml_file
from fin2.extract.text import _detect_body_statement_tables
from parser.common.amount_normalizer import parse_amount
from parser.xml.section_detector import table_direct_rows
from parser.xml.table_extractor import (
    _AMOUNT_LIKE_RE, _SUPPLEMENTARY_RESERVE_RE,
    _first_of_compacted_supplementary_cell, _get_cells)

_SD = "/Volumes/dart_data/raw_report"


def _one(job: dict) -> dict:
    out = {"rcept_no": job["rcept_no"], "corp_name": job["corp_name"],
           "fy": job["fiscal_year"], "hits": []}
    path = Path(job["path"])
    if not path.exists():
        return out
    try:
        root = _parse_xml_file(path)
        if root is None:
            return out
        fin_type = _detect_fin_type(root, file_path=str(path))
        groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    except Exception:                                   # noqa: BLE001
        return out

    for code, entries in groups.items():
        for tbl, _u, _k in entries:
            for tr in table_direct_rows(tbl):
                cells = _get_cells(tr)
                if not cells:
                    continue
                label = re.sub(r"\s+", " ", cells[0]).strip()
                if not _SUPPLEMENTARY_RESERVE_RE.search(label):
                    continue
                # ★Only the FIRST amount-bearing cell matters for BS/IS/CF:
                #   `_PERIOD_AXIS_STATEMENTS` loads col_index=0 alone, so an
                #   unreadable prior-year column never reaches the DB. Counting
                #   those would inflate the residual (they are the bulk of the
                #   raw hits - 대신증권's prior columns).
                seen_amount = False
                for pos, raw in enumerate(cells[1:]):
                    cell = re.sub(r"\s+", " ", raw).strip()
                    if not cell or cell in ("-", "—", "–"):
                        continue
                    if not re.search(r"\d", cell):
                        continue          # text - not an amount
                    # ★A note-number cell ('26, 27' - 미래에셋증권, documented in
                    #   R152) is not an amount at all. Production refuses it on
                    #   purpose; counting it as "unreadable" would be a scanner
                    #   false positive, so screen it out the same way.
                    if not _AMOUNT_LIKE_RE.match(cell.split()[0]):
                        continue
                    if seen_amount:
                        break             # prior-period column - not loaded
                    seen_amount = True
                    if parse_amount(_first_of_compacted_supplementary_cell(cell)) is None:
                        out["hits"].append({"code": code, "label": label[:60],
                                            "cell": cell[:60]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file-list", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--show", type=int, default=30)
    args = ap.parse_args()

    rels = [l.strip().lstrip("./") for l in open(args.file_list) if l.strip()]
    rcepts = [Path(r).stem for r in rels]
    with get_session() as s:
        meta = {r["rcept_no"]: dict(r) for r in s.execute(text("""
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period,
                   c.corp_name
            FROM filings f JOIN corporations c USING (corp_code)
            WHERE f.rcept_no = ANY(:r) AND f.fiscal_year >= 2015"""),
            {"r": rcepts}).mappings()}

    jobs = []
    for rel in rels:
        m = meta.get(Path(rel).stem)
        if not m:
            continue
        j = dict(m)
        j["path"] = "%s/%s" % (_SD, rel)
        jobs.append(j)
    print("to scan: %d" % len(jobs), flush=True)

    hits = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_one, j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r["hits"]:
                hits.append(r)
            if i % 250 == 0:
                print("  ... %d/%d  filings with an unparsed cell=%d"
                      % (i, len(jobs), len(hits)), flush=True)

    n_cells = sum(len(h["hits"]) for h in hits)
    print("\nfilings with a supplementary row we still cannot read: %d"
          % len(hits))
    print("unreadable cells: %d" % n_cells)

    shapes = Counter()
    for h in hits:
        for x in h["hits"]:
            c = x["cell"]
            if re.match(r"^[\d,]+\s*[-−–—]\s*\(", c):
                shapes["amount dash paren"] += 1
            elif re.match(r"^[\d,]+\s*\(", c):
                shapes["amount paren"] += 1
            elif " " in c:
                shapes["space separated"] += 1
            else:
                shapes["other / no separator"] += 1
    print("\nshape tally:")
    for k, v in shapes.most_common():
        print("  %-24s %d" % (k, v))

    print("\nsamples:")
    for h in hits[:args.show]:
        for x in h["hits"][:2]:
            print("  %s %-14s %s  %-7s %s" % (
                h["rcept_no"], (h["corp_name"] or "")[:12], h["fy"],
                x["code"], x["label"][:40]))
            print("      cell=%r" % x["cell"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
