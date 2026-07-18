# 전문가 리뷰 — 재무 데이터 팜 & 투자 발굴 시스템 (tj_finance)

## Context (왜 이 리뷰인가)

목표: DART 공시 수집 → 전 재무정보 추출·DB화 → **재무 데이터 팜** → 재무성과 평가·시장평가지표 →
**투자 기업 발굴**. 이 큰 목표 기준으로 현 프로젝트를 4개 전문가 렌즈로 점검하고, **데이터 무결성**을
최우선으로 개선 로드맵을 제시한다. (현황 정찰 3개 + 2026 best-practice 웹조사 근거.)

**현 상태 한 줄**: 파이프라인(수집→추출→표준화→달력화→주가결합)과 report==DB 감사(Gate A/B)까지
탄탄하게 구축됨. 남은 격차는 ① 운영 안전(백업)·성능 ② **무결성의 독립 교차검증·상시화** ③ 이미 DB에
있으나 화면에 안 쓰는 데이터 자산.

**이번 산출물(사용자 확정)**: 이 리뷰를 `docs/prd/08_expert_review.md` 로 저장 + 아래 로드맵 확정.
개별 항목 구현은 착수 시 별도 상세계획. **무결성 P0는 I1→I2→I3 순차 전부 진행** 확정.

---

## 종합 평가 (투자자 목표 관점)

**강점**: 20년+ 재무(std_financials_v2 533K행)·일별 주가/시총(stock_prices 11.2M) 결합, report==DB
line audit value_diff=0, 지표 레지스트리(48종)+대가지표(Buffett/Graham/Greenblatt/Lynch/Fisher/
Piotroski)+스크리너(윈도우 집계·멀티패스)+DCF/배당. 엔진 재사용 구조 우수.

**전략적 격차 3가지**:
1. **신뢰(무결성)**: 모든 검증이 "보고서 XML ↔ DB" 자기일관성뿐 — **독립 소스 교차검증 0**, 일일 수집분은
   무검증 통과. 투자 판단의 토대인데 "가장 중요"한 부분에 구멍.
2. **운영 안전/성능**: 89GB 단일 사본 **백업·PITR 전무**(최고위험). fact_v2 인덱스 43GB 낭비, 스톡 튜닝.
3. **데이터 활용**: executives(임원보수)·order_backlog(수주)·일별 PER/PBR/배당수익률 등 **DB에 있는데
   화면에 전혀 안 나오는** 고가치 자산 다수.

---

## 1. DB 운용 전문가 리뷰

**측정치**: `pg_database_size`=89GB, 이 중 **fact_v2 = ~86GB(97%)**(heap 43GB + 인덱스 43GB, 87.2M행).
소비계층은 작음(std_v2 301MB·calendar 201MB·stock_prices 1.5GB). 뷰 4개 전부 일반뷰(matview·파티션 0).
엔진 `pool_size=5/overflow=10/pre_ping`(collector·app 공유), 인증=**passwordless localhost trust**.

**핵심 지적(우선순위)**
1. **백업·PITR 전무 = 최고위험**: crontab 비어있고 `pg_dump`/`archive_command` 없음, `archive_mode=off`.
   디스크 사고=89GB 전손. → 야간 `pg_dump`(소비계층) + `archive_mode=on` WAL 아카이빙 또는 주기 basebackup.
2. **fact_v2 인덱스 낭비 ~9GB 회수 가능**: `ix_fact_v2_is_dimensional`(scan 0, 2GB)·`ix_fact_v2_corp_code`
   (ix_fact_v2_lookup의 좌프리픽스 중복, 2.8GB)·`ix_fact_v2_report_fiscal_year`(scan 31)·surrogate
   `fact_v2_pkey`(scan 11, 4.2GB, FK 참조 없음) 재평가. **stock_prices 중복 인덱스** `ix_sp_stock_date`==
   `uq_stock_prices`(683MB) 드롭.
3. **스톡 튜닝**(89GB 분석 워크로드엔 과소): `shared_buffers 128MB`·`work_mem 4MB`·`maintenance_work_mem
   64MB`·`effective_cache_size 4GB`·`random_page_cost 4`(SSD면 ~1.1). 상향 필요.
