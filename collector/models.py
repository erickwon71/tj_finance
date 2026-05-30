"""
SQLAlchemy ORM 모델 정의
테이블:
  Phase 1: corporations / filings / download_tasks / collection_runs
  Phase 2: financial_facts / unknown_accounts / standard_financials / stock_prices
  Phase 6: executives / order_backlog
"""
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float,
    ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── 1. 기업 마스터 ─────────────────────────────────────────────────────
class Corporation(Base):
    """
    DART corp_code 기준 기업 마스터
    - stock_code 있는 것 = 상장 기업
    - market: KOSPI / KOSDAQ / KONEX / None(비상장)
    """
    __tablename__ = "corporations"

    corp_code        = Column(String(8),   primary_key=True, comment="DART 고유번호 8자리")
    stock_code       = Column(String(6),   nullable=True,  index=True,  comment="KRX 종목코드")
    corp_name        = Column(String(200), nullable=False,               comment="기업명")
    market           = Column(String(10),  nullable=True,               comment="KOSPI/KOSDAQ/KONEX")
    fiscal_month     = Column(SmallInteger, default=12,                  comment="결산월 1~12 (사업보고서 (YYYY.MM)에서 도출, 기본 12월)")
    is_active        = Column(Boolean,     default=True,                 comment="현재 상장 여부")
    dart_modify_date = Column(String(8),   nullable=True,               comment="DART 최종변경일(yyyymmdd)")
    last_filing_sync = Column(DateTime,    nullable=True,               comment="공시목록 마지막 수집 시각")
    created_at       = Column(DateTime,    default=datetime.utcnow)
    updated_at       = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    filings          = relationship("Filing", back_populates="corporation", lazy="dynamic")

    def __repr__(self):
        return f"<Corporation {self.corp_code} {self.corp_name}>"

    def safe_name(self) -> str:
        """파일시스템에 안전한 기업명 (특수문자 제거)"""
        import re
        return re.sub(r'[\\/:*?"<>|]', '_', self.corp_name)


# ── 2. 공시 목록 ────────────────────────────────────────────────────────
class Filing(Base):
    """
    DART 공시 메타데이터 (list API 결과)
    - 기재정정 처리: is_final=True인 행만 다운로드 대상
    - superseded_by: 이 공시를 대체한 정정공시의 rcept_no
    """
    __tablename__ = "filings"

    rcept_no      = Column(String(14), primary_key=True,              comment="접수번호 14자리")
    corp_code     = Column(String(8),  ForeignKey("corporations.corp_code"), nullable=False, index=True)
    corp_name     = Column(String(200), nullable=True)
    report_nm     = Column(String(500), nullable=True,                comment="원본 보고서명")
    report_type   = Column(String(10),  nullable=False, index=True,   comment="annual/half/quarter")
    fiscal_year   = Column(Integer,     nullable=True,  index=True,   comment="회계연도")
    fiscal_period = Column(String(5),   nullable=True,               comment="FY/H1/Q1/Q3")
    filed_at      = Column(Date,        nullable=True,  index=True,   comment="접수일자")
    corp_cls      = Column(String(1),   nullable=True,               comment="Y:유가 K:코스닥 N:코넥스 E:기타")
    is_amendment  = Column(Boolean,     default=False,               comment="기재정정 여부")
    superseded_by = Column(String(14),  nullable=True,               comment="대체한 정정공시 rcept_no")
    is_final      = Column(Boolean,     default=True,  index=True,   comment="최종본 여부(다운로드 대상)")
    created_at    = Column(DateTime,    default=datetime.utcnow)
    updated_at    = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    corporation   = relationship("Corporation", back_populates="filings")
    download_task = relationship("DownloadTask", back_populates="filing", uselist=False)

    __table_args__ = (
        # 동일 (기업 + 보고서유형 + 회계연도 + 기간) 묶음에서 최종본 1개 확인용 인덱스
        Index("ix_filings_group", "corp_code", "report_type", "fiscal_year", "fiscal_period"),
    )

    def __repr__(self):
        return f"<Filing {self.rcept_no} {self.corp_name} {self.report_nm}>"


