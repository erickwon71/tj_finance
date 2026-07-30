"""
SQLAlchemy ORM 모델 정의
테이블:
  Phase 1: corporations / filings / download_tasks / collection_runs
  Phase 2: financial_facts / unknown_accounts / standard_financials / stock_prices
  Phase 6: executives / order_backlog
  갭채우기 Phase 2: dividend_facts / treasury_activity / employee_stats / other_investments /
    exec_pay_summary / exec_pay_individual / periodic_api_progress
"""
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float,
    ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, Index,
    CheckConstraint, func, text as sa_text
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
    induty_code      = Column(String(6),   nullable=True,  index=True,   comment="DART 업종코드(KSIC). 섹터/피어 그룹핑용")
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

    # ── provenance (2026-07-17 재구축) ────────────────────────────────────
    # 배경: 이전 파이프라인은 **추측한 값과 원본을 그대로 읽은 값을 구분하지 못했다**.
    # 주석표가 본문으로 새어들어도(요약재무정보 폴백·레거시 섹션 갭필), 단위를 배율 대입으로
    # 추측해도, 후보가 여럿일 때 max-abs 로 골라도 — 결과 행은 정상 행과 **바이트 단위로 동일**
    # 했다. 그래서 "오염된 것만 골라 삭제"를 SQL 로 표현할 수 없었고 전수 재파싱 외에 길이
    # 없었다. 아래 컬럼들은 그 구분을 **스키마로 강제**해 같은 사고의 재발을 막는다.
    # 모범 선례 = statement_source.lineage(후보 전체+선택근거 기록).
    # index=False: 재추출 전까지 전 행 NULL 이라 인덱스 이득이 없고, 87M 행 CREATE INDEX 는
    # 테이블을 오래 잠근다. 재구축 완료 후 별도 마이그레이션으로 추가.
    section_kind       = Column(String(20),   nullable=True,
                                comment="DART 섹션 출처: 연결재무제표 / 재무제표 / "
                                        "연결재무제표주석 / 재무제표주석 "
                                        "(요약재무정보는 적재하지 않음)")
    mapping_stage      = Column(String(12),   nullable=True,
                                comment="계정 매핑 근거: exact/normalized(사전 일치) · "
                                        "guard · fuzzy(유사도 추측) · unknown. "
                                        "fuzzy 는 canonical_account 를 부여하지 않는다")
    mapping_confidence = Column(Float,        nullable=True,
                                comment="매핑 신뢰도(참고용). exact=1.0")
    unit_source        = Column(String(10),   nullable=True,
                                comment="단위 출처: declared(원문에 (단위:…) 명시) 만 적재. "
                                        "미표기/불명은 추측하지 않고 보류큐로 보낸다")

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
# ── 5b2. 계층2 원문 tree (report_lines, 4계층 재설계 2026-07-19) ───────────
class ReportLine(Base):
    """
    4계층 재설계의 계층2 산출물 — 보고서 원문을 **판단 없이** tree 구조 그대로 저장.

    fact_v2 와의 차이:
      - canonical_account 없음(계층3 산출). concept_map/account_mapper 를 전혀 호출하지 않는다.
      - 라벨은 label_raw(원문 계정명, normalize_account_name 미적용) — acode 처럼 정규화하지 않는다.
      - **중복 라벨을 병합하지 않는다**: 같은 계정명이 서로 다른 위치(예 금융업 이중섹션)에
        나오면 그대로 둘 다 남는다(fact_v2 의 (acode, acontext) 충돌-시-보류와 다름 — 여기선
        충돌 자체가 없다. 위치가 다르면 서로 다른 행이다).
      - 재추출은 upsert 가 아니라 **rcept_no 단위 delete-then-insert**로 재현성을 보장한다
        (report_lines.py:store_report_lines).

    tree 구조 컬럼 — 2026-07-19 계획 §계층2 + 2026-07-21 실측 재설계:
      · section_path : 조상 라벨 경로('자산>유동자산'). 들여쓰기 stack 으로 산출.
      · node_role    : P/S/F — **다음 행과의 들여쓰기 비교만**으로 나오는 순수 구조 사실.
      · table_seq    : 한 섹션 안의 표 **문서 순번**. 정렬키는 항상 (table_seq, row_order).
      · table_title  : 그 표의 원문 제목. 위치 기록이지 판단이 아니다.

    ★ is_subtotal 을 두지 않는 이유(2026-07-21 실측, scripts/measure_subtotal_position.py):
      구 체인 `table_extractor._is_subtotal()` 은 부분문자열 매칭이고 키워드에 맨 '계' 가 있어
      관계기업투자·설계용역까지 소계로 찍는다(정밀도 49.5%). 그래서 계층2 전용 텍스트 규칙을
      만들려 했으나, 측정 결과 **텍스트 규칙 자체가 불필요**하다는 결론:
        - 진짜 소계의 55.3% 는 '자식을 거느린 행'(P) 이고 텍스트에 '계' 가 아예 없다
          (유동자산·비유동부채·영업활동현금흐름 …). 어떤 텍스트 규칙으로도 못 잡는다.
        - 반대로 IS 의 매출총이익·영업이익은 **자식이 없는 워터폴 이정표**라 애초에 이중계산
          위험이 없다. 그건 소계 판정이 아니라 canonical 매핑 문제(=계층3).
      → 계층2 는 node_role(구조 사실)만 남기고 "그래서 소계인가"는 계층3 이 조합해 판단한다.
        집계행 후보 = `node_role='P' OR (node_role='S' AND value_won IS NOT NULL)`.

    신규 테이블이므로 Base.metadata.create_all() 로 자동 생성(별도 마이그레이션 불요).
    """
    __tablename__ = "report_lines"

    id                 = Column(BigInteger,   primary_key=True, autoincrement=True)
    corp_code          = Column(String(8),    nullable=False, index=True)
    rcept_no           = Column(String(14),   ForeignKey("filings.rcept_no"), nullable=False, index=True)

    # index=True 제거(2026-07-31): 단독 인덱스는 카디널리티 ~12 라 플래너가 쓰지 않고
    # `ix_report_lines_lookup` 의 접두라 중복이다. 353 MB 회수(db.py 마이그레이션 참고).
    report_fiscal_year   = Column(SmallInteger, nullable=False, comment="보고서 회계연도")
    report_fiscal_period = Column(String(5),    nullable=False, comment="보고서 기간 FY/H1/Q1/Q3")

    statement          = Column(String(10),   nullable=False, comment="BS/IS/CF/SCE/note")
    basis              = Column(String(12),   nullable=True,  comment="consolidated/separate")

    # ── tree 구조 (계층2 핵심) ─────────────────────────────────────────────
    section_path       = Column(Text,         nullable=True,
                                comment="하위섹션 경로 예 '자산>유동자산'/'자산>금융업자산' — "
                                        "2C 에서 채움(NULL=미구현, 금융업 이중섹션 구분 핵심). "
                                        "★TEXT: 깊은 tree + 긴 원문 라벨이면 255 를 넘겨 insert 가 "
                                        "실패한다(전량 적재에서 터지는 종류) — 길이 제한 없음.")
    table_seq          = Column(SmallInteger, nullable=True,
                                comment="섹션 내 표의 문서 순번(0,1,…). 2표식(손익계산서/포괄손익"
                                        "계산서 분리, 실측 10.7%)에서 row_order 가 표마다 0 부터 "
                                        "다시 시작해 뒤섞이는 것을 막는다. 정렬키=(table_seq,row_order)")
    # table_title 은 `report_tables` 로 이동(F3, 2026-07-31) — 표 단위 값이라 행마다 반복하면
    # note 27.6 GB · 본문 5.6 GB 를 쓴다. 함수종속은 audit_db_waste 가 질의로 측정했다.
    row_order          = Column(SmallInteger, nullable=True,  comment="표 내 등장 순서(RowData.row_order 재사용)")
    depth              = Column(SmallInteger, nullable=True,  comment="들여쓰기 수준=원문 전각공백 수(raw_indent). "
                                                                     "★연속된 레벨번호가 아님(0→2→4 로 건너뜀) — "
                                                                     "계층 판단은 section_path 로 할 것")
    node_role          = Column(String(1),    nullable=True,
                                comment="구조적 위치 P/S/F — 다음 행 raw_indent 비교만(텍스트 안 봄). "
                                        "P=다음이 더 깊음(자식 거느림) S=다음이 더 얕음/표끝(형제 run 끝) "
                                        "F=다음이 같은 깊이(형제 중간). 소계 여부 주장 아님 — 위 docstring 참고")

    label_raw          = Column(Text,         nullable=False,
                                comment="원문 계정명 그대로(정규화 안 함). ★TEXT: 원문 충실전사가 "
                                        "원칙이라 잘라내면 안 된다 — section_path 를 구성하는 원자이기도 함.")

    col_index          = Column(SmallInteger, nullable=True,
                                comment="BS/IS/CF=0 당기 1 전기 2 전전기 / note·SCE=위치(연도 아님)")
    col_label          = Column(Text,         nullable=True,
                                comment="열 헤더 원문(다단이면 '>'로 연결). **자본변동표 전용** — "
                                        "SCE 는 열이 기간이 아니라 자본 구성요소(자본금/이익잉여금/…)"
                                        "라 이게 없으면 col_index 만으로는 어느 열인지 알 수 없다. "
                                        "COLSPAN/ROWSPAN 그리드 복원으로 산출(원문 전사, 판단 아님)")
    # index=True 제거(2026-07-31): report_lines 는 col_index=0 만 적재해 사실상
    # report_fiscal_year 와 같고 주석·SCE 에서는 전량 NULL 이다. 327 MB 회수.
    context_fiscal_year= Column(SmallInteger, nullable=True)
    period_kind        = Column(String(8),    nullable=True,  comment="instant(BS)/duration(IS·CF)")
    is_cumulative       = Column(Boolean,     default=False)

    value_won          = Column(BigInteger,   nullable=True,  comment="원 단위 정규화 금액")
    value_raw          = Column(Text,         nullable=True,
                                comment="셀 원문 문자열. **value_won 이 NULL 인 칸에만** 채운다 — "
                                        "비금액 열(이자율·지분율·주식수)이나 단위 미확정 열이라 원 "
                                        "단위로 환산할 수 없는 경우(2026-07-31 F1). 값이 있는 칸은 "
                                        "원문이 value_won 에서 복원되므로 NULL(용량 0). "
                                        "이 컬럼이 있어야 '단위 미확정 → NULL' 이 정보손실이 아니다.")
    header_hint        = Column(Text,         nullable=True,
                                comment="헤더 판정 규칙 이름(날짜/기수/단위표기/구분과목/N개월/"
                                        "N분기/날짜범위/기준일/기간라벨/공정가치수준/빈셀). "
                                        "NULL=규칙에 안 걸린 평범한 데이터 행. **관찰이지 판단이 "
                                        "아니다** — 행이 기간축인 표에서 '당기말' 은 헤더가 아니라 "
                                        "데이터 행 라벨이다(2026-07-31 F2). 계층3 소비자는 기본 "
                                        "`header_hint IS NULL` 로 거르고, note_periods 는 반대로 "
                                        "'기간라벨' 을 기간축 식별 신호로 쓴다.")
    adecimal           = Column(SmallInteger, nullable=True)
    unit_source        = Column(String(14),   nullable=True,
                                comment="value_won 의 근거(fin2/extract/units.py): declared(표 선언 "
                                        "배수) | col_money(혼합 선언+열 헤더가 금액) | non_monetary"
                                        "(비금액 열/표 — value_won 없음) | undetermined(단위 확정 실패) "
                                        "| undeclared(선언 자체가 없는 표)")

    source_ref         = Column(String(180),  nullable=True)
    context_raw        = Column(String(255),  nullable=True,  comment="합성 위치 태그(감사용, uq 아님)")
    # parsed_at 도 `report_tables` 로 이동(F3) — rcept 단위로 같은 값이라 행마다 둘 이유가 없다.

    __table_args__ = (
        Index("ix_report_lines_lookup", "corp_code", "report_fiscal_year", "statement", "basis"),
    )

    def __repr__(self):
        return (f"<ReportLine {self.corp_code} r{self.rcept_no} {self.statement} "
                f"{self.label_raw!r} {self.value_won}>")


