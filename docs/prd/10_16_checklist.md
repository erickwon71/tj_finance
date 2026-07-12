# 진행 체크리스트 — 전문 서비스 갭 채우기(PRD 10~16)

> 마스터 계획 `~/.claude/plans/cosmic-stirring-snail.md` / `10_gap_fill_plan.md`.
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. 각 Phase 는 검증 통과 후 다음으로.
> Phase 0·1·3·4 는 상호 독립 — 순서를 꼭 지킬 필요는 없으나 Phase 0(감사)을 먼저 하면
> Phase 3·4 착수 근거가 확실해진다.

## 모델 전환 안내 (중요)

**모델 변경은 사용자만 `/model` 명령으로 실행 가능합니다.** 각 Phase 착수 전, 아래 표의 권장
모델과 현재 설정이 다르면 먼저 사용자에게 전환을 요청하고 확인 후 진행할 것 — 안내 없이
진행하지 말 것(2026-07-12 세션에서 이 규칙을 건너뛴 전례 있음, 재발 방지).

| Phase | 권장 모델 | 근거 |
|---|---|---|
| PRD 문서 작성(완료) | Sonnet | 정형 문서화, 설계는 이미 확정 |
| Phase 0 인벤토리 감사 | **Fable/Opus** | 헤딩 분류 룰북 설계·표 유형 판별이 판단 집약적 |
| Phase 1 extended 뷰 | Sonnet | SQL 뷰+카탈로그 노출, 패턴 명확 |
| Phase 2 API 수집 | Sonnet | dart_extra/dart_capital 기존 패턴 복제 |
| Phase 3 매출 파서 | **Fable/Opus** | 이질적 표 파싱 — B4 이력상 트리아지 반복 多 |
| Phase 4 비용성격 파서 | **Fable/Opus** | 표준화 파이프라인(재표준화→분기→달력) 접점, 회귀 위험 |
| Phase 5 차트빌더 | Sonnet | UI 증분, 기존 컴포넌트 재사용 |

(Pro 요금제 쿼터 관리 원칙: 판단 집약 Phase만 상위 모델, 나머지는 Sonnet으로 절약.)

---

## Phase 0 — 전수 인벤토리 감사 ☑ 완료 (2026-07-12) (PRD 11, 모델: Opus)
- ☑ `scripts/audit_table_inventory.py --pass1`: 미매핑 acode 상위빈도 + 미승격 캐노니컬 51종
  행수·corp×fy 커버율(동적 산출) + 부가테이블 커버리지 SQL
- ☑ `RULEBOOK`(ItemType 49종, section/status/source/keywords) — 단일원소 튜플 버그 수정,
  기간/순번마커 정제 필터(_is_substantive), 근접미스 보강(공백무시 매칭+MD&A/내부회계관리/
  매출채권 주석 등 3종 추가)
- ☑ `scripts/audit_table_inventory.py --pass2 --all --shard a/n --merge`: 전 활성 보통주
  2,551사 전수 스캔(층화표본 대신 4-way 병렬 샤딩, verify_corp_sequential.py 컨벤션과 동일
  `i%n==a`) — 읽기 전용, expand_table_grid/_looks_numeric/_is_clean_number 재사용
- ☑ `docs/data_inventory_matrix.md` 산출 — 항목|절|최적소스|상태|전수출현 매트릭스(2,551사 기준)
- **검증**: ☑ 10사 인라인 예비검증(오분류 0) → 4샤드 전수 실행(2,551사·파일6,452·표1,461,448)
  → 병합 산술 정합 확인(파일수·표수 4샤드 합산=병합값) · ☑ 49개 룰북 항목 전수에서 전부 등장
  (항목종류 포화) · ☑ 미분류 34.7% 상위 60헤딩 육안검토 — 신규 카테고리 0건(전부 기존버킷
  하위상세/보일러플레이트) · ☑ Phase 1/4 payoff 사전확증(미승격 51종 3만 corp×fy, 급여95K·
  D&A99K acode; 본문 "비용의 성격별 분류" 자체도 2,331사(91%) 등장)
- **사용자 실행**: ☑ 전수 스캔 완료(4-way 샤드 병렬+병합) · ☐ (선택, 미실행) 189K 전수
  제목-레벨 정규식 스캔

