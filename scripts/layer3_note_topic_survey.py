"""계층3 ②주제 정규화 — 주석 제목 분포 조사 (READ-ONLY).

배경
----
①주석 분절은 끝났다(2026-07-28 백필: COLLAPSED 57.5%→0%, `section_path` 가
'30. 비용의 성격별 분류' 같은 실제 주석 제목을 담는다). 다음 단계는 그 제목을
**canonical topic** 으로 정규화하는 것 — 계층3 의 모든 주석 파생 항목(D&A·R&D·리스·부문)이
"어느 주석을 볼 것인가"를 이 topic 으로 지목하게 된다.

카탈로그를 감으로 만들면 변종을 놓친다. 실제로 이미 확인된 것만 해도
`판매비와관리비`(30.0%) 와 `판매비와 관리비`(13.3%) 가 띄어쓰기만 다른 같은 주석이다.
그래서 먼저 **원문 제목 분포를 전수 조사**해 정규화 규칙과 canonical 목록을 근거 위에 세운다.

출력
----
1. 정규화 후 제목별 corp 커버리지 순위 (canonical 후보)
2. 같은 정규형으로 합쳐진 **원문 변종** — 정규화 규칙이 실제로 무엇을 흡수했는지
3. 저빈도 롱테일 규모 — 카탈로그로 다룰지, 미분류로 남길지 판단용

Writes nothing to the DB.

Usage
-----
    python scripts/layer3_note_topic_survey.py --corps 300
    python scripts/layer3_note_topic_survey.py --corps 300 --show-variants 25
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

SECTIONS_SQL = text(
    """
    SELECT DISTINCT basis, section_path
    FROM note_lines
    WHERE corp_code = :corp
      AND report_fiscal_year = :year
      AND report_fiscal_period = 'FY'
      AND statement = 'note'
    """
)

# 주석 번호 접두 '30.' / '30．'
_NUM_PREFIX = re.compile(r"^\s*\d{1,2}\s*[.．]\s*")
# 말미 기준 표기 '(연결)' '(별도)' ' - 연결'
_BASIS_TAIL = re.compile(r"(\s*[-–]\s*(연결|별도)\s*$)|([(（]\s*(연결|별도)\s*[)）]\s*$)")
# 괄호 주석 '(주1)' 등 말미 부기
_PAREN_TAIL = re.compile(r"\s*[(（][^)）]{0,20}[)）]\s*$")


def normalize_topic(section_path: str) -> str:
    """주석 제목 → canonical 후보 문자열.

    적용 규칙(각각 실측 변종에 대응):
      · 번호 접두 제거      '30. 비용의 성격별 분류' → '비용의 성격별 분류'
      · 기준 표기 제거      '유형자산 (연결)' / '유형자산 - 연결' → '유형자산'
      · 공백 전부 제거      '판매비와 관리비' → '판매비와관리비'  ★실측 변종
      · 중점/구분자 통일    'ㆍ·，' → ','
    """
    s = (section_path or "").strip()
    s = _NUM_PREFIX.sub("", s)
    s = _BASIS_TAIL.sub("", s)
    s = _PAREN_TAIL.sub("", s)
    s = s.replace("ㆍ", ",").replace("·", ",").replace("，", ",")
    s = re.sub(r"\s+", "", s)          # 띄어쓰기 변종 흡수
    return s.strip(" .,-—")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=300)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--top", type=int, default=45, help="상위 몇 개 topic 을 볼지")
    ap.add_argument("--show-variants", type=int, default=15,
                    help="원문 변종이 여러 개인 topic 을 몇 개 보여줄지")
    args = ap.parse_args()

    topic_corps: dict[str, set[str]] = defaultdict(set)
    variants: dict[str, Counter] = defaultdict(Counter)
    raw_total = 0

    with get_session() as session:
        corps = [
            r[0] for r in session.execute(
                text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
            ).fetchall()
        ]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        scanned = 0
        for corp in corps:
            rows = session.execute(
                SECTIONS_SQL, {"corp": corp, "year": args.year}
            ).fetchall()
            if not rows:
                continue
            scanned += 1
            for r in rows:
                raw = (r.section_path or "").strip()
                if not raw:
                    continue
                raw_total += 1
                topic = normalize_topic(raw)
                if not topic:
                    continue
                topic_corps[topic].add(corp)
                variants[topic][raw] += 1

    n = max(scanned, 1)
    print(f"=== 주석 topic 분포 · FY{args.year} · corp {scanned}개(주석 보유) ===")
    print(f"원문 제목 인스턴스 {raw_total:,} → 정규화 후 고유 topic {len(topic_corps):,}\n")

    ranked = sorted(topic_corps.items(), key=lambda kv: -len(kv[1]))
    print(f"{'corp커버리지':>12}  topic")
    for topic, corps_set in ranked[: args.top]:
        pct = len(corps_set) / n * 100
        print(f"  {len(corps_set):>4} ({pct:5.1f}%)  {topic[:60]}")

    # 롱테일 규모 — 카탈로그 대상 범위 판단용
    tail_1 = sum(1 for _, c in ranked if len(c) == 1)
    tail_5 = sum(1 for _, c in ranked if len(c) <= 5)
    covered_top = sum(len(c) for _, c in ranked[: args.top])
    covered_all = sum(len(c) for _, c in ranked)
    print(f"\n롱테일: 1개 corp 에서만 = {tail_1:,} topic · 5개 이하 = {tail_5:,} topic")
    print(f"상위 {args.top}개가 전체 (topic,corp) 출현의 "
          f"{covered_top / max(covered_all,1) * 100:.1f}% 를 커버")

    print(f"\n=== 정규화가 흡수한 원문 변종 (상위 {args.show_variants}) ===")
    multi = [(t, v) for t, v in variants.items() if len(v) > 1]
    multi.sort(key=lambda kv: -len(topic_corps[kv[0]]))
    for topic, vc in multi[: args.show_variants]:
        forms = " | ".join(f"{f}" for f, _ in vc.most_common(4))
        print(f"  {topic[:34]:<34} ← {len(vc)}종: {forms[:100]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