class ReportTable(Base):
    """계층2 **표 단위** 메타데이터 — 행마다 반복되던 값을 한 곳으로 모은다(F3, 2026-07-31).

    왜 별 테이블인가 — 측정된 함수종속
    ----------------------------------
    `scripts/audit_db_waste.py` 가 `GROUP BY 키 HAVING count(DISTINCT col) > 1` 을 **실제로
    질의**해, 아래 컬럼들이 `(rcept_no, statement, basis, table_seq)` 에 함수종속임을 확인했다
    (표본 300 rcept: note 995,310행 → 48,037그룹, 위반 0). 즉 한 표의 모든 행이 같은 값을
    들고 있었다. 실측 회수량:

        note_lines.table_title    141 B × 2.2억 행  → **27.6 GB**
        note_lines.section_path    33 B × 2.2억 행  →  **6.4 GB**
        report_lines.table_title  164 B × 3,748만 행 → **5.6 GB**
        parsed_at                   8 B × 양쪽       →  **1.9 GB**

    ★ `report_lines.section_path` 는 **여기 오지 않는다.** 그건 들여쓰기 stack 경로
      ('자산>유동자산')라 **행마다 다르다**. 이름이 같다고 같은 것이 아니다 — 주석의
      section_path 만 '그 표의 주석 제목'이라 표 단위다.

    단위 정보도 함께 둔다(F1). 행에는 `unit_source`(그 칸을 왜 그렇게 판정했는가)만 남기고,
    **표가 원문에 뭐라고 적었는지**(`unit_decl_raw`)는 여기 한 번만 적는다 — 계층3 이 나중에
    다시 해석할 수 있게 하는 근거이며, 행마다 반복하면 그 자체가 새 낭비가 된다.
    """
    __tablename__ = "report_tables"

    rcept_no    = Column(String(14), ForeignKey("filings.rcept_no"), primary_key=True)
    statement   = Column(String(10), primary_key=True, comment="BS/IS/CF/SCE/note")
    basis       = Column(String(12), primary_key=True, comment="consolidated/separate")
    table_seq   = Column(SmallInteger, primary_key=True, comment="섹션 내 표 문서 순번")

    table_title = Column(Text, nullable=True,
                         comment="그 표의 원문 제목(위치 기록). 종전 report_lines/note_lines 의 "
                                 "동명 컬럼이 여기로 왔다")
    section_path= Column(Text, nullable=True,
                         comment="**주석 전용** — 관장 번호 주석 제목('27. 현금흐름표'). "
                                 "본문 report_lines.section_path(들여쓰기 경로)와는 다른 것이라 "
                                 "본문 행에는 계속 행마다 남는다")
    unit_decl_raw = Column(Text, nullable=True,
                           comment="표가 원문에 적은 단위 선언 문자열 그대로('(단위 : 주, 천원)')")
    declared_unit = Column(BigInteger, nullable=True, comment="선언에서 읽은 금액 배수(없으면 NULL)")
    unit_kind     = Column(String(12), nullable=True,
                           comment="money_only/mixed/non_money/undeclared (fin2/extract/units.py)")
    unit_inherited= Column(Boolean, default=False,
                           comment="표 자신의 선언이 아니라 앞선 선언 전용 표·항목 도입 문단에서 "
                                   "상속했는가(사용자 결정 D1)")
    parsed_at     = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (f"<ReportTable r{self.rcept_no} {self.statement}/{self.basis}"
                f"#{self.table_seq} {self.table_title!r}>")


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
    # C 합산(2026-07-18): 유동+비유동 리스부채 / 단기+장기 차입 유입·상환 합계.
    lease_liability     = Column(BigInteger, nullable=True)
    borrowings_proceeds = Column(BigInteger, nullable=True)
    borrowings_repaid   = Column(BigInteger, nullable=True)

    # ── 메타·연원 ──
    data_quality        = Column(SmallInteger, default=0, comment="0:미검증 1:정상 2:경고 3:오류")
    bs_rcept            = Column(String(14),  nullable=True, comment="BS source filing")
    is_rcept            = Column(String(14),  nullable=True, comment="IS source filing")
    cf_rcept            = Column(String(14),  nullable=True, comment="CF source filing")
    applied_rules       = Column(JSONB,       nullable=True, comment="적용된 규칙 이름 목록")
    # 후보가 갈려 **보류한** canonical 의 후보 전체(2026-07-17, C1/C6/C7 max-abs 폐지의 짝).
    # {canonical: [{value, rcept, chosen:false}, ...]}. 값이 왜 비었는지의 근거이자
    # Phase C 패턴루프의 작업목록. 선례 = statement_source.lineage.
    value_lineage       = Column(JSONB,       nullable=True,
                                 comment="충돌로 보류한 canonical 의 후보 전체(근거)")
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