## Phase 1 — extended_financials 뷰 + 차트빌더 노출 ☑ 완료 (2026-07-12, 커밋 540cf28) (PRD 12, 모델: Sonnet)
- ☑ `collector/db.py` 마이그레이션 `2026_07_extended_financials_view`(멱등 CREATE OR REPLACE VIEW)
- ☑ `app/registry/extended.py`: EXTENDED_CATALOG **94종**(DB 실측 기준, 당초 추정 51종보다 확대 —
  concept_map 뿐 아니라 account_mapper Track B 어휘까지 포함됨. 한글라벨+UnitType, eps=원/주)
- ☑ `app/data/extended.py:load_extended_all` (+ std_v2 조인으로 period_end 확보)
- ☑ `app/compute/sources.py:fetch_ext_frame`(build_metric_frame 동일 tidy 스키마, 분기 그레인 가드)
- ☑ `app/cache.py:extended_series` 캐시
- ☑ `app/views/chart_builder_page.py`: 카테고리 필터 셀렉트(위젯안전) + 레지스트리·확장 통합
  지표선택. 파생연산(A/B)은 레지스트리 전용 유지(확장 파생은 Phase 5)
- ☑ `scripts/dq_assertions.py`: `extended_financials_n_facts_outlier` WARN 어서션
- **검증**: ☑ 삼성전자 실데이터 대조(interest_paid 전연도 정상, cash/total_assets 등 항등식
  일치) · ☑ EPS 원단위 정확 표시(4,950원, 억원 오스케일 없음) · ☑ 분기 그레인 가드 빈프레임 확인
  · ☑ AppTest 3단계(기본→확장추가→카테고리전환) 예외 0 · ☑ 회귀 57 tests pass ·
  ☑ dq_assertions 신규 어서션 SQL 무오류(ERROR 0, n_facts 위반 149,708건은 WARN 트리아지 대상으로 기록)
- **사용자 실행**: 없음(뷰 즉시 반영)
- **부수 발견·수정(Phase 1 범위 밖, 검증 중 발견)**: `controlling_ni` 총포괄손익 오염 버그 —
  별도 커밋 22d21f9. 상세는 memory `bug-controlling-ni-total-comprehensive.md`. 소급 재표준화
  1,733사 사용자 실행 중(진행상황: 위반 17,424→16,743, 계속 감소 중).

## Phase 2 — 주주환원 + 회사 일반현황 API 수집 ☐ (PRD 13, 권장 모델: Sonnet)
- ☐ `collector/models.py`: dividend_facts·treasury_activity·employee_stats·other_investments·
  exec_pay_summary·exec_pay_individual·periodic_api_progress(체크포인트) 7테이블
