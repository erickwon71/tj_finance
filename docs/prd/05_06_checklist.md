# 진행 체크리스트 — 시각화(PRD 05) + 스크리너(PRD 06)

> 마스터 계획 `docs/plans/curried-doodling-metcalfe.md`. 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료.
> 각 Phase 는 검증 통과 후 다음으로. 동일 엔진 재사용이므로 `run.py` CLI 가 수치 oracle.

## Phase 0 — 스캐폴드 ☑ 완료 (2026-06-27)
- ☑ `.venv_tj_finance` 에 `streamlit==1.50.0` 설치 + `requirements.txt` 추가(plotly 6.7.0·pandas)
- ☑ `app/` 패키지 골격 생성(main·state·cache·format + registry/data/compute/views/components)
- ☑ `app/main.py` `st.navigation`(company/screener, url_path 지정) + 글로벌 사이드바(기업검색·연결/별도·분기/연간 = `st.radio`)
- ☑ `app/data/corp.py:search_corps(q)`·`resolve_corp(corp_code)`·`table_counts()`
- ☑ DB 연결 스모크(`get_session` 동작, 사이드바 'DB 상태' 익스팬더)
- **검증**: ☑ AppTest 헤드리스 부팅 무예외 · ☑ 실서버 health=ok(3s) · ☑ `search_corps("삼성전자")`→005930 · ☑ 토글 state 반영(separate/quarter) · ☑ 선택→focus_corp→식별헤더 렌더
- ⚠ 비차단: 사용자 전역 `~/.streamlit/config.toml` 에 리터럴 `\n` 오타 → 파싱 경고(앱 동작엔 무영향). 사용자 확인 후 수정 가능.

## Phase 1 — Company MVP (연간) ☑ 완료 (2026-06-27)
- ☑ `app/data/series.py:load_annual_series`(+폴백) / `load_price_series` / `price_date_bounds`
- ☑ `app/views/company_page.py` 헤더(기업명+종목코드+corp_code+시장) + DQ 배너 + 연결/별도 폴백 안내
- ☑ 연간 재무표(IS/BS/CF 억원) — `load_standard_financials` FY 재사용, std_v2 라인 = `run.py analyze` 동일
- ☑ 밸류에이션 탭(최신 FY) — `compute_multiples` 재사용(PER/PBR/PSR/PCR/EV·EV배수 + EPS/BPS 파생)
- ☑ `app/views/chart_panel.py` 주가차트(종가/캔들 + 거래량) + **log 토글** + 기간선택 + 장기 주간 다운샘플
- ☑ `app/components/export.py:to_csv_bytes`(utf-8-sig BOM) + 통합 CSV 다운로드(raw 원)
- ☑ `app/cache.py` st.cache_data 래퍼(annual_series·price_series·price_bounds·company_multiples)
- ☑ `width=` API 로 전환(use_container_width deprecation 제거; plotly_chart 는 use_container_width 유지)
- **검증**: ☑ 삼성전자 매출 3,336,059억 == 오라클 333.6조 · 순이익 452,068억==45.2조(3기업 일치) · ☑ AppTest 무예외(4 df·4 탭) · ☑ log 토글·basis 전환 동작 · ☑ CSV=raw 원(333,605,938,000,000)·BOM · ☑ 실서버 health=ok(2s) 에러 0