4. **분석계층 물질화**: `valuation_daily`가 11.2M 주가행마다 LATERAL로 최신FY 재무 조인하는 일반뷰 →
   **매일 수집 후 refresh하는 materialized view**로. 2026 best practice = matview 계층 + (선택) `pg_duckdb`
   컬럼엔진으로 분석쿼리 10~100× 가속.
5. **VACUUM/bloat**: fact_v2 dead 12.8M(~15%), 수동 VACUUM/ANALYZE 이력 전무. fact_v2 `autovacuum_vacuum_
   scale_factor` 하향(테이블 storage param) + 주기 `VACUUM(ANALYZE)`.
6. **마이그레이션 거버넌스**: Alembic 없이 `collector/db.py:_run_migrations`가 30개 DDL을 **매 부팅 재실행**
   (idempotent이나 PK rebuild가 ACCESS EXCLUSIVE). → `schema_migrations` 버전테이블 또는 Alembic 도입.
7. **보안**: 개인 박스라도 role+password 부여.
8. (관찰) 같은 클러스터에 `fin_data_lake` DB + `com.dart.financial.worker.plist` 존재 — 리소스 경합 확인.

핵심 파일: `collector/db.py`(엔진·마이그레이션·뷰), `collector/config.py:44`, `app/data/screen_window.py`.

---

## 2. 데이터 무결성 전문가 리뷰 ★최우선

### 이미 있는 보증(강함)
- **Gate A**(`validate_downloads.py`/`verify_corp_sequential.py`): 파일 무결·추출존재 → `download_tasks.gate_a_status`.
- **Gate B Phase A**(`fin2/audit/face_audit.py`): 보고서 면표를 **독립 reader**(Track A/B/C)로 재판독해
  std_v2 헤드라인 ~25필드를 won-space ±1 표시단위로 대조. **face_audit 271,197 pass / 0 fail**(2,554사).
- **Gate B Phase B**(`fin2/audit/line_audit.py`): Track A 전 면표라인 ↔ fact_v2 정확대조. **value_diff=0**,
  MISSING_IN_DB 2,474(완전성 지표, 비차단).
- **빌드시 항등식**(`fin2/standardize/rules.py:validate_equations`): 자산=부채+자본·매출−매출원가≈매출총이익
  → `data_quality`(DQ1 445,785/DQ2 86,720/DQ3 1,163). 소비계층은 `data_quality<3` 필터.
- **소스선택**(`fin2/reconcile.py`): BS/IS/CF 독립·기재정정 우선(over-supersede·×1000 해결). golden 5케이스+parity.

### 격차/약점 (DQ 전문가가 파고들 지점)
1. **★독립 교차검증 0 (최대 격차)**: 모든 검증이 보고서↔DB 자기일관성뿐. KRX/pykrx·Naver는 유니버스·
   주가에만 쓰고 **재무 수치 교차검증엔 미사용**. DART 자체 재무API(`fnlttSinglAcnt`/`MultiAcnt`)도 대조에
   안 씀. → **보고서와 DB가 똑같이 틀린 ×1000·부호오류는 Gate B를 조용히 통과**.
2. **★수집시 무결성 검사 없음**: 일일 `collect_new.py`(launchd 18:00)에 verify/gateb/golden/항등식 호출
   전무. **매일 들어오는 데이터는 무검증**. 검증은 전부 수동 1회성.
3. **죽은 검증계층**: `analyzer/verifier.py`(IS체인·연속성 등 풍부)가 `verification_results`에 쓰는데 **0행**
   + 레거시 뷰 대상 → 사실상 미실행. `corp_verify_status`도 **0행**(orchestrator 미완) → "검증된 corp %"
   질의 불가.
