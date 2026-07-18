# 재무↔주가 결합 지표 계층 (밸류에이션 멀티플)

## Context

주가 데이터 확충(일별 OHLCV 6.1M행, 커버리지 100%)이 끝났고, KRX 시총·펀더멘탈은 구조적
breakage 로 미수집 상태. 이제 검증 재무 DB(`std_financials_v2`)와 주가(`stock_prices`)를 결합해
**밸류에이션 멀티플**(시총·PER·PBR·PSR·EV/EBITDA·EPS·BPS·배당수익률)을 파생하는 계층을 만든다.
이게 주가연동 시각화의 지표 토대다.

**핵심 제약 = 상장주식수**. 모든 멀티플이 shares 에 의존하는데 `std_v2.shares_out` 은 **29%만** 채워짐.
출처를 추적하니 `fin2/standardize/build.py::_shares_out`(:112) 가 `stock_prices.shares_out` 에서 읽고,
그 값은 과거 sparse DART 수집분뿐이다. ⟹ **DART 전수 백필이 키스톤**(`analyzer/price_fetcher.py::
get_shares_from_dart` 작동 확인됨: 삼성 2024 = 5,969,782,550주).

사용자 확정: ① 주식수 **전체 이력 DART 백필** ② **시총 일별 적재 + 멀티플 view**(materialized 테이블 아님).

## 재사용 (신규 로직 최소화)
- `analyzer/valuation_engine.py::compute_multiples`(:52) — PER/PBR/PSR/PCR/EV/EV-EBITDA/EV-EBIT/EV-FCF
  **공식 그대로**(EV=시총+순부채, PER=mc/지배순이익, PBR=mc/지배자본…). 이 공식을 view 의 SQL 로 이식.
- `analyzer/price_fetcher.py::get_shares_from_dart`(:106) — DART stockTotqySttus 보통주 조회(백필에 재사용).
- 멱등 ALTER 마이그레이션 패턴: `collector/db.py::_run_migrations`. 오케스트레이터 골격:
  `scripts/fin2_sync_prices_daily.py`(shard/resume/limit).

## 변경 사항

### Part A — 주식수 전체 이력 백필 (키스톤) · `scripts/fin2_backfill_shares.py` (신규)
- 대상 = `std_financials_v2` FY 행 중 `shares_out IS NULL`(corp_code, fiscal_year DISTINCT).
- 각 (corp, fy): `get_shares_from_dart(corp, fy)` → 값이 있으면:
  1. `UPDATE std_financials_v2 SET shares_out=:n WHERE corp_code AND fiscal_year AND fiscal_period='FY'`
     (consolidated·separate 양쪽 — 주식수는 실체 단위 동일).
  2. `stock_prices.shares_out` 에 그 FY `period_end` 최근접 거래일 행으로도 seed(=기존 `_shares_out`
     소스 일관 유지 → 향후 재표준화가 백필을 덮지 않음).
- `--shard I/N`·`--resume-file`·`--limit`·`--corp`. DART 쿼터(일 20K) → **사용자 직접 실행(장시간, ~1일)**.
  [[feedback-long-running-commands]]. 결측(해당연도 보고서 없음)은 NULL 유지(부분 커버 허용).

### Part B — 시총 일별 적재 (액면분할 보정) · `scripts/fin2_market_cap_daily.py` (신규)
- ★ **close_price 는 KRX 수정주가**(pykrx adjusted=True 기본 — 분할·무상·유상을 현재 기준 back-adjust).
  ⟹ 시총은 **수정주가 × 현재(최신 FY) 상장주식수** 로 계산해야 전 기간 일관(`close × as-of-shares` 는
  분할 이전 시점에서 틀림). 분할 이전 가격이 자동으로 현재 주식수 기준이 됨(사용자 요구 충족).
- 순수 set-based SQL: `current_shares`= corp 최신 FY shares(con/sep max) → `market_cap = close × current_shares`,
  `stock_prices.shares_out = current_shares`(상수, 항등 유지). 실제 연도별 주식수는 std_v2.shares_out 보존.
