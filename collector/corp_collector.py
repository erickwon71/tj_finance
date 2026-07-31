"""
기업 목록 수집기 — KRX 기반 보통주 유니버스

설계 원칙:
  KRX 상장 목록을 1차 소스로 사용 → DART corp_code 매핑

  [KRX get_market_ticker_list]  ← ETF/ETN 이미 제외됨
           ↓ stock_code 기준 JOIN
  [DART corpCode.xml]           ← corp_code, corp_name 획득
           ↓ 이름 필터
  [SPC/펀드 제거]               ← 스팩, 투자회사, 리츠, 선박투자 등
           ↓
  [corporations 테이블]         ← 보통주 실질 투자 대상만 저장

핵심 장점:
  - 우선주: DART corpCode.xml은 법인 기준(보통주 코드만 보유)이라
    우선주 ticker는 DART 매핑 미스 → 자동 제외
  - ETF/ETN: pykrx get_market_ticker_list()에서 이미 미포함
  - 상장폐지: KRX 목록에 없으면 자연 제외
"""
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.config import CORP_EXCLUDE_KEYWORDS
from collector.dart_client import DartClient
from collector.db import get_session
from collector.models import Corporation, CollectionRun


# ── SPC/펀드 이름 필터 ────────────────────────────────────────────────

def _should_exclude(corp_name: str) -> bool:
    name_upper = corp_name.upper()
    return any(kw.upper() in name_upper for kw in CORP_EXCLUDE_KEYWORDS)


def _is_foreign_stock(stock_code: Optional[str]) -> bool:
    """국내 증시 상장 **외국 기업**(중국·홀딩스 구조 등) 판별.

    KRX 는 외국기업에 **9 로 시작하는 종목코드대**(900xxx 직상장·950xxx DR/원주)를 부여한다.
    실측(2026-07-19) 국내 9xxxxx 코드 전건이 외국기업(로스웰·소마젠·프레스티지바이오파마 등).
    이들은 재무제표 서식이 이질적이라 파싱 정합이 낮아 **유니버스에서 제외**(사용자 결정).
    이 필터는 sync 시 후보에서 걸러 **재유입을 차단**한다(기존 잔존분은 purge_foreign_corps.py)."""
    return bool(stock_code) and stock_code[:1] == "9"


# ── KRX 상장 종목 조회 ────────────────────────────────────────────────

def _extract_code_column(df) -> Optional[str]:
    """
    FinanceDataReader StockListing DataFrame에서 종목코드 컬럼명 탐지.
    버전에 따라 'Code', 'Symbol', 또는 index에 위치.
    """
    for col in ("Code", "Symbol", "code", "symbol"):
        if col in df.columns:
            return col
    return None  # index에 코드가 있는 경우


_MARKETS = ("KOSPI", "KOSDAQ")

# 두 소스가 이 비율 미만으로 겹치면 "실질적 불일치"로 보고 경고(+메일).
_CROSS_CHECK_MIN_OVERLAP = 0.95


def _get_fdr_universe() -> tuple[dict, dict[str, Optional[int]]]:
    """FinanceDataReader(비인증 스크래핑) 경로. 반환: (universe, {market: 건수|None})

    ⚠️ 빈 결과(`df.empty`)는 **실패로 간주**한다 — 정상 조회와 구분되지 않으면
    그 시장 전체가 상장폐지로 오인된다.
    """
    status: dict[str, Optional[int]] = {m: None for m in _MARKETS}
    universe: dict[str, str] = {}

    try:
        import FinanceDataReader as fdr
    except ImportError:
        logger.warning("  FDR 미설치")
        return universe, status

    for market in _MARKETS:
        try:
            df = fdr.StockListing(market)
            if df is None or df.empty:
                logger.warning(f"  FDR {market}: 빈 결과 → 조회 실패로 간주")
                continue

            code_col = _extract_code_column(df)
            codes = (df[code_col].astype(str).str.strip() if code_col
                     else df.index.astype(str).str.strip())

            n_before = len(universe)
            for code in codes:
                if code and len(code) <= 7:   # 6~7자리 종목코드만
                    universe[code.zfill(6)] = market

            status[market] = len(universe) - n_before
            logger.info(f"  FDR {market}: {len(df):,}개")
        except Exception as e:
            logger.warning(f"  FDR {market} 조회 실패: {type(e).__name__}: {e}")

    return universe, status


