"""
Multiprocess driver for census_note_span_misattribution.py — see that file's docstring for
what "defect" means here and the BASELINE vs POSTFIX distinction.

Full-population run (2026-08-07, BASELINE-only, pre-fix code path): 101,327 filings, 0 parse
errors, 28,189,281/245,499,415 amount values (11.48%) mis-attributed to the wrong column,
12,011,666 defect rows, 100,272/101,327 filings (99.0%) affected. ~58min with 8 worker processes.
BASELINE never changes regardless of pipeline code — it's a hardcoded historical replica of the
pre-fix bug, kept only for reference. The T3.1 pass/fail signal is POSTFIX (added 2026-08-08),
which actually calls the current pipeline's `expand_table_grid` (R11 fix) and should converge
to ~0 defects if the fix is correct.

Investigation-only — does not touch the DB. See docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md
and docs/plans/note_span_fix_plan_2026-08-07.md §3 (T3.1).
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for census_note_span_misattribution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for collector.db (project root)

from collector.db import engine
from sqlalchemy import text
from concurrent.futures import ProcessPoolExecutor


def work(fp):
    from census_note_span_misattribution import analyze_filing
    try:
        n_tables, stats = analyze_filing(fp)
        return ("ok",) + tuple(stats)
    except Exception:
        return ("err", 0, 0, 0, 0, 0, 0)


if __name__ == "__main__":
    t0 = time.time()
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()]
        rows = conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall()
        paths = dict(rows)
    print(f"filings to scan: {len(rcepts)} (path lookup {time.time()-t0:.0f}s)", flush=True)

    fps = []
    missing = 0
    for r in rcepts:
        fp = paths.get(r)
        if fp:
            fps.append(fp)
        else:
            missing += 1
    print(f"missing file_path for {missing} rcept_no (skipped)", flush=True)

    n_ok = n_err = n_defect_filings_postfix = 0
    # rows_scanned, defect_rows_baseline, defect_values_baseline, amount_values_total,
    # defect_rows_postfix, defect_values_postfix
    grand = [0, 0, 0, 0, 0, 0]
    t1 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(work, fps, chunksize=8)):
            status = res[0]
            stats = res[1:]
            if status == "ok":
                n_ok += 1
                for k in range(6):
                    grand[k] += stats[k]
                if stats[5] > 0:  # defect_values_postfix
                    n_defect_filings_postfix += 1
            else:
                n_err += 1
            if (i + 1) % 5000 == 0:
                el = time.time() - t1
                rate = (i + 1) / el
                eta = (len(fps) - (i + 1)) / rate if rate > 0 else 0
                print(f"...{i+1}/{len(fps)} ({el:.0f}s, {rate:.1f}/s, eta {eta/60:.1f}min) "
                      f"ok={n_ok} err={n_err} defect_filings_postfix={n_defect_filings_postfix} "
                      f"defect_values_postfix={grand[5]} defect_values_baseline={grand[2]} "
                      f"amount_values={grand[3]}", flush=True)

    print("=" * 70)
    print(f"total filings                          : {len(fps)}")
    print(f"parsed ok                              : {n_ok}")
    print(f"parse errors                           : {n_err}")
    print(f"rows scanned                           : {grand[0]}")
    print(f"amount values total                    : {grand[3]}")
    print(f"BASELINE defect values (pre-fix, hist) : {grand[2]} "
          f"({grand[2]/max(1,grand[3])*100:.2f}% of amount values)")
    print(f"BASELINE defect rows                   : {grand[1]}")
    print(f"POSTFIX defect values (actual pipeline): {grand[5]} "
          f"({grand[5]/max(1,grand[3])*100:.2f}% of amount values)  <- T3.1 pass/fail")
    print(f"POSTFIX defect rows                    : {grand[4]}")
    print(f"filings with >=1 POSTFIX defect        : {n_defect_filings_postfix} "
          f"({n_defect_filings_postfix/max(1,len(fps))*100:.1f}%)")
    print(f"elapsed total                          : {time.time()-t0:.0f}s")
