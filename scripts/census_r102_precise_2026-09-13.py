"""R102(주석마커/헤딩판정 순서변경) 만의 **정확한** 기여도 측정 — "DB에 report_lines가
있는지"로 비교하면 오늘 손 안 댄 다른 전면적 개선(수개월치 누적 수정)까지 섞여 부풀려진다
(실측: 삼일제약 20000330000052은 레거시 섹션이 사실상 비어있는데도 "1행 확보"로 잡혔다 —
R100/R101/R102와 무관, 그냥 전혀 다른 경로에서 나온 값).

이 스크립트는 R102가 **정확히 무엇을 바꾸는지**(주석마커로 걸릴 요소인데 R101 꼬리표제
폴백으로는 헤딩으로도 인식되는 경우) 그 조건만 직접 재현해 센다 — DB 상태와 무관.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import SEC_LEGACY_FS, SEC_LEGACY_APPENDIX, iter_section_elements
from fin2.extract.statement_titles import classify_legacy_statement_heading, is_legacy_note_marker


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
    logger.info(f"대상 {len(rows):,}건")

    n_no_section = 0
    n_r102_triggers = 0
    n_read_fail = 0
    hits: list[dict] = []

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
            n_no_section += 1
            continue

        found = False
        for tag, el in elements:
            txt = " ".join("".join(el.itertext()).split())
            if not txt:
                continue
            # 정확히 R102가 바꾸는 조건: 예전 순서라면 주석마커에 먼저 걸렸을 텐데
            # (is_legacy_note_marker True), 그럼에도 헤딩판정이 성공하는 경우.
            if is_legacy_note_marker(txt) and classify_legacy_statement_heading(txt) is not None:
                found = True
                break
        if found:
            n_r102_triggers += 1
            hits.append(r)

        if i % 1000 == 0:
            logger.info(f"{i:,}/{len(rows):,} — R102 트리거 {n_r102_triggers:,}건")

    logger.success(f"완료 — 전체 {len(rows):,} · 섹션없음 {n_no_section:,} · "
                    f"★R102가 실제로 바꾸는 건 {n_r102_triggers:,} · 읽기실패 {n_read_fail:,}")

    if hits:
        out = Path("manual_review/_legacy_paren_heading_census_2026-09-13/r102_precise.csv")
        import csv
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["rcept_no", "corp_name", "fiscal_year", "report_type", "dart_link"])
            for r in hits:
                w.writerow([r["rcept_no"], r["corp_name"], r["fiscal_year"], r["report_type"],
                            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"])
        logger.info(f"목록 → {out}")


if __name__ == "__main__":
    main()
