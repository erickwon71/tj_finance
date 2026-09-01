# fact_v2 / std_financials_v2 폐기(GC) 트랙 — 범위 정리 및 단계 계획 (2026-09-01)

★이 문서는 **범위 정리(스코핑) 전용**이다. 구현은 포함하지 않는다 — 어느 하위 단계를
착수할지는 이 문서를 검토한 뒤 사용자가 별도로 결정한다(`CLAUDE.md` "계획 후 대기" 정책).

## 0. 배경 — 왜 지금 이 트랙인가

[[generation-unification-layer2-layer3-2026-08-30]]에서 방향은 이미 확정됐다: 계층2·계층3
모두 신세대(`report_lines`/`std_financials_v3`) 단일화, 구세대(`fact_v2` 55GB /
`std_financials_v2` 633MB) 이중 적재·관리 금지. `net_debt`/`valuation_daily` 이식
대작업(R57~R60)이 2026-09-01 기준 전부 완전 종료됐고, 그 설계 문서(`std_v3_daily_wiring_plan_
2026-08-30.md` §8)가 이 GC를 "이 문서 이후의 후속" 항목으로 이미 나열해 뒀다 — 이 문서는
그 나열을 실행 가능한 단계 계획으로 구체화한다.

## 1. 이미 확정된 전제 (재확인 불필요)

| 항목 | 상태 | 근거 |
|---|---|---|
| `std_financials_v2` 신규 쓰기 | 중단됨(Phase 2, `e6d1692`) | [[std-v3-daily-wiring-and-valuation-migration-2026-08-30]] |
| `valuation_daily` matview | v3 기반으로 완전 이식 | [[valuation-daily-order5-netdebt-v3-migration-2026-08-31]] |
| `gateb_audit.py` | `source="v3"` 전 구간 이미 지원 | `std_v3_daily_wiring_plan_2026-08-30.md` §1-3 |
| `statement_source`(`fin2/reconcile.py`) | v3는 `source_rcepts`로 이미 자체 해결 | 상동 §8 |
| D&A 결합공시+별도계상분 | v3 `note_da.py`에 이미 구현됨(이식 불필요로 확인, 2026-09-01) | `std_v3_daily_wiring_plan_2026-08-30.md` §8(정정 완료) |

## 2. 실측 — 활성 소비자 인벤토리(2026-09-01)

`scripts/`·`fin2/tests/`·`scripts/archive/`(1회성 진단/과거 백필 스크립트)를 제외한
**실제 프로덕션 경로**만 추린 결과:

### 2-1. `std_financials_v2` 활성 소비자

| 파일 | 용도 | 이식 난이도 |
|---|---|---|
| `app/data/extended.py::load_extended_all` | `extended_financials` 조회 결과에 `period_end` 조인(정렬용) | 낮음 — v3에 동등 컬럼 있으면 단순 테이블명 교체 |
| `app/data/shareholder_return.py::load_dividend_series_for_chart` | 동일 패턴(`period_end` 조인) | 낮음 |
| `app/data/collect.py` | 데일리 상태 표시용 `count(DISTINCT corp_code)` | 낮음 — 표시용, D0(셀렉터 전환)에서 이미 실측된 v3 카운트로 교체 가능 |
| `fin2/standardize/build.py`·`rules.py`·`quarterly.py`·`calendar.py` | **std_v2 자체의 조립 파이프라인**(쓰기 로직) | 해당 없음 — Phase 2로 이미 죽은 경로, 드롭 시 파일째 정리 대상이지 "이식" 대상이 아님 |

★확인 완료(§5-a) — `extended.py`/`shareholder_return.py` 두 곳 모두 조인 조건에
`s.version = 1 AND NOT is_stub AND NOT is_discrete`를 걸지만, `std_financials_v3`는
PK가 `(corp_code, fiscal_year, fiscal_period, statement_type)` 하나뿐이라 이 조건군 자체가
불필요하다 — 통째로 삭제하고 `s.corp_code=…AND s.fiscal_year=…AND s.fiscal_period='FY'
AND s.statement_type=:basis` 등치 조인으로 바꾸면 끝(§5-a 상세 참고). **이식 난이도가
"확인 필요"에서 "낮음, 조치 확정"으로 격상.**

