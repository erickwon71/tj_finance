# PRD 06 — Screener (퀀트 스크리너 + 비파괴 분할 시각화)

> 작성 2026-06-27. 시각화(PRD 05)와 짝을 이루는 스크리닝 기능. 총괄: `00_pm_master_plan.md`.
> 마스터 계획: `docs/plans/curried-doodling-metcalfe.md`. 진행 체크리스트: `05_06_checklist.md`.

## 0. 왜 이 PRD 인가

> 시각화는 "아는 기업을 본다". 스크리너는 "조건으로 기업을 찾는다". 확보한 재무·배당·대가별 지표를
> 필터·정렬하여 후보를 좁히고, **퀀트식 다단계 스크린**으로 전략을 실험하며, 선택한 기업을
> **스크린 결과를 가리지 않고** 곧장 시각화로 들여다본다.

## 1. 목표

PRD 05 의 **지표 카탈로그 + 재무/배당 필드**를 조건으로 활성 보통주를 스크린한다.
기간은 **연/분기, 최대 10년**의 **평균 또는 증가율(CAGR/YoY)** 윈도우 집계를 지원하고,
**최대 3단계 퀀트 스크린+정렬**을 순차 적용하며, 결과 행 클릭 시 **분할 화면**으로 시각화를 띄운다.

## 2. 범위 (확정)

- 필터 소스: `METRIC_REGISTRY`(PRD 05) 전 항목 + std_v2 라인 + 배당 필드.
- 윈도우: `n_years ≤ 10`, 집계 = `average` | `CAGR` | `YoY`.
- 퀀트: `≤ 3` 패스, 각 패스 = {필터들, sort_by, asc, limit} 순차 적용.
- 결과↔시각화: 좌(결과)·우(선택기업 시각화) **분할, 비파괴**.

## 3. 비범위

- 백테스트(과거 시점 포트폴리오 수익률 추적)는 후속.
- 실시간 리밸런싱·자동매매 없음.

## 4. 입력·출력 계약 / 신규 자산

- **재사용**: `analyzer/screener._parse_condition`·`_check`(필터 문법 `">15%"`·`"<12"`·`">=7"` 동일) ·
  `_load_screening_data`(확장 대상) · `ratio_engine._cagr`·`_growth_rate`(윈도우 집계) ·
  PRD 05 의 `resolver.build_metric_frame`·`company_page` 패널(우측 재사용).
- **신규**: `app/data/screen_window.py:load_screening_window(n_years, fiscal_year)` —
  `_load_screening_data` 의 `rn<=2` 캡을 `rn<=:n` 으로 확장, corp별 series 그룹화.
  `app/compute/screen_eval.py` — 윈도우 집계 + `run_quant_passes(base, passes)`.

## 5. 데이터 플로우

### 5.1 윈도우 로드 (avg / CAGR / YoY)
- 단일 window-function 쿼리(`standard_financials`, `ix_sf_screening_full`)로 corp별 최근 `n`년 +
  최신 시총(1행 LATERAL). `{corp: {meta, series:[…n행…]}}` 그룹화.
- corp별 지표 series → 집계:
  - `average` = 비결측 평균
  - `CAGR` = `_cagr(series[-1], series[0], len-1)`
  - `YoY` = `_growth_rate(series[0], series[1])`
- 연결/별도 토글이 윈도우 쿼리 `statement_type` 결정(consolidated→separate 폴백).

### 5.2 퀀트 다단계 (≤3)
- 각 패스는 순수 `DataFrame → DataFrame`: `filter(_check) → sort(sort_by, asc) → head(limit)`.
- `df1=apply(base, p1); df2=apply(df1, p2); df3=apply(df2, p3)`.
- 마법공식 등 종합랭크 지표는 패스의 `sort_by` 로 직접 사용.

### 5.3 클릭 → 시각화 (분할·비파괴)
- 레이아웃: `left, right = st.columns([5, 7])`.
- 좌: 필터·집계·퀀트 컨트롤 + `st.dataframe(screen_results, on_select="rerun", selection_mode="single-row")`.
  결과는 `session_state["screen_results"]`(캐시)에서 렌더 → 재실행돼도 유지.
- 행 선택 → `session_state["focus_corp"]` 갱신 → 우: PRD 05 `company_page` 패널 렌더.
- 결과표 식별 컬럼: **기업명 / corp_code / 종목코드** 동시.

## 6. 성능

- 윈도우 로드가 최중량 → `(fiscal_year, n, statement_type)` 별 **1회 캐시**. 퀀트 패스는 메모리 pandas.
- 스크리너 멀티플은 `valuation_daily` 전수 스캔 대신 윈도우쿼리 + corp별 1행 LATERAL.

## 7. 완료기준 (DoD)

- 단일 필터 결과·정렬 == `python run.py screen --roe ">15%" --per "<12"`.
- `n`년 평균/CAGR/YoY 가 1개 기업 수기 대조와 일치.
- 퀀트 3패스가 순차로 모집단을 좁힘(각 패스 결과 검증).
- 결과 행 클릭 시 우측 시각화 표시 + **좌측 결과 비파괴**(유지).
- 결과표에 기업명+corp_code+종목코드 동시 표시.

## 8. 위험

- 10년 윈도우 × 전 기업 로드 비용 → 캐시 미스시 지연. 완화: 캐시 + 필요한 지표만 series 계산.
- 분기 윈도우는 calendar discrete 기준(누적 아님) — 집계 의미 혼동 방지 라벨링.
- 결측 많은 지표(EV/EBITDA 등)로 필터시 모집단 급감 가능 → 결측 처리 정책 명시(제외 vs 통과).