### Phase 1.5 — 분기 시계열 + 주가·재무 결합 (추가요청) ☑ 완료 (2026-06-27)
- ☑ `app/data/series.py:load_quarter_series`(+폴백) — `calendar_financials` 달력분기 CQ1~CQ4 이산
- ☑ `app/cache.py:quarter_series` 캐시 래퍼
- ☑ company_page 분기/연간 토글 반영 — 재무표 컬럼이 분기('2026 CQ1' …)/연간 전환, DQ 배너·CSV grain 인식
- ☑ object dtype 결측 안전(표시용 to_numeric 강제 환산, CSV 는 raw 정수 보존)
- ☑ `chart_panel.render_price_financial_combined` — 주가(라인,좌축 원,log) + 재무항목(막대,우축 억원) 이중축
- ☑ company_page '📊 주가·재무 결합' 탭 — 재무항목 **multiselect 최대 3개**·log 토글·막대 폭 230/55일
  - ※ 기간(연간/분기)은 **좌측 사이드바 단일 컨트롤**이 결합 탭까지 일괄 구동(중복 토글 제거). 검증: 사이드바 annual→15막대 / quarter→40막대 일치
  - ※ **재무 1개=막대, 2~3개=라인+마커**(겹침 방지). 검증: 1개→bar 1·price line 1 / 3개→scatter 4(price+3) / multiselect max_selections=3 / AppTest 무예외
### 데이터 진단 (삼성 2026 Q1) — A: 원본 보고서 대조 완료 (2026-06-27)
- 결합/분기 표의 2026 막대 = **2026년 1분기(1~3월) 이산 분기**(period_end 2026-03-31), 전체연도 아님.
- **원본 공시 보고서(raw XML, rcept 20260515002181) 직접 대조**: 보고서 본문 연결손익계산서가
  `영업이익 57,232,797 백만원`·`매출 133,873,444 백만원`을 그대로 기재(ADECIMAL=-6 백만원). **영업부문
  주석 segment note 합산도 57.2조로 내부 일치**. 전기비교(2025 Q1)는 `영업이익 6,685,272`·`매출
  79,140,503` 백만원 = 현실값과 일치.
- **Gate B line audit: n_lines=317 · value_diff=0 · status=pass** → **DB = 보고서 원문 100% 일치**.
  ⟹ 추출·표시단위·컬럼 **오류 없음**. 파이프라인 수정 불필요(**A 결론**).
- 단, 2026 현재기간 값은 실제 삼성(현실 Q1 영업이익 ~6.7조)과 동떨어짐. **SK하이닉스 2026 Q1 도 동일
  inflation(영업이익률 72%)** → **이 환경의 2026 현재기간 데이터가 합성/시드 테스트값**으로 강하게 추정.
  소스(보고서) 측 이슈이며 우리 통제 밖. [[viz-app-status]] 참조.

### Plan B — 이상치 가드 UI ☑ 완료 (2026-06-27)
- ☑ `app/compute/checks.py:financial_anomalies(series, grain)` — ① 영업이익률 >100%(불가)·>60%(의심)
  ② 급증: **전년 동기(YoY) 4배↑ 그리고 직전 분기(QoQ) 1.8배↑ 동시**(분기)/전년 4배↑(연간). 메시지에
  전년 동기·직전 분기 값과 배수 병기. 데이터 미수정, 표시용 경고만.
- ☑ company_page 상단 '⚠ 이상치 점검' expander(DB=보고서 일치 안내 포함)
- **검증**: ☑ 삼성 2026 CQ1 OP(전년 8.6배·직전 2.9배)·NI 포착 2건 · ☑ SK 2026 CQ1 3건 · ☑ 삼성SDS·현대차 0건
  · ☑ 경기민감 회복 오탐 배제(삼성 2024 CQ2 YoY 6배지만 QoQ 1.5배→미플래그, SK 적자기저 회복 미플래그)
  · ☑ 연간 0건 · ☑ AppTest quarter 2건 · ☑ 실서버 0 에러
- **검증**: ☑ AppTest annual·quarter 무예외(4 df·4 탭) · ☑ 분기 컬럼 '2026 CQ1'… 정상 · ☑ 분기 CSV raw 정수 · ☑ 결합차트 metric·log 토글 동작 · ☑ 실서버 health=ok·deprecation 0
- ⚠ **데이터 주의(UI 무관)**: 일부 최신 분기(예: 삼성 2026 CQ1=133.9조)가 비정상 과대 — Layer 2 이산환산의 최신보고서 처리 이슈로 추정. UI 가 아닌 `calendar_financials` 데이터 레이어 후속 점검 대상.

