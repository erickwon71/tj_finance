"""Retitle the SECTION-2 of already built web-view prints by what their body prints (R381).

The generator named a statement section '2. 연결재무제표' only when the TOC node text said 연결, so
review-report layouts ('반 기 재 무 제 표') and 'XI. 재무제표 등' nodes were stored as basis=separate
although the body prints 연결 statements. `viewer_xml.fix_basis_titles` fixes new builds; this script
applies the same function to the prints on disk (no DART refetch).

Usage (cwd = repo root):
  python scripts/r0_2_migration/fix_viewer_basis_titles.py <out.jsonl>            # dry run
  python scripts/r0_2_migration/fix_viewer_basis_titles.py <out.jsonl> --apply    # rewrite files

The out file lists one record per changed print ({rcept, path, changed, titles_before/after}).
Rewritten files keep the old bytes next to them as <name>.basis_bak (removed by hand later).
After --apply, reload the listed filings with `vq.py batch add-targets` + `batch reload`.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())


def main():
    out_path, apply = sys.argv[1], "--apply" in sys.argv
    import psycopg2
    from lxml import etree
    from fin2.extract.viewer_xml import fix_basis_titles

    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor()
    cur.execute("SELECT rcept_no, viewer_xml_path FROM download_tasks "
                "WHERE viewer_xml_path IS NOT NULL ORDER BY 1")
    rows = cur.fetchall()
    conn.close()
    n_changed = n_err = 0
    with open(out_path, "w") as fo:
        for rc, p in rows:
            rec = {"rcept": rc, "path": p}
            try:
                raw = Path(p).read_bytes()
                root = etree.fromstring(raw)
                before = [s.findtext("TITLE") for s in root.iter("SECTION-2")]
                n = fix_basis_titles(root)
                if not n:
                    continue
                rec.update(changed=n, titles_before=before,
                           titles_after=[s.findtext("TITLE") for s in root.iter("SECTION-2")])
                if apply:
                    Path(p + ".basis_bak").write_bytes(raw)
                    tmp = Path(p + ".tmp")
                    tmp.write_bytes(etree.tostring(root, encoding="utf-8", xml_declaration=True))
                    tmp.replace(p)
                n_changed += 1
            except Exception as e:      # noqa: BLE001 - report and continue
                rec["err"] = f"{type(e).__name__}: {str(e)[:120]}"
                n_err += 1
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"prints {len(rows)} changed {n_changed} err {n_err}", "(applied)" if apply else "(dry run)")


if __name__ == "__main__":
    main()
