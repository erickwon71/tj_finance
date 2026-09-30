"""Park verification issues raised on 2015+ PDF-only filings ("PDF-only hold").

PDF-only = the filing has a completed PDF download, no completed non-PDF download and
zero report_lines (docs/qa/handoff_2026-09-29_pdf_only_2015plus_gap.md; user decision
2026-10-01: hold them for the whole 2015+ campaign). For every unassigned open/reopened
issue on such a filing this creates one batch per error_type, then sets it to
`waiting_decision` (parked) with a note, so fix-queue stops listing them as unassigned.
`abandoned` is refused by vq.py while the issues are still `fixing`. NEVER run
`vq.py batch reload` on these batches — they are holds, not fixes.

Usage (cwd = repo root, DATABASE_URL in env):
    python scripts/hold_pdf_only_issues.py            # dry run
    python scripts/hold_pdf_only_issues.py --apply
"""
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict

import psycopg2

SQL = """
with pdfonly as (
  select f.rcept_no from filings f
  where f.fiscal_year >= 2015
    and exists (select 1 from download_tasks d where d.rcept_no = f.rcept_no
                and d.file_type = 'pdf' and d.status = 'completed')
    and not exists (select 1 from download_tasks d where d.rcept_no = f.rcept_no
                    and d.file_type <> 'pdf' and d.status = 'completed')
    and not exists (select 1 from report_lines r where r.rcept_no = f.rcept_no))
select i.error_type, i.issue_id, i.rcept_no
from verification.issues i join pdfonly p using (rcept_no)
where i.fix_batch_id is null and i.status in ('open', 'reopened')
order by 1, 2
"""
NOTE = ("PDF-only 보류(사용자 결정 2026-10-01): 2015+ 캠페인 동안 PDF만 제공되는 필링은 적재하지 않는다. "
        "근거 docs/qa/handoff_2026-09-29_pdf_only_2015plus_gap.md. 이슈 {n}건 · 필링 {f}건.")


def vq(*args):
    out = subprocess.run([sys.executable, "scripts/vq.py", *args], check=True,
                         capture_output=True, text=True).stdout
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    apply = ap.parse_args().apply
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute(SQL)
    by_type = defaultdict(list)
    for et, iid, rc in cur.fetchall():
        by_type[et].append((iid, rc))
    if not by_type:
        print("nothing to hold")
        return
    for et, rows in by_type.items():
        ids = [r[0] for r in rows]
        files = len({r[1] for r in rows})
        print(f"{et}: issues {len(ids)} filings {files}")
        if not apply:
            continue
        out = vq("batch", "new", "--type", et, "--title", "PDF-only 보류 (2015+ 캠페인 동안 미적재)",
                 "--issues", ",".join(map(str, ids)))
        bid = json.loads(out[out.index("{"):])["batch_id"]
        vq("batch", "set", str(bid), "--status", "waiting_decision", "--note", NOTE.format(n=len(ids), f=files))
        print(f"  -> batch #{bid} parked (waiting_decision)")
    if not apply:
        print("dry run — pass --apply")


if __name__ == "__main__":
    main()
