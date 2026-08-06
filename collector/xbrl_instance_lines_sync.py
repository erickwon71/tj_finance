"""계층2 증분 적재 — 데일리 파이프라인용, DART 표준 XBRL instance zip 전용
(`file_type='xbrl_zip'`, `parser_track='XBRL_INSTANCE'`).

`collector/note_lines_sync.py`(HTML/XML `document.xml` 경로, `file_type='xml'`)의 구조를
그대로 재사용한다 — 대상 쿼리만 다르고 나머지(corp 바운드 재개, 멱등 delete-then-insert,
한 건 실패가 전체를 막지 않는 것)는 동일한 원칙이다.

`fin2/extract/report_lines_xbrl.py::extract_report_lines_xbrl()`은 BS/IS/CF/SCE(본문)만
만든다(주석 없음 — 모듈 docstring 참고) — 그래서 여기서는 `store_report_lines`/
`store_report_tables`만 호출한다(`store_note_lines` 불필요).

★적재 완료 판정은 `report_lines.unit_source = 'xbrl'`로 한다(단순히 rcept_no 존재 여부가
아니라) — 같은 rcept_no가 `file_type='xml'` 경로(HTML/XML 파서, `unit_source` 다른 값)로도
적재될 가능성에 대비한 안전장치. `sync_layer2_lines`가 corp/note 두 테이블 UNION으로 재개
경계를 잡는 것과 같은 이유로, 여기서는 이 파이프라인이 실제로 쓴 행만 "이미 적재됨"으로 본다.

Phase 4 TODO(`docs/plans/xbrl_instance_parser_todo_2026-08-05.md`)의 두 call site 배선,
소급 백필(Phase 5), 검증(Phase 6)은 이 모듈과 별개 단계 — 이 파일은 4-1(신설)만 담당한다.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import store_report_lines, store_report_tables
from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl

FY_MIN = 2015

# 대상: XBRL instance zip 다운로드가 끝난 정기보고서(document.xml 014 폴백으로 받은 것,
# collector/downloader.py::_try_xbrl_instance_fallback — Phase 2). period_end_date 는
# extract_report_lines_xbrl() 의 col0(당기) 날짜 정확매치에 필수(없으면 그 rcept 는 스킵됨).
_TARGETS_SQL = text(
    """
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period, f.period_end_date
    FROM download_tasks dt JOIN filings f USING(rcept_no)
    WHERE dt.status = 'completed'
      AND dt.file_type = 'xbrl_zip'
      AND dt.file_path IS NOT NULL
      AND f.fiscal_year >= :fy_min
      AND f.corp_code = ANY(:corps)
    ORDER BY dt.rcept_no
    """
)

# 이미 이 파이프라인으로 적재된 rcept — corp 바운드(전역 스캔 회피, note_lines_sync.py 와
# 동일 원칙). unit_source='xbrl' 로 좁혀서 file_type='xml' 경로가 같은 rcept_no 를 이미
# 적재해놨어도(같은 보고서가 두 경로 다 있을 리는 없지만, 있다 해도) 잘못 "완료"로 보지 않는다.
_LOADED_SQL = text(
    """
    SELECT DISTINCT rcept_no FROM report_lines
    WHERE corp_code = ANY(:corps) AND unit_source = 'xbrl'
    """
)


def sync_xbrl_instance_lines(
    corps: list[str], year_min: int = FY_MIN, recheck: bool = False,
) -> dict:
    """주어진 기업들의 미적재 XBRL instance zip 을 계층2(report_lines/report_tables)에 적재한다.

    Args:
        corps: corp_code 목록
        year_min: 이 회계연도 이상만
        recheck: True 면 이미 적재된 rcept 도 다시 적재(파서 개선 소급 반영용)

    Returns:
        {"corps": n, "filings": n, "rows": n, "table_rows": n, "errors": n}
    """
    out = {"corps": 0, "filings": 0, "rows": 0, "table_rows": 0, "errors": 0}
    if not corps:
        return out

    with get_session() as session:
        targets = session.execute(
            _TARGETS_SQL, {"fy_min": year_min, "corps": list(corps)}
        ).fetchall()
        if not targets:
            return out

        if not recheck:
            loaded = {
                r[0]
                for r in session.execute(_LOADED_SQL, {"corps": list(corps)}).fetchall()
            }
            targets = [t for t in targets if t.rcept_no not in loaded]
        if not targets:
            return out

        seen_corps = set()
        for t in targets:
            if not Path(t.file_path).exists():
                continue
            try:
                lines = extract_report_lines_xbrl(
                    t.file_path,
                    rcept_no=t.rcept_no,
                    corp_code=t.corp_code,
                    report_fiscal_year=t.fiscal_year,
                    report_fiscal_period=t.fiscal_period,
                    period_end_date=t.period_end_date,
                )
                if not lines:
                    # extract_report_lines_xbrl 은 실패해도 절대 raise 하지 않고 [] 를 반환한다
                    # (모듈 docstring). 빈 결과는 실패가 아니라 "이 필링에서 뽑을 게 없었다" —
                    # errors 로 세지 않는다(note_lines_sync.py 의 예외 처리와 대칭되는 정상 경로).
                    out["filings"] += 1
                    seen_corps.add(t.corp_code)
                    continue
                out["rows"] += store_report_lines(session, t.rcept_no, lines)
                out["table_rows"] += store_report_tables(session, t.rcept_no, lines)
                out["filings"] += 1
                seen_corps.add(t.corp_code)
            except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                out["errors"] += 1
                logger.warning(
                    f"[xbrl_instance_lines] {t.rcept_no} 적재 실패: {type(exc).__name__}: {exc}"
                )
                session.rollback()
        session.commit()
        out["corps"] = len(seen_corps)

    return out
