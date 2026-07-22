# 시각화 + 스크리너 앱 — 구현 계획 / PRD / 체크리스트

## Context (왜 이 작업인가)

데이터 레이어(Track A)는 완전히 종결되었다: 재무(`std_v2`, 1997–2026) · 캘린더화 분기(`calendar_financials`, CQ1–4/CY) · 일별 주가/시총(`stock_prices`, 1990–2026, 11.2M행) · 일별 멀티플(`valuation_daily`). Gate B 보고서↔DB 100% 일치 검증 완료.

원래 개발 목표(블룸버그 터미널형 재무 시각화)는 아직 앱이 없다. `streamlit`만 미설치이고 `analyzer/`에 재사용 가능한 엔진이 이미 풍부하다(ratio/buffett/dcf/dividend/valuation/screener/comparator + 포맷터). **새 코드를 거의 만들지 않고** 기존 엔진을 import 하여 Streamlit UI로 노출하는 것이 핵심 전략.

이 계획은 ① 시각화 앱 ② 스크리너 ③ 투자 대가별 지표 카탈로그를 설계하고, 승인 후 **PRD 문서(`docs/prd/05_visualization.md`, `06_screener.md`)와 진행 체크리스트(`docs/prd/05_06_checklist.md`)**를 작성한다.

### 확정된 결정 (사용자)
- **UI 프레임워크: Streamlit + Plotly** (Plotly는 설치됨; log 스케일 무료)
- **Table export: CSV만** (의존성 0)
- **대가 지표: Warren Buffett · Benjamin Graham · Joel Greenblatt(마법공식) · Lynch·Piotroski·Fisher 전부 포함**
- 금액 단위 억원, 비율 %, 기간 분기/연간 선택, 연결/별도 토글, 기업명+코드+종목코드 동시표시, 주가 log 스케일

---

## 1. 지표 카탈로그 (Metric Catalog) — 전문 재무서비스 표준 + 대가별

각 지표는 `MetricSpec`(id, 이름, 카테고리, 단위, source, 계산위치, 지원 grain)로 레지스트리에 등록. **대부분 이미 엔진에 존재** → 등록만으로 추가됨. `source` = `column`(DB 컬럼) / `ratios`(ratio_engine) / `buffett` / `valuation` / `price` / `custom`.

### 1.1 재무데이터 (FINANCIALS, 억원) — `source=column`, std_v2/calendar 컬럼
매출(revenue) · 매출원가(cogs) · 매출총이익(gross_profit) · 판관비(sga) · R&D(rd_expense) · 영업이익(operating_income) · 세전이익(ebt) · 당기순이익(net_income) · 지배순이익(controlling_ni) · 자산총계(total_assets) · 부채총계(total_liabilities) · 자본총계(total_equity) · 지배지분(controlling_equity) · 현금(cash) · 차입금(short_term_debt+long_term_debt) · 순차입금(net_debt) · 재고(inventory) · 매출채권(receivables) · 영업CF(cfo) · 투자CF(cfi) · 재무CF(cff) · CAPEX(capex) · 감가상각(depreciation/da_total) · EBITDA · FCF · 배당지급(dividends_paid) · 상장주식수(shares_out)

### 1.2 수익성 (PROFIT, %) — `source=ratios` (ratio_engine.compute_ratios)
매출총이익률(gross_margin) · 영업이익률(op_margin) · 순이익률(net_margin) · EBITDA마진(ebitda_margin) · ROE · ROA · ROIC · NOPAT · 자산회전율(asset_turnover) · 유효세율(effective_tax_rate)

### 1.3 성장성 (GROWTH, %) — `source=ratios` + 윈도우 CAGR
매출성장률(revenue_growth) · 영업이익성장률(op_income_growth) · 순이익성장률(net_income_growth) · 자산성장률(asset_growth) · (윈도우) 매출 CAGR · EPS CAGR · DPS CAGR · 자본 CAGR

### 1.4 안정성 (STABILITY, %/x/days) — `source=ratios`
부채비율(debt_ratio) · 유동비율(current_ratio) · 이자보상배율(interest_coverage) · 순차입금/EBITDA(net_debt_ebitda) · CAPEX/매출(capex_to_revenue) · CAPEX/감가상각(capex_to_dep) · FCF/매출(fcf_to_revenue) · CFO/순이익(cfo_to_ni, 이익의 질) · 발생액비율(accrual_ratio) · DSO · DIO · DPO · CCC(현금전환주기)

