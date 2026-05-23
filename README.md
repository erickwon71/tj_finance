# TJ Finance — DART PDF 수집 시스템 (Phase 1)

KOSPI/KOSDAQ 상장 기업의 분기·반기·사업보고서 최종본 PDF를  
DART 전자공시에서 자동 수집해 로컬에 저장합니다.

---

## 빠른 시작

### 1. 환경 설정

```bash
cd ~/Project/tj_finance

# 가상환경 활성화
source .venv_tj_finance/bin/activate

# 패키지 설치 (최초 1회)
pip install -r requirements.txt
```

### 2. PostgreSQL DB 생성 (최초 1회)

```bash
createdb tj_finance          # 또는 psql로 직접 생성
```

### 3. .env 확인

`.env` 파일의 `DATABASE_URL`을 본인 PostgreSQL 환경에 맞게 수정하세요.

```
DATABASE_URL=postgresql://localhost/tj_finance
```

### 4. DB 초기화 (최초 1회)

```bash
python run.py init
```

---

## 수집 실행 순서

```bash
# Step 1: 기업 목록 동기화 (DART corpCode — API 1콜)
python run.py sync-corps

# Step 2: 공시 목록 동기화 (전체 기업 — 기업당 ~1-3콜)
python run.py sync-filings

# Step 3: PDF 다운로드
python run.py download

# 또는 한 번에 (위 3단계 순서 실행)
python run.py all
```

---

## 주요 명령어

| 명령어 | 설명 |
|--------|------|
| `python run.py init` | DB 테이블 생성 (최초 1회) |
| `python run.py sync-corps` | DART에서 기업 목록 갱신 |
| `python run.py sync-filings` | 전체 기업 공시 목록 수집 |
| `python run.py sync-filings --corp 00126380` | 특정 기업만 |
| `python run.py download` | 전체 PDF 다운로드 |
| `python run.py download --limit 100` | 최대 100건만 |
| `python run.py download --corp 00126380` | 특정 기업만 |
| `python run.py status` | 수집 현황 요약 |
| `python run.py failed` | 실패 목록 확인 |
| `python run.py reset-failed` | 실패 건 재시도 등록 |

---

## 디렉토리 구조

```
tj_finance/
├── .env                    # API 키, DB URL
├── requirements.txt
├── run.py                  # CLI 진입점
├── collector/
│   ├── config.py           # 전역 설정
│   ├── models.py           # DB 모델
│   ├── db.py               # PostgreSQL 연결
│   ├── rate_limiter.py     # API 호출 속도 제한
│   ├── dart_client.py      # DART API 클라이언트
│   ├── corp_collector.py   # 기업 목록 수집
│   ├── filing_collector.py # 공시 목록 수집
│   ├── downloader.py       # PDF 다운로드
│   └── runner.py           # 현황 조회
├── raw_report/             # PDF 저장 루트
│   ├── KOSPI/
│   │   └── {corp_code}_{corp_name}/
│   │       ├── annual/{year}/{rcept_no}.pdf
│   │       ├── half/{year}/{rcept_no}.pdf
│   │       └── quarter/{year}/{rcept_no}.pdf
│   └── KOSDAQ/
├── logs/                   # 날짜별 로그 파일
└── tmp/                    # ZIP 임시 압축 해제
```

---

## API 호출 한도 관리

- 하루 **40,000콜** 한도
- 콜 간 **2.5초** 간격 자동 강제 → 하루 최대 ~34,500콜 (버퍼 14%)
- 한도 도달 시 자정까지 자동 대기 후 재개
- `python run.py status`로 당일 사용량 확인 가능

---

## DB 테이블

| 테이블 | 설명 |
|--------|------|
| `corporations` | 기업 마스터 (DART corp_code 기준) |
| `filings` | 공시 메타데이터 + 기재정정 버전 관리 |
| `download_tasks` | 다운로드 상태 추적 (resume 지원) |
| `collection_runs` | 실행 이력 로그 |

---

## 자동화 (선택)

매일 자동 실행이 필요하면 crontab 설정:

```bash
crontab -e
# 매일 오전 2시 실행 (sync-filings는 주 1회, download는 매일)
0 2 * * * cd /Users/taejin/Project/tj_finance && .venv_tj_finance/bin/python run.py download >> logs/cron.log 2>&1
0 3 * * 0 cd /Users/taejin/Project/tj_finance && .venv_tj_finance/bin/python run.py sync-filings >> logs/cron.log 2>&1
```