# ── 11. 시장조치/규제 지정 이력 (관리종목·상장폐지·매매정지 등) ──────────────────
class RegulatoryEvent(Base):
    """
    거래소(KRX) 시장조치 공시(DART pblntf_ty='I') 중 관리종목·상장폐지·매매거래정지·
    불성실공시법인·회생절차 등 투자위험 관련 이벤트만 선별 저장.
    시각화 각주(주3)·기업 상세 패널의 데이터 소스. collector/dart_extra.py::sync_regulatory_events 가 채움.
    """
    __tablename__ = "regulatory_events"

    id          = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code   = Column(String(8),    nullable=False,   index=True)
    rcept_no    = Column(String(14),   nullable=False,   unique=True)
    filed_at    = Column(Date,         nullable=False)
    report_nm   = Column(String(300),  nullable=True)
    event_type  = Column(String(30),   nullable=False,
                         comment="admin_issue/delisting/trading_halt/disclosure_violation/rehabilitation")
    is_lift     = Column(Boolean,      default=False,
                         comment="True=지정 해제/정상화 이벤트, False=지정/발생 이벤트")
    fetched_at  = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_regevt_corp_type", "corp_code", "event_type", "filed_at"),
    )


# ── 12. 자본이벤트 (증자·감자·CB/BW/EB 발행·자기주식) ────────────────────────────
class CapitalEvent(Base):
    """
    주식수에 영향(즉시 또는 잠재적)을 주는 주요사항보고서 이벤트.
    DART 주요사항보고(pblntf_ty='B') 중 유/무상증자·감자·전환사채·신주인수권부사채·
    교환사채 발행·자기주식 취득/처분 결정만 선별해 타입별 구조화 API(piicDecsn 등)로
    상세 조회한 결과. shares_delta 는 필드 가용 시의 best-effort 추정치(전량 신뢰 금지 —
    원본은 detail JSONB). CB/BW/EB 는 전환 전 "잠재" 주식수(양수)로 저장.
    시각화 B-2 발행주식수 추이 차트의 dilution 오버레이 데이터 소스.
    collector/dart_capital.py::sync_capital_events 가 채움.
    """
    __tablename__ = "capital_events"

    id            = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code     = Column(String(8),    nullable=False,   index=True)
    rcept_no      = Column(String(14),   nullable=False,   unique=True)
    filed_at      = Column(Date,         nullable=False)
    board_date    = Column(Date,         nullable=True,   comment="이사회결의일(bddd)")
    report_nm     = Column(String(300),  nullable=True)
    event_type    = Column(String(20),   nullable=False,
                           comment="paid_increase/free_increase/mixed_increase/reduction/"
                                   "cb_issue/bw_issue/eb_issue/treasury_acquire/treasury_dispose")
    shares_delta  = Column(BigInteger,   nullable=True,
                           comment="증권종류 무관 보통주 기준 best-effort 추정(+증가/잠재발행, -감소). "
                                   "필드 미공시 시 NULL")
    detail        = Column(JSONB,        nullable=True,   comment="해당 rcept_no 의 원본 API 응답 전체")
    fetched_at    = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_capevt_corp_type", "corp_code", "event_type", "filed_at"),
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