- 멱등. shares 없는 corp 는 market_cap NULL. ⚠ 분할 동작 검증은 실 KRX 데이터 필요(현 env 합성가).

### Part C — 멀티플 view `valuation_daily` · `collector/db.py::_run_migrations` (멱등 CREATE OR REPLACE VIEW)
- grain = (stock_code, trade_date). 각 행을 **as-of FY 재무**(period_end ≤ trade_date 중 최신, consolidated
  우선·없으면 separate)에 LATERAL 조인. 단일종목 조회(WHERE stock_code=…)는 인덱스로 빠름.
- 노출 컬럼: corp_code, corp_name, stock_code, trade_date, close_price, market_cap, shares_out,
  fiscal_year(기준재무), basis, **per, pbr, psr, pcr, ev, ev_ebitda, ev_ebit, eps, bps, dps, dividend_yield**.
  - per=mc/지배순이익(>0), pbr=mc/지배자본(sep=총자본), psr=mc/revenue, pcr=mc/cfo, ev=mc+net_debt,
    ev_ebitda=ev/ebitda, eps=지배순이익/shares, bps=지배자본/shares, dps=dividends_paid/shares,
    dividend_yield=dps/close. (compute_multiples 와 동일 가드: 분모>0일 때만.)
- (선택) `scripts/diag_valuation.py` 또는 인라인 쿼리로 스팟체크.

## 검증 (end-to-end)
1. **Part A 파일럿**(`--corp 00126380`): 삼성 FY 전 연도 shares 채워짐, std_v2·stock_prices 동기.
2. **Part B 후**: 삼성 최근 거래일 market_cap ≈ close×shares(수백조), forward-fill 경계(분할·증자) 점검.
3. **Part C 뷰**: `SELECT * FROM valuation_daily WHERE stock_code='005930' ORDER BY trade_date DESC LIMIT 1`
   → PER ≈ 시총/지배순이익, PBR>0, EPS·BPS 합리적. 알려진 대형주 1~2개 교차 상식 점검.
4. **커버리지**: 멀티플 non-null 비율(=shares 백필 성공 종목/연도). 결측 트리아지(보고서 없는 구·소형).
5. golden 무관(이 계층은 std_v2 read-only 파생, Layer 1 불가침). init_db 무에러(뷰 생성 멱등).

## 데이터 가용 한계 (조사 확정, 2026-06-27) — 20년+ 목표 관련
- **재무 std_v2: 1997~2026 (30년)** ✓ 이미 최대.
- **주식수**: DART stockTotqySttus 는 ~2016+ 만 보유(이전 `istc_totqy='-'`). pre-2016 EPS 파생도
  **0% 커버**(레거시 미태깅). pre-2016 은 '주식의 총수' 보고서 파싱만이 길(raw_report 접근 가능).
- **주가**: pykrx·FDR 둘 다 **~2014 floor**(pre-2014 0행, 무료소스 고갈). 더 과거는 대체/유료 소스 필요.
- ⟹ **밸류에이션 멀티플은 주가가 병목 → 2014+**. **사용자 결정: 2014+ 만 확정**, 아래 확장 보류.

## 비범위 (후속 — 사용자 보류)
- **주식수 보고서 파싱**(2014-2015 갭 2,364 + pre-2014 → 주가 없는 20~30년 EPS/BPS 추이). raw_report.
- **딥 주가 소스 조사**(pre-2014 일별주가 = KRX 정보데이터시스템 bulk·네이버 등).
- 스크리닝/비교(전수 멀티플 정렬) — 필요 시 valuation_daily 를 materialized 로 승격.
- 시각화 앱(Streamlit 등) — 다음 단계. valuation_daily + calendar_financials + stock_prices 소비.
- TTM(최근 4분기 합) 기반 PER — 현재는 연간(FY) 기준. 분기 결합은 후속 옵션.