### 1.5 가격 (PRICE, 원) — `source=price`, stock_prices
종가(close) · 시가/고가/저가 · 거래량(volume) · 시가총액(market_cap, 억원) · **주가 차트 log 스케일 지원**

### 1.6 멀티플 (MULTIPLE, x) — `source=valuation` (valuation_engine / valuation_daily)
PER · PBR · PSR · PCR · EV/EBITDA · EV/EBIT · EV/FCF · EPS(원) · BPS(원)

### 1.7 배당 (DIVIDEND) — `source=custom` (dividend_engine.analyze_dividend)
DPS(원) · 배당수익률(div_yield, %) · 배당성향(payout_ratio, %) · 연속배당연수 · DPS CAGR(3y/5y) · 평균배당수익률(3y)

### 1.8 대가별 지표 (MASTER) — 이름과 함께 선택
**Warren Buffett** (`source=buffett`, 구현됨): Owner's Earnings(억원) · 유지보수 CAPEX · FCF Quality(CFO/NI) · ROIC 5년평균/표준편차(일관성) · 발생액비율 · 배당성향 · 자사주매입수익률(buyback_yield) · 총주주수익률(total_shareholder_yield) · 유보이익ROE(retained_roe) · Piotroski F-Score(0–9)
**Benjamin Graham** (`source=custom`): Graham Number(√(22.5×EPS×BPS)) · PER×PBR(<22.5) · 유동비율(>2) · 무차입/저부채 · 연속배당 · NCAV(순유동자산가치)·NCAV/시총 · EPS 안정성(과거 적자 없음)
**Joel Greenblatt 마법공식** (`source=custom`): Earnings Yield(EBIT/EV) · Return on Capital(EBIT/투하자본) · 두 순위 합산 종합랭크 → 퀀트 정렬에 직결
**Peter Lynch** (`source=custom`): PEG(PER/이익성장률, <1) · 매출/이익 동반성장 · 부채 점검 · 배당
**Piotroski F-Score** (`source=buffett`, 구현됨): 9개 항목 합 + 개별 플래그
**Philip Fisher** (`source=ratios`/custom): R&D/매출 비중 · 영업이익률 추세 질적 평가 · 매출 지속성장

> 추가 지표는 `METRIC_REGISTRY`에 `MetricSpec` 한 줄 append로 확장(config-driven). 신규 수식만 `compute` 콜백 필요.

---

## 2. 아키텍처

### 2.1 신규 패키지 `app/` (analyzer·collector의 형제)
엔진을 **import만** 하고 재구현하지 않음. 진입점 `streamlit run app/main.py`.

```
app/
  main.py            # st.navigation, 글로벌 사이드바(기업검색·연결/별도·분기/연간)
  state.py           # session_state 키 상수 + 게터/세터
  cache.py           # 모든 DB 로더 st.cache_data 래퍼
  format.py          # table_view 포맷터 재export + pandas 벡터화 억원/% 변환
  registry/
    units.py         # UnitType / Category / Grain enum
    metrics.py       # MetricSpec dataclass + METRIC_REGISTRY (§1 카탈로그)
  data/              # 얇은 신규 DB 헬퍼 (아래 gap만)
    corp.py          # search_corps(q), resolve_corp(corp_code)
    series.py        # load_annual_series, load_quarter_series(discrete), load_price_series
    screen_window.py # load_screening_window(n_years<=10, fiscal_year)
    multiples.py     # load_valuation_series(stock_code,start,end) — 단일티커 valuation_daily
  compute/
    resolver.py      # build_metric_frame(corp, metric_ids, grain, stmt, years) -> tidy DataFrame
    screen_eval.py   # 윈도우 집계(avg/CAGR/YoY) + run_quant_passes(<=3)
  views/
    company_page.py  # 시각화 페이지(지표 멀티셀렉트, 그래프/표 토글, 주가 log)
    screener_page.py # 분할 레이아웃(좌:필터+결과 / 우:선택기업 시각화)
    chart_panel.py   # render_chart(plotly, log토글, 금액+비율 이중축)
    table_panel.py   # render_table + CSV export 버튼
    compare_page.py  # (후기) comparator.compare 래핑
    valuation_page.py# (후기) dcf_engine / dividend_engine 래핑
  components/
    selectors.py     # 지표 picker, grain, stmt 토글, 연도 윈도우 슬라이더
    export.py        # to_csv_bytes(df) -> st.download_button
```

