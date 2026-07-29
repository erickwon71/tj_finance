"""계층2 주석 누락 스캔 — 원문에 있는데 전사본에 없는 '의미 있는 주석' (READ-ONLY).

왜 주석 번호로는 안 되는가
--------------------------
처음엔 'FY 의 최대 주석번호 < 분기의 최대 주석번호'를 절단 신호로 썼는데 약하다:
  · 분기보고서는 중간공시 전용 주석이 있거나 번호를 다르게 매긴다 — 보고서 간 번호가 대응되지 않는다.
  · 최대 번호는 **행을 만든 주석**만 반영한다. 단위 미선언 서술형 주석(회계정책 등)은 설계상
    제외되므로 끝부분이 서술형이면 정상인데도 낮게 나온다.
  실제로 그 방식의 '이상' 189건 중 161건이 gap 1~3 = 위 노이즈였다.

그래서 **의미 기준**으로 본다: 계층3 가 실제로 쓰는 주석(D&A 완결형 소스 등)이
원문 텍스트에는 등장하는데 note_lines 에는 없는 경우만 결함으로 센다.

방법
----
원문 XML 을 **파싱하지 않고 텍스트 검색**한다(빠르다). 주제별 키워드가 원문에 있는지 보고,
같은 rcept 의 note_lines 에 해당 topic 이 있는지 대조한다.

Usage
-----
    python scripts/layer2_note_topic_gap_scan.py --year 2024 --limit 500
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.common.note_topics import (EXPENSE_BY_NATURE, CASH_FLOW, SGA,
                                       map_topic)

# 계층3 가 D&A 완결형 소스로 쓰는 주제 — 이게 빠지면 실제 값이 틀어진다.
# (topic, 원문에서 찾을 키워드들)
_TARGETS = [
    (EXPENSE_BY_NATURE, ("비용의 성격별", "비용의성격별", "성격별 분류")),
    (CASH_FLOW,         ("현금흐름표", "영업으로부터 창출된 현금", "창출된 현금")),
    (SGA,               ("판매비와관리비", "판매비와 관리비")),
]

FILINGS_SQL = text(
    """
    SELECT f.corp_code, f.rcept_no, d.file_path
    FROM filings f
    JOIN download_tasks d USING (rcept_no)
    WHERE f.fiscal_year = :year AND f.fiscal_period = 'FY'
      AND f.report_type = 'annual' AND f.is_final
      AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
    """
)

TOPICS_SQL = text(
    """
    -- ★basis 를 고정하면 안 된다. 연결재무제표를 작성하지 않는 기업은 별도만 공시하므로
    --   consolidated 만 보면 주석이 통째로 없는 것처럼 보인다(허위 누락).
    SELECT DISTINCT section_path FROM note_lines
    WHERE rcept_no = :rcept AND statement = 'note'
    """
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=500, help="0 = 전수")
    ap.add_argument("--seed", type=int, default=20260729)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    tally: Counter[str] = Counter()
    missing_examples: list[str] = []

    with get_session() as session:
        rows = session.execute(FILINGS_SQL, {"year": args.year}).fetchall()
        rows = list(rows)
        random.Random(args.seed).shuffle(rows)
        if args.limit:
            rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing (FY{args.year})", flush=True)

        for i, f in enumerate(rows, 1):
            if i % 100 == 0:
                print(f"  … {i}/{len(rows)}", flush=True)
            p = Path(f.file_path)
            if not p.exists():
                tally["파일없음"] += 1
                continue
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                tally["읽기실패"] += 1
                continue

            have = {
                map_topic(r[0])
                for r in session.execute(TOPICS_SQL, {"rcept": f.rcept_no}).fetchall()
            }
            tally["검사"] += 1

            gaps = []
            for topic, keywords in _TARGETS:
                # ★단순 키워드 포함으로는 안 된다 — '현금흐름표'·'판매비와관리비'는 본문
                #   재무제표에도 나오는 단어라 주석에 없어도 참이 된다(허위 누락).
                #   **번호 붙은 주석 제목**('27. 현금흐름표') 형태일 때만 주석으로 본다.
                in_raw = any(
                    re.search(r"\d{1,2}\s*[.．]\s*" + re.escape(k), raw)
                    for k in keywords
                )
                if in_raw and topic not in have:
                    gaps.append(topic.replace("note.", ""))
                    tally[f"누락:{topic}"] += 1
            if gaps:
                tally["결함filing"] += 1
                if len(missing_examples) < args.show:
                    missing_examples.append(
                        f"{f.corp_code} {f.rcept_no} 누락={','.join(gaps)}")
            else:
                tally["정상"] += 1

    n = max(tally["검사"], 1)
    print(f"\n=== 원문 대비 주석 누락 · FY{args.year} (검사 {n}) ===")
    for k, v in tally.most_common():
        print(f"  {k:<34} {v:>5}")
    print(f"\n  결함 filing {tally['결함filing']}/{n} = {tally['결함filing']/n*100:.1f}%")
    if missing_examples:
        print("\n--- 예시 ---")
        for e in missing_examples:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
