"""
SQLAlchemy ORM 모델 정의
테이블: corporations / filings / download_tasks / collection_runs
"""
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime,
    ForeignKey, Integer, String, Text, UniqueConstraint, Index
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
    file_type        = Column(String(5),   nullable=True,   comment="pdf/html/hwp/zip")
    file_size        = Column(BigInteger,  nullable=True,   comment="바이트")
    attempts         = Column(Integer,     default=0,       comment="시도 횟수")
    last_error       = Column(Text,        nullable=True,   comment="마지막 오류 메시지")
    last_attempt_at  = Column(DateTime,    nullable=True)
    completed_at     = Column(DateTime,    nullable=True)
    created_at       = Column(DateTime,    default=datetime.utcnow)

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
