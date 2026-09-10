"""census_sanemax_shift_2026-09-06.py의 55,573건 후보 중 진짜 R74 버그(당기값이
사한상한 근처까지 커서 거부됨)와 그냥 원문이 그 기간을 비운 정상 결측(특히 CF
세부항목에 흔함)을 가른다.

판정: 남아있는 값(present col_index 중 아무거나)의 절대값이 5000억원을 넘으면
"거부 근처까지 컸다"는 정황(정상 CF 세부항목이 500억원을 넘는 경우는 드묾) —
high_confidence. 아니면 low_confidence(원문 재확인 필요, 정상 결측일 가능성 높음).
읽기 전용, 판정만 — 백필은 이 결과를 보고 별도 결정.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

IN_CSV = Path(__file__).parent.parent / "scratch_census_sanemax_shift.csv"
OUT_CSV = Path(__file__).parent.parent / "scratch_census_sanemax_shift_triaged.csv"

HIGH_CONF_THRESHOLD = 500_000_000_000  # 5000억원


def _init_worker():
    from loguru import logger
    logger.remove()


def _triage_filing(item):
    rcept_no, file_path, targets = item
    from fin2.extract.report_lines import extract_report_lines
    p = Path(file_path)
    if not p.exists():
        return [(rcept_no, *t, "file_missing") for t in targets]

    corp_code = targets[0][0]
    fiscal_year = int(targets[0][1])
    results = []
    try:
        lines = extract_report_lines(
            p, rcept_no=rcept_no, corp_code=corp_code,
            report_fiscal_year=fiscal_year, report_fiscal_period=targets[0][2],
            include_notes=False,
        )
    except Exception as e:  # noqa: BLE001
        return [(rcept_no, *t, f"error:{str(e)[:100]}") for t in targets]

    by_key = defaultdict(list)
    for l in lines:
        key = (l.statement, l.basis, l.table_seq, l.label_raw)
        by_key[key].append((l.col_index, l.value_won))

    for (corp, fy, period, statement, basis, table_seq, label_raw, cols) in targets:
        key = (statement, basis, int(table_seq), label_raw)
        vals = by_key.get(key, [])
        max_abs = max((abs(v) for _, v in vals), default=0)
        verdict = "high_confidence" if max_abs >= HIGH_CONF_THRESHOLD else "low_confidence"
        results.append((corp, rcept_no, fy, period, statement, basis, table_seq, label_raw,
                         cols, max_abs, verdict))
    return results


def main():
    with open(IN_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"input rows: {len(rows)}")

    # rcept_no별로 묶고, file_path/fiscal_period 조회 필요 — DB에서 한 번에 가져온다.
    from sqlalchemy import text
    from collector.db import get_session

    rcept_nos = sorted({r["rcept_no"] for r in rows})
    print(f"distinct filings: {len(rcept_nos)}")
    path_map = {}
    period_map = {}
    with get_session() as session:
        for i in range(0, len(rcept_nos), 500):
            chunk = rcept_nos[i:i + 500]
            res = session.execute(text("""
                SELECT dt.rcept_no, dt.file_path, f.fiscal_period
                FROM download_tasks dt JOIN filings f USING(rcept_no)
                WHERE dt.rcept_no = ANY(:rs) AND dt.file_type='xml' AND dt.status='completed'
            """), {"rs": chunk}).fetchall()
            for r in res:
                path_map[r.rcept_no] = r.file_path
                period_map[r.rcept_no] = r.fiscal_period

    by_rcept = defaultdict(list)
    for r in rows:
        rc = r["rcept_no"]
        by_rcept[rc].append((r["corp_code"], r["fiscal_year"], period_map.get(rc, "FY"),
                              r["statement"], r["basis"], r["table_seq"], r["label_raw"],
                              r["cols_present"]))

    items = [(rc, path_map.get(rc), targets) for rc, targets in by_rcept.items()]

    from multiprocessing import Pool
    import time
    t0 = time.time()
    all_results = []
    with Pool(8, initializer=_init_worker) as pool:
        for i, res in enumerate(pool.imap_unordered(_triage_filing, items, chunksize=5)):
            all_results.extend(res)
            if (i + 1) % 500 == 0:
                print(f"  {i+1}/{len(items)} filings triaged, {time.time()-t0:.0f}s elapsed",
                      flush=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corp_code", "rcept_no", "fiscal_year", "fiscal_period", "statement",
                    "basis", "table_seq", "label_raw", "cols_present", "max_abs_value_won",
                    "verdict"])
        for r in all_results:
            w.writerow(r)

    from collections import Counter
    verdicts = Counter(r[-1] for r in all_results)
    print("verdicts:", verdicts)
    hi = [r for r in all_results if r[-1] == "high_confidence"]
    print(f"high_confidence rows: {len(hi)}, filings: {len({(r[0],r[1]) for r in hi})}, "
          f"corps: {len({r[0] for r in hi})}")
    print(f"saved: {OUT_CSV}")


if __name__ == "__main__":
    main()