## Phase 2 — 레지스트리 + 차트패널 ☑ 완료 (2026-06-27)
- ☑ `app/registry/units.py`(UnitType·Category·Grain + display_value/format_value)
- ☑ `app/registry/metrics.py`(MetricSpec + METRIC_REGISTRY 49종: 재무24·수익성9·성장성4·안정성12) + metrics_by_category
- ☑ `app/compute/resolver.py:build_metric_frame`(기간당 compute_ratios 1회·tidy DataFrame)
- ☑ `app/data/series.py:load_quarter_series`(calendar discrete) — Phase 1.5 기구현
- ☑ `app/views/metric_panel.py` 카테고리 멀티셀렉트 + 표/그래프 토글 + CSV(원시값) → company_page '📊 지표' 탭
- ☑ `chart_panel.render_metric_chart` 단위별 이중축(금액 억원=좌축 / 비율·배수·일수=우축)
- **검증**: ☑ revenue/op_margin(13.1%==오라클)/ROE 리졸버==엔진 정확일치 · ☑ ΣCQ2024==FY2024 revenue(ratio 1.0000) · ☑ AppTest 5탭·50옵션·표/그래프/멀티셀렉트(금액+%+x 혼합) 무예외(연간/분기) · ☑ 실서버 health=ok 0에러

## Phase 3 — 스크리너 단일패스 ☑ 완료 (2026-06-27)
- ☑ `app/data/screen_window.py:load_population(fiscal_year)` — `screen()` 를 필터無·한도無로
  호출해 전수 모집단 1회 로드(행 스키마 == `screen()`). rn 캡 확장(윈도우)은 Phase 4.
- ☑ `app/cache.py:screen_population` 캐시 래퍼(ttl 600, spinner)
- ☑ `app/views/screener_page.py` 필터 빌더(FIELDS 22종 + `_parse_condition`/`_check` 재사용) +
  시장/정렬/방향/한도 컨트롤 + 메모리 필터(`_apply` = screen() 메모리단계와 동일) + 결과 CSV(raw 원)
- ☑ 결과표(기업명/종목코드/corp_code/시장/FY/시총 + ROE·ROIC·PER·PBR·EV/EBITDA·영업이익률·매출성장·부채비율·F)
- **검증**: ☑ 4 케이스 결과·정렬 == CLI `screen()` 정확일치(`scripts/verify_screener_phase3.py` ALL PASS,
  `--roe ">15%" --per "<12"` 30건 포함) · ☑ AppTest 부팅+결과렌더 무예외(dataframe=1) · ☑ 실서버 health=ok(1s) 에러 0

## Phase 4 — 윈도우집계 + 퀀트 + 분할뷰 ☑ 완료 (2026-06-27)
- ☑ `app/data/screen_window.py:load_screening_window(n_years≤10, fiscal_year, statement_type)`
  — `_load_screening_data` rn 캡을 `rn≤n_years+1`(오래된 기간 ratio prev용 +1)로 확장, corp별 series 그룹화
- ☑ `app/compute/screen_eval.py` — `aggregate(average/CAGR/YoY)`(=`_cagr`/`_growth_rate`) +
  `build_base_frame`(corp당 1행, compute_ratios 기간당 1회) + 최신 멀티플(per/pbr/ev_ebitda/psr/pcr) +
  `run_quant_passes(≤3)`(filter→sort→limit, `_check` 재사용) + 단위/임계 헬퍼(`effective_unit`·`make_threshold`)
  - ※ CAGR 부호반전(end≤0) 시 복소수 차단 → None
- ☑ `app/cache.py:screen_base_frame`((n,method,stmt,fy)별 1회 캐시)
- ☑ `app/views/screener_page.py` 분할 레이아웃(`st.columns([5,7])`) — 좌: 윈도우(기간/방법/시장) +
  퀀트 ≤3패스(폼 밖, 멀티셀렉트→조건 위젯 즉시) + 결과표 `on_select`→`focus_corp` + CSV(raw) · 우: `company_page.render()` 재사용
