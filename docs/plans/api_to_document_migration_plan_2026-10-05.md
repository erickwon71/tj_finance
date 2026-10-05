# DART API 유래 테이블 → 원문 문서 추출 전환 계획 (2026-10-05)

> 상태: **2015+ 완료(2026-10-05)** — Phase 0~7 실행·컷오버 완료(커밋 7233c98). Phase 8 완료(R225, 유통주식수). 남은 것: 2014 이전(표제 폴백 매핑).
> 발단: 삼양식품 분석 리포트 점검 중 `dividend_facts` 가 원문이 아닌 DART OpenAPI(alotMatter) 유래임을 확인.
> 원칙: CLAUDE.md "DB화할 재무등의 정보는 모두 local folder에 저장된 문서로부터 가져올 것".
> 파서 작업 전 필독: `docs/PARSING_RULES.md`, 편입 절차: `docs/runbook_new_parser_pipeline_integration.md`.

## 1. 결론 요약

| 구분 | 테이블 | 처리 |
|---|---|---|
| **전환 (10)** | dividend_facts · treasury_activity · employee_stats · executives · exec_pay_summary · exec_pay_individual · other_investments · major_shareholders · shareholder_changes · retail_ownership | 정기보고서 해당 섹션에서 추출. **테이블명·컬럼 유지**(앱 무변경), 소스만 교체. API 테이블은 검증 통과 후 백업→DROP |
| **API 유지 (2)** | capital_events · regulatory_events | 정기보고서가 아닌 주요사항보고서·시장조치 공시가 소스 → 로컬 문서로 만들 수 없음. **사용자 승인 예외**로 문서화 |
| 부속 | periodic_api_progress | 전환 완료 후 함께 DROP |
| **전환 (컬럼)** | stock_prices.shares_out | DART stockTotqySttus(사업보고서 기준 연 1회) 유래. 원문 기반 `report_shares_outstanding`(분기별)이 이미 있음 → Phase 8 에서 소스 교체 |

> 테이블 수: 10개. major_shareholders·shareholder_changes·retail_ownership 은 같은 섹션('주주에 관한 사항')이라 1개 도메인으로 묶어, 실제 작업 단위는 **7개 도메인**이다.

**전환 이득**
- 원문 대조 검증 가능(API 값은 대조 불가 + API 스펙 변경에 조용히 깨짐).
- 커버리지 확대: API 테이블은 전부 **2015+만**(executives 는 2024 하나). 로컬 XML 은 사업보고서 1999+ 53,580건(2015+ 29,756 · 2010-14 9,883 · 1999-2009 13,941).
- 주주·임원 4테이블은 수동 스크립트라 7월 초 이후 갱신이 멈춰 있음 → 데일리 파이프라인에 편입.

## 2. 아키텍처 — 계층2 범용 섹션표 + 계층3 도메인 매퍼

기존 4계층 원칙(계층2=원문 그대로·판단 없음, 계층3=해석)을 그대로 따른다. `biz_section_tables`(사업의 내용 전용)를 일반화하는 대신, **정기보고서 비재무 섹션 전체**를 담는 범용 계층2 테이블을 하나 둔다.

### 2.1 계층2 `doc_section_tables` (신설)
- 1행 = 원문 표 1개. 컬럼(안): `rcept_no, corp_code, report_fiscal_year, report_fiscal_period, section_key(정규화 표제), section_title_raw, heading_path(섹션 안 소제목 경로), table_ord, unit_decl_raw, basis_date_raw('기준일'), grid JSONB(ROWSPAN/COLSPAN 전개 셀 격자), n_rows, parsed_at`.
- 섹션 귀속은 `parser/xml/section_detector.py::assign_tables_to_dart_sections` 의 **문서 순서** 규칙을 쓴다(계단식 중첩 SECTION 실측 근거가 이미 문서화됨).
- 격자 전개는 `biz_raw_tables.py`·`table_extractor._get_cells` 와 같은 방식.
- 범위: 이번 10개 테이블 섹션 + (적재만) census 미귀속 상위 섹션. 매퍼는 이번 도메인만 만든다 — 나머지 섹션은 나중에 매퍼만 추가하면 됨.
- 적재: rcept 단위 delete-then-insert. R219 교훈대로 **자기 범위(section 집합)만 지우는** scope 규약을 처음부터 둔다.