### 2.2 재사용 엔진 (재구현 금지)
- `ratio_engine.compute_ratios(curr, prev)` · `load_standard_financials(corp, stmt, fp, years)` · 내부 `_cagr`/`_growth_rate`
- `buffett_engine.compute_buffett(sf_list, market_cap)`
- `valuation_engine.compute_multiples(sf, corp, ...)`
- `dividend_engine.analyze_dividend(corp, years, stmt)` · `dcf_engine.run_dcf(...)`
- `screener._parse_condition`/`_check`(필터 문법 동일) · `_load_screening_data`(확장 대상)
- `display/table_view._fmt_amount`/`_fmt_pct`/`_fmt_ratio`/`_period_label`
- DB: `collector/db.get_session()` + `text()` + `.mappings().fetchall()` (금액 raw 원)

### 2.3 기존 엔진 gap → 얇은 신규 헬퍼 (이것만 신규 코드)
| 요구 | 기존 한계 | 신규 헬퍼 |
|---|---|---|
| 스크리너 10년 윈도우 | `_load_screening_data`가 `rn<=2` 캡 | `load_screening_window(n,fy)` — 동일 쿼리 `rn<=:n`, corp별 series 그룹화 |
| 분기 **이산** 차트 | `load_standard_financials('ALL')`=YTD 누적 | `load_quarter_series()` — `calendar_financials WHERE is_discrete` (CQ1–4 이미 이산) |
| 윈도우 집계 | `_cagr`/`_growth_rate`는 내부 | `screen_eval.py`가 import해 series에 적용 |
| 지표 시계열 프레임 | 엔진은 스칼라/dataclass 반환 | `build_metric_frame()` → tidy `(period, metric, value, unit)` |
| 멀티플 시계열 | `valuation_daily` 단일티커만 빠름 | `load_valuation_series(stock_code,...)` |
| 주가 log 시계열 | 컬럼만 존재 | `load_price_series()`; log는 chart_panel `type="log"` |
| 기업명 검색 | 정확매칭만 | `search_corps(q)` ILIKE corp_name/stock_code |

### 2.4 핵심 동작 모델
- **resolver**: 기간별로 엔진 출력(ratios/buffett/multiples)을 **한 번만** 계산 후 각 MetricSpec이 지정한 위치에서 값 읽기 → 30개 지표 선택해도 기간당 1회 계산.
- **연결/별도 토글**: 모든 로더 `statement_type` 파라미터 + consolidated→separate 폴백(print_analysis 패턴).
- **스크리너 분할(비파괴)**: `screen_results`(캐시 DataFrame)는 좌측 고정 렌더, 행 선택 시 `focus_corp`만 갱신 → 우측에 `company_page` 패널 렌더. 좌측은 state에서 읽으므로 재실행돼도 결과 유지.
- **퀀트 다단계**: `quant_passes`(≤3 dict 리스트)를 캐시된 base universe에 순차 적용(filter→sort→head). 각 pass는 순수 pandas 변환.

### 2.5 페이지 구성
1. **Company(시각화)**: 헤더 `기업명 (종목코드) · corp_code · 시장`. 패널A=지표 멀티셀렉트(카테고리 그룹)+그래프/표 토글+분기/연간+금액(억원)/비율(%) 이중축+CSV. 패널B=주가 OHLC/종가+거래량+**log 토글**+멀티플 오버레이. **패널C=주가·재무 결합**: 주가(라인,좌축 원,log)+선택 재무항목(막대,우축 억원) 이중축으로 펀더멘털↔주가 추세 동시 관찰(분기/연간 grain 연동). DQ≥2 경고 배너.
   - ※ 분기 재무는 `calendar_financials` 달력분기 CQ1~CQ4 이산(IS/CF=3개월·BS=분기말 스냅샷)로 토글 반영(Phase 1.5 구현 완료).
2. **Screener**: 분할 레이아웃(§2.4). 좌=카탈로그 필터+집계(avg/CAGR/YoY, 최대10년)+퀀트 ≤3패스+결과표(기업명/코드/종목코드). 우=선택기업 시각화.
3. **Compare**(후기): comparator.compare 래핑.
4. **Valuation**(후기): DCF + 배당 패널.

---

## 3. 단계별 빌드 순서 + 검증

