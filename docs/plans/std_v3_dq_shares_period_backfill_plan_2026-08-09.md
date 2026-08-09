# 계획 — std_v3 미백필 3종(data_quality·period_end·shares_out) 해소 (2026-08-09)

> 상태: **설계 확정 — 실행요청 대기.** [정책](../../CLAUDE.md) 상 계획 작성 후 자동 실행 금지, 별도
> 실행요청 대기. 발견 경로 = C-1 렌더 확인 작업 중([뷰 브리지 swap 계획](layer3_v3_bridge_swap_2026-07-25.md)
> §4 단계 7) 스크리너 population 이상치를 추적하다 발견. 마스터 허브 =
> [rearchitecture_4layer.md](rearchitecture_4layer.md).
>
> **2026-08-09 갱신 — shares_out 방식 확정**: §3.3의 옵션A(계층2 신설, 아키텍처 준수)로 사용자 결정
> (2026-08-09). 실행 체크리스트 = [`std_v3_dq_shares_period_backfill_todo_2026-08-09.md`](std_v3_dq_shares_period_backfill_todo_2026-08-09.md).

## 0. 한 줄 요약
`std_financials_v3`(184,580행, 브리지 swap으로 앱이 이미 이 테이블을 읽는 중)에서
`data_quality`·`period_end`·`shares_out` **3개 컬럼이 전량(100%) NULL**이다. 셋 다
`fin2/layer3/build.py`의 기존 주석("별도 백필 UPDATE, 여기 없음")이 이미 정확히 지목했던
결손인데, 그 백필이 한 번도 구현·실행되지 않았다. `data_quality`는 스크리너가 SQL
`WHERE data_quality < 3`으로 직접 게이팅하므로 **치명적**(NULL 행 전량 조용히 탈락 →
모집단 1,852개사, 정상치 2,520개사 대비 668개사 누락 + 잔존 기업도 옛 std_v2 값으로
조용히 대체). `period_end`·`shares_out`은 상대적으로 경미(표시·주당지표용).

## 1. 증거 (실측, 2026-08-09)

```
std_v3 총 184,580행 중:
  data_quality NOT NULL:  0  (100% NULL)
  period_end   NOT NULL:  0  (100% NULL)
  shares_out   NOT NULL:  0  (100% NULL)
  (참고, 이미 채워진 것: depreciation 149,031·amortization 114,582·da_total 177,873·
   ebitda 177,681·capex 169,237·fcf 168,314·net_debt 127,701 — 다른 enrichment는 정상)
```

**data_quality 필터의 실제 피해** — `analyzer/screener.py:99`(`load_population` 경유),
`app/data/screen_window.py:111,137`(`load_screening_window`)가 `sf.data_quality < 3`을
직접 WHERE에 건다:
- 스크리너 모집단: 1,852개사 (COALESCE 처리 시 기대치 2,520개사, **668개사 누락**)
- 한국캐피탈(credit_finance): 모집단에서 완전히 사라짐
- 기업은행(bank): population 쿼리가 뽑아온 값이 FY2025(연결매출 19.0조)가 아니라 훨씬
  옛 std_v2 잔존행 — 영업이익률 757.6%로 튀는 등 명백히 비정상. `load_screening_window`도
  "최신 매출"로 6,797억(실제 FY2025는 19.0조)을 반환 — **약 28배 축소된 값을 "최신"이라고
  보여줌.**
- 삼성증권(securities): population 값도 window 값도 서로 다른 연도 뒤섞임(4배 이상 괴리).

