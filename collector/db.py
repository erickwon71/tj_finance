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
    # std_financials_v2: fact_v2/std_v2 GC 트랙(2026-09-01, docs/plans/factv2_stdv2_gc_
    # scoping_2026-09-01.md §3-5/6) — std_financials_v3 가 완전히 대체(신규 쓰기는 이미
    # Phase 2, 2026-08-30 에 중단됨). 386MB 회수, 백업 NAS(tj_finance_data)/db_backup/
    # std_financials_v2_backup_2026-09-01.dump. 같은 GC 후보였던 std_financials_calendar 는 **제외** — calendar_
    # financials 뷰를 통해 app/data/screen_window.py·series.py·quarter_change.py·
    # app/views/company_page.py 가 현재도 실제로 읽고 있어(이산분기 CQ1~CQ4 스크리너/시계열
    # 기능) 소비자 이식 없이 드롭하면 그 화면들이 깨진다 — 별도 결정 대기.
    # fact_v2: 같은 GC 트랙 §4-4(`docs/plans/factv2_sync_scripts_migration_design_
    # 2026-09-01.md`) — extended_financials 는 이미 extended_facts_v3 로 이전(§4-2),
    # 유일 남은 소비자였던 cf_da_sync.py/expense_nature_sync.py 의 fact_v2 upsert 도
    # Track1(extended_facts_v3 로 이식)/Track2(D&A 계열 은퇴)로 정리 완료. 55GB 회수,
    # 백업 NAS(tj_finance_data)/db_backup/fact_v2_backup_2026-09-01.dump. pg_depend
    # 전수 확인 결과 의존 뷰 0건(std_financials_v2 때와 달리 calendar_financials 류의
    # 숨은 소비자 없음 — 위 사고 전례 때문에 재확인함).
    for _dropped in ("financial_facts", "unknown_accounts", "std_financials_v2", "fact_v2"):
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

    A4c(2026-07) — schema_migrations 거버넌스: 각 항목에 안정적 id 를 부여하고
    schema_migrations 테이블에 적용 이력을 기록한다. 이미 적용된 id 는 다음 부팅부터
    스킵되므로, DB 가 커져도 매번 30여 개 DDL 을 재실행/재잠금하지 않는다(멱등 SQL 자체는
    유지 — 옛 DB에서 최초 1회는 여전히 안전하게 재실행됨).
    """
    from loguru import logger

    migrations: list[tuple[str, str]] = [
        ("2025_05_corp_last_filing_sync",
         # 2025-05: last_filing_sync 컬럼 추가 (sync-filings resume 기능)
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS last_filing_sync TIMESTAMP"),

        ("2026_06_corp_coverage_class",
         # 2026-06: coverage_class — 펀드/집합투자기구 등 정기보고 미대상 분리(완전성 모집단 제외, 추후 보강)
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS coverage_class VARCHAR(20) DEFAULT 'periodic'"),

        ("2026_06_corp_account_bucket",
         # 2026-06: PRD 03 §5.2 — 계정 표준화 버킷(general/financial). 금융=이자/보험/순영업수익 구조
         # (은행·보험·증권·금융지주). 시각화 peer 그룹·버킷별 지표 적용용. tag 는 scripts/tag_account_bucket.py.
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS account_bucket VARCHAR(12)"),

        # 2026-06: PRD 01a 결산월 변경 대응 — filings 기간 정체성 컬럼(추가만, 기존 무영향)
        ("2026_06_filings_period_end_date",
         "ALTER TABLE filings ADD COLUMN IF NOT EXISTS period_end_date   DATE"),
        ("2026_06_filings_period_end_month",
         "ALTER TABLE filings ADD COLUMN IF NOT EXISTS period_end_month  SMALLINT"),
        ("2026_06_filings_fye_month_at_time",
         "ALTER TABLE filings ADD COLUMN IF NOT EXISTS fye_month_at_time SMALLINT"),
        ("2026_06_filings_is_stub",
         "ALTER TABLE filings ADD COLUMN IF NOT EXISTS is_stub           BOOLEAN DEFAULT FALSE"),
        ("2026_06_ix_filings_period_end",
         "CREATE INDEX IF NOT EXISTS ix_filings_period_end ON filings (corp_code, report_type, period_end_date)"),
        ("2026_06_filings_is_attachment_amendment",
         # 2026-06: PRD 02 — 첨부정정 플래그(기재정정과 구분)
         "ALTER TABLE filings ADD COLUMN IF NOT EXISTS is_attachment_amendment BOOLEAN DEFAULT FALSE"),

        ("2026_06_statement_source_pk_is_stub",
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
        """),

        ("2026_06_std_v2_pk_is_stub",
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
        """),

        ("2026_06_std_v2_pk_is_discrete",
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
        """),

        ("2026_06_face_audit_gate_status",
         # 2026-06: PRD 04 Gate B task #5 — face_audit.gate_status(promote 게이트). 뷰가 참조하므로
         # 뷰 재정의 **앞에** 추가. (create_all 이 fresh DB 엔 이미 생성 → IF NOT EXISTS 멱등.)
         "ALTER TABLE face_audit ADD COLUMN IF NOT EXISTS gate_status VARCHAR(8)"),

        # 2026-06: PRD 04 Phase B — corp_verify_status 에 라인 전수대조 롤업 컬럼(기존 테이블 보강).
        # face_line_audit 테이블 자체는 create_all 이 생성. 측정 우선 — promote 뷰는 미참조.
        ("2026_06_corp_verify_status_line_total",
         "ALTER TABLE corp_verify_status ADD COLUMN IF NOT EXISTS line_total INTEGER DEFAULT 0"),
        ("2026_06_corp_verify_status_line_value_diff",
         "ALTER TABLE corp_verify_status ADD COLUMN IF NOT EXISTS line_value_diff INTEGER DEFAULT 0"),
        ("2026_06_corp_verify_status_line_missing",
         "ALTER TABLE corp_verify_status ADD COLUMN IF NOT EXISTS line_missing INTEGER DEFAULT 0"),

        ("2026_06_standard_financials_view_gateb",
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
        """),

        ("2026_06_standard_financials_verified_view",
         # 2026-06: PRD 04 Gate B — strict 검증뷰: gate_b_status='pass' 만(=보고서 100% 충실 보증).
         # 메인뷰 재사용. 메인뷰가 view 일 때만 생성.
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials_verified AS
                SELECT * FROM standard_financials WHERE gate_b_status = 'pass';
            END IF;
        END $$
        """),

        ("2026_06_calendar_financials_view",
         # 2026-06: PRD 03 §5.3 Layer 2 — calendar_financials 뷰(달력 정규화, 파생·Gate B 비대상).
         # std_financials_calendar 테이블은 create_all 로 생성됨. 뷰는 소비자 노출용(파생 플래그 포함).
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='std_financials_calendar' AND relkind='r') THEN
                CREATE OR REPLACE VIEW calendar_financials AS
                SELECT * FROM std_financials_calendar WHERE version = 1;
            END IF;
        END $$
        """),

        # 2026-06: 주가 데이터 확충 — stock_prices 에 일별 OHLCV + 펀더멘탈 컬럼(additive, nullable).
        # create_all 이 fresh DB 엔 이미 생성 → ADD COLUMN IF NOT EXISTS 멱등.
        ("2026_06_stock_prices_open_price", "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS open_price INTEGER"),
        ("2026_06_stock_prices_high_price", "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS high_price INTEGER"),
        ("2026_06_stock_prices_low_price",  "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS low_price  INTEGER"),
        ("2026_06_stock_prices_volume",     "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS volume     BIGINT"),
        ("2026_06_stock_prices_per",        "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS per        DOUBLE PRECISION"),
        ("2026_06_stock_prices_pbr",        "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS pbr        DOUBLE PRECISION"),
        ("2026_06_stock_prices_eps",        "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS eps        BIGINT"),
        ("2026_06_stock_prices_bps",        "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS bps        BIGINT"),
        ("2026_06_stock_prices_div_yield",  "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS div_yield  DOUBLE PRECISION"),
        ("2026_06_stock_prices_dps",        "ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS dps        BIGINT"),

        ("2026_06_ix_std_v2_corp_period",
         # 2026-06: 재무↔주가 결합 준비 — 단일종목 조회 인덱스(아래 valuation_daily matview 의 조인 대상).
         "CREATE INDEX IF NOT EXISTS ix_std_v2_corp_period ON std_financials_v2 (corp_code, period_end)"),

        ("2026_07_valuation_daily_drop_plain_view",
         # A4a(2026-07) — valuation_daily 를 일반 뷰에서 materialized view 로 전환하는 1단계:
         # 옛 배포에서 이미 plain view 로 존재하면 제거(그래야 CREATE MATERIALIZED VIEW 가 이름을 쓸 수 있음).
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='valuation_daily' AND relkind='v') THEN
                DROP VIEW valuation_daily;
            END IF;
        END $$
        """),

        ("2026_07_valuation_daily_matview",
         # A4a — 재무↔주가 결합 matview(밸류에이션 멀티플). 11.2M 주가행마다 LATERAL로 최신FY 재무를
         # 조인하는 비용을 매 조회 대신 야간 1회로 상각(D3, 전문가 리뷰 §4). WITH NO DATA 로 생성만 하고,
         # 최초 적재는 scripts/refresh_valuation_daily.py(1회, 사용자 실행)로 채운다 — 부팅 중 장시간
         # 마이그레이션 잠금을 피하기 위함. 이후는 collect_new.py 가 매일 REFRESH CONCURRENTLY 로 갱신.
         """
        CREATE MATERIALIZED VIEW IF NOT EXISTS valuation_daily AS
        SELECT
            c.corp_code, c.corp_name, sp.stock_code, sp.trade_date,
            sp.close_price, sp.market_cap, sp.shares_out,
            fin.fiscal_year, fin.basis,
            CASE WHEN fin.ni > 0      THEN sp.market_cap::double precision / fin.ni END      AS per,
            CASE WHEN fin.eq > 0      THEN sp.market_cap::double precision / fin.eq END      AS pbr,
            CASE WHEN fin.revenue > 0 THEN sp.market_cap::double precision / fin.revenue END AS psr,
            CASE WHEN fin.cfo > 0     THEN sp.market_cap::double precision / fin.cfo END     AS pcr,
            (sp.market_cap + COALESCE(fin.net_debt, 0))                                      AS ev,
            CASE WHEN fin.ebitda > 0
                 THEN (sp.market_cap + COALESCE(fin.net_debt,0))::double precision / fin.ebitda END           AS ev_ebitda,
            CASE WHEN fin.operating_income > 0
                 THEN (sp.market_cap + COALESCE(fin.net_debt,0))::double precision / fin.operating_income END AS ev_ebit,
            CASE WHEN sp.shares_out > 0 THEN fin.ni::double precision / sp.shares_out END AS eps,
            CASE WHEN sp.shares_out > 0 THEN fin.eq::double precision / sp.shares_out END AS bps,
            CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL
                 THEN abs(fin.dividends_paid)::double precision / sp.shares_out END AS dps,
            CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL AND sp.close_price > 0
                 THEN (abs(fin.dividends_paid)::double precision / sp.shares_out) / sp.close_price END AS dividend_yield
        FROM stock_prices sp
        JOIN corporations c ON c.stock_code = sp.stock_code AND c.is_active
        LEFT JOIN LATERAL (
            SELECT f.fiscal_year, f.statement_type AS basis,
                   COALESCE(f.controlling_ni, f.net_income)       AS ni,
                   COALESCE(f.controlling_equity, f.total_equity) AS eq,
                   f.revenue, f.cfo, f.ebitda, f.operating_income, f.net_debt, f.dividends_paid
            FROM std_financials_v2 f
            WHERE f.corp_code = c.corp_code AND f.fiscal_period = 'FY' AND f.version = 1
              AND NOT COALESCE(f.is_discrete, false) AND NOT COALESCE(f.is_stub, false)
              AND f.period_end <= sp.trade_date
            ORDER BY f.period_end DESC,
                     CASE f.statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
            LIMIT 1
        ) fin ON true
        WHERE sp.market_cap IS NOT NULL
        WITH NO DATA
        """),

        ("2026_07_valuation_daily_matview_unique_index",
         # A4a — REFRESH MATERIALIZED VIEW CONCURRENTLY 에는 unique index 가 필수.
         # 소비 쪽(app/data/valuation_bands.py) 조회 패턴(corp_code=... ORDER BY trade_date)과도 일치.
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_valuation_daily_corp_date ON valuation_daily (corp_code, trade_date)"),

        # Phase 2: download_tasks 파싱 상태 컬럼 추가
        ("2026_p2_download_tasks_parse_status", "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parse_status  VARCHAR(15)"),
        ("2026_p2_download_tasks_parse_error",  "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parse_error   TEXT"),
        ("2026_p2_download_tasks_parsed_at",    "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parsed_at     TIMESTAMP"),
        ("2026_p2_download_tasks_parsed_facts", "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parsed_facts  INTEGER"),
        ("2026_p2_download_tasks_parser_track", "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS parser_track  VARCHAR(3)"),

        # 2026-06: PRD 02 Gate A — 다운로드 유효성 검증 결과
        ("2026_06_download_tasks_gate_a_status",     "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS gate_a_status     VARCHAR(12)"),
        ("2026_06_download_tasks_gate_a_reason",     "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS gate_a_reason     VARCHAR(20)"),
        ("2026_06_download_tasks_gate_a_checked_at", "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS gate_a_checked_at TIMESTAMP"),

        ("2026_p2_financial_facts_unit_multiplier_int",
         # Phase 2: unit_multiplier SmallInteger → Integer (백만원 1,000,000 지원).
         # ⚠ financial_facts 는 P5 에서 드롭됨 → 존재할 때만 ALTER(레거시 DB 호환).
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class
                       WHERE relname='financial_facts' AND relkind='r') THEN
                ALTER TABLE financial_facts ALTER COLUMN unit_multiplier TYPE INTEGER;
            END IF;
        END $$
        """),

        ("2026_p2_ix_dt_parse_status",
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
        """),

        ("2026_p3_standard_financials_screening_cols",
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
        """),
        # 섹터/피어 벤치마킹 — DART 업종코드(KSIC). company.json 로 채움(collect_industry.py).
        ("2026_sector_corp_induty_code", "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS induty_code VARCHAR(6)"),
        ("2026_sector_ix_corp_induty",   "CREATE INDEX IF NOT EXISTS ix_corporations_induty ON corporations (induty_code)"),
        # P1 D2 — 중복/미사용 인덱스 정리(디스크 회수, 멱등). 재생성 안 함:
        #  ix_sp_stock_date = uq_stock_prices 와 동일 컬럼 중복(683MB)
        #  ix_fact_v2_is_dimensional = boolean 저선택 인덱스, 스캔 0(2.1GB)
        #  ix_fact_v2_corp_code = ix_fact_v2_lookup(corp_code,…) 의 좌프리픽스 중복(2.8GB)
        ("2026_p1_d2_drop_ix_sp_stock_date",             "DROP INDEX IF EXISTS ix_sp_stock_date"),
        ("2026_p1_d2_drop_ix_fact_v2_is_dimensional",    "DROP INDEX IF EXISTS ix_fact_v2_is_dimensional"),
        ("2026_p1_d2_drop_ix_fact_v2_corp_code",         "DROP INDEX IF EXISTS ix_fact_v2_corp_code"),

        ("2026_07_fact_v2_autovacuum_tuning",
         # A4b(2026-07) — 전문가 리뷰 §5: fact_v2(87M행, dead 12.8M/~15%, 수동 VACUUM 이력 전무)의
         # autovacuum 임계값을 하향(기본 스케일 팩터 20%→2%)해 죽은 튜플이 쌓이기 전에 더 자주 청소.
         # 주기 VACUUM(ANALYZE)은 scripts/vacuum_db.py(주간 launchd, D5)가 보완.
         "ALTER TABLE fact_v2 SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02)"),

        ("2026_07_extended_financials_view",
         # PRD 10~12(전문 서비스 갭 채우기 Phase 1) — concept_map 이 매핑하지만 std_financials_v2
         # wide 컬럼으로 승격되지 않은 ~51종 캐노니컬(bs.goodwill·is.finance_income·
         # cf.borrowings_proceeds 등)을 앱에 저비용 노출하는 long 뷰. statement_source 가 이미
         # (corp,fy,fp,basis,statement) 별 승자 rcept 를 선택했으므로 그 rcept 의 fact_v2 만
         # 골라 dedup 은 공짜. SUM 은 의도적(leaf-additive 캐노니컬 — 예: bs.lease_liability=
         # 유동+비유동 두 acode 합). col_index=0(당기)·NOT is_dimensional(SCE/차원 제외)만.
         # v1 은 연간(FY)만 앱 노출(H1/Q3 는 누적 as-filed 라 이산화 재구현 회피, 앱단에서 필터).
         """
        CREATE OR REPLACE VIEW extended_financials AS
        SELECT f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
               f.canonical_account, SUM(f.amount_won) AS amount_won,
               COUNT(*) AS n_facts, ss.source_rcept_no
        FROM statement_source ss
        JOIN fact_v2 f ON f.rcept_no = ss.source_rcept_no
          AND f.corp_code = ss.corp_code
          AND f.report_fiscal_year = ss.fiscal_year
          AND f.report_fiscal_period = ss.fiscal_period
          AND f.basis = ss.basis
        WHERE NOT ss.is_stub
          AND f.col_index = 0
          AND NOT f.is_dimensional
          AND f.canonical_account IS NOT NULL AND f.amount_won IS NOT NULL
          AND CASE left(f.canonical_account, 3)
                WHEN 'bs.' THEN 'BS' WHEN 'is.' THEN 'IS' WHEN 'cf.' THEN 'CF'
              END = ss.statement
        GROUP BY f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
                 f.canonical_account, ss.source_rcept_no
        """),

        ("2026_07_biz_metrics_channel",
         # PRD 14(전문 서비스 갭 채우기 Phase 3) — 부문·수출/내수 매출 파서. biz_metrics 에 가산
         # 컬럼 channel(수출/내수/합계/기타). 신규 테이블 대신 metric='sales' 신규 값 + channel 로
         # 확장(기존 생산 로더/sync 재사용). 생산 지표(capacity/output/utilization)는 channel NULL.
         "ALTER TABLE biz_metrics ADD COLUMN IF NOT EXISTS channel VARCHAR(12)"),

        ("2026_07_extended_financials_view_note",
         # PRD 15(Phase 4) — extended_financials 뷰가 note.*(비용성격 주석: employee_benefits/
         # raw_materials_used 등)도 노출하도록 WHERE 절 보강. note.* 는 statement 접두(bs/is/cf)가
         # 없어 기존 CASE(left 3자)에서 배제됐다 — expense_nature_sync 가 IS 승자 rcept 에 적재하므로
         # ss.statement='IS' 와 매칭하는 분기를 OR 로 추가한다(나머지 로직·컬럼 동일).
         """
        CREATE OR REPLACE VIEW extended_financials AS
        SELECT f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
               f.canonical_account, SUM(f.amount_won) AS amount_won,
               COUNT(*) AS n_facts, ss.source_rcept_no
        FROM statement_source ss
        JOIN fact_v2 f ON f.rcept_no = ss.source_rcept_no
          AND f.corp_code = ss.corp_code
          AND f.report_fiscal_year = ss.fiscal_year
          AND f.report_fiscal_period = ss.fiscal_period
          AND f.basis = ss.basis
        WHERE NOT ss.is_stub
          AND f.col_index = 0
          AND NOT f.is_dimensional
          AND f.canonical_account IS NOT NULL AND f.amount_won IS NOT NULL
          AND (
                CASE left(f.canonical_account, 3)
                  WHEN 'bs.' THEN 'BS' WHEN 'is.' THEN 'IS' WHEN 'cf.' THEN 'CF'
                END = ss.statement
                OR (f.canonical_account LIKE 'note.%' AND ss.statement = 'IS')
              )
        GROUP BY f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
                 f.canonical_account, ss.source_rcept_no
        """),

        ("2026_07_fact_v2_provenance",
         # ★ 재무데이터 재구축(계획: docs/plans/vast-nibbling-blum.md) — provenance 4종.
         # 왜 필요한가: 이전 파이프라인은 추측값과 원본값을 구분하지 못했다. 주석표가 본문으로
         # 새어도(요약폴백·레거시 갭필), 단위를 배율대입으로 추측해도, 후보 다중 시 max-abs 로
         # 골라도 결과 행이 정상 행과 동일해 **"오염된 것만 삭제"를 SQL 로 표현할 수 없었다**
         # (실측: DB손해보험 이익잉여금 8.5경원이 DQ=1 로 앱 노출). 이 컬럼들이 그 구분을
         # 스키마로 강제한다. 선례 = statement_source.lineage.
         # 신규 컬럼은 전부 nullable·DEFAULT 없음 → PG11+ 에서 **메타데이터 전용 즉시 반영**
         # (87M 행 rewrite 없음, 재추출 전까지 NULL).
         # ⚠ 인덱스는 **의도적으로 여기서 만들지 않는다**: 87M 행 CREATE INDEX 는 트랜잭션 안에서
         # 테이블을 수 분간 잠그는데, 재추출 전까지 전 행이 NULL 이라 지금은 이득이 없다.
         # 재구축 완료 후 별도 마이그레이션으로 추가할 것(불변식 어서션 성능용).
         """
         ALTER TABLE fact_v2 ADD COLUMN IF NOT EXISTS section_kind VARCHAR(20);
         ALTER TABLE fact_v2 ADD COLUMN IF NOT EXISTS mapping_stage VARCHAR(12);
         ALTER TABLE fact_v2 ADD COLUMN IF NOT EXISTS mapping_confidence DOUBLE PRECISION;
         ALTER TABLE fact_v2 ADD COLUMN IF NOT EXISTS unit_source VARCHAR(10);
         """),

        ("2026_07_std_v2_value_lineage",
         # Phase A-3(C1/C6/C7) — max-abs 채택 폐지의 짝. 후보가 갈려 **보류한** canonical 의
         # 후보 전체를 여기에 남긴다: {canonical: [{value, rcept, chosen:false}, ...]}.
         # 구버전은 큰 값을 집고 진 후보를 흔적 없이 버려, 사후에 무엇이 경합했는지 알 수 없었다.
         # 이 컬럼이 **Phase C 패턴루프의 작업목록**이 된다(어떤 계정이 왜 비었는지 SQL 로 조회):
         #   SELECT corp_code, fiscal_year, jsonb_object_keys(value_lineage)
         #     FROM std_financials_v2 WHERE value_lineage IS NOT NULL;
         # 선례 = statement_source.lineage(후보 전체 + chosen 기록).
         # nullable·DEFAULT 없음 → 메타데이터 전용 즉시 반영(테이블 rewrite 없음).
         """
         ALTER TABLE std_financials_v2 ADD COLUMN IF NOT EXISTS value_lineage JSONB;
         """),

        ("2026_07_std_v2_lease_borrowings",
         # C 합산(concept_map 감사, docs/qa/audit_concept_map_collapse_2026-07-18.md):
         # 유동+비유동 리스부채, 단기+장기 차입 유입/상환을 합산한 신규 지표. 구 concept_map 은
         # 서로 다른 부분을 한 canonical 로 collapse 해 값충돌(보류)만 냈다 → 별도 canonical +
         # rule_additive_lease/borrowings 합산. nullable·DEFAULT 없음 → 즉시 반영, 재추출 전 NULL.
         """
         ALTER TABLE std_financials_v2 ADD COLUMN IF NOT EXISTS lease_liability BIGINT;
         ALTER TABLE std_financials_v2 ADD COLUMN IF NOT EXISTS borrowings_proceeds BIGINT;
         ALTER TABLE std_financials_v2 ADD COLUMN IF NOT EXISTS borrowings_repaid BIGINT;
         """),

        ("2026_07_extended_financials_view_distinct",
         # 2026-07-17 트리아지(dq_assertions extended_financials_n_facts_outlier) — 같은 rcept
         # 안에서 동일 canonical_account 가 서로 다른 표(본문표+증감명세 주석 등)에 완전히 같은
         # 금액으로 중복 등장하는 사례를 실측 확인(메가스터디 00422284 2018 별도 CF, 23,522,546원이
         # AUTOSUM(ROWALL/COLALL) 셀+개별 셀+라벨변형(하이픈/언더스코어) 표까지 4곳에서 중복).
         # SUM→SUM(DISTINCT)로 바꿔 완전 동일 금액 재등장을 1회로 접는다(정말 다른 항목들의 합인
         # AUTOSUM 총계는 이 변경으로는 못 잡음 — 별도 추출단 AUTOSUM 속성 필터 필요, 후속 과제).
         # 검증: dq_assertions 필터후 n_facts>5 위반 10,770→9,044(-16%), ERROR게이트/타 WARN 불변.
         """
        CREATE OR REPLACE VIEW extended_financials AS
        SELECT f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
               f.canonical_account, SUM(DISTINCT f.amount_won) AS amount_won,
               COUNT(DISTINCT f.amount_won) AS n_facts, ss.source_rcept_no
        FROM statement_source ss
        JOIN fact_v2 f ON f.rcept_no = ss.source_rcept_no
          AND f.corp_code = ss.corp_code
          AND f.report_fiscal_year = ss.fiscal_year
          AND f.report_fiscal_period = ss.fiscal_period
          AND f.basis = ss.basis
        WHERE NOT ss.is_stub
          AND f.col_index = 0
          AND NOT f.is_dimensional
          AND f.canonical_account IS NOT NULL AND f.amount_won IS NOT NULL
          AND (
                CASE left(f.canonical_account, 3)
                  WHEN 'bs.' THEN 'BS' WHEN 'is.' THEN 'IS' WHEN 'cf.' THEN 'CF'
                END = ss.statement
                OR (f.canonical_account LIKE 'note.%' AND ss.statement = 'IS')
              )
        GROUP BY f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
                 f.canonical_account, ss.source_rcept_no
        """),

        # 2026-07: 계층2 주석(note) 전사 별도 테이블. report_lines 구조 트윈(모델 중복 회피 —
        # LIKE INCLUDING ALL 로 컬럼·인덱스 복제). 주석 볼륨(본문의 ~4.7배·수억 행)을 본문 조회에서
        # 격리. statement='note' 행은 store_note_lines 가 여기에 적재. create_all 뒤(report_lines 존재).
        ("2026_07_note_lines_table",
         "CREATE TABLE IF NOT EXISTS note_lines (LIKE report_lines INCLUDING ALL)"),
        ("2026_07_note_lines_seq",
         "CREATE SEQUENCE IF NOT EXISTS note_lines_id_seq OWNED BY note_lines.id"),
        ("2026_07_note_lines_seq_default",
         "ALTER TABLE note_lines ALTER COLUMN id SET DEFAULT nextval('note_lines_id_seq')"),

        # 2026-07-28: 위 LIKE INCLUDING ALL 이 **본문용 인덱스 6개를 그대로 복제**하는데
        # 주석에는 맞지 않는 것이 섞여 있다. 아래로 교정한다(신규 DB·기존 DB 모두 동일 상태로 수렴).
        #   · context_fiscal_year : 주석은 연도를 주장하지 않아 이 컬럼이 **전량 NULL**(실측 non-null 0).
        #                           btree 는 NULL 도 저장하므로 수억 개의 NULL 엔트리를 만들고 유지한다.
        #   · corp_code           : 아래 복합 인덱스의 접두라 중복.
        #   · report_fiscal_year  : 카디널리티 ~12 라 단독으로는 플래너가 거의 쓰지 않는다.
        # 유지: note_lines_pkey · note_lines_rcept_no_idx
        #   ★ rcept_no 는 store_note_lines 의 filing 단위 DELETE 가 쓰므로 절대 제거 금지.
        ("2026_07_note_lines_drop_ctx_fy_idx",
         "DROP INDEX IF EXISTS note_lines_context_fiscal_year_idx"),
        ("2026_07_note_lines_drop_corp_idx",
         "DROP INDEX IF EXISTS note_lines_corp_code_idx"),
        ("2026_07_note_lines_drop_fy_idx",
         "DROP INDEX IF EXISTS note_lines_report_fiscal_year_idx"),
        # statement 는 note_lines 에서 상수('note')라 키에서 뺀다(원본 4컬럼 → 3컬럼).
        ("2026_07_note_lines_drop_old_lookup_idx",
         "DROP INDEX IF EXISTS note_lines_corp_code_report_fiscal_year_statement_basis_idx"),
        ("2026_07_note_lines_corp_fy_basis_idx",
         "CREATE INDEX IF NOT EXISTS note_lines_corp_fy_basis_idx "
         "ON note_lines (corp_code, report_fiscal_year, basis)"),

        # 2026-07-31 (F1): 단위 판정을 표 단위 → **열 단위**로 내리면서 생긴 두 컬럼 변경.
        #   · value_raw   : 단위를 확정하지 못한 칸의 **셀 원문**. 이게 있어야 'value_won=NULL'
        #                   이 정보손실이 아니다(fin2/extract/units.py 참고).
        #   · unit_source : 값 4종(declared/col_money/non_monetary/undetermined/undeclared)을
        #                   담아야 해서 varchar(10) → varchar(14).
        # ADD COLUMN(nullable, DEFAULT 없음)은 PG11+ 에서 카탈로그만 바꾸므로 84 GB 테이블에도
        # 즉시 적용된다. 기존 행의 value_raw 는 NULL 로 남고, 전량 재적재(Phase 4)에서 채워진다.
        ("2026_07_31_report_lines_value_raw",
         "ALTER TABLE report_lines ADD COLUMN IF NOT EXISTS value_raw TEXT"),
        ("2026_07_31_note_lines_value_raw",
         "ALTER TABLE note_lines ADD COLUMN IF NOT EXISTS value_raw TEXT"),
        ("2026_07_31_report_lines_unit_source_len",
         "ALTER TABLE report_lines ALTER COLUMN unit_source TYPE varchar(14)"),
        ("2026_07_31_note_lines_unit_source_len",
         "ALTER TABLE note_lines ALTER COLUMN unit_source TYPE varchar(14)"),

        # 2026-07-31: 미사용 단일컬럼 인덱스 정리(`docs/qa/db_waste_ledger_2026-07-30.md` W2).
        # 둘 다 `ix_report_lines_lookup(corp_code, report_fiscal_year, statement, basis)` 가
        # 대신하고, 코드에서 이 컬럼을 단독 조건으로 쓰는 질의가 없다(grep 확인):
        #   · report_fiscal_year  단독 — 카디널리티 ~12. `build.py:_periods` 는 corp_code 와
        #     함께 쓰므로 복합 인덱스가 이긴다. 통계 창에서 스캔 5.
        #   · context_fiscal_year — report_lines 는 col_index=0 만 적재하므로 사실상
        #     report_fiscal_year 와 같고, 주석·SCE 에서는 전량 NULL. 스캔 0.
        # 모델의 index=True 도 함께 제거했다 — 안 그러면 신규 DB 에서 create_all 이 되살린다.
        #
        # ⚠ `note_lines_corp_fy_basis_idx`(1.5 GB)는 **지우지 않는다.** 원장은 idx_scan=0 을
        #   근거로 drop 후보로 올렸지만, 그 인덱스의 소비자는 데일리 증분 적재의 재개 질의
        #   (`collector/note_lines_sync.py:43` — `WHERE corp_code = ANY(:corps)`)이고
        #   야간 잡이 2026-07-22 에 전량 삭제돼 통계 창 안에서 한 번도 돌지 않았다.
        #   지우면 데일리마다 76 GB heap seq scan 이 된다. 'scan 0 은 미사용의 증명이 아니다'의
        #   실제 사례라 원장에도 정정해 두었다.
        ("2026_07_31_drop_report_lines_report_fy_idx",
         "DROP INDEX IF EXISTS ix_report_lines_report_fiscal_year"),
        ("2026_07_31_drop_report_lines_context_fy_idx",
         "DROP INDEX IF EXISTS ix_report_lines_context_fiscal_year"),

        # 2026-07-31 (F2): 헤더 판정을 **삭제 대신 기록**으로 바꾼다(주석 경로 한정).
        # 설계안 `docs/plans/layer2_header_hint_lossless_2026-07-30.md`. NOT NULL 비율이
        # 낮아(표본 0.6%) 부분 인덱스로 충분하다 — 전체 인덱스는 수억 개 NULL 엔트리를 만든다.
        ("2026_07_31_report_lines_header_hint",
         "ALTER TABLE report_lines ADD COLUMN IF NOT EXISTS header_hint TEXT"),
        ("2026_07_31_note_lines_header_hint",
         "ALTER TABLE note_lines ADD COLUMN IF NOT EXISTS header_hint TEXT"),
        ("2026_07_31_note_lines_header_hint_idx",
         "CREATE INDEX IF NOT EXISTS ix_note_lines_header_hint ON note_lines (header_hint) "
         "WHERE header_hint IS NOT NULL"),

        # 2026-07-31 (F3 마무리): 표 단위 값이 `report_tables` 로 옮겨간 뒤, 라인 테이블에서
        # **비어 버린 컬럼**을 제거한다. 전량 재적재가 끝나고 `verify_phase4_reload.py` 가
        # 통과한 뒤에만 의미가 있다(그 전에는 구 포맷 값이 아직 들어 있다).
        #
        # ⚠ PostgreSQL 의 DROP COLUMN 은 **공간을 즉시 돌려주지 않는다** — 카탈로그에서 숨길
        #   뿐이고 튜플 안의 바이트는 테이블이 재작성될 때 사라진다. 이번에는 재적재 자체가
        #   재작성이라 note_lines 의 세 컬럼은 이미 값이 없다(= 공간을 안 쓴다).
        #   report_lines.parsed_at 만 이번 판에 값이 들어갔으므로(ORM default 사고) 그쪽은
        #   drop 후 VACUUM FULL 로 회수한다 — 재적재 후 17 GB 규모라 수 분이면 끝난다.
        ("2026_07_31_note_lines_drop_table_level_cols",
         "ALTER TABLE note_lines "
         "  DROP COLUMN IF EXISTS table_title, "
         "  DROP COLUMN IF EXISTS section_path, "
         "  DROP COLUMN IF EXISTS parsed_at"),
        ("2026_07_31_report_lines_drop_table_level_cols",
         "ALTER TABLE report_lines "
         "  DROP COLUMN IF EXISTS table_title, "
         "  DROP COLUMN IF EXISTS parsed_at"),

        # ── 2026-07-31: 수집 파이프라인 복구·강화 ─────────────────────────────
        # 계획: docs/plans/collection_pipeline_restore_2026-07-31.md
        # 전부 **추가만** — 기존 컬럼·데이터 무변경.

        # 상장폐지 상태기계(§6.2). `is_active` 는 KRX 관측 사실 그대로 두고, 파일 아카이브 등
        # **조치 판단은 오직 delisting_status** 가 한다. 두 개념을 분리해야 오탐(조회 실패)이
        # 원문에 손대지 못한다. 값: NULL | candidate | confirmed | reinstated
        ("2026_07_31_corp_delisting_status",
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS delisting_status VARCHAR(12)"),
        ("2026_07_31_corp_delisting_first_seen",
         # KRX 목록 부재를 처음 관측한 날 — G1(10영업일 연속 부재) 계산 기준
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS delisting_first_seen DATE"),
        ("2026_07_31_corp_delisted_at",
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS delisted_at DATE"),
        ("2026_07_31_corp_archive_path",
         # NAS 아카이브로 옮긴 원문의 위치(되돌리기용). 삭제는 하지 않는다(결정 D1).
         "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS archive_path VARCHAR(500)"),
        ("2026_07_31_ix_corp_delisting_status",
         "CREATE INDEX IF NOT EXISTS ix_corporations_delisting_status "
         "ON corporations (delisting_status) WHERE delisting_status IS NOT NULL"),

        # 판정 근거 원장(§6.3). **왜 확정했는지**가 남아야 오탐을 사후 추적할 수 있다.
        # G0 스킵(소스 불신)도 기록한다 — 조회 실패가 반복되는 것을 알아채야 하기 때문.
        ("2026_07_31_delisting_audit",
         """
        CREATE TABLE IF NOT EXISTS delisting_audit (
            id                 BIGSERIAL PRIMARY KEY,
            corp_code          VARCHAR(8),          -- NULL = 그날 전체 스킵(G0) 기록
            checked_at         TIMESTAMP NOT NULL DEFAULT now(),
            krx_mode           VARCHAR(10),         -- krx | dart_only            (G0c)
            krx_market_ok      VARCHAR(64),         -- 'KOSPI:ok,KOSDAQ:fail'     (G0a)
            krx_market_size    INTEGER,             -- 해당 시장 목록 크기        (G0b)
            krx_present        BOOLEAN,
            days_absent        INTEGER,
            regulatory_event   VARCHAR(200),
            last_price_date    DATE,
            dart_recent_filing DATE,
            verdict            VARCHAR(20) NOT NULL,
            reason             TEXT
        )
        """),
        ("2026_07_31_ix_delisting_audit_corp",
         "CREATE INDEX IF NOT EXISTS ix_delisting_audit_corp "
         "ON delisting_audit (corp_code, checked_at DESC)"),

        # 데일리 실행 워터마크(§5.2). `--days 3` 고정이 21일 공백을 만든 직접 원인이라,
        # 다음 실행이 마지막 성공 구간부터 다시 훑도록 이력을 남긴다(자가복구).
        ("2026_07_31_pipeline_runs",
         """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id          BIGSERIAL PRIMARY KEY,
            mode        VARCHAR(24) NOT NULL,      -- download_only | full | ...
            started_at  TIMESTAMP NOT NULL DEFAULT now(),
            finished_at TIMESTAMP,
            status      VARCHAR(12) NOT NULL,      -- running | success | failed
            window_bgn  DATE,
            window_end  DATE,
            summary     JSONB
        )
        """),
        ("2026_07_31_ix_pipeline_runs_lookup",
         "CREATE INDEX IF NOT EXISTS ix_pipeline_runs_lookup "
         "ON pipeline_runs (mode, status, window_end DESC)"),

        # 미러 이력(§5.3). 덧붙이기 전용으로 바꾼 대가가 '백업이 조용히 낡는 것'이라
        # 마지막 성공 시각을 근거로 신선도를 감시한다(§5.4).
        ("2026_07_31_storage_sync_log",
         """
        CREATE TABLE IF NOT EXISTS storage_sync_log (
            id            BIGSERIAL PRIMARY KEY,
            started_at    TIMESTAMP NOT NULL DEFAULT now(),
            finished_at   TIMESTAMP,
            status        VARCHAR(12) NOT NULL,    -- success | failed | skipped
            files_sent    INTEGER,
            bytes_sent    BIGINT,
            duration_sec  DOUBLE PRECISION,
            message       TEXT
        )
        """),
        ("2026_07_31_ix_storage_sync_log_status",
         "CREATE INDEX IF NOT EXISTS ix_storage_sync_log_status "
         "ON storage_sync_log (status, started_at DESC)"),

        # XBRL 원문 파서(docs/plans/xbrl_instance_parser_2026-08-05.md) Phase 1.
        # dcm_no: ifrs.do 다운로드에 필요한 DART 문서번호(view_params 로 얻음, PDF 폴백에도 재사용 가능).
        ("2026_08_download_tasks_dcm_no",
         "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS dcm_no VARCHAR(20)"),
        # file_type 이 'pdf'/'html'/'hwp'/'zip'/'xml'(5자) 대비 'xbrl_zip'(8자)로 늘어남 — 폭만 확장, 값 무변경.
        ("2026_08_download_tasks_file_type_widen",
         "ALTER TABLE download_tasks ALTER COLUMN file_type TYPE VARCHAR(10)"),

        ("2026_08_standard_financials_v3_bridge_swap",
         # 2026-08-09: 계층3 재설계 브리지 swap(docs/plans/layer3_v3_bridge_swap_2026-07-25.md §2·§4-5).
         # standard_financials 뷰의 원천을 std_financials_v2 → std_financials_v3(신 체인, report_lines
         # 경유) 로 전환. std_v3 는 enrichment 를 네이티브 산출(capex/fcf/net_debt/D&A/ebitda 등,
         # combine+run_rules)하고 industry_lines(업종 조립 revenue, C-1 소비)를 새로 노출한다.
         # 커버리지 브리지(G1 무손실, 위 계획 §5): std_v3 는 아직 2015+ 만 있고 corp-period 일부
         # 미빌드 갭도 있으므로 std_v2 를 두 갈래로 UNION ALL 폴백한다 — ① pre-2015 전체(2차 패스
         # 전까지) ② 2015+ 인데 std_v3 에 아직 없는 corp-period(NOT EXISTS). 실측(2026-08-09):
         # v2 커버 263,792행 → 신규뷰 279,860행, 손실 0·순증 16,068(v3 가 v2 에 없던 corp-period
         # 도 보유). is_ifrs 는 v3(2015+ 전량 K-IFRS 의무화 이후)라 TRUE 상수, rcept_no 는
         # source_rcepts(JSONB {"BS":...,"IS":...,"CF":...})에서 대표 1건 추출. gate_b_status 는
         # face_audit 를 v3 분기에도 동일하게 조인(감사기는 corp/period/basis 키로 소스 체인
         # 무관 — 2026-08-07 Gate B 감사기 수정으로 report_lines 기준 통일됨). 뷰 전환은
         # CREATE OR REPLACE(데이터 무변경) → 롤백 = 2026_06_standard_financials_view_gateb 의
         # DDL 재적용. view 일 때만 재정의(레거시 base table 보호).
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials AS
                SELECT
                    v3.corp_code, v3.fiscal_year, v3.fiscal_period, v3.statement_type,
                    1::smallint AS version,
                    v3.period_end,
                    TRUE AS is_ifrs,
                    COALESCE(v3.source_rcepts->>'BS', v3.source_rcepts->>'IS', v3.source_rcepts->>'CF')::varchar(14) AS rcept_no,
                    v3.total_assets, v3.current_assets, v3.cash, v3.receivables, v3.inventory, v3.ppe, v3.intangibles,
                    v3.total_liabilities, v3.current_liabilities, v3.short_term_debt, v3.long_term_debt,
                    v3.total_equity, v3.controlling_equity, v3.retained_earnings, v3.trade_payables,
                    v3.revenue, v3.cogs, v3.gross_profit, v3.sga, v3.rd_expense, v3.operating_income,
                    v3.interest_expense, v3.ebt, v3.tax_expense, v3.net_income, v3.controlling_ni,
                    v3.cfo, v3.cfi, v3.cff, v3.capex, v3.dividends_paid,
                    v3.depreciation, v3.amortization, v3.da_total, v3.ebitda, v3.fcf, v3.net_debt, v3.shares_out,
                    v3.data_quality,
                    NULL::timestamp without time zone AS superseded_at,
                    v3.built_at AS calculated_at,
                    COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
                    v3.industry_lines
                FROM std_financials_v3 v3
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = v3.corp_code
                  AND fa.fiscal_year = v3.fiscal_year
                  AND fa.fiscal_period = v3.fiscal_period
                  AND fa.statement_type = v3.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                WHERE COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'

                UNION ALL

                SELECT
                    s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type, s.version,
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
                    COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
                    NULL::jsonb AS industry_lines
                FROM std_financials_v2 s
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = s.corp_code
                  AND fa.fiscal_year = s.fiscal_year
                  AND fa.fiscal_period = s.fiscal_period
                  AND fa.statement_type = s.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                WHERE s.version = 1 AND NOT COALESCE(s.is_stub, false) AND NOT COALESCE(s.is_discrete, false)
                  AND COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'
                  AND (
                        s.fiscal_year < 2015
                        OR NOT EXISTS (
                             SELECT 1 FROM std_financials_v3 v3b
                             WHERE v3b.corp_code = s.corp_code AND v3b.fiscal_year = s.fiscal_year
                               AND v3b.fiscal_period = s.fiscal_period AND v3b.statement_type = s.statement_type
                           )
                      );
            END IF;
        END $$
        """),
        # biz_content_layer2_migration_2026-08-09 §Phase1 — biz_section_tables 를 4개 도메인
        # (production/sales/catalog/order_backlog) 공용 원본 grid 저장소로 일반화. 기존
        # 528,564행(production/sales/catalog만 존재, order_backlog는 아직 미편입)의 domain을
        # metric 값에서 역산 채움 — SELECT DISTINCT metric 실측(2026-08-09)으로 검증된 매핑:
        # biz_section.py는 capacity/output/utilization(+조합)만 방출, sales_section.py와
        # biz_catalog.py는 둘 다 metric='sales'를 공유(biz_catalog.py:266 주석 — 의도된 통일),
        # 그 외는 전부 biz_catalog.py의 CATALOG 규칙표 라벨(catalog).
        ("2026_08_biz_section_tables_domain", """
            ALTER TABLE biz_section_tables ADD COLUMN IF NOT EXISTS domain VARCHAR(20);

            UPDATE biz_section_tables SET domain = CASE
                WHEN metric IN ('capacity', 'output', 'utilization',
                                 'capacity+output', 'output+utilization', 'capacity+utilization',
                                 'capacity+output+utilization') THEN 'production'
                WHEN metric = 'sales' THEN 'sales'
                ELSE 'catalog'
            END
            WHERE domain IS NULL;

            ALTER TABLE biz_section_tables ALTER COLUMN domain SET NOT NULL;
        """),
        # Correction found during Phase3 parity testing (biz_content_layer2_migration_todo_
        # 2026-08-09.md) — the migration above classified purely by `metric`, missing that
        # fin2/extract/biz_catalog.py *also* emits metric='sales' for its own supplementary
        # captions (biz_catalog.py:266). Those rows carry the catalog composite narrative shape
        # "[{subsection}] {caption_raw}[ (연속표)] :: {narrative}" (verified 2026-08-09: 0/141,646
        # production rows match it, 300,000/300,000 sampled catalog rows do) — a reliable,
        # metric-independent signal. 6,148/63,167 metric='sales' rows matched it and were
        # mis-tagged domain='sales' when they need map_catalog_table (not map_sales_table) to
        # reconstruct correctly.
        ("2026_08_biz_section_tables_domain_sales_catalog_fix", r"""
            UPDATE biz_section_tables
            SET domain = 'catalog'
            WHERE domain = 'sales'
              AND narrative ~ '^\[.*?\] .*?( \(연속표\))? :: '
        """),

        ("2026_08_standard_financials_v3_pre2015_dedup",
         # 2026-08-11: pre-2015 2차 패스(docs/plans/pre2015_layer2_backfill_plan_2026-08-10.md
         # Phase7) — std_v3 가 이제 pre-2015 corp-period 도 빌드하므로, 위 08-09 bridge swap
         # 뷰의 std_v2 분기가 갖고 있던 하드코딩 `s.fiscal_year < 2015 OR` 조건을 제거한다.
         # 그 조건이 남아있으면 std_v3 에 이미 존재하는 pre-2015 corp-period 에 대해 std_v2
         # 쪽도 무조건 UNION ALL 돼 **중복행**이 생긴다(NOT EXISTS 만으로는 안 걸러짐 — OR 로
         # 묶여 있었기 때문). 남기는 `NOT EXISTS` 조건 하나로 2015+/pre-2015 를 동일하게
         # 취급 — std_v3 에 없는 corp-period(PDF-only 1,405건처럼 이번 트랙 스코프 밖인 것
         # 포함)만 std_v2 로 계속 폴백한다. SELECT 목록·JOIN 은 무변경, WHERE 절 한 줄만 수정.
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials AS
                SELECT
                    v3.corp_code, v3.fiscal_year, v3.fiscal_period, v3.statement_type,
                    1::smallint AS version,
                    v3.period_end,
                    TRUE AS is_ifrs,
                    COALESCE(v3.source_rcepts->>'BS', v3.source_rcepts->>'IS', v3.source_rcepts->>'CF')::varchar(14) AS rcept_no,
                    v3.total_assets, v3.current_assets, v3.cash, v3.receivables, v3.inventory, v3.ppe, v3.intangibles,
                    v3.total_liabilities, v3.current_liabilities, v3.short_term_debt, v3.long_term_debt,
                    v3.total_equity, v3.controlling_equity, v3.retained_earnings, v3.trade_payables,
                    v3.revenue, v3.cogs, v3.gross_profit, v3.sga, v3.rd_expense, v3.operating_income,
                    v3.interest_expense, v3.ebt, v3.tax_expense, v3.net_income, v3.controlling_ni,
                    v3.cfo, v3.cfi, v3.cff, v3.capex, v3.dividends_paid,
                    v3.depreciation, v3.amortization, v3.da_total, v3.ebitda, v3.fcf, v3.net_debt, v3.shares_out,
                    v3.data_quality,
                    NULL::timestamp without time zone AS superseded_at,
                    v3.built_at AS calculated_at,
                    COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
                    v3.industry_lines
                FROM std_financials_v3 v3
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = v3.corp_code
                  AND fa.fiscal_year = v3.fiscal_year
                  AND fa.fiscal_period = v3.fiscal_period
                  AND fa.statement_type = v3.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                WHERE COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'

                UNION ALL

                SELECT
                    s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type, s.version,
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
                    COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
                    NULL::jsonb AS industry_lines
                FROM std_financials_v2 s
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = s.corp_code
                  AND fa.fiscal_year = s.fiscal_year
                  AND fa.fiscal_period = s.fiscal_period
                  AND fa.statement_type = s.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                WHERE s.version = 1 AND NOT COALESCE(s.is_stub, false) AND NOT COALESCE(s.is_discrete, false)
                  AND COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'
                  AND NOT EXISTS (
                        SELECT 1 FROM std_financials_v3 v3b
                        WHERE v3b.corp_code = s.corp_code AND v3b.fiscal_year = s.fiscal_year
                          AND v3b.fiscal_period = s.fiscal_period AND v3b.statement_type = s.statement_type
                      );
            END IF;
        END $$
        """),

        ("2026_08_face_audit_source_version",
         # 2026-08-11: docs/plans/std_v3_native_gate_b_plan_2026-08-11.md Phase 1 — face_audit
         # 이 std_v2 전용이라 v2/v3 병행 감사를 못 함(PK 에 버전 구분 없음). source_version
         # 컬럼을 PK 에 추가해 같은 (corp,fy,fp,basis) 키를 v2 감사결과·v3 감사결과가 각자
         # 별도 행으로 병행 보관하게 한다(나중 실행이 먼저 것을 덮어쓰지 않도록). 기존
         # 271,695행은 전부 DEFAULT 'v2'로 채워짐(과거 gateb_audit.py 는 std_v2만 감사했으므로
         # 무손실 백필). standard_financials 뷰의 JOIN 조건 갱신은 별도 Phase(Phase 4).
         """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='face_audit' AND column_name='source_version') THEN
                ALTER TABLE face_audit ADD COLUMN source_version VARCHAR(2) NOT NULL DEFAULT 'v2';
                ALTER TABLE face_audit DROP CONSTRAINT face_audit_pkey;
                ALTER TABLE face_audit ADD CONSTRAINT face_audit_pkey PRIMARY KEY
                    (corp_code, fiscal_year, fiscal_period, statement_type, is_stub, source_version);
            END IF;
        END $$
        """),

        ("2026_08_standard_financials_view_source_version",
         # 2026-08-18: docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md —
         # 위 2026_08_face_audit_source_version 이 face_audit PK 에 source_version 을 추가해
         # 같은 (corp,fy,fp,basis) 키에 v2 감사행·v3 감사행이 **정상적으로 공존**하게 됐는데,
         # 이 뷰의 JOIN 은 그 컬럼을 지정하지 않아 v2/v3 감사행이 둘 다 매치돼 뷰 행이
         # 2배로 중복됐다(244,585키 실측 2026-08-18). gate_b_status 도 엉뚱한 체인의 감사결과가
         # 붙을 수 있고, fail_a 차단 게이트가 v2 결과로 우회되는 부작용도 있었다(설계서 §1-B).
         # 각 UNION ALL 분기에 `fa.source_version = 'v3'`/`'v2'` 를 추가해 자신이 표시하는
         # std 체인의 감사결과만 조인하도록 명시화. SELECT 목록·데이터는 무변경, JOIN 조건
         # 두 줄만 추가. 검증(dry-run view 로 사전 대조): 561→321,141행 dedup 완전(중복 0),
         # 적용 전 키 집합 ⊇ 적용 후(차집합 214건 전부 v3 fail_a 로 설명됨, 미설명 0),
         # gate_b_status 100% 일치, 삼성전자 2024FY 연결 2행→1행.
         """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='standard_financials' AND relkind='v') THEN
                CREATE OR REPLACE VIEW standard_financials AS
                SELECT
                    v3.corp_code, v3.fiscal_year, v3.fiscal_period, v3.statement_type,
                    1::smallint AS version,
                    v3.period_end,
                    TRUE AS is_ifrs,
                    COALESCE(v3.source_rcepts->>'BS', v3.source_rcepts->>'IS', v3.source_rcepts->>'CF')::varchar(14) AS rcept_no,
                    v3.total_assets, v3.current_assets, v3.cash, v3.receivables, v3.inventory, v3.ppe, v3.intangibles,
                    v3.total_liabilities, v3.current_liabilities, v3.short_term_debt, v3.long_term_debt,
                    v3.total_equity, v3.controlling_equity, v3.retained_earnings, v3.trade_payables,
                    v3.revenue, v3.cogs, v3.gross_profit, v3.sga, v3.rd_expense, v3.operating_income,
                    v3.interest_expense, v3.ebt, v3.tax_expense, v3.net_income, v3.controlling_ni,
                    v3.cfo, v3.cfi, v3.cff, v3.capex, v3.dividends_paid,
                    v3.depreciation, v3.amortization, v3.da_total, v3.ebitda, v3.fcf, v3.net_debt, v3.shares_out,
                    v3.data_quality,
                    NULL::timestamp without time zone AS superseded_at,
                    v3.built_at AS calculated_at,
                    COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
                    v3.industry_lines
                FROM std_financials_v3 v3
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = v3.corp_code
                  AND fa.fiscal_year = v3.fiscal_year
                  AND fa.fiscal_period = v3.fiscal_period
                  AND fa.statement_type = v3.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                  AND fa.source_version = 'v3'
                WHERE COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'

                UNION ALL

                SELECT
                    s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type, s.version,
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
                    COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
                    NULL::jsonb AS industry_lines
                FROM std_financials_v2 s
                LEFT JOIN face_audit fa
                  ON  fa.corp_code = s.corp_code
                  AND fa.fiscal_year = s.fiscal_year
                  AND fa.fiscal_period = s.fiscal_period
                  AND fa.statement_type = s.statement_type
                  AND NOT COALESCE(fa.is_stub, false)
                  AND fa.source_version = 'v2'
                WHERE s.version = 1 AND NOT COALESCE(s.is_stub, false) AND NOT COALESCE(s.is_discrete, false)
                  AND COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'
                  AND NOT EXISTS (
                        SELECT 1 FROM std_financials_v3 v3b
                        WHERE v3b.corp_code = s.corp_code AND v3b.fiscal_year = s.fiscal_year
                          AND v3b.fiscal_period = s.fiscal_period AND v3b.statement_type = s.statement_type
                      );
            END IF;
        END $$
        """),

        ("2026_08_face_audit_evidence_detail",
         # 2026-08-18: docs/plans/gateb_evidence_grade_redesign_2026-08-17.md Phase 1 —
         # fail_a/fail_b 는 "그 결함이 얼마나 확실한가" 가 아니라 "어느 리더가 그 보고서를
         # 읽었는가" 를 반영하고(§1-A), pass 는 근거를 하나도 남기지 않아(§1-B) "정확 일치"와
         # "관용/폴백/휴리스틱 후보와 일치"가 전부 같은 pass 로 뭉뚱그려졌다. 판정(축1)과
         # 증거강도(축2)를 분리하는 첫 단계 — 계측만 추가하고 게이팅 산식(gate_status_for_row)
         # 은 한 줄도 바꾸지 않는다(무해·되돌릴 것 없음). Phase 2(전수 재감사로 분포 실측)~4
         # (게이팅 규칙 재정의)는 이 컬럼이 채워진 뒤 별도로 진행.
         """
        ALTER TABLE face_audit ADD COLUMN IF NOT EXISTS evidence_detail JSONB;
        """),

        ("2026_08_valuation_daily_v3_ebitda_migration",
         # valuation_daily_v3_migration_plan_2026-08-30.md D1 + 후속
         # valuation_daily_blockers_da_netdebt_design_2026-08-30.md §3/§5(순서2) — matview
         # 재정의. `ni`/`eq`/`revenue`/`cfo`/`ebitda`/`operating_income`/`dividends_paid`는
         # std_financials_v2 → **v3**로 스왑(D1-a 안전 컬럼 + 보류 해제된 ebitda, §0 정정:
         # "v3에 결합공시 로직 미이식"이 아니라 레거시 note_extractor 의 note.da_total
         # 합성물이 v2에서 이중계상되던 것 — v3가 애초에 맞았다).
         # `net_debt`만 v2 LATERAL(`finnd`)에 잔류 — v3 차입금 alias 갭 + `_CURRENT_STRICT`
         # 탈락분 미회수(원인 A/B, 블로커문서 §2)가 아직 안 고쳐졌다(그 트랙에서 v3로 이관 후
         # 단일 LATERAL로 복귀 예정, §5 순서5). 두 LATERAL은 독립적으로 "corp 기준 최신 FY"를
         # 고르므로 fin/finnd 가 서로 다른 (fiscal_year,basis)를 가리킬 수 있음 — net_debt가
         # v3로 이관되기 전까지의 알려진 과도기 트레이드오프(§3 표).
         # v3엔 version/is_discrete/is_stub 컬럼이 없다 — 실측(§1-3): v3(FY) 78,213행이
         # v2(FY,non-stub,version=1) 63,110행보다 넓고, is_stub 비중은 0.064%(gateb_audit.py
         # 선례 재사용, 별도 필터 없이 무시). matview는 CREATE OR REPLACE 불가 → DROP+CREATE
         # 필수(D4: 파생 뷰라 기저 테이블 무변경, 이전 SQL 재실행하면 즉시 롤백 가능).
         # ★ WITH NO DATA 로 생성만 함 — 마이그레이션 직후 `scripts/refresh_valuation_daily.py`
         # (non-concurrent, 최초 1회 수동 실행) 로 데이터를 채워야 조회가 가능해진다.
         """
        DROP MATERIALIZED VIEW IF EXISTS valuation_daily;

        CREATE MATERIALIZED VIEW valuation_daily AS
        SELECT
            c.corp_code, c.corp_name, sp.stock_code, sp.trade_date,
            sp.close_price, sp.market_cap, sp.shares_out,
            fin.fiscal_year, fin.basis,
            CASE WHEN fin.ni > 0      THEN sp.market_cap::double precision / fin.ni END      AS per,
            CASE WHEN fin.eq > 0      THEN sp.market_cap::double precision / fin.eq END      AS pbr,
            CASE WHEN fin.revenue > 0 THEN sp.market_cap::double precision / fin.revenue END AS psr,
            CASE WHEN fin.cfo > 0     THEN sp.market_cap::double precision / fin.cfo END     AS pcr,
            (sp.market_cap + COALESCE(finnd.net_debt, 0))                                    AS ev,
            CASE WHEN fin.ebitda > 0
                 THEN (sp.market_cap + COALESCE(finnd.net_debt,0))::double precision / fin.ebitda END           AS ev_ebitda,
            CASE WHEN fin.operating_income > 0
                 THEN (sp.market_cap + COALESCE(finnd.net_debt,0))::double precision / fin.operating_income END AS ev_ebit,
            CASE WHEN sp.shares_out > 0 THEN fin.ni::double precision / sp.shares_out END AS eps,
            CASE WHEN sp.shares_out > 0 THEN fin.eq::double precision / sp.shares_out END AS bps,
            CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL
                 THEN abs(fin.dividends_paid)::double precision / sp.shares_out END AS dps,
            CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL AND sp.close_price > 0
                 THEN (abs(fin.dividends_paid)::double precision / sp.shares_out) / sp.close_price END AS dividend_yield
        FROM stock_prices sp
        JOIN corporations c ON c.stock_code = sp.stock_code AND c.is_active
        LEFT JOIN LATERAL (
            SELECT f.fiscal_year, f.statement_type AS basis,
                   COALESCE(f.controlling_ni, f.net_income)       AS ni,
                   COALESCE(f.controlling_equity, f.total_equity) AS eq,
                   f.revenue, f.cfo, f.ebitda, f.operating_income, f.dividends_paid
            FROM std_financials_v3 f
            WHERE f.corp_code = c.corp_code AND f.fiscal_period = 'FY'
              AND f.period_end <= sp.trade_date
            ORDER BY f.period_end DESC,
                     CASE f.statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
            LIMIT 1
        ) fin ON true
        LEFT JOIN LATERAL (
            SELECT f.net_debt
            FROM std_financials_v2 f
            WHERE f.corp_code = c.corp_code AND f.fiscal_period = 'FY' AND f.version = 1
              AND NOT COALESCE(f.is_discrete, false) AND NOT COALESCE(f.is_stub, false)
              AND f.period_end <= sp.trade_date
            ORDER BY f.period_end DESC,
                     CASE f.statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
            LIMIT 1
        ) finnd ON true
        WHERE sp.market_cap IS NOT NULL
        WITH NO DATA;

        CREATE UNIQUE INDEX ux_valuation_daily_corp_date ON valuation_daily (corp_code, trade_date);
        """),

        ("2026_08_valuation_daily_v3_netdebt_migration",
         # valuation_daily_blockers_da_netdebt_design_2026-08-30.md §5(순서5) +
         # docs/plans/valuation_daily_order5_netdebt_v3_migration_2026-08-31.md.
         # 순서4(①wiring/②alias 3종/③나머지 소수 라벨, R58/R59)가 전부 완전 종료돼
         # `net_debt`의 v2 잔류 사유(원인 A/B)가 해소됨 — `finnd`(v2) LATERAL을 없애고
         # `net_debt`를 `fin`(v3) LATERAL 안으로 합쳐 **단일 LATERAL로 복귀**.
         # 실측(2026-08-31): std_financials_v3 FY net_debt 보유 62,634행 > v2 44,540행
         # (v3가 더 완전). 두 LATERAL이 독립적으로 "corp 기준 최신 FY"를 고르던 구조적
         # 갭(과도기 트레이드오프, 위 ebitda 마이그레이션 주석 참고)도 이걸로 해소.
         # matview는 CREATE OR REPLACE 불가 → DROP+CREATE(파생 뷰라 기저 테이블
         # 무변경, 문제 시 위 ebitda 마이그레이션 SQL 재실행하면 즉시 롤백 가능).
         # ★ WITH NO DATA — 직후 `scripts/refresh_valuation_daily.py`(non-concurrent,
         # 최초 1회 수동 실행) 필요.
         """
        DROP MATERIALIZED VIEW IF EXISTS valuation_daily;

        CREATE MATERIALIZED VIEW valuation_daily AS
        SELECT
            c.corp_code, c.corp_name, sp.stock_code, sp.trade_date,
            sp.close_price, sp.market_cap, sp.shares_out,
            fin.fiscal_year, fin.basis,
            CASE WHEN fin.ni > 0      THEN sp.market_cap::double precision / fin.ni END      AS per,
            CASE WHEN fin.eq > 0      THEN sp.market_cap::double precision / fin.eq END      AS pbr,
            CASE WHEN fin.revenue > 0 THEN sp.market_cap::double precision / fin.revenue END AS psr,
            CASE WHEN fin.cfo > 0     THEN sp.market_cap::double precision / fin.cfo END     AS pcr,
            (sp.market_cap + COALESCE(fin.net_debt, 0))                                     AS ev,
            CASE WHEN fin.ebitda > 0
                 THEN (sp.market_cap + COALESCE(fin.net_debt,0))::double precision / fin.ebitda END           AS ev_ebitda,
            CASE WHEN fin.operating_income > 0
                 THEN (sp.market_cap + COALESCE(fin.net_debt,0))::double precision / fin.operating_income END AS ev_ebit,
            CASE WHEN sp.shares_out > 0 THEN fin.ni::double precision / sp.shares_out END AS eps,
            CASE WHEN sp.shares_out > 0 THEN fin.eq::double precision / sp.shares_out END AS bps,
            CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL
                 THEN abs(fin.dividends_paid)::double precision / sp.shares_out END AS dps,
            CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL AND sp.close_price > 0
                 THEN (abs(fin.dividends_paid)::double precision / sp.shares_out) / sp.close_price END AS dividend_yield
        FROM stock_prices sp
        JOIN corporations c ON c.stock_code = sp.stock_code AND c.is_active
        LEFT JOIN LATERAL (
            SELECT f.fiscal_year, f.statement_type AS basis,
                   COALESCE(f.controlling_ni, f.net_income)       AS ni,
                   COALESCE(f.controlling_equity, f.total_equity) AS eq,
                   f.revenue, f.cfo, f.ebitda, f.operating_income, f.dividends_paid, f.net_debt
            FROM std_financials_v3 f
            WHERE f.corp_code = c.corp_code AND f.fiscal_period = 'FY'
              AND f.period_end <= sp.trade_date
            ORDER BY f.period_end DESC,
                     CASE f.statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
            LIMIT 1
        ) fin ON true
        WHERE sp.market_cap IS NOT NULL
        WITH NO DATA;

        CREATE UNIQUE INDEX ux_valuation_daily_corp_date ON valuation_daily (corp_code, trade_date);
        """),

        ("2026_09_std_financials_v2_drop",
         # fact_v2/std_v2 GC 트랙(docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md §3-5/6).
         # standard_financials 뷰의 v2 UNION ALL 분기를 제거하고(이제 std_financials_v3
         # 단일 소스), std_financials_v2 테이블을 DROP한다(386MB 회수, ix_std_v2_corp_period
         # 인덱스도 테이블과 함께 자동 제거). init_db()의 _dropped 튜플에도 추가해 create_all
         # 이 빈 테이블로 재생성하지 않도록 함(financial_facts/unknown_accounts 와 동일 패턴).
         #
         # ★알려진 영구 손실(사용자 승인, 2026-09-01): std_v2 FY행 16,617건(fy>=1999) 중
         # 12,149건(73%)은 v3엔 대응 행이 없다 — report_lines의 "당기만 적재" 정책
         # (2026-07-30 결정)의 의도된 결과라 배치로 못 채움, 대부분 IPO 이전 연도의
         # 3개년 비교표시열 유래 데이터. 이 드롭으로 그 12,149건이 standard_financials
         # 통합뷰에서 완전히 사라진다(std_financials_v2 자체가 없어지므로). 백업:
         # db_backups/std_financials_v2_backup_2026-09-01.dump(pg_dump -Fc, 복원 가능).
         #
         # ★std_financials_calendar 는 함께 안 지운다 — calendar_financials 뷰를 통해
         # app/data/screen_window.py·series.py·quarter_change.py·app/views/company_page.py
         # 가 현재도 읽는 활성 소비자라(이산분기 CQ1~CQ4), 별도 이식 없이 지우면 깨진다.
         """
        CREATE OR REPLACE VIEW standard_financials AS
        SELECT
            v3.corp_code, v3.fiscal_year, v3.fiscal_period, v3.statement_type,
            1::smallint AS version,
            v3.period_end,
            TRUE AS is_ifrs,
            COALESCE(v3.source_rcepts->>'BS', v3.source_rcepts->>'IS', v3.source_rcepts->>'CF')::varchar(14) AS rcept_no,
            v3.total_assets, v3.current_assets, v3.cash, v3.receivables, v3.inventory, v3.ppe, v3.intangibles,
            v3.total_liabilities, v3.current_liabilities, v3.short_term_debt, v3.long_term_debt,
            v3.total_equity, v3.controlling_equity, v3.retained_earnings, v3.trade_payables,
            v3.revenue, v3.cogs, v3.gross_profit, v3.sga, v3.rd_expense, v3.operating_income,
            v3.interest_expense, v3.ebt, v3.tax_expense, v3.net_income, v3.controlling_ni,
            v3.cfo, v3.cfi, v3.cff, v3.capex, v3.dividends_paid,
            v3.depreciation, v3.amortization, v3.da_total, v3.ebitda, v3.fcf, v3.net_debt, v3.shares_out,
            v3.data_quality,
            NULL::timestamp without time zone AS superseded_at,
            v3.built_at AS calculated_at,
            COALESCE(fa.gate_status, 'unaudited') AS gate_b_status,
            v3.industry_lines
        FROM std_financials_v3 v3
        LEFT JOIN face_audit fa
          ON  fa.corp_code = v3.corp_code
          AND fa.fiscal_year = v3.fiscal_year
          AND fa.fiscal_period = v3.fiscal_period
          AND fa.statement_type = v3.statement_type
          AND NOT COALESCE(fa.is_stub, false)
          AND fa.source_version = 'v3'
        WHERE COALESCE(fa.gate_status, 'unaudited') <> 'fail_a';

        DROP TABLE IF EXISTS std_financials_v2;
        """),

        ("2026_09_extended_financials_v3_view",
         # 계층2 GC 트랙(docs/plans/extended_financials_v3_label_based_design_2026-09-01.md
         # §3-4) — extended_financials 뷰를 fact_v2(acode 기반) 경유에서
         # extended_facts_v3(라벨 기반, fin2/layer3/combine.py::combine_full()의
         # confirmed 중 DIRECT_MAP 밖 확장 캐노니컬을 build_corp() 이 상시 upsert) 로
         # 전환한다. extended_facts_v3 테이블은 create_all 이 생성(위 규칙과 동일 순서).
         #
         # n_facts=1 고정: 옛 값(COUNT(DISTINCT amount_won), fact_v2 의 원시 다중매치 개수)은
         # 더 이상 성립하지 않는다 — confirmed 는 이미 _resolve() 가 충돌을 해소한 단일값이라
         # "여러 금액이 같은 canonical 에 걸리는" 신호 자체가 없다(설계문서 §3-4/§4-①,
         # dq_assertions.py::extended_financials_n_facts_outlier 는 이 시점부터 상시 0건 —
         # 같은 커밋에서 폐기).
         #
         # ★note.* 확장 캐노니컬(employee_benefits/raw_materials_used)은 이 뷰가 처음
         # extended_facts_v3 로 전환된 시점(이 마이그레이션)엔 없었다 — combine.py 의
         # 일반 라벨매핑이 이 두 canonical 을 만들지 못해 당시 조용히 앱 노출이 끊겼다.
         # 같은 날 후속 트랙(`docs/plans/factv2_sync_scripts_migration_design_2026-09-01.md`
         # Track 1)이 collector/expense_nature_sync.py 를 extended_facts_v3 직접 upsert로
         # 전환 + 과거분 소급 이관까지 완료해 복구했다.
         # DROP+CREATE(OR REPLACE 아님): 컬럼 타입이 바뀐다(fact_v2.canonical_account
         # VARCHAR(120) → extended_facts_v3.canonical_account VARCHAR(40)) — PostgreSQL은
         # CREATE OR REPLACE VIEW로 기존 컬럼 타입 변경을 거부한다(InvalidTableDefinition).
         """
        DROP VIEW IF EXISTS extended_financials;
        CREATE VIEW extended_financials AS
        SELECT ef.corp_code, ef.fiscal_year, ef.fiscal_period, ef.statement_type AS basis,
               ef.canonical_account, ef.amount_won, 1 AS n_facts,
               COALESCE(s.source_rcepts->>'BS', s.source_rcepts->>'IS', s.source_rcepts->>'CF') AS source_rcept_no
        FROM extended_facts_v3 ef
        JOIN std_financials_v3 s
          ON s.corp_code = ef.corp_code AND s.fiscal_year = ef.fiscal_year
         AND s.fiscal_period = ef.fiscal_period AND s.statement_type = ef.statement_type;
        """),

        ("2026_09_fact_v2_drop",
         # fact_v2 GC 트랙 §4-4(`docs/plans/factv2_sync_scripts_migration_design_
         # 2026-09-01.md`) — `fact_v2`(55GB) DROP. 선행조건 전부 충족:
         #   · extended_financials 뷰: 위 2026_09_extended_financials_v3_view 마이그레이션에서
         #     이미 extended_facts_v3 단일소스로 전환(fact_v2 참조 0).
         #   · 유일 남은 소비자(collector/cf_da_sync.py·expense_nature_sync.py 의 fact_v2
         #     upsert)는 Track1(employee_benefits/raw_materials_used → extended_facts_v3
         #     이식, 과거분 3,387행 소급 완료)/Track2(D&A 계열 은퇴, cf_da_sync.py 배선
         #     제거) 로 정리 완료.
         #   · pg_depend 전수 재확인(2026-09-01) — 의존 뷰/FK 0건.
         #   · fin2/extract/xbrl.py::store_facts() 에 RuntimeError 가드 추가(유일 쓰기
         #     경로, standardize_corp() 의 std_financials_v2 가드와 동일 패턴).
         # 백업: NAS(tj_finance_data)/db_backup/fact_v2_backup_2026-09-01.dump
         # (pg_dump -Fc -t fact_v2, 복원 가능).
         """
        DROP TABLE IF EXISTS fact_v2;
        """),

        ("2026_09_std_financials_v3_lease_borrowings",
         # P1A(2026-09-03, docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md
         # §Phase 1, 설계 확정 2026-08-22 §3.12 T0~T7) — v2 파리티 마지막 3컬럼.
         # v2 는 위 484-486행에서 이미 같은 3컬럼을 std_financials_v2 에 추가했다
         # (2026-07-18 "C 합산"). std_financials_v3 에도 동일 계약으로 신설 —
         # account_maps/bs_accounts.py(bs.lease_current/_noncurrent 신설)·
         # account_maps/cf_accounts.py(cf.borrow_proceeds_st/_lt·cf.borrow_repaid_
         # st/_lt 신설)가 카탈로그를 분해했고, fin2/layer3/combine.py 가
         # fin2/standardize/rules.py::rule_additive_lease/rule_additive_borrowings
         # (v2 코드 그대로 재사용, 신규 작성 아님)로 합산해 채운다. ADD COLUMN(nullable,
         # DEFAULT 없음)이라 PG11+ 에서 카탈로그만 바뀜(위 561행 주석 참고, 즉시 완료).
         """
        ALTER TABLE std_financials_v3 ADD COLUMN IF NOT EXISTS lease_liability BIGINT;
        ALTER TABLE std_financials_v3 ADD COLUMN IF NOT EXISTS borrowings_proceeds BIGINT;
        ALTER TABLE std_financials_v3 ADD COLUMN IF NOT EXISTS borrowings_repaid BIGINT;
        """),

        ("2026_09_std_financials_v3_unit_overrides",
         # 원문 자기모순 필링 수동 단위교정(2026-09-06, docs/plans/unit_override_self_
         # contradictory_filings_design_2026-09-06.md) — v2-drop-remaining-backlog
         # (가+라) 그룹: 표 자신이 인쇄한 단위 라벨이 실제 자릿수와 안 맞는 케이스(코드
         # 버그 아님, 원문 표기 오류). report_lines는 원문 그대로 두고, combine.py 집계
         # 단계에서 fin2/layer3/unit_overrides.py 의 curated 배수로 교정한 뒤 이 컬럼에
         # 근거를 남긴다. ADD COLUMN(nullable, DEFAULT 없음)이라 PG11+ 에서 즉시 완료.
         """
        ALTER TABLE std_financials_v3 ADD COLUMN IF NOT EXISTS unit_overrides JSONB;
        """),
    ]

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT now()
            )
        """))
        applied = {row[0] for row in conn.execute(text("SELECT id FROM schema_migrations"))}

    pending = [(mid, sql) for mid, sql in migrations if mid not in applied]
    if not pending:
        logger.info(f"마이그레이션: 신규 없음 (전체 {len(migrations)}건 적용됨)")
        return

    for mid, sql in pending:
        with engine.begin() as conn:
            conn.execute(text(sql))
            conn.execute(text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": mid})

    logger.info(f"마이그레이션 {len(pending)}건 신규 적용 완료 "
                f"(전체 {len(migrations)}건 중 스킵 {len(migrations) - len(pending)}건)")


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