# ── 3. 다운로드 작업 ────────────────────────────────────────────────────
class DownloadTask(Base):
    """
    파일 다운로드 상태 추적
    status: pending → downloading → completed / failed / skipped
    """
    __tablename__ = "download_tasks"

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    rcept_no         = Column(String(14), ForeignKey("filings.rcept_no"), unique=True, nullable=False, index=True)
    status           = Column(String(15), default="pending", nullable=False, index=True,
                               comment="pending/downloading/completed/failed/skipped")
    file_path        = Column(String(1000), nullable=True,  comment="저장된 파일 절대경로")
    file_type        = Column(String(5),   nullable=True,   comment="pdf/html/hwp/zip/xml")
    file_size        = Column(BigInteger,  nullable=True,   comment="바이트")
    attempts         = Column(Integer,     default=0,       comment="시도 횟수")
    last_error       = Column(Text,        nullable=True,   comment="마지막 오류 메시지")
    last_attempt_at  = Column(DateTime,    nullable=True)
    completed_at     = Column(DateTime,    nullable=True)
    created_at       = Column(DateTime,    default=datetime.utcnow)

    # Phase 2: 파싱 상태 추적
    parse_status     = Column(String(15), nullable=True, index=True,
                               comment="pending/parsing/success/partial/failed/skip")
    parse_error      = Column(Text,       nullable=True)
    parsed_at        = Column(DateTime,   nullable=True)
    parsed_facts     = Column(Integer,    nullable=True, comment="추출된 fact 행 수")
    parser_track     = Column(String(15), nullable=True, comment="A/B/PDF/PDF_AMEND")

    filing           = relationship("Filing", back_populates="download_task")

    def __repr__(self):
        return f"<DownloadTask {self.rcept_no} [{self.status}]>"


# ── 4. 실행 이력 ────────────────────────────────────────────────────────
class CollectionRun(Base):
    """
    수집 실행 로그 (하루 단위 또는 수동 실행 단위)
    run_type: corp_sync / filing_sync / download
    """
    __tablename__ = "collection_runs"

    id         = Column(Integer,  primary_key=True, autoincrement=True)
    run_type   = Column(String(30), nullable=False, comment="corp_sync/filing_sync/download")
    started_at = Column(DateTime,  nullable=False,  default=datetime.utcnow)
    ended_at   = Column(DateTime,  nullable=True)
    total      = Column(Integer,   default=0)
    completed  = Column(Integer,   default=0)
    failed     = Column(Integer,   default=0)
    skipped    = Column(Integer,   default=0)
    api_calls  = Column(Integer,   default=0,  comment="해당 실행에서 소비한 API 콜 수")
    notes      = Column(Text,      nullable=True)

    def __repr__(self):
        return f"<CollectionRun {self.run_type} {self.started_at:%Y-%m-%d %H:%M}>"


# ══ Phase 2 테이블 ═══════════════════════════════════════════════════════════

