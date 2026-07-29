"""계층2 적재 충실성 — 원문 왕복 검증 (READ-ONLY).

왜 이게 최우선인가
------------------
report_lines / note_lines 가 **유일한 DB 소스**다. 여기가 원문과 다르면 계층3·4 검증은
전부 무의미하다. 지금까지의 확인은 "정규화가 무엇을 바꿨나"였지 "적재된 것이 원문과
같은가"가 아니었다.

두 방향을 따로 본다 (같은 것이 아니다):
  ① 역방향(fabrication) — **DB 값이 원문에 실재하는가**.
     여기서 불일치가 나오면 우리가 없는 값을 만들어낸 것이라 가장 심각하다. 0 이어야 한다.
  ② 정방향(completeness) — 원문의 금액 셀이 DB 에 있는가.
     설계상 제외(단위 미선언·데이터행 없음)가 많아 100% 가 목표가 아니다. 별도 감사 대상.

이 스크립트는 ①을 검사한다.

방법
----
value_won 은 표시금액 × 단위배수다. 배수를 되돌려 표시금액 문자열을 만들고, 그 문자열이
원문 텍스트에 실재하는지 본다. 배수를 모르는 경우를 대비해 1/천/백만/억을 모두 시도한다.
부호는 원문에서 괄호(음수)로 쓰이므로 절대값으로 대조한다.

Usage
-----
    python scripts/layer2_fidelity_roundtrip.py --limit 30
    python scripts/layer2_fidelity_roundtrip.py --rcept 20250327001024
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import sanitize_dart_xml

_MULTS = (1, 1_000, 1_000_000, 100_000_000)

ROWS_SQL = text(
    """
    SELECT statement, basis, section_path, label_raw, col_index, value_won
    FROM {tbl}
    WHERE rcept_no = :r AND value_won IS NOT NULL AND value_won <> 0
    """
)

PATH_SQL = text(
    "SELECT d.file_path FROM download_tasks d WHERE d.rcept_no = :r "
    "AND d.file_type='xml' LIMIT 1"
)


def source_numbers(path: str) -> set[str]:
    """원문 표의 모든 숫자 셀을 콤마 제거·절대값 문자열로."""
    raw = sanitize_dart_xml(Path(path).read_bytes())
    root = etree.fromstring(raw, etree.XMLParser(recover=True))
    out: set[str] = set()
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.upper() not in ("TD", "TE", "TH", "TU"):
            continue
        s = "".join(el.itertext()).strip()
        if not s:
            continue
        s = s.replace(",", "").replace(" ", "").replace(" ", "")
        s = s.strip("()△▲-−+원%")
        if s and re.fullmatch(r"\d+(?:\.\d+)?", s):
            out.add(s)
            # ★소수 표기를 정수부로도 등록한다. 원문은 '(208.00)' '49.00' 처럼 쓰는데
            #   DB 는 정수(-208, 49000)로 담기므로 정수부가 없으면 허위 불일치가 난다.
            #   (초판이 '.0' 만 처리해 39건 허위 불일치가 났다)
            if "." in s:
                out.add(s.split(".")[0])
                out.add(s.rstrip("0").rstrip("."))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--rcept", nargs="*", help="특정 rcept 만")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--show", type=int, default=8)
    args = ap.parse_args()

    t: Counter[str] = Counter()
    misses: list[str] = []

    with get_session() as session:
        if args.rcept:
            targets = [(r, session.execute(PATH_SQL, {"r": r}).scalar())
                       for r in args.rcept]
        else:
            rows = list(session.execute(text("""
                SELECT f.rcept_no, d.file_path
                FROM filings f JOIN download_tasks d USING (rcept_no)
                WHERE f.fiscal_year = :y AND f.fiscal_period='FY'
                  AND f.report_type='annual' AND f.is_final
                  AND d.file_type='xml' AND d.status='completed'
                  AND d.file_path IS NOT NULL
            """), {"y": args.year}).fetchall())
            random.Random(args.seed).shuffle(rows)
            targets = [(r.rcept_no, r.file_path) for r in rows[: args.limit]]

        print(f"대상 {len(targets)} filing", flush=True)
        for i, (rcept, path) in enumerate(targets, 1):
            if not path or not Path(path).exists():
                t["파일없음"] += 1
                continue
            if i % 10 == 0:
                print(f"  … {i}/{len(targets)}", flush=True)
            src = source_numbers(path)
            t["filing"] += 1

            for tbl in ("report_lines", "note_lines"):
                db = session.execute(
                    text(str(ROWS_SQL).format(tbl=tbl)), {"r": rcept}
                ).fetchall()
                for r in db:
                    t[f"{tbl}:검사"] += 1
                    v = abs(r.value_won)
                    hit = any(
                        (v % m == 0) and str(v // m) in src for m in _MULTS
                    )
                    if hit:
                        t[f"{tbl}:일치"] += 1
                    else:
                        t[f"{tbl}:원문에 없음"] += 1
                        if len(misses) < args.show:
                            misses.append(
                                f"{tbl} {rcept} <{str(r.section_path)[:28]}> "
                                f"{str(r.label_raw)[:22]} c{r.col_index} = {r.value_won:,}")

    print(f"\n=== 역방향 충실성(DB→원문) · FY{args.year} ===")
    for tbl in ("report_lines", "note_lines"):
        n = t[f"{tbl}:검사"]
        if not n:
            continue
        ok = t[f"{tbl}:일치"]
        print(f"  {tbl:<14} 검사 {n:>9,} · 일치 {ok:>9,} ({ok/n*100:6.3f}%) · "
              f"원문에 없음 {t[f'{tbl}:원문에 없음']:,}")
    if misses:
        print("\n--- 원문에서 못 찾은 값(★조사 대상) ---")
        for m in misses:
            print(f"  {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