- **Phase 0 — 스캐폴드**: `.venv`에 `streamlit` 설치(requirements.txt 추가), `app/main.py` + 사이드바 기업검색, DB 연결 스모크. *검증:* 앱 로드, `search_corps("삼성")` 반환.
- **Phase 1 — Company MVP(연간)**: `load_standard_financials`(FY)+`compute_ratios`+`compute_multiples`로 연간 재무표 + log 가능 주가차트 + CSV. *검증:* `python run.py analyze <corp>` 수치와 동일(동일 엔진).
- **Phase 2 — 레지스트리+차트패널**: `MetricSpec`/`METRIC_REGISTRY`+`build_metric_frame`+멀티셀렉트+그래프/표 토글+분기/연간(연간=load_standard_financials, 분기=calendar discrete). *검증:* ROE/op_margin/매출 시계열이 엔진 출력과 기간별 일치, 분기 CQ1–4 합≈FY.
- **Phase 3 — 스크리너 단일패스**: 카탈로그 필터+`screen()` 문법, 결과표 풀 식별자. *검증:* `run.py screen --roe ">15%"` 결과·정렬 일치.
- **Phase 4 — 윈도우집계+퀀트+분할뷰**: `load_screening_window(n≤10)`+avg/CAGR/YoY+≤3 퀀트패스+클릭→우측 시각화(비파괴). *검증:* 알려진 기업 CAGR/avg 수기 대조, 행클릭 시 좌측 결과 유지.
- **Phase 5 — 대가 지표 + 폴리시**: Graham/Greenblatt/Lynch/Fisher custom 지표 등록, Compare/DCF/Dividend 페이지, 캐싱/성능. *검증:* DCF/배당 페이지가 `run.py` 출력과 일치, 마법공식 랭크 산식 검증.

---

## 4. 성능 주의
- **`valuation_daily` 전수 스캔 금지** — 단일 stock_code 필터시만 빠름(`ix_sp_stock_date`). 스크리너 멀티플은 윈도우쿼리+corp별 1행 LATERAL.
- 모든 DB 로더 `st.cache_data`(params 키). 10년 윈도우가 최중량 → `(fy,n,stmt)`별 1회 캐시, 퀀트패스는 메모리에서.
- 기존 인덱스로 핫패스 충분(`ix_sf_screening_full`, `ix_std_v2_corp_period`, `ix_sp_stock_date`). 분기차트 느리면 `std_financials_calendar(corp,stmt,is_discrete,period_end)` 인덱스 검토.
- 주가차트 5년+ 범위는 주간 다운샘플. 금액은 raw 원 유지하고 포맷 경계에서 ÷1e8 벡터화.

---

## 5. 산출물 (승인 후 작성)
1. `app/` 패키지 (위 구조, Phase 0→5)
2. `requirements.txt`에 `streamlit` 추가
3. **PRD `docs/prd/05_visualization.md`** — 목표/지표카탈로그(§1)/페이지명세/단위·기간·연결별도/CSV/수용기준
4. **PRD `docs/prd/06_screener.md`** — 필터·윈도우집계·퀀트 다단계·분할뷰 명세/수용기준
5. **체크리스트 `docs/prd/05_06_checklist.md`** — Phase 0~5 진행상황 + 지표 등록 체크리스트(카탈로그 항목별 done/todo)

---

## 6. 주요 파일
- 신규: `app/**` 전체
- 확장: `analyzer/screener.py`(`_load_screening_data` rn캡→윈도우; `_parse_condition`/`_check` 재사용)
- 재사용(수정 없음): `analyzer/ratio_engine.py` · `buffett_engine.py` · `valuation_engine.py` · `dividend_engine.py` · `dcf_engine.py` · `comparator.py` · `display/table_view.py` · `collector/db.py`(뷰·세션)
- 신규 문서: `docs/prd/05_visualization.md` · `docs/prd/06_screener.md` · `docs/prd/05_06_checklist.md`

---

## 7. 검증 (전체 E2E)
1. `streamlit run app/main.py` 기동 → 사이드바 기업검색 동작.
2. Company 페이지 수치 == `python run.py analyze --corp <code>` (동일 엔진이므로 정확일치 기대), 3개 기업 교차확인.
3. 분기 토글: calendar discrete CQ1–4 합 ≈ FY 검증.
4. 스크리너 == `python run.py screen --roe ">15%" --per "<12"` 결과/정렬 일치.
5. 윈도우 CAGR/avg 1개 기업 수기 대조; 퀀트 3패스 순차 축소 확인; 행클릭 시 좌측 결과 비파괴.
6. CSV export 다운로드 → 값이 raw 원 보존(표시는 억원).
7. 주가차트 log 토글 동작.
