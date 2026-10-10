"""Rewrite the web-viewer prints built before the <BR> fix (2026-10-10): drop <BR> elements
(fin2/extract/viewer_xml.strip_line_breaks — the viewer's rendering of DART's `&cr;`, which the
DART XML reader deletes). A kept <BR/> was read as the text '<BR/>' (labels like
'Ⅴ. 이익잉여금<BR/>' in 176 filings, 20180906000287 lost every title -> 0 rows).

Each rewritten file gets viewer_built_at = now() (the NAS -> SD mirror follows it) and
layer2_reload_pending = TRUE.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/strip_viewer_br.py [--apply]
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.getcwd())

from lxml import etree  # noqa: E402

from fin2.extract.viewer_xml import strip_line_breaks  # noqa: E402


def main():
    apply = "--apply" in sys.argv
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT rcept_no, viewer_xml_path FROM download_tasks WHERE viewer_xml_path IS NOT NULL")
    rows = cur.fetchall()
    files = removed = 0
    for rc, path in rows:
        tree = etree.parse(path)
        n = strip_line_breaks(tree.getroot())
        if not n:
            continue
        files += 1
        removed += n
        if apply:
            tree.write(path, encoding="utf-8", xml_declaration=True)
            cur.execute("""UPDATE download_tasks SET viewer_built_at = %s, layer2_reload_pending = TRUE
                           WHERE rcept_no = %s AND viewer_xml_path = %s""", (datetime.now(), rc, path))
    if apply:
        conn.commit()
    conn.close()
    print(f"prints {len(rows)} · rewritten {files} · <BR> removed {removed}", "" if apply else "(dry run)")


if __name__ == "__main__":
    main()
