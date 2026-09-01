# fact_v2 GC — `cf_da_sync.py`/`expense_nature_sync.py` 이식 설계 (2026-09-01)

상위 문서: `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §4 항목4,
`docs/plans/gateb_phaseb_line_audit_v3_migration_design_2026-09-01.md` §7
(§4-4 `fact_v2` DROP 잔여 블로커로 이 두 파일을 지목한 실측).

## 0. 결론 선행

이 트랙은 애초 프레이밍("이식만 하면 됨")보다 심각하다. 코드를 직접 추적한 결과 —

1. **`cf_da_sync.py`가 매일 쓰는 `fact_v2` 값(`note.depreciation`/`amortization`/
   `rou_depreciation`/`da_total`)은 2026-09-01 `std_financials_v2` DROP 이후로
   이미 아무도 읽지 않는 죽은 쓰기다.** 유일한 소비자였던
   `fin2/standardize/build.py::standardize_corp()`는 지금 `RuntimeError` 가드로
   막혀 있고(`build.py:327`), v3 쪽 D&A 계산(`fin2/layer3/note_da.py`)은
   `fact_v2`를 아예 읽지 않는다(`note_lines`만 읽음). 매일 밤 `fact_v2`에 새 행이
   쌓이지만 어디에도 반영되지 않는다.
2. **`expense_nature_sync.py`가 쓰는 `note.employee_benefits`/
   `note.raw_materials_used`(EXTENDED_CATALOG 등재 항목, "종업원급여(비용성격)"/
   "원재료 사용액(비용성격)")는 §4-2 `extended_financials` 뷰 재설계(commit
   `243e9ee`) 이후 이미 앱에서 조용히 사라진 상태다.** 뷰가 `fact_v2` 대신
   `extended_facts_v3`만 읽는데, 이 두 canonical은 `combine.py`의 일반 라벨매핑이
   만들지 않는다(`extended_facts_v3`에 `note.%` 행 0건, 아래 §1 실측).
   `chart_builder_page.py`엔 여전히 선택 가능한 지표로 남아 있지만 항상 빈 값이다.

즉 이 트랙은 "DROP 전 이식"이 아니라 **"두 개의 조용한 회귀를 지금 발견해 고치는
일"**에 더 가깝다. 아래 설계는 두 canonical 그룹을 근본적으로 다른 목적지로
분리해서 다룬다.

## 1. 실측 데이터 (2026-09-01, psql)

| 위치 | canonical_account | 행 수 | 기업 수 |
|---|---|---:|---:|
| `fact_v2` | `note.depreciation` | 6,591 | 1,632 |
| `fact_v2` | `note.amortization` | 5,883 | 1,411 |
| `fact_v2` | `note.rou_depreciation` | 665 | 307 |
| `fact_v2` | `note.da_total` | 689 | 437 |
| `fact_v2` | `note.employee_benefits` | 1,954 | 1,174 |
| `fact_v2` | `note.raw_materials_used` | 1,437 | 883 |
| `extended_facts_v3` | `note.%` (전체) | **0** | **0** |
| `std_financials_v3` | `depreciation IS NULL`(연결, fy≥2024) | 4,492 | — |

`extended_facts_v3`에 `note.*`가 0건이라는 게 §0-②의 직접 증거다. `app/data/extended.py`가
`extended_financials` 뷰 하나만 조회하고(`FROM extended_financials e`, fact_v2
직접 접근 없음), 그 뷰는 이제 `extended_facts_v3 JOIN std_financials_v3`뿐이므로
(`collector/db.py` migration `2026_09_extended_financials_v3_view`) 이 두
canonical은 정말로 아무 경로로도 사용자에게 도달하지 않는다.

## 2. 두 갈래로 분리 (목적지가 근본적으로 다르다)

### Track 1 — `note.employee_benefits`/`note.raw_materials_used` → `extended_facts_v3` 직접 upsert

- **낮은 리스크.** `combine.py`/Gate B 비접촉.
- `extended_facts_v3`의 그레인과 정확히 일치한다: `(corp_code, fiscal_year,
  fiscal_period, statement_type, canonical_account) → amount_won`.
- `expense_nature_sync.py`가 호출하는 `store_facts(session, facts)`(→`fact_v2`)를,
  이 두 canonical만 걸러서 `ExtendedFactV3` upsert로 바꿔치기하면 된다. 나머지
  canonical(`note.depreciation` 등, Track 2 소관)은 그대로 두거나 Track 2 결정에
  따른다.
- 부수효과: **지금 깨져 있는 앱 노출을 되살린다.** 이건 `fact_v2` DROP과 무관하게
  당장 고쳐도 되는 버그다 — 오히려 DROP 일정과 별개로 먼저 처리할 이유가 있다.

### Track 2 — `note.depreciation`/`amortization`/`rou_depreciation`/`da_total` → `std_financials_v3` DIRECT_MAP 컬럼

목적지가 확장 카탈로그 행이 아니라 `std_financials_v3.depreciation`/
`amortization`/`da_total`(+파생 `ebitda`) 컬럼 그 자체라 Track 1처럼 단순
upsert 대상이 안 된다. `combine.py`/`note_da.py`는 `build_corp()`가 돌 때마다
`note_lines`에서 **매번 실시간 재계산**하는 구조라(영속 저장소 없음, 순수
in-memory), "한 번 upsert하고 끝"이 통하지 않는다 — 나중에 그 corp/fy/fp가
재추출·기재정정 등으로 다시 빌드되면 이번에 넣은 값은 `note_lines`엔 없는
값이라 그대로 사라진다.

**옵션 비교**

| 옵션 | 설명 | 장점 | 단점 |
|---|---|---|---|
| A. 직접 UPDATE | `std_financials_v3.depreciation` 등 컬럼에 build_corp 우회 직접 UPDATE | 가장 단순, 즉시 구현 가능 | build_corp이 그 corp/fy/fp를 나중에 다시 빌드하면 통째로 유실("조용한 손실" 패턴). `ebitda` 파생(`rule_derive_ebitda`)도 수동 중복 구현 필요 |
| B. override 테이블 + `note_da.py` 병합 + `build_corp` 재호출 | 전용 소테이블(예: `cf_da_recovered`) 신설, `note_da_canonicals()` 병합 지점 추가, cf_da_sync 실행 후 해당 corp `build_corp()` 재트리거 | 단일 writer(combine.py) 유지, `note_lines` "원문 그대로" 불변식 보존, 재빌드돼도 override 테이블을 다시 참조하므로 안 사라짐 | **`combine.py` 변경 필요**(Gate B 핵심 감사 대상, R-트랙 다발 지역) → 전수재감사 필수. `_sync_cf_da` 이후 `build_corp` 재호출 재배선 필요(순서·"두 call site" 룰 재검토) |
| C. `note_lines`에 합성 행 직접 insert | — | — | **기각.** `cf_da.py`/`note_da.py` 자체 주석이 이미 이 설계를 "Phase C 재검토 대상"이라고 명시("주석이 아닌데 note.*를 단다") — 기존 설계자가 스스로 반대한 길 |
| D. 은퇴(retire) | `cf_da_sync.py` 배선을 끈다 | 리스크 0, combine.py 무변경 | 연결 CF D&A 갭(fy≥2024, 4,492건) 복구를 포기 |

**핵심 판단 근거**: D를 "후퇴"로 볼 필요가 없다. §0-①에서 확인했듯 이 값들은
**std_v2 DROP 시점(2026-09-01)부터 이미 아무데도 노출되지 못하고 있었다** —
지금 끄나 계속 두나 사용자가 보는 결과는 동일(안 보임)하고, 차이는 오직
"안 쓰이는 55GB를 계속 채우는가"뿐이다. 즉 D는 현상유지이지 신규 손실이 아니다.

## 3. 권장안

- **Track 1**: 승인 즉시 착수 권장. 리스크 낮고, 살아있는 버그를 고치는 일이기도 하다.
- **Track 2**: **사용자 결정 필요** — B(정공법, combine.py 변경 + 전수재감사)
  vs D(은퇴). 권장은 **D** — 이유는 §2 표 하단 판단 근거. B로 갈 경우 오늘
  끝낸 line_audit 이식과 동급의 별도 세션급 작업(설계→Phase 0~5→전수재감사)이
  또 필요하다. D를 채택하면 §4-4 DROP은 Track 1 완료 직후 바로 가능해진다.
  D 이후에도 "연결 CF D&A 커버리지 개선"을 원하면, `note_da.py` 확장이나
  XBRL Track A 태깅 갭 자체를 원천에서 다루는 별도 트랙으로 새로 설계하는 편이
  이 GC 트랙과 얽히지 않아 더 낫다.

## 4. Track 1 구현 스케치 (승인 후 착수, 지금은 미착수)

1. `fin2/extract/xbrl.py::store_facts()`와 나란히 `ExtendedFactV3` 대상 upsert
   헬퍼 신설. PK: `(corp_code, fiscal_year, fiscal_period, statement_type,
   canonical_account)`, `on_conflict_do_update`.
2. `expense_nature_sync.py`: `extract_expense_nature_facts()`가 반환하는
   facts를 canonical_account 기준으로 분리 —
   - `{note.employee_benefits, note.raw_materials_used}` → 신설 헬퍼로
     `extended_facts_v3` upsert.
   - 나머지(`note.depreciation`/`amortization`/`rou_depreciation`/`da_total`) →
     Track 2 결정에 따름(D 채택 시 폐기/미기록).
3. `cf_da_sync.py`: `recover_cf_da()` 산출물은 전부 depreciation-family라
   Track 2 결정에 100% 종속. D 채택 시 이 파일은 사실상 은퇴 —
   `scripts/collect_new.py`의 `_sync_cf_da` 배선(현재 호출부 1곳,
   `_run_standardize_batches` 내부)에서 `sync_cf_da` 호출부만 제거하고
   `sync_expense_nature` 호출은 Track 1 버전으로 유지.
4. **소급 이관(1회성)**: `fact_v2`에 이미 쌓인 `note.employee_benefits`
   1,954행 + `note.raw_materials_used` 1,437행을 `extended_facts_v3`로
   1회성 백필 — DROP 전에 안 하면 과거분이 그대로 유실된다.
5. **검증**: 배포 후 `chart_builder_page.py`에서 두 지표가 실제 값과 함께
   표시되는지 표본 확인(원문 대조 1~2건) + `extended_facts_v3` 행 수 증가
   확인. Gate B 비접촉이므로 전수재감사는 불요(Track 1 한정).

## 5. §4-4 DROP 최종 체크리스트 (Track 1 완료 + Track 2 결정 후)

1. Track 1 배포 + 소급 이관 완료 확인
2. Track 2 = D 확정 시: `cf_da_sync.py` 배선 제거, 파일 자체는 보존(주석에
   "은퇴, 사유는 이 설계문서" 남김) 또는 `scripts/archive/`로 이동
3. `pg_depend` 전수 재확인(§7 경고 — `calendar_financials` 뷰를 grep만으로
   놓쳤던 전례 반복 금지)
4. `scripts/backup_db.py:33`의 `EXCLUDE_DATA=("fact_v2",)` 정리
5. `fin2/extract/*.py`(`notes.py`/`report_lines.py`/`xbrl.py`/`text.py`/
   `pdf.py`/`statement_titles.py`)의 `fact_v2` 쓰기 경로 비활성화 여부 결정
   (DROP 자체가 쓰기를 막지는 않음 — 테이블이 없으면 즉시 에러가 나므로 코드도
   같이 꺼야 함)
6. `DROP TABLE fact_v2` 실행 + 백업(`pg_dump -Fc`, `std_financials_v2` 때와
   동일 패턴)

## 6. 결정 및 실행 결과 (2026-09-01, 같은 세션)

- **Track 2 = D(은퇴) 채택.** `collector/cf_da_sync.py` 배선을
  `scripts/collect_new.py::_sync_cf_da`에서 제거(파일 자체는 재검토 참고용으로 보존,
  상단에 은퇴 사유 기록). `expense_nature_sync.py`가 뽑는 D&A 계열
  (`note.depreciation`/`amortization`/`rou_depreciation`/`da_total`)도 저장 없이 폐기.
- **Track 1 = 즉시 착수, 완료.**
  1. `fin2/extract/xbrl.py::store_extended_facts_v3()` 신설(`store_facts()`의
     `extended_facts_v3` 대상 자매 함수).
  2. `collector/expense_nature_sync.py`가 `note.employee_benefits`/
     `note.raw_materials_used`만 걸러 이 함수로 적재하도록 전환.
  3. 소급 이관 스크립트 `scripts/factv2_backfill_extended_facts_v3_expense_nature.py`
     신설·실행 — `fact_v2`의 과거분(중복 제거 후 3,387행: employee_benefits 1,951 /
     raw_materials_used 1,436)을 `extended_facts_v3`로 이관 완료.
  4. **검증**: `extended_facts_v3`·`extended_financials` 뷰 양쪽에서 건수 일치
     확인(1,951/1,436), 표본 3건 원문 그레인(corp/fy/fp/basis) 정상 확인. 이걸로
     §0-②에서 발견한 "조용히 깨진 앱 노출" 회귀가 복구됐다 — `chart_builder_page.py`의
     두 지표가 다시 값을 받는다.
  5. `pytest tests/ fin2/tests/` 전체 실행 — 684 pass / 1 fail(무관 기존 실패,
     `test_biz_section.py::test_lxintl_facility_table_dropped`, 생산능력표 파싱 —
     이 트랙과 무관, 별도 이슈).

### 잔여 (§4-4 DROP까지) — 진행 중 (같은 세션 이어서)

Track 1/2 완료로 `cf_da_sync.py`/`expense_nature_sync.py`의 `fact_v2` upsert가 모두
사라졌다. §5 체크리스트 진행 상황:

1. **`pg_depend` 전수 재확인 — 완료.** 의존 뷰/규칙 0건(`extended_financials`가
   §4-2에서 이미 이탈 확인과 일치), FK는 `fact_v2`가 `filings`로 나가는 것 1개뿐
   (자기 PK/인덱스/시퀀스 제외).
2. **`fact_v2` 쓰기 경로 실사용 조사 — 완료.** `store_facts()`(`fin2/extract/xbrl.py`)가
   유일한 쓰기 함수(전수 grep, `INSERT INTO fact_v2`/`insert(FactV2)` 0건 그 외)임을
   확인. 호출부는 전부 CLI/배치 전용(`run.py::cmd_extract2`/`cmd_fin2_all`,
   `scripts/phase_c_rebuild.py`, `collector/cf_da_sync.py`) — 데일리 자동 파이프라인엔
   없음. `extract_file()` 자체는 어디서도 호출되지 않는 dead code임도 확인.
   → `store_facts()`에 `standardize_corp()`(std_v2 가드)와 동일 패턴의 RuntimeError
   가드 추가(단일 지점이라 위 호출부 전부 커버).
3. **`backup_db.py` 정리 — 완료.** `EXCLUDE_DATA=("fact_v2",)`/`--full` 플래그 제거
   (이제 항상 전체 덤프). 부수 발견: `scripts/restore_drill.py`가 `std_financials_v2`
   (오늘 이미 DROP됨)를 여전히 참조하는 별개의 stale 버그를 발견해 같이 수정
   (`std_financials_v3`로 교체, `SCHEMA_ONLY_TABLES`/`fact_v2` 제거).
4. **백업 — 진행/완료** (아래 실행 로그 참고).
5. **`collector/db.py` 마이그레이션 추가 — 완료.** `init_db()`의 `_dropped` 튜플에
   `"fact_v2"` 추가(std_financials_v2 선례와 동일, create_all 재생성 방지) +
   `2026_09_fact_v2_drop` 마이그레이션(`DROP TABLE IF EXISTS fact_v2;`) 추가.
6. **`DROP TABLE fact_v2` 실행** — 아래 실행 로그 참고.

### 실행 로그 — §4-4 `fact_v2` DROP 완료 (2026-09-01, 같은 세션)

- **백업**: `pg_dump -Fc -t fact_v2 --no-owner --no-privileges -d tj_finance -f
  /Volumes/tj_finance_data/db_backup/fact_v2_backup_2026-09-01.dump` — 1.93GB(원본
  55GB), `pg_restore -l`로 TOC 무결성 확인. DROP 직전 행수 74,203,366.
- **DROP 실행**: `collector/db.py`의 `2026_09_fact_v2_drop` 마이그레이션
  (`init_db()` → `_run_migrations()`, `std_financials_v2` 선례와 동일 절차) —
  `DROP TABLE IF EXISTS fact_v2;` + `init_db()`의 `_dropped` 튜플에 `"fact_v2"` 추가
  (create_all 재생성 방지).
- **회수**: DB 전체 157GB → **102GB**(−55GB).
- **검증**:
  - `extended_financials` 뷰(10,706,561행)·`standard_financials`(303,840행)·
    `face_line_audit`(155,224행) 전부 정상 카운트.
  - `extended_financials`의 `note.employee_benefits`(1,951)/`note.raw_materials_used`
    (1,436) — Track 1 이식분 그대로 노출 확인.
  - `pytest tests/ fin2/tests/` — 684 pass / 1 fail(무관 기존실패
    `test_lxintl_facility_table_dropped`, 이 트랙과 무관).
  - `python scripts/dq_assertions.py` — ERROR 1건(`statement_magnitude_impossible`
    150건, 기존 이슈·std_v2 DROP 세션에서 이미 확인된 것과 동일 수치, 무관) 외
    크래시 없음. `fact_v2` 참조 어서션 2건(`std_v2_controlling_ni_exceeds_net`/
    `fact_v2_q1_duration_col0_eq_col1`)이 신규로 SKIP 전환(UndefinedTable, 방어적
    무시) — **아래 잔여 참고 항목으로 별도 기록**.
  - fact_v2 전체 grep 재확인 — `collector/db.py`의 매치는 전부 이미 적용된 과거
    마이그레이션 텍스트(불변, 재실행 안 됨). 나머지는 전부 수동 CLI 진단/백필
    스크립트(`fin2/reconcile.py`는 §4-1에서 이미 저위험으로 스코핑됨). 데일리
    파이프라인(`collect_new.py`)·Streamlit 앱(`app/*.py`, 4개 파일 재확인 — 전부
    주석뿐, 실쿼리 없음) 둘 다 fact_v2 무관 확인.
- **부수 정리**: `scripts/backup_db.py`(EXCLUDE_DATA/--full 제거, 항상 전체 덤프),
  `scripts/restore_drill.py`(std_financials_v2→v3 교체, SCHEMA_ONLY_TABLES 제거 —
  이 파일이 std_v2 DROP 이후로 이미 stale해져 있던 별개 버그도 같이 발견·수정),
  `scripts/dq_assertions.py`(신규 SKIP 2건에 원인·재구현 시 참고사항 주석 추가).

### 잔여 — 새로 발견된 사이드이펙트 (범위 밖, 별도 트랙 후보)

`dq_assertions.py`의 WARN 어서션 2건이 DROP으로 영구 SKIP됐다 — 단순 dead-code
정리가 아니라 **실제 회귀탐지 기능 상실**:
1. `std_v2_controlling_ni_exceeds_net` — controlling_ni 총포괄오염(R25/R26/R43 계열)
   재발 감지. line_audit(Phase B)은 지배/비지배 계열을 의도적으로 제외해 이 공백을
   대신 메우지 않는다.
2. `fact_v2_q1_duration_col0_eq_col1` — Q1 전기컬럼 중복추출(DEF-4) 원문 직접비교
   감지. `calendar_adjacent_year_cq1_identical`(소비계층 기반)이 부분적으로 유사
   신호를 잡지만 탐지 범위가 다르다.

재구현하려면 `report_lines`/`note_lines` 기반으로 새로 설계해야 한다(단순 포팅
아님). 이번 트랙 범위 밖 — 사용자 판단 필요.
