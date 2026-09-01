# 계획 — 이산분기/달력(calendarize) v3 재설계 스코핑 (2026-09-02)

> 상태: **스코핑만 — 실행 계획 아님.** [정책](../../CLAUDE.md) 상 계획 작성 후 자동 실행
> 금지, 구현은 별도 승인 후 착수. 배경 = `docs/plans/factv2_stdv2_gc_backfill_backlog_
> 2026-09-01.md` §6, 사용자가 "v3 재설계"를 선택(2026-09-02).

## 0. 문제 재정의

`fin2/standardize/quarterly.py::derive_quarters_corp()`(as-filed 누적행→이산분기 파생)와
`fin2/standardize/calendar.py::calendarize_corp()`(이산분기→달력분기 정규화)는 둘 다
`std_financials_v2`를 직접 읽고 쓴다. 이 두 함수는 **`std_financials_v2` DROP(2026-09-01)
훨씬 전, Phase 2(2026-08-30)에 데일리 파이프라인 배선이 끊긴 뒤로 아무도 안 부르고
있었다**(현재 호출부는 수동 CLI `run.py:2928`/`scripts/phase_c_rebuild.py:272` 뿐, 실측
grep 확인). DROP으로 이 두 함수는 `RuntimeError` 가드가 걸려 호출 시 즉시 명확히 죽는다
(우연한 UndefinedTable 대신). `std_financials_calendar`(4개 소비 화면이 읽는 테이블)는
그래서 신규 기업·신규 분기로 전혀 자라지 않는 정지 테이블 — 최신 `calendar_year`=2026,
319,694행(Phase 2 중단 직전까지의 데이터).

## 1. 재설계 방향 (제안)

### 1-1. 두 함수를 하나로 병합 — 이산분기 중간 저장을 없앤다

