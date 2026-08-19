"""P2-1 remediation, sample-of-3 trial: re-download the 3 filings that were
[014]-fallback (xbrl_zip) at collection time, now that DART's document.xml
API returns cleanly for them (confirmed by scripts/investigate_p2_2_014_recheck.py).

Their download_tasks rows were reset to status='pending' + cleared
file_type/parser_track/dcm_no/file_path so run_downloads() picks them up
through the REAL pipeline code (not a hand-rolled save), targeting only the
2 corps involved so nothing else in the download queue is touched.

Precondition: rcept_no in (20260814003597, 20260811000654, 20260813001784)
already reset to pending via a manual UPDATE (see session log) -- this
script does not do that reset itself, to keep the reset an explicit,
auditable step.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.downloader import run_downloads  # noqa: E402

stats = run_downloads(only_corp_codes=["01032486", "00138516"])
print(stats)
