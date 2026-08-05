"""원문 대비 **조용한 절단**을 전수 탐지하고, 재적재 대상 rcept 목록을 만든다.

배경 — 2026-08-05 에 `<?` 오해석으로 문서 뒷부분이 통째로 사라지던 것을 고쳤다
(`parser/xml/dart_xml_parser._BAD_LT`). 웅진 20190401004194 는 원문 929표 중 101표만
남아 있었는데 **오류 하나 없이** 그랬다. 그런 filing 이 또 있는지는 추측이 아니라
원문 대비 표 수로만 알 수 있다.

판정 = `원문 <TABLE 수` 대비 `파싱된 TABLE 수`.
★ 원문 카운트는 **경계를 앵커**한다(`<TABLE[\\s>]`). `b"<TABLE"` 로 세면 `<TABLE-GROUP>`
  까지 함께 세어 원문 표 수가 부풀고, 멀쩡한 문서가 절단으로 보인다(2026-08-04 에 실제로
  이 실수를 했다).

사용:
    python scripts/audit_xml_truncation.py                      # 전수 스캔(느림)
    python scripts/audit_xml_truncation.py --sample 500         # 표본
    python scripts/audit_xml_truncation.py --out targets.txt    # 재적재 목록 저장
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file

_RAW_TABLE = re.compile(rb"<TABLE[\s>]", re.I)
# 본문에 나타난 '<?' — XML 선언(첫 줄) 외에 또 있으면 PI 오해석 후보였다.
_PI = re.compile(rb"<\?")

SQL = """
SELECT f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no, d.file_path
  FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
 WHERE f.fiscal_year >= 2015
   AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
 ORDER BY md5(f.rcept_no)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="0=전수")
    ap.add_argument("--threshold", type=float, default=0.95,
                    help="파싱/원문 비율이 이 값 미만이면 절단으로 본다")
    ap.add_argument("--out", help="재적재 대상 rcept_no 목록을 쓸 파일")
    args = ap.parse_args()

    sql = SQL + (f" LIMIT {args.sample}" if args.sample else "")
    with get_session() as s:
        rows = s.execute(text(sql)).fetchall()

    checked = 0
    losses: list[tuple] = []
    pi_files = 0

    for corp_name, fy, fp, rcept, fpth in rows:
        p = Path(fpth)
        if not p.exists():
            continue
        raw = p.read_bytes()
        n_raw = len(_RAW_TABLE.findall(raw))
        if n_raw == 0:
            continue                       # PDF 등 — 대상 아님
        if len(_PI.findall(raw)) > 1:
            pi_files += 1
        root = _parse_xml_file(p)
        n_parsed = len(root.findall(".//TABLE")) if root is not None else 0
        checked += 1
        ratio = n_parsed / n_raw
        if ratio < args.threshold:
            losses.append((ratio, corp_name, fy, fp, rcept, n_raw, n_parsed))
        if checked % 2000 == 0:
            print(f"  … {checked}건 검사 · 절단 {len(losses)}건", flush=True)

    print(f"\n=== 검사 {checked}건 ===")
    print(f"  본문에 '<?' 가 또 있는 파일 : {pi_files}  (PI 오해석 후보였던 것)")
    print(f"  절단(파싱/원문 < {args.threshold}) : {len(losses)}건")
    for x in sorted(losses)[:40]:
        print(f"   {x[0]*100:5.1f}%  {x[1]:14s} {x[2]}{x[3]:3s} {x[4]}  "
              f"원문{x[5]:5d}→파싱{x[6]:5d}")

    if args.out:
        Path(args.out).write_text("\n".join(x[4] for x in losses))
        print(f"\n재적재 목록 {len(losses)}건 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