### 2-2. `fact_v2` 활성 소비자

| 파일 | 용도 | 이식 난이도 |
|---|---|---|
| `fin2/audit/line_audit.py` | **Gate B Phase B** — 원문 face 라인 vs `fact_v2` acode 정확매칭(Track A) / 라벨-값집합 대조(Track B) | **높음** — Gate B 신뢰성의 핵심 감사 리더. `report_lines`/`note_lines`엔 `acode`가 없다(`adecimal`만 있음). `face_audit.read_report_face_xbrl()`이 이미 감사 시점에 원문 XML에서 직접 읽는 선례가 있어 그 패턴을 따를 여지는 있으나, Track A/B 로직 전체 재설계가 필요 |
| `extended_financials` 뷰 | `canonical_account` 조회. 뷰 정의는 `collector/db.py`(`"2026_07_extended_financials_view_distinct"`)에 있음, §5-b에서 원문 확인 완료 | **미해결 설계 질문**(§8 원문 그대로, §5-b로 재확인) — `report_lines`/`note_lines`엔 `is_dimensional`도 `canonical_account`도 없다(확인됨) — acode 기반이 아니라 라벨 기반으로 재구성해야 함 |
| ~~`app/registry/dividend.py`~~ | ~~배당 관련 조회~~ | **해당 없음**(§5-c 확인 완료) — docstring 언급뿐, 실제 fact_v2 읽기 없음. 표에서 제외 |
| `fin2/reconcile.py` | `statement_source` 선택 | 낮음 — v3는 이미 자체 해결(§1), 소비처 확인만 |
| `fin2/extract/*.py`(`notes.py`/`report_lines.py`/`xbrl.py`/`text.py`/`pdf.py`/`statement_titles.py`) | fact_v2로의 **쓰기**(추출 파이프라인 본체) | 해당 없음 — 드롭 시 이 쓰기 경로 자체를 끄는 게 목적이지 "이식"이 아님 |

## 3. `std_financials_v2`/`std_financials_calendar` 드롭까지 남은 계층3 축 작업 (§8 원문 재정리)

1. `std_financials_v3` 결측 백필(fy≥1999) — ★§5-1로 재확정: 16,617행 중 **4,366행만
   백필 가능**(설계 완료, §5-1 참고), 나머지 12,149행은 2026-07-30 "당기만 적재" 정책의
   의도된 결과라 영구 갭(정책을 뒤집지 않는 한 배치로 못 채움)
2. pre-1999 249행 정책 결정 — **범위 밖, 별도 트랙**(§6 후보 D)
3. 이산분기·달력 기능 — Phase 2에서 **신규 기간 생성만 중단**(D1-b, 기존 데이터는 유지).
   ★§5-d 정정: `calendar_financials` 뷰를 통해 스크리너·시계열·회사페이지가 **현재도
   실사용 중** → 폐기 불가, GC하려면 그 4개 소비자를 v3 기반으로 먼저 이식해야 함(별도
   트랙, 미착수)
4. §2-1의 소비자 3곳 이식 — **조건 확정됨(§5-a), 착수 가능**
5. ~~뷰의 v2 UNION 브랜치 제거~~ — **완료(2026-09-01)**. 사용자가 12,149건(§5-1) 영구
   손실을 감수하기로 결정. `standard_financials` 뷰를 `std_financials_v3` 단일 소스로
   재정의(마이그레이션 `2026_09_std_financials_v2_drop`, `collector/db.py`).
