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


def _get_krx_universe() -> Optional[dict]:
    """
    FinanceDataReader로 KRX 상장 법인 목록 조회.
    KIND(한국거래소 기업공시) 기준 → 법인당 1개(보통주 코드), ETF/ETN/우선주 미포함.
    반환: {stock_code(6자리): market} 또는 None
    """
    try:
        import FinanceDataReader as fdr
    except ImportError:
        logger.warning("finance-datareader 미설치 — DART 단독 모드로 진행합니다.")
        return None

    universe = {}
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(market)
            if df is None or df.empty:
                logger.warning(f"  FDR {market}: 빈 결과")
                continue

            # 종목코드 컬럼 탐지
            code_col = _extract_code_column(df)
            if code_col:
                codes = df[code_col].astype(str).str.strip()
            else:
                # index가 코드인 경우
                codes = df.index.astype(str).str.strip()

            for code in codes:
                if code and len(code) <= 7:   # 6~7자리 종목코드만
                    universe[code.zfill(6)] = market

            logger.info(f"  FDR {market}: {len(df):,}개")
        except Exception as e:
            logger.warning(f"  FDR {market} 조회 실패: {type(e).__name__}: {e}")

    if not universe:
        logger.warning("FinanceDataReader 조회 실패 — DART 단독 모드로 진행합니다.")
        logger.warning("※ DART 단독 모드는 상장폐지 기업이 포함될 수 있습니다.")
        return None

    logger.info(f"KRX 전체 상장 법인: {len(universe):,}개 (ETF/ETN/우선주 미포함)")
    return universe


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
        krx_universe = _get_krx_universe()
        krx_mode = krx_universe is not None

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
                if _should_exclude(corp_name):
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
                if _should_exclude(corp_name):
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

        with get_session() as session:
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
            existing_active = session.scalars(
                select(Corporation.corp_code).where(Corporation.is_active == True)
            ).all()
            to_deactivate = [c for c in existing_active if c not in final_codes]

            if to_deactivate:
                session.execute(
                    update(Corporation)
                    .where(Corporation.corp_code.in_(to_deactivate))
                    .values(is_active=False, updated_at=datetime.utcnow())
                )
                logger.info(f"  상장폐지·제외 처리: {len(to_deactivate):,}개 → is_active=False")

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
