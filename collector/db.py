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
    ]

    with engine.begin() as conn:
        for sql in migrations:
            conn.execute(text(sql))

    logger.info(f"마이그레이션 {len(migrations)}건 적용 완료")


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
