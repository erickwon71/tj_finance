"""
보고서 수집·DB화 파이프라인 헬퍼 (수집 페이지용).

실행일 기준으로 최근 등록된 정기공시(사업/반기/분기)를 DART 날짜범위 조회로 효율적으로
탐지(전 기업 per-corp 스캔 회피)한 뒤, 기존 검증된 파이프라인을 그 기업들로 한정해 재사용:
  sync_filings(corp_codes) → run_downloads(only_corp_codes) → process_corp(per corp).

DART list.json 은 corp_code 없이 bgn_de~end_de 로 전체 정기공시를 페이지네이션 조회 가능.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from collector.db import get_session


def collection_status() -> dict:
    """수집 대시보드 지표(읽기 전용)."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT
              (SELECT max(filed_at) FROM filings) AS latest_filed,
              (SELECT count(*) FROM corporations WHERE is_active) AS active_corps,
              (SELECT count(*) FROM filings
                 WHERE report_type IN ('annual','half','quarter')) AS filings,
              (SELECT count(*) FROM download_tasks
                 WHERE status='completed' AND file_type='xml') AS downloaded,
              (SELECT count(*) FROM download_tasks
                 WHERE status IN ('pending','failed')) AS pending,
              (SELECT count(DISTINCT corp_code) FROM std_financials_v2) AS std_corps
        """)).mappings().fetchone()
    return dict(row)


def refresh_universe() -> dict:
    """
    상장 유니버스(활성 보통주) 갱신 — KRX 상장 목록 기준으로 **신규 상장** 기업을 대상에
    추가(is_active=True)하고, 목록에서 빠진 기업(**상장폐지·제외**)을 비활성화(is_active=False).

    반환: sync_corporations() 결과(new_count/new_corps/deactivated/deactivated_corps 포함).
    ⚠ KRX(FinanceDataReader) + DART corpCode.xml 네트워크 조회가 있어 수십 초 걸릴 수 있음.
    """
    from collector.corp_collector import sync_corporations
    return sync_corporations()


def discover_recent_corps(days: int = 7) -> dict:
    """
    최근 `days` 일 DART 정기공시(pblntf_ty=A) 날짜범위 조회 → 우리 활성 보통주 중
    공시가 올라온 corp_code 목록. (corp_code 없이 list.json 페이지네이션)

    반환: {"corps": [corp_code...], "total_filings": N, "window": "bgn~end"}
    """
    from collector.dart_client import DartClient

    end = date.today()
    bgn = end - timedelta(days=max(1, days))
    bgn_s, end_s = bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    client = DartClient()
    seen_corps: set[str] = set()
    total = 0
    page = 1
    try:
        while page <= 100:  # 안전 상한
            data = client._api_get_json("/list.json", {
                "bgn_de": bgn_s, "end_de": end_s, "pblntf_ty": "A",
                "page_no": page, "page_count": 100,
            })
            items = data.get("list", []) or []
            for it in items:
                cc = it.get("corp_code")
                if cc:
                    seen_corps.add(cc)
            total += len(items)
            total_page = int(data.get("total_page", 1) or 1)
            if page >= total_page or not items:
                break
            page += 1
    finally:
        client.close()

    with get_session() as s:
        active = {r[0] for r in s.execute(
            text("SELECT corp_code FROM corporations WHERE is_active")).fetchall()}

    return {
        "corps": sorted(seen_corps & active),
        "total_filings": total,
        "window": f"{bgn_s}~{end_s}",
    }


def needs_standardize_corps(only: list[str] | None = None) -> list[str]:
    """
    다운로드(xml completed)는 됐지만 그 (fy, 기간)이 아직 std_v2 에 없는 기업 = 표준화 대상.
    only 지정 시 그 corp 들로 한정.
    """
    clause = "AND f.corp_code = ANY(:only)" if only else ""
    sql = f"""
        SELECT DISTINCT f.corp_code
        FROM filings f
        JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
         AND dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
        WHERE f.report_type IN ('annual','half','quarter') {clause}
          AND NOT EXISTS (
            SELECT 1 FROM std_financials_v2 s
            WHERE s.corp_code=f.corp_code AND s.fiscal_year=f.fiscal_year
              AND s.fiscal_period=f.fiscal_period)
        ORDER BY f.corp_code
    """
    params = {"only": only} if only else {}
    with get_session() as s:
        rows = s.execute(text(sql), params).fetchall()
    return [r[0] for r in rows]
