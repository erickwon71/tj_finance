"""R135(다중 라벨 셀 조인) 영향범위 표본 스캔 — SCE 한정, 2015+.

`_grid_body_rows`의 physical[0]-only 라벨 버그(원익피앤이 20161128000288 실측)가
얼마나 널리 재현되는지 재파싱 표본으로 추정한다. 전수(185K 필링)는 시간이 오래 걸려
표본(기본 3,000건 무작위)으로 먼저 규모를 가늠한다.

수정된 코드(_grid_body_rows, R135)로 재파싱해서 라벨에 ">"가 새로 들어간 SCE 행 수를
센다 — 수정 전에는 그 행들이 physical[0] 텍스트만 남았을 행들이다.

사용:
    python scripts/census_r135_multicell_label_sample_2026-09-16.py --sample 3000
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

_NAS_PREFIX = "/Users/taejin/Project/tj_finance/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"

_UNIVERSE_SQL = """
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
           c.corp_name, c.stock_code
    FROM download_tasks dt
    JOIN filings f USING (rcept_no)
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE c.is_active AND c.stock_code IS NOT NULL AND c.stock_code NOT LIKE '9%%'
      AND c.coverage_class = 'periodic'
      AND f.report_type IN ('annual','half','quarter')
      AND f.fiscal_year >= 2015
      AND f.is_final = TRUE
      AND f.report_nm NOT LIKE '%%제출기한연장%%'
      AND dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
"""


def _sd(path: str) -> str:
    return path.replace(_NAS_PREFIX, _SD_PREFIX) if path.startswith(_NAS_PREFIX) else path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--show", type=int, default=25)
    ap.add_argument("--statement", default="SCE", choices=["SCE", "note"],
                     help="어느 statement 를 셀지 — note 면 include_notes=True 로 파싱(훨씬 느림)")
    args = ap.parse_args()

    with get_session() as session:
        rows = session.execute(text(_UNIVERSE_SQL)).fetchall()
    print(f"유니버스 전체: {len(rows):,}건")
    sample = random.Random(args.seed).sample(rows, min(args.sample, len(rows)))
    print(f"표본: {len(sample):,}건")

    n_filings_parsed = n_filings_err = 0
    n_sce_rows = n_sce_rows_joined = 0
    affected_corps: Counter = Counter()
    examples = []

    for i, t in enumerate(sample):
        path = _sd(t.file_path)
        if not Path(path).exists():
            path = t.file_path
        if not Path(path).exists():
            continue
        try:
            lines = extract_report_lines(
                path, rcept_no=t.rcept_no, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                include_notes=(args.statement == "note"))
        except Exception:
            n_filings_err += 1
            continue
        n_filings_parsed += 1
        seen_rows = set()
        for l in lines:
            if l.statement != args.statement:
                continue
            key = (l.basis, l.table_seq, l.row_order, l.label_raw)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            n_sce_rows += 1
            if ">" in (l.label_raw or ""):
                n_sce_rows_joined += 1
                affected_corps[(t.corp_name, t.stock_code)] += 1
                if len(examples) < args.show:
                    examples.append((t.corp_name, t.stock_code, t.rcept_no, l.label_raw))
        if (i + 1) % 500 == 0:
            print(f"  ...{i+1}/{len(sample)} 처리, 지금까지 조인행={n_sce_rows_joined}")

    print(f"\n파싱 성공 {n_filings_parsed:,} / 오류 {n_filings_err:,}")
    print(f"{args.statement} 행 총 {n_sce_rows:,}건 중 다중라벨 조인행 {n_sce_rows_joined:,}건 "
          f"({100*n_sce_rows_joined/max(n_sce_rows,1):.3f}%)")
    print(f"영향받은 회사(표본 내): {len(affected_corps)}개사")
    print(f"\n표본 유니버스 대비 전체 추정 필링 수(비례): "
          f"{len(rows) * n_filings_err / max(len(sample),1):.0f}건 오류 예상 (참고용)")

    print(f"\n상위 영향 회사(표본 내 조인행수 많은 순):")
    for (name, code), cnt in affected_corps.most_common(20):
        print(f"  {cnt:4d}  {name}({code})")

    print(f"\n예시 조인 라벨:")
    for name, code, rcept, label in examples:
        print(f"  {name}({code}) {rcept}  {label!r}")


if __name__ == "__main__":
    main()
