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