# ── 5. 재무 원시 데이터 ─────────────────────────────────────────────────────
class FinancialFact(Base):
    """
    DART XML/PDF에서 파싱된 계정과목별 금액 (원시 데이터)

    레이어 구조:
      financial_facts (원시) → standard_financials (집계/표준화)

    파티셔닝: PostgreSQL 선언적 파티셔닝 (fiscal_year 기준 RANGE)
    PostgreSQL에서 파티션 생성 필요:
      CREATE TABLE financial_facts_y1999_2009 PARTITION OF financial_facts FOR VALUES FROM (1999) TO (2010);
      CREATE TABLE financial_facts_y2010_2019 PARTITION OF financial_facts FOR VALUES FROM (2010) TO (2020);
      CREATE TABLE financial_facts_y2020_2029 PARTITION OF financial_facts FOR VALUES FROM (2020) TO (2030);
      CREATE TABLE financial_facts_default    PARTITION OF financial_facts DEFAULT;
    """
    __tablename__ = "financial_facts"

    id                    = Column(BigInteger,   primary_key=True, autoincrement=True)
    corp_code             = Column(String(8),    nullable=False, index=True, comment="DART 기업코드")
    rcept_no              = Column(String(14),   ForeignKey("filings.rcept_no"), nullable=False, index=True)
    fs_type               = Column(String(6),    nullable=False,
                                    comment="BS_C/IS_C/CF_C/BS_S/IS_S/CF_S/NOTE_C/NOTE_S")
    statement_type        = Column(String(12),   nullable=False,
                                    comment="consolidated / separate")
    period_type           = Column(String(15),   nullable=False,
                                    comment="annual / cumulative_ytd / point_in_time")
    account_code          = Column(String(120),  nullable=False,
                                    comment="표준 계정 코드 (bs.current_assets 등) 또는 unknown.xxx")
    account_name_raw      = Column(String(300),  nullable=False, comment="원문 계정과목명 또는 XBRL ACODE")
    period_end            = Column(Date,         nullable=True,  comment="결산 기준일 (비12월 결산 대응)")
    fiscal_year           = Column(SmallInteger, nullable=False, index=True)
    fiscal_period         = Column(String(5),    nullable=False, comment="FY/H1/Q1/Q3")
    amount                = Column(BigInteger,   nullable=True,  comment="금액 (원 단위, unit_multiplier 적용 후 — parse_amount()가 변환하여 저장)")
    unit_multiplier       = Column(Integer,     default=1,       comment="원본 표기 단위 출처 메타: 1=원, 1000=천원, 1000000=백만원 (금액 계산에 재사용 불필요)")
    # amount_won = amount * unit_multiplier (원 단위). Python 레이어에서 계산 (GENERATED AS 불사용)
    col_index             = Column(SmallInteger, nullable=False,
                                    comment="0=당기, 1=전기, 2=전전기")
    row_order             = Column(SmallInteger, nullable=True)
    is_subtotal           = Column(Boolean,      default=False,  comment="합계/소계 행 여부")
    is_ifrs               = Column(Boolean,      default=True)
    source_format         = Column(String(15),   nullable=False,
                                    comment="xbrl_acode / xml_text / pdf_plumber / pdf_camelot / pdf_ocr")
    extraction_confidence = Column(Float,        default=1.0)
    parser_track          = Column(String(15),   nullable=True,  comment="A / B / PDF / PDF_AMEND")
    is_superseded         = Column(Boolean,      default=False,  comment="기재정정으로 대체된 데이터")
    source_ref            = Column(String(120),  nullable=True,  comment="원본 문서 내 위치: PDF='p42/t3/r5', XBRL='BS_C/ACODE=ifrs-full_Assets', XML='IS_S/row=12'")
    parsed_at             = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "corp_code", "rcept_no", "fs_type", "account_code", "col_index",
            name="uq_financial_facts"
        ),
        Index("ix_ff_corp_year",  "corp_code", "fiscal_year", "statement_type"),
        Index("ix_ff_account",    "account_code", "fiscal_year"),
        Index("ix_ff_cross",      "fiscal_year", "fiscal_period", "account_code"),
    )

    @property
    def amount_won(self):
        """원 단위 정규화 금액"""
        if self.amount is None:
            return None
        return self.amount * (self.unit_multiplier or 1)

    def __repr__(self):
        return f"<FinancialFact {self.corp_code} {self.fiscal_year} {self.account_code} {self.col_index}>"


# ── 6. 미매핑 계정과목 추적 ─────────────────────────────────────────────────
class UnknownAccount(Base):
    """
    3단계 매핑에서 실패한 계정과목 집계.
    주기적으로 검토해 account_maps/*.py 에 alias 추가.
    """
    __tablename__ = "unknown_accounts"

    account_name_normalized = Column(String(300), primary_key=True, comment="정규화된 계정과목명")
    fs_type                 = Column(String(6),   nullable=True)
    occurrence_count        = Column(Integer,     default=1)
    corp_sample             = Column(String(8),   nullable=True, comment="처음 발견한 기업코드")
    first_seen_at           = Column(DateTime,    default=datetime.utcnow)
    last_seen_at            = Column(DateTime,    default=datetime.utcnow)
    suggested_code          = Column(String(120), nullable=True, comment="검토 후 수동 입력할 표준 코드")

    def __repr__(self):
        return f"<UnknownAccount '{self.account_name_normalized}' ({self.occurrence_count}회)>"


