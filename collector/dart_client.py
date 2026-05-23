"""
DART Open API HTTP 클라이언트
- rate limiter 자동 적용
- tenacity 기반 재시도 (5xx / 네트워크 오류)
- 공통 응답 파싱 헬퍼
"""
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
