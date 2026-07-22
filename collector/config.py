"""
시스템 전역 설정
- .env 파일에서 환경변수 로드
- 경로, API 파라미터 등 상수 정의
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 기준으로 .env 로드
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

# ── 경로 설정 ──────────────────────────────────────────
RAW_REPORT_DIR = BASE_DIR / "raw_report"   # PDF 저장 루트
LOG_DIR        = BASE_DIR / "logs"          # 로그 파일
TMP_DIR        = BASE_DIR / "tmp"           # ZIP 임시 압축 해제

# ── DART API ────────────────────────────────────────────
DART_API_KEY  = os.getenv("OPENDART_API_KEY", "")
DART_BASE_URL = "https://opendart.fss.or.kr/api"

# ── API 호출 한도 관리 ──────────────────────────────────
DAILY_CALL_LIMIT = 40_000   # DART 하루 허용 콜 수

# 요청 유형별 최소 대기 시간
# - metadata (list.json 등 JSON 조회): 가벼운 요청, 1.0초
# - document (document.xml ZIP 다운로드): 파일 크기가 크므로 별도 관리
#   실제로는 다운로드 자체에 시간이 걸려 추가 딜레이 불필요
MIN_REQUEST_INTERVAL          = 1.0   # metadata API 기본 간격 (초)
MIN_DOWNLOAD_INTERVAL         = 0.5   # 다운로드 완료 후 추가 대기 (초)
                                      # 다운로드 시간 자체가 자연 딜레이 역할

# ── 재시도 설정 ─────────────────────────────────────────
MAX_RETRIES      = 5    # 최대 재시도 횟수
RETRY_WAIT_MIN   = 5    # 첫 재시도 대기(초)
RETRY_WAIT_MAX   = 120  # 최대 대기(초)

# ── 다운로드 설정 ───────────────────────────────────────
DOWNLOAD_TIMEOUT = 120          # 초 (대용량 PDF 대비)
MAX_DOWNLOAD_ATTEMPTS = 3       # 다운로드 실패 시 재시도 횟수

# ── DB ─────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost/tj_finance"   # 기본값: 수정 필요
)

# ── 수집 대상 보고서 유형 매핑 ───────────────────────────
# DART report_nm 키워드 → 내부 타입
REPORT_TYPE_MAP = {
    "사업보고서": "annual",
    "반기보고서": "half",
    "분기보고서": "quarter",
}

# ── 기업 목록 필터 ──────────────────────────────────────
# 이름에 아래 키워드가 포함된 종목은 수집 제외 (is_active=False 처리)
CORP_EXCLUDE_KEYWORDS = [
    # 기업인수목적 (SPAC)
    "스팩", "SPAC", "기업인수목적",
    # 선박투자회사 — 선박 1척 보유 페이퍼컴퍼니 (SPC)
    "선박투자",
    # 리츠(REITs) / 부동산투자회사 — 별도 수집 예정
    "리츠", "부동산투자회사",
    # 인프라펀드
    "인프라투자",
    # 집합투자기구 (펀드형 상장법인) — 가장 넓은 범주
    # "투자회사"가 사명에 들어간 경우는 자본시장법상 집합투자기구 구조
    # (유전개발, 주식혼합형, 해외자원개발 등 모든 SPC 펀드 포괄)
    "투자회사",
]

# Phase 2에서 별도 수집할 특수 카테고리 (현재는 제외, 추후 확장)
# REIT_KEYWORDS   = ["리츠", "부동산투자회사"]
# INFRA_KEYWORDS  = ["인프라투자", "맥쿼리"]
# SHIP_KEYWORDS   = ["선박투자"]

# 수집 시작 일자
COLLECT_START_DATE = "20000101"

# ── 디렉토리 자동 생성 ──────────────────────────────────
# RAW_REPORT_DIR 는 NAS(SMB) 심링크일 수 있다. NAS 미마운트 시 심링크는 "존재하지만 대상 없음"
# (broken symlink) 상태가 되고, 그때 mkdir(exist_ok=True) 는 FileExistsError 로 죽는다 → import
# 자체가 실패해 DB 전용 작업(원문 파일이 필요 없는 조회·표준화)까지 막힌다. 이미 존재하거나
# 심링크면 생성하지 않는다(NAS 마운트 시 동작 불변). 실제 원문 접근은 사용 시점에 자연히 실패한다.
for _d in (RAW_REPORT_DIR, LOG_DIR, TMP_DIR):
    if _d.is_symlink() or _d.exists():
        continue
    _d.mkdir(parents=True, exist_ok=True)
