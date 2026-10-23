# 외부 소비자용 DB 가이드 (A안: DB 내장) — 초안 2026-10-23

> 상태: **초안, DB 미적용.** 검토 후 별도 요청 시에만 적용한다(스키마 변경 포함).
> 목적: 별개 프로젝트(tj_asset 등)의 Claude 가 파일을 읽지 않고 **DB 접속만으로** 계층3 데이터 사용법을 알게 한다.
> 분리 원칙: 쓰기는 tj_finance 만, 소비자는 `tja_reader`(읽기 전용)로 조회만.

## 1. 구성

| 요소 | 내용 |
|---|---|
| `consumer_guide` 테이블 (신규) | `section`(PK), `ord`, `title`, `body`, `guide_version`, `updated_at`. 본문은 아래 §3 |
| `COMMENT ON` | 소비자 대상 객체 9개의 표/컬럼 설명을 영어로 보강 (기존 한국어 코멘트 236개는 유지, 빈 컬럼만 채움) |
| 권한 | `GRANT SELECT ON consumer_guide TO tja_reader` |
| 진입점 | 소비자 CLAUDE.md 에 한 줄: `SELECT section,title,body FROM consumer_guide ORDER BY ord` 를 먼저 읽을 것 |
| 유지 | 스키마/규칙 변경 시 tj_finance 가 가이드 행과 `guide_version` 을 같이 갱신. 가이드 본문은 `docs/consumer_guide/*.md` 를 원본으로 두고 적재 스크립트로 upsert (원본 1곳) |

적용 시 해야 할 일: 마이그레이션 SQL 작성 → `schema_migrations` 기록 → 적재 스크립트 → `tja_reader` 로 조회 확인.
스키마 변경(테이블 1개 추가)이므로 CLAUDE.md "스키마 변경은 아침에 확인" 대상.

## 2. 실측으로 확인한 사실 (가이드 근거)

- 소비자용 객체: `corporations`, `filings`, `std_financials_v3`(원본), `standard_financials`(뷰, v3 + gate_b), `standard_financials_verified`(뷰, gate_b=pass 만),
  `std_financials_calendar`/`calendar_financials`(version=1), `extended_financials`(뷰, 계정과목 long format), `report_lines_l3`(뷰), `stock_prices`, `valuation_daily`(MV).
- 기간 의미: `std_financials_v3.fiscal_period` ∈ FY/H1/Q1/Q3 이고 **흐름 값은 누적(YTD)**. 삼성전자 2024 revenue: Q1 71.9조 / H1 146.0조 / Q3 225.1조 / FY 300.9조.
  `std_financials_calendar.calendar_period` CQ1~CQ4 는 **분기 단독**(CQ2 = 74.1조), CY 는 연 합계. 비12월 결산사는 `derivation='recomposed'`(합성).
- `statement_type` ∈ consolidated/separate. `consolidation_status`: `consolidated`(연결) / `no_subsidiary_confirmed`(종속기업 없음 확인, 별도=연결) / `fallback_unconfirmed`(연결 없어 별도로 폴백, 미확인) / 빈 값(별도 행).
- `data_quality`: 1 정상(분기 테이블은 핵심 항목 전부 존재), 2 경고, ≥3 항등식 위반으로 **격리**(쓰지 말 것). 분포 316,090 / 2,576 / 1,513.
- 범위: `std_financials_v3` fiscal_year 1999~2027, 2,544개 종목(KOSPI 800 + KOSDAQ 1,731 활성). `stock_prices` 1990-01-03~2026-10-23.
- `report_lines_l3` = `report_lines`(계층2 인쇄값) + `layer3_cell_corrections`(value 보정 대체, drop 제외, 추가행 union). `printed_value_won` 이 인쇄값, `value_won` 이 보정값, `correction_rule` 이 보정 사유.
  `report_lines`(26 GB)는 소비자 금지. 뷰를 `filings` 와 조인하면 26 GB 스캔 → rcept_no 를 `= ANY(ARRAY(SELECT ... WHERE is_final))` 로 전달.
- 금액 단위는 컬럼명이 `_won`/표준 컬럼 모두 **원(KRW)**, `bigint`. EPS 등 주당 값은 원 단위 정수가 아닐 수 있어 `amount_exact`(numeric) 사용.
- `standard_financials` 는 gate_b 상태가 `fail_a` 인 행을 제외하고 `unaudited` 를 포함한다. 엄격 사용은 `standard_financials_verified`(pass 만, 커버리지 낮음).

## 3. 가이드 본문 (consumer_guide 행, 영어)

### s01_scope (ord 10) — What this DB is
Korean listed companies (KOSPI/KOSDAQ common stock). Source = DART periodic reports (annual/half/quarter), price data from KRX. Maintained by the separate tj_finance project; you have read-only access. Amounts are KRW (won), bigint. Never write.

### s02_layers (ord 20) — Which layer to use
- Layer 2 `report_lines` = printed values only, unrefined. **Do not query it.**
- Layer 3 = refined. Use `report_lines_l3` for line-level data, and `std_financials_v3` / `standard_financials` / `std_financials_calendar` for standardized metrics.
- `printed_value_won` shows the original printed number; `value_won` is the corrected one; `correction_rule` tells why it differs.

