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
from sqlalchemy.dialects.postgresql import JSONB
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
    coverage_class   = Column(String(20),  default="periodic",           comment="periodic=표준 정기보고 대상 / non_periodic=펀드·집합투자기구 등 정기보고 미대상(완전성 모집단 제외, 추후 보강)")
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
    fiscal_year   = Column(Integer,     nullable=True,  index=True,   comment="회계연도(기간이 끝나는 달력연도)")
    fiscal_period = Column(String(5),   nullable=True,               comment="FY/H1/Q1/Q3")
    filed_at      = Column(Date,        nullable=True,  index=True,   comment="접수일자")
    # ── 결산월 변경 대응(PRD 01a): 보고서 (YYYY.MM) 기반 기간 정체성 ──
    period_end_date   = Column(Date,        nullable=True, index=True, comment="보고 기간 기말일 (report_nm (YYYY.MM)의 말일). 라벨/충돌해소의 정체성 키")
    period_end_month  = Column(SmallInteger, nullable=True,           comment="기말 월 (1~12)")
    fye_month_at_time = Column(SmallInteger, nullable=True,           comment="이 보고 시점에 유효한 결산월(FYE timeline 도출)")
    is_stub           = Column(Boolean,     default=False, index=True, comment="결산월 변경 전환기의 12개월 미만 회계기간 소속")
    corp_cls      = Column(String(1),   nullable=True,               comment="Y:유가 K:코스닥 N:코넥스 E:기타")
    is_amendment  = Column(Boolean,     default=False,               comment="기재정정([기재정정]) 여부 — 본문 정정")
    is_attachment_amendment = Column(Boolean, default=False, index=True, comment="첨부정정([첨부정정]) 여부 — 본문 동일·첨부만 정정")
    superseded_by = Column(String(14),  nullable=True,               comment="대체한 정정공시 rcept_no")
    is_final      = Column(Boolean,     default=True,  index=True,   comment="최종본 여부(다운로드 대상). 그룹키=period_end_date(없으면 fy+fp)")
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

    # PRD 02 Gate A: 다운로드 유효성 검증
    gate_a_status    = Column(String(12), nullable=True, index=True,
                               comment="PASS/FAIL — 다운로드 무결성·재무제표존재 검증 결과")
    gate_a_reason    = Column(String(20), nullable=True,
                               comment="MISSING_FILE/ZERO_BYTE/BAD_MAGIC/NO_STATEMENTS 등 실패 사유")
    gate_a_checked_at = Column(DateTime,  nullable=True)

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


