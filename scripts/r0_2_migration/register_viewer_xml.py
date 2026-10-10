"""Register the collected web-viewer prints (collect_viewer_xml.py) as the layer-2 source
(docs/plans/viewer_xml_source_policy_2026-10-10.md).

  1. <rcept>.xml written by the collector -> <rcept>.viewer.xml (the package's own XML, if it
     ever arrives, is saved as <rcept>.xml).
  2. download_tasks.viewer_xml_path / viewer_built_at, layer2_reload_pending = TRUE.
  3. --recheck-package: one OpenDART document.xml call per filing. A package that now holds a
     main XML is queued for the daily downloader (status pending, xml_pending_since now), which
     saves it and flags the reload from it (collector/downloader.py::_mark_completed).

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/register_viewer_xml.py <manifest.jsonl> [--recheck-package] [--apply]
"""
import io
import json
import os
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())


def main():
    manifest, apply, recheck = sys.argv[1], "--apply" in sys.argv, "--recheck-package" in sys.argv
    import psycopg2
    rows = {}
    for d in map(json.loads, open(manifest)):
        rows[d["rcept"]] = d
    ok = [d for d in rows.values() if d["status"] == "ok"]
    tally = Counter(d["status"].split(":")[0] for d in rows.values())
    print("manifest", dict(tally))
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    done = 0
    for d in ok:
        src = Path(d["path"])
        dst = src if src.name.endswith(".viewer.xml") else src.with_name(src.name[:-4] + ".viewer.xml")
        if apply:
            if src != dst and src.exists():
                src.rename(dst)
            cur.execute("""UPDATE download_tasks SET viewer_xml_path = %s, viewer_built_at = %s,
                               layer2_reload_pending = TRUE WHERE rcept_no = %s""",
                        (str(dst), datetime.now(), d["rcept"]))
            done += 1
    if apply:
        conn.commit()
    print("registered", done, "(dry run)" if not apply else "")

    if recheck:
        from collector.dart_client import DartClient, DartApiError
        client = DartClient()
        found, none, err = [], 0, 0
        for d in ok:
            try:
                data = client.get_document_zip(d["rcept"])
                names = zipfile.ZipFile(io.BytesIO(data)).namelist()
                # the main XML is named exactly <rcept>.xml (R96, downloader._pick_body_by_filename);
                # XBRL packages also hold lab_*.xml / pre_*.xml linkbases
                if any(n.lstrip("/") == f"{d['rcept']}.xml" for n in names):
                    found.append(d["rcept"])
                else:
                    none += 1
            except (DartApiError, zipfile.BadZipFile):
                none += 1
            except Exception as e:  # noqa: BLE001
                err += 1
                print("err", d["rcept"], type(e).__name__, str(e)[:120])
        client.close()
        print(f"package recheck: main XML now present {len(found)} · still none {none} · errors {err}")
        if apply and found:
            cur.execute("""UPDATE download_tasks SET status = 'pending', attempts = 0,
                               xml_pending_since = now() WHERE rcept_no = ANY(%s)""", (found,))
            conn.commit()
            print("queued for the daily downloader:", len(found))
    conn.close()


if __name__ == "__main__":
    main()
