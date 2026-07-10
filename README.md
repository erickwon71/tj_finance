# TJ Finance

KOSPI/KOSDAQ 상장 보통주의 재무·경영·시장 데이터를 DART 전자공시에서 수집·표준화해
PostgreSQL에 적재하고, 주가와 연동해 시각화하는 로컬 분석 시스템. (v1.0)

---

## 기능별 구조

| 기능 | 위치 | 설명 |
|------|------|------|
| **보고서 수집** | `collector/` | DART Open API 클라이언트(`dart_client`), 다운로더(`downloader`), 웹/PDF 폴백(`legacy_downloader`), 공시·기업 목록 수집(`filing_collector`, `corp_collector`), 도메인 수집기(임원·수주·증자·주주 등). 원본은 `raw_report/`(외장 볼륨 심볼릭 링크). |
| **파싱·추출** | `fin2/` (현행) | 현행 엔진: 추출(extract) → 정합(reconcile) → 표준화(standardize). 산출 테이블 `fact_v2` → `statement_source` → `std_financials_v2`. |
| | `parser/` (레거시) | 구 엔진(financial_facts/standard_financials). 유지만 하며 v1.0 메인 파이프라인 아님. |
| **데이터베이스** | `collector/db.py`, `collector/models.py`, `collector/config.py` | 로컬 PostgreSQL. `db.py`가 엔진/세션/인라인 마이그레이션, `models.py`가 ORM/DDL, 설정은 `.env`. (Alembic 미사용) |
| **분석 엔진** | `analyzer/` | 재무비율·밸류에이션·DCF·배당·버핏·스크리너·비교 엔진. |
| **시각화 앱** | `app/` | Streamlit + Plotly. 실행: `streamlit run app/main.py`. |
| **운영·스케줄링** | `scripts/`, `deploy/launchd/` | 일일 수집·DQ·백업·VACUUM 등. 1회성/과거 처리 스크립트는 `scripts/archive/`로 분리. |
| **문서** | `docs/` | PRD(`docs/prd/`), QA(`docs/qa/`), 사용자 매뉴얼·런북. 과거 기록은 `docs/archive/`. |

---

## 빠른 시작 (최초 1회)

```bash
cd ~/Project/tj_finance
source .venv_tj_finance/bin/activate
pip install -r requirements.txt

createdb tj_finance            # 로컬 PostgreSQL
# .env 의 DATABASE_URL / OPENDART_API_KEY 확인
python run.py init             # DB 테이블 생성
```

---

## 일일 파이프라인

메인 수집→파싱→적재는 `scripts/collect_new.py`가 담당하며 launchd로 매일 자동 실행됩니다
(`deploy/launchd/com.tjfinance.collect`, 18:00).

```bash
# 수동 실행 예시 — 최근 3일 신규 공시 수집→fin2(E→R→S)→보조수집→밸류에이션 갱신
python scripts/collect_new.py --days 3 --timeout 600 --refresh-universe
```

흐름: 신규 공시 감지 → 다운로드 → 기업별 fin2 추출·정합·표준화 → 분기/캘린더 파생
→ 보조 수집기(임원·증자·수주·현금흐름 D&A 등) → 밸류에이션 일일 갱신.

---

## 주요 명령어

```bash
# 수집 (현행)
python run.py sync-corps            # 기업 목록 갱신
python run.py sync-filings          # 공시 목록 수집
python run.py download              # 원본 다운로드
python run.py status                # 수집 현황

# 재무 표준화 (현행 fin2 엔진)
python run.py fin2-all              # 기업별 extract2 → reconcile2 → standardize2 (+quarterly/calendar)
python run.py fin2-all --corp 00126380

# 시각화
streamlit run app/main.py
```

> 레거시 명령(`run.py parse | parse-pdf | aggregate`, `parser/`)은 구 엔진 경로로,
> 유지만 하며 신규 작업에는 사용하지 않습니다.

---

## 운영

- **스케줄**: `deploy/launchd/` — 수집(`collect`)·DQ 점검(`dqcheck`)·백업(`backup`)·VACUUM(`vacuum`)·복원 드릴(`restoredrill`).
- **백업/복원**: `docs/runbook_backup_restore.md`. 백업은 `scripts/backup_db.py`(야간 pg_dump, NAS).
- **스크립트 맵**: 메인 vs 아카이브 구분은 `scripts/README.md` 참고.
- **대용량 산출물**(QA 스크린샷·parity baseline·coverage 덤프)은 리포 밖 `~/tj_finance_archive/`에 보관.

---

## 편의 명령 (Makefile)

```bash
make app        # 시각화 앱 실행
make collect    # 최근 3일 신규 수집 파이프라인
make backup     # DB 백업
make dq         # 야간 DQ 점검
```