# ── 13. 대주주/지분 현황 (B3) ─────────────────────────────────────────────────
class MajorShareholder(Base):
    """
    DART hyslrSttus(최대주주 현황) — 사업보고서 기준 corp+fiscal_year+주주 단위 지분.
    본인(최대주주) + 특수관계인 전 행. 지배구조 패널의 최대주주 지분율 소스.
    """
    __tablename__ = "major_shareholders"

    id            = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code     = Column(String(8),    nullable=False,   index=True)
    fiscal_year   = Column(SmallInteger, nullable=False)
    name          = Column(String(100),  nullable=False)
    relation      = Column(String(50),   nullable=True,   comment="최대주주 본인/특수관계인 등")
    stock_kind    = Column(String(20),   nullable=True,   comment="보통주/우선주")
    shares_begin  = Column(BigInteger,   nullable=True,   comment="기초소유주식수")
    pct_begin     = Column(Float,        nullable=True,   comment="기초지분율(%)")
    shares_end    = Column(BigInteger,   nullable=True,   comment="기말소유주식수")
    pct_end       = Column(Float,        nullable=True,   comment="기말지분율(%)")
    remark        = Column(String(200),  nullable=True)
    fetched_at    = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "fiscal_year", "name", "relation", "stock_kind",
                         name="uq_major_shareholders"),
        Index("ix_mshr_corp_year", "corp_code", "fiscal_year"),
    )


class ShareholderChange(Base):
    """DART hyslrChgSttus(최대주주 변동현황) — 실제 변동이 있었던 연도만 행 존재(대부분 '-')."""
    __tablename__ = "shareholder_changes"

    id            = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code     = Column(String(8),    nullable=False,   index=True)
    fiscal_year   = Column(SmallInteger, nullable=False)
    change_on     = Column(String(20),   nullable=True,   comment="변동일")
    holder_name   = Column(String(100),  nullable=True,   comment="최대주주명(변경 후)")
    shares        = Column(BigInteger,   nullable=True)
    pct           = Column(Float,        nullable=True)
    cause         = Column(String(200),  nullable=True,   comment="변동원인")
    fetched_at    = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_shrchg_corp_year", "corp_code", "fiscal_year"),
    )


class RetailOwnership(Base):
    """DART mrhlSttus(소액주주 현황) — corp+fiscal_year 당 1행 집계. float(유통물량) 근사치."""
    __tablename__ = "retail_ownership"

    id                = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code         = Column(String(8),    nullable=False,   index=True)
    fiscal_year       = Column(SmallInteger, nullable=False)
    holder_count      = Column(BigInteger,   nullable=True,   comment="소액주주 수")
    holder_total_count = Column(BigInteger,  nullable=True,   comment="전체 주주 수")
    holder_rate_pct   = Column(Float,        nullable=True,   comment="소액주주 비중(인원 기준, %)")
    held_shares       = Column(BigInteger,   nullable=True,   comment="소액주주 보유주식수")
    total_shares      = Column(BigInteger,   nullable=True,   comment="발행주식총수")
    held_rate_pct     = Column(Float,        nullable=True,   comment="소액주주 지분율(주식수 기준, %) — float 근사치")
    fetched_at        = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "fiscal_year", name="uq_retail_ownership"),
    )


# ── 12. 사업의 내용 · 생산능력/생산실적/가동률 (B4) ────────────────────────────
class BizSectionTable(Base):
    """
    사업보고서 "II. 사업의 내용" 본문 생산능력/생산실적/가동률 소제목의 원본 표(무손실).
    XBRL 비대상 순수 HTML형 표라 fin2/extract/biz_section.py 가 ROWSPAN/COLSPAN 확장한
    2D 그리드를 그대로 보존한다(캐노니컬 매핑 실패/부분 대비 audit 원천). 구조화된 long-format
    행은 biz_metrics 에 별도 적재. corp+rcept 단위 delete-then-insert(멱등).
    """
    __tablename__ = "biz_section_tables"

    id           = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code    = Column(String(8),    nullable=False,   index=True)
    fiscal_year  = Column(SmallInteger, nullable=False)
    rcept_no     = Column(String(14),   nullable=False)
    table_ord    = Column(SmallInteger, nullable=False,   comment="보고서 내 추출 표 순번(0-based)")
    metric       = Column(String(40),   nullable=True,    comment="소제목 파생 지표: capacity/output/utilization(+결합)")
    narrative    = Column(Text,         nullable=True,    comment="소제목 다음 설명 문단(단위·산출기준)")
    grid         = Column(JSONB,        nullable=False,   comment="원본 2D 텍스트 그리드(헤더 포함)")
    n_metric_rows = Column(SmallInteger, nullable=True,   comment="이 표에서 매핑된 biz_metrics 행 수")
    fetched_at   = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("rcept_no", "table_ord", name="uq_biz_section_tables"),
        Index("ix_biz_sec_corp_year", "corp_code", "fiscal_year"),
    )


class BizMetric(Base):
    """
    생산능력/생산실적/가동률의 구조화된 long-format 값(corp·기간·지표·부문·품목 단위 1행).
    biz_section_tables 의 원본 그리드를 fin2/extract/biz_section.map_biz_table 이 해석한 결과.
    period_year 는 '제N기(YYYY년)' 헤더에서 해석한 달력연도(해석 불가 시 NULL — 비-시계열
    보조표는 period_label 에 헤더 라벨 보존). value 는 원공시 단위(unit) 기준 그대로.
    corp+rcept 단위 delete-then-insert(멱등).
    """
    __tablename__ = "biz_metrics"

    id           = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code    = Column(String(8),    nullable=False,   index=True)
    fiscal_year  = Column(SmallInteger, nullable=False,   comment="보고서 회계연도")
    rcept_no     = Column(String(14),   nullable=False)
    table_ord    = Column(SmallInteger, nullable=False,   comment="출처 biz_section_tables.table_ord")
    metric       = Column(String(20),   nullable=False,   comment="capacity/output/utilization/sales")
    channel      = Column(String(12),   nullable=True,    comment="매출 채널(수출/내수/합계/기타) — metric='sales' 전용, 생산지표는 NULL")
    segment      = Column(String(120),  nullable=True,    comment="부문(예: DX부문/정유부문)")
    item         = Column(String(150),  nullable=True,    comment="품목(예: 메모리/TV·모니터). 부문뿐이면 NULL")
    period_label = Column(String(60),   nullable=True,    comment="원본 기간 라벨(제56기 등) 또는 보조컬럼 헤더")
    period_year  = Column(SmallInteger, nullable=True,   comment="해석한 달력연도(비시계열 보조표는 NULL)")
    value        = Column(Float,        nullable=False)
    unit         = Column(String(30),   nullable=True,    comment="원공시 단위(천대/천배럴/% 등)")
    is_ratio     = Column(Boolean,      default=False,    comment="가동률 등 백분율 값 여부")
    source       = Column(String(20),   default="html_parse")
    fetched_at   = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_biz_metric_corp_year", "corp_code", "fiscal_year", "metric"),
        Index("ix_biz_metric_lookup", "corp_code", "metric", "period_year"),
    )


# ── 13. Phase 2 · 주주환원 + 회사 일반현황 (정기보고서 API 6종) ──────────────────
# DART 사업보고서(11011) 기준 corp+fiscal_year 단위. 각 API 응답의 raw 원본을 JSONB 로
# 보존(필드명 변이·PRD 추정과 실제 API 응답 차이 대비 — 착수 전 실호출로 확인한 실제
# 필드 스펙은 docs/prd/13_phase2_periodic_apis.md 참조). collector/dart_periodic.py 가 채움.