# ── 5b. fin2 E-레이어 원시 사실 (fact_v2) ───────────────────────────────────
class FactV2(Base):
    """
    fin2 재구축의 추출(E) 산출물. 단위·기간·연결/별도·차원을 **추론이 아닌 저장**.

    financial_facts 와의 차이:
      - ADECIMAL(단위 권위)·ACONTEXT(구조: basis/기간/instant·duration/extra_dims)를
        그대로 보존. 텍스트 proximity 단위탐지·연결별도 추정 폐기.
      - **is_superseded 컬럼 없음**: 기재정정 정합은 R-레이어(statement_source)가
        period·basis·statement 단위로 source filing 을 선택해 처리(over-supersede 구조 제거).
      - period_end 를 저장하지 않음: ACONTEXT 는 회계연도+instant/duration 만 주므로
        실제 날짜는 R/S-레이어에서 기업 결산월(fiscal_month)로 산출(현 period_end 불신 해소).

    신규 테이블이므로 Base.metadata.create_all() 로 자동 생성(별도 마이그레이션 불요).
    대용량화 시 financial_facts 처럼 report_fiscal_year 기준 파티셔닝 추가 가능.
    """
    __tablename__ = "fact_v2"

    id                 = Column(BigInteger,   primary_key=True, autoincrement=True)
    corp_code          = Column(String(8),    nullable=False, index=True)
    rcept_no           = Column(String(14),   ForeignKey("filings.rcept_no"), nullable=False, index=True)

    # 보고서(파일) 메타 — 이 fact 가 실린 정기보고서
    report_fiscal_year   = Column(SmallInteger, nullable=False, index=True, comment="보고서 회계연도")
    report_fiscal_period = Column(String(5),    nullable=False, comment="보고서 기간 FY/H1/Q1/Q3")

    # 계정
    acode              = Column(String(255),  nullable=False, comment="원문 XBRL ACODE/계정명 (ifrs-full 표준 개념명은 최대 ~180자)")
    canonical_account  = Column(String(120),  nullable=True,  comment="concept_map 매핑 결과(미매핑 시 NULL)")

    # ACONTEXT 구조 파싱 결과 (acontext.parse_acontext)
    basis              = Column(String(12),   nullable=True,  comment="consolidated/separate/NULL(불명→파일 fin_type 폴백)")
    context_fiscal_year= Column(SmallInteger, nullable=True,  index=True, comment="데이터의 절대 회계연도(C/P/BP 해석)")
    col_index          = Column(SmallInteger, nullable=True,  comment="0=당기 1=전기 2=전전기")
    period_kind        = Column(String(8),    nullable=True,  comment="instant(BS) / duration(IS·CF)")
    period_type        = Column(String(4),    nullable=True,  comment="FY/FQ/FH")
    is_cumulative      = Column(Boolean,      default=False,  comment="FQA/FHA 누적")
    extra_dims         = Column(JSONB,        nullable=True,  comment="연결/별도 외 차원 [[axis,member],...] (SCE 등)")
    is_dimensional     = Column(Boolean,      default=False,  index=True, comment="extra_dims 보유 → statement 합계 제외 대상")

    # 단위·금액 (ADECIMAL 권위)
    adecimal           = Column(SmallInteger, nullable=True,  comment="원본 ADECIMAL (단위 출처)")
    amount_won         = Column(BigInteger,   nullable=True,  comment="원 단위 정규화 금액 = 표기값 × 10^(-adecimal)")

    # 연원/추적
    source_format      = Column(String(15),   nullable=False, default="xbrl_acode",
                                comment="xbrl_acode / xml_text / pdf_* (P2)")
    source_ref         = Column(String(180),  nullable=True,  comment="원본 위치 단서")
    acontext_raw       = Column(String(255),  nullable=True,  comment="원문 ACONTEXT(감사/재파싱용)")
    context_parsed     = Column(Boolean,      default=True,   comment="ACONTEXT 구조 파싱 성공 여부")
    parsed_at          = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        # 한 보고서 내 (ACODE, ACONTEXT) 셀은 유일
        UniqueConstraint("rcept_no", "acode", "acontext_raw", name="uq_fact_v2_cell"),
        # R-레이어: (corp, 데이터연도, 연결/별도)로 source filing 의 facts 조회
        Index("ix_fact_v2_lookup", "corp_code", "context_fiscal_year", "basis"),
        Index("ix_fact_v2_canon",  "canonical_account", "context_fiscal_year"),
    )

    def __repr__(self):
        return (f"<FactV2 {self.corp_code} r{self.rcept_no} {self.acode} "
                f"{self.basis} {self.context_fiscal_year} {self.amount_won}>")


