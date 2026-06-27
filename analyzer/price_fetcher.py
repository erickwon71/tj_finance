"""
주가 / 시가총액 수집

주가:   pykrx → Naver Finance (get_market_ohlcv) ← 항상 동작
상장주식수: DART OpenAPI (stockTotqySttus) ← corp_code 필요
시가총액: 종가 × 상장주식수 로 계산

사용 예:
    from analyzer.price_fetcher import get_market_data

    data = get_market_data("005930", as_of_date=date(2024, 12, 31),
                           corp_code="00126380", fiscal_year=2024)
    # → {"market_cap": 324_756_170_720_000, "close_price": 54400,
    #    "shares_out": 5_969_782_550, "trade_date": date(2025, 1, 3)}
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional
from loguru import logger


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def get_market_data(
    stock_code: str,
    as_of_date: Optional[date] = None,
    corp_code: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    use_cache: bool = True,
) -> Optional[dict]:
    """
    종목코드(6자리)와 기준일로 시가총액/주가 반환.

    1순위: stock_prices 테이블 캐시 (market_cap != NULL 조건)
    2순위: pykrx(Naver) 주가 + DART 상장주식수 → 계산

    Args:
        stock_code:  KRX 6자리 종목코드 (예: "005930")
        as_of_date:  기준일. None이면 오늘
        corp_code:   DART 8자리 기업코드. 상장주식수 조회에 사용.
                     None이면 DB에서 자동 조회.
        fiscal_year: 상장주식수 기준 사업연도. None이면 as_of_date 연도
        use_cache:   DB 캐시 사용 여부

    Returns:
        dict: market_cap, close_price, shares_out, trade_date
        조회 실패 시 None
    """
    if as_of_date is None:
        as_of_date = date.today()

    # 캐시: market_cap이 있는 레코드 우선 조회
    if use_cache:
        cached = _load_from_cache(stock_code, as_of_date)
        if cached and cached.get("market_cap"):
            return cached

    # corp_code 없으면 DB에서 조회
    if not corp_code:
        corp_code = _lookup_corp_code(stock_code)

    return _fetch_live(stock_code, as_of_date, corp_code, fiscal_year)


# ---------------------------------------------------------------------------
# 주가 조회 (pykrx → Naver Finance)
# ---------------------------------------------------------------------------

def _fetch_close_price(stock_code: str, target_date: date):
    """종가와 실제 거래일 반환. 실패 시 (None, None)."""
    try:
        from pykrx import stock as krx  # type: ignore[import]

        start = (target_date - timedelta(days=15)).strftime("%Y%m%d")
        end   = (target_date + timedelta(days=5)).strftime("%Y%m%d")

        df = krx.get_market_ohlcv(start, end, stock_code)
        if df is None or df.empty:
            return None, None

        # target_date 이전 마지막 거래일 우선
        before = df[df.index.date <= target_date]
        if not before.empty:
            row = before.iloc[-1]
            trade_dt = before.index[-1].date()
        else:
            row = df.iloc[-1]
            trade_dt = df.index[-1].date()

        close = int(row.get("종가", row.get("Close", 0)))
        return close, trade_dt

    except Exception as e:
        logger.debug(f"주가 조회 오류 [{stock_code}]: {e}")
        return None, None


# ---------------------------------------------------------------------------
# 상장주식수 조회 (DART OpenAPI)
# ---------------------------------------------------------------------------

def get_shares_from_dart(corp_code: str, fiscal_year: int) -> Optional[int]:
    """
    DART stockTotqySttus API로 보통주 상장주식수 조회.

    Returns:
        보통주 istc_totqy (상장주식 총수) or None
    """
    try:
        import requests
        from collector.config import DART_API_KEY

        if not DART_API_KEY:
            return None

        url = "https://opendart.fss.or.kr/api/stockTotqySttus.json"
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code":  corp_code,
            "bsns_year":  str(fiscal_year),
            "reprt_code": "11011",  # 사업보고서
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "000" or not data.get("list"):
            # 사업보고서 없으면 반기 시도
            params["reprt_code"] = "11012"
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

        if data.get("status") != "000" or not data.get("list"):
            return None

        # 보통주 행 탐색
        for item in data["list"]:
            se = item.get("se", "")
            if "보통주" in se or se == "합계":
                raw = item.get("istc_totqy", "0")
                shares = int(re.sub(r"[^0-9]", "", raw) or "0")
                if shares > 0:
                    return shares

        return None

    except Exception as e:
        logger.debug(f"DART 상장주식수 조회 오류 [{corp_code}/{fiscal_year}]: {e}")
        return None


# ---------------------------------------------------------------------------
# 메인 조회 로직
# ---------------------------------------------------------------------------

def _fetch_live(
    stock_code: str,
    target_date: date,
    corp_code: Optional[str],
    fiscal_year: Optional[int],
) -> Optional[dict]:
    """pykrx 주가 + DART 상장주식수 → 시총 계산 후 캐시 저장."""

    close, trade_dt = _fetch_close_price(stock_code, target_date)
    if close is None:
        logger.debug(f"주가 없음: {stock_code} @ {target_date}")
        return None

    # 상장주식수: DART API
    shares_out = None
    market_cap  = None

    if corp_code:
        fy = fiscal_year or target_date.year
        shares_out = get_shares_from_dart(corp_code, fy)
        # 연말 결산 기준 상장주식수가 없으면 전년도 시도
        if not shares_out and fy > 2000:
            shares_out = get_shares_from_dart(corp_code, fy - 1)

    if shares_out:
        market_cap = close * shares_out

    result = {
        "market_cap":  market_cap,
        "close_price": close,
        "shares_out":  shares_out,
        "trade_date":  trade_dt,
    }

    _save_to_cache(stock_code, trade_dt, result)
    return result


# ---------------------------------------------------------------------------
# DB 캐시 헬퍼
# ---------------------------------------------------------------------------

def _load_from_cache(stock_code: str, target_date: date) -> Optional[dict]:
    """stock_prices 테이블에서 조회 (±7일 이내, 가장 가까운 날)."""
    try:
        from sqlalchemy import text
        from collector.db import get_session

        with get_session() as session:
            row = session.execute(text("""
                SELECT close_price, market_cap, shares_out, trade_date
                FROM stock_prices
                WHERE stock_code = :code
                  AND trade_date BETWEEN :start AND :end
                ORDER BY ABS(CAST(trade_date AS DATE) - CAST(:target AS DATE)) ASC
                LIMIT 1
            """), {
                "code":   stock_code,
                "start":  target_date - timedelta(days=7),
                "end":    target_date + timedelta(days=7),
                "target": target_date.isoformat(),
            }).fetchone()

        if row:
            return {
                "market_cap":  row.market_cap,
                "close_price": row.close_price,
                "shares_out":  row.shares_out,
                "trade_date":  row.trade_date,
            }
    except Exception as e:
        logger.debug(f"캐시 조회 오류 [{stock_code}]: {e}")

    return None


def _save_to_cache(stock_code: str, trade_date: date, data: dict) -> None:
    """주가 데이터를 stock_prices 테이블에 저장."""
    try:
        from sqlalchemy import text
        from collector.db import get_session

        with get_session() as session:
            session.execute(text("""
                INSERT INTO stock_prices (stock_code, trade_date, close_price, market_cap, shares_out)
                VALUES (:code, :dt, :price, :cap, :shares)
                ON CONFLICT (stock_code, trade_date) DO UPDATE
                    SET close_price = EXCLUDED.close_price,
                        market_cap  = COALESCE(EXCLUDED.market_cap, stock_prices.market_cap),
                        shares_out  = COALESCE(EXCLUDED.shares_out, stock_prices.shares_out)
            """), {
                "code":   stock_code,
                "dt":     trade_date,
                "price":  data.get("close_price"),
                "cap":    data.get("market_cap"),
                "shares": data.get("shares_out"),
            })
    except Exception as e:
        logger.debug(f"주가 캐시 저장 오류: {e}")


def _lookup_corp_code(stock_code: str) -> Optional[str]:
    """DB의 corporations 테이블에서 stock_code → corp_code 조회."""
    try:
        from sqlalchemy import text
        from collector.db import get_session

        with get_session() as session:
            row = session.execute(text("""
                SELECT corp_code FROM corporations
                WHERE stock_code = :code LIMIT 1
            """), {"code": stock_code}).fetchone()

        return row.corp_code if row else None
    except Exception as e:
        logger.debug(f"corp_code 조회 오류 [{stock_code}]: {e}")
        return None


# ---------------------------------------------------------------------------
# 일괄 주가 수집 (sync-prices 명령어)
# ---------------------------------------------------------------------------

def sync_prices(
    corp_codes: Optional[list] = None,
    since_year: int = 2015,
) -> int:
    """
    DB의 기업들에 대해 결산일 기준 주가/시총을 일괄 수집.

    Returns:
        저장된 행 수
    """
    from sqlalchemy import text
    from collector.db import get_session

    sql = """
        SELECT DISTINCT c.corp_code, c.stock_code, sf.period_end,
               sf.fiscal_year
        FROM standard_financials sf
        JOIN corporations c ON c.corp_code = sf.corp_code
        WHERE c.stock_code IS NOT NULL
          AND sf.fiscal_year >= :since
          AND sf.period_end IS NOT NULL
          AND sf.fiscal_period = 'FY'
        ORDER BY sf.period_end DESC
    """
    with get_session() as session:
        targets = session.execute(text(sql), {"since": since_year}).fetchall()

    logger.info(f"주가 수집 대상: {len(targets)}건")
    saved = 0

    for row in targets:
        if corp_codes and row.corp_code not in corp_codes:
            continue
        result = get_market_data(
            row.stock_code,
            as_of_date=row.period_end,
            corp_code=row.corp_code,
            fiscal_year=row.fiscal_year,
        )
        if result and result.get("market_cap"):
            saved += 1
        if saved % 50 == 0 and saved > 0:
            logger.info(f"  주가 수집 {saved}/{len(targets)}")

    logger.success(f"주가 수집 완료: {saved}건 저장")
    return saved


# ---------------------------------------------------------------------------
# Daily full-history bulk sync (OHLCV + market cap/shares + fundamentals)
# ---------------------------------------------------------------------------

def _to_int(v):
    """pandas/numpy scalar → int or None (NaN-safe)."""
    import math
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None


def _pos_int(v):
    """Positive int or None. KRX 는 거래정지일에 시/고/저를 0 으로 채움(종가=정지 기준가).
    가격 0 은 무의미 → None 으로 둔다(거래량 0 은 사실이라 보존)."""
    n = _to_int(v)
    return n if (n is not None and n > 0) else None


def _pykrx_df(fn, *args):
    """Call a pykrx *_by_date function with one retry; return non-empty DataFrame or None."""
    for attempt in range(2):
        try:
            df = fn(*args)
            if df is not None and not df.empty:
                return df
            return None
        except Exception as e:  # transient throttle / network
            logger.debug(f"pykrx {getattr(fn, '__name__', fn)} 재시도{attempt} [{args}]: {e}")
    return None


def sync_corp_daily(stock_code: str, start: str, end: str) -> int:
    """
    한 종목의 [start, end] 일별 OHLCV(시/고/저/종/거래량)를 pykrx 로 수집해 stock_prices 에
    멱등 upsert. 반환 = 적재(또는 갱신)된 행 수. start/end = "YYYYMMDD".

    ⚠ 시총·펀더멘탈(PER/PBR/EPS/BPS/DIV/DPS)은 **수집하지 않는다**: KRX 의 market_cap/
    fundamental 엔드포인트가 (pykrx 최신판에서도) 빈 응답으로 구조적 breakage 상태. 해당 지표는
    후속 '재무↔주가 결합' 단계에서 검증 재무 DB(종가×주식수, controlling_ni/equity 등)로 파생한다.
    그 컬럼들(market_cap/shares_out/per/pbr/eps/bps/div_yield/dps)은 여기서 건드리지 않아
    기존 값(FY 스냅샷·후속 파생)을 보존한다.
    """
    from pykrx import stock as krx
    from sqlalchemy import text
    from collector.db import get_session

    ohlcv = _pykrx_df(krx.get_market_ohlcv_by_date, start, end, stock_code)
    if ohlcv is None:
        return 0  # 해당 구간 거래이력 없음(상장 전/폐지 등)

    rows = []
    for idx, o in ohlcv.iterrows():
        close = _to_int(o.get("종가"))
        if not close or close <= 0:
            continue  # close_price 는 NOT NULL — 종가 없는 행은 스킵
        trade_dt = idx.date() if hasattr(idx, "date") else idx
        rows.append({
            "code": stock_code, "dt": trade_dt,
            "open": _pos_int(o.get("시가")), "high": _pos_int(o.get("고가")),
            "low": _pos_int(o.get("저가")), "close": close,
            "volume": _to_int(o.get("거래량")),
        })

    return _upsert_ohlcv(rows)


def _upsert_ohlcv(rows: list[dict]) -> int:
    """OHLCV 행(code/dt/open/high/low/close/volume) stock_prices 멱등 upsert. 반환=행수."""
    from sqlalchemy import text
    from collector.db import get_session
    if not rows:
        return 0
    with get_session() as session:
        session.execute(text("""
            INSERT INTO stock_prices
                (stock_code, trade_date, open_price, high_price, low_price, close_price, volume)
            VALUES
                (:code, :dt, :open, :high, :low, :close, :volume)
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price  = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume     = EXCLUDED.volume
        """), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Naver Finance siseJson — 심화 이력(상장~현재) 일별 수정주가 OHLCV
#   KRX(pykrx)/koapy 가 pre-2014 를 못 줘서(2014 floor / MDCSTAT LOGOUT) 대체 소스.
#   반환값은 **수정주가**(액면분할 등 보정, 현재 기준) — 기존 pykrx 수집과 동일 basis.
#   상장주식수·시총은 미제공 → std_v2 주식수 timeline 으로 파생(fin2_market_cap_daily).
# ---------------------------------------------------------------------------

def fetch_naver_daily(stock_code: str, start: str, end: str) -> list[dict]:
    """Naver siseJson 일별 OHLCV. start/end='YYYYMMDD'. 행 dict 목록(code 제외)."""
    import ast
    import requests
    url = "https://api.finance.naver.com/siseJson.naver"
    params = {"symbol": stock_code, "requestType": "1",
              "startTime": start, "endTime": end, "timeframe": "day"}
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"})
    except Exception as e:
        logger.debug(f"naver 요청 오류 [{stock_code}]: {e}")
        return []
    if r.status_code != 200 or not r.text.strip():
        return []
    try:
        raw = ast.literal_eval(r.text.strip())  # 헤더 작은따옴표·데이터 큰따옴표 모두 허용
    except Exception as e:
        logger.debug(f"naver 파싱 오류 [{stock_code}]: {e}")
        return []
    out = []
    for row in raw[1:]:  # [0]=헤더
        if not row or len(row) < 6:
            continue
        d, o, h, l, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
        try:
            trade_dt = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
            close = int(c)
        except (ValueError, TypeError, IndexError):
            continue
        if close <= 0:
            continue
        out.append({"dt": trade_dt, "open": _pos_int(o), "high": _pos_int(h),
                    "low": _pos_int(l), "close": close, "volume": _to_int(v)})
    return out


def sync_corp_daily_naver(stock_code: str, start: str, end: str) -> int:
    """한 종목 [start,end] 일별 OHLCV(Naver 수정주가) → stock_prices 멱등 upsert. 반환=행수."""
    rows = fetch_naver_daily(stock_code, start, end)
    for r in rows:
        r["code"] = stock_code
    return _upsert_ohlcv(rows)