class DividendFacts(Base):
    """DART alotMatter(배당에 관한 사항) — corp+fiscal_year 당 1행으로 피벗.
    원본은 se(항목명)+stock_knd(보통주/우선주) 조합의 long-format 15행이라 앱에서 바로 쓰기
    어려워 대표 지표만 컬럼화하고 전체 15행은 raw 에 보존."""
    __tablename__ = "dividend_facts"

    id                    = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code             = Column(String(8),    nullable=False,   index=True)
    fiscal_year           = Column(SmallInteger, nullable=False)
    dps_common            = Column(BigInteger,   nullable=True,   comment="주당 현금배당금(원), 보통주")
    dps_pref              = Column(BigInteger,   nullable=True,   comment="주당 현금배당금(원), 우선주")
    stock_dividend_ratio  = Column(Float,        nullable=True,   comment="주당 주식배당(주), 보통주")
    total_dividend_amount = Column(BigInteger,   nullable=True,   comment="현금배당금총액(백만원)")
    payout_ratio          = Column(Float,        nullable=True,   comment="(연결)현금배당성향(%), 공시값")
    dividend_yield_common = Column(Float,        nullable=True,   comment="현금배당수익률(%), 보통주")
    rcept_no              = Column(String(14),   nullable=True)
    raw                   = Column(JSONB,        nullable=True,   comment="alotMatter 응답 전체(15행 se/stock_knd 조합)")
    fetched_at            = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "fiscal_year", name="uq_dividend_facts"),
    )


class TreasuryActivity(Base):
    """DART tesstkAcqsDspsSttus(자기주식 취득 및 처분현황) — 취득방법(대/중/소분류)×주식종류
    조합별 1행(총계/소계 subtotal 행 포함, raw 원본 그대로). corp+fiscal_year 단위 delete-then-insert."""
    __tablename__ = "treasury_activity"

    id               = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code        = Column(String(8),    nullable=False,   index=True)
    fiscal_year      = Column(SmallInteger, nullable=False)
    stock_kind       = Column(String(20),   nullable=True,   comment="보통주/우선주")
    acqs_method1     = Column(String(60),   nullable=True,   comment="취득방법 대분류")
    acqs_method2     = Column(String(60),   nullable=True,   comment="취득방법 중분류")
    acqs_method3     = Column(String(60),   nullable=True,   comment="취득방법 소분류(총계/소계 포함)")
    qty_begin        = Column(BigInteger,   nullable=True,   comment="기초 수량")
    qty_acquired     = Column(BigInteger,   nullable=True,   comment="변동 수량(취득)")
    qty_disposed     = Column(BigInteger,   nullable=True,   comment="변동 수량(처분)")
    qty_incinerated  = Column(BigInteger,   nullable=True,   comment="변동 수량(소각)")
    qty_end          = Column(BigInteger,   nullable=True,   comment="기말 수량")
    remark           = Column(String(200),  nullable=True)
    rcept_no         = Column(String(14),   nullable=True)
    raw              = Column(JSONB,        nullable=True)
    fetched_at       = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_treasury_corp_year", "corp_code", "fiscal_year"),
    )


class EmployeeStats(Base):
    """DART empSttus(직원 현황) — 부문(fo_bbm)×성별(sexdstn) 조합별 1행(부문/성별 합계행 포함)."""
    __tablename__ = "employee_stats"

    id                   = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code            = Column(String(8),    nullable=False,   index=True)
    fiscal_year          = Column(SmallInteger, nullable=False)
    division             = Column(String(60),   nullable=True,   comment="부문(fo_bbm), '성별합계'=부문 전체")
    sex                  = Column(String(4),    nullable=True,   comment="남/여")
    regular_count        = Column(BigInteger,   nullable=True,   comment="정규직 수(rgllbr_co)")
    contract_count       = Column(BigInteger,   nullable=True,   comment="계약직 수(cnttk_co)")
    total_count          = Column(BigInteger,   nullable=True,   comment="합계(sm)")
    avg_tenure_years     = Column(Float,        nullable=True,   comment="평균 근속연수(avrg_cnwk_sdytrn)")
    annual_salary_total  = Column(BigInteger,   nullable=True,   comment="연간급여총액(원, fyer_salary_totamt) — 성별합계 행에만 존재")
    avg_salary           = Column(BigInteger,   nullable=True,   comment="1인평균급여액(원, jan_salary_am) — 성별합계 행에만 존재")
    remark               = Column(String(200),  nullable=True)
    rcept_no             = Column(String(14),   nullable=True)
    raw                  = Column(JSONB,        nullable=True)
    fetched_at           = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_employee_corp_year", "corp_code", "fiscal_year"),
    )


class OtherInvestment(Base):
    """DART otrCprInvstmntSttus(타법인 출자현황) — corp+fiscal_year 당 피출자법인별 1행."""
    __tablename__ = "other_investments"

    id                    = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code             = Column(String(8),    nullable=False,   index=True)
    fiscal_year           = Column(SmallInteger, nullable=False)
    investee_name         = Column(String(150),  nullable=True,   comment="법인명(inv_prm)")
    first_acquired_date   = Column(String(20),   nullable=True,   comment="최초취득일자(frst_acqs_de)")
    purpose               = Column(String(60),   nullable=True,   comment="출자목적(invstmnt_purps)")
    first_acquired_amount = Column(BigInteger,   nullable=True,   comment="최초취득금액(원)")
    begin_qty             = Column(BigInteger,   nullable=True,   comment="기초잔액 수량")
    begin_pct             = Column(Float,        nullable=True,   comment="기초잔액 지분율(%)")
    begin_book_value      = Column(BigInteger,   nullable=True,   comment="기초잔액 장부가액(원)")
    end_qty               = Column(BigInteger,   nullable=True,   comment="기말잔액 수량")
    end_pct               = Column(Float,        nullable=True,   comment="기말잔액 지분율(%)")
    end_book_value        = Column(BigInteger,   nullable=True,   comment="기말잔액 장부가액(원)")
    investee_total_assets = Column(BigInteger,   nullable=True,   comment="피출자법인 최근사업연도 총자산(원)")
    investee_net_income   = Column(BigInteger,   nullable=True,   comment="피출자법인 최근사업연도 당기순이익(원)")
    rcept_no              = Column(String(14),   nullable=True)
    raw                   = Column(JSONB,        nullable=True)
    fetched_at            = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_otherinv_corp_year", "corp_code", "fiscal_year"),
    )


