"""
DART Open API HTTP 클라이언트
- rate limiter 자동 적용
- tenacity 기반 재시도 (5xx / 네트워크 오류)
- 공통 응답 파싱 헬퍼
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    RetryError,
)
import logging

from collector.config import (
    DART_API_KEY, DART_BASE_URL,
    MAX_RETRIES, RETRY_WAIT_MIN, RETRY_WAIT_MAX,
    DOWNLOAD_TIMEOUT,
)
from collector.rate_limiter import get_limiter


# tenacity용 Python 표준 logger (loguru → stdlib 브리지)
_std_logger = logging.getLogger("tenacity")


class DartApiError(Exception):
    """DART API 응답 오류 (status 코드 != 000)"""
    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(f"DART API Error [{status}]: {message}")


class DartClient:
    """
    DART Open API 래퍼.
    인스턴스 생성 후 with 문 없이 바로 사용 가능 (httpx.Client 내부 관리).
    """

    def __init__(self, api_key: str = DART_API_KEY):
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=DART_BASE_URL,
            timeout=DOWNLOAD_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "TJFinance/1.0 (personal research)"},
        )

    def close(self):
        self._client.close()

    # ── 핵심 메서드 ─────────────────────────────────────────────

    def get_corp_code_zip(self) -> bytes:
        """
        전체 기업 코드 ZIP 다운로드.
        /api/corpCode.xml → ZIP 바이너리 반환.
        """
        return self._raw_get("/corpCode.xml", params={})

    def get_filing_list(
        self,
        corp_code: str,
        bgn_de: str,
        end_de: str,
        pblntf_ty: str = "A",   # A: 정기공시
        page_no: int = 1,
        page_count: int = 100,
    ) -> dict[str, Any]:
        """
        공시 목록 조회 (JSON).
        반환: {total_count, page_no, page_count, list: [...]}
        """
        params = {
            "corp_code":   corp_code,
            "bgn_de":      bgn_de,
            "end_de":      end_de,
            "pblntf_ty":   pblntf_ty,
            "page_no":     page_no,
            "page_count":  page_count,
        }
        return self._api_get_json("/list.json", params)

    def get_document_zip(self, rcept_no: str) -> bytes:
        """
        공시 원본 문서 ZIP 다운로드.
        /api/document.xml → ZIP 바이너리 반환.
        """
        return self._raw_get("/document.xml", params={"rcept_no": rcept_no})

    def get_single_account(
        self,
        corp_code: str,
        bsns_year: str | int,
        reprt_code: str = "11011",   # 11011 사업보고서 / 11012 반기 / 11013 1분기 / 11014 3분기
    ) -> list[dict[str, Any]]:
        """
        단일회사 주요계정(fnlttSinglAcnt) — 독립 소스 교차검증용.
        DART가 공시 원문에서 구조화해 제공하는 주요계정(매출액·영업이익·당기순이익·자산/부채/자본총계
        등)을 반환한다. 각 행은 fs_div(CFS=연결/OFS=별도)·account_nm·thstrm_amount(당기금액, 원) 포함.
        조회결과 없음(status 013) → 빈 리스트. 2015 사업연도부터 제공.
        """
        params = {
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
        }
        data = self._api_get_json("/fnlttSinglAcnt.json", params)
        return data.get("list", [])

    def get_executive_status(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """임원 현황(exctvSttus) — 성명·직위·등기/상근·담당업무·주요경력·최대주주관계·재직기간 등.
        지배구조 패널용. 조회결과 없음(013) → 빈 리스트. 사업보고서(11011) 기준."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        data = self._api_get_json("/exctvSttus.json", params)
        return data.get("list", [])

    def get_major_shareholders(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """최대주주 현황(hyslrSttus) — 주주명·관계·주식종류·기초/기말 소유주식수·지분율.
        B3 지배구조 패널용. 조회결과 없음(013) → 빈 리스트. 사업보고서(11011) 기준."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/hyslrSttus.json", params).get("list", [])

    def get_shareholder_changes(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """최대주주 변동현황(hyslrChgSttus) — 변동일·변경후 최대주주·지분율·변동원인.
        변동이 없던 연도는 '-' 로 채워진 placeholder 1행만 옴(호출측에서 필터)."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/hyslrChgSttus.json", params).get("list", [])

    def get_minority_shareholders(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """소액주주 현황(mrhlSttus) — corp+연도당 1행 집계(소액주주 수/지분율). float(유통물량) 근사치."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/mrhlSttus.json", params).get("list", [])

    def get_dividend_matters(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """배당에 관한 사항(alotMatter) — se(항목명)+stock_knd 조합의 long-format 응답
        (주당액면가액/당기순이익/현금배당금총액/현금배당성향/현금배당수익률/주당 현금배당금 등
        약 15행, 실호출 확인 2026-07-12). 조회결과 없음(013) → 빈 리스트."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/alotMatter.json", params).get("list", [])

    def get_treasury_stock_status(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """자기주식 취득 및 처분현황(tesstkAcqsDspsSttus) — 취득방법(대/중/소분류)×주식종류
        조합별 1행(총계/소계 subtotal 포함). 조회결과 없음(013) → 빈 리스트."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/tesstkAcqsDspsSttus.json", params).get("list", [])

    def get_employee_status(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """직원 현황(empSttus) — 부문×성별 조합별 1행(부문/성별 합계행 포함).
        조회결과 없음(013) → 빈 리스트."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/empSttus.json", params).get("list", [])

    def get_other_corp_investment(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """타법인 출자현황(otrCprInvstmntSttus) — 피출자법인별 1행. 조회결과 없음(013) → 빈 리스트."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/otrCprInvstmntSttus.json", params).get("list", [])

    def get_exec_pay_summary(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """이사·감사 전체의 보수현황(hmvAuditAllSttus) — corp+연도당 1행 집계.
        조회결과 없음(013) → 빈 리스트."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/hmvAuditAllSttus.json", params).get("list", [])

    def get_exec_pay_individual(
        self, corp_code: str, bsns_year: str | int, reprt_code: str = "11011",
    ) -> list[dict[str, Any]]:
        """개인별 보수지급금액(indvdlByPay, 5억원 이상 상위5인) — 등기임원 여부 무관(고문/상담역
        등 미등기 포함 가능). get_executive_status 의 hmvAuditIndvdlBySttus(등기임원 한정)와
        별개 소스이므로 executives.compensation 과 병존한다. 조회결과 없음(013) → 빈 리스트."""
        params = {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code}
        return self._api_get_json("/indvdlByPay.json", params).get("list", [])

    def get_company(self, corp_code: str) -> dict[str, Any]:
        """기업개황(company.json) — induty_code(업종/KSIC)·acc_mt(결산월)·corp_cls 등.
        섹터/피어 그룹핑용. 조회결과 없음(013) → 빈 dict."""
        data = self._api_get_json("/company.json", {"corp_code": corp_code})
        return {} if data.get("status") == "013" else data

    # ── 내부 헬퍼 ───────────────────────────────────────────────

    def _api_get_json(self, path: str, params: dict) -> dict:
        """JSON 응답 API 호출 + 상태코드 검증"""
        params["crtfc_key"] = self.api_key
        get_limiter().wait()

        response = self._request_with_retry(path, params)
        data = response.json()

        status = data.get("status", "")
        message = data.get("message", "")

        if status == "013":
            # 조회 결과 없음 — 오류가 아닌 정상 케이스
            return {"total_count": 0, "page_no": 1, "page_count": 0, "list": []}

        if status != "000":
            raise DartApiError(status, message)

        return data

    def _raw_get(self, path: str, params: dict) -> bytes:
        """바이너리 응답 (ZIP 등) 다운로드"""
        params["crtfc_key"] = self.api_key
        get_limiter().wait()

        response = self._request_with_retry(path, params)
        return response.content

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
        before_sleep=before_sleep_log(_std_logger, logging.WARNING),
        reraise=True,
    )
    def _request_with_retry(self, path: str, params: dict) -> httpx.Response:
        """HTTP GET with 자동 재시도 (5xx / 네트워크 오류)"""
        response = self._client.get(path, params=params)

        if response.status_code == 429:
            # Too Many Requests — rate limit 보호
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning(f"429 Too Many Requests. {retry_after}초 대기...")
            time.sleep(retry_after)
            raise httpx.TransportError("429 rate limited")  # 재시도 유발

        if response.status_code >= 500:
            logger.warning(f"서버 오류 {response.status_code} ({path}), 재시도...")
            raise httpx.TransportError(f"HTTP {response.status_code}")

        response.raise_for_status()
        return response