6. ~~`std_financials_v2` DROP~~ — **완료(2026-09-01)**. 386MB 회수(계산해보니 애초 추정
   633MB는 v2+calendar 합산이었음 — calendar 247MB는 아래 이유로 **드롭 안 함**). 백업:
   `/Volumes/tj_finance_data/db_backup/std_financials_v2_backup_2026-09-01.dump`(pg_dump -Fc, 복원 가능).
   ★`std_financials_calendar`는 **드롭하지 않음** — 실행 직전 재확인 결과 `calendar_
   financials` 뷰를 통해 `app/data/screen_window.py`·`series.py`·`quarter_change.py`·
   `app/views/company_page.py`가 **현재도 실사용 중**(이산분기 CQ1~CQ4 스크리너/시계열/
   회사페이지)이라 §5-d의 "사용자 노출 없음" 결론이 **틀렸음이 드러남**(정정: §5-d는
   `is_discrete`/"이산분기" 텍스트만 grep했지 파생 뷰명 `calendar_financials`를 놓쳤다 —
   교훈, 아래 실행결과 참고).
   ★★부수 발견(DROP 실행 중): `collector/cf_da_sync.py`·`expense_nature_sync.py`(매일
   18:00 `collect_new.py`가 부르는 실사용 코드)와 `scripts/dq_assertions.py`(매일 20:30
   `dq_nightly.py`가 부르는 실사용 코드, launchd 스케줄)가 std_financials_v2 를 **읽고
   있었다** — §2-1 조사 때 "죽은 std_v2 파이프라인"으로 뭉뚱그려 놓쳤던 부분. DROP
   실행 직후 전부 v3로 이식 완료(같은 세션, 상세 아래). `scripts/gateb_audit.py`의
   `--source` 기본값도 `v2`였던 것을 `v3`로 전환(v2 선택지 자체를 제거, 수동 실행 시
   과거 습관으로 인자 생략해도 에러 안 나게).

   **검증**: `python scripts/dq_assertions.py` 전체 실행 완료(exit 0, 크래시 없음).
   `calendar_orphan_cq` 어서션 1건만 SKIP — 이건 의도된 결과다: 그 술어(`diag_calendar_
   orphans.py::_ORPHAN_PRED`)가 "달력분기에 대응하는 **이산분기**(v2 `is_discrete`)가
   있는가"를 묻는데, 이산분기 생성 자체가 Phase 2(2026-08-30)에 이미 멈춰서 이 검사의
   전제(그 write 경로가 살아있다)가 v2 DROP 이전부터 이미 깨져 있었다 — v3엔 애초에
   `is_discrete` 개념이 없어 포팅할 대상이 없다(§3-3 이산분기·달력 트랙과 함께 재설계
   전까지 SKIP 유지가 맞다, 기존 코드의 "레거시 테이블 드롭 시 건너뛰기" 방어 설계
   그대로 동작). 나머지 21개 어서션은 전부 정상 실행(ERROR 위반 1건=`statement_
   magnitude_impossible` 150건, WARN 다수 — **전부 std_v3 데이터 자체의 기존 품질
   이슈**이지 이번 DROP으로 생긴 문제가 아님. 특히 `statement_magnitude_impossible`은
   이 어서션이 지금까지 std_v2 를 봐 왔어서 몰랐던 **v3 쪽 신규 가시성**일 수 있음 —
   표본 확인(00366942 FY2004H1 등, 이익잉여金 9,950조원류 명백한 단위오염) 진짜 문제로
   보임, 이번 트랙 범위 밖이라 별도 백로그로 남김).

## 4. `fact_v2` 드롭까지 남은 계층2 축 작업 (§8 원문 재정리)

1. `fin2/reconcile.py` 소비처 확인 — 낮은 리스크
2. `extended_financials` 뷰 라벨 기반 재설계 — **완료(2026-09-01, §4-2)**, 커밋 `243e9ee`
3. `line_audit.py`(Gate B Phase B) 이식 — **완료(2026-09-01, §4-3)**. 별도 설계 문서
   (`docs/plans/gateb_phaseb_line_audit_v3_migration_design_2026-09-01.md`, Phase 0~5)로
   분리해 진행 — 게이트1(라벨 매칭률 95% 목표, 실측 100.00%), 전수재감사(개선 14,014 :
   악화 209 = 67:1), Phase A(`gate_status`) 무영향 확인까지 전부 통과. 과정에서 발견한
   Track A/B 감사리더 진짜 버그 3종은 `docs/PARSING_RULES.md` R61에 등재. 데일리 알림도
   절대치→어제 대비 신규증가분(delta) 기준으로 재설계(4-6, `scripts/collect_new.py`) —
   Phase 4가 확정한 잔존 배경잡음(209건) 재발화 문제 해소. 상세 [[gateb-phaseb-line-audit-migration-phase0-1-2026-09-01]]