4. **미래기간 유령행(참조무결성 위반)**: std_v2에 `period_end>오늘` 8행(예: 2026-09-30 Q3, 실매출값) +
   불가능 미래기간(FY2026 22·Q3 84·Q2 54행 등). 달력가드는 전파는 막지만 **Layer-1에 잔존**, `period_end
   > now()` CHECK 없음. (이전 세션에서 phantom 달력분기는 수정·`diag_calendar_orphans.py` 상주화.)
5. **검증 범위가 Track A(XBRL)에 국한**: Track B(텍스트)·C(PDF)는 line audit **pending 107,847** — PDF-only
   3,044·텍스트 보고서는 report==DB 검증 자체가 없음. 커버리지 갭(`docs/known_gaps_db_coverage.md`):
   pre-2010 K-GAAP 13,508·2015+ 이질 83 등.
6. **Gate B fail 0의 역설**: 274k 감사행 fail_a/b=0은 from-scratch 파이프라인치고 지나치게 깨끗 → 감사
   범위가 좁아 under-report인지 재확인 필요. golden 5케이스는 87.9M fact 대비 얇고 레거시 뷰를 가리킴.

### 신규 검증 아이디어 (2026 best practice 근거)
- **A. 교차검증(cross-source reconciliation)** ★최대효과: DART 오픈API `fnlttSinglAcnt` 로 corp/연도 표본의
  매출·자산·순이익을 당겨 std_v2와 diff(결정적 키매칭·감사가능). 선택적으로 KRX/FnGuide 시장수치 삼각검증.
  → "보고서==DB"를 넘어 "**진실==DB**"로 격상.
- **B. 수집시 상시 DQ 게이트**: `collect_new.py` 표준화 직후 **터치된 corp만** `gateb_audit.audit_corp` +
  `validate_equations` 실행, 실패 시 loud fail, `corp_verify_status`/`verification_results` 채움 → 대시보드
  실수치 확보. (Great Expectations/Soda/dbt-test 패턴의 경량 자가구현 — 이미 엔진 존재, 배선만.)
- **C. 참조무결성 SQL 어서션(경량·빠름)**: `period_end<=now()` · CY 없이 4CQ 불가 · 달력 orphan 0
  (`diag_calendar_orphans.py` 승격) · 명세당 단일소스 · consolidated≥separate(지주 자산/매출) — 야간 쿼리로
  검사·리포트.
- **D. 통계/이상치 확장**: `_dq_cross_year`(현 200×/30×)에 **부호반전·YoY 10×·basis 불일치** 추가.
- **E. 죽은 계층 부활**: `analyzer/verifier.py`를 std_v2 대상으로 재배선(IS체인·net_income=ebt−tax 항등식 기록).
- **F. golden 세트 확대 + std_v2로 재조준**, parity 동일.

---

## 3. 데이터 표시(시각화/제품) 전문가 리뷰

**현재**(7페이지): 기업 시각화(재무제표·지표·밸류에이션·대가지표·주가·주가재무결합) / 스크리너(윈도우
집계·멀티패스·분할뷰) / 분기변화(QoQ·YoY+모달) / 밸류에이션(DCF·배당) / 기업비교 / 수집 / 도움말.

### 개선 기회
**A. 이미 DB에 있는데 안 쓰는 자산(빠른 고효율)**
1. **일별 PER/PBR/배당수익률 히스토리 밴드**(stock_prices에 per/pbr/eps/bps/div_yield/dps 일별 저장중) —
   "자기 역사 대비 싸다/비싸다" 밸류에이션 밴드. **최대 quick win**(신규 데이터 0).
2. **주당지표·주식수 추이**(EPS/BPS/FCF per share, 자사주/희석) — std에 기간별 shares_out 보유, 현재 최신값만.
3. **EV/EBITDA·멀티플 시계열**(현재 최신FY만 표시).
4. **임원보수·지배구조 패널**(`executives` 테이블 완전 미사용) + **수주잔고 추이**(`order_backlog` 미사용) —
   조선·건설·방산·반도체 투자에 고가치.
5. **데이터 신뢰 배지**(`face_audit`/Gate B pass)를 재무제표 옆에 — 무결성 작업과 직접 연결.

