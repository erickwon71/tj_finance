"""전수스캔(읽기전용) — `_split_label_amounts()`의 주석번호 가드가 본문(BS/IS/CF/SCE) 표에서
콤마 없는 1~3자리 당기 첫 컬럼 값을 "주석번호"로 오인해 드롭하는 케이스의 DB 전체 규모를
파악한다.

배경: docs/qa/gate_b_revenue_bugB_note_ref_guard_root_cause_2026-08-14.md — 한진중공업홀딩스
사례에서 확정된 근본원인의 파급범위 확인(사용자 결정 2026-08-14, "전수스캔 먼저"). 검증
스캔에서 필링 1건에 후보 97건이 나와(예상보다 훨씬 큼) **원본 행 전체를 CSV로 뽑는 대신
집계 통계 + 소표본만 남기도록** 설계를 바꿨다(사용자 결정, 같은 날 재확인).

DB 쓰기 없음, 소스 코드 수정 없음. 실제 `_split_label_amounts()`가 쓰는 정규식
(`_NOTE_REF_PATTERN`/`_AMOUNT_GROUPED_PATTERN`/`_NUMBER_PATTERN`)을 그대로 import해서
같은 판정을 재현한다(재구현 시 원본과 갈릴 위험 회피).

**주의**: 여기서 세는 건 "가드가 발동하는 모든 행"이다 — 그중 일부는 진짜 주석번호(가드의
원래 설계 의도대로 정상 스킵)일 수 있다. 최종 진위 판정은 소표본 원문 대조로 한다.

사용법(샤딩, gateb_audit 병렬 스캔과 동일 패턴):
    python scripts/scan_note_ref_guard_dropped_amounts_2026-08-14.py --shard 0 --n-shards 5 \
        --out-prefix scratchpad/note_ref_scan
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session, init_db
from fin2.extract.report_lines import (
    _detect_body_statement_tables,
    _detect_fin_type,
    _detect_pre2015_body_statement_tables_merged,
    _PRE2015_ROUTING_MAX_FY,
)
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import table_direct_rows
from parser.xml.table_extractor import (
    _get_cells,
    _NOTE_REF_PATTERN,
    _AMOUNT_GROUPED_PATTERN,
    _NUMBER_PATTERN,
)
from parser.common.amount_normalizer import _TRAIL_DECOR_RE

SAMPLE_CAP = 1000  # 샤드당 예시 행 상한(원문 대조용, 전수 아님)


def find_dropped_cells(table) -> list[tuple[str, str, list[str]]]:
    """한 표의 각 행에서 `_split_label_amounts()`의 주석번호 가드가 발동할 셀을 찾는다.

    `_split_label_amounts()`와 **완전히 같은 순서·조건**으로 순회하되, `continue` 하는 대신
    (라벨, 드롭된 셀 텍스트, 전체 cells) 를 기록한다.
    """
    hits = []
    for tr in table_direct_rows(table):
        cells = _get_cells(tr)
        if not cells:
            continue
        label = cells[0]
        amount_cells: list[str] = []
        for i, cell in enumerate(cells):
            if i == 0:
                continue
            cell_nospace = cell.replace(' ', '')
            cell_nospace = _TRAIL_DECOR_RE.sub('', cell_nospace)
            cell_stripped = cell_nospace.replace(',', '')
            if (not amount_cells
                    and _NOTE_REF_PATTERN.match(cell_nospace)
                    and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
                hits.append((label, cell, list(cells)))
                continue
            if _NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
                amount_cells.append(cell)
    return hits


def scan_file(file_path: str, fiscal_year: int | None = None) -> list[dict]:
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []
    fin_type = _detect_fin_type(root)
    try:
        # extract_report_lines() 와 동일한 라우팅(fiscal_year<=2010 은 pre-2015 병합 탐지기).
        if fiscal_year is not None and fiscal_year <= _PRE2015_ROUTING_MAX_FY:
            groups = _detect_pre2015_body_statement_tables_merged(root, fin_type)
        else:
            groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    except Exception as e:
        logger.debug(f"[scan] 표 탐지 실패 {file_path}: {e}")
        return []

    out = []
    for code, tables_with_unit in groups.items():
        for table, unit, _ in tables_with_unit:
            for label, dropped, cells in find_dropped_cells(table):
                out.append({
                    "section_code": code,
                    "label": label,
                    "dropped_cell": dropped,
                    "cells": " | ".join(cells),
                })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--limit", type=int, default=None, help="디버그용 상한(선택)")
    args = ap.parse_args()

    init_db()
    with get_session() as s:
        rows = s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, f.corp_code, f.corp_name,
                   f.fiscal_year, f.fiscal_period, f.report_type
            FROM download_tasks dt
            JOIN filings f ON f.rcept_no = dt.rcept_no
            WHERE dt.file_type='xml' AND dt.status='completed'
            ORDER BY dt.rcept_no
        """)).fetchall()

    shard_rows = [r for i, r in enumerate(rows) if i % args.n_shards == args.shard]
    if args.limit:
        shard_rows = shard_rows[:args.limit]
    logger.info(f"샤드 {args.shard}/{args.n_shards}: 대상 {len(shard_rows)}건")

    # 집계 카운터
    n_files_scanned = 0
    n_files_with_hit = 0
    n_hits_total = 0
    by_year = Counter()
    by_section = Counter()
    by_report_type = Counter()
    corps_affected: set[str] = set()
    rcepts_affected: set[str] = set()

    sample_path = Path(f"{args.out_prefix}_sample_shard{args.shard}.csv")
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_f = open(sample_path, "w", newline="", encoding="utf-8")
    sample_writer = csv.writer(sample_f)
    sample_writer.writerow(["rcept_no", "corp_code", "corp_name", "fiscal_year", "fiscal_period",
                             "report_type", "section_code", "label", "dropped_cell", "cells"])
    n_sampled = 0

    for i, r in enumerate(shard_rows):
        if i % 2000 == 0:
            logger.info(f"  ..{i}/{len(shard_rows)} hits={n_hits_total}건/{n_files_with_hit}건파일")
        n_files_scanned += 1
        try:
            hits = scan_file(r.file_path, fiscal_year=r.fiscal_year)
        except Exception as e:
            logger.debug(f"[scan] 오류 {r.rcept_no}: {e}")
            continue
        if not hits:
            continue
        n_files_with_hit += 1
        n_hits_total += len(hits)
        by_year[r.fiscal_year] += len(hits)
        by_report_type[r.report_type] += len(hits)
        corps_affected.add(r.corp_code)
        rcepts_affected.add(r.rcept_no)
        for h in hits:
            by_section[h["section_code"]] += 1
            if n_sampled < SAMPLE_CAP:
                sample_writer.writerow([r.rcept_no, r.corp_code, r.corp_name, r.fiscal_year,
                                         r.fiscal_period, r.report_type, h["section_code"],
                                         h["label"], h["dropped_cell"], h["cells"]])
                n_sampled += 1

    sample_f.close()

    summary = {
        "shard": args.shard,
        "n_shards": args.n_shards,
        "n_files_scanned": n_files_scanned,
        "n_files_with_hit": n_files_with_hit,
        "n_hits_total": n_hits_total,
        "n_distinct_corps_affected": len(corps_affected),
        "n_distinct_rcepts_affected": len(rcepts_affected),
        "by_fiscal_year": dict(sorted(by_year.items())),
        "by_section_code": dict(by_section.most_common()),
        "by_report_type": dict(by_report_type.most_common()),
        "n_sampled_rows_written": n_sampled,
        "sample_file": str(sample_path),
    }
    summary_path = Path(f"{args.out_prefix}_summary_shard{args.shard}.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    logger.success(f"샤드 {args.shard} 완료: {summary}")


if __name__ == "__main__":
    main()
