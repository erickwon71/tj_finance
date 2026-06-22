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

        # 2026-06: PRD 03 §5.2 — 계정 표준화 버킷(general/financial). 금융=이자/보험/순영업수익 구조
        # (은행·보험·증권·금융지주). 시각화 peer 그룹·버킷별 지표 적용용. tag 는 scripts/tag_account_bucket.py.
        "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS account_bucket VARCHAR(12)",

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

        # 2026-06: PRD 03 §5.1 — std_financials_v2 PK(uq_std_v2) 에 is_discrete 추가(분기환산 이산행
        # Q1~Q4 가 누적 as-filed 와 공존). 1회만(컬럼 없을 때).
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='std_financials_v2' AND column_name='is_discrete') THEN
                ALTER TABLE std_financials_v2 ADD COLUMN is_discrete BOOLEAN NOT NULL DEFAULT FALSE;
                ALTER TABLE std_financials_v2 DROP CONSTRAINT uq_std_v2;
                ALTER TABLE std_financials_v2 ADD CONSTRAINT uq_std_v2 PRIMARY KEY
                    (corp_code, fiscal_year, fiscal_period, statement_type, version, is_stub, is_discrete);
            END IF;
        END $$
        """,

        # 2026-06: PRD 04 Gate B task #5 — face_audit.gate_status(promote 게이트). 뷰가 참조하므로
        # 뷰 재정의 **앞에** 추가. (create_all 이 fresh DB 엔 이미 생성 → IF NOT EXISTS 멱등.)
        "ALTER TABLE face_audit ADD COLUMN IF NOT EXISTS gate_status VARCHAR(8)",

        # 2026-06: PRD 01a + 04 — standard_financials view: stub 제외(정상연도만) + Gate B promote 게이트.
        # face_audit LEFT JOIN 으로 gate_b_status 파생(std_v2 컬럼 미저장 → 재표준화가 감사결과 리셋 안 함).
        # 메인뷰는 **fail_a(Track A 확정버그)만 차단**, 나머지(pass·fail_b·pending·미감사)는 노출.
        # 멱등(CREATE OR REPLACE, 끝 컬럼 gate_b_status 추가). view 일 때만 재정의(레거시 base table 보호).
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials AS
                SELECT s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type, s.version,
                       s.period_end, s.is_ifrs,
                       COALESCE(s.bs_rcept, s.is_rcept, s.cf_rcept) AS rcept_no,
                       s.total_assets, s.current_assets, s.cash, s.receivables, s.inventory, s.ppe, s.intangibles,
                       s.total_liabilities, s.current_liabilities, s.short_term_debt, s.long_term_debt,
                       s.total_equity, s.controlling_equity, s.retained_earnings, s.trade_payables,
                       s.revenue, s.cogs, s.gross_profit, s.sga, s.rd_expense, s.operating_income,
                       s.interest_expense, s.ebt, s.tax_expense, s.net_income, s.controlling_ni,
                       s.cfo, s.cfi, s.cff, s.capex, s.dividends_paid,
                       s.depreciation, s.amortization, s.da_total, s.ebitda, s.fcf, s.net_debt, s.shares_out,
                       s.data_quality,
                       NULL::timestamp without time zone AS superseded_at,
                       s.calculated_at,
                       COALESCE(fa.gate_status, 'unaudited') AS gate_b_status
                FROM std_financials_v2 s
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = s.corp_code
                  AND fa.fiscal_year = s.fiscal_year
                  AND fa.fiscal_period = s.fiscal_period
                  AND fa.statement_type = s.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                WHERE s.version = 1 AND NOT COALESCE(s.is_stub, false)
                  AND NOT COALESCE(s.is_discrete, false)
                  AND COALESCE(fa.gate_status, 'unaudited') <> 'fail_a';
            END IF;
        END $$
        """,

        # 2026-06: PRD 04 Gate B — strict 검증뷰: gate_b_status='pass' 만(=보고서 100% 충실 보증).
        # 메인뷰 재사용. 메인뷰가 view 일 때만 생성.
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials_verified AS
                SELECT * FROM standard_financials WHERE gate_b_status = 'pass';
            END IF;
        END $$
        """,

        # 2026-06: PRD 03 §5.3 Layer 2 — calendar_financials 뷰(달력 정규화, 파생·Gate B 비대상).
        # std_financials_calendar 테이블은 create_all 로 생성됨. 뷰는 소비자 노출용(파생 플래그 포함).
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='std_financials_calendar' AND relkind='r') THEN
                CREATE OR REPLACE VIEW calendar_financials AS
                SELECT * FROM std_financials_calendar WHERE version = 1;
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
