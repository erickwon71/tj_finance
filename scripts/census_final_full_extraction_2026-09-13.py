"""오늘(2026-09-13) 수정 3종(R100 괄호숫자 접두 + R101 꼬리표제 + pending_age 빈요소
스킵) 의 **진짜** 전사 영향도 — classify() 함수 비교가 아니라 `extract_report_lines()`
그 자체를 0행 필링 전체(이미 오늘 구제 확인된 55건 제외)에 돌려 몇 건이 실제로 데이터를
얻는지 최종 확정한다. (앞선 census_r101_tail_heading_2026-09-13.py 는 classify() 함수
차이만 봐서 "54건"을 찾았지만, pending_age 수정은 그 스캔에 안 걸렸다 — 이 스크립트가
최종 확정치다.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from fin2.extract.report_lines import extract_report_lines


def _load_candidates() -> list[dict]:
    sql = text("""
        SELECT f.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
               c.corp_name
        FROM filings f
        JOIN download_tasks dt USING(rcept_no)
        JOIN corporations c ON c.corp_code = f.corp_code
        LEFT JOIN report_lines rl ON rl.rcept_no = f.rcept_no
        WHERE f.report_type IN ('annual','half','quarter')
          AND dt.status='completed' AND dt.file_type='xml'
          AND rl.rcept_no IS NULL
        ORDER BY f.fiscal_year
    """)
    with get_session() as s:
        return [dict(r) for r in s.execute(sql).mappings()]


def _resolve_path(file_path: str) -> Path:
    p = Path(file_path)
    try:
        sd = BACKUP_ROOT / p.relative_to(_RAW_REPORT_SYMLINK)
        if sd.exists():
            return sd
    except ValueError:
        pass
    return p


def main() -> None:
    rows = _load_candidates()
    logger.info(f"대상 {len(rows):,}건 (report_lines 0행 전체, 오늘 구제분 제외)")

    n_now_data = 0
    n_still_zero = 0
    n_error = 0
    rescued: list[dict] = []

    for i, r in enumerate(rows, start=1):
        path = _resolve_path(r["file_path"])
        try:
            lines = extract_report_lines(
                str(path), rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                report_fiscal_year=r["fiscal_year"],
                report_fiscal_period=r["fiscal_period"], include_notes=False)
        except Exception as exc:
            n_error += 1
            continue
        if lines:
            n_now_data += 1
            rescued.append(r)
        else:
            n_still_zero += 1

        if i % 500 == 0:
            logger.info(f"{i:,}/{len(rows):,} — 신규데이터 {n_now_data:,}건")

    logger.success(f"완료 — 전체 {len(rows):,} · ★신규데이터확보 {n_now_data:,} · "
                    f"여전히0행 {n_still_zero:,} · 오류 {n_error:,}")

    if rescued:
        out = Path("manual_review/_legacy_paren_heading_census_2026-09-13/rescued_final_full.csv")
        import csv
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["rcept_no", "corp_name", "corp_code", "fiscal_year", "fiscal_period",
                        "dart_link", "file_path"])
            for r in rescued:
                w.writerow([r["rcept_no"], r["corp_name"], r["corp_code"], r["fiscal_year"],
                            r["fiscal_period"],
                            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
                            r["file_path"]])
        logger.info(f"목록 → {out}")


if __name__ == "__main__":
    main()
