# PRD 05 — Visualization (재무·주가 연동 시각화 앱)

> 작성 2026-06-27. 데이터 레이어(PRD 01~04) 종결 후 **원래 개발 목표**인 블룸버그 터미널형
> 시각화로 진입. 총괄: `00_pm_master_plan.md`. 스크리너는 `06_screener.md`.
> 마스터 계획: `~/.claude/plans/curried-doodling-metcalfe.md`. 진행 체크리스트: `05_06_checklist.md`.

## 0. 왜 이 PRD 인가

> 데이터 신뢰(보고서↔DB 100% 일치, Gate B)가 확보되었으므로 이제 그 데이터를 **투자판단용으로
> 본다**. 재무·재무비율·성장성·수익성·안정성·가격·멀티플·배당·대가별 지표를 주가와 연동해
> 원하는 모양(그래프/표)으로 시각화한다. 핵심 원칙: **분석 로직을 새로 만들지 않는다** — `analyzer/`의
> 검증된 엔진을 import 해 Streamlit UI 로 노출한다.

## 1. 목표

활성 KOSPI/KOSDAQ 보통주에 대해, 사용자가 선택한 지표를 **연결/별도·분기/연간**으로
**그래프 또는 표**로 보고, **주가는 log 스케일**까지 지원하며, **표는 CSV 로 export** 한다.
지표 카탈로그는 **config-driven**(레지스트리 한 줄 추가)으로 확장 가능해야 한다.

## 2. 범위 (확정)

- UI: **Streamlit + Plotly** (로컬 실행, Pro 요금제). 진입점 `streamlit run app/main.py`.
- 데이터: `standard_financials`(Layer 1, FY/H1/Q1/Q3) · `calendar_financials`(Layer 2, CQ1–4/CY 이산) ·
  `stock_prices` · `valuation_daily`(단일티커). 금액은 raw 원 저장.
- 표시: 금액 **억원**(자동 조원), 비율 **%**, 멀티플 **x**, 주당 **원**.
- 기업 식별: **기업명 + corp_code + 종목코드** 항상 동시 표시.

## 3. 비범위

- 분석 수식 재구현(전부 `analyzer/` 재사용). 신규는 §6 의 얇은 DB 헬퍼뿐.
- DB 엔진 교체, 수집 대상 확장, 실시간 시세(일별 캐시 기준).
- Excel/CSS export(사용자 결정: **CSV 단독**).

## 4. 단위·표시 규약

| 종류 | 저장 | 표시 | 변환 |
|------|------|------|------|
| 금액(AMOUNT_EOK) | 원(KRW) | 억원(≥1만억 자동 조원) | `÷1e8`, `table_view._fmt_amount` |
| 비율(PCT) | 소수(0.152) | `%`(15.2%) | `×100`, `_fmt_pct` |
| 멀티플(MULTIPLE_X) | 배수 | `x`(12.5x) | as-is, `_fmt_ratio` |
| 주당(PER_SHARE) | 원 | 원 | as-is |
| 일수(DAYS)/점수(SCORE) | 그대로 | 그대로 | — |

- **연결/별도**: 모든 로더가 `statement_type` 파라미터. consolidated 우선, 없으면 separate 폴백(`print_analysis` 패턴).
- **기간 grain**: 연간=`standard_financials` FY. 분기=`calendar_financials` `is_discrete`(CQ1–4, 이산 3개월).
- **CSV export**: 표시는 억원/%이되 **export 값은 raw 원 보존**(재가공 정확성).

## 5. 지표 카탈로그 (METRIC_REGISTRY)

각 지표 = `MetricSpec(id, name_ko, category, unit, source, key, grains, needs_prev, compute)`.
`source` ∈ `column`/`ratios`/`buffett`/`valuation`/`price`/`custom`. **대부분 등록만으로 추가**(엔진 기존 보유).

| Category | 항목(요약) | source |
|----------|-----------|--------|
| FINANCIALS(억원) | 매출·매출원가·매출총이익·판관비·R&D·영업이익·세전·순이익·지배순이익·자산·부채·자본·지배지분·현금·차입금·순차입금·재고·매출채권·영업/투자/재무CF·CAPEX·감가상각·EBITDA·FCF·배당지급·주식수 | column |
| PROFIT(%) | gross/op/net/ebitda margin·ROE·ROA·ROIC·NOPAT·asset_turnover·effective_tax_rate | ratios |
| GROWTH(%) | 매출/영업이익/순이익/자산 성장률 + (윈도우) 매출·EPS·DPS·자본 CAGR | ratios/window |
| STABILITY | debt_ratio·current_ratio·interest_coverage·net_debt_ebitda·capex_to_rev·capex_to_dep·fcf_to_rev·cfo_to_ni·accrual·DSO·DIO·DPO·CCC | ratios |
| PRICE(원) | close·O/H/L·volume·market_cap(억) — **log 스케일 지원** | price |
| MULTIPLE(x) | PER·PBR·PSR·PCR·EV/EBITDA·EV/EBIT·EV/FCF·EPS·BPS | valuation |
| DIVIDEND | DPS·div_yield·payout·연속배당연수·DPS CAGR·평균수익률 | custom(dividend_engine) |

