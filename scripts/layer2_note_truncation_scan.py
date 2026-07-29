"""계층2 주석 '절단' 스캔 — 전사가 중간에 멈춘 filing (READ-ONLY).

배경 — 앞선 측정들이 왜 실패했나
--------------------------------
이 결함을 재려고 네 가지를 시도했고 **전부 내 측정 쪽 거짓양성**이었다:
  ① FY vs 분기 최대 주석번호 비교      → 보고서 간 번호가 대응 안 되고, 서술형 주석은 애초에 제외됨
  ② 원문 키워드 포함 여부              → '현금흐름표'는 본문 재무제표에도 나옴
  ③ basis='consolidated' 고정          → 연결 미작성 기업은 별도만 있어 전부 누락처럼 보임
  ④ 번호 붙은 제목으로 좁힘            → '4. 현금흐름표'가 **본문 재무제표 섹션** 제목이라 여전히 오검출
그 결과 38.8% → 27.2% → 9.4% 로 계속 내려왔다.

확실한 것: **완전 붕괴(섹션 1개)** 는 SQL 로 정확히 셀 수 있고 FY2024 기준 0.3%(5건)다.
남은 것은 성일하이텍형 **절단** — 섹션은 여러 개인데 중간에서 멈춘 경우.

이 스캔의 신호
--------------
전사된 주석 번호의 최대값 `db_max` 를 구하고, 원문에서 **db_max 보다 큰 번호의 주석 제목**이
있는지 본다. 본문 재무제표 섹션 제목은 번호가 작아(1~9) db_max(보통 20+) 보다 크지 않으므로
자연히 걸러진다. 이게 앞선 방식들의 오검출 원인을 구조적으로 피한다.

Usage
-----
    python scripts/layer2_note_truncation_scan.py --year 2024 --limit 300
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

FILINGS_SQL = text(
    """
    SELECT f.corp_code, f.rcept_no, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE f.fiscal_year = :year AND f.fiscal_period = 'FY'
      AND f.report_type = 'annual' AND f.is_final
      AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
    """
)

DBMAX_SQL = text(
    """
    SELECT max((regexp_match(section_path, '^\\s*(\\d{1,2})\\s*[.．]'))[1]::int) AS db_max,
           count(DISTINCT section_path) AS secs
    FROM note_lines
    WHERE rcept_no = :rcept AND statement = 'note'
      AND section_path ~ '^\\s*\\d{1,2}\\s*[.．]'
    """
)

# 원문의 '번호. 한글제목' — 주석 제목 형태.
_HEAD_RE = re.compile(r"(\d{1,2})\s*[.．]\s*([가-힣][가-힣 ,·()]{2,24})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=300, help="0 = 전수")
    ap.add_argument("--seed", type=int, default=20260729)
    ap.add_argument("--min-gap", type=int, default=3,
                    help="db_max 보다 이만큼 이상 큰 번호가 원문에 있으면 절단으로 본다")
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    tally: Counter[str] = Counter()
    cases: list[tuple[int, str]] = []

    with get_session() as session:
        rows = list(session.execute(FILINGS_SQL, {"year": args.year}).fetchall())
        random.Random(args.seed).shuffle(rows)
        if args.limit:
            rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing (FY{args.year})", flush=True)

        for i, f in enumerate(rows, 1):
            if i % 100 == 0:
                print(f"  … {i}/{len(rows)}", flush=True)
            r = session.execute(DBMAX_SQL, {"rcept": f.rcept_no}).fetchone()
            db_max, secs = (r.db_max, r.secs) if r else (None, 0)
            if not db_max:
                tally["번호주석없음"] += 1
                continue
            if secs <= 1:
                tally["완전붕괴"] += 1
                continue
            p = Path(f.file_path)
            if not p.exists():
                tally["파일없음"] += 1
                continue
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                tally["읽기실패"] += 1
                continue

            tally["검사"] += 1
            beyond = sorted({
                int(m.group(1)) for m in _HEAD_RE.finditer(raw)
                if int(m.group(1)) > db_max
            })
            if beyond and max(beyond) - db_max >= args.min_gap:
                tally["절단의심"] += 1
                cases.append((max(beyond) - db_max,
                              f"{f.corp_code} {f.rcept_no} db_max={db_max} "
                              f"원문최대={max(beyond)} 초과번호={beyond[:8]}"))
            else:
                tally["정상"] += 1

    n = max(tally["검사"], 1)
    print(f"\n=== 주석 절단 스캔 · FY{args.year} (검사 {n}) ===")
    for k, v in tally.most_common():
        print(f"  {k:<16} {v:>5}")
    print(f"\n  절단의심 {tally['절단의심']}/{n} = {tally['절단의심']/n*100:.1f}%")
    cases.sort(reverse=True)
    print("\n--- 큰 것부터 ---")
    for _g, c in cases[: args.show]:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
