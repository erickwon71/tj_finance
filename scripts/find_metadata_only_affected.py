"""R4-2 잔여 백로그 ② — 표제 인식 수정(`0b93816`) 소급 미반영분의 **정확한 rcept_no 목록**을
전량(2015+, 이미 적재된 filing) 스캔해서 뽑는다.

`measure_metadata_only_impact.py` 는 표본으로 **비율**만 쟀다(400건 0.25%, 800건 0.1%).
이 스크립트는 같은 방식(수정 전/후 monkeypatch 비교)을 **전수**에 적용해 소급 백필 대상
rcept_no 를 직접 확정한다 — 그래야 `load_report_lines.py --rcept-file` 로 좁게(전량 재파싱
~14h 대신 대상만) 백필할 수 있다.

`--shard a/n` 으로 나눠 병렬 실행(load_report_lines.py 와 같은 관례: 정렬 후 i%n).

**재개**: `--out` 옆에 `<out>.ckpt` 로 마지막까지 스캔한 인덱스를 남긴다(500건마다 갱신).
같은 `--out` 으로 다시 실행하면 그 인덱스 다음부터 이어서 스캔한다 — 대상 집합은 SQL
정렬로 고정이라 재현 가능. 중간에 죽어도(메모리 부족 등) 처음부터 다시 돌 필요 없다.

사용:
    python scripts/find_metadata_only_affected.py --shard 0/8 --out /tmp/affected_0.txt
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import table_direct_rows
import fin2.extract.statement_titles as ST
import fin2.extract.text as T
from scripts.measure_metadata_only_impact import old_is_metadata_only, snapshot

FY_MIN = 2015

SQL = """
    SELECT dt.rcept_no, dt.file_path, f.corp_name, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt
    JOIN filings f USING (rcept_no)
    JOIN report_line_load_progress p ON p.rcept_no = dt.rcept_no AND p.status = 'done'
    WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
      AND f.fiscal_year >= :fy_min
    ORDER BY dt.rcept_no
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="a/n 분할(정렬 후 i %% n == a)")
    ap.add_argument("--out", required=True, help="영향받은 rcept_no 를 append 로 기록할 파일")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(SQL), {"fy_min": FY_MIN}).fetchall()

    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        rows = [r for i, r in enumerate(rows) if i % n == a]
    if args.limit:
        rows = rows[: args.limit]

    tag = f"shard {args.shard}" if args.shard else "all"
    ckpt_path = Path(args.out + ".ckpt")
    start_i = 0
    if ckpt_path.exists():
        start_i = int(ckpt_path.read_text().strip() or 0)
        rows = rows[start_i:]
        logger.info(f"[{tag}] 체크포인트 발견 — {start_i:,}건 완료분 건너뜀")
    logger.info(f"[{tag}] 대상 {len(rows):,}건 스캔 시작")

    new_impl = ST._is_metadata_only
    out_f = open(args.out, "a")
    t0 = time.time()
    n_changed = n_docs = 0

    for i, (rcept, fpth, corp_name, fy, fp) in enumerate(rows, 1):
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        n_docs += 1

        try:
            ST._is_metadata_only = old_is_metadata_only
            before = snapshot(root)
            ST._is_metadata_only = new_impl
            after = snapshot(root)
        except Exception as exc:                      # noqa: BLE001 — 문서 하나가 전체를 죽이면 안 됨
            # 실측: 일부 원문에서 lxml getpath 가 "Element is not in this tree" (드묾, 전량
            # 스캔에서만 노출). 원인 조사는 범위 밖 — 이 스캔의 목적은 회수 대상 확정이지
            # 개별 파싱 결함 규명이 아니다. 건너뛰고 계속.
            logger.warning(f"  [{tag}] {rcept} 스냅샷 실패(건너뜀): {type(exc).__name__}: {exc}")
            continue
        finally:
            ST._is_metadata_only = new_impl

        added = {k: v for k, v in after.items() if k not in before}
        removed = {k: v for k, v in before.items() if k not in after}
        if added or removed:
            n_changed += 1
            add_rows = sum(v[1] for v in added.values())
            rm_rows = sum(v[1] for v in removed.values())
            out_f.write(f"{rcept}\t{corp_name}\t{fy}{fp}\t+{len(added)}/-{len(removed)} tables"
                        f"\t+{add_rows}/-{rm_rows} rows\n")
            out_f.flush()

        if i % 500 == 0:
            el = time.time() - t0
            rate = i / el
            eta = (len(rows) - i) / rate / 3600
            logger.info(f"  [{tag}] {i:,}/{len(rows):,} ({100*i/len(rows):.1f}%) · "
                        f"{rate:.1f}건/s · ETA {eta:.2f}h · 변경 {n_changed}")
            ckpt_path.write_text(str(start_i + i))

    out_f.close()
    ckpt_path.write_text(str(start_i + len(rows)))  # 완주 표시(재실행 시 0건으로 즉시 종료)
    el = time.time() - t0
    logger.success(f"[{tag}] 완료 {el/3600:.2f}h — 스캔 {n_docs:,} · 변경(영향받음) {n_changed:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