class ExecPaySummary(Base):
    """DART hmvAuditAllSttus(이사·감사 전체의 보수현황) — corp+fiscal_year 당 1행 집계."""
    __tablename__ = "exec_pay_summary"

    id                  = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code           = Column(String(8),    nullable=False,   index=True)
    fiscal_year         = Column(SmallInteger, nullable=False)
    total_exec_count    = Column(Integer,      nullable=True,   comment="인원수(nmpr)")
    total_pay_amount    = Column(BigInteger,   nullable=True,   comment="보수총액(원, mendng_totamt)")
    avg_pay_per_person  = Column(BigInteger,   nullable=True,   comment="1인평균보수액(원, jan_avrg_mendng_am)")
    remark              = Column(String(200),  nullable=True)
    rcept_no            = Column(String(14),   nullable=True)
    raw                 = Column(JSONB,        nullable=True)
    fetched_at          = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("corp_code", "fiscal_year", name="uq_exec_pay_summary"),
    )


class ExecPayIndividual(Base):
    """DART indvdlByPay(개인별 보수지급금액, 5억원 이상 상위5인) — 등기임원 여부 무관(고문/상담역
    등 미등기 포함 가능, executives.compensation(hmvAuditIndvdlBySttus=등기임원 한정)와 별개 소스."""
    __tablename__ = "exec_pay_individual"

    id                = Column(Integer,      primary_key=True, autoincrement=True)
    corp_code         = Column(String(8),    nullable=False,   index=True)
    fiscal_year       = Column(SmallInteger, nullable=False)
    person_name       = Column(String(50),   nullable=True,   comment="성명(nm)")
    position          = Column(String(100),  nullable=True,   comment="직위(ofcps)")
    total_pay_amount  = Column(BigInteger,   nullable=True,   comment="보수총액(원, mendng_totamt)")
    pay_detail        = Column(JSONB,        nullable=True,   comment="해당 행 원본(mendng_totamt_ct_incls_mendng 등)")
    rcept_no          = Column(String(14),   nullable=True)
    fetched_at        = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_execpayind_corp_year", "corp_code", "fiscal_year"),
    )


class PeriodicApiProgress(Base):
    """Phase 2 6개 API 백필 체크포인트 — (corp_code, fiscal_year, api_name) 단위 진행상태.
    no_data(status='013') 응답도 반드시 기록해야 재실행 시 이미 확인한 no-data 케이스를
    다시 조회해 DART 일일 쿼터를 낭비하지 않는다(B3/B2 백필 쿼터소진 교훈과 동일 패턴)."""
    __tablename__ = "periodic_api_progress"

    corp_code    = Column(String(8),    primary_key=True)
    fiscal_year  = Column(SmallInteger, primary_key=True)
    api_name     = Column(String(30),   primary_key=True,
                          comment="alotMatter/tesstkAcqsDspsSttus/empSttus/otrCprInvstmntSttus/"
                                  "hmvAuditAllSttus/indvdlByPay")
    status       = Column(String(10),   nullable=False,   comment="ok/no_data/error")
    checked_at   = Column(DateTime,     default=datetime.utcnow)


class ReportLineAnomaly(Base):
    """계층2 이상치 **표시**(2026-07-21) — 값을 고치지 않고 "이상하다"만 기록한다.

    ★ 설계 원칙(사용자 확정): report_lines 는 **원문 그대로**를 유지하고, 보정은 계층3 이
      이 플래그를 보고 판단해 적용한다. 계층2 에서 값을 덮어쓰지 않는 이유:
        1. `scripts/verify_report_lines.py` 가 report_lines ↔ 원문 XML **완전일치**로 회귀를
           잡는다(현재 299/300). 값을 고치면 이 1차 탐지기가 설계상 영구히 깨진다.
        2. `store_report_lines` 는 rcept 단위 delete-then-insert 다 — 같은 행에 보정값을 두면
           재추출 때마다 사라진다.
        3. 판정 근거가 BS 교차대조(다른 재무제표)라 애초에 계층3 성격의 판단이다.

    실측 사례(전부 공시 원문 자체의 오기. 같은 XML 의 BS 는 정상값이라 파서 결함 아님):
      · 쏠리드 2019 연결   이익잉여금 BS 26,038,777,444 ↔ SCE 2,603,877,744  (끝자리 유실)
      · 대림제지 2023 연결 자본조정 기말 부호 누락(기초+변동 = -5,480,372,400, 원문 +)
      · 에스에이티 2019 연결 총계 부호 반전(사용자 원문 확인)

    소비 방법: 계층3 에서 자연키로 조인해 `COALESCE(a.suggested_value, rl.value_won)` 형태로
    쓰거나, confidence 를 보고 채택 여부를 정한다. suggested_value 는 **제안**이며 적용된 적 없다.

    자연키를 쓰는 이유: report_lines.id 는 재추출(delete-then-insert)마다 바뀐다.
    original_value 스냅샷은 재추출로 원문 값이 달라졌을 때 그 표시가 낡았음을 감지하는 장치다.
    """
    __tablename__ = "report_line_anomalies"

    id             = Column(BigInteger,   primary_key=True, autoincrement=True)
    rcept_no       = Column(String(14),   ForeignKey("filings.rcept_no"), nullable=False, index=True)
    corp_code      = Column(String(8),    nullable=False, index=True)

    # ── report_lines 를 지목하는 자연키 ──────────────────────────────────
    statement      = Column(String(10),   nullable=False)
    basis          = Column(String(12),   nullable=True)
    table_seq      = Column(SmallInteger, nullable=True)
    row_order      = Column(SmallInteger, nullable=True)
    col_index      = Column(SmallInteger, nullable=True)
    label_raw      = Column(Text,         nullable=True, comment="감사 편의용(자연키 아님)")

    original_value = Column(BigInteger,   nullable=True, comment="표시 시점의 원문 값 스냅샷")
    suggested_value= Column(BigInteger,   nullable=True,
                            comment="근거로 유도된 값. **제안일 뿐 적용된 적 없음** — 계층3 판단")

    anomaly_kind   = Column(String(20),   nullable=False,
                            comment="SIGN(부호반전) / DIGIT_TRUNC(끝자리유실) / DIGIT_EXTRA / OTHER")
    evidence       = Column(String(24),   nullable=False,
                            comment="bs_crosscheck(다른 재무제표=최강) / sce_column_flow(기초+변동=기말) "
                                    "/ sce_row_sum(구성요소=총계)")
    evidence_detail= Column(Text,         nullable=True, comment="예 'BS 이익잉여금 -34,471,912,378'")
    confidence     = Column(String(8),    nullable=False, default="medium", comment="high/medium/low")
    detected_at    = Column(DateTime,     default=datetime.utcnow)

    __table_args__ = (
        Index("ix_rl_anomaly_lookup", "corp_code", "statement", "anomaly_kind"),
        Index("ix_rl_anomaly_key", "rcept_no", "statement", "basis",
              "table_seq", "row_order", "col_index"),
    )

    def __repr__(self):
        return (f"<ReportLineAnomaly {self.corp_code} r{self.rcept_no} {self.statement} "
                f"{self.anomaly_kind} {self.original_value}→{self.suggested_value}>")