# ── 5c. fin2 R-레이어 statement source 선택 (statement_source) ───────────────
class StatementSource(Base):
    """
    fin2 정합(R) 산출물: (기업·연도·기간·연결별도·재무제표) 단위로 **단일 source filing 선택**.

    over-supersede 구조적 해결:
      기존 파이프라인은 (period,basis) 전체를 '최신 final filing' 하나로 blunt-supersede →
      부분 기재정정이 미정정 statement까지 덮어써 데이터 손실(리메드 2023: 정정본 revenue=283,638).
      fin2 는 BS/IS/CF **각 statement 별로 독립 선택** → 부분정정은 가진 statement만 이김.

    선택 규칙(reconcile.py):
      후보 = fact_v2 에서 해당 (corp, report_fy, report_period, basis) + statement(canonical 접두어)을
             1줄 이상 가진 filing. 점수 = 매핑 canonical 라인 수(완전성), anchor 라인 보유 가산.
      최고점 채택, 동점이면 filed_at 최신(정정 우선).

    S-레이어는 (period,basis) 한 레코드를 BS=선택본·IS=선택본·CF=선택본 으로 조립.
    신규 테이블 → create_all 자동 생성.
    """
    __tablename__ = "statement_source"

    corp_code      = Column(String(8),    primary_key=True)
    fiscal_year    = Column(SmallInteger, primary_key=True)
    fiscal_period  = Column(String(5),    primary_key=True)   # FY/H1/Q1/Q3
    basis          = Column(String(12),   primary_key=True)   # consolidated/separate
    statement      = Column(String(2),    primary_key=True)   # BS/IS/CF
    is_stub        = Column(Boolean,      primary_key=True, default=False,
                            comment="결산월 변경 전환기 stub 회계기간(PRD 01a) — 정상연도와 동일 (fy,fp) 충돌 분리")

    source_rcept_no = Column(String(14),  nullable=False, comment="선택된 source filing")
    line_count      = Column(SmallInteger, nullable=True, comment="선택본의 매핑 canonical 라인 수(완전성)")
    has_anchor      = Column(Boolean,     default=False, comment="anchor 라인(BS=assets/IS=revenue/CF=operating) 보유")
    candidate_count = Column(SmallInteger, nullable=True, comment="경쟁한 filing 수")
    lineage         = Column(JSONB,       nullable=True, comment="후보별 [{rcept,line_count,filed_at,chosen}]")
    reconciled_at   = Column(DateTime,    default=datetime.utcnow)

    __table_args__ = (
        Index("ix_stmt_src_lookup", "corp_code", "fiscal_year", "fiscal_period", "basis"),
    )

    def __repr__(self):
        return (f"<StatementSource {self.corp_code} {self.fiscal_year}{self.fiscal_period} "
                f"{self.basis}/{self.statement} ← r{self.source_rcept_no} ({self.line_count})>")


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