**B. 상용 서비스 대비 격차(구조 필요)**
6. **섹터/피어 벤치마킹**: 스키마에 산업분류(DART 업종/GICS) 없음 → 섹터중앙값·백분위·"vs 피어" 불가.
   산업코드 추가가 선행조건.
7. **워치리스트·저장된 스크린·알림**: 전무.
8. **재무제표 라인 → 원천 공시 드릴다운**(rcept 이미 저장: bs/is/cf_rcept, face_line_audit).
9. **차트 고도화**: 이동평균·지수대비 상대강도·주석, 중앙 테마/다크모드, **모바일 반응형**(5:7 분할 미대응).
10. **티어시트 export**(PDF/Excel, 현재 CSV만).

핵심 파일: `app/views/*`, `app/registry/metrics.py`, `app/compute/*`, `analyzer/*`(엔진 재사용).

---

## 4. 통합 우선순위 로드맵

**P0 — 신뢰·안전 토대 (무결성 최우선 + 운영 안전) — 무결성은 I1→I2→I3 순차 전부 진행**
- I1. **DART API 교차검증 배치**(§2-A): 표본 corp/연도 재무 diff 리포트. *신규* `scripts/verify_cross_source.py`.
- I2. **수집시 DQ 게이트 상시화**(§2-B): `scripts/collect_new.py`에 gateb+항등식 훅, `corp_verify_status`/
  `verification_results` 적재. `collect.err.log`에 요약.
- I3. **참조무결성 SQL 어서션 야간실행**(§2-C): `diag_calendar_orphans.py` 확장 → `scripts/dq_assertions.py`.
- D1. **백업/PITR**(§1-1): 야간 `pg_dump` + WAL 아카이빙. *신규* `deploy/launchd/com.tjfinance.backup.plist`.
  (I1→I2→I3 순으로 착수하되 D1 백업은 병행 권장 — 최고위험 완화가 먼저일수록 안전.)

**P1 — 성능·정합 정리**
- D2. 인덱스 정리(~9.7GB 회수) + D3. `valuation_daily` matview화(+수집후 refresh) + D4. postgres.conf 튜닝 +
  D5. VACUUM/ANALYZE 정례화. I4. `analyzer/verifier.py` std_v2 재배선 + golden 확대.

**P2 — 활용/제품 고도화**
- V1. 밸류에이션 밴드(일별 PER/PBR/배당) → V2. 주당·주식수 추이 → V3. 멀티플 시계열 → V4. 임원보수·수주
  패널 → V5. 신뢰배지. (구조) V6. 산업분류 추가→피어 벤치마킹, V7. 워치리스트/알림, V8. 라인 드릴다운.

각 항목 착수 시 별도 상세계획으로 분해. **원칙: 기존 엔진·감사 자산 재사용, 재작성 금지.**

---

## 검증 (개선 확인 방법)
- **무결성**: 교차검증 리포트의 불일치 건수·비율; 수집 후 `corp_verify_status` 실채움 + fail loud 동작;
  `dq_assertions.py` 전 어서션 0위반; golden 확대분 통과.
- **DB**: 백업 복원 리허설 성공; 인덱스 드롭 후 디스크 회수·핫쿼리 무저하; matview 후 스크리너/밸류 응답 단축.
- **표시**: 신규 패널이 실서버·AppTest 무예외로 렌더, 값이 오라클(CLI/엔진)과 일치.

## 출처 (2026 웹조사)
- 데이터품질 프레임워크: [Atlan open-source DQ tools](https://atlan.com/open-source-data-quality-tools/) · [dbt vs GE vs Soda](https://cybersierra.co/blog/best-data-quality-tools/)
- Postgres 분석 스케일: [7 ways to scale Postgres 2026](https://www.velodb.io/glossary/ways-to-scale-postgresql) · [pg_duckdb](https://github.com/duckdb/pg_duckdb)
- 금융 무결성/교차검증: [cross-system reconciliation (arXiv 2604.15108)](https://arxiv.org/abs/2604.15108) · [XBRL US validation rules](https://xbrl.us/home/priorities/data-quality/rules-guidance/)