- **검증**: ☑ `scripts/verify_screener_phase4.py` — avg/CAGR/YoY 삼성 revenue·roe 수기 대조 일치 ·
  퀀트 3패스 단조축소(2259→200→100→30) · ☑ AppTest 부팅·실행·선택→우측패널 무예외(좌측 결과 유지=비파괴) ·
  ☑ 실서버 health=ok(1s) 에러 0

## Phase 5 — 대가 지표 + 폴리시 ☑ 완료 (2026-06-27)
- ☑ `app/compute/master_metrics.py:compute_master` — Graham(Graham Number·NCAV/주가·PER×PBR·EPS흑자연수) ·
  Greenblatt(EY=EBIT/EV·ROC=EBIT/(순운전자본+순고정자산)) · Lynch(PEG) · Fisher(R&D/매출·매출총이익률변화).
  Buffett/Piotroski 는 `buffett_engine.compute_buffett` 재사용.
- ☑ `screen_eval`: 대가 점값 필드(MASTER_FIELDS) base frame 통합 + `add_magic_rank`(EY랭크+ROC랭크→재랭크) +
  effective_unit/make_threshold 확장. 스크리너 필터/정렬에 EY·ROC·마법공식랭크·PEG·Graham상승여력·NCAV·R&D 추가.
- ☑ `app/views/company_page.py` '🏆 대가지표' 탭(Buffett/Graham/Greenblatt·Lynch·Fisher 3열)
- ☑ `app/views/compare_page.py`(comparator.compare 재사용, 항목×기업 표) + nav 등록
- ☑ `app/views/valuation_page.py`(dcf_engine.run_dcf + dividend_engine.analyze_dividend, focus_corp) + nav 등록
- ☑ `cache.py`: compare_companies·dcf_cached·dividend_cached 캐시 래퍼
- **검증**: ☑ `scripts/verify_screener_phase5.py` — 삼성 Graham Number·EY·ROC 수기 대조 일치 ·
  마법공식 종합랭크 산식 일치(유효 2062사, 1위 검출) · ☑ AppTest 대가탭·밸류에이션(metric8·DCF표·배당표)·비교 무예외 ·
  ☑ 실서버 health=ok(1s) 4페이지 에러 0
  - ※ DCF 베타계산은 `pkg_resources` 부재로 β=1.0 폴백(엔진 기존 동작, `run.py dcf` 동일)

---

## 지표 등록 체크리스트 (카탈로그)
> 등록 = `METRIC_REGISTRY` 에 `MetricSpec` 추가. source 가 기존 엔진이면 코드 0.

- ☐ FINANCIALS (28종, source=column)
- ☐ PROFIT (10종, source=ratios)
- ☐ GROWTH (8종, source=ratios/window)
- ☐ STABILITY (13종, source=ratios)
- ☐ PRICE (6종, source=price, log 지원)
- ☐ MULTIPLE (9종, source=valuation)
- ☐ DIVIDEND (6종, source=custom/dividend_engine)
- ☐ MASTER · Buffett (10종, source=buffett — 구현됨)
- ☐ MASTER · Graham (8종, source=custom)
- ☐ MASTER · Greenblatt 마법공식 (3종, source=custom)
- ☐ MASTER · Lynch (4종, source=custom)
- ☐ MASTER · Piotroski (F-Score + 9플래그, source=buffett — 구현됨)
- ☐ MASTER · Fisher (3종, source=ratios/custom)

## 전체 E2E (DoD 종합)
- ☐ 앱 기동 + 기업검색
- ☐ Company 수치 == CLI (3기업)
- ☐ 분기 CQ1–4 합 ≈ FY
- ☐ 스크리너 == CLI
- ☐ 윈도우 CAGR/avg 수기 대조 · 퀀트 3패스 · 행클릭 비파괴
- ☐ CSV export(raw 원 보존)
- ☐ 주가 log 토글