# ── 7b. fin2 S-레이어 표준화 (std_financials_v2) ─────────────────────────────
class StdFinancialV2(Base):
    """
    fin2 표준화(S) 산출물. statement_source 선택을 읽어 (corp,period,basis) 한 레코드 조립.

    standard_financials 와 **동일 값 컬럼 계약**(P5 호환 view 가 이 위에 version=1 상수로 올라감)
    + lineage(bs/is/cf_rcept)·applied_rules(규칙엔진 추적). 표준화 규칙은 fin2/standardize/rules.py
    (현 aggregator 13 휴리스틱을 명명·순서·테스트가능 규칙으로 이식).
    신규 테이블 → create_all 자동 생성.
    """
    __tablename__ = "std_financials_v2"

    corp_code           = Column(String(8),    primary_key=True)
    fiscal_year         = Column(SmallInteger, primary_key=True)
    fiscal_period       = Column(String(5),    primary_key=True)
    statement_type      = Column(String(12),   primary_key=True)
    version             = Column(SmallInteger, primary_key=True, default=1)
    is_stub             = Column(Boolean,      primary_key=True, default=False,
                                 comment="결산월 변경 전환기 stub 회계기간(PRD 01a). 기본 view 는 NOT is_stub 만 노출")
    is_discrete         = Column(Boolean,      primary_key=True, default=False,
                                 comment="분기 환산 이산행(PRD 03 §5.1, Q1~Q4 3개월). 누적 as-filed 와 공존. 기본 view·Gate B 는 NOT is_discrete 만")
    period_end          = Column(Date,         nullable=True)
    is_ifrs             = Column(Boolean,      nullable=True)

    # ── BS ──
    total_assets        = Column(BigInteger, nullable=True)
    current_assets      = Column(BigInteger, nullable=True)
    cash                = Column(BigInteger, nullable=True)
    receivables         = Column(BigInteger, nullable=True)
    inventory           = Column(BigInteger, nullable=True)
    ppe                 = Column(BigInteger, nullable=True)
    intangibles         = Column(BigInteger, nullable=True)
    total_liabilities   = Column(BigInteger, nullable=True)
    current_liabilities = Column(BigInteger, nullable=True)
    short_term_debt     = Column(BigInteger, nullable=True)
    long_term_debt      = Column(BigInteger, nullable=True)
    total_equity        = Column(BigInteger, nullable=True)
    controlling_equity  = Column(BigInteger, nullable=True)
    retained_earnings   = Column(BigInteger, nullable=True)
    trade_payables      = Column(BigInteger, nullable=True)
    # ── IS ──
    revenue             = Column(BigInteger, nullable=True)
    cogs                = Column(BigInteger, nullable=True)
    gross_profit        = Column(BigInteger, nullable=True)
    sga                 = Column(BigInteger, nullable=True)
    rd_expense          = Column(BigInteger, nullable=True)
    operating_income    = Column(BigInteger, nullable=True)
    interest_expense    = Column(BigInteger, nullable=True)
    ebt                 = Column(BigInteger, nullable=True)
    tax_expense         = Column(BigInteger, nullable=True)
    net_income          = Column(BigInteger, nullable=True)
    controlling_ni      = Column(BigInteger, nullable=True)
    # ── CF ──
    cfo                 = Column(BigInteger, nullable=True)
    cfi                 = Column(BigInteger, nullable=True)
    cff                 = Column(BigInteger, nullable=True)
    capex               = Column(BigInteger, nullable=True)
    dividends_paid      = Column(BigInteger, nullable=True)
    # ── 주석/파생 ──
    depreciation        = Column(BigInteger, nullable=True)
    amortization        = Column(BigInteger, nullable=True)
    da_total            = Column(BigInteger, nullable=True)
    ebitda              = Column(BigInteger, nullable=True)
    fcf                 = Column(BigInteger, nullable=True)
    net_debt            = Column(BigInteger, nullable=True)
    shares_out          = Column(BigInteger, nullable=True)

    # ── 메타·연원 ──
    data_quality        = Column(SmallInteger, default=0, comment="0:미검증 1:정상 2:경고 3:오류")
    bs_rcept            = Column(String(14),  nullable=True, comment="BS source filing")
    is_rcept            = Column(String(14),  nullable=True, comment="IS source filing")
    cf_rcept            = Column(String(14),  nullable=True, comment="CF source filing")
    applied_rules       = Column(JSONB,       nullable=True, comment="적용된 규칙 이름 목록")
    calculated_at       = Column(DateTime,    default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version",
                         "is_stub", "is_discrete", name="uq_std_v2"),
        Index("ix_stdv2_screening", "fiscal_year", "fiscal_period", "statement_type"),
        Index("ix_stdv2_corp_year", "corp_code", "fiscal_year"),
    )

    def __repr__(self):
        return f"<StdFinancialV2 {self.corp_code} {self.fiscal_year}{self.fiscal_period} {self.statement_type}>"