### 2.2 계층3 도메인 매퍼 (도메인당 1모듈, `fin2/layer3/doc_<domain>.py`)
- 입력 = `doc_section_tables` 만(원문 파일 직접 접근 금지, R1).
- 출력 = 기존 테이블 스키마 그대로. `raw` JSONB 는 `source_ref`(rcept·table_ord·row) 로 대체하고 원문 셀 텍스트를 남긴다.
- 정본 선택은 `PARSING_RULES` 정본 정책(최초등록본 + 순차 델타 패치)을 따른다. API 는 최종 정정본만 주었으므로, 정정 이력 처리 방식이 API 와 달라질 수 있다 → 검증 단계에서 차이로 드러나면 원문 기준.

## 3. 도메인별 원문 구조 (실측: 삼양식품 2003·2010·2016·2024 사업보고서)

섹션 표제 변형이 시대별로 크다 → **전사 표제 카탈로그 스캔**(census 도구 확장)을 Phase 0 에서 먼저 한다.

| 도메인 → 테이블 | 표제 변형(실측) | 표 구조 메모 |
|---|---|---|
| 배당 → dividend_facts | 2024 `배당에관한사항` · 2010/2016 `배당에관한사항등` · 2003 `가.최근5사업연도의배당에관한사항` | '주요배당지표' 표(15~17행): 구분×주식종류×당기/전기/전전기. 2024 는 앞에 배당정책·배당기준일 표가 추가됨(표 4개 중 4번째). 당기 열만 그 연도로 적재(계층2 당기만 원칙과 동일) |
| 주주 → major_shareholders · shareholder_changes · retail_ownership | `주주에관한사항` · 2003 `가.최대주주및그특수관계인의주식소유현황`/`나.5%이상주주…`/`라.소액주주,최대주주및기타주주분포` | 다단 헤더(기초/기말 × 주식수/지분율). 최대주주 법인 개요·대표자 변동 표가 같은 섹션에 섞임 → 헤더 패턴으로 표 종류 판정 |
| 임원 → executives | `임원및직원등의현황` · 2010/2016 `임원및직원의현황` · 2003 `임원의현황` | 명부 표(성명·성별·출생년월·직위·등기여부·상근·담당·경력·소유주식·관계·재직·임기). 변동(선임/사임) 표 별도 |
| 직원 → employee_stats | 같은 섹션 · 2003 `직원의현황` | 부문×성별 × 정규/계약/합계·근속·급여 |
| 임원보수 → exec_pay_summary · exec_pay_individual | `임원의보수등` · 2003 `라.임원의보수등` | 주총승인금액 표, 전체 보수 표, 유형별 표, 개인별 5억 이상 표. 단위(천원/백만원) 선언 표가 별도 행으로 앞에 옴 |
| 타법인출자 → other_investments | `타법인출자현황(상세)`(상세표 부속) · 2003 `타법인출자현황` · 2010/2016 표제 미검출 → 위치 확인 필요 | 3단 헤더. 2024 는 첫 표가 '본문 위치로 이동' 링크 |
| 자기주식 → treasury_activity | 2003 `다.자기주식의취득및처분` · 2024 는 SECTION 표제 없이 '주식의 총수 등' 안 소제목/본문 | 취득방법(대/중/소)×주식종류 × 기초/취득/처분/소각/기말. **SECTION 표제가 아닌 소제목 탐지 필요**(heading_path) |

분기·반기보고서는 일부 섹션이 생략·축약된다(개인별 보수·소액주주 등은 사업보고서 위주). 현재 API 테이블도 사업보고서(11011) 기준이라 **1차 범위는 사업보고서**, 반기·분기는 섹션이 있는 경우만 추가 적재(후속).

## 4. 검증 — API 를 "대조 기준"으로 한 번 쓰고 버린다

1. **겹치는 기간(2015+) 필드별 일치율**: 문서 추출값 vs API 값. 도메인별 게이트(안): 숫자 필드 일치율 ≥ 99%.
2. 불일치는 **원문 대조로 판정**한다(API 가 정답이 아님). 원문과 같으면 원문 채택(과도복구 금지 원칙과 동일), 파서 결함이면 규칙 추가 → `PARSING_RULES` R 번호 부여.
3. 2015 이전(API 없음)은 표본 원문 대조 + 항등식(배당총액 = DPS × 주식수 근사, 직원 합계 = 부문 합 등).
4. 회귀 테스트: 도메인별 시대 대표 표본(2003·2010·2016·2024) 고정 픽스처.
5. 앱 스모크: 주주환원·임원·지분 탭과 차트빌더 div.* 지표가 같은 값을 그리는지.

