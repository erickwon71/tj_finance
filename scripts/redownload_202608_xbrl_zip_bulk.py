"""Bulk remediation (2026-08-19, user-directed): reset all 2026-08 xbrl_zip-only
download_tasks back to pending (clearing file_type/parser_track/dcm_no/file_path/
file_size/parse_status/parsed_facts/completed_at) so run_downloads() retries them
through the now-fixed downloader (see collector/downloader.py's 2026-08-19 policy
comment: [014] no longer auto-falls back to xbrl_instance/legacy, it retries
document.xml daily instead).

Scope: ONLY filings.filed_at in 2026-08 (the half-report deadline rush that
caused this — confirmed via scripts/investigate_p2_2_sample_check.py, 15/15
sample resolved cleanly on re-request). Older xbrl_zip completions (2015-2020,
pre-2015 backfill era) are untouched — different, unrelated, often-permanent
cases.

Old raw_report .zip files are left in place (not deleted) — harmless orphans,
easy to clean up later once the .xml replacement is confirmed good.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from collector.downloader import run_downloads  # noqa: E402

with get_session() as session:
    corp_codes = session.execute(text("""
        SELECT DISTINCT f.corp_code
        FROM download_tasks dt JOIN filings f USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xbrl_zip'
          AND f.filed_at >= '2026-08-01' AND f.filed_at < '2026-09-01'
    """)).scalars().all()
    print(f"대상 기업 수: {len(corp_codes)}")

    result = session.execute(text("""
        UPDATE download_tasks dt
        SET status='pending', file_type=NULL, parser_track=NULL, dcm_no=NULL,
            file_path=NULL, file_size=NULL, parse_status=NULL, parsed_facts=NULL,
            completed_at=NULL
        FROM filings f
        WHERE dt.rcept_no = f.rcept_no
          AND dt.status='completed' AND dt.file_type='xbrl_zip'
          AND f.filed_at >= '2026-08-01' AND f.filed_at < '2026-09-01'
        RETURNING dt.rcept_no
    """))
    reset_rcepts = result.scalars().all()
    print(f"리셋된 rcept_no 수: {len(reset_rcepts)}")

print("\n재다운로드 시작...")
stats = run_downloads(only_corp_codes=corp_codes)
print(stats)
