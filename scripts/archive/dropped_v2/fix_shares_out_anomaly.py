"""P0-3 · shares_out 10^6 과다저장 교정 (외부평가 2026-07-15).

일부 최근상장 기업의 `std_financials_v2.shares_out` 이 실제 발행주식수의 **정확히 10^6배**로
저장돼 있다(예: 소프트캠프 258790 = 24,991,284,000,000, 실제 ≈2,499만주). 이 값은
`fin2_market_cap_daily.py` 가 `stock_prices.shares_out`·`market_cap = close × shares` 로 그대로
증폭시켜, 시총·PER/PBR 을 천문학적 수치로 왜곡한다(LS에코에너지 시총 1,463,869조 등).

이 스크립트는 **권위 있는 상장주식수(pykrx get_market_cap 의 '상장주식수')와 대조**해 10^6 배
관계가 확인된 corp 만 교정한다(무분별한 ÷10^6 방지). 교정 후 fin2_market_cap_daily.run() 을
호출해 stock_prices·market_cap 에 전파한다. 멱등.

usage:
  python scripts/fix_shares_out_anomaly.py --dry-run        # 진단만(기본)
  python scripts/fix_shares_out_anomaly.py --apply          # 실제 교정 + 시총 재전파
  python scripts/fix_shares_out_anomaly.py --apply --stock 229640 258790
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

# 외부평가에서 확인된 대상(기본). --stock 으로 재정의 가능.
_DEFAULT_TARGETS = ["229640", "258790"]
_FACTOR = 1_000_000          # 관측된 과다 배율(10^6)
_TOL = 0.02                  # 배율 판정 허용오차(2%) — stored/auth 가 10^6±2% 여야 교정
# 물리적 상한: KOSPI/KOSDAQ 최다주식(삼성전자 ~60억주)도 10^10 미만. 10^11 초과는 불가값.
# 권위 소스(DART/pykrx)가 모두 불가할 때의 안전 폴백 판정에 사용.
_IMPOSSIBLE_SHARES = 100_000_000_000   # 10^11
_PLAUSIBLE_MAX = 10_000_000_000        # 10^10 (÷10^6 결과가 이보다 작아야 정상)


def _authoritative_shares(corp_code: str, stock_code: str, fiscal_year: int | None) -> int | None:
    """권위 있는 발행주식수. 1순위 DART stockTotqySttus, 2순위 pykrx get_market_cap. 실패 시 None."""
    # 1순위: DART(신뢰·단일콜). 최신 FY 부터 2년 역순 시도.
    from analyzer.price_fetcher import get_shares_from_dart
    for fy in [y for y in (fiscal_year, (fiscal_year or date.today().year) - 1) if y]:
        n = get_shares_from_dart(corp_code, fy)
        if n and n > 0:
            return n
    # 2순위: pykrx '상장주식수'(KRX market_cap 엔드포인트는 breakage 가능 — 폴백).
    try:
        from pykrx import stock as krx
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=15)).strftime("%Y%m%d")
        df = krx.get_market_cap(start, end, stock_code)
        if df is not None and not df.empty and "상장주식수" in df.columns:
            val = int(df["상장주식수"].iloc[-1])
            return val if val > 0 else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[fix-shares] pykrx 폴백 실패 {stock_code}: {type(e).__name__}: {e}")
    return None


def _stored_latest(session, stock_code: str) -> tuple[str | None, int | None, int | None]:
    """(corp_code, 최신 FY std_financials_v2.shares_out, fiscal_year)."""
    row = session.execute(text(
        "SELECT c.corp_code, f.shares_out, f.fiscal_year "
        "FROM std_financials_v2 f JOIN corporations c USING (corp_code) "
        "WHERE c.stock_code = :sc AND f.version = 1 AND f.shares_out IS NOT NULL "
        "ORDER BY f.fiscal_year DESC, f.shares_out DESC LIMIT 1"),
        {"sc": stock_code}).fetchone()
    return (row[0], row[1], row[2]) if row else (None, None, None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", nargs="*", default=_DEFAULT_TARGETS, help="대상 종목코드(6자리)")
    ap.add_argument("--apply", action="store_true", help="실제 교정(미지정 시 진단만)")
    args = ap.parse_args()
    apply = args.apply

    corrected: list[str] = []
    with get_session() as s:
        for sc in args.stock:
            corp_code, stored, fy = _stored_latest(s, sc)
            if corp_code is None or stored is None:
                logger.info(f"[fix-shares] {sc}: std_financials_v2 shares_out 없음 — 스킵")
                continue
            auth = _authoritative_shares(corp_code, sc, fy)
            if auth is not None:
                ratio = stored / auth
                ok = abs(ratio - _FACTOR) <= _FACTOR * _TOL
                logger.info(f"[fix-shares] {sc}({corp_code}): stored={stored:,} auth={auth:,} "
                            f"ratio={ratio:,.1f} {'→ 10^6 과다 확인' if ok else '→ 배율 불일치(스킵)'}")
                thr = auth * _FACTOR // 2
            else:
                # 권위 소스 불가(DART 쿼터소진·pykrx breakage) → 물리적 불가 + 10^6 정합 폴백.
                #   ① stored 가 물리적 불가(>10^11)  ② 10^6 로 나누어떨어짐  ③ 결과가 물리적 가능(<10^10)
                ok = (stored > _IMPOSSIBLE_SHARES and stored % _FACTOR == 0
                      and (stored // _FACTOR) < _PLAUSIBLE_MAX)
                logger.info(f"[fix-shares] {sc}({corp_code}): 권위조회 불가 → 물리적 폴백 판정 · "
                            f"stored={stored:,} ÷10^6={stored // _FACTOR:,} "
                            f"{'→ 불가값·10^6정합 확인' if ok else '→ 폴백조건 불충족(스킵·수동확인)'}")
                thr = _IMPOSSIBLE_SHARES
            if not ok:
                continue
            if not apply:
                # dry-run: 영향 행수만 집계
                n = s.execute(text(
                    "SELECT count(*) FROM std_financials_v2 "
                    "WHERE corp_code = :cc AND version = 1 AND shares_out IS NOT NULL "
                    "AND shares_out >= :thr"),
                    {"cc": corp_code, "thr": thr}).scalar()
                logger.info(f"[fix-shares]   (dry-run) 교정 대상 {n} 행 — --apply 로 실행")
                continue
            # 교정: 과다(≈×10^6) 행만 ÷10^6. 정상 저장된 행은 건드리지 않음.
            res = s.execute(text(
                "UPDATE std_financials_v2 SET shares_out = shares_out / :f "
                "WHERE corp_code = :cc AND version = 1 AND shares_out IS NOT NULL "
                "AND shares_out >= :thr"),
                {"f": _FACTOR, "cc": corp_code, "thr": thr})
            logger.success(f"[fix-shares]   {sc}: {res.rowcount} 행 ÷{_FACTOR:,} 교정")
            corrected.append(sc)

    if apply and corrected:
        logger.info(f"[fix-shares] 시총 재전파(fin2_market_cap_daily) — 대상 {corrected}")
        from scripts.fin2_market_cap_daily import run as market_cap_run
        for sc in corrected:
            market_cap_run(stock=sc)
        logger.success("[fix-shares] 완료 — stock_prices.shares_out·market_cap 재전파됨")
    elif not apply:
        logger.info("[fix-shares] 진단 완료(변경 없음). 실제 교정은 --apply")


if __name__ == "__main__":
    main()