# ── 7. 표준화 재무제표 (와이드 테이블, 스크리닝 최적화) ─────────────────────
class StandardFinancial(Base):
    """
    financial_facts를 집계한 와이드 테이블.
    PER/PBR 스크리닝 등 Cross-sectional 쿼리에 최적화.

    갱신: parse 완료 후 배치 계산. version으로 기재정정 이력 관리.
    """
    __tablename__ = "standard_financials"

    corp_code           = Column(String(8),    primary_key=True)
    fiscal_year         = Column(SmallInteger, primary_key=True)
    fiscal_period       = Column(String(5),    primary_key=True)
    statement_type      = Column(String(12),   primary_key=True)
    version             = Column(SmallInteger, primary_key=True, default=1)
    period_end          = Column(Date,         nullable=True)
    is_ifrs             = Column(Boolean,      nullable=True)
    rcept_no            = Column(String(14),   nullable=True)

    # ── 재무상태표 (BS) ───────────────────────────────────────────────
    total_assets         = Column(BigInteger, nullable=True)
    current_assets       = Column(BigInteger, nullable=True)
    cash                 = Column(BigInteger, nullable=True)
    receivables          = Column(BigInteger, nullable=True)
    inventory            = Column(BigInteger, nullable=True)
    ppe                  = Column(BigInteger, nullable=True)
    intangibles          = Column(BigInteger, nullable=True)
    total_liabilities    = Column(BigInteger, nullable=True)
    current_liabilities  = Column(BigInteger, nullable=True)
    short_term_debt      = Column(BigInteger, nullable=True)
    long_term_debt       = Column(BigInteger, nullable=True)
    total_equity         = Column(BigInteger, nullable=True)
    controlling_equity   = Column(BigInteger, nullable=True)
    retained_earnings    = Column(BigInteger, nullable=True)
    trade_payables       = Column(BigInteger, nullable=True)

    # ── 손익계산서 (IS) ───────────────────────────────────────────────
    revenue              = Column(BigInteger, nullable=True)
    cogs                 = Column(BigInteger, nullable=True)
    gross_profit         = Column(BigInteger, nullable=True)
    sga                  = Column(BigInteger, nullable=True)
    rd_expense           = Column(BigInteger, nullable=True)   # 연구개발비
    operating_income     = Column(BigInteger, nullable=True)
    interest_expense     = Column(BigInteger, nullable=True)
    ebt                  = Column(BigInteger, nullable=True)
    tax_expense          = Column(BigInteger, nullable=True)
    net_income           = Column(BigInteger, nullable=True)
    controlling_ni       = Column(BigInteger, nullable=True)

    # ── 현금흐름표 (CF) ───────────────────────────────────────────────
    cfo                  = Column(BigInteger, nullable=True)
    cfi                  = Column(BigInteger, nullable=True)
    cff                  = Column(BigInteger, nullable=True)
    capex                = Column(BigInteger, nullable=True)
    dividends_paid       = Column(BigInteger, nullable=True)

    # ── 주석에서 추출 ─────────────────────────────────────────────────
    depreciation         = Column(BigInteger, nullable=True)
    amortization         = Column(BigInteger, nullable=True)
    da_total             = Column(BigInteger, nullable=True)

    # ── 파생 계산 ─────────────────────────────────────────────────────
    ebitda               = Column(BigInteger, nullable=True)  # op_income + da_total
    fcf                  = Column(BigInteger, nullable=True)   # cfo - abs(capex)
    net_debt             = Column(BigInteger, nullable=True)   # short+long debt - cash

    # ── 주식수 (stock_prices에서 period_end 기준 조회) ─────────────────
    shares_out           = Column(BigInteger, nullable=True, comment="상장주식수")

    # ── 메타 ──────────────────────────────────────────────────────────
    data_quality         = Column(SmallInteger, default=0,
                                   comment="0:미검증 1:정상 2:경고 3:오류")
    superseded_at        = Column(DateTime,    nullable=True,
                                   comment="기재정정으로 대체된 시각")
    calculated_at        = Column(DateTime,    default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "corp_code", "fiscal_year", "fiscal_period", "statement_type", "version",
            name="uq_standard_financials"
        ),
        Index(
            "ix_sf_screening",
            "fiscal_year", "fiscal_period", "statement_type",
        ),
        Index("ix_sf_corp_year", "corp_code", "fiscal_year"),
    )

    def __repr__(self):
        return f"<StandardFinancial {self.corp_code} {self.fiscal_year}{self.fiscal_period} v{self.version}>"


# ── 8. 주가 데이터 ──────────────────────────────────────────────────────────
class StockPrice(Base):
    """
    pykrx에서 수집한 일별 주가 및 시총.
    밸류에이션 멀티플(PER/PBR/EV-EBITDA) 계산에 사용.
    """
    __tablename__ = "stock_prices"

    stock_code   = Column(String(6),  primary_key=True)
    trade_date   = Column(Date,       primary_key=True)
    close_price  = Column(Integer,    nullable=False)
    market_cap   = Column(BigInteger, nullable=True, comment="시가총액 (원)")
    shares_out   = Column(BigInteger, nullable=True, comment="상장주식수")

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_stock_prices"),
        Index("ix_sp_stock_date", "stock_code", "trade_date"),
    )


# ── 9. 검증 결과 ────────────────────────────────────────────────────────────