class ReportLineLoadProgress(Base):
    """계층2 전량적재 진행 체크포인트 — rcept 단위. **재개 가능성의 근거**.

    report_lines 에 행이 있는지로 재개를 판단하면 안 된다: 추출 결과가 0행인 보고서(단위
    미선언·본문 섹션 없음 등 '보류')가 정상적으로 존재하므로, 그런 건은 매 재시작마다
    무한 재처리된다. 그래서 처리 사실 자체를 따로 기록한다.

    status: done(적재 완료, 0행 포함) / skip(파일 소실) / error(예외 — message 보존)
    """
    __tablename__ = "report_line_load_progress"

    rcept_no     = Column(String(14), primary_key=True)
    corp_code    = Column(String(8),  nullable=False, index=True)
    fiscal_year  = Column(SmallInteger, nullable=True, index=True)
    status       = Column(String(8),  nullable=False, index=True)
    n_lines      = Column(Integer,    nullable=True)
    n_anomalies  = Column(Integer,    nullable=True)
    message      = Column(Text,       nullable=True)
    processed_at = Column(DateTime,   default=datetime.utcnow)


class ReportLineCorrection(Base):
    """계층2 원문오류 **보정 규칙**(2026-07-22) — 사람/탐지기의 **판정 저장소**.

    ★ report_line_anomalies 와 역할이 다르다(전문가 자문 반영):
      - anomalies = 탐지기 파생물. rcept 단위 delete-then-insert 로 매 실행마다 재생성된다.
        → 사람이 원문 대조로 확정한 판정을 **여기 넣으면 다음 탐지 실행이 지운다.**
      - corrections = 판정. **재생성되지 않는다.** 탐지기가 넣은 detector 판정과 사람이 넣은
        human 판정이 공존하며, 계층3 이 이 표를 보고 보정을 적용한다.

    ★ report_lines 의 value_won 은 **절대 고치지 않는다.** 원문 그대로 보존하고(원문 대조
      회귀 유지) 보정은 이 표에 '규칙'으로만 남긴다. 계층3 적재 시 인메모리로 적용.

    ── 왜 '값'이 아니라 '규칙(scope+operation)'인가 ──────────────────────────────
    단위오류(HLB제약: 표제 '백만원'인데 실제 '원')는 **표 전체**가 대상이다. 행마다
    suggested_value 를 넣으면 수천 행이 필요하고 의미도 왜곡된다. scope 로 적용범위를,
    operation 으로 연산을 표현한다. 특히 단위오류는 배율(÷10⁶)이 아니라 **set_adecimal(0)**
    으로 — 멱등이라 재추출 후 중복적용되지 않고 원문 인쇄값 복원 경로와 일치한다.

    ── 재추출 내구성 (계층2 는 rcept 단위 delete-then-insert, 행 id 가 매번 바뀜) ──────
    자연키(rcept/statement/basis/table_seq/row_order/col_index)로 행을 지목하되, table_seq·
    row_order 는 **파서 산출물**이라 파서 개선 시 밀린다. 그래서 지문 2종을 함께 둔다:
      · scope='row'  → expect_label + expect_value (라벨+값 이중지문. 값만으론 0/반복금액에서 오지목)
      · scope in (filing,table) → expect_row_count (행을 특정 안 하므로 '이 표가 여전히 N행인가')
    계층3 적재기는 규칙마다 대상을 찾아 지문을 검증하고, **불일치면 status='stale' 마킹 후
    적재를 실패시킨다**(NULL 폴백 금지 — 오류가 사라진 것처럼 보이는 게 최악). 자동 재바인딩
    (라벨 유사도로 행 재탐색)은 만들지 않는다 — 제거하기로 한 '추측'의 재발이다.

    ── cross_verdict (2026-07-22 실측) ──────────────────────────────────────────
    SIGN 이상치의 suggested_value 가 옳은지 **BS 시계열 연속성**(독립 근거)으로 교차확인한 결과:
      제안우세(70.3%)=BS값 옳음 방증 → detector 자동판정 가능
      혼재(25.5%)=근거부족 → 격리(status='held')
      원문우세(3.0%)=오히려 BS 의심 → 사람 확인 필수(decided_by='human' 대기)
    """
    __tablename__ = "report_line_corrections"

    id             = Column(BigInteger, primary_key=True, autoincrement=True)
    rcept_no       = Column(String(14), ForeignKey("filings.rcept_no"), nullable=False, index=True)
    corp_code      = Column(String(8),  nullable=False, index=True)

    # ── 적용 범위 ──────────────────────────────────────────────────────
    scope          = Column(String(8),  nullable=False, comment="filing | table | row")
    statement      = Column(String(10), nullable=True,  comment="scope=filing 이면 NULL=전 재무제표")
    basis          = Column(String(12), nullable=True)
    table_seq      = Column(SmallInteger, nullable=True, comment="scope in (table,row) 에서 NOT NULL")
    row_order      = Column(SmallInteger, nullable=True, comment="scope=row 에서 NOT NULL")
    col_index      = Column(SmallInteger, nullable=True)

    # ── 연산 ───────────────────────────────────────────────────────────
    operation      = Column(String(16), nullable=False,
                            comment="set_adecimal(단위) | negate(부호) | replace(값교체)")
    op_adecimal    = Column(SmallInteger, nullable=True, comment="operation=set_adecimal 일 때")
    op_value       = Column(BigInteger,   nullable=True, comment="operation=replace 일 때(원 단위)")

    # ── 재추출 내구성 지문 ─────────────────────────────────────────────
    expect_label   = Column(Text,       nullable=True, comment="scope=row 필수 — 지목행 라벨 지문")
    expect_value   = Column(BigInteger, nullable=True, comment="scope=row 필수 — 지목행 원문값 스냅샷")
    expect_row_count = Column(Integer,  nullable=True, comment="scope in (filing,table) — 표 행수 지문")

    # ── 감사 추적 ──────────────────────────────────────────────────────
    evidence       = Column(String(24), nullable=False,
                            comment="bs_crosscheck | bs_series_link | manual_source_check | correction_filing")
    evidence_detail= Column(Text,       nullable=True)
    cross_verdict  = Column(String(8),  nullable=True, comment="제안우세 | 혼재 | 원문우세(BS시계열 교차)")
    decided_by     = Column(String(8),  nullable=False, comment="detector | human")
    # server_default: 원시 SQL INSERT(보정 스크립트·수동 판정)에서도 채워지도록 DB 기본값 사용.
    decided_at     = Column(DateTime,   nullable=False,
                            default=datetime.utcnow, server_default=func.now())
    source_anomaly_id = Column(BigInteger,
                              ForeignKey("report_line_anomalies.id", ondelete="SET NULL"),
                              nullable=True)
    status         = Column(String(8),  nullable=False, default="active",
                            server_default=sa_text("'active'"),
                            comment="active(적용) | held(격리·근거대기) | stale(지문불일치) | retired")

    __table_args__ = (
        CheckConstraint("scope IN ('filing','table','row')", name="ck_rlc_scope"),
        CheckConstraint("operation IN ('set_adecimal','negate','replace')", name="ck_rlc_op"),
        CheckConstraint("status IN ('active','held','stale','retired')", name="ck_rlc_status"),
        CheckConstraint("decided_by IN ('detector','human')", name="ck_rlc_decided_by"),
        # scope 별 필수 컬럼
        CheckConstraint(
            "scope <> 'row' OR (row_order IS NOT NULL AND table_seq IS NOT NULL "
            "AND expect_label IS NOT NULL AND expect_value IS NOT NULL)",
            name="ck_rlc_row_required"),
        CheckConstraint("scope <> 'table' OR table_seq IS NOT NULL", name="ck_rlc_table_required"),
        # operation 별 필수 컬럼
        CheckConstraint("operation <> 'set_adecimal' OR op_adecimal IS NOT NULL",
                        name="ck_rlc_setadec_val"),
        CheckConstraint("operation <> 'replace' OR op_value IS NOT NULL", name="ck_rlc_replace_val"),
        # set_adecimal 은 표/보고서 단위만 의미 있다(단위는 표 전체 속성)
        CheckConstraint("operation <> 'set_adecimal' OR scope IN ('filing','table')",
                        name="ck_rlc_setadec_scope"),
        # 뷰 조인용 부분 인덱스(active 만)
        Index("ix_rlc_row", "rcept_no", "statement", "table_seq", "row_order", "col_index",
              postgresql_where=sa_text("status='active' AND scope='row'")),
        Index("ix_rlc_scope_tab", "rcept_no", "statement", "table_seq",
              postgresql_where=sa_text("status='active' AND scope<>'row'")),
        # 같은 대상에 같은 연산이 두 번 붙는 사고 방지(active 만)
        Index("uq_rlc_target", "rcept_no",
              func.coalesce(Column("statement"), ""), func.coalesce(Column("basis"), ""),
              func.coalesce(Column("table_seq"), -1), func.coalesce(Column("row_order"), -1),
              func.coalesce(Column("col_index"), -1), "operation",
              unique=True, postgresql_where=sa_text("status='active'")),
    )

    def __repr__(self):
        return (f"<ReportLineCorrection {self.corp_code} r{self.rcept_no} "
                f"{self.scope}/{self.operation} [{self.status}]>")


