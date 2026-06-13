"""
PostgreSQL 연결 및 세션 관리
- 앱 시작 시 create_all()로 테이블 자동 생성
- get_session() context manager로 트랜잭션 관리
"""
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from collector.config import DATABASE_URL
from collector.models import Base


# 엔진 생성 (pool_pre_ping: 끊긴 연결 자동 감지)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,   # SQL 디버그 출력 끄기 (True로 바꾸면 쿼리 확인 가능)
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """
    DB 초기화: 존재하지 않는 테이블을 생성하고 연결 상태를 확인.
    최초 1회 또는 스키마 변경 후 실행.
    """
    from loguru import logger

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(f"DB 연결 성공: {DATABASE_URL.split('@')[-1]}")
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}")
        raise

    # financial_facts: P5 컷오버로 드롭(레거시 parse→aggregate 경로 폐기, std_financials_v2
    # 가 대체). create_all 이 빈 테이블로 재생성하지 않도록 메타데이터에서 제외(드롭 영속).
    # unknown_accounts: 레거시 parse 부산물(미매핑 계정). fin2 파이프라인 미사용 → 함께 드롭.
    for _dropped in ("financial_facts", "unknown_accounts"):
        _t = Base.metadata.tables.get(_dropped)
        if _t is not None:
            Base.metadata.remove(_t)
    Base.metadata.create_all(engine)
    logger.info("테이블 스키마 확인/생성 완료")

    _run_migrations()