def _get_krx_universe() -> tuple[Optional[dict], dict]:
    """상장 유니버스 — **KRX OpenAPI 1차 + FinanceDataReader 2차(상호보완)**.

    반환: (universe, market_status)
      universe      {stock_code(6자리): market} 또는 None(전 시장 실패 = DART 단독 모드)
      market_status {market: {"krx": 건수|None, "fdr": 건수|None,
                              "used": "krx"|"fdr"|None, "count": 건수|None}}
                    `used=None` = **그 시장을 신뢰할 수 없다**

    설계 의도
    ─────────
    · **KRX OpenAPI 를 기준**으로 쓴다. 인증 기반이라 실패가 401 로 명시적이고,
      `KIND_STKCERT_TP_NM`/`SECUGRP_NM` 으로 우선주·인프라펀드·투자회사를 소스에서 바로
      걸러준다(FDR 은 우선주가 섞여 들어와 DART 매핑 실패로 간접 제외됐다).
    · **한 소스가 죽어도 다른 소스로 그 시장을 살린다.** pykrx 는 이미 차단됐고 FDR 도
      비인증 스크래핑이라 같은 운명이 될 수 있다. 반대로 KRX 는 서비스별 활용기간이 있어
      만료되면 401 이 난다(2026-07-31 기준 유가증권 1개월·코스닥 1년).
    · **둘 다 죽은 시장이 하나라도 있으면** 호출자가 비활성 처리를 건너뛴다 — 그 시장
      전체가 상장폐지로 오인되는 사고(KOSPI 809개)를 막는다.
    · 인증 문제는 조용히 넘기지 않고 **알림+메일**로 띄운다(만료는 며칠 안에 조치해야 한다).
    """
    from collector import krx_client as kc

    market_status: dict[str, dict] = {
        m: {"krx": None, "fdr": None, "used": None, "count": None} for m in _MARKETS
    }

    # ── 1차: KRX OpenAPI ──────────────────────────────────
    logger.info("KRX OpenAPI 조회...")
    try:
        krx_uni, krx_results = kc.fetch_all()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"  KRX OpenAPI 호출 실패: {type(e).__name__}: {e}")
        krx_uni, krx_results = {}, {}

    auth_errors: list[str] = []
    for m in _MARKETS:
        lst = krx_results.get(m)
        if lst is None:
            continue
        if lst.ok:
            market_status[m]["krx"] = sum(1 for k, v in krx_uni.items() if v == m)
        elif lst.error and ("미승인" in lst.error or "인증키" in lst.error):
            auth_errors.append(f"{m}: {lst.error}")

    # 인증·구독 문제는 방치하면 수집이 멈춘다 → 알림 + 메일
    if auth_errors:
        try:
            from scripts.notify import notify_failure
            notify_failure(
                "KRX OpenAPI 인증 실패",
                "KRX 상장목록 조회가 인증 문제로 실패했습니다. data.krx.co.kr 에서 "
                "해당 API 활용신청(재)승인이 필요합니다.\n\n" + "\n".join(auth_errors)
                + "\n\n지금은 FinanceDataReader 로 폴백합니다. 두 소스가 모두 실패한 시장이 "
                  "있으면 상장폐지 판정은 자동으로 중단됩니다.",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"  알림 발송 실패(비치명적): {type(e).__name__}: {e}")

    # ── 2차: FinanceDataReader ────────────────────────────
    logger.info("FinanceDataReader 조회...")
    fdr_uni, fdr_status = _get_fdr_universe()
    for m in _MARKETS:
        market_status[m]["fdr"] = fdr_status[m]

    # ── 병합: 시장별로 KRX 우선, 없으면 FDR ────────────────
    universe: dict[str, str] = {}
    for m in _MARKETS:
        st = market_status[m]
        if st["krx"]:
            universe.update({c: mk for c, mk in krx_uni.items() if mk == m})
            st["used"], st["count"] = "krx", st["krx"]
        elif st["fdr"]:
            universe.update({c: mk for c, mk in fdr_uni.items() if mk == m})
            st["used"], st["count"] = "fdr", st["fdr"]
            logger.warning(f"  {m}: KRX 실패 → FDR 로 대체(우선주가 섞일 수 있음)")
        else:
            logger.error(f"  ⚠ {m}: **두 소스 모두 실패** — 비활성 처리 금지 대상")

    # ── 교차 검증: 둘 다 성공한 경우 실질적 불일치 감지 ────
    if krx_uni and fdr_uni:
        overlap = len(set(krx_uni) & set(fdr_uni)) / max(1, len(krx_uni))
        if overlap < _CROSS_CHECK_MIN_OVERLAP:
            msg = (f"KRX·FDR 상장목록이 크게 어긋납니다 — 겹침 {overlap:.1%} "
                   f"(KRX {len(krx_uni):,} · FDR {len(fdr_uni):,}). "
                   f"어느 한쪽이 오염됐을 수 있으니 확인이 필요합니다.")
            logger.error(f"  ⚠ {msg}")
            try:
                from scripts.notify import notify_failure
                notify_failure("상장목록 소스 불일치", msg)
            except Exception:  # noqa: BLE001
                pass
        else:
            logger.info(f"  교차검증 OK — KRX·FDR 겹침 {overlap:.1%}")

    if not universe:
        logger.warning("KRX·FDR 모두 실패 — DART 단독 모드로 진행합니다.")
        logger.warning("※ DART 단독 모드는 상장폐지 기업이 포함될 수 있습니다.")
        return None, market_status

    untrusted = [m for m in _MARKETS if market_status[m]["used"] is None]
    if untrusted:
        logger.error(
            f"  ⚠ 신뢰 불가 시장: {', '.join(untrusted)} — "
            f"이번 실행은 **비활성 처리를 건너뛴다**(그 시장 전체가 상장폐지로 오인되는 것 방지)")

    used = ", ".join(f"{m}={market_status[m]['used']}" for m in _MARKETS)
    logger.info(f"KRX 전체 상장 법인: {len(universe):,}개 (소스: {used})")
    return universe, market_status