- ☐ `collector/dart_periodic.py`: 6 API 공통루프(fetch_periodic/sync_periodic), no-data 기록,
  연속 쿼터초과 감지 시 즉시중단+재개안내(key-bugs-fixed #6·#7 패턴)
- ☐ `scripts/collect_periodic_apis.py`(--api --years --resume --skip-existing)
- ☐ `scripts/collect_new.py` ⑤-3 비치명적 단계(신규기업 최신 fy 증분)
- ☐ `app/data/shareholder_return.py`: 배당성향(공시우선+재계산폴백)·총주주환원율 파생
- ☐ `app/data/company_profile.py`: 직원·타법인출자·임원보수 로더
- ☐ `app/views/company_page.py`: 신규 "💸 주주환원" 탭 + "👔 임원·지분" 탭 확장(직원/보수/출자)
- ☐ `app/registry/extended.py`+`sources.py`: dividend/employee kind 추가
- **검증**: ☐ 100사×FY2023 표본(~200콜) · ☐ 유명 배당주 5사 DPS DART 원문 대조 · ☐ 배당성향
  재계산 vs 공시값 허용오차(±2%p) · ☐ periodic_api_progress 멱등성(재실행 시 API 재호출 없음)
- **사용자 실행(야간 1커맨드/일)**: ☐ 1일차 alotMatter 2020+ · ☐ 2일차 tesstkAcqsDspsSttus ·
  ☐ 3일차 empSttus · ☐ 4일차 otrCprInvstmntSttus+hmvAuditAllSttus(+indvdlByPay) ·
  ☐ 5~7일차 2015~2019 확장

## Phase 3 — 부문·수출/내수 매출 파서 ☐ (PRD 14, 권장 모델: Fable/Opus)
- ☐ `fin2/extract/sales_section.py`: find_sales_tables+map_sales_table
  (expand_table_grid/find_biz_subsections 패턴 재사용, 신규 그리드 확장기 작성 금지)
- ☐ `collector/db.py`: `biz_metrics.channel VARCHAR(12)` 가산 마이그레이션(ADD COLUMN IF NOT EXISTS)
- ☐ `collector/models.py`: BizMetric.channel
- ☐ `biz_section.py` `_SALES_KW` 가드 라우팅(생산파서는 배제 유지, 매출파서는 캡처 — 이중캡처 방지)
- ☐ `scripts/collect_sales_metrics.py`(rcept 멱등)
- ☐ `scripts/collect_new.py` 배선(⑤-1 또는 ⑤-4)
- ☐ `app/data/biz.py:load_sales_composition` + company_page 매출구성 패널(부문 스택+수출비중)
- ☐ 차트빌더 biz kind 확장(segment×channel 동적 discover)
- ☐ `fin2/tests/test_sales_section.py`
- **검증**: ☐ 삼성전자·S-Oil 프로토타입 · ☐ 20사 확대 스윕 · ☐ 부문합≈std_v2 revenue ±20% 단위가드
  · ☐ 100~300사 스윕 트리아지(중첩TABLE/매출생산혼동 등) · ☐ test_biz_section.py 전체 그린 유지
  (생산파서 회귀 0)
- **사용자 실행**: ☐ 전수 백필(로컬 파일, 쿼터 무관, 수 시간)

## Phase 4 — 비용의 성격별 주석 파서 + EBITDA 상승 ☐ (PRD 15, 권장 모델: Fable/Opus)
- ☐ `fin2/extract/expense_nature.py`(rd_note.py 모델): note.employee_benefits/
  raw_materials_used/depreciation/amortization/da_total 방출
- ☐ `collector/expense_nature_sync.py`(cf_da_sync.py 클론): depreciation IS NULL 대상 →
  추출→재표준화→이산→달력 순서 준수
- ☐ `scripts/collect_new.py` ④-2 확장 배선
- ☐ **Phase 1 뷰 재확인**: extended_financials 가 note.* canonical 을 노출하도록 WHERE 절 보강
  (현재 bs./is./cf. 만 매칭 — note.* 분기 추가 필요)
- ☐ `app/registry/extended.py`: employee_benefits/raw_materials_used 항목 추가
- **검증**: ☐ golden set 전후 da_total/ebitda NULL율 diff 측정 · ☐ da/매출 [0.3%,60%] 가드 재사용
  · ☐ Gate B fail 카운트 무변화(note.*는 non-face) · ☐ 100사 스윕 → EBITDA 커버리지 이동 리포트
- **사용자 실행**: ☐ 전수 백필+재표준화 스윕(로컬 파일, 장시간, 순서 필수)

## Phase 5 — 차트빌더 고급 기능 ☐ (PRD 16, 권장 모델: Sonnet)
- ☐ `app/compute/derived.py`: yoy(%) 연산, ttm(분기 롤링4합) 연산 + validate 가드
- ☐ `app/views/chart_builder_page.py`: 밸류에이션 시계열 섹션(cache.valuation_series 재사용,
  독립 시간축 렌더)
- ☐ 다기업 비교 모드: 2~4사 multiselect + tidy frame corp_code 컬럼 + chart_panel color=corp 변형
  (단일회사 경로 무회귀 유지)
- ☐ `app/registry/units.py`: 원/억원/조원 스케일 토글(표시 레이어만)
- ☐ `app/data/presets.py`: 신규 op 포함 스키마 검증(구 프리셋 하위호환)
- **검증**: ☐ yoy/ttm 단위테스트(삼성전자 등 오라클 수기대조) · ☐ AppTest 무예외(다기업 비교+
  extended+yoy 조합) · ☐ 구버전 프리셋 로드 무에러

---

## Phase 완료 후 공통 작업
- ☐ 각 Phase 완료 시 `docs/data_inventory_matrix.md` 해당 항목 상태를 `collected` 로 갱신
- ☐ 커밋 메시지에 Phase 번호 명시(예: `feat(phase2): 배당·자사주 API 수집기`)
- ☐ 장시간 사용자 실행 잡은 에이전트 백그라운드로 절대 넘기지 않음(기존 운영교훈 준수)
