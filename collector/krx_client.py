"""KRX OpenAPI (data.krx.co.kr) 클라이언트 — 상장 종목 마스터.

왜 필요한가:
  상장 유니버스의 1차 소스가 그동안 FinanceDataReader 스크래핑이었다. 비인증 스크래퍼라
  언제 막혀도 이상하지 않고(pykrx 는 이미 차단됨), **그 소스가 상장폐지 판정의 유일한 근거**다.
  KRX 공식 OpenAPI 는 인증키 기반이라 실패가 명시적(401)이고, 우선주 구분·상장일·상장주식수
  같은 필드를 덤으로 준다.

⚠️ 이 API 의 함정 — **HTTP 200 + 0건**:
  · `basDd` 를 안 주면 200 에 빈 목록이 온다
  · 당일(장 마감 전/데이터 미공표)도 200 에 빈 목록이 온다
  이를 정상으로 받으면 **그 시장 전체가 상장폐지로 오인**된다(KOSPI 943개). 그래서 이 모듈은
  빈 목록을 **실패로 취급**하고, 직전 영업일로 최대 `MAX_LOOKBACK_DAYS` 만큼 거슬러 재시도한다.
  (주말 날짜를 주면 KRX 가 알아서 직전 영업일 데이터를 준다.)

⚠️ 서비스별 구독 만료:
  KRX OpenAPI 는 API 별로 활용신청·승인이 필요하고 **기간이 있다**(2026-07-31 기준 유가증권
  1개월·코스닥 1년). 만료되면 `Unauthorized API Call` 이 온다. 이때도 실패로 보고해
  `sync_corporations` 가 비활성 처리를 건너뛰게 해야 한다(그 시장 전체 오탐 방지).

인증: `AUTH_KEY` 헤더. (다른 헤더명은 `Unauthorized Key` 를 돌려준다.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import requests
from loguru import logger

# .env 로드는 collector.config 가 담당한다. 이 모듈만 단독으로 import 되는 경우
# (스크립트·테스트)에도 KRX_API_KEY 가 보이도록 여기서 한 번 끌어온다.
import collector.config  # noqa: F401

BASE_URL = "http://data-dbg.krx.co.kr/svc/apis"

# 시장 → 종목기본정보 엔드포인트
ENDPOINTS = {
    "KOSPI":  "/sto/stk_isu_base_info",
    "KOSDAQ": "/sto/ksq_isu_base_info",
}

PAYLOAD_KEY = "OutBlock_1"
TIMEOUT = 30
MAX_LOOKBACK_DAYS = 10      # 연휴 대비(설·추석 최대 ~5영업일 + 여유)


class KrxUnavailable(RuntimeError):
    """이 시장 목록을 신뢰할 수 없다. 호출자는 **비활성 처리를 건너뛰어야** 한다."""


@dataclass
class MarketListing:
    """한 시장의 조회 결과."""
    market: str
    bas_dd: Optional[str] = None            # 실제로 데이터를 얻은 기준일
    rows: list[dict] = field(default_factory=list)
    error: Optional[str] = None             # None 이면 성공

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.rows)


def _api_key() -> str:
    key = os.getenv("KRX_API_KEY", "").strip()
    if not key:
        raise KrxUnavailable("KRX_API_KEY 미설정(.env)")
    return key


def _get(path: str, bas_dd: str) -> list[dict]:
    """단일 호출. 실패는 KrxUnavailable."""
    try:
        r = requests.get(BASE_URL + path,
                         headers={"AUTH_KEY": _api_key()},
                         params={"basDd": bas_dd},
                         timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise KrxUnavailable(f"네트워크 오류: {type(exc).__name__}: {exc}") from exc

    if r.status_code == 401:
        msg = (r.text or "")[:120]
        if "Unauthorized Key" in msg:
            raise KrxUnavailable("인증키가 유효하지 않다(KRX_API_KEY 확인)")
        # 'Unauthorized API Call' = 키는 유효하나 이 서비스 미승인/기간 만료
        raise KrxUnavailable(
            f"서비스 미승인 또는 활용기간 만료 — data.krx.co.kr 에서 재신청 필요 ({msg})")
    if r.status_code != 200:
        raise KrxUnavailable(f"HTTP {r.status_code}: {(r.text or '')[:120]}")

    try:
        payload = r.json()
    except ValueError as exc:
        raise KrxUnavailable(f"JSON 파싱 실패: {(r.text or '')[:120]}") from exc

    rows = payload.get(PAYLOAD_KEY)
    if rows is None:
        raise KrxUnavailable(f"예상 키 '{PAYLOAD_KEY}' 없음: {list(payload)[:5]}")
    return rows


def fetch_listing(market: str, bas_dd: Optional[str] = None) -> MarketListing:
    """시장별 상장 종목 마스터. 빈 목록은 실패로 보고 직전 영업일로 거슬러 재시도한다.

    Args:
        market: "KOSPI" | "KOSDAQ"
        bas_dd: YYYYMMDD. 생략하면 어제부터 거슬러 올라간다(당일은 미공표라 0건).
    """
    path = ENDPOINTS.get(market)
    if path is None:
        return MarketListing(market, error=f"알 수 없는 시장: {market}")

    # 당일은 데이터가 아직 없다 → 기본 시작점은 어제.
    start = (date.today() - timedelta(days=1) if bas_dd is None
             else date(int(bas_dd[:4]), int(bas_dd[4:6]), int(bas_dd[6:8])))

    last_err: Optional[str] = None
    for back in range(MAX_LOOKBACK_DAYS):
        d = (start - timedelta(days=back)).strftime("%Y%m%d")
        try:
            rows = _get(path, d)
        except KrxUnavailable as exc:
            # 인증·구독 문제는 날짜를 바꿔도 소용없다 → 즉시 중단
            return MarketListing(market, bas_dd=d, error=str(exc))
        if rows:
            if back:
                logger.debug(f"[krx] {market}: {d} 로 {back}일 거슬러 조회 성공")
            return MarketListing(market, bas_dd=d, rows=rows)
        last_err = f"빈 목록(HTTP 200) — {d}"

    return MarketListing(
        market,
        error=f"{MAX_LOOKBACK_DAYS}일 거슬러도 빈 목록 (마지막: {last_err}). "
              f"데이터 미공표이거나 서비스 이상 — 비활성 처리 금지",
    )


def is_common_stock(row: dict) -> bool:
    """보통주 주권만 채택. 우선주·신주인수권·ETF 등 제외.

    KRX 는 `KIND_STKCERT_TP_NM` 에 '보통주'/'우선주' 를, `SECUGRP_NM` 에 '주권' 을 준다.
    (기존 FDR 경로는 DART corpCode.xml 매핑 실패로 우선주가 '자동 제외'되는 간접 방식이었다.
     여기서는 소스가 직접 알려주므로 명시적으로 거른다.)
    """
    return (row.get("KIND_STKCERT_TP_NM") == "보통주"
            and row.get("SECUGRP_NM") == "주권")


def to_universe(listings: list[MarketListing]) -> dict[str, str]:
    """성공한 시장들의 보통주 → {stock_code: market}."""
    universe: dict[str, str] = {}
    for lst in listings:
        if not lst.ok:
            continue
        for row in lst.rows:
            if not is_common_stock(row):
                continue
            code = (row.get("ISU_SRT_CD") or "").strip()
            if len(code) == 6:
                universe[code] = lst.market
    return universe


def fetch_all(bas_dd: Optional[str] = None) -> tuple[dict[str, str], dict[str, MarketListing]]:
    """전 시장 조회. 반환: (universe, {market: MarketListing})

    **부분 실패를 숨기지 않는다** — 호출자가 시장별 성공 여부를 보고
    비활성 처리 여부를 결정해야 한다(그 시장 전체가 상장폐지로 오인되는 것 방지).
    """
    results = {m: fetch_listing(m, bas_dd) for m in ENDPOINTS}
    for m, lst in results.items():
        if lst.ok:
            n_common = sum(1 for r in lst.rows if is_common_stock(r))
            logger.info(f"  KRX {m}: 전체 {len(lst.rows):,} · 보통주 {n_common:,} (기준일 {lst.bas_dd})")
        else:
            logger.error(f"  KRX {m}: 실패 — {lst.error}")
    return to_universe(list(results.values())), results