# ── DART corpCode.xml 파싱 ────────────────────────────────────────────

def _get_dart_corp_map(zip_bytes: bytes) -> dict:
    """
    DART corpCode.xml 파싱.
    반환: {stock_code: (corp_code, corp_name, modify_date)}
    단, stock_code가 비어있는 항목(비상장)은 제외.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml_name = next(n for n in zf.namelist() if n.endswith(".xml"))
        xml_bytes = zf.read(xml_name)

    root = ET.fromstring(xml_bytes)
    dart_map = {}
    for item in root.findall("list"):
        stock_code  = (item.findtext("stock_code")  or "").strip()
        corp_code   = (item.findtext("corp_code")   or "").strip()
        corp_name   = (item.findtext("corp_name")   or "").strip()
        modify_date = (item.findtext("modify_date") or "").strip()
        if stock_code:
            dart_map[stock_code] = (corp_code, corp_name, modify_date)

    return dart_map


# ── 메인: 기업 목록 동기화 ────────────────────────────────────────────

def sync_corporations() -> dict:
    """
    KRX 상장 보통주 유니버스 → DART 매핑 → DB upsert.

    처리 흐름:
      1. KRX 상장 종목코드 수집 (ETF/ETN 제외됨)
      2. DART corpCode.xml 다운로드 → stock_code 기준 JOIN
      3. DART에 매핑되지 않는 코드 제외 (우선주 등)
      4. 이름 필터로 SPC/펀드 제외
      5. DB upsert + 기존에 있던 비대상 기업 is_active=False 처리

    반환: {krx_total, dart_matched, excluded_no_dart, excluded_name,
           final_count, deactivated}
    """
    client = DartClient()
    run = CollectionRun(run_type="corp_sync", started_at=datetime.utcnow())
    today_str = datetime.today().strftime("%Y%m%d")

    try:
        # ── Step 1: KRX 상장 종목 (실패 시 DART 단독 모드) ──────
        logger.info("KRX 상장 종목 조회 중...")
        krx_universe, market_status = _get_krx_universe()
        krx_mode = krx_universe is not None

        # 비활성 처리(파괴적 방향)를 수행해도 되는가 — upsert(신규 반영)는 항상 한다.
        #  · 시장별 부분 실패: 실패한 시장 전체가 상장폐지로 오인된다
        #  · DART 단독 모드: 상장폐지 기업을 걸러내지 못하므로 판정 근거가 없다
        failed_markets = [m for m, st in market_status.items() if st["used"] is None]
        may_deactivate = krx_mode and not failed_markets
        if not may_deactivate:
            reason = ("DART 단독 모드" if not krx_mode
                      else f"신뢰 불가 시장({', '.join(failed_markets)}) — KRX·FDR 모두 실패")
            logger.warning(f"※ 비활성 처리 생략 — {reason}. 신규 상장 반영(upsert)은 정상 수행")

        if krx_mode:
            logger.info(f"KRX 전체 상장 종목(주권): {len(krx_universe):,}개  [KRX+DART 모드]")
        else:
            logger.warning("KRX 조회 불가 → DART 단독 모드로 진행 (우선주 자동제외 불가)")

        # ── Step 2: DART corpCode.xml ─────────────────────────
        logger.info("DART corpCode.xml 다운로드 중...")
        zip_bytes = client.get_corp_code_zip()
        dart_map  = _get_dart_corp_map(zip_bytes)
        logger.info(f"DART 상장법인: {len(dart_map):,}개")

        # ── Step 3 & 4: 매핑 + 필터 ──────────────────────────
        candidates = []
        excluded_no_dart = 0
        excluded_name    = 0
        excluded_name_list = []

        if krx_mode:
            # ── KRX 기반: KRX 목록 기준으로 DART 매핑 ──────────
            source = krx_universe.items()
            for stock_code, market in source:
                if stock_code not in dart_map:
                    excluded_no_dart += 1
                    continue
                corp_code, corp_name, modify_date = dart_map[stock_code]
                if _should_exclude(corp_name) or _is_foreign_stock(stock_code):
                    excluded_name += 1
                    excluded_name_list.append(f"{stock_code} {corp_name}")
                    continue
                candidates.append({
                    "corp_code": corp_code, "stock_code": stock_code,
                    "corp_name": corp_name, "market": market,
                    "is_active": True, "dart_modify_date": modify_date or None,
                    "updated_at": datetime.utcnow(),
                })
            logger.info(
                f"\n  KRX 전체:         {len(krx_universe):>5,}개\n"
                f"  DART 미매핑 제외: {excluded_no_dart:>5,}개  ← 우선주·DART미등록\n"
                f"  이름필터 제외:    {excluded_name:>5,}개  ← 스팩·투자회사·리츠 등\n"
                f"  ─────────────────────────────────────────\n"
                f"  최종 수집 대상:   {len(candidates):>5,}개"
            )
        else:
            # ── DART 단독: stock_code 있는 전체 → 이름 필터만 적용 ──
            market_map = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX"}
            for stock_code, (corp_code, corp_name, modify_date) in dart_map.items():
                if _should_exclude(corp_name) or _is_foreign_stock(stock_code):
                    excluded_name += 1
                    excluded_name_list.append(f"{stock_code} {corp_name}")
                    continue
                candidates.append({
                    "corp_code": corp_code, "stock_code": stock_code,
                    "corp_name": corp_name, "market": None,  # filing_collector에서 채움
                    "is_active": True, "dart_modify_date": modify_date or None,
                    "updated_at": datetime.utcnow(),
                })
            logger.info(
                f"\n  DART 상장법인:    {len(dart_map):>5,}개\n"
                f"  이름필터 제외:    {excluded_name:>5,}개\n"
                f"  ─────────────────────────────────────────\n"
                f"  최종 수집 대상:   {len(candidates):>5,}개  ※ 우선주 포함 가능"
            )

        if excluded_name_list:
            logger.debug("이름필터 제외 목록:")
            for item in excluded_name_list:
                logger.debug(f"  {item}")

        # ── Step 5: DB Upsert ─────────────────────────────────
        final_codes = {c["corp_code"] for c in candidates}
        meta_by_code = {
            c["corp_code"]: {"corp_name": c["corp_name"], "market": c["market"]}
            for c in candidates
        }

        with get_session() as session:
            # upsert 이전의 활성 집합 스냅샷 → 이번 실행으로 '신규 활성화'된 기업 판별용.
            pre_active = set(session.scalars(
                select(Corporation.corp_code).where(Corporation.is_active == True)
            ).all())

            # 현재 수집 대상 upsert
            batch_size = 500
            for i in range(0, len(candidates), batch_size):
                batch = candidates[i : i + batch_size]
                stmt = pg_insert(Corporation).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["corp_code"],
                    set_={
                        "corp_name":        stmt.excluded.corp_name,
                        "stock_code":       stmt.excluded.stock_code,
                        "market":           stmt.excluded.market,
                        "is_active":        True,
                        "dart_modify_date": stmt.excluded.dart_modify_date,
                        "updated_at":       stmt.excluded.updated_at,
                    },
                )
                session.execute(stmt)

            # 이전에 있었으나 이번 KRX 목록에서 빠진 기업 → is_active=False
            # (상장폐지 또는 필터 대상으로 변경된 경우)
            # ※ may_deactivate=False(부분 실패·DART 단독)면 후보를 만들지 않는다.
            existing_active = session.scalars(
                select(Corporation.corp_code).where(Corporation.is_active == True)
            ).all()
            to_deactivate = ([c for c in existing_active if c not in final_codes]
                             if may_deactivate else [])

            # 제외 대상 이름 조회(업데이트 전) — UI/로그 노출용.
            deactivated_corps = []
            if to_deactivate:
                deactivated_corps = [
                    {"corp_code": r[0], "corp_name": r[1], "market": r[2]}
                    for r in session.execute(
                        select(Corporation.corp_code, Corporation.corp_name,
                               Corporation.market)
                        .where(Corporation.corp_code.in_(to_deactivate))
                    ).all()
                ]
                session.execute(
                    update(Corporation)
                    .where(Corporation.corp_code.in_(to_deactivate))
                    .values(is_active=False, updated_at=datetime.utcnow())
                )
                logger.info(f"  상장폐지·제외 처리: {len(to_deactivate):,}개 → is_active=False")

            # 이번 실행으로 새로 활성화된 기업(신규 상장 + 재등록) — 이름/시장 첨부.
            new_active_codes = final_codes - pre_active
            new_corps = sorted(
                ({"corp_code": cc, **meta_by_code.get(cc, {})} for cc in new_active_codes),
                key=lambda d: (d.get("corp_name") or ""),
            )

            krx_total = len(krx_universe) if krx_universe else len(dart_map)
            run.ended_at  = datetime.utcnow()
            run.total     = krx_total
            run.completed = len(candidates)
            run.skipped   = excluded_no_dart + excluded_name
            run.api_calls = 1
            session.add(run)

        krx_total = len(krx_universe) if krx_universe else len(dart_map)
        result = {
            "krx_total":        krx_total,
            "dart_matched":     krx_total - excluded_no_dart,
            "excluded_no_dart": excluded_no_dart,
            "excluded_name":    excluded_name,
            "final_count":      len(candidates),
            "deactivated":      len(to_deactivate),
            "new_count":        len(new_corps),
            "new_corps":        new_corps,          # [{corp_code, corp_name, market}]
            "deactivated_corps": deactivated_corps,  # [{corp_code, corp_name, market}]
            # 상장폐지 판정 엔진(collector.delisting)이 소스 신뢰도를 판단하는 데 쓴다.
            "krx_mode":         "krx" if krx_mode else "dart_only",
            "market_status":    market_status,      # {"KOSPI": 건수|None, ...}
            "may_deactivate":   may_deactivate,
        }
        logger.success(
            f"기업 목록 동기화 완료 — 최종 {len(candidates):,}개 기업"
        )
        return result

    finally:
        client.close()


def deactivate_excluded_corps() -> dict:
    """
    DB에 is_active=True로 남아있는 기업 중
    현재 CORP_EXCLUDE_KEYWORDS에 해당하는 것을 is_active=False로 마킹.
    (sync_corporations() 재실행의 경량 버전 — 긴급 정리용)
    """
    deactivated = 0
    matched_names = []

    with get_session() as session:
        all_corps = session.scalars(
            select(Corporation).where(Corporation.is_active == True)
        ).all()

        to_deactivate = [c for c in all_corps if _should_exclude(c.corp_name)]

        if to_deactivate:
            codes = [c.corp_code for c in to_deactivate]
            matched_names = [(c.corp_code, c.corp_name) for c in to_deactivate]
            session.execute(
                update(Corporation)
                .where(Corporation.corp_code.in_(codes))
                .values(is_active=False, updated_at=datetime.utcnow())
            )
            deactivated = len(codes)

    if matched_names:
        logger.info(f"비활성화 처리 ({deactivated}개):")
        for code, name in matched_names[:30]:
            logger.info(f"  {code}  {name}")
        if len(matched_names) > 30:
            logger.info(f"  ... 외 {len(matched_names) - 30}개")
    else:
        logger.info("비활성화 대상 없음")

    logger.success(f"비활성화 완료: {deactivated}개")
    return {"deactivated": deactivated, "keywords_matched": [n for _, n in matched_names]}
