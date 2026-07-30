"""계층2 증분 적재 — 데일리 파이프라인용. **본문(BS/IS/CF/SCE) + 주석(note) 둘 다.**

계층2 전사는 지금까지 `scripts/load_report_lines.py` 로 **수동 전량 적재**만 해왔고
`scripts/collect_new.py` 에는 배선돼 있지 않았다. 그래서 백필을 끝내도 **신규 보고서가
적재되지 않는** 상태였다. 이 모듈이 그 갭을 메운다.

★2026-07-31 (F4): 본문을 함께 적재하도록 넓혔다. 종전에는 같은 `extract_report_lines(...)`
호출로 본문 행까지 만들어 놓고 `store_note_lines` 만 불러 **본문을 버리고 있었다** — 그래서
신규 공시의 `report_lines` 가 데일리 경로에 영영 들어오지 않았다(승인된 계획의 P0,
`docs/plans/report_coverage_gaps_and_db_size_2026-07-30.md` §2-C). 추출은 이미 하고 있었으므로
추가 비용은 INSERT 뿐이다.

전량 백필(벌크)과의 차이 — 데일리는 다음을 하면 **안 된다**:
  · 인덱스 drop/create : 2.16억 행짜리 인덱스를 몇 건 넣자고 재생성하는 꼴
  · TRUNCATE           : 말할 것도 없음
  · `SELECT DISTINCT rcept_no FROM note_lines` 전역 스캔(로더의 재개 로직)
    → 2.16억 행 전체 스캔이라 데일리엔 부적합. 여기서는 **corp 바운드**로 확인한다.

멱등: store_note_lines 가 rcept 단위 delete-then-insert 라 재실행해도 중복되지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (extract_report_lines, store_note_lines,
                                       store_report_lines)

FY_MIN = 2015

# 대상: 이미 XML 다운로드가 끝난 정기보고서.
_TARGETS_SQL = text(
    """
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt JOIN filings f USING(rcept_no)
    WHERE dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
      AND f.fiscal_year >= :fy_min
      AND f.corp_code = ANY(:corps)
    ORDER BY dt.rcept_no
    """
)

# 이미 적재된 rcept — corp 바운드(전역 DISTINCT 스캔 회피).
# ★두 테이블을 모두 본다(2026-07-31): 주석이 0행인 보고서(비화폐 표만 있는 분기보고서 등)는
#   note_lines 에 흔적이 없어 매 실행마다 재처리된다. 본문까지 적재하게 된 지금은 그 재처리가
#   report_lines delete-then-insert 를 매일 반복하는 것이 되므로 본문 쪽도 함께 확인한다.
_LOADED_SQL = text(
    """
    SELECT rcept_no FROM note_lines   WHERE corp_code = ANY(:corps)
    UNION
    SELECT rcept_no FROM report_lines WHERE corp_code = ANY(:corps)
    """
)


def sync_layer2_lines(
    corps: list[str], year_min: int = FY_MIN, recheck: bool = False,
    include_body: bool = True,
) -> dict:
    """주어진 기업들의 미적재 보고서를 계층2 두 테이블에 적재한다.

    Args:
        corps: corp_code 목록
        year_min: 이 회계연도 이상만
        recheck: True 면 이미 적재된 rcept 도 다시 적재(파서 개선 소급 반영용)
        include_body: False 면 주석만(종전 동작). 기본 True = 본문도 적재.

    Returns:
        {"corps": n, "filings": n, "rows": n, "body_rows": n, "errors": n}
        (`rows` 는 주석 행 수 — 기존 호출부 로그 호환)
    """
    out = {"corps": 0, "filings": 0, "rows": 0, "body_rows": 0, "errors": 0}
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
                lines = extract_report_lines(
                    t.file_path,
                    rcept_no=t.rcept_no,
                    corp_code=t.corp_code,
                    report_fiscal_year=t.fiscal_year,
                    report_fiscal_period=t.fiscal_period,
                    include_notes=True,
                )
                out["rows"] += store_note_lines(session, t.rcept_no, lines)
                if include_body:
                    # 같은 추출 결과에서 본문(BS/IS/CF/SCE)을 적재한다. store_report_lines 가
                    # rcept 단위 delete-then-insert + col_index=0 필터를 이미 한다.
                    out["body_rows"] += store_report_lines(session, t.rcept_no, lines)
                out["filings"] += 1
                seen_corps.add(t.corp_code)
            except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                out["errors"] += 1
                logger.warning(
                    f"[note_lines] {t.rcept_no} 적재 실패: {type(exc).__name__}: {exc}"
                )
                session.rollback()
        session.commit()
        out["corps"] = len(seen_corps)

    return out


# 구 이름 호환(호출부가 아직 쓴다). 동작은 동일 — 본문 적재 포함.
sync_note_lines = sync_layer2_lines
