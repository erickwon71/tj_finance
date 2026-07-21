"""IS 섹션의 '2표식(손익계산서 + 포괄손익계산서 분리)' 처리 실태 측정.

배경: `parser/xml/section_detector.py:32` 는 `("IS_C", ["연결","손익계산서"])` 하나로
**포괄손익계산서와 손익계산서를 같은 섹션 코드로 묶는다**('포괄손익계산서' ⊃ '손익계산서').
K-IFRS 는 두 가지 표시를 모두 허용한다:
  · 1표식(single statement) — 포괄손익계산서 하나에 당기순이익 + OCI 가 이어짐
  · 2표식(two statement)   — 손익계산서(…당기순이익) / 포괄손익계산서(당기순이익 + OCI) 별도 표
2표식이면 한 섹션에 표가 2개 들어오고, report_lines 는 표 구분자가 없어서:
  (a) row_order 가 표마다 0부터 다시 시작 → 섹션 내 문서순서 복원 불가(정렬 시 뒤섞임)
  (b) 당기순이익 등 동일 라벨이 두 표에 중복 등장 → 계층3 이 어느 쪽인지 구분 불가
  (c) _assign_section_paths 가 표별로 독립 실행 → 두 표의 root 가 같은 이름공간에서 충돌
을 측정으로 확인/정량화한다.

사용:
    python scripts/measure_is_two_statement.py --sample 400
    python scripts/measure_is_two_statement.py --sample 400 --show 15
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
from measure_subtotal_position import _walk_report  # noqa: E402  (같은 디렉터리)

# 2표식이면 두 표에 걸쳐 반드시 중복되는 연결고리 라벨(포괄손익계산서의 첫 줄).
_BRIDGE = ("당기순이익", "당기순손실", "분기순이익", "반기순이익", "당기순손익")


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").replace("　", "")


def _is_bridge(label: str) -> bool:
    n = _norm(label)
    return any(n.startswith(b) or n.endswith(b) for b in _BRIDGE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    sql = """SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
             FROM download_tasks dt JOIN filings f USING(rcept_no)
             WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
               AND f.fiscal_period='FY' AND f.report_nm NOT LIKE '%정정%'"""
    with get_session() as session:
        rows = session.execute(text(sql)).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)

    n_reports = 0
    tables_per_is = Counter()      # IS 섹션당 표 개수 분포
    n_multi = 0                    # 표 2개 이상인 IS 섹션 수
    n_bridge_dup = 0               # 두 표 이상에 bridge 라벨이 중복 등장한 섹션
    n_roworder_collide = 0         # row_order 가 표 간 겹치는 섹션
    examples = []

    for r in rows:
        if not Path(r.file_path).exists():
            continue
        try:
            walk = list(_walk_report(r.file_path, r.fiscal_year, r.fiscal_period))
        except Exception:
            continue
        if not walk:
            continue
        n_reports += 1
        # _walk_report 는 (statement, rows, ...) 를 표 단위로 방출 → statement 별로 모은다.
        per_stmt: dict[str, list] = {}
        for section_code, trows, paths, positions, verdict in walk:
            per_stmt.setdefault(section_code, []).append(trows)

        # ★ section_code 단위(IS_C / IS_S 각각) — statement 로 뭉개면 연결+별도가 '표 2개'로
        #   보여 2표식과 구분되지 않는다. basis 컬럼이 이미 연결/별도를 구분하므로 무해한 경우.
        for stmt, tables in per_stmt.items():
            if not stmt.startswith("IS"):
                continue
            tables_per_is[len(tables)] += 1
            if len(tables) < 2:
                continue
            n_multi += 1
            bridge_tables = sum(1 for t in tables if any(_is_bridge(x.account_name) for x in t))
            orders = [{x.row_order for x in t} for t in tables]
            collide = any(orders[i] & orders[j]
                          for i in range(len(orders)) for j in range(i + 1, len(orders)))
            if bridge_tables >= 2:
                n_bridge_dup += 1
            if collide:
                n_roworder_collide += 1
            if bridge_tables >= 2 and len(examples) < args.show:
                examples.append((r, [len(t) for t in tables], bridge_tables, collide))

    print(f"\n=== IS 2표식(손익계산서/포괄손익계산서 분리) 실태 ===")
    print(f"보고서 {n_reports}건\n")
    print("[1] IS 섹션당 표 개수 분포")
    for k in sorted(tables_per_is):
        print(f"    표 {k}개: {tables_per_is[k]:6,} 섹션")
    print(f"\n[2] 표 2개 이상인 IS 섹션            {n_multi:,}")
    print(f"[3] 그중 bridge 라벨(당기순이익류)이 2표 이상에 중복  {n_bridge_dup:,}"
          f"   ← 계층3 이 구분 불가한 중복")
    print(f"[4] 그중 row_order 가 표 간 충돌       {n_roworder_collide:,}"
          f"   ← 섹션 내 문서순서 복원 불가")

    if examples:
        print(f"\n[5] 사례 (bridge 중복) 상위 {len(examples)}")
        for r, sizes, bt, collide in examples:
            print(f"    {r.corp_code} r{r.rcept_no} {r.fiscal_year}{r.fiscal_period} "
                  f"표크기={sizes} bridge표={bt} row_order충돌={collide}")


if __name__ == "__main__":
    main()
