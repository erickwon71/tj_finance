"""
DART 웹(dart.fss.or.kr) 기반 구형 공시 문서 수집기

OpenDART API(opendart.fss.or.kr) document.xml에서 014(파일없음) 오류가
반환되는 구형 문서를 DART 웹에서 직접 수집합니다.

수집 흐름:
  1. dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}
     → 공시 뷰어 메인 페이지 조회 (세션 쿠키 + dcmNo 수집)
     → viewDoc("rcpNo","dcmNo","eleId","offset","length","dtd","") 파싱

  2-A. PDF 우선 시도 (dart.fss.or.kr/pdf/download)
       /pdf/download/main.do?rcp_no=...&dcm_no=...  → PDF 존재 확인
       /pdf/download/pdf.do?rcp_no=...&dcm_no=...   → PDF 바이너리 다운로드

  2-B. PDF 없을 때 HTML 뷰어 폴백
       /report/viewer.do?rcpNo=...&dcmNo=...&eleId=...&offset=...&length=...&dtd=...

핵심 설계:
  - PDF가 존재하면 항상 PDF 우선 (HTML 표지 페이지 문제 해결)
  - viewDoc() JS 함수 인수를 위치 기반으로 파싱
    (DART 뷰어 세대별 dtd가 dart2.dtd / dart3.xsd로 다름 → 자동 감지)
  - eleId/offset/length: viewDoc 실제 값 사용 (0으로 고정하면 빈 응답 반환)
  - 세션 쿠키(JSESSIONID): 메인 페이지 방문으로 자동 취득, httpx.Client 재사용
  - 2초 간격 쓰로틀링 (공공 서비스 부하 경감)
"""
import re
import time
from typing import Optional

import httpx
from loguru import logger


DART_WEB_BASE  = "https://dart.fss.or.kr"
WEB_INTERVAL   = 2.0    # 요청 간 최소 간격(초)
MIN_HTML_BYTES = 500    # 유효 HTML 응답 최소 크기

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer":         DART_WEB_BASE,
}