## 5. 단계 (도메인 단위로 끝까지 — 설계→구현→백필→검증→컷오버)

| Phase | 내용 | 산출 |
|---|---|---|
| 0 | 표제 카탈로그 전사 스캔(SD 미러, 읽기 전용) + `doc_section_tables` 스키마/계층2 writer + 데일리 배선 + 전수 적재 | 섹션 변형 카탈로그 문서, 계층2 테이블 |
| 1 | **배당**(앱 노출 최다: DPS·수익률·배당성향·총주주환원율·차트빌더) | dividend_facts 문서판 |
| 2 | **주주 3종**(7월 이후 갱신 정지 해소) | 3테이블 |
| 3 | 임원 + 직원 | 2테이블 |
| 4 | 임원보수 2종 | 2테이블 |
| 5 | 타법인출자 | 1테이블 |
| 6 | 자기주식(소제목 탐지가 필요해 가장 까다로움) | 1테이블 |
| 7 | 컷오버 정리: API 테이블 pg_dump 백업 → DROP, `collector/dart_periodic.py`·`collect_shareholders.py`·`collect_executives.py`·`collect_new._sync_periodic_apis` 제거, `periodic_api_progress` DROP, census `_API_TOPIC` 갱신 | — |
| 8 | stock_prices.shares_out 소스 교체(§8) | 컬럼 소스 교체 |

각 Phase 의 컷오버 방식: 매퍼가 **같은 테이블에** 문서판을 적재하기 전에 API 판을 `<table>_api_snap` 으로 떠 두고(대조 기준), 검증 통과 후 스냅샷을 백업 파일로 내보내고 DROP.

**편입 체크리스트(runbook)**: ① `scripts/collect_new.py` 두 call site(메인 + `--standardize-only`) 배선, ② 1999+ 소급 백필(수동, SD 미러), ③ 회귀 테스트 + 원문 대조 + Gate B 무영향 확인.

## 6. 규모·리스크

- 공수(추정): Phase 0 이 가장 큼(범용 계층2 + 카탈로그). 도메인 매퍼는 Phase 당 1~2 세션, 자기주식·타법인출자는 표제/헤더 변형 때문에 더 걸릴 수 있음.
- 백필 시간: 사업보고서 53,580건 계층2 적재. R219 복구 실측(주석 포함 재추출 ≈ 분당 200~280건, 6워커)보다 가벼움(섹션 일부만) → 수 시간 규모.
- 리스크
  - 표제 변형·소제목 탐지 누락 → 조용한 결측. Phase 0 카탈로그 + "섹션은 있는데 표 0개" 감사로 잡는다.
  - PDF-only 필링(462건 보류 정책) → 이번 범위 밖, 결측으로 남김(API 판에는 있던 2015+ 일부가 빠질 수 있음 → 검증 단계에서 건수 보고).
  - 정정공시 처리 차이로 API 와 값이 다를 수 있음 → 원문 기준.

## 7. 결정 (사용자, 2026-10-05)

1. capital_events·regulatory_events: **다른 용도로 쓰이면 예외로 유지** → 둘 다 사용 중이므로 예외 확정.
   - capital_events: 밸류에이션 탭 희석 이벤트·잠재희석률, `scripts/dq_assertions.py`(launchd dqcheck).
   - regulatory_events: 기업 시각화 페이지 시장조치 표시(페이지 전체가 의존), `collector/delisting.py` 상장폐지 교차신호 ⓐ.
   - 할 일: PARSING_RULES 와 CLAUDE.md 에 "API 허용 목록(사유 포함)"으로 명시.
2. 테이블명·스키마 유지 — 권장대로.
3. 과거 범위 — **2015+ 먼저 완료, 2014 이전은 후속 작업**(2026-10-05 사용자 정정). 2015+ 는 서식 코드(ACLASS) 출현 99~100% 라 코드 경로로 충분하고, 2014 이전은 표제 폴백 매핑이 추가로 필요(docs/qa/doc_section_catalog_2026-10-05.md).
4. 진행 순서 — §5 그대로.
5. `stock_prices.shares_out` — 사용처 확인 결과 아래와 같아 **전환 대상에 포함(Phase 8)**.