### 5.1 대가별 지표 (MASTER) — 대가 이름과 함께 선택
- **Warren Buffett**(`buffett`, 구현됨): Owner's Earnings·유지보수 CAPEX·FCF Quality(CFO/NI)·ROIC 5y avg/std·발생액비율·payout·buyback_yield·total_shareholder_yield·retained_roe·Piotroski F-Score.
- **Benjamin Graham**(`custom`): Graham Number(√(22.5·EPS·BPS))·PER×PBR(<22.5)·유동비율(>2)·저부채·연속배당·NCAV·NCAV/시총·EPS 안정성.
- **Joel Greenblatt 마법공식**(`custom`): Earnings Yield(EBIT/EV)·Return on Capital(EBIT/투하자본)·두 순위 합산 종합랭크.
- **Peter Lynch**(`custom`): PEG(<1)·매출/이익 동반성장·부채·배당.
- **Piotroski F-Score**(`buffett`, 구현됨): 9항목 합 + 개별 플래그.
- **Philip Fisher**(`ratios`/custom): R&D/매출·영업이익률 추세·매출 지속성장.

> 확장 규약: 신규 지표는 `app/registry/metrics.py` 의 `METRIC_REGISTRY` 에 `MetricSpec` 한 줄 append.
> 기존 엔진에 이미 있는 값이면 코드 0. 새 수식만 `compute` 콜백.

## 6. 입력·출력 계약 / 신규 자산

- **재사용(수정 없음)**: `ratio_engine`(compute_ratios·load_standard_financials·_cagr·_growth_rate) ·
  `buffett_engine`·`valuation_engine`·`dividend_engine`·`dcf_engine`·`display/table_view`(포맷터) ·
  `collector/db.get_session`.
- **신규 패키지 `app/`**: `registry/`(units·metrics) · `data/`(corp·series·multiples) ·
  `compute/resolver.py`(`build_metric_frame` → tidy `(period, metric_id, value, unit)`) ·
  `views/`(company_page·chart_panel·table_panel) · `components/`(selectors·export) ·
  `cache.py`(st.cache_data) · `format.py`.
- **신규 DB 헬퍼(gap)**: `load_annual_series`·`load_quarter_series`(calendar discrete)·`load_price_series`·
  `load_valuation_series(stock_code,…)`·`search_corps(q)`.

## 7. 페이지 명세

### 7.1 Company (시각화)
- 헤더: `기업명 (종목코드) · corp_code · 시장`. DQ≥2 경고 배너.
- **탭 1 — 재무제표**: IS/BS/CF 본문(억원). **분기/연간 토글** = 연간(FY, std_v2) / 분기(달력분기
  CQ1~CQ4 이산, `calendar_financials`; IS/CF=3개월 발생액·BS=분기말 스냅샷). 통합 **CSV export(raw 원)**.
- **탭 2 — 밸류에이션**: 최신 FY 기준 시총·EV·PER/PBR/PSR/PCR·EV배수·EPS·BPS(`compute_multiples`).
- **탭 3 — 주가 차트**: 종가/캔들 + 거래량, **log 스케일 토글**, 기간 선택, 장기 주간 다운샘플.
- **탭 4 — 주가·재무 결합**: 주가(라인, 좌축 원, log 토글) + 선택 재무항목(막대, 우축 억원)을 한
  차트에 **이중축** 결합. 분기/연간 grain 에 따라 막대 시점·폭 변경(펀더멘털↔주가 추세 동시 관찰).
- (후속 패널 A) 카테고리 그룹 멀티셀렉트 지표 패널 + 그래프/표 토글(Phase 2 레지스트리).

### 7.2 (후속) Compare / Valuation
- Compare: `comparator.compare` 래핑(다기업 나란히).
- Valuation: `dcf_engine.run_dcf` + `dividend_engine.analyze_dividend` 패널.

## 8. 성능

- `valuation_daily` 는 **단일 stock_code 필터시만** 사용(`ix_sp_stock_date`). 전수 스캔 금지.
- 모든 DB 로더 `st.cache_data`(params 키). 금액은 raw 원 유지, 포맷 경계에서 `÷1e8` 벡터화.
- 주가 5년+ 범위는 주간 다운샘플. 기존 인덱스로 핫패스 충분.

## 9. 완료기준 (DoD)

- `streamlit run app/main.py` 기동 + 기업검색 동작.
- Company 페이지 수치 == `python run.py analyze --corp <code>`(동일 엔진 → 정확일치), 3개 기업 교차확인.
- 분기 토글에서 calendar discrete CQ1–4 합 ≈ FY.
- 그래프↔표 자유 전환, 주가 log 토글, 연결/별도 토글, CSV export(값=raw 원) 동작.
- 기업명+corp_code+종목코드 항상 동시 표시.
- 카탈로그 신규 지표를 `MetricSpec` 한 줄로 추가 가능함을 시연.

## 10. 위험

- Streamlit 전체 재실행 모델 → 무거운 로더는 캐시 필수(미캐시 시 체감 지연).
- EV/EBITDA 등 일부 지표는 데이터갭(ebitda 커버 ~25%)으로 NULL 다수 → UI 에서 "—" 처리·오해 방지.
- pre-2014 멀티플은 주가 병목으로 부분 결측 → 기간 안내.
