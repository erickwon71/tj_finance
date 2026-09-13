"""R101 꼬리표제 폴백(문장 종결 뒤 헤딩) 전사 영향도 재확인 — R100("(N)" 접두)과
R101(문장 뒤 꼬리 헤딩)을 합친 **현재 코드**와, 오늘 손대기 전 **원본 코드**
(`git show HEAD:...`)를 나란히 돌려 0행 필링(4,842건) 중 몇 건이 새로 헤딩을
찾는지 정확히 비교한다 (2026-09-13).

사용: python scripts/census_r101_tail_heading_2026-09-13.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import SEC_LEGACY_FS, SEC_LEGACY_APPENDIX, iter_section_elements

# ── 원본(오늘 수정 전) classify_legacy_statement_heading 을 별도 모듈로 로드 ──
_ORIG_PATH = Path(
    "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
    "c4504621-124b-4f2a-a595-ddb7edd24020/scratchpad/orig_statement_titles.py")
_spec = importlib.util.spec_from_file_location("orig_statement_titles", _ORIG_PATH)
_orig_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_orig_mod)
classify_orig = _orig_mod.classify_legacy_statement_heading

# 현재(오늘 수정 반영) 버전
from fin2.extract.statement_titles import classify_legacy_statement_heading as classify_new


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
    n_newly_rescued = 0
    n_no_change = 0
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

        had_orig_heading = False
        has_new_heading = False
        for tag, el in elements:
            txt = " ".join("".join(el.itertext()).split())
            if not txt:
                continue
            if classify_orig(txt, include_sce=False) is not None:
                had_orig_heading = True
            if classify_new(txt, include_sce=False) is not None:
                has_new_heading = True

        if not had_orig_heading and has_new_heading:
            n_newly_rescued += 1
            rescued.append(r)
        else:
            n_no_change += 1

        if i % 1000 == 0:
            logger.info(f"{i:,}/{len(rows):,} — 신규구제 {n_newly_rescued:,}건 발견 중")

    logger.success(
        f"완료 — 전체 {len(rows):,} · 레거시섹션없음 {n_no_legacy_section:,} · "
        f"★신규구제(오늘 수정 전엔 헤딩 0개 → 지금은 있음) {n_newly_rescued:,} · "
        f"변화없음 {n_no_change:,} · 읽기실패 {n_read_fail:,}")

    if rescued:
        out = Path("manual_review/_legacy_paren_heading_census_2026-09-13/rescued_r101.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        import csv
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["rcept_no", "corp_name", "fiscal_year", "report_type", "dart_link", "file_path"])
            for r in rescued:
                w.writerow([r["rcept_no"], r["corp_name"], r["fiscal_year"], r["report_type"],
                            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
                            r["file_path"]])
        logger.info(f"신규구제 목록 → {out}")


if __name__ == "__main__":
    main()