## 8. Phase 8 — stock_prices.shares_out 소스 교체

**사용처(코드 확인)**
- `valuation_daily` 머티리얼라이즈드 뷰(`collector/db.py:248`·`975`): 시가총액·EPS·BPS·DPS·배당수익률 = 재무값 ÷ `sp.shares_out` → 앱 밸류에이션 밴드·차트빌더.
- `analyzer/price_fetcher.py:173-189`: `market_cap = close × shares_out`(DART API 값) 경로.
- `analyzer/aggregator.py:701`, `analyzer/dcf_engine.py:292`(시가총액), `analyzer/dividend_engine.py`.

**대체 소스**: `report_shares_outstanding`(계층2, R12, '주식의 총수 등' 원문 전사, 2015+ FY 29,379·H1 25,852·Q1 22,617·Q3 21,206행) + 계층3 `_select_shares_out` 정본 선택. API(사업보고서 연 1회)보다 시점이 촘촘하다(분기말).

**선행 검증(필수)** — 2026-10-05 실측: 2025-06 주가행의 API 값 vs FY2024 문서값, 3,156쌍 중 정확일치 1,938(61%)·1% 이내 2,144(68%). 삼양식품은 일치(7,533,015, 원문 '발행주식의 총수'). 불일치 원인을 먼저 분류한다:
보통주/우선주 합산 여부, 발행주식 vs 유통주식(자기주식 차감) 정의, API 연도 폴백(fy−1), 감자·분할·증자 시점, 다중 stock_code 조인 중복. 정의가 다르면 valuation 산식이 요구하는 정의(보통주 발행주식수, 또는 유통주식수)를 먼저 확정한 뒤 문서값을 맞춘다.

**적용**: 일별 주가행에 "직전 분기말 이전 공시된 최신 문서값"을 as-of 로 붙인다(공시일 기준, 미래 참조 금지). 컷오버 후 `get_shares_from_dart` 제거, valuation_daily 재생성.


## 9. 실행 결과 (2026-10-05)

- Phase 0: `doc_section_tables` 2015+ 사업보고서 29,389필링 · 표 1,036,862 · 832 MB(R224 파서 수정 후 재적재). 표 0개 367필링.
- Phase 1~6: 매퍼 6모듈 + 공통, 테스트 24건. 전사 비교(`scripts/compare_doc_vs_api_2026-10-05.py`, (corp,FY) 그룹 완전일치):
  임원보수 개인 99.95% · 요약 99.87% · 임원 99.59% · 직원 99.50% · 자기주식 99.34% · 소액주주 98.83% · 최대주주 98.61% · 변동 98.60% · 타법인출자 98.36% · 배당 97.14%.
  표본 불일치는 모두 원문판이 맞음(기재정정 반영, API '#######', 주식배당 절삭, API NULL). API 전용 그룹은 자리표시 행('합계'·'-')·결산월 변경 사례.
- Phase 7: 백업 `NAS db_backups/api_tables_before_doc_cutover_2026-10-05.dump` → `scripts/sync_doc_sections.py --all`(2,516개사, 2.4분) 컷오버, API 수집 코드·`periodic_api_progress` 제거, 데일리 ⑤-3 `_sync_doc_sections`(두 call site).
- 부수 발견·수정: R224(`&cr;` 뒤 `&amp;` 소실) — `docs/PARSING_RULES.md` R224.
- 남은 일: 2014 이전(표제 폴백), Phase 8 shares_out, 반기·분기보고서 섹션(필요 시).
- Phase 8(R225, 2026-10-05): 실측하니 stock_prices.shares_out 은 이미 전부 원문 Ⅳ 기반(API 는 price_fetcher 캐시 미스 경로 코드뿐). 사용자 결정 '유통주식수'로 정의 전환 — Ⅴ/Ⅵ 계층2·3 적재, 시총·주당지표 유통주식 기준, `get_shares_from_dart` 삭제. 부수 수정: R90 이전 적재로 1,000배 빠져 있던 Ⅳ 313행(현대로템 시총 126억 → 12.6조). 상세 PARSING_RULES R225.
