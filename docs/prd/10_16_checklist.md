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

## Phase 2 — 주주환원 + 회사 일반현황 API 수집 ☑ 완료 (2026-07-12) (PRD 13, 모델: Sonnet)
- ☑ `collector/models.py`: dividend_facts·treasury_activity·employee_stats·other_investments·
  exec_pay_summary·exec_pay_individual·periodic_api_progress(체크포인트) 7테이블
- ☑ `collector/dart_client.py`: 6 API 신규 메서드(013/020 을 기존 `_api_get_json`/`DartApiError`
  로 정확히 구분 — dart_extra.py 의 ad-hoc `_get()` 재구현 금지 원칙 준수, key-bugs-fixed #6)
- ☑ `collector/dart_periodic.py`: 6 API 공통루프(fetch_periodic/sync_periodic), no-data 기록,
  '020' 은 그대로 raise 해 호출측 circuit breaker 로 전파(key-bugs-fixed #6·#7 패턴)
- ☑ `scripts/collect_periodic_apis.py`(--api --years --corps --sample --skip-existing, 연속
  '020' 5회 감지 시 즉시중단+재개안내)
- ☑ `scripts/collect_new.py` ⑤-3 비치명적 단계(신규기업 최신 fy 증분)
- ☑ `app/data/shareholder_return.py`: 배당성향(공시우선+재계산폴백)·총주주환원율 파생
  (자사주 순취득금액은 extended_financials 의 cf.treasury_stock_purchase, CF 부호 관례상
  음수→abs() 변환 필요했음 — 발견·수정)
- ☑ `app/data/company_profile.py`: 직원·타법인출자·임원보수 로더
- ☑ `app/views/company_page.py`: 신규 "💸 주주환원" 탭 + "👔 임원·지분" 탭 확장(임원보수/직원/
  타법인출자 3패널 추가)
- ☑ `app/registry/dividend.py`(신규)+`app/compute/sources.py::fetch_dividend_frame`+
  `chart_builder_page.py`: 배당지표(DPS/배당성향/배당수익률/배당총액) 차트빌더 노출.
  **employee kind 는 미구현**(부문×성별 원자료가 차트빌더의 corp+기간당 1값 tidy 스키마로
  자연스럽게 축약 안 됨 — 별도 설계 필요, 후속 검토 항목으로 이월)
- **검증**: ☑ 100사×FY2023 실행(600콜, ok=498/no_data=102/error=0 — no_data 는 17개 corp 전
  API 일관 결측, corp 조회 결과 FY2023 사업보고서 자체가 없는 기업들로 확인·정상) · ☑ 배당주
  6사(삼성전자·SK텔레콤·POSCO홀딩스·현대자동차·케이티앤지·기아) DPS+배당성향 DART 원문과
  완전일치 · ☑ 배당성향 재계산 vs 공시값 허용오차(±2%p): 45건 중 37건(82%) 통과, 8건 초과분은
  대부분 당기순이익이 0에 근접한 기업(퍼센트 분모 왜소화로 근소한 절대차도 %포인트로 증폭)이고
  raw JSONB 원문과 대조 시 우리 파싱은 DART 공시값을 정확히 그대로 반영 — 공시 자체의
  이상수치(회사 제출 데이터 오류 가능성)로 판단, PRD 결정대로 공시값 우선 유지(재계산으로
  덮어쓰지 않음) · ☑ periodic_api_progress 멱등성(동일 스코프 재실행 시 622건 전부 스킵,
  API 재호출 0) · ☑ AppTest 무예외(주주환원 탭·임원·지분 확장 탭, 데이터有/無 기업 모두)
- **사용자 실행(야간 1커맨드/일)**: ☐ 1일차 alotMatter 2020+ · ☐ 2일차 tesstkAcqsDspsSttus ·
  ☐ 3일차 empSttus · ☐ 4일차 otrCprInvstmntSttus+hmvAuditAllSttus(+indvdlByPay) ·
  ☐ 5~7일차 2015~2019 확장 (전수 백필, 코드 완료기준엔 불필요 — 재개가능 체크포인트 확인됨)

## Phase 3 — 부문·수출/내수 매출 파서 ☑ 완료 (2026-07-12) (PRD 14, 모델: Opus)
- ☑ `fin2/extract/sales_section.py`: find_sales_subsections+map_sales_table
  (expand_table_grid/find_biz_subsections 패턴·수치파서·기간해석 재사용, 신규 그리드 확장기 無).
  채널 3레이아웃 대응(채널-차원열/채널-헤더/채널없음→합계), 비율(%)열 제외, 수주표·재무요약표 가드,
  단위 3단계 폴백(narrative 엄격→관대(백만원,%)→표 셀 배너 흡수)
- ☑ `collector/db.py`: `biz_metrics.channel VARCHAR(12)` 마이그레이션(2026_07_biz_metrics_channel)
- ☑ `collector/models.py`: BizMetric.channel + metric='sales'
- ☑ `biz_section.py` `_SALES_KW` 가드 무변경(생산 배제 유지) + `parse_biz_metrics` 에 sales 통합
  (table_ord 이어붙임, 이중캡처 방지는 창 절단이 보장 — grid dedup 불필요)
- ☑ `scripts/collect_sales_metrics.py`(rcept 멱등, --skip-existing 은 metric='sales' 존재로 판정)
- ☑ `scripts/collect_new.py` ⑤-1 배선(sales 가 parse_biz_metrics 에 통합돼 자동 수집, 로그 갱신)
- ☑ `app/data/biz.py:load_sales_composition`(부문 구성표·수출비중표 각각 단일 table 선택, subtotal
  segment+item 양축 제외) + `app/cache.py:sales_composition` + company_page "🏭 생산·매출" 탭
  매출 패널(부문 스택 막대 + 내수/수출 스택 + 수출비중 라인)
- ☐ (이월) 차트빌더 biz kind — biz_metrics 의 corp별 동적 segment×channel 키가 차트빌더의 정적
  카탈로그(1 corp·기간당 1값 tidy) 모델과 구조적으로 안 맞음(Phase 2 employee kind 이월과 동일
  사유). PRD 14 §7 완료기준엔 미포함. company_page 패널이 시각화 수요 충족. 별도 설계 필요.
- ☑ `fin2/tests/test_sales_section.py`(7종, 실측 4사)
- **검증**: ☑ 삼성전자·S-Oil 프로토타입(원문 대조 정확) · ☑ 40사 스윕(내수/수출/합계 채널 정확) ·
  ☑ 부문합≈std_v2 revenue ±20% 단위가드(40사: within20%=14/within2x=4, 개선 후) · ☑ 120사 스윕
  트리아지(**파서 크래시 0**; 괴리는 전부 설명가능 — 단위라벨이 다른 셀·다중표 재분해·소계변형·
  로더 표선택 미스로 인한 것이지 파서 값버그 아님. subtotal item축 누락 버그 1건 발견·수정으로
  2~4.5x 오계상 대부분 해소) · ☑ test_biz_section.py 18종 전체 그린(생산파서 회귀 0) ·
  ☑ 핵심 57 tests·AppTest 무예외
- **알려진 한계(값버그 아님, 이월 개선)**: 로더의 "부문 구성표 단일 선택" 휴리스틱이 이질 레이아웃
  일부(주 매출표 대신 소규모 하위표 선택)에서 under-capture. 파서는 무손실 저장이라 데이터는 온전.
- **사용자 실행**: ☐ 전수 백필(로컬 파일, 쿼터 무관, 수 시간): `python scripts/collect_sales_metrics.py
  --latest --skip-existing`

## Phase 4 — 비용의 성격별 주석 파서 + EBITDA 상승 ☑ 완료 (2026-07-12) (PRD 15, 모델: Opus)
- ☑ `fin2/extract/expense_nature.py`(rd_note/notes 모델): 헤딩('비용의 성격별 분류 (연결/별도)')
  → 데이터 표(iXBRL 2x2 배너 다음 nested '공시금액' 표) → note.employee_benefits/raw_materials_used/
  depreciation/amortization/da_total 방출. **감가상각/무형상각 분리(삼성·현대차) vs 결합(LG·S-Oil
  '감가상각비, 무형자산상각비'→da_total 직접) 두 형태 대응**. 라벨열 가변(삼성 그룹열), 단위감지+
  매출앵커 보정, 총계/설명행 스킵. acontext='note:{basis}:col0'(cf_da 계열과 동일—타겟팅이 중복 방지)
- ☑ `collector/expense_nature_sync.py`(cf_da_sync.py 클론): **depreciation IS NULL AND da_total IS
  NULL** 대상(cf_da 다음, 이중계상 방지), statement='IS' 승자 rcept 파싱 → store_facts →
  standardize→quarterly→calendar 순서 준수
- ☑ `scripts/collect_new.py` ④-2 확장(cf_da 다음 expense_nature 비치명 배선)
- ☑ **extended_financials 뷰 보강**: 마이그레이션 `2026_07_extended_financials_view_note` —
  `OR (canonical_account LIKE 'note.%' AND ss.statement='IS')` 분기 추가(note.* 노출)
- ☑ `app/registry/extended.py`: note.employee_benefits/raw_materials_used 항목 추가(statement='NOTE')
- ☑ `fin2/tests/test_expense_nature.py`(5종, 실측 4사)
- **검증**: ☑ **30사 표본 da_total 커버리지 0/60→58/60(96.7%)** (2024+ 연결; 전체 2024+ 모집단은
  현재 50/4229=1.2%로 Track A 절벽, 타겟 2,117사) · ☑ da/매출 [0.3%,60%] 가드(표본 0건 위반) ·
  ☑ **EBITDA=영업이익+da_total 항등식 58/58 일치(0 불일치)** · ☑ Gate B 무변화(5사 재감사
  gb_fail_a=0·line_value_diff=0, note.*는 non-face) · ☑ note.* 뷰 노출+차트빌더 조회 확인 ·
  ☑ 회귀 전체 그린(biz 18·sales 7·expense 5·core 57)
- **미충전 트리아지**: 표본 2/60(강원에너지·국일제지 각 2024년 1건)—개별 보고서 파싱 미스(각 사
  2025/2026 은 정상 충전). 시스템적 버그 아님.
- **사용자 실행**: ☐ 전수 백필+재표준화(로컬, 장시간 ~2.5h/2100사, 순서 필수, cf_da 다음):
  `python -c "from collector.expense_nature_sync import sync_expense_nature; sync_expense_nature(year_min=2024)"`
  (또는 collect_new 파이프라인이 신규분 자동 처리)

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