# ── 7c. Layer 2 달력 정규화 (PRD 03 §5.3) ────────────────────────────────────
class StdFinancialCalendar(Base):
    """
    PRD 03 §5.3 Layer 2 — 전 기업 12월 달력기준 정규화(파생, 비교·시각화용).

    Layer 1(std_financials_v2, as-filed)의 **이산분기(is_discrete)** 를 period_end 로 달력분기에
    재배열·합산. **Gate B 비적용**(어느 단일 보고서에도 없는 계산값) — 항상 파생 플래그.
    flow(IS/CF)=ΣCQ, stock(BS)=분기말/12-31 스냅샷(합산 금지). 결측분기→CY 미생성(추정 금지).
    """
    __tablename__ = "std_financials_calendar"

    corp_code        = Column(String(8),    primary_key=True)
    calendar_year    = Column(SmallInteger, primary_key=True)
    calendar_period  = Column(String(4),    primary_key=True, comment="CQ1/CQ2/CQ3/CQ4/CY")
    statement_type   = Column(String(12),   primary_key=True, comment="consolidated/separate(=basis)")
    version          = Column(SmallInteger, primary_key=True, default=1)
    period_end       = Column(Date,         nullable=True, comment="CQ=분기말, CY=12-31")
    is_ifrs          = Column(Boolean,      nullable=True)

    # 파생 추적 플래그
    derivation       = Column(String(10),   nullable=True, comment="native(12월결산)|recomposed(비12월 합성)|partial")
    is_complete      = Column(Boolean,      default=False, comment="CY 가 4분기 완비")
    source_lineage   = Column(JSONB,        nullable=True, comment="구성 회계 (fy,fp) 목록")
    data_quality     = Column(SmallInteger, default=0)

    # ── 값 컬럼(std_v2 와 동일 계약) ──
    total_assets        = Column(BigInteger, nullable=True)
    current_assets      = Column(BigInteger, nullable=True)
    cash                = Column(BigInteger, nullable=True)
    receivables         = Column(BigInteger, nullable=True)
    inventory           = Column(BigInteger, nullable=True)
    ppe                 = Column(BigInteger, nullable=True)
    intangibles         = Column(BigInteger, nullable=True)
    total_liabilities   = Column(BigInteger, nullable=True)
    current_liabilities = Column(BigInteger, nullable=True)
    short_term_debt     = Column(BigInteger, nullable=True)
    long_term_debt      = Column(BigInteger, nullable=True)
    total_equity        = Column(BigInteger, nullable=True)
    controlling_equity  = Column(BigInteger, nullable=True)
    retained_earnings   = Column(BigInteger, nullable=True)
    trade_payables      = Column(BigInteger, nullable=True)
    revenue             = Column(BigInteger, nullable=True)
    cogs                = Column(BigInteger, nullable=True)
    gross_profit        = Column(BigInteger, nullable=True)
    sga                 = Column(BigInteger, nullable=True)
    rd_expense          = Column(BigInteger, nullable=True)
    operating_income    = Column(BigInteger, nullable=True)
    interest_expense    = Column(BigInteger, nullable=True)
    ebt                 = Column(BigInteger, nullable=True)
    tax_expense         = Column(BigInteger, nullable=True)
    net_income          = Column(BigInteger, nullable=True)
    controlling_ni      = Column(BigInteger, nullable=True)
    cfo                 = Column(BigInteger, nullable=True)
    cfi                 = Column(BigInteger, nullable=True)
    cff                 = Column(BigInteger, nullable=True)
    capex               = Column(BigInteger, nullable=True)
    dividends_paid      = Column(BigInteger, nullable=True)
    depreciation        = Column(BigInteger, nullable=True)
    amortization        = Column(BigInteger, nullable=True)
    da_total            = Column(BigInteger, nullable=True)
    ebitda              = Column(BigInteger, nullable=True)
    fcf                 = Column(BigInteger, nullable=True)
    net_debt            = Column(BigInteger, nullable=True)
    shares_out          = Column(BigInteger, nullable=True)

    calculated_at       = Column(DateTime,    default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "calendar_year", "calendar_period",
                         "statement_type", "version", name="uq_std_calendar"),
        Index("ix_cal_screening", "calendar_year", "calendar_period", "statement_type"),
        Index("ix_cal_corp", "corp_code", "calendar_year"),
    )

    def __repr__(self):
        return (f"<StdFinancialCalendar {self.corp_code} {self.calendar_year}"
                f"{self.calendar_period} {self.statement_type}>")


