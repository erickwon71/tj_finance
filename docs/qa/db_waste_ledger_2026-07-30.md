# DB 용량 낭비 원장 — 2026-07-30 21:30

DB 총 크기 **108.9 GB** · 테이블 36개 · 임계 50 MB 미만 생략

## 0. 테이블 개요 (상위 10)

| 테이블 | 총 | heap | 인덱스 | 행 | 바이트/행 |
|---|---|---|---|---|---|
| `note_lines` | 83.8 GB | 75.9 GB | 7.9 GB | 220,605,004 | 369 |
| `report_lines` | 17.5 GB | 15.0 GB | 2.4 GB | 37,477,142 | 431 |
| `stock_prices` | 2.1 GB | 1.4 GB | 684.9 MB | 11,187,625 | 139 |
| `std_financials_v2` | 386.2 MB | 301.0 MB | 85.0 MB | 522,526 | 604 |
| `statement_source` | 311.1 MB | 216.8 MB | 94.2 MB | 719,619 | 316 |
| `biz_metrics` | 292.5 MB | 195.5 MB | 96.9 MB | 1,189,376 | 172 |
| `std_financials_calendar` | 246.9 MB | 201.1 MB | 45.7 MB | 314,809 | 670 |
| `other_investments` | 231.4 MB | 218.8 MB | 12.6 MB | 252,233 | 909 |
| `biz_section_tables` | 205.1 MB | 101.5 MB | 14.9 MB | 113,263 | 940 |
| `verification_results` | 201.5 MB | 114.5 MB | 87.0 MB | 691,068 | 174 |

## W1. 반복 저장 — 함수종속 **측정** 결과

반복도가 높다고 정규화 대상이 아니다(`value_won` 은 306× 반복이지만 행별 실데이터다).
후보 컬럼마다 `GROUP BY 키 HAVING count(DISTINCT col) > 1` 을 **실제로 질의**해
종속을 확인한다(표본 300 rcept_no). 회수액 = `평균폭 × (행 − 그룹)`.

| 컬럼 | 평균폭 | 종속 키(측정됨) | 표본 | 회수액 |
|---|---|---|---|---|
| `note_lines.table_title` | 141 B | `rcept_no+statement+basis+table_seq` | 995,310행→48,037그룹 | **27.6 GB** |
| `note_lines.section_path` | 33 B | `rcept_no+statement+basis+table_seq` | 964,758행→47,168그룹 | **6.4 GB** |
| `report_lines.table_title` | 164 B | `rcept_no+statement+basis+table_seq` | 144,097행→2,326그룹 | **5.6 GB** |
| `note_lines.unit_source` | 9 B | `rcept_no` | 959,507행→300그룹 | **1.8 GB** |
| `note_lines.corp_code` | 9 B | `rcept_no` | 939,552행→300그룹 | **1.8 GB** |
| `note_lines.parsed_at` | 8 B | `rcept_no` | 857,329행→300그룹 | **1.6 GB** |
| `note_lines.statement` | 5 B | `rcept_no` | 862,574행→300그룹 | **1.0 GB** |
| `report_lines.unit_source` | 9 B | `rcept_no` | 137,987행→300그룹 | **321.0 MB** |
| `report_lines.corp_code` | 9 B | `rcept_no` | 132,517행→300그룹 | **320.9 MB** |
| `report_lines.parsed_at` | 8 B | `rcept_no` | 136,516행→300그룹 | **285.3 MB** |
| `report_lines.period_kind` | 8 B | `rcept_no+statement+basis` | 134,170행→2,276그룹 | **281.1 MB** |

## W2. 사실상 미사용 인덱스

통계 창: `stats_reset` = None — 리셋 이력 없음
같은 창에서 최다 사용 인덱스 = `filings_pkey` **141,234,130 회** → 창이 유효한지 이 값으로 판단한다(0 이면 창 자체를 신뢰할 수 없다).

★ UNIQUE 는 회수액 합계에서 **제외**한다 — `ON CONFLICT` 업서트는 `idx_scan` 을
올리지 않으므로 통계상 0 으로 보이지만 지우면 writer 가 깨진다.

