"""구형 레이아웃 "(N)명칭" 표제 census — SBI인베스트먼트(20120329001048)에서 발견된
`classify_legacy_statement_heading()` 미탐지 패턴("(1)연결재무상태표" 처럼 괄호숫자가
재무제표명 바로 앞에 붙는 형식)이 다른 필링에도 있는지, **실제 파서 코드로** 확인한다
(2026-09-13, 원문 grep 전수스캔은 문맥 없는 부분일치라 6만여건 오탐 — 폐기하고 이 방식으로
대체).

## 방법
`report_lines`가 0행인 전체 필링(4,842건, annual/half/quarter × file_type='xml')을 대상으로:
1. XML 파싱 → SEC_LEGACY_FS("재무제표등") 또는 SEC_LEGACY_APPENDIX("부속명세서") 섹션 탐색
2. 그 섹션 안의 각 요소 텍스트에 대해 현재 `classify_legacy_statement_heading()`이
   None을 반환하지만, 맨 앞 "(숫자)" 를 떼면 재무제표명으로 인식되는 경우를 센다
   (=이 fix가 실제로 구제할 필링).

사용: python scripts/census_legacy_paren_heading_2026-09-13.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import SEC_LEGACY_FS, SEC_LEGACY_APPENDIX, iter_section_elements
from fin2.extract.statement_titles import classify_legacy_statement_heading

_PAREN_NUM_PREFIX = re.compile(r"^\(\d+\)\s*")


def _load_candidates() -> list[dict]:
    sql = text("""
        SELECT f.rcept_no, dt.file_path, f.fiscal_year, f.report_type, c.corp_name
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
    logger.info(f"대상 {len(rows):,}건 (report_lines 0행 전체)")

    n_no_legacy_section = 0
    n_rescued = 0
    n_not_rescued_still_zero_heading = 0
    n_already_has_heading = 0  # 섹션은 있는데 이미 헤딩 인식됨(0행 원인이 다른 데 있음)
    n_read_fail = 0
    rescued: list[dict] = []

    for i, r in enumerate(rows, start=1):
        path = _resolve_path(r["file_path"])
        try:
            root = _parse_xml_file(path)
        except Exception:
            root = None
        if root is None:
            n_read_fail += 1
            continue

        elements = iter_section_elements(root, SEC_LEGACY_FS)
        if not elements:
            elements = iter_section_elements(root, SEC_LEGACY_APPENDIX)
        if not elements:
            n_no_legacy_section += 1
            continue

        found_existing_heading = False
        found_rescuable = False
        for tag, el in elements:
            txt = " ".join("".join(el.itertext()).split())
            if not txt:
                continue
            if classify_legacy_statement_heading(txt, include_sce=False) is not None:
                found_existing_heading = True
                continue
            stripped = _PAREN_NUM_PREFIX.sub("", txt)
            if stripped != txt and classify_legacy_statement_heading(
                    stripped, include_sce=False) is not None:
                found_rescuable = True

        if found_rescuable:
            n_rescued += 1
            rescued.append(r)
        elif found_existing_heading:
            n_already_has_heading += 1
        else:
            n_not_rescued_still_zero_heading += 1

        if i % 500 == 0:
            logger.info(f"{i:,}/{len(rows):,} — 구제후보 {n_rescued:,}건 발견 중")

    logger.success(
        f"완료 — 전체 {len(rows):,} · 레거시섹션없음 {n_no_legacy_section:,} · "
        f"헤딩이미인식(다른원인) {n_already_has_heading:,} · "
        f"★(N)패턴으로 구제가능 {n_rescued:,} · 그래도못찾음 {n_not_rescued_still_zero_heading:,} · "
        f"읽기실패 {n_read_fail:,}")

    if rescued:
        out = Path("manual_review/_legacy_paren_heading_census_2026-09-13/rescued.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        import csv
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["rcept_no", "corp_name", "fiscal_year", "report_type", "dart_link", "file_path"])
            for r in rescued:
                w.writerow([r["rcept_no"], r["corp_name"], r["fiscal_year"], r["report_type"],
                            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
                            r["file_path"]])
        logger.info(f"구제가능 목록 → {out}")


if __name__ == "__main__":
    main()