# ── 9. 계층3 산출 (std_financials_v3, 4계층 신 체인, L3-3 2026-07-23) ──────────────
class StdFinancialV3(Base):
    """계층3(조합) 산출물 — report_lines(계층2)에서 조립한 표준 재무. 신 체인 단독.

    std_financials_v2(구 체인, fact_v2 경유)와 **동일 값 컬럼 계약**을 미러링하되, 출처는
    report_lines 이고 조립은 `fin2.layer3.combine` 이다. swap 전까지 std_v2 와 병행 존재하며
    L3-4 parity 대조 후 앱을 이쪽으로 전환한다(계획 결정 #2: 새 테이블 후 swap).

    ★provenance(구 체인엔 없던 것):
      - source_rcepts : {statement: rcept} — 각 재무제표를 실제로 읽은 정본 filing(statement 단위).
      - amended_cols  : 기재정정 반영으로 값이 온 std 컬럼 목록(최초등록본+델타패치, L3-1b).
      - amend_chain   : {std_col: [rcept,...]} — 그 컬럼을 고친 정정본 순서(감사·as-filed 복원용).
      - basis_fallback: 단일 basis 기업(연결 없음→별도) 폴백 사용 여부(L3-2).
      - conflicts     : 조립 중 값이 갈려 보류한 canonical(결측 근거).

    값 컬럼은 combine 의 DIRECT_MAP 산출분(BS/IS/CF 직접매핑). 합산/파생(D&A·EBITDA·차입합계
    ·capex)은 후속(rules.py additive 이식). 신규 테이블 → create_all 자동 생성.
    """
    __tablename__ = "std_financials_v3"

    corp_code      = Column(String(8),    primary_key=True)
    fiscal_year    = Column(SmallInteger, primary_key=True)
    fiscal_period  = Column(String(5),    primary_key=True)   # FY/H1/Q1/Q3
    statement_type = Column(String(12),   primary_key=True)   # consolidated/separate
    period_end     = Column(Date,         nullable=True)

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
    dividends_paid      = Column(BigInteger, nullable=True)
    # ── enrichment (v3-native, 2026-07-25: std_v2 컬럼 파리티) ──
    # capex/fcf/net_debt = combine 이 run_rules(rule_additive_capex·derive_fcf·derive_net_debt)로 산출.
    # depreciation/amortization/da_total/ebitda = cf_da 백필(주석+CF본문 하이브리드, ~34%) 후 UPDATE.
    # shares_out = shares 백필, data_quality = DQ 백필. ★재빌드가 행을 delete-insert 하므로
    # 백필은 재빌드 후 재실행 필요(v2 동일 패턴).
    capex               = Column(BigInteger, nullable=True)
    depreciation        = Column(BigInteger, nullable=True)
    amortization        = Column(BigInteger, nullable=True)
    da_total            = Column(BigInteger, nullable=True)
    ebitda              = Column(BigInteger, nullable=True)
    fcf                 = Column(BigInteger, nullable=True)
    net_debt            = Column(BigInteger, nullable=True)
    shares_out          = Column(BigInteger, nullable=True)
    data_quality        = Column(SmallInteger, nullable=True)

    # ── provenance ──
    source_rcepts   = Column(JSONB, nullable=True, comment="{statement: rcept} 정본 filing(statement 단위)")
    amended_cols    = Column(JSONB, nullable=True, comment="기재정정 반영으로 값이 온 std 컬럼 목록")
    amend_chain     = Column(JSONB, nullable=True, comment="{std_col: [rcept,...]} 정정본 순서")
    basis_fallback  = Column(Boolean, default=False, comment="단일 basis 기업 반대 basis 폴백")
    conflicts       = Column(JSONB, nullable=True, comment="값 충돌로 보류한 canonical")
    # 업종별 매출 성분(P1) — K-IFRS 표준이 일반기업과 다른 업종(보험 등)에서 revenue 를
    # 소계 합산으로 조립하고 그 성분을 보존. {"profile":"insurance","insurance_revenue":…,
    # "investment_revenue":…}. general 기업=NULL. tearsheet 업종별 표시·조립 revenue 표식용.
    industry_lines  = Column(JSONB, nullable=True, comment="업종별 매출 성분(보험 등 조립 revenue)")
    built_at        = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_stdv3_screening", "fiscal_year", "fiscal_period", "statement_type"),
        Index("ix_stdv3_corp_year", "corp_code", "fiscal_year"),
    )

    def __repr__(self):
        return f"<StdFinancialV3 {self.corp_code} {self.fiscal_year}{self.fiscal_period} {self.statement_type}>"
