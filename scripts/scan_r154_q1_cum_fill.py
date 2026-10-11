#!/usr/bin/env python
"""R154/R116 → layer 3 (2026-10-11, user decision) — find the filings whose layer 2 holds a
Q1 cumulative cell filled from the 3-month column.

Layer 2 rows carry no mark of that fill, so the source is read again: every 2015+ Q1 filing
with an XML source (main XML or web-viewer print) is extracted once with only the step
`R154_q1_cum_fill` on, and `select_by_header_columns` is wrapped so that each call that was
allowed to fill is repeated without the fill. A filing is a target when any call differs.
Read-only: nothing is written to the DB.

    python scripts/scan_r154_q1_cum_fill.py --shard 0 --of 4       # one shard
    python scripts/scan_r154_q1_cum_fill.py --merge --of 4          # merge shard files

Raw files are read from the SD mirror when present (NAS SMB stalls on bulk reads).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
import fin2.extract.report_lines as RL  # noqa: E402
from fin2.extract import as_printed as AP  # noqa: E402
from fin2.verification.ops import _sd_path  # noqa: E402

_OUT = Path(__file__).resolve().parents[1] / "docs/qa"
_STEP = "R154_q1_cum_fill"


def _targets() -> list[tuple]:
    with get_session() as s:
        return list(s.execute(text("""
            SELECT f.rcept_no,
                   CASE WHEN dt.status = 'completed' AND dt.file_type = 'xml' THEN dt.file_path
                        ELSE dt.viewer_xml_path END AS fp,
                   f.corp_code, f.fiscal_year
            FROM filings f JOIN download_tasks dt USING (rcept_no)
            WHERE f.fiscal_period = 'Q1' AND f.fiscal_year >= 2015
              AND ((dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL)
                   OR dt.viewer_xml_path IS NOT NULL)
              AND EXISTS (SELECT 1 FROM report_lines rl WHERE rl.rcept_no = f.rcept_no)
            ORDER BY f.rcept_no""")))


def scan(shard: int, of: int, limit: int | None = None, only: set | None = None) -> Path:
    out = (_OUT / f"r154_q1_cum_fill_scan.shard{shard}of{of}.jsonl" if not only
           else Path("/dev/stdout"))
    done = set()
    if not only and out.exists():
        done = {json.loads(l)["rcept"] for l in out.read_text(encoding="utf-8").splitlines() if l}
    orig = RL.select_by_header_columns
    hits: list[int] = []

    def wrapped(*a, **kw):
        res = orig(*a, **kw)
        if kw.get("allow_three_month_as_cumulative"):
            if res != orig(*a, **{**kw, "allow_three_month_as_cumulative": False}):
                hits.append(1)
        return res

    RL.select_by_header_columns = wrapped
    AP.DISABLED.update(s for s in AP.STEPS if s != _STEP)
    rows = [t for i, t in enumerate(_targets()) if i % of == shard and t.rcept_no not in done]
    rows = rows[:limit] if limit else rows
    rows = [t for t in rows if t.rcept_no in only] if only else rows
    with out.open("a", encoding="utf-8") as fh:
        for n, t in enumerate(rows, 1):
            rec = {"rcept": t.rcept_no, "corp": t.corp_code, "year": t.fiscal_year}
            try:
                hits.clear()
                with AP.forced("repaired"):
                    RL.extract_report_lines(
                        _sd_path(t.fp), rcept_no=t.rcept_no, corp_code=t.corp_code,
                        report_fiscal_year=t.fiscal_year, report_fiscal_period="Q1",
                        include_notes=False)
                rec["fill_calls"] = len(hits)
            except Exception as e:  # keep scanning; the failure is recorded
                rec["error"] = f"{type(e).__name__}: {e}"[:200]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if n % 200 == 0:
                print(f"shard {shard}: {n}/{len(rows)}", flush=True)
    return out


def merge(of: int) -> None:
    recs = []
    for i in range(of):
        p = _OUT / f"r154_q1_cum_fill_scan.shard{i}of{of}.jsonl"
        recs += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l]
    hit = sorted(r["rcept"] for r in recs if r.get("fill_calls"))
    err = [r for r in recs if "error" in r]
    (_OUT / "r154_q1_cum_fill_targets.txt").write_text("\n".join(hit) + "\n", encoding="utf-8")
    print(f"scanned {len(recs)} · targets {len(hit)} · errors {len(err)}")
    for r in err[:10]:
        print("  error", r["rcept"], r["error"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--rcepts", nargs="*", help="check these filings only, print to stdout")
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    merge(a.of) if a.merge else print(scan(a.shard, a.of, a.limit, set(a.rcepts or ())))
