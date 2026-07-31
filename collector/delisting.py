"""상장폐지 판정 엔진 — 소스 신뢰도 게이트 + 상태기계.

계획: docs/plans/collection_pipeline_restore_2026-07-31.md §6

왜 이렇게까지 하나
──────────────────
기존 판정은 `corp_collector.py` 의 한 줄이 전부였다:

    to_deactivate = [c for c in existing_active if c not in final_codes]

"이번 조회 목록에 없으면 비활성." 그런데 목록에서 빠지는 경로는 4가지고(진짜 상장폐지 /
조회 실패 / DART 매핑 실패 / 필터 변경) 전부 똑같이 처리됐다. 여기에 파일 삭제를 연결했다면
**일시적 조회 실패 한 번으로 원문이 영구 삭제**된다.

그래서 판정을 두 층으로 나눈다:
  · **G0 계열** — 소스를 믿을 수 있나? 못 믿으면 그날 판정 전체를 스킵한다.
  · **G1~G4** — 이 기업이 정말 빠졌나? 단일 신호로는 확정하지 않는다.

`is_active` 는 KRX 관측 사실 그대로 두고(corp_collector 소관), 파일 아카이브 같은 **조치
판단은 오직 `delisting_status`** 가 한다. 두 개념을 분리해야 오탐이 원문에 손대지 못한다.

상태기계
────────
    NULL ──(목록 부재 첫 관측)──> candidate
    candidate ──(G1~G4 통과)──> confirmed ──> 원문 NAS 아카이브(수동 명령)
    candidate|confirmed ──(목록 재등장)──> reinstated
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

# ── 게이트 임계값 ───────────────────────────────────────────────────
MIN_DAYS_ABSENT = 10          # G1 — 영업일 기준 연속 부재
MARKET_SHRINK_LIMIT = 0.05    # G0b — 시장별 목록 -5% 이상 감소면 스킵
PRICE_STALE_DAYS = 10         # G2ⓑ — 신규 시세 없음 판정(영업일)

# G3 — 하루 confirmed 전환 상한. **두 경로의 실패 양상이 달라 따로 둔다.**
#   · 추론 경로(부재+교차신호): 조회 이상이 대량 오탐으로 번질 수 있다 → 5건으로 조인다.
#   · 명부 경로(폐지일·사유 명시): 오탐이 나려면 명부가 **없는 폐지를 지어내야** 한다.
#     대신 명부 자체의 오염을 REGISTRY_MAX_SHARE 로 본다.
DAILY_CONFIRM_CAP = 5
DAILY_CONFIRM_CAP_REGISTRY = 20

# 명부 경로 sanity — 우리 기업 중 이번에 폐지 명부에 걸린 비율이 이보다 크면 명부를
# 신뢰하지 않고 경로를 통째로 비활성화한다(추론 경로로 자연 폴백).
# 실측 2026-07-31: 12/2,545 = 0.47%. 월 20건이 넘어도 1% 미만이다.
REGISTRY_MAX_SHARE = 0.02

# G2ⓐ — 상장폐지를 시사하는 시장조치 키워드
DELISTING_EVENT_KEYWORDS = ("상장폐지", "정리매매", "상장적격성", "폐지결정", "폐지사유")


@dataclass
class Verdict:
    corp_code: str
    corp_name: str
    status: str                       # candidate | confirmed | reinstated | hold
    reason: str
    days_absent: Optional[int] = None
    signals: list[str] = field(default_factory=list)


def _business_days_between(a: date, b: date) -> int:
    """a~b 사이 영업일 수(주말만 제외 — 공휴일은 보수적으로 미반영해 더 오래 기다린다)."""
    if b <= a:
        return 0
    days = 0
    cur = a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


# ── G0: 소스 신뢰도 ─────────────────────────────────────────────────

def check_source_trust(market_status: dict, krx_mode: bool) -> tuple[bool, str]:
    """그날 판정을 진행해도 되는지. 반환 (진행가능, 사유).

    G0a  시장별 조회가 하나라도 실패(두 소스 모두)면 스킵
    G0b  시장별 목록 크기가 직전 성공 대비 -5% 이상 감소면 스킵
    G0c  DART 단독 모드면 스킵 (상장폐지 기업을 걸러내지 못하는 모드)
    """
    if not krx_mode:
        return False, "G0c: DART 단독 모드 — 상장폐지 기업을 걸러내지 못하므로 판정 근거가 없다"

    dead = [m for m, st in market_status.items() if st.get("used") is None]
    if dead:
        return False, (f"G0a: {', '.join(dead)} 조회 실패(KRX·FDR 모두) — "
                       f"그 시장 전체가 상장폐지로 오인될 수 있다")

    # G0b — 직전 성공 실행의 시장별 크기와 비교
    with get_session() as s:
        for market, st in market_status.items():
            now_n = st.get("count") or 0
            prev = s.execute(text("""
                SELECT krx_market_size FROM delisting_audit
                WHERE verdict = 'source_ok' AND krx_market_ok LIKE :m
                  AND krx_market_size IS NOT NULL
                ORDER BY checked_at DESC LIMIT 1
            """), {"m": f"%{market}:%"}).scalar()
            if prev and now_n < prev * (1 - MARKET_SHRINK_LIMIT):
                return False, (f"G0b: {market} 목록이 {prev:,} → {now_n:,} "
                               f"({(now_n/prev - 1):.1%}) 급감 — 조회 이상 의심")
    return True, "ok"


# ── G2: 교차 신호 ───────────────────────────────────────────────────

def _cross_signals(session, corp_code: str, stock_code: Optional[str]) -> list[str]:
    """상장폐지를 뒷받침하는 독립 신호. 하나라도 있어야 confirmed 가 된다."""
    signals: list[str] = []

    # ⓐ 시장조치 이벤트
    row = session.execute(text("""
        SELECT report_nm FROM regulatory_events
        WHERE corp_code = :c AND filed_at >= current_date - 180
        ORDER BY filed_at DESC
    """), {"c": corp_code}).fetchall()
    for (nm,) in row:
        if any(k in (nm or "") for k in DELISTING_EVENT_KEYWORDS):
            signals.append(f"규제이벤트: {nm.strip()[:60]}")
            break

    # ⓑ 신규 시세 없음
    if stock_code:
        last_px = session.execute(text(
            "SELECT max(trade_date) FROM stock_prices WHERE stock_code = :s"),
            {"s": stock_code}).scalar()
        if last_px is None:
            signals.append("시세 이력 없음")
        elif _business_days_between(last_px, date.today()) >= PRICE_STALE_DAYS:
            signals.append(f"신규 시세 없음(마지막 {last_px})")

    # ⓒ 최근 정기공시 없음 — 상장사는 분기마다 제출한다. 200일 넘게 없으면 이상.
    last_filing = session.execute(text(
        "SELECT max(filed_at) FROM filings WHERE corp_code = :c"), {"c": corp_code}).scalar()
    if last_filing and (date.today() - last_filing).days > 200:
        signals.append(f"정기공시 없음(마지막 {last_filing})")

    return signals


# ── 판정 ────────────────────────────────────────────────────────────

def evaluate(listed: set, market_status: dict, krx_mode: bool,
             apply: bool = False, delisted_registry: Optional[dict] = None) -> dict:
    """상장 목록 대비 상장폐지 상태를 판정한다.

    Args:
        listed:        **거래소에 상장된 전 증권**의 종목코드 집합
                       (`krx_client.listed_codes()`). 우리 투자 유니버스(보통주만)가
                       **아니다** — 그걸 쓰면 KRX 에 멀쩡히 상장된 인프라펀드·리츠가
                       상장폐지로 오판된다.
        market_status: corp_collector._get_krx_universe() 의 두 번째 반환값
        krx_mode:      목록이 KRX/FDR 에서 왔는가(False = DART 단독)
        apply:         True 면 corporations 를 갱신한다. 기본은 드라이런.
        delisted_registry: `krx_client.fetch_delisted()` 의 상장폐지 명부.
                       여기 등재된 종목은 **양성 증거**(폐지일·사유 명시)라 G1(10영업일 대기)을
                       건너뛰고 바로 확정한다. 명부가 비었으면(조회 실패) 무시되고
                       기존 부재-추론 경로로 폴백한다.

    반환: {"skipped": bool, "reason": str, "verdicts": [Verdict], "counts": {...}}
    """
    market_ok = ",".join(
        f"{m}:{st.get('used') or 'fail'}" for m, st in sorted(market_status.items()))

    trusted, reason = check_source_trust(market_status, krx_mode)
    if not trusted:
        logger.error(f"[delisting] 판정 스킵 — {reason}")
        _audit(None, applied=apply, verdict="source_untrusted", reason=reason,
               krx_mode="krx" if krx_mode else "dart_only", krx_market_ok=market_ok)
        return {"skipped": True, "reason": reason, "verdicts": [], "counts": {}}

    # 소스 정상 — 시장별 크기를 기준선으로 남긴다(다음 실행의 G0b 비교 대상)
    for m, st in market_status.items():
        _audit(None, applied=apply, verdict="source_ok", reason=f"{m} 정상",
               krx_mode="krx", krx_market_ok=f"{m}:{st.get('used')}",
               krx_market_size=st.get("count"))

    verdicts: list[Verdict] = []
    counts = {"candidate": 0, "confirmed": 0, "reinstated": 0, "hold": 0}
    today = date.today()
    registry = dict(delisted_registry or {})

    with get_session() as s:
        # 명부 sanity — 우리 기업 중 폐지 명부에 걸린 비율이 비정상이면 명부를 버린다.
        # 명부가 오염돼도(잘못된 대량 등재) 확정으로 번지지 않게 하는 유일한 가드다.
        if registry:
            n_corps = s.execute(text(
                "SELECT count(*) FROM corporations WHERE stock_code IS NOT NULL")).scalar() or 1
            hits = s.execute(text("""
                SELECT count(*) FROM corporations
                WHERE stock_code = ANY(:codes) AND delisting_status IS DISTINCT FROM 'confirmed'
            """), {"codes": list(registry)}).scalar() or 0
            share = hits / n_corps
            if share > REGISTRY_MAX_SHARE:
                logger.error(f"[delisting] 폐지 명부 신뢰 불가 — 미확정 기업의 {share:.1%}가 "
                             f"명부에 등재({hits}/{n_corps}). 명부 경로 비활성화, 추론 경로로 진행")
                _audit(None, applied=apply, verdict="registry_untrusted",
                       reason=f"명부 등재 비율 {share:.1%} > {REGISTRY_MAX_SHARE:.0%}",
                       krx_mode="krx", krx_market_ok=market_ok)
                registry = {}
            else:
                logger.info(f"[delisting] 폐지 명부 sanity OK — 미확정 중 {hits}건 등재({share:.2%})")
        # stock_code 가 있는 **전 기업**을 본다. `is_active=TRUE` 로 좁히면,
        # corp_collector 가 이미 내려버린 기업(is_active=False·delisting_status=NULL)이
        # 판정 대상에서 빠져 영원히 미평가로 남는다 — 실제로 5개사가 그 상태였다.
        rows = s.execute(text("""
            SELECT corp_code, corp_name, stock_code, delisting_status,
                   delisting_first_seen
            FROM corporations
            WHERE stock_code IS NOT NULL
        """)).fetchall()

        confirmed_today = s.execute(text("""
            SELECT count(*) FROM corporations
            WHERE delisting_status = 'confirmed' AND delisted_at = :d
        """), {"d": today}).scalar() or 0

        for corp_code, corp_name, stock_code, status, first_seen in rows:
            present = stock_code in listed

            # ── 재등장 → reinstated ──
            if present:
                if status in ("candidate", "confirmed"):
                    v = Verdict(corp_code, corp_name, "reinstated",
                                f"KRX 목록 재등장(이전 {status})")
                    verdicts.append(v)
                    counts["reinstated"] += 1
                    if apply:
                        s.execute(text("""
                            UPDATE corporations
                            SET delisting_status = 'reinstated',
                                delisting_first_seen = NULL, updated_at = now()
                            WHERE corp_code = :c
                        """), {"c": corp_code})
                    _audit(corp_code, applied=apply, verdict="reinstated", reason=v.reason,
                           krx_present=True, krx_mode="krx", krx_market_ok=market_ok)
                continue

            # ── 부재 ──
            # ★ 양성 증거 우선 — 상장폐지 명부에 폐지일·사유가 적혀 있으면 '추론'이 아니라
            #    '사실'이다. G1(10영업일 대기)은 부재 추론이 틀릴 위험을 막는 장치이므로
            #    여기엔 적용하지 않는다. G0(소스 신뢰)·G3(상한)·G4(알림)는 그대로 적용된다.
            reg = registry.get(stock_code)
            if reg and status != "confirmed":
                if confirmed_today >= DAILY_CONFIRM_CAP_REGISTRY:
                    v = Verdict(corp_code, corp_name, "hold",
                                f"G3 상한(명부) — 오늘 확정 {confirmed_today}건 도달, 내일로 이월",
                                signals=[f"상장폐지 명부 등재({reg['delisting_date']})"])
                    verdicts.append(v)
                    counts["hold"] += 1
                    _audit(corp_code, applied=apply, verdict="hold", reason=v.reason, krx_present=False,
                           krx_mode="krx", krx_market_ok=market_ok)
                    continue
                sig = (f"상장폐지 명부: {reg['delisting_date']} · {reg['reason'][:60]}")
                v = Verdict(corp_code, corp_name, "confirmed",
                            "상장폐지 명부 등재(양성 증거 — G1 대기 불필요)",
                            signals=[sig])
                verdicts.append(v)
                counts["confirmed"] += 1
                confirmed_today += 1
                if apply:
                    s.execute(text("""
                        UPDATE corporations
                        SET delisting_status = 'confirmed',
                            delisted_at = :d, is_active = FALSE, updated_at = now()
                        WHERE corp_code = :c
                    """), {"c": corp_code, "d": reg["delisting_date"] or today})
                _audit(corp_code, applied=apply, verdict="confirmed", reason=v.reason + " | " + sig,
                       krx_present=False, krx_mode="krx", krx_market_ok=market_ok,
                       regulatory_event=reg["reason"][:200])
                continue

            if status is None or status == "reinstated":
                # 첫 관측 → candidate
                v = Verdict(corp_code, corp_name, "candidate",
                            "KRX 목록 부재 첫 관측", days_absent=0)
                verdicts.append(v)
                counts["candidate"] += 1
                if apply:
                    s.execute(text("""
                        UPDATE corporations
                        SET delisting_status = 'candidate',
                            delisting_first_seen = :d, updated_at = now()
                        WHERE corp_code = :c
                    """), {"c": corp_code, "d": today})
                _audit(corp_code, applied=apply, verdict="candidate", reason=v.reason,
                       krx_present=False, days_absent=0, krx_mode="krx",
                       krx_market_ok=market_ok)
                continue

            if status == "confirmed":
                continue  # 이미 확정 — 재판정 불필요

            # candidate 유지 중 → G1/G2/G3 심사
            days = _business_days_between(first_seen or today, today)
            if days < MIN_DAYS_ABSENT:
                v = Verdict(corp_code, corp_name, "hold",
                            f"G1 미충족 — 부재 {days}영업일 < {MIN_DAYS_ABSENT}",
                            days_absent=days)
                verdicts.append(v)
                counts["hold"] += 1
                _audit(corp_code, applied=apply, verdict="hold", reason=v.reason,
                       krx_present=False, days_absent=days, krx_mode="krx",
                       krx_market_ok=market_ok)
                continue

            signals = _cross_signals(s, corp_code, stock_code)
            if not signals:
                v = Verdict(corp_code, corp_name, "hold",
                            "G2 미충족 — 교차 신호 없음(단일 소스로는 확정 불가)",
                            days_absent=days)
                verdicts.append(v)
                counts["hold"] += 1
                _audit(corp_code, applied=apply, verdict="hold", reason=v.reason,
                       krx_present=False, days_absent=days, krx_mode="krx",
                       krx_market_ok=market_ok)
                continue

            if confirmed_today >= DAILY_CONFIRM_CAP:
                v = Verdict(corp_code, corp_name, "hold",
                            f"G3 상한 — 오늘 확정 {confirmed_today}건 도달, 내일로 이월",
                            days_absent=days, signals=signals)
                verdicts.append(v)
                counts["hold"] += 1
                _audit(corp_code, applied=apply, verdict="hold", reason=v.reason,
                       krx_present=False, days_absent=days, krx_mode="krx",
                       krx_market_ok=market_ok)
                continue

            # ── 전부 통과 → confirmed ──
            v = Verdict(corp_code, corp_name, "confirmed",
                        f"G1~G3 통과 — 부재 {days}영업일 · 교차신호 {len(signals)}건",
                        days_absent=days, signals=signals)
            verdicts.append(v)
            counts["confirmed"] += 1
            confirmed_today += 1
            if apply:
                s.execute(text("""
                    UPDATE corporations
                    SET delisting_status = 'confirmed', delisted_at = :d, updated_at = now()
                    WHERE corp_code = :c
                """), {"c": corp_code, "d": today})
            _audit(corp_code, applied=apply, verdict="confirmed",
                   reason=v.reason + " | " + "; ".join(signals),
                   krx_present=False, days_absent=days, krx_mode="krx",
                   krx_market_ok=market_ok,
                   regulatory_event=next((x for x in signals if x.startswith("규제")), None))

        if apply:
            s.commit()

    # G4 — 확정 전환은 사람이 사후 검토할 수 있게 알린다
    if counts["confirmed"]:
        names = ", ".join(f"{v.corp_name}({v.corp_code})"
                          for v in verdicts if v.status == "confirmed")
        try:
            from scripts.notify import notify_failure
            notify_failure(
                f"상장폐지 확정 {counts['confirmed']}건",
                f"{names}\n\n원문은 삭제하지 않고 NAS 아카이브로 이관 대상이 됩니다.\n"
                f"되돌리려면: scripts/delisting_manage.py --restore <corp_code>")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[delisting] 알림 실패(비치명적): {exc}")

    logger.info(f"[delisting] 판정 — 후보 {counts['candidate']} · 확정 {counts['confirmed']} · "
                f"복귀 {counts['reinstated']} · 보류 {counts['hold']}"
                f"{'' if apply else '  (드라이런 — DB 미반영)'}")
    return {"skipped": False, "reason": "", "verdicts": verdicts, "counts": counts}


def _audit(corp_code: Optional[str], *, verdict: str, reason: str,
           applied: bool = True,
           krx_mode: Optional[str] = None, krx_market_ok: Optional[str] = None,
           krx_market_size: Optional[int] = None, krx_present: Optional[bool] = None,
           days_absent: Optional[int] = None,
           regulatory_event: Optional[str] = None) -> None:
    """판정 근거를 남긴다. **왜 그렇게 판정했는지**가 오탐 추적의 유일한 단서다.

    `applied=False`(드라이런)면 verdict 에 `dry:` 접두를 붙인다. 안 그러면 "확정했다"는
    기록만 남고 실제로는 DB 를 안 바꾼 상태가 되어 원장이 거짓을 말한다.
    """
    if not applied:
        verdict = f"dry:{verdict}"[:20]
    try:
        with get_session() as s:
            s.execute(text("""
                INSERT INTO delisting_audit
                    (corp_code, krx_mode, krx_market_ok, krx_market_size, krx_present,
                     days_absent, regulatory_event, verdict, reason)
                VALUES (:c, :mode, :mok, :msize, :present, :days, :ev, :v, :r)
            """), {"c": corp_code, "mode": krx_mode, "mok": (krx_market_ok or "")[:64],
                   "msize": krx_market_size, "present": krx_present, "days": days_absent,
                   "ev": (regulatory_event or None), "v": verdict, "r": reason[:2000]})
            s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[delisting] 감사 기록 실패(비치명적): {type(exc).__name__}: {exc}")