원인: `standard_financials` 뷰(브리지)가 std_v3 행을 그대로 통과시키는데, v3 행은
`data_quality`가 애초에 NULL로 INSERT됨 → `< 3` 비교가 SQL에서 `NULL`(=falsy)이 되어
**조용히 걸러짐**. std_v2 UNION 쪽만 남아 옛 데이터가 대신 노출된다 — 전형적인
[[layer2-silent-loss-patterns]] 패턴(계층은 다르지만 "필터가 조용히 최신 데이터를 죽이고
옛 데이터로 대체"라는 동일 구조).

## 2. 근본 원인 — 왜 비어있나

`fin2/layer3/build.py::build_corp`는 `_VALUE_COLS`(capex/fcf/net_debt/D&A/ebitda 등)만
계산해 넣고, 아래 3개는 **애초에 컬럼 대입 코드 자체가 없다**(주석만 있음, `build.py:28`,
`combine.py:598,614`):
```python
# shares_out/data_quality 는 여전히 별도 백필 UPDATE(여기 없음).
```
`analyzer/verifier.py:322`의 "fin2 build.py 가 이미 data_quality 를 산출하므로 레거시 DQ
writeback 은 스킵한다"는 주석은 **`fin2/standardize/build.py`(std_v2 빌더)를 가리킨
것**이지 `fin2/layer3/build.py`(std_v3 빌더)가 아니다 — 이름이 같은 두 `build.py`가
혼동을 낳았다. v2 쪽은 실제로 `dq = max(validate_equations(...), _dq_cross_year(...))`를
계산해 넣지만(`fin2/standardize/build.py:468`), v3 쪽엔 그 대응 코드가 없다.

## 3. 설계 — v3-native로 3종 모두 계산 (아키텍처 준수 확인 필요)

### 3.1 `data_quality` — 재사용 가능, 저위험
`fin2/standardize/rules.py::validate_equations(col: dict) -> int`는 **순수 함수**(세션
불필요, BS 항등식·IS gross_profit 항등식만 봄) — `build_corp`의 `col` dict에 그대로
호출 가능. 교차연도 이상치 체크(`fin2/standardize/build.py::_dq_cross_year`, 200x→DQ3·
30x→DQ2)는 `std_financials_v2` 테이블·`version`·`is_stub` 컬럼을 가정하므로 **std_v3용
변형**(`std_financials_v3` 대상, corp_code+statement_type+fiscal_period='FY' 키만 사용)이
필요 — 로직 자체는 동일 이식. `_future_guard`(미래 period_end 방어)도 그대로 이식.

`build_corp`는 기간을 **오름차순**(`_periods` 쿼리 `ORDER BY 1,2`)으로 순회하며 같은
세션 트랜잭션 안에서 delete-then-insert 하므로, 연도 Y의 cross-year 체크 시점에 Y 이전
연도는 이미 이 호출 안에서 커밋 전 상태로 조회 가능(같은 트랜잭션 내 SELECT로 보임) —
**`build_corp` 안에 인라인으로 넣을 수 있다**(v2와 동일 패턴, 별도 백필 스크립트 불필요).

### 3.2 `period_end` — 재사용 가능, 저위험
`fin2/standardize/build.py::_period_end(session, corp_code, fiscal_year, fiscal_period,
rcept)` — ① 원문 filing의 period_end_date(권위) → ② 기업 결산월로 도출 → ③ None. 세션
읽기만 하는 순수 조회 함수, `build_corp`가 이미 갖고 있는 `src`(=`select_canonical_rcepts`
결과)를 그대로 넘기면 됨. **그대로 이식 가능.**

### 3.3 `shares_out` — ★확정: 계층2 신설(옵션 A, 2026-08-09 사용자 결정)
v2의 대응 백필(`scripts/phase_c_rebuild.py::backfill_shares_corp`)은 **사업보고서 원문
XML을 직접 read**해서(`fin2/extract/shares.py::extract_issued_common_shares`) 주식수를
뽑는다. 이 방식을 v3(계층3)에 그대로 재사용하면 **"보고서 직접 read = 계층2 전용" 원칙**
([[architecture-report-read-layer2-only]], 마스터 허브 §6 확정 결정)을 계층3가 위반한다 —
biz_metrics.py가 이미 이 원칙을 위반 중인 것으로 §6에 별도 기록돼 있고, 새 위반을 하나 더
늘리는 셈이라 **채택하지 않는다.**

**확정 설계(계층2 일반현황 전사, `layer2_notes_transcription_2026-07-25.md` §8이 예고한 (b)
옵션)**:
- 발행주식수(주식의 총수)는 재무제표 tree(BS/IS/CF/주석)와 구조가 다른 **일반현황** 섹션
  값이라 `report_lines`(계정×기간 tree)에 억지로 끼워 넣지 않는다. **cross-cutting 별도
  테이블**로 둔다 — `stock_prices`와 같은 성격(계정 tree 밖, corp×시점 스칼라 값).
- **신규 계층2 모듈**: 기존 `fin2/extract/shares.py::extract_issued_common_shares(path)`의
  파싱 로직(이미 검증됨, v2에서 실사용 중)을 **그대로 재사용**하되, 호출 위치를 v2 사후
  백필 스크립트(`phase_c_rebuild.py`)에서 **계층2 추출 파이프라인**(raw XML을 여는 시점,
  `fin2/extract/report_lines.py`와 같은 층)으로 옮긴다 — 파일을 이미 열어 파싱하는 지점에서
  같이 뽑아 별도 테이블에 적재(원문 재오픈 없이 한 번의 read로 report_lines + shares 동시
  산출 가능하면 그쪽이 더 낫다 — 구현 시 확인).
- **신규 테이블**(가칭 `report_shares_outstanding` — 확정명은 구현 시 기존 명명 규칙에 맞춰
  결정): `corp_code · rcept_no · fiscal_year · fiscal_period · shares_out · as_of_date ·
  source_ref`. filing 단위로 적재(같은 회사 다른 filing이 다른 시점 주식수를 보고할 수 있음
  — 정본선택은 계층3 소관 원칙과 동일하게 계층3가 corp+fy+period당 대표값 선택).
- **계층3(`build_corp`)는 이 신규 테이블만 읽는다**(원문 read 없음) — 정본 filing
  (`select_canonical_rcepts` 이미 갖고 있는 rcept)에 대응하는 행을 조인해 `shares_out` 채움.
- 소급 백필은 [[parser-pipeline-integration-runbook]] 체크리스트 B(전 filing 재파싱)를 그대로
  적용 — v2 시절처럼 "매 rebuild마다 재실행" 패턴이 아니라 **계층2 적재이므로 한 번 백필하면
  끝**(report_lines과 동일 성격, 데일리 파이프라인 배선 후엔 신규 filing에 자동 적재).

## 4. 구현 순서 (승인 시)
1. `fin2/layer3/build.py`에 `_dq_cross_year_v3`(std_v3 대상 이식) + `_future_guard` 이식,
   `build_corp`의 각 (fy, basis) 완성 시점에 `data_quality` 계산해 `row.data_quality = dq`.
2. 같은 지점에 `_period_end` 이식 호출 → `row.period_end = period_end`.
3. **계층2 shares 전사 신설**(§3.3 확정 설계): 신규 테이블+모델, 신규 추출 모듈(기존
   `extract_issued_common_shares` 재사용), `collect_new.py` 두 call site 배선([[parser-pipeline-integration-runbook]]),
   과거 전 filing 소급 백필. → 완료 후 `build_corp`가 이 테이블을 조인해 `shares_out` 채움.
4. `build_std_v3.py --all` 전량 재빌드(계획서 참고 소요 ~25분) — data_quality·period_end·
   shares_out 동시 채워짐(shares_out은 3단계 백필이 먼저 끝나 있어야 함).
5. **검증**:
   - `std_v3 count(data_quality IS NOT NULL)` = 전체 행수 일치 확인.
   - 스크리너 모집단 재확인: `load_population()` 개수가 1,852→~2,520 근접 확인.
   - 기업은행·삼성증권·한국캐피탈 재확인: population/window 값이 §1 표 원문(FY2025 실제
   값)과 일치하는지 재대조.
   - **오탐 방지**([[feedback-verify-against-source]])**: DQ=3(오류) 판정이 실제 이상치
   원문과 일치하는 표본 확인** — 전부 DQ=1로 깔아버리는 게 아니라 진짜 이상치가 잡히는지
   (v2 시절 알려진 사례, 예: 경농 2024·농심 2018)도 std_v3 쪽에서 같은 방식으로 잡히는지
   교차 확인.
   - Gate B(`line_value_diff`) 무관 확인(값 컬럼 변경 없음, 메타 컬럼만 채움 — 회귀 없어야
   정상).

## 5. 확정 사항 (2026-08-09)
- **shares_out**: 옵션A(계층2 신설, 아키텍처 준수) 확정. §3.3 설계대로 진행.
- data_quality·period_end: 재사용 이식, 저위험 — 별도 결정 불요.

## 6. 다음 액션
실행 체크리스트 = [`std_v3_dq_shares_period_backfill_todo_2026-08-09.md`](std_v3_dq_shares_period_backfill_todo_2026-08-09.md).
사용자 실행 승인 후 그 문서 순서대로 착수.