4. `fact_v2` DROP — 55 GB 회수, 위 전부 끝난 뒤. **잔여 블로커**는 마이그레이션 설계문서
   §7 참고(`cf_da_sync.py`/`expense_nature_sync.py`의 fact_v2 upsert 2건이 핵심 블로커)

## 5. 실측 갭 — 채움 완료 (2026-09-01)

### (a) v3의 "정본 FY 행 하나" 조건 — ★결론: 별도 조건 자체가 불필요

`\d std_financials_v3`로 확인: PK가 `(corp_code, fiscal_year, fiscal_period,
statement_type)`뿐이다. `version`/`is_stub`/`is_discrete` 컬럼이 **아예 없고**, 구조상
한 (corp,fy,fp,basis)에 행이 정확히 0개 또는 1개다 — v2처럼 "여러 후보 중 정본 하나를
골라야 하는" 문제 자체가 성립하지 않는다. 실제로 `valuation_daily` matview(§Phase 0-2
설계문서, D1)도 `fin.` LATERAL 서브쿼리에서 `is_stub`/`is_discrete` 필터를 **전혀 안 쓴다**
(`period_end<=trade_date` + `ORDER BY period_end DESC, (consolidated 우선)` 뿐). §2-1의
소비자 3곳도 이 패턴을 그대로 따르면 된다 — `s.version=1 AND NOT is_stub AND NOT
is_discrete` 조건은 통째로 삭제하고 `fiscal_period='FY' AND statement_type=:basis`
등치 조인으로 바꾸면 끝. ★새 우려는 없다.

### (b) `extended_financials` 뷰 정의 위치 — 확인 완료

리포지토리 `migrations/` 디렉터리는 없다 — 이 프로젝트의 마이그레이션은
`collector/db.py`의 이름 붙은 구문 리스트(`("2026_07_extended_financials_view", …)`
형태, 멱등 `CREATE OR REPLACE`)로 관리된다. 최신 버전(`2026_07_extended_financials_view_
distinct`)은:

```sql
CREATE OR REPLACE VIEW extended_financials AS
SELECT f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
       f.canonical_account, SUM(DISTINCT f.amount_won) AS amount_won,
       COUNT(DISTINCT f.amount_won) AS n_facts, ss.source_rcept_no
FROM statement_source ss
JOIN fact_v2 f ON f.rcept_no = ss.source_rcept_no
  AND f.corp_code = ss.corp_code AND f.report_fiscal_year = ss.fiscal_year
  AND f.report_fiscal_period = ss.fiscal_period AND f.basis = ss.basis
WHERE NOT ss.is_stub AND f.col_index = 0 AND NOT f.is_dimensional
  AND f.canonical_account IS NOT NULL AND f.amount_won IS NOT NULL
  AND ( CASE left(f.canonical_account,3) WHEN 'bs.' THEN 'BS' WHEN 'is.' THEN 'IS'
          WHEN 'cf.' THEN 'CF' END = ss.statement
        OR (f.canonical_account LIKE 'note.%' AND ss.statement='IS') )
GROUP BY f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
         f.canonical_account, ss.source_rcept_no
```

`\d report_lines`/`\d note_lines`로 대조 확인: 두 테이블 다 `col_index`는 있지만
**`is_dimensional`도 `canonical_account`도 없다**(`§2-2`의 "미해결 설계 질문" 서술이
정확했음, 재확인만 됨). 라벨 기반 재구성이 실제로 필요하다 — `account_mapper`를
`label_raw`에 감사 시점(read-time)에 돌리거나(선례: `face_audit.read_report_face_
xbrl()`), 혹은 layer3 빌드 시점에 canonical을 별도 인덱스 테이블로 미리 적재해두는 두
방향 중 하나를 다음 설계에서 고를 것.

### (c) `app/registry/dividend.py`의 fact_v2 의존 — ★결론: 의존 없음(오탐)

