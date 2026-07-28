"""계층3 ②주제 정규화 검증 — note_topics 카탈로그의 실제 커버리지 (READ-ONLY).

`parser/common/note_topics.map_topic` 이 실제 주석 제목을 얼마나 잡아내는지 측정한다.
카탈로그는 롱테일 전체를 덮을 필요가 없다(2,239 topic 중 1,707 이 1개 corp 전용) —
**계층3 가 실제로 쓰는 주석**을 안정적으로 지목하면 된다. 그래서 두 가지를 본다:

  1. topic 별 corp 커버리지 — D&A 등 소스가 충분히 잡히는가
  2. **미분류 상위 제목** — 카탈로그에 넣어야 할 누락이 있는가 (가장 중요한 출력)

행 기준 커버리지도 함께 낸다. 제목 종류는 롱테일이 길어도 실제 데이터의 대부분은
소수 topic 에 몰리기 때문.

Usage
-----
    python scripts/layer3_note_topic_validate.py --corps 300
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.common.note_topics import GENERIC, map_topic, normalize_title

SECTIONS_SQL = text(
    """
    SELECT section_path, count(*) AS n
    FROM note_lines
    WHERE corp_code = :corp
      AND report_fiscal_year = :year
      AND report_fiscal_period = 'FY'
      AND statement = 'note'
    GROUP BY section_path
    """
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=300)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--top-unmapped", type=int, default=25)
    args = ap.parse_args()

    topic_corps: dict[str, set[str]] = defaultdict(set)
    topic_rows: Counter[str] = Counter()
    unmapped_corps: dict[str, set[str]] = defaultdict(set)
    unmapped_rows: Counter[str] = Counter()
    rows_total = 0
    scanned = 0

    with get_session() as session:
        corps = [
            r[0] for r in session.execute(
                text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
            ).fetchall()
        ]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        for corp in corps:
            rows = session.execute(
                SECTIONS_SQL, {"corp": corp, "year": args.year}
            ).fetchall()
            if not rows:
                continue
            scanned += 1
            for r in rows:
                rows_total += r.n
                topic = map_topic(r.section_path)
                if topic is None:
                    key = normalize_title(r.section_path)[:50]
                    unmapped_corps[key].add(corp)
                    unmapped_rows[key] += r.n
                else:
                    topic_corps[topic].add(corp)
                    topic_rows[topic] += r.n

    n = max(scanned, 1)
    mapped_rows = sum(v for k, v in topic_rows.items() if k != GENERIC)
    generic_rows = topic_rows.get(GENERIC, 0)
    unmapped_total = sum(unmapped_rows.values())

    print(f"=== note_topics 커버리지 · FY{args.year} · corp {scanned}개 ===")
    print(f"주석 행 {rows_total:,}")
    print(f"  topic 매핑    {mapped_rows:,} ({mapped_rows / max(rows_total,1) * 100:5.1f}%)")
    print(f"  GENERIC(문서수준) {generic_rows:,} ({generic_rows / max(rows_total,1) * 100:5.1f}%)")
    print(f"  미분류        {unmapped_total:,} ({unmapped_total / max(rows_total,1) * 100:5.1f}%)")

    print(f"\n=== topic 별 corp 커버리지 ===")
    for topic, corps_set in sorted(topic_corps.items(), key=lambda kv: -len(kv[1])):
        if topic == GENERIC:
            continue
        print(f"  {len(corps_set):>4} ({len(corps_set) / n * 100:5.1f}%)  {topic:<28} "
              f"행 {topic_rows[topic]:>9,}")

    print(f"\n=== 미분류 상위 {args.top_unmapped} (카탈로그 누락 후보) ===")
    ranked = sorted(unmapped_corps.items(), key=lambda kv: -len(kv[1]))
    for title, corps_set in ranked[: args.top_unmapped]:
        print(f"  {len(corps_set):>4} ({len(corps_set) / n * 100:5.1f}%)  {title[:52]:<52} "
              f"행 {unmapped_rows[title]:>8,}")

    print(f"\n미분류 고유 제목 {len(unmapped_corps):,} · "
          f"그중 1개 corp 전용 {sum(1 for _, c in ranked if len(c) == 1):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
