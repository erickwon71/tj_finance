"""F1 수용 검증 — 열별 단위 판정이 **무엇을 채우고 무엇을 비우는지** 표본으로 본다 (READ-ONLY).

`verify_f1_columns.py` 가 한 filing 을 눈으로 보는 도구라면, 이쪽은 같은 판정을 표본 규모로
집계해 **두 방향의 거짓양성**을 찾는 도구다:

  · 채웠는데 비금액이면      → **오염**(가장 나쁘다). `col_money`·`declared` 의 열 헤더를 본다
  · 비웠는데 금액이면        → 유실(원문은 value_raw 에 남아 회수 가능). `non_monetary`·
                              `undetermined` 의 열 헤더를 본다

실제로 이 도구의 눈으로 두 건을 잡았다(둘 다 units.py 에 기록):
  · '계약금액($)' — USD 금액인데 '금액' 표지에 걸려 ×1,000
  · '10%상승'     — 천원 금액 열인데 '%' 표지에 걸려 NULL

Usage
-----
    python scripts/audit_f1_column_sources.py --limit 80
    python scripts/audit_f1_column_sources.py --limit 80 --top 40
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    ORDER BY f.rcept_no
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    with get_session() as s:
        rows = list(s.execute(text(TARGETS_SQL)).fetchall())
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    src = Counter()
    by_src_label: dict[str, Counter] = defaultdict(Counter)
    stats = Counter()
    t0 = time.time()
    for i, f in enumerate(rows, 1):
        if i % 20 == 0:
            print(f"  … {i}/{len(rows)} ({(time.time()-t0)/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            stats["파일없음"] += 1
            continue
        try:
            lines = [l for l in extract_report_lines(
                p, rcept_no=f.rcept_no, corp_code=f.corp_code,
                report_fiscal_year=f.fiscal_year, report_fiscal_period=f.fiscal_period,
                include_notes=True) if l.statement == "note"]
        except Exception as e:  # noqa: BLE001
            stats["추출실패"] += 1
            if stats["추출실패"] <= 3:
                print(f"  ! {f.rcept_no}: {type(e).__name__}: {e}")
            continue
        stats["filing"] += 1
        stats["note행"] += len(lines)
        for l in lines:
            src[l.unit_source] += 1
            if l.header_hint:                       # F2: 종전에는 통째로 삭제되던 행
                stats["header_hint행"] += 1
                by_src_label[f"hint:{l.header_hint}"][(l.label_raw or "")[:30]] += 1
            by_src_label[l.unit_source][(l.col_label or "(헤더없음)")[:44]] += 1
            if l.value_won is None and not l.value_raw:
                stats["★값도원문도없음"] += 1
            if l.value_won is not None and l.value_raw:
                stats["★값과원문중복"] += 1
            if l.value_won is not None:
                stats["채움"] += 1

    n = max(stats["filing"], 1)
    print(f"\n=== F1 열별 판정 (filing {n}, note 행 {stats['note행']:,}, "
          f"{(time.time()-t0)/n:.2f}s/filing) ===")
    print(f"  채움 {stats['채움']:,} / 원문만 {stats['note행']-stats['채움']:,}")
    print(f"  header_hint 행(F2 로 회복): {stats['header_hint행']:,} "
          f"({100*stats['header_hint행']/max(stats['note행'],1):.2f}%)")
    print(f"  ★값도 원문도 없음: {stats['★값도원문도없음']:,} (0 이어야)   "
          f"★값·원문 중복: {stats['★값과원문중복']:,} (0 이어야)")
    print(f"\n{'unit_source':<14}{'행':>12}{'비율':>8}")
    for k, v in src.most_common():
        print(f"{str(k):<14}{v:>12,}{100*v/max(stats['note행'],1):>7.1f}%")

    for key, why in (("declared", "표 선언 배수 적용 — 비금액 열이 섞였는지 본다(오염 방향)"),
                     ("col_money", "혼합 선언에서 금액이라 판정 — 가장 위험한 판정(오염 방향)"),
                     ("non_monetary", "비금액이라 비움 — 실제로 금액인 열이 섞였는지(유실 방향)"),
                     ("undetermined", "확정 실패 — 무엇을 놓치고 있는지"),
                     ("undeclared", "선언 자체가 없는 표"),
                     ("hint:기간라벨", "★F2 로 살아난 '기간라벨' 행 — 행이 기간축인 표의 실데이터"),
                     ("hint:날짜", "★F2 로 살아난 '날짜' 행"),
                     ("hint:기수", "★F2 로 살아난 '기수' 행")):
        if not by_src_label.get(key):
            continue
        print(f"\n--- {key} 상위 열 헤더 ({why}) ---")
        for lbl, c in by_src_label[key].most_common(args.top):
            print(f"  {c:>8,}  {lbl}")

    for k in ("파일없음", "추출실패"):
        if stats[k]:
            print(f"  {k}: {stats[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