`grep -n "fact_v2\|import"` 결과 실제 코드에서 fact_v2를 참조하는 줄이 **없다** — 파일
상단 docstring 한 줄(`"EXTENDED_CATALOG(fact_v2 기반 확장 재무항목)와 별개 테이블..."`)이
`app/data/extended.py`와 대비 설명하려고 언급한 것뿐이다. §2-2 표에서 이 행 제거.
실제 배당 소비자는 `app/data/shareholder_return.py`(§2-1에 이미 포함)뿐이다.

### (d) 이산분기·달력 기능의 실사용 여부 — ★★★정정(2026-09-01): 이 결론은 틀렸다

**최초 결론(아래 원문 보존, 오류 사례로 남김)**: "`app/`, `analyzer/` 전체에서
`std_financials_calendar`/`is_discrete`/`분기` 텍스트를 스캔한 결과, 실제로 그 데이터를
읽어 화면에 그리는 코드는 없다... '기능 자체를 폐기' 쪽이 유력하다."

**★정정(§6-3 DROP 실행 직전 `pg_depend`로 재확인하다가 발견)**: 텍스트 grep이
`std_financials_calendar`라는 **테이블명**만 찾았지, 그 위에 얹힌 **파생 뷰명**
`calendar_financials`는 안 찾았다(이름이 다름). `pg_depend`로 실제 DB 의존관계를 보니
`calendar_financials` 뷰를 `app/data/screen_window.py`(스크리너 분기윈도우)·
`app/data/series.py`(분기 이산 시계열)·`app/data/quarter_change.py`(전기대비 분기변화)·
`app/views/company_page.py`(회사 상세페이지)가 **전부 실사용 중**이다 — 이산분기
CQ1~CQ4 기능은 죽지 않았다. → **`std_financials_calendar`는 드롭 대상에서 제외**,
§3-3 정책 결정은 "폐기 유력"이 아니라 **"유지 필요, GC하려면 소비자 4곳의 v3 이식이
먼저"**로 뒤집힌다(별도 트랙, 이번 세션엔 착수 안 함).

**교훈**: 어떤 기능이 죽었는지 판단할 때 **원 테이블명 텍스트 grep만으로는 부족하다** —
그 위에 얹힌 뷰가 다른 이름을 쓰면 놓친다. 반드시 `pg_depend`(또는 `pg_get_viewdef`
전수 스캔)로 실제 DB 의존관계를 확인해야 한다. 이번엔 DROP 직전에 다시 확인하는
습관 덕에 사고를 막았지만, 원래 §5 단계에서 잡았어야 할 오류였다.

### (e) v3 결측 16,617행 재실측 — ★결론: 2026-08-30 대비 변화 없음(16,617 그대로)

```sql
SELECT count(*) FILTER (WHERE s.fiscal_year>=1999) AS gap_ge_1999,
       count(*) FILTER (WHERE s.fiscal_year<1999)  AS gap_lt_1999
FROM std_financials_v2 s
WHERE s.version=1 AND NOT COALESCE(s.is_stub,false) AND NOT COALESCE(s.is_discrete,false)
  AND NOT EXISTS (SELECT 1 FROM std_financials_v3 v3b
                  WHERE v3b.corp_code=s.corp_code AND v3b.fiscal_year=s.fiscal_year
                    AND v3b.fiscal_period=s.fiscal_period AND v3b.statement_type=s.statement_type);
```
→ **16,617(fy≥1999) / 249(fy<1999) / 합계 16,866 — 2026-08-30 실측치와 원 단위까지 동일.**
D0가 기대했던 "셀렉터를 v3 기준으로 바꾸면 데일리가 점진적으로 이 갭을 갉아먹는다"는
효과가 **이 2일 창에서는 전혀 관측되지 않았다** — self-healing은 *신규 공시가 있는*
기업만 건드리므로, 오래된 gap 자체(대부분 과거 신고 완료 기업)는 daily가 능동적으로
줄이지 못한다는 게 재확인됐다(짧은 관측창이라 결정적이진 않지만, 방향은 문서 원안과
일치 — **통제된 배치 백필이 실제로 필요**).

연도별 분포(fy≥1999, 27개 연도 전부 존재 — 특정 연도 급증이 아니라 넓게 퍼져 있음):
2000~2003(연 1,000~1,400건, XBRL 이전/과도기 구간)이 가장 두껍고, 2004년 이후는 연
350~860건 수준으로 완만. 2025년만 118건으로 작다(연중이라 당연).