class LegacyDartScraper:
    """
    DART 웹 스크래퍼.
    run_downloads() 한 번에 단일 인스턴스를 생성·재사용.
    쿠키 유지를 위해 httpx.Client를 내부에서 재사용함.
    """

    def __init__(self):
        self._client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers=_HEADERS,
        )
        self._last_ts = 0.0

    def close(self) -> None:
        self._client.close()

    # ── 공개 API ────────────────────────────────────────────────

    def fetch(self, rcept_no: str) -> tuple[Optional[bytes], str]:
        """
        rcept_no 공시 문서 다운로드.
        순서: PDF 우선 → HTML 뷰어 폴백
        반환: (bytes, fmt) — fmt는 "pdf" 또는 "html"
               실패 시 (None, "")
        """
        logger.debug(f"    [legacy] 시도: {rcept_no}")

        params = self._get_view_params(rcept_no)
        if not params:
            logger.debug(f"    [legacy] 뷰어 파라미터 추출 실패")
            return None, ""

        dcm_no = params["dcmNo"]
        logger.debug(
            f"    [legacy] dcmNo={dcm_no}  eleId={params['eleId']}  dtd={params['dtd']}"
        )

        # ── 1. PDF 시도 ──────────────────────────────────────
        pdf_bytes = self._fetch_pdf(rcept_no, dcm_no)
        if pdf_bytes:
            logger.debug(f"    [legacy] PDF 성공: {len(pdf_bytes):,}B")
            return pdf_bytes, "pdf"

        # ── 2. HTML 뷰어 폴백 ────────────────────────────────
        html_bytes = self._fetch_html(rcept_no, params)
        if html_bytes and len(html_bytes) >= MIN_HTML_BYTES:
            logger.debug(f"    [legacy] HTML 성공: {len(html_bytes):,}B")
            return html_bytes, "html"

        logger.debug(
            f"    [legacy] 모두 실패 "
            f"(HTML크기={len(html_bytes) if html_bytes else 0}B)"
        )
        return None, ""

    def fetch_xbrl_zip(self, rcept_no: str) -> tuple[Optional[bytes], Optional[str]]:
        """
        표준 XBRL 원문(instance+taxonomy zip) 다운로드 (docs/plans/xbrl_instance_parser_2026-08-05.md
        Phase 0 실측 기반). `_get_view_params()`로 dcm_no 확보 후 ifrs.do 1회 GET이면 충분
        (PDF 흐름의 main.do 존재확인 단계는 필요 없음 — Phase 0 §1).

        반환: (zip_bytes, dcm_no) — 실패(파라미터 추출 실패 또는 XBRL 부재) 시 (None, None)
        """
        params = self._get_view_params(rcept_no)
        if not params:
            logger.debug(f"    [legacy] XBRL: 뷰어 파라미터 추출 실패")
            return None, None

        dcm_no = params["dcmNo"]
        zip_bytes = self._fetch_xbrl_instance(rcept_no, dcm_no)
        if zip_bytes:
            logger.debug(f"    [legacy] XBRL zip 성공: {len(zip_bytes):,}B (dcm_no={dcm_no})")
            return zip_bytes, dcm_no

        logger.debug(f"    [legacy] XBRL zip 없음/실패 (dcm_no={dcm_no})")
        return None, None

    # ── 내부 메서드 ─────────────────────────────────────────────

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_ts
        if elapsed < WEB_INTERVAL:
            time.sleep(WEB_INTERVAL - elapsed)
        self._last_ts = time.monotonic()

    def _get(self, url: str, params: dict) -> Optional[httpx.Response]:
        self._throttle()
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            logger.debug(f"    [legacy] HTTP {e.response.status_code}: {url}")
            return None
        except Exception as e:
            logger.debug(f"    [legacy] 요청 실패: {e}")
            return None

    def _fetch_pdf(self, rcept_no: str, dcm_no: str) -> Optional[bytes]:
        """
        dart.fss.or.kr/pdf/download 엔드포인트로 PDF 다운로드 시도.

        흐름:
          1. /pdf/download/main.do  → PDF 존재 여부 확인 (HTML 목록 페이지)
          2. /pdf/download/pdf.do   → PDF 바이너리 다운로드 (Referer 필수)

        반환: PDF bytes (성공) / None (PDF 없거나 실패)
        """
        # 1. PDF 목록 페이지 확인
        main_resp = self._get(
            f"{DART_WEB_BASE}/pdf/download/main.do",
            {"rcp_no": rcept_no, "dcm_no": dcm_no},
        )
        if not main_resp or "/pdf/download/pdf.do" not in main_resp.text:
            logger.debug(f"    [legacy] PDF 없음 (dcm_no={dcm_no})")
            return None

        # 2. PDF 실제 다운로드 (Referer: main.do 필요)
        self._throttle()
        try:
            resp = self._client.get(
                f"{DART_WEB_BASE}/pdf/download/pdf.do",
                params={"rcp_no": rcept_no, "dcm_no": dcm_no},
                headers={
                    **_HEADERS,
                    "Referer": (
                        f"{DART_WEB_BASE}/pdf/download/main.do"
                        f"?rcp_no={rcept_no}&dcm_no={dcm_no}"
                    ),
                },
                timeout=120,  # PDF 대용량 대비
            )
            resp.raise_for_status()
            self._last_ts = time.monotonic()
        except Exception as e:
            logger.debug(f"    [legacy] PDF 다운로드 실패: {e}")
            return None

        content = resp.content
        # PDF 매직 바이트 확인 (%PDF)
        if content[:4] != b"%PDF":
            logger.debug(
                f"    [legacy] PDF 매직 바이트 불일치 "
                f"(첫 8B={content[:8].hex()}, "
                f"Content-Type={resp.headers.get('content-type', '?')})"
            )
            return None

        return content

    def _fetch_xbrl_instance(self, rcept_no: str, dcm_no: str) -> Optional[bytes]:
        """
        dart.fss.or.kr/pdf/download/ifrs.do 엔드포인트로 표준 XBRL instance zip 다운로드.

        PDF 흐름(`_fetch_pdf`)의 main.do 존재확인 2단계와 달리, 여기는 **1회 GET으로 충분**
        (Phase 0 실측 §1 — main.do는 PDF 존재 여부만 알려주고 XBRL 존재와는 무관).
        """
        self._throttle()
        try:
            resp = self._client.get(
                f"{DART_WEB_BASE}/pdf/download/ifrs.do",
                params={"rcp_no": rcept_no, "dcm_no": dcm_no, "lang": "ko"},
                headers={
                    **_HEADERS,
                    # Referer는 반드시 /pdf/download/main.do (dsaf001/main.do 아님) — 아니면
                    # 서버가 200 + Content-Length 0(빈 바디)만 반환함(_fetch_pdf 패턴과 동일 Referer 필요,
                    # main.do를 실제로 먼저 호출할 필요는 없음 — Referer 값만 맞으면 충분, 재확인됨).
                    "Referer": (
                        f"{DART_WEB_BASE}/pdf/download/main.do"
                        f"?rcp_no={rcept_no}&dcm_no={dcm_no}"
                    ),
                },
                timeout=120,  # 대형 연결기업 zip은 수십MB (Phase 0: 한화 1.1MB, 더 큰 필링 가능)
            )
            resp.raise_for_status()
            self._last_ts = time.monotonic()
        except Exception as e:
            logger.debug(f"    [legacy] XBRL instance 다운로드 실패: {e}")
            return None

        content = resp.content
        # zip 매직 바이트 확인 (PK\x03\x04). HTML 오류 페이지와 구분(Phase 0: 2866B HTML vs zip).
        if content[:4] != b"PK\x03\x04":
            logger.debug(
                f"    [legacy] XBRL zip 매직 바이트 불일치 "
                f"(첫 8B={content[:8].hex()}, "
                f"Content-Type={resp.headers.get('content-type', '?')})"
            )
            return None

        return content

    def _get_view_params(self, rcept_no: str) -> Optional[dict]:
        """
        DART 뷰어 메인 페이지에서 viewDoc 파라미터 추출.
        메인 페이지 방문으로 세션 쿠키(JSESSIONID)도 함께 취득.

        viewDoc() 인수 위치:
          [0] rcpNo   [1] dcmNo   [2] eleId   [3] offset
          [4] length  [5] dtd     [6] tocNo

        dtd 예시:
          - dart2.dtd : ~2012년 이전 구형 공시
          - dart3.xsd : 2013년 이후 현행 공시

        ※ eleId/offset/length를 0으로 고정하면 viewer.do가 빈 응답을 반환하므로
          viewDoc 실제 값을 그대로 사용해야 함.
        """
        resp = self._get(
            f"{DART_WEB_BASE}/dsaf001/main.do",
            {"rcpNo": rcept_no},
        )
        if resp is None:
            return None

        text = resp.text

        # ── 전략 1: viewDoc("rcpNo","dcmNo",...) 위치 기반 파싱 ─────
        # 모든 viewDoc( ... ) 블록을 추출 → rcept_no 포함된 것 선택
        for call_match in re.finditer(r"viewDoc\([^)]{5,400}\)", text, re.DOTALL):
            call = call_match.group(0)
            if rcept_no not in call:
                continue

            # 쌍따옴표로 묶인 인수 순서대로 추출
            args = re.findall(r'"([^"]*)"', call)
            if len(args) >= 2 and args[1].isdigit():
                return {
                    "dcmNo":  args[1],
                    # eleId/offset/length: 실제 viewDoc 값 사용
                    # (0으로 고정하면 viewer.do 가 빈 응답을 반환함)
                    "eleId":  args[2] if len(args) > 2 and args[2].lstrip("-").isdigit() else "0",
                    "offset": args[3] if len(args) > 3 and args[3].lstrip("-").isdigit() else "0",
                    "length": args[4] if len(args) > 4 and args[4].lstrip("-").isdigit() else "0",
                    # dtd: args[5] 있으면 사용, 없으면 dart3.xsd
                    "dtd": args[5] if len(args) > 5 and args[5] else "dart3.xsd",
                }

        # ── 전략 2: dcmNo 키워드 직접 탐색 (JSON / URL 파라미터 형식) ─
        m = re.search(r'["\s(,]dcmNo[":\s=]+(\d{4,})', text, re.IGNORECASE)
        if m:
            logger.debug("    [legacy] dcmNo 키워드 패턴으로 추출")
            return {
                "dcmNo": m.group(1),
                "eleId": "0", "offset": "0", "length": "0",
                "dtd":  "dart3.xsd",
            }

        # ── 전략 3: frame/iframe src에서 dcmNo 탐색 (구형 프레임셋) ──
        try:
            from lxml import html as lxml_html
            tree = lxml_html.fromstring(text.encode("utf-8", errors="replace"))
            for elem in tree.iter("frame", "iframe"):
                src = elem.get("src", "")
                m = re.search(r"dcmNo=(\d{4,})", src)
                if m:
                    dtd_m = re.search(r"dtd=([^&]+)", src)
                    dtd   = dtd_m.group(1) if dtd_m else "dart3.xsd"
                    logger.debug("    [legacy] frame src에서 dcmNo 추출")
                    return {
                        "dcmNo": m.group(1),
                        "eleId": "0", "offset": "0", "length": "0",
                        "dtd":  dtd,
                    }
        except Exception:
            pass

        logger.debug(f"    [legacy] 모든 전략 실패. 응답 크기={len(text):,}chars")
        return None

    def _fetch_html(self, rcept_no: str, params: dict) -> Optional[bytes]:
        """
        뷰어 본문 HTML 다운로드.
        eleId/offset/length는 viewDoc에서 추출한 실제 값을 사용.
        메인 페이지에서 취득한 세션 쿠키가 httpx.Client에 유지됨.
        """
        resp = self._get(
            f"{DART_WEB_BASE}/report/viewer.do",
            {
                "rcpNo":  rcept_no,
                "dcmNo":  params["dcmNo"],
                "eleId":  params["eleId"],
                "offset": params["offset"],
                "length": params["length"],
                "dtd":    params["dtd"],
            },
        )
        return resp.content if resp else None