class VerificationResult(Base):
    """
    계층형 재무 정합성 검증 결과.
    Layer 1: BS/IS/CF 항등식
    Layer 2: XBRL 소계 대조
    Layer 3: 기간 연속성 (전기 기말 = 당기 기초)
    Layer 4: 수동 대조 안내 (source_ref 기반)
    """
    __tablename__ = "verification_results"

    id             = Column(BigInteger,   primary_key=True, autoincrement=True)
    corp_code      = Column(String(8),    nullable=False, index=True)
    fiscal_year    = Column(SmallInteger, nullable=False)
    fiscal_period  = Column(String(5),    nullable=False)
    statement_type = Column(String(12),   nullable=False)
    rcept_no       = Column(String(14),   nullable=True)
    check_name     = Column(String(40),   nullable=False)
    layer          = Column(SmallInteger, nullable=True, comment="1=항등식 2=소계 3=연속성 4=수동")
    passed         = Column(Boolean,      nullable=True)
    lhs_label      = Column(String(60),   nullable=True)
    rhs_label      = Column(String(60),   nullable=True)
    lhs_value      = Column(BigInteger,   nullable=True, comment="원 단위")
    rhs_value      = Column(BigInteger,   nullable=True, comment="원 단위")
    diff_pct       = Column(Float,        nullable=True)
    tolerance_pct  = Column(Float,        nullable=True, default=0.5)
    source_ref     = Column(String(120),  nullable=True, comment="fail 항목의 원본 위치")
    checked_at     = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "corp_code", "fiscal_year", "fiscal_period", "statement_type", "check_name",
            name="uq_verification"
        ),
        Index("ix_verif_corp_year", "corp_code", "fiscal_year", "fiscal_period"),
        Index("ix_verif_failed", "passed"),
    )

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"<VerificationResult {self.corp_code} {self.fiscal_year} {self.check_name} [{status}]>"


# ── 10. 임원 현황 ────────────────────────────────────────────────────────────
class Executive(Base):
    """
    DART exctvSttus API 기반 임원 현황.
    hmvAuditIndvdlBySttus API로 5억원 이상 고액 보수도 병합.
    """
    __tablename__ = "executives"

    id              = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code       = Column(String(8),    nullable=False,   index=True)
    fiscal_year     = Column(SmallInteger, nullable=False)
    name            = Column(String(50),   nullable=False)
    gender          = Column(String(4),    nullable=True)   # 남/여
    birth_ym        = Column(String(10),   nullable=True)   # "1968.06"
    position        = Column(String(150),  nullable=True)   # 직위
    is_registered   = Column(Boolean,      nullable=True)   # 등기임원 여부
    is_fulltime     = Column(Boolean,      nullable=True)   # 상근 여부
    responsibility  = Column(String(300),  nullable=True)   # 담당업무
    main_career     = Column(String(500),  nullable=True)   # 주요경력
    shareholder_rel = Column(String(100),  nullable=True)   # 최대주주관계
    tenure_period   = Column(String(60),   nullable=True)   # "2016.11.01 ~ 2026.03.31"
    tenure_end      = Column(String(20),   nullable=True)   # 임기만료일
    compensation    = Column(BigInteger,   nullable=True,
                             comment="보수총액(원), DART 5억이상 공시 기준")
    fetched_at      = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "fiscal_year", "name", "position",
                         name="uq_executives"),
        Index("ix_exec_corp_year", "corp_code", "fiscal_year"),
    )


# ── 10. 수주잔고 ────────────────────────────────────────────────────────────
class OrderBacklog(Base):
    """
    수주잔고 (건설/조선/방산/반도체 등 수주 기반 업종).
    사업보고서 '수주상황' 섹션 파싱 결과 저장.
    """
    __tablename__ = "order_backlog"

    id           = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code    = Column(String(8),    nullable=False,   index=True)
    fiscal_year  = Column(SmallInteger, nullable=False)
    category     = Column(String(150),  nullable=True)   # 수주 분류 (품목/계약처)
    backlog_amt  = Column(BigInteger,   nullable=True)   # 수주잔고 (원)
    new_orders   = Column(BigInteger,   nullable=True)   # 당기 신규수주
    completed    = Column(BigInteger,   nullable=True)   # 당기 완성/납품
    unit         = Column(String(20),   nullable=True,
                          comment="원래 공시 단위 (억원/백만원 등)")
    source       = Column(String(20),   nullable=True,
                          comment="html_parse / dart_api")
    rcept_no     = Column(String(14),   nullable=True)
    fetched_at   = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_order_corp_year", "corp_code", "fiscal_year"),
    )