## 5-1. §6-3 원인규명(2026-09-01) — ★"16,617행 백필"은 잘못된 전제였다

착수 전 "왜 v3에 없는가"부터 규명했다(읽기 전용, 코드/DB 변경 없음). 결론: **16,617건 중
실제로 백필 가능한 건 4,366건(26%)뿐이고, 나머지 12,149건(73%)은 v3의 기존 설계 결정에
따른 의도된 결과라 배치 백필로 채울 수 없다.**

### 원인 분해

```sql
-- gap = std_v2에 있고 v3에 없는 (corp,fy,fp,basis), report_lines에도 해당 키가 없는 행
```
| 카테고리 | 건수 | 비율 | 원인 |
|---|---:|---:|---|
| **A. 필링 자체가 없음** | 12,149 | 73% | 아래 참고 — **의도된 설계, 백필 불가** |
| **C. 다운로드는 됐는데 계층2 추출이 전혀 안 됨** | 4,366 | 26% | 진짜 백로그 — **백필 가능** |
| D. basis 일부만 추출 | 22 | <1% | 미미, 후순위 |

### A(73%) — `report_lines`의 "당기만 적재" 정책(2026-07-30 기결정)의 직접 결과

표본 확인(센서뷰 `01593668` FY2021 연결): `std_financials_v2`의 FY2021 행은
`bs_rcept=20240319000506`(2024-03-19 제출, **FY2023 사업보고서**)를 소스로 갖는다 — 즉
v2는 FY2023 보고서 안의 **3개년 비교표시 열(전전기=FY2021)**을 읽어 FY2021 행을 만들었다.
그런데 `report_lines`는 `fin2/extract/report_lines.py:1199`의 명시적 정책
(`"적재 대상인가 — 당기(col_index=0)만 DB로 옮긴다(사용자 결정 2026-07-30)"`)에 따라
**당기 열만 저장**하고 전기·전전기 비교열은 `context_fiscal_year=NULL`로 버려둔다("이전
기간은 그 기간의 보고서에서 온다"는 게 이 정책의 전제). 전수 확인: A 12,149건 **전건**이
"해당 회사의 더 늦은 필링에 미해결(context_fiscal_year IS NULL) 비교열이 존재"하는
패턴과 일치한다 — 즉 이 회사들은 그 연도 자체의 **단독 필링이 아예 없고**(상장 시점이
늦거나 첫 정기공시 이전 연도), v2는 비교열 복원으로 메웠지만 v3는 정책상 안 한다.
→ **이건 v3의 버그도 아니고 "덜 된 백필"도 아니다.** 2026-07-30 정책을 뒤집지 않는 한
배치 작업으로 채울 방법이 없다 — 뒤집을지는 이 문서 범위 밖의 별도 결정(정책 재검토
자체가 note_periods 급의 새 설계 작업).

### C(26%, 4,366건/922개사/4,799 rcept, 전부 fy≤2017) — 진짜 백필 대상

표본 확인(`00148832` FY2007 연결): 필링 4건 전부 다운로드 완료(xml)인데 `report_lines`가
그 연도 전체에 대해 **0행** — 계층2 추출 자체가 이 필링들에 한 번도 안 돌았다(2026-07-31
이전에 다운로드된 오래된 필링들이 그 이후 배선된 데일리 증분 경로를 못 탄 전형적 사례,
[[parser-pipeline-integration-runbook]] ②와 같은 패턴).

**이식 도구는 이미 있다** — 신규 코드 불필요: `collector/note_lines_sync.py::
sync_layer2_lines(corps=[...], year_min=1999)`가 정확히 "다운로드는 됐는데 아직
report_lines/note_lines에 없는 rcept"만 골라(멱등, corp 바운드) 추출·적재한다. 이 922개사
목록만 넘기면 끝 — 이 함수가 자연스럽게 해당 4,799개 rcept를 대상으로 잡는다(더 넓게도
잡을 수 있음 — 같은 회사의 다른 미적재 필링도 같이 메워짐, 부수 이득).

### 제안 실행 계획(승인 대기, 미실행)

1. `sync_layer2_lines(corps=<922개사>, year_min=1999)` 호출 — `report_lines`/`note_lines`
   증분 적재(멱등, delete-then-insert 단위=rcept라 안전)
2. 영향받은 922개사만 `build_std_v3`(또는 `build_corp` 루프)로 std_v3 재빌드 — 전사가
   아니라 **이 922개사로 스코프 한정**(R60류 90분 전수재감사와 무관하게 훨씬 작음)
3. 검증: (a) 재실측 쿼리로 category C 잔여 0건 확인 (b) 이 922개사만 `gateb_audit.py
   --source v3`로 국소 재감사(pass→fail_a 전이 0 확인) (c) 표본 3~5건 원문대조
4. 규모가 작아(4,366행, pre-2017) 데일리 배선(runbook ①) 은 불필요 — 이미 daily가
   신규분은 `_sync_layer2_lines`로 자연히 처리 중(§1 표 "std_v2 신규 쓰기 중단" 참고).
   이건 **일회성 과거분 백필**로 충분.

리스크는 낮다 — 순수 additive(기존 std_v3 행을 건드리지 않고 빈 자리만 채움),
`sync_layer2_lines`/`build_corp` 둘 다 기존에 검증된 멱등 함수를 그대로 재사용.

### ★실행 결과(2026-09-01) — 완주했지만 gap 순감소 0건. category C는 더 깊은 문제였다

`scripts/backfill_stdv3_gap_category_c_2026-09-01.py` 실행(sharding 없이 단일 프로세스,
계층2 전사 1,251s + std_v3 build 2,845s, 실패 0건). 사후 재실측: **gap 총량 16,617 →
16,617(불변)**, category C 4,366 → 4,366(불변). Gate B 회귀 없음(사전 스냅샷 164,995건
대조, gate_status 전이 0건 확인) — 그러나 애초에 새로 쓴 게 없어 회귀도 없을 수밖에 없었다.

**원인**: `sync_layer2_lines`가 처리한 필링 13,249건 중 **13,223건(99.8%)**이
`extract_report_lines()`의 `_detect_body_statement_tables`(pre-2015는
`_detect_pre2015_body_statement_tables_merged`)에서 **"본문 섹션 없음 → 빈 결과(보류)"**
로 끝났다 — 표(BS/IS/CF) 자체를 못 찾아 본문 행을 하나도 못 만든 것이다(주석은 52,137행
성공적으로 적재됨 — note_lines 커버리지는 순증했지만 std_v3 BS/IS/CF 컬럼과는 무관).
표본 확인(`20000110000001`, 한솔전자 FY1999 H1): 파일 자체가 22KB짜리 구형 DART
`<DOCUMENT>` 포맷(XBRL 이전, ACODE 태그 요약정보 위주) — 지금 파서의 표 탐지 로직이
이 시대 포맷의 재무제표 표를 인식 못 한다.

→ **category C(4,366건)는 "추출이 안 도는 백로그"가 아니라 "이 시대 포맷을 파서가
아예 못 읽는" 구조적 한계였다.** `sync_layer2_lines`/`build_corp` 재사용만으로는 못
고친다 — `_detect_pre2015_body_statement_tables_merged`(또는 그 이전 단계)의 표 탐지
로직 자체를 이 포맷 변종까지 넓히는 **별도 파서 작업**이 필요하다. 이미 완료된
"pre-2015 2차패스"([[pre2015-layer2-backfill-plan-2026-08-10]], 81,660행 백필)와
"PDF-only 3차패스"([[pdf-only-parser-plan-2026-08-11]])가 같은 시대(1999~2010년대 초)를
다뤘던 트랙이라 — 이번 4,366건이 그 두 트랙이 이미 커버한 포맷들과 어떻게 다른지부터
확인해야 새 파서 작업 범위를 잡을 수 있다(이번 세션에서는 미착수 — 표 하나 원문 확인
까지만 했음). **부수 이득**: note_lines 52,137행은 순증(과거 주석 커버리지 개선, 주석
소비 경로에는 유효).

**결론: C(4,366건) 백필은 "기존 도구 재사용"으로 안 끝났다.** 진짜로 닫으려면 파서
표 탐지 로직을 조사·확장하는 새 R-트랙이 필요 — 이번 세션 범위 밖, 사용자 결정 대기.

## 6. 권장 착수 순서 (낮은 리스크 → 높은 리스크)

1. ~~§5의 실측 갭(a)~(e) 먼저 채운다~~ — **완료(2026-09-01, 전부 읽기 전용, 코드/DB 변경 없음)**
2. ~~§2-1 소비자 3곳 이식~~ — **완료(2026-09-01)**. `app/data/extended.py`·
   `app/data/shareholder_return.py`: `JOIN std_financials_v2 s ... AND s.version=1 AND
   NOT is_stub AND NOT is_discrete` → `JOIN std_financials_v3 s`(조건 삭제, §5-a대로).
   `app/data/collect.py::collection_status()`: 상태표시 `std_corps` 카운트 소스를 v2→v3로.
   전환 전후 조인 커버리지 실측: `extended_financials` FY키 54,623건 중 v2 54,600건(99.96%)
   → v3 54,619건(99.99%, 소폭 개선), `dividend_facts` FY(연결) 23,147건 중 v2 19,340건
   (83.5%) → v3 23,139건(99.97%) — **v2 시절 조용히 빠지던 배당 차트 데이터 약 3,800건
   복구**(회귀 아니라 부수 개선). psql로 신규 쿼리 직접 실행해 결과 정상 확인(00126380
   표본). 테스트 커버리지 없음(얇은 조회 레이어) — `py_compile` 통과만 확인.
3. §3-1 v3 결측 백필 — ★§5-1로 범위 재확정: 16,617행 중 **실제 백필 대상은 4,366행뿐**
   (922개사, 설계 완료·승인 대기). 나머지 12,149행은 2026-07-30 정책의 의도된 결과라
   배치로 못 채움(별도 정책 재검토 없이는 영구 갭) — 249행(pre-1999, §6 후보 D)과 같은
   성격의 "영구 커버리지 한계"로 재분류
4. §3-3 이산분기·달력 정책 결정(사용자) — 실사용 없음 확인됨(§5-d), 판단은 쉬워짐
5. §3-5~6 뷰 정리 + `std_financials_v2`/`calendar` DROP(633MB 회수) — **여기서 1차 완결점**
6. §4-1 reconcile.py 확인 → §4-2 extended_financials 뷰 재설계(**완료**, 커밋 `243e9ee`)
   → §4-3 line_audit 이식(**완료**, 별도 설계문서로 진행) → §4-4 `fact_v2` DROP(55GB
   회수) — **잔여 블로커**: `cf_da_sync.py`/`expense_nature_sync.py`의 fact_v2 upsert
   (마이그레이션 설계문서 §7 참고, note.* 2종이 여전히 fact_v2에 적재 중이라 이 두
   경로부터 해소해야 DROP 가능)

★2와 5 사이가 리스크 낮은 "계층3 GC"로 한 트랙, 6이 리스크 높은 "계층2 GC"로 별도 트랙 —
**두 트랙을 하나로 묶지 말 것**을 권고한다(Gate B 감사 리더가 걸린 6은 특히 신중하게).

## 7. 참고

- `docs/plans/std_v3_daily_wiring_plan_2026-08-30.md` §8 — 원 백로그 표(이 문서가 구체화한 원본)
- [[generation-unification-layer2-layer3-2026-08-30]] — 방향 확정 근거
- [[valuation-daily-order5-netdebt-v3-migration-2026-08-31]] — `is_stub`/`is_discrete` 없이 정본 FY 행을 뽑은 선례(§5-a에서 재사용 검토)
- `docs/plans/gateb_phaseb_line_audit_v3_migration_design_2026-09-01.md` — §4-3(line_audit
  이식) 구체화 설계·실행 기록(Phase 0~5 전부). `docs/PARSING_RULES.md` R61 — 이식 과정에서
  발견한 Track A/B 감사리더 버그 3종. [[gateb-phaseb-line-audit-migration-phase0-1-2026-09-01]]