`std_financials_v3`는 PK가 `(corp_code, fiscal_year, fiscal_period, statement_type)`
하나뿐이고 `is_discrete`/`is_stub`/`version` 컬럼이 없다(§5-a 결정, "정본 행 선택 조건
자체가 불필요"). `derive_quarters_corp()`가 v2에 만들던 "이산분기 레코드"를 v3에도 같은
방식으로 저장하려면 그 설계를 되돌려야 한다 — 바람직하지 않음.

대신 **이산분기를 DB에 저장하지 않고 메모리 dict로만** 만들어 바로
`calendar.py::_cq_record()`/`_cy_record()`에 먹인다 — 최종 저장 대상은
`std_financials_calendar` 하나뿐. `derive_quarters_corp()`의 계산 로직(`_build_discrete()`,
end−sub 차감, flow/stock 분리)과 `calendarize_corp()`의 계산 로직(`_cq_record()`/
`_cy_record()`, native/recomposed 판정)은 둘 다 이미 순수 계산 함수라 **한 글자도 안
바꾸고 재사용 가능** — 바뀌는 건 입력 소스(`std_financials_v2` SELECT → `std_financials_v3`
SELECT)와 중간 저장 단계 제거뿐.

### 1-2. `_QUARTER_SPEC`/`_FLOW_COLS`/`_STOCK_COLS`는 그대로 재사용 가능

`quarterly.py`의 `_FLOW_COLS`/`_STOCK_COLS`는 `_BS_MAP`/`_IS_MAP`/`_CF_MAP`(std_v2 규칙
카탈로그) 값에서 온다. `std_financials_v3`의 코어 컬럼명(§ 앞서 실측: total_assets·revenue·
operating_income 등)이 v2와 동일한 이름 체계를 쓰고 있어 컬럼 교집합만 맞으면 그대로
재사용될 가능성이 높다 — **단, 정확한 컬럼명 1:1 대조는 구현 전 재확인 필요**(v3엔
`capex`/`depreciation`/`amortization`/`da_total`/`ebitda`/`fcf`/`net_debt`가 이미 코어
컬럼으로 있음을 이번 세션에 실측 확인함 — 유리한 신호).

## 2. 구현 표면 (제안)

- 신설: `fin2/standardize/calendar_v3.py`(가칭) 또는 기존 `calendar.py`에 v3 경로 추가 —
  `_load_asfiled_v3()`(std_financials_v3 SELECT, WHERE fiscal_period IN ('Q1','H1','Q3','FY'))
  → `_build_discrete()`(quarterly.py 그대로 재사용, PK 관련 필드만 제거) → `_cq_record()`/
  `_cy_record()`(calendar.py 그대로 재사용) → `std_financials_calendar` upsert.
- 기존 v2 경로(`derive_quarters_corp`/`calendarize_corp`, RuntimeError 가드 상태)는 **삭제
  않고 보존**(과거 검증·재조회 참고용, 이미 죽은 경로라 위험 없음).
- 데일리 배선: `build_corp()`가 끝난 뒤(std_v3 upsert 직후) 새 함수를 호출 — `collect_new.py`
  의 정확한 지점은 [[parser-pipeline-integration-runbook]] 절차대로 구현 단계에서 확정.

## 3. 런북 3층 체크리스트 (CLAUDE.md 필수 절차)

1. **데일리 배선**: `scripts/collect_new.py`의 **두 call site**(메인 경로 +
   `--standardize-only` 재개 경로) 모두에 새 함수 배선 필요.
2. **소급 백필**: 전사 corp × basis 재계산 — 규모 추정 필요(현재 `std_financials_calendar`
   319,694행이 참고 상한, 전사 재빌드는 최근 category-C 백필 실측 기준 2,845초 규모로
   유사할 것으로 추정, 실측 필요).
3. **검증**: (a) 12월결산 native 표본으로 CY flow == 보고 FY 항등식 대조(calendar.py
   docstring이 이미 "공짜 검증"으로 명시), (b) 기존 정지 스냅샷(319,694행)과 신규 재계산
   결과의 회사·연도별 diff로 회귀 없는지 확인, (c) `calendar_orphan_cq` 어서션을 v3 기반으로
   재작성해 재감시 복구, (d) 4개 소비 화면 스모크.

## 4. 열린 질문 — 조사 완료(2026-09-02, 읽기전용, 코드/DB 변경 없음)

1. **컬럼 1:1 대응 — ✅ 완전 일치 확인.** `_FLOW_COLS ∪ _STOCK_COLS`(quarterly.py, 38개
   컬럼) 전부를 `std_financials_v3`의 실제 컬럼 목록과 코드로 집합대조: **차집합 0개**.
   v2에만 있는 `lease_liability`/`borrowings_proceeds`/`borrowings_repaid`(및 PK 성격의
   `version`/`is_stub`/`is_discrete`)는 애초에 quarterly/calendar 로직이 안 쓰는
   컬럼이라 무관. §1-2의 "유리한 신호" 추정이 실측으로 확정됨 — 컬럼 재매핑 작업 불요.

2. **`version` 개념 — ✅ v3 경로엔 불필요, 폐기 권고.** `version=2`는 v2 시대 "Phase C"
   재구축 전략(`scripts/phase_c_rebuild.py`) 전용 — **같은 테이블 안에서 병행행을
   version 플래그로 구분**해 두다가 검증 후 version=1로 스왑하는 방식이었다. `std_
   financials_v3` 자체가 이미 이 패턴을 다른 방식(별도 신규 테이블 + 컷오버)으로
   대체했고 `version` 컬럼 자체가 없다 — v3 경로에선 이 파라미터를 아예 없앤다(장래에
   같은 "안전 재구축" 필요가 생기면 v3 자신의 선례(신규 테이블)를 따르면 됨, row-level
   버전 플래그 부활 불요).

3. **데일리 배선 지점 — ✅ 확정.** `scripts/collect_new.py`의 ④-6 `_sync_std_v3()`
   (표준 std_v3 재빌드) 바로 다음에 새 단계(④-7 가칭)로 건다 — `build_corp()`가 그날
   갱신한 corp만 담긴 `v3_corps`(실패 제외)를 그대로 재사용하면 **그날 실제로 바뀐 기업만
   처리**돼 비용이 자동으로 최소화되고(전사 재계산 아님) 신선도도 당일 확보된다. 런북
   ①에 따라 메인 경로(`v3_agg = _sync_std_v3(v3_corps)` 직후)와 `--standardize-only`
   재개 경로 **두 곳 모두**에 배선해야 함.

4. **전사 백필 규모 — ✅ 실측 완료.** `std_financials_v3` 2,546개사·303,903행(Q1/H1/Q3/FY).
   이산분기 파생 상한이 이 값과 같은 자릿수이고, 현재 정지된 `std_financials_calendar`의
   319,694행과도 규모가 일치(교차검증 정합). 50개사 표본으로 읽기비용 실측(0.34초) →
   전사 외삽 **약 17초**(읽기만). 이 작업엔 XML 파싱이 없어(순수 SQL 읽기 + 산술 +
   upsert) category-C 백필의 build 단계(2,845초, XML 파싱 포함)보다 훨씬 가벼울 것으로
   추정 — 전체 소요 수 분 이내로 예상(직접 실행 전까진 upsert 쓰기비용은 추정치).

## 5. 다음 단계

열린 질문 4개 전부 조사 완료 — **구현을 막는 미지수는 없다.** 구현 착수는 여전히
**별도 승인 필요**(정책). 승인되면 §5 원안 순서(Phase 1 함수 구현 → 표본검증 →
데일리 배선 → 전사백필 → 어서션 복구)대로 진행 권고.