# ── 8. 주가 데이터 ──────────────────────────────────────────────────────────
class StockPrice(Base):
    """
    pykrx에서 수집한 일별 주가 및 시총.
    밸류에이션 멀티플(PER/PBR/EV-EBITDA) 계산에 사용.
    """
    __tablename__ = "stock_prices"

    stock_code   = Column(String(6),  primary_key=True)
    trade_date   = Column(Date,       primary_key=True)
    # OHLCV (KRW; volume = shares traded)
    open_price   = Column(Integer,    nullable=True,  comment="시가")
    high_price   = Column(Integer,    nullable=True,  comment="고가")
    low_price    = Column(Integer,    nullable=True,  comment="저가")
    close_price  = Column(Integer,    nullable=False, comment="종가")
    volume       = Column(BigInteger, nullable=True,  comment="거래량(주)")
    market_cap   = Column(BigInteger, nullable=True,  comment="시가총액 (원)")
    shares_out   = Column(BigInteger, nullable=True,  comment="상장주식수")
    # Valuation fundamentals (KRX 제공: PER/PBR/DIV = ratios, EPS/BPS/DPS = KRW/share)
    per          = Column(Float,      nullable=True,  comment="주가수익비율")
    pbr          = Column(Float,      nullable=True,  comment="주가순자산비율")
    eps          = Column(BigInteger, nullable=True,  comment="주당순이익 (원)")
    bps          = Column(BigInteger, nullable=True,  comment="주당순자산 (원)")
    div_yield    = Column(Float,      nullable=True,  comment="배당수익률 (%)")
    dps          = Column(BigInteger, nullable=True,  comment="주당배당금 (원)")

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_stock_prices"),
        # ix_sp_stock_date 는 uq_stock_prices(동일 컬럼 unique index)와 중복이라 제거.
        # 기존 DB 의 잔존분은 db._run_migrations 의 DROP INDEX IF EXISTS 로 정리(멱등).
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


# ── 10. Gate B 감사대장 (face_audit) ──────────────────────────────────────────
class FaceAudit(Base):
    """
    PRD 04 Gate B 감사 산출물: std_v2 한 행(corp,fy,fp,basis)을 원본 보고서 face 표와
    표시단위 정확일치로 대조한 결과. status 가 promote 게이트(gate_b_status)를 구동한다.

    grain = std_financials_v2 와 동일(corp,fiscal_year,fiscal_period,statement_type,is_stub).
    - status: pass = in-scope 전 계정 검증·일치 / fail = Track A own-report col0 값불일치 1+ /
      pending = 아직 감사불가(비교컬럼행·Track B source·미매핑).
    - fail_detail/pending_detail: 트리아지용 필드별 [{field,canonical,db,report,reason}].
    신규 테이블 → create_all 자동 생성.
    """
    __tablename__ = "face_audit"

    corp_code      = Column(String(8),    primary_key=True)
    fiscal_year    = Column(SmallInteger, primary_key=True)
    fiscal_period  = Column(String(5),    primary_key=True)
    statement_type = Column(String(12),   primary_key=True)   # consolidated/separate (=basis)
    is_stub        = Column(Boolean,      primary_key=True, default=False)

    status         = Column(String(8),    nullable=False, comment="pass/fail/pending")
    gate_status    = Column(String(8),    nullable=True,  comment="promote 게이트: pass/fail_a/fail_b/pending")
    n_pass         = Column(SmallInteger, default=0)
    n_fail         = Column(SmallInteger, default=0)
    n_pending      = Column(SmallInteger, default=0)
    fail_fields    = Column(JSONB,        nullable=True, comment="FAIL 필드명 목록")
    fail_detail    = Column(JSONB,        nullable=True, comment="[{field,canonical,db_won,report_won,reason}]")
    pending_detail = Column(JSONB,        nullable=True, comment="범위밖 사유 집계 {reason:count}")
    reader_version = Column(String(20),   nullable=True, comment="감사 reader 버전(재현)")
    checked_at     = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_face_audit_status", "status", "fiscal_year"),
    )


