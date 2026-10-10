"""Collect the printed document (DART web viewer) for FY2015+ filings that have no main XML
(loaded from XBRL, or PDF-only) — user decisions 2026-10-10. Saves a DART-style XML next to the
source file (<same folder>/<rcept>.xml) via fin2/extract/viewer_xml.py. Read-only on the DB.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/collect_viewer_xml.py <manifest.jsonl> [limit]
Resumable: rcepts already in the manifest with status ok are skipped. Requests are throttled by
LegacyDartScraper (2 s between requests).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

# XBRL-only filings (no main XML), and PDF-only filings with no layer-2 rows except
# [첨부정정] (an audit/review report with the statements attached — another section layout,
# handled separately). User decisions 2026-10-10.
SQL = """
SELECT x.rcept_no, x.file_path FROM download_tasks x JOIN filings f USING (rcept_no)
WHERE x.file_type = 'xbrl_zip' AND x.status = 'completed' AND f.fiscal_year >= 2015
  AND NOT EXISTS (SELECT 1 FROM download_tasks d WHERE d.rcept_no = x.rcept_no AND d.file_type = 'xml')
UNION
SELECT d.rcept_no, d.file_path FROM download_tasks d JOIN filings f USING (rcept_no)
WHERE d.file_type = 'pdf' AND d.status = 'completed' AND f.fiscal_year >= 2015
  AND f.report_nm NOT LIKE '%%첨부정정%%'
  AND NOT EXISTS (SELECT 1 FROM download_tasks x WHERE x.rcept_no = d.rcept_no
                  AND x.file_type <> 'pdf' AND x.status = 'completed')
  AND NOT EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = d.rcept_no)
ORDER BY 1 DESC"""


def main():
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    import psycopg2
    from collector.legacy_downloader import LegacyDartScraper
    from fin2.extract.html_viewer import parse_toc_tree
    from fin2.extract.viewer_xml import build_document, is_statement_section

    manifest = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    done = set()
    if os.path.exists(manifest):
        done = {d["rcept"] for d in map(json.loads, open(manifest)) if d["status"] == "ok"}
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute(SQL)
    targets = [(r, p) for r, p in cur.fetchall() if r not in done][:limit]
    print("targets", len(targets), flush=True)
    s = LegacyDartScraper()
    with open(manifest, "a") as fo:
        for i, (rc, zip_path) in enumerate(targets, 1):
            rec = {"rcept": rc}
            try:
                toc = s.fetch_toc_page(rc)
                nodes = parse_toc_tree(toc or "")
                picked = [n for n in nodes if is_statement_section(n.text)]
                if not picked:
                    rec.update(status="no_statement_nodes", toc=[n.text for n in nodes][:40])
                else:
                    sections = []
                    for n in picked:
                        raw = s.fetch_viewer_section(rc, dcm_no=n.dcm_no, ele_id=n.ele_id,
                                                     offset=n.offset, length=n.length, dtd=n.dtd)
                        sections.append((n.text, raw or b""))
                    out = Path(zip_path).with_suffix(".xml")
                    data = build_document(sections)
                    out.write_bytes(data)
                    rec.update(status="ok", path=str(out), bytes=len(data),
                               sections=[(t, len(b)) for t, b in sections])
            except Exception as e:
                rec.update(status=f"err {type(e).__name__}: {str(e)[:200]}")
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fo.flush()
            if i % 50 == 0:
                print(i, flush=True)
    s.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