### s03_standard_tables (ord 30) — Standardized financials
- `std_financials_v3` key: (corp_code, fiscal_year, fiscal_period, statement_type). fiscal_period FY/H1/Q1/Q3; flow items (revenue, net_income, cfo, ...) are **cumulative year-to-date**; stock items (total_assets, ...) are period-end balances.
- `std_financials_calendar` (use view `calendar_financials`, version=1): calendar-aligned. CQ1..CQ4 are **discrete quarters**, CY is the calendar year. Prefer this for TTM/QoQ work; non-December fiscal years are recomposed (`derivation='recomposed'`).
- statement_type: consolidated | separate. Check `consolidation_status` (see s05).
- Always filter `data_quality < 3` (3+ = identity violation, quarantined).
- `standard_financials_verified` = only rows that passed the independent audit (gate_b = pass); higher trust, lower coverage.

### s04_point_in_time (ord 40) — Avoiding look-ahead bias
`filings.filed_at` is the disclosure date. A period is public only on/after the earliest `filed_at` of a filing whose `period_end_date` equals the period end. `std_financials_calendar` has no filing date; join `filings` on (corp_code, period_end_date) and use `min(filed_at)`. Amended filings (`is_amendment`) replace originals (`is_final`, `superseded_by`); values in standard tables already reflect the final filing, so a historic backtest sees corrected numbers earlier than the market did.

### s05_consolidation (ord 50) — Consolidated vs separate
Prefer consolidated. `consolidation_status`: `consolidated` = real consolidated statements; `no_subsidiary_confirmed` = company has no subsidiaries (separate equals consolidated, confirmed from the report); `fallback_unconfirmed` = no consolidated data found, separate shown, not confirmed — treat with caution.

### s06_line_level (ord 60) — Line items (`report_lines_l3`)
Columns: statement (BS/IS/CF/SCE), basis, section_path, label_raw, period_kind, is_cumulative, value_won, node_role, col_label. Filter to final filings only: `rcept_no = ANY(ARRAY(SELECT rcept_no FROM filings WHERE corp_code=%s AND is_final AND ...))`. Do NOT join the view to `filings` (scans 26 GB). `extended_financials` offers canonical-account long format (`canonical_account`, `amount_won`, `amount_exact`) when a metric is not a standard column.

### s07_prices (ord 70) — Prices and valuation
`stock_prices` (stock_code, trade_date): OHLCV, market_cap (KRW), shares_out, per/pbr/eps/bps/dps/div_yield as published by KRX. `valuation_daily` (materialized view, joins prices with financials per corp/basis/fiscal_year): per, pbr, psr, pcr, ev, ev_ebitda, ev_ebit. Use `stock_code` for prices and `corp_code` for financials; map via `corporations`.

### s08_limits (ord 80) — Known gaps
- 462 filings (2015+) exist only as PDF and are parked; their periods may be missing.
- Pre-2015 data is thinner and less verified than 2015+.
- Foreign companies (stock_code starting with 9) and delisted companies' follow-ups are excluded; `corporations.is_active=false` rows exist for delisted names (survivorship matters for backtests).
- Financial-sector firms (`account_bucket='financial'`, 74 companies) use a different account structure; revenue/gross_profit/cogs are not comparable.
- `fiscal_year` follows the company's own fiscal year (values up to 2027 occur for non-December year-ends).
- Report problems to the tj_finance owner; do not patch data locally.

### s09_examples (ord 90) — Verified example queries
(Each example is to be executed against the DB before it is stored; see §5.)
1. Latest 4 discrete quarters of consolidated revenue and net income for one stock.
2. Point-in-time revenue as of a date (join `filings` for `min(filed_at)`).
3. Price + latest PER/PBR for a stock.
4. Final-filing line items for one report (the `= ANY(ARRAY(SELECT ...))` pattern).

## 4. COMMENT ON 보강 대상

대상 객체: `std_financials_v3`, `std_financials_calendar`, `report_lines_l3`, `stock_prices`, `valuation_daily`, `extended_financials`, `corporations`, `filings`, `standard_financials(_verified)`.
기존 코멘트가 있는 컬럼은 유지. 비어 있는 컬럼과 표 단위 설명(예: "flow columns are cumulative YTD")만 추가한다. 코멘트는 영어.

## 5. 적용 전 검증 항목

- [ ] 예제 SQL 4개를 `tja_reader` 로 실제 실행해 결과 확인(삼성전자 등 2~3종목).
- [ ] `valuation_daily` 컬럼 의미 확인(`fiscal_year`/`basis` 가 어떤 재무 시점을 가리키는지, 갱신 주기).
- [ ] `data_quality` 2 의 정확한 의미 확인(코드상 1/≥3 만 확인됨 — 2 는 추정).
- [ ] 금융업·비12월 결산사 예외 문구를 `docs/rules/20_layer3_map.md` 와 대조.
- [ ] 가이드 원본 위치 결정: `docs/consumer_guide/*.md` (권장) → 적재 스크립트 → `consumer_guide` upsert.
- [ ] `tja_reader` 권한 범위가 가이드가 안내하는 객체와 일치하는지(`report_lines` 접근 차단 여부 포함).
- [ ] 적용은 사용자 승인 후. 야간(22–08시)이면 자율 적용 가능하나 스키마 변경은 아침 확인 항목.