class FaceLineAudit(Base):
    """
    PRD 04 Phase B 산출물: 한 보고서(rcept_no)의 **본문 Track A 전 face 라인**을 추출된 전 셀
    (fact_v2 col0·비차원)과 acode 정확매칭으로 1:1 대조한 결과(롤업).

    grain = rcept_no(보고서 1행, fact_v2 키와 일치).
    - line_gate_status: pass(n_value_diff=0) / fail_a(n_value_diff>0, 추출 손상 차단 후보) /
      pending(Track≠A·0라인 → 본 단계 비대상).
    - value_diff_detail: 차단 후보 라인 상세(추출버그 vs 감사reader 트리아지).
    - missing_detail: 보고서엔 있으나 fact_v2 부재(완전성 지표, 측정 우선이라 비차단).
    측정 우선 정책상 promote 뷰(standard_financials)는 본 표를 아직 참조하지 않는다(규모 측정 후 결정).
    신규 테이블 → create_all 자동 생성.
    """
    __tablename__ = "face_line_audit"

    rcept_no        = Column(String(14), primary_key=True)
    corp_code       = Column(String(8),  nullable=False, index=True)
    track           = Column(String(2),  nullable=True, comment="A(이번 범위)/B/C")

    n_lines         = Column(Integer, default=0, comment="대조한 Track A face 라인 수")
    n_match         = Column(Integer, default=0)
    n_value_diff    = Column(Integer, default=0, comment="fact_v2 존재·won 불일치(차단 후보)")
    n_missing       = Column(Integer, default=0, comment="보고서엔 있고 fact_v2 부재(완전성 지표)")
    n_extra         = Column(Integer, default=0, comment="fact_v2 col0 행이 face 부재(감사 reader 갭)")
    line_gate_status = Column(String(8), nullable=True, comment="pass/fail_a/pending")

    value_diff_detail = Column(JSONB, nullable=True,
                               comment="[{acode,basis,statement,label,report_won,db_won}]")
    missing_detail    = Column(JSONB, nullable=True, comment="동(완전성 지표)")
    reader_version    = Column(String(20), nullable=True)
    checked_at        = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_face_line_audit_gate", "line_gate_status"),
    )


class CorpVerifyStatus(Base):
    """
    기업별 순차 검증 오케스트레이터(scripts/verify_corp_sequential.py) 산출물.

    grain = corp_code (기업 1행). 한 기업의 전기간(상장 이후 분기/반기/사업보고서)에 대해
    다운로드→Gate A→fin2(E·R·S)→Gate B 를 1패스로 돌린 결과 요약이자 재개 마커.

    - stage: 마지막 완주 단계(downloaded/loaded/audited). 재실행 시 audited 면 skip(--recheck 로 강제).
    - gb_fail_a 가 0 이면 기업 PASS(보고서=DB 표시단위 정확일치), 그 외 FAIL(사유는 fail_periods).
      실패해도 루프는 중단하지 않고 기록 후 다음 기업 진행(PRD 00 불변원칙 추적용).
    신규 테이블 → create_all 자동 생성.
    """
    __tablename__ = "corp_verify_status"

    corp_code      = Column(String(8), primary_key=True)
    corp_name      = Column(String(120), nullable=True)
    stage          = Column(String(12), nullable=True, comment="downloaded/loaded/audited")

    # 다운로드/Gate A
    n_filings      = Column(Integer, default=0, comment="공시(필링) 수")
    n_downloaded   = Column(Integer, default=0, comment="completed download_tasks 수")
    gate_a_pass    = Column(Integer, default=0)
    gate_a_fail    = Column(Integer, default=0)

    # 적재
    n_std_rows     = Column(Integer, default=0, comment="std_financials_v2 적재 행수(연결+별도, 전기간)")

    # Gate B(보고서↔DB) 집계 — 전 fy·fp·basis
    gb_pass        = Column(Integer, default=0)
    gb_fail        = Column(Integer, default=0)
    gb_pending     = Column(Integer, default=0)
    gb_fail_a      = Column(Integer, default=0, comment="Track A 자기보고서 값불일치(차단)")
    fail_periods   = Column(JSONB,   nullable=True, comment="[[fy,fp,basis,gate], ...] 트리아지 진입점")

    # Phase B(라인 전수 대조) 집계 — face_line_audit 롤업(전 source rcept)
    line_total      = Column(Integer, default=0, comment="대조한 Track A 라인 총수")
    line_value_diff = Column(Integer, default=0, comment="라인 값불일치(차단 후보)")
    line_missing    = Column(Integer, default=0, comment="보고서 라인 fact_v2 부재(완전성 지표)")

    error          = Column(String(300), nullable=True, comment="기업 단위 예외 메시지(있으면)")
    verified_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_corp_verify_stage", "stage"),
    )
