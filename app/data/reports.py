"""공시 원문(보고서) 목록 — filings + download_tasks.

기업별 정기보고서(사업/반기/분기)를 연도·기간순으로 반환한다. 각 보고서는 DART 웹
뷰어 URL(공식 원문)과 로컬 저장 XML 경로(있으면 다운로드)를 함께 제공한다.
"""
from __future__ import annotations

from collector.db import get_session
from sqlalchemy import text

# DART 공시 원문 뷰어 (rcept_no 로 직접 열림)
DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}"

_TYPE_KO = {"annual": "사업보고서", "half": "반기보고서", "quarter": "분기보고서"}
# fiscal_period 기반 정확 명칭(같은 해 1분기/3분기 구분 → 라벨 중복 방지)
_PERIOD_KO = {"FY": "사업보고서", "H1": "반기보고서", "Q1": "1분기보고서", "Q3": "3분기보고서"}


def list_reports(corp_code: str) -> list[dict]:
    """
    corp 의 최종(is_final) 정기보고서 목록. 최신연도·최신기간 우선.

    반환: [{fiscal_year, fiscal_period, report_type, report_nm, rcept_no,
            is_amendment, file_path, dart_url, label}, ...]
    """
    sql = """
        SELECT f.rcept_no, f.report_nm, f.report_type, f.fiscal_year, f.fiscal_period,
               COALESCE(f.is_amendment, false) AS is_amendment, dt.file_path
        FROM filings f
        LEFT JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
        WHERE f.corp_code = :cc
          AND f.report_type IN ('annual', 'half', 'quarter')
          AND f.is_final IS NOT FALSE
        ORDER BY f.fiscal_year DESC NULLS LAST,
                 CASE f.fiscal_period WHEN 'FY' THEN 4 WHEN 'Q3' THEN 3
                      WHEN 'H1' THEN 2 WHEN 'Q1' THEN 1 ELSE 0 END DESC
    """
    with get_session() as session:
        rows = session.execute(text(sql), {"cc": corp_code}).mappings().fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d["dart_url"] = DART_VIEWER.format(rcept=r["rcept_no"])
        ko = _PERIOD_KO.get(r["fiscal_period"]) or _TYPE_KO.get(r["report_type"], "보고서")
        amend = " (정정)" if r["is_amendment"] else ""
        d["label"] = f"{r['fiscal_year']} {ko}{amend}"
        out.append(d)
    return out