def _run_migrations() -> None:
    """
    Alembic 없이 컬럼 추가 등 경량 마이그레이션 처리.
    ADD COLUMN IF NOT EXISTS를 사용하므로 멱등성 보장 (여러 번 실행해도 안전).
    """
    from loguru import logger

    migrations = [
        # 2025-05: last_filing_sync 컬럼 추가 (sync-filings resume 기능)
        "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS last_filing_sync TIMESTAMP",

        # 2026-06: coverage_class — 펀드/집합투자기구 등 정기보고 미대상 분리(완전성 모집단 제외, 추후 보강)
        "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS coverage_class VARCHAR(20) DEFAULT 'periodic'",

        # 2026-06: PRD 01a 결산월 변경 대응 — filings 기간 정체성 컬럼(추가만, 기존 무영향)
        "ALTER TABLE filings ADD COLUMN IF NOT EXISTS period_end_date   DATE",
        "ALTER TABLE filings ADD COLUMN IF NOT EXISTS period_end_month  SMALLINT",
        "ALTER TABLE filings ADD COLUMN IF NOT EXISTS fye_month_at_time SMALLINT",
        "ALTER TABLE filings ADD COLUMN IF NOT EXISTS is_stub           BOOLEAN DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS ix_filings_period_end ON filings (corp_code, report_type, period_end_date)",
        # 2026-06: PRD 02 — 첨부정정 플래그(기재정정과 구분)
        "ALTER TABLE filings ADD COLUMN IF NOT EXISTS is_attachment_amendment BOOLEAN DEFAULT FALSE",

        # 2026-06: PRD 01a — statement_source PK 에 is_stub 추가(정상연도 vs stub 공존). 1회만(컬럼 없을 때).
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='statement_source' AND column_name='is_stub') THEN
                ALTER TABLE statement_source ADD COLUMN is_stub BOOLEAN NOT NULL DEFAULT FALSE;
                ALTER TABLE statement_source DROP CONSTRAINT statement_source_pkey;
                ALTER TABLE statement_source ADD PRIMARY KEY
                    (corp_code, fiscal_year, fiscal_period, basis, statement, is_stub);
            END IF;
        END $$
        """,

        # 2026-06: PRD 01a — std_financials_v2 PK(uq_std_v2) 에 is_stub 추가. 1회만.
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='std_financials_v2' AND column_name='is_stub') THEN
                ALTER TABLE std_financials_v2 ADD COLUMN is_stub BOOLEAN NOT NULL DEFAULT FALSE;
                ALTER TABLE std_financials_v2 DROP CONSTRAINT uq_std_v2;
                ALTER TABLE std_financials_v2 ADD CONSTRAINT uq_std_v2 PRIMARY KEY
                    (corp_code, fiscal_year, fiscal_period, statement_type, version, is_stub);
            END IF;
        END $$
        """,

        # 2026-06: PRD 01a — standard_financials view 에서 stub 제외(정상연도만 노출, 기존 소비자 무영향).
        # 멱등(CREATE OR REPLACE). view 일 때만 재정의(레거시 base table 환경 보호).
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials AS
                SELECT corp_code, fiscal_year, fiscal_period, statement_type, version,
                       period_end, is_ifrs,
                       COALESCE(bs_rcept, is_rcept, cf_rcept) AS rcept_no,
                       total_assets, current_assets, cash, receivables, inventory, ppe, intangibles,
                       total_liabilities, current_liabilities, short_term_debt, long_term_debt,
                       total_equity, controlling_equity, retained_earnings, trade_payables,
                       revenue, cogs, gross_profit, sga, rd_expense, operating_income,
                       interest_expense, ebt, tax_expense, net_income, controlling_ni,
                       cfo, cfi, cff, capex, dividends_paid,
                       depreciation, amortization, da_total, ebitda, fcf, net_debt, shares_out,
                       data_quality,
                       NULL::timestamp without time zone AS superseded_at,
                       calculated_at
                FROM std_financials_v2
                WHERE version = 1 AND NOT COALESCE(is_stub, false);
            END IF;
        END $$
        """,

        # Phase 2: download_tasks 파싱 상태 컬럼 추가
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parse_status  VARCHAR(15)",
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parse_error   TEXT",
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parsed_at     TIMESTAMP",
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parsed_facts  INTEGER",
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parser_track  VARCHAR(3)",

        # 2026-06: PRD 02 Gate A — 다운로드 유효성 검증 결과
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS gate_a_status     VARCHAR(12)",
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS gate_a_reason     VARCHAR(20)",
        "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS gate_a_checked_at TIMESTAMP",

        # Phase 2: unit_multiplier SmallInteger → Integer (백만원 1,000,000 지원).
        # ⚠ financial_facts 는 P5 에서 드롭됨 → 존재할 때만 ALTER(레거시 DB 호환).
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class
                       WHERE relname='financial_facts' AND relkind='r') THEN
                ALTER TABLE financial_facts ALTER COLUMN unit_multiplier TYPE INTEGER;
            END IF;
        END $$
        """,

        # Phase 2: parse_status 인덱스
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename='download_tasks' AND indexname='ix_dt_parse_status'
            ) THEN
                CREATE INDEX ix_dt_parse_status ON download_tasks (parse_status)
                WHERE parse_status IS NOT NULL;
            END IF;
        END $$
        """,

        # Phase 3 + P5: standard_financials 컬럼/스크리닝 인덱스.
        # ⚠ P5 컷오버 후 standard_financials 는 std_financials_v2 위 view → relkind='r'(base table)
        #    일 때만 ALTER/CREATE INDEX 수행(view 면 스킵). 멱등.
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class
                       WHERE relname='standard_financials' AND relkind='r') THEN
                ALTER TABLE standard_financials ADD COLUMN IF NOT EXISTS rd_expense BIGINT;
                ALTER TABLE standard_financials ADD COLUMN IF NOT EXISTS shares_out BIGINT;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE tablename='standard_financials' AND indexname='ix_sf_screening_full'
                ) THEN
                    CREATE INDEX ix_sf_screening_full ON standard_financials
                        (fiscal_year, fiscal_period, statement_type, data_quality);
                END IF;
            END IF;
        END $$
        """,
    ]

    with engine.begin() as conn:
        for sql in migrations:
            conn.execute(text(sql))

    logger.info(f"마이그레이션 {len(migrations)}건 적용 완료")


def relation_is_view(name: str) -> bool:
    """주어진 relation 이 view 인지 여부. P5 컷오버 후 standard_financials 가
    std_financials_v2 위 view 로 바뀌었는지 판정해 레거시 쓰기 경로를 차단하는 데 쓴다."""
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT relkind='v' FROM pg_class WHERE relname=:n"
        ), {"n": name}).scalar())


@contextmanager
def get_session() -> Session:
    """
    트랜잭션 컨텍스트 매니저.
    with get_session() as session: 형태로 사용.
    예외 발생 시 자동 rollback, 정상 종료 시 commit.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
