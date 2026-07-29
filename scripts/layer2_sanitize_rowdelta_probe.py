"""정규화가 본문 행 수를 줄인 이유 규명 (READ-ONLY).

전량 재적재 후 report_lines 가 64,508,192 → 64,336,430 (-171,762) 으로 **줄었다**.
데이터는 늘어야 하는데 줄었으므로 원인을 확인해야 한다.

가설: 앞선 영향 측정은 셀을 (statement, basis, section_path, label_raw, col_index) **dict 키**로
집계해 **중복 행이 합쳐졌다**. 깨진 트리가 만들던 중복 행(고아 TR 재귀 등)이 정규화로
사라지면 DB 행 수는 줄지만 dict 기준으로는 변화가 안 보인다.

이 스크립트는 **원시 행 수**(dict 아님)와 중복 행 수를 정규화 전/후로 비교해 가설을 검증한다.
추측하지 않고 실제 추출기 출력을 센다.

Usage
-----
    python scripts/layer2_sanitize_rowdelta_probe.py --limit 60
"""
from __future__ import annotations

import argparse
import random
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines
from parser.xml.dart_xml_parser import sanitize_dart_xml


def rows_of(path: str, rcept: str, corp: str, fy: int, per: str):
    """추출기 원시 행. (키, 값) 리스트 — 중복을 합치지 않는다."""
    out = []
    for r in extract_report_lines(path, rcept_no=rcept, corp_code=corp,
                                  report_fiscal_year=fy, report_fiscal_period=per,
                                  include_notes=False):
        out.append(((r.statement, r.basis, r.section_path, r.label_raw,
                     r.col_index), r.value_won))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260730)
    args = ap.parse_args()

    t: Counter[str] = Counter()
    examples: list[str] = []

    with get_session() as session:
        rows = list(session.execute(text("""
            SELECT f.corp_code, f.rcept_no, d.file_path
            FROM filings f JOIN download_tasks d USING (rcept_no)
            WHERE f.fiscal_year = :y AND f.fiscal_period='FY' AND f.report_type='annual'
              AND f.is_final AND d.file_type='xml' AND d.status='completed'
              AND d.file_path IS NOT NULL
        """), {"y": args.year}).fetchall())
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing", flush=True)

        for i, f in enumerate(rows, 1):
            if i % 20 == 0:
                print(f"  … {i}/{len(rows)}", flush=True)
            raw = Path(f.file_path).read_bytes()
            # ★현재 파서는 sanitize 를 내장하므로, '정규화 전'을 보려면 원문을 그대로
            #   쓰는 임시 파일이 아니라 **역으로** sanitize 를 끈 경로가 필요하다.
            #   여기서는 sanitize 적용본을 '후', 원문을 파서에 통과시키되 sanitize 가
            #   이미 들어갔으므로 동일해진다 → 대신 '정규화가 실제로 바꾼 바이트'가 있는
            #   filing 만 골라 전/후를 비교한다(원문 그대로 파싱하는 경로는 아래 monkeypatch).
            import parser.xml.dart_xml_parser as dxp
            orig = dxp.sanitize_dart_xml
            try:
                dxp.sanitize_dart_xml = lambda b: b          # 정규화 끔
                before = rows_of(f.file_path, f.rcept_no, f.corp_code, args.year, "FY")
            finally:
                dxp.sanitize_dart_xml = orig
            after = rows_of(f.file_path, f.rcept_no, f.corp_code, args.year, "FY")

            t["비교"] += 1
            t["행 전"] += len(before)
            t["행 후"] += len(after)

            dup_b = len(before) - len(set(before))
            dup_a = len(after) - len(set(after))
            t["중복행 전"] += dup_b
            t["중복행 후"] += dup_a

            if len(after) != len(before):
                t["행수 변한 filing"] += 1
                if len(examples) < 8:
                    examples.append(
                        f"{f.corp_code} {len(before)} -> {len(after)} "
                        f"(중복 {dup_b} -> {dup_a})")

    n = max(t["비교"], 1)
    print(f"\n=== 정규화 전/후 원시 행 수 · FY{args.year} ({n} filing) ===")
    for k in ("행 전", "행 후", "중복행 전", "중복행 후", "행수 변한 filing"):
        print(f"  {k:<16} {t[k]:>9,}")
    d = t["행 후"] - t["행 전"]
    print(f"\n  행 증감 {d:+,} ({d/max(t['행 전'],1)*100:+.2f}%)")
    print(f"  중복 감소 {t['중복행 전'] - t['중복행 후']:+,}")
    if examples:
        print("\n--- 예시 ---")
        for e in examples:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
