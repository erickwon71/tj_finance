"""Scope narrowing for face_audit.py NI-attribution vs comprehensive-income-attribution
mislabel bug (01137383 2024Q3 case, see memory gateb-r44-resolve-redesign-2026-08-25
appendix C follow-up, 2026-08-26 investigation).

For each face_audit fail row on is.controlling_ni/is.noncontrolling_ni, this determines
whether the SAME mechanism is at play: the generic Track B mapper (account_mapper.map())
picks up a "...지분순이익(손실)"-style label from the *comprehensive-income* attribution
section (no literal "포괄" in the label itself, so account_mapper's existing guards don't
catch it) and that wrong value pre-empts `_with_ni_attribution_text_fallback()`'s
"already have it" skip-gate, starving the structurally-aware
`_ni_attribution_text_candidates()` of its chance to supply the correct value.

Method (원문 직접 실행 대조, no guessing):
  1. Pull all face_audit fail rows for is.controlling_ni/is.noncontrolling_ni (source=v3).
  2. Resolve each row's IS-statement source file via std_financials_v3.source_rcepts + the
     download_tasks file_path (rewritten from the NAS symlink target to the SD card mirror,
     per [[feedback-bulk-read-use-sdcard]]).
  3. Parse the raw XML once, then run BOTH:
       - the actual production reader (`read_report_face_tracked`) to reproduce report_won,
       - the structurally-aware fallback in isolation (`_ni_attribution_text_candidates`)
         to see what it WOULD have found had it been given the chance.
  4. Classify a row as "confirmed pattern" only if:
       - the production reader's candidate set for that canonical matches report_won
         (reproduces the fail as recorded), AND
       - the structural function's candidate set (run standalone) contains db_won
         (proves the correct value was recoverable via the section-aware route), AND
       - db_won is NOT in the production candidate set (proves it never got the chance —
         the skip-gate starved it).
  Anything else is left "unclassified" — not guessed at.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text as sqltext
from collector.db import get_session
from fin2.audit.face_audit import (
    read_report_face_tracked, _ni_attribution_text_candidates, _parse_xml_file,
)

NAS_MARK = "/raw_report/"
SD_ROOT = "/Volumes/dart_data/raw_report/"


def sd_path(nas_or_local_path: str) -> str | None:
    idx = nas_or_local_path.find(NAS_MARK)
    if idx == -1:
        return None
    return SD_ROOT + nas_or_local_path[idx + len(NAS_MARK):]


def main() -> None:
    with get_session() as session:
        _run(session)


def _run(session) -> None:
    rows = session.execute(sqltext("""
        SELECT corp_code, fiscal_year, fiscal_period, fail_detail
        FROM face_audit
        WHERE source_version = 'v3' AND status = 'fail'
    """)).fetchall()

    targets = []
    for corp, fy, fp, fd in rows:
        if not fd:
            continue
        for item in fd:
            if item.get("canonical") in ("is.controlling_ni", "is.noncontrolling_ni"):
                targets.append((corp, fy, fp, item["canonical"], item["db_won"], item["report_won"]))
    print(f"total target rows: {len(targets)}")

    results = []
    for corp, fy, fp, canon, db_won, report_won in targets:
        row = session.execute(sqltext("""
            SELECT source_rcepts FROM std_financials_v3
            WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
        """), {"c": corp, "y": fy, "p": fp}).fetchone()
        if not row or not row[0]:
            results.append((corp, fy, fp, canon, db_won, report_won, "NO_SOURCE_RCEPTS", None))
            continue
        rcepts = row[0]
        is_rcept = rcepts.get("IS")
        if not is_rcept:
            results.append((corp, fy, fp, canon, db_won, report_won, "NO_IS_RCEPT", None))
            continue
        dt = session.execute(sqltext("""
            SELECT file_path, file_type FROM download_tasks
            WHERE rcept_no=:r AND status='completed' AND file_path IS NOT NULL
            ORDER BY CASE file_type WHEN 'xml' THEN 0 WHEN 'pdf' THEN 1 WHEN 'xbrl_zip' THEN 2 ELSE 9 END
            LIMIT 1
        """), {"r": is_rcept}).fetchone()
        if not dt or dt[1] != "xml":
            results.append((corp, fy, fp, canon, db_won, report_won, "NO_XML_FILE", None))
            continue
        path = sd_path(dt[0])
        if not path or not Path(path).exists():
            results.append((corp, fy, fp, canon, db_won, report_won, "SD_PATH_MISSING", None))
            continue

        root = _parse_xml_file(Path(path))
        if root is None:
            results.append((corp, fy, fp, canon, db_won, report_won, "PARSE_FAILED", None))
            continue

        try:
            prod_lines, track = read_report_face_tracked(path)
        except Exception as e:  # noqa: BLE001 -- probe script, log and continue
            results.append((corp, fy, fp, canon, db_won, report_won, f"READER_EXC:{e}", None))
            continue
        prod_vals = {ln.amount_won for ln in prod_lines if ln.canonical == canon}

        try:
            struct_lines = _ni_attribution_text_candidates(root)
        except Exception as e:  # noqa: BLE001
            results.append((corp, fy, fp, canon, db_won, report_won, f"STRUCT_EXC:{e}", None))
            continue
        struct_vals = {ln.amount_won for ln in struct_lines if ln.canonical == canon}

        reproduced = report_won in prod_vals
        recoverable = db_won in struct_vals
        starved = db_won not in prod_vals

        if reproduced and recoverable and starved:
            verdict = "CONFIRMED_PATTERN"
        elif reproduced and not recoverable:
            verdict = "REPRODUCED_BUT_STRUCT_FUNC_ALSO_MISSES"
        elif not reproduced:
            verdict = "NOT_REPRODUCED"
        else:
            verdict = "OTHER"
        results.append((corp, fy, fp, canon, db_won, report_won, verdict, track))
        print(corp, fy, fp, canon, verdict, track)

    out = Path("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
               "cf828295-d75c-4a81-9d42-16abb4f65081/scratchpad/faceaudit_ni_oci_scope_2026-08-26.csv")
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["corp", "fy", "fp", "canonical", "db_won", "report_won", "verdict", "track"])
        w.writerows(results)
    print(f"\nwrote {out}")

    from collections import Counter
    print(Counter(r[6] for r in results))


if __name__ == "__main__":
    main()