| 인덱스 | 테이블 | 크기 | 스캔 | 종류 | 코드 참조 | 판정 |
|---|---|---|---|---|---|---|
| `note_lines_pkey` | `note_lines` | 4.6 GB | 0 | PK | 2 | 보류 — 대리키 필요성 확인 |
| `note_lines_corp_fy_basis_idx` | `note_lines` | 1.5 GB | 0 | 일반 | 2 | **drop 후보** |
| `report_lines_pkey` | `report_lines` | 805.0 MB | 0 | PK | 0 | 보류 — 대리키 필요성 확인 |
| `uq_stock_prices` | `stock_prices` | 684.9 MB | 0 | PK | 3 | 보류 — 대리키 필요성 확인 |
| `ux_valuation_daily_corp_date` | `valuation_daily` | 470.1 MB | 0 | UNIQUE | 3 | **유지** — 업서트 보호 |
| `ix_report_lines_report_fiscal_year` | `report_lines` | 352.8 MB | 5 | 일반 | 0 | **drop 후보** |
| `ix_report_lines_context_fiscal_year` | `report_lines` | 326.6 MB | 0 | 일반 | 0 | **drop 후보** |
| `statement_source_pkey` | `statement_source` | 67.1 MB | 0 | PK | 1 | 보류 — 대리키 필요성 확인 |
| `uq_verification` | `verification_results` | 58.9 MB | 0 | UNIQUE 제약 | 1 | **유지** — 업서트 보호 |

⚠ `스캔 0` 은 미사용의 증명이 아니다. drop 전에 '코드 참조'·통계 창·종류를 함께 볼 것.
PK 는 `store_report_lines` 가 delete-then-insert 라 조회에 안 쓰이지만, 드롭하려면
복제/논리 디코딩·`ctid` 의존 여부를 먼저 확인해야 하므로 별도 판단으로 남긴다.

## W3. 상수·전량 NULL 컬럼

상수 컬럼은 W1 에서 이미 함수종속으로 잡히는 경우가 많다 — **중복 계상을 막기 위해**
W1 에 이미 든 컬럼은 합계에서 제외하고 표시만 남긴다.

| 컬럼 | 종류 | 평균폭 | 행 | 회수액 | 합계 반영 |
|---|---|---|---|---|---|
| `note_lines.unit_source` | 상수 | 9 B | 220,605,004 | 1.8 GB | W1 중복 — 합계 제외 |
| `note_lines.statement` | 상수 | 5 B | 220,605,004 | 1.0 GB | W1 중복 — 합계 제외 |
| `note_lines.context_fiscal_year` | 전량 NULL | 2 B | 220,605,004 | 420.8 MB | **신규** |
| `report_lines.unit_source` | 상수 | 9 B | 37,477,142 | 321.7 MB | W1 중복 — 합계 제외 |
| `note_lines.is_cumulative` | 상수 | 1 B | 220,605,004 | 210.4 MB | **신규** |
| `stock_prices.per` | 전량 NULL | 8 B | 11,187,625 | 85.4 MB | **신규** |
| `stock_prices.pbr` | 전량 NULL | 8 B | 11,187,625 | 85.4 MB | **신규** |
| `stock_prices.eps` | 전량 NULL | 8 B | 11,187,625 | 85.4 MB | **신규** |
| `stock_prices.bps` | 전량 NULL | 8 B | 11,187,625 | 85.4 MB | **신규** |
| `stock_prices.div_yield` | 전량 NULL | 8 B | 11,187,625 | 85.4 MB | **신규** |
| `stock_prices.dps` | 전량 NULL | 8 B | 11,187,625 | 85.4 MB | **신규** |

## W4. 튜플 정렬 패딩 (근사)

고정폭 컬럼의 **선언 순서**가 만드는 빈틈. varlena 는 short header 면 정렬이
필요 없어 1 B 로 본다 — 그래서 이 값은 하한에 가깝다.

| 테이블 | 현재/행 | 최적/행 | 차 | 행 | 회수액 |
|---|---|---|---|---|---|
| `note_lines` | 325 B | 317 B | 8 B | 220,605,004 | **1.6 GB** |
| `report_lines` | 422 B | 419 B | 3 B | 37,477,142 | **107.2 MB** |
| `stock_prices` | 104 B | 99 B | 5 B | 11,187,625 | **53.3 MB** |

## W5. 코드 참조 0 테이블

과거 `financial_facts`(27 GB) 사례의 재발 감시. 참조 0 이라고 곧 드롭이 아니다 —
동적 SQL·문서화된 수동 절차일 수 있으므로 확인 후 판단한다.

_해당 없음_

## B. Bloat (dead tuple)

| 테이블 | live | dead | 비율 |
|---|---|---|---|
| `std_financials_v3` | 185,268 | 34,282 | 18.5% |

## 합계

회수 가능 추정 **52.3 GB** / DB 108.9 GB (48.0%)

⚠ 합계는 추정이다 — W1 은 표본 투영, W4 는 하한(varlena 정렬 무시)이고, W3·W4 는
서로 완전히 가법적이지 않다(상수 컬럼을 드롭하면 패딩 배치가 바뀐다). 실행 전 항목별 실측 필요.
