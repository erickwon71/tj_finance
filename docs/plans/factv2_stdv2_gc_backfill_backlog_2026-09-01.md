# 계획 — fact_v2/std_financials_v2 DROP 이후 보강 백로그 (2026-09-01)

> **2026-09-02 진행 기록**: 사용자 지시로 우선순위 1~5(§2 표) 착수, 6(v2 UNION 정책
> 재검토)은 제외. §1/§4는 구현·검증 완료(커밋 전 워킹트리). §2/§3은 원문대조 기반
> 원인규명 완료(코드 변경 없음). §5는 조사 중 원 스코핑이 틀렸음을 발견 — 구현 전
> 사용자 결정 필요(아래 각 섹션 "2026-09-02 진행" 참고).

> 상태: **리스트업만 — 실행 계획 아님.** [정책](../../CLAUDE.md) 상 계획 작성 후 자동 실행
> 금지, 항목 선택 및 착수 승인은 별도 요청 대기. 배경 = 계층3 GC(`std_financials_v2` DROP,
> 커밋 `510095a`) + 계층2 GC(`fact_v2` DROP, 커밋 `31bc4e4`+`f76f4f7`) 완료 이후 두 세션에서
> 발견된 "DROP으로 기능이 조용히 빠지거나 미완으로 남은" 항목을 한곳에 모은 것.

---

## 0. 한 줄 요약

두 GC 트랙(계층2 `fact_v2` 55GB, 계층3 `std_financials_v2` 386MB) 자체는 **완전 종료**됐고
Gate B 전수재감사·pytest·dq_assertions로 크래시·회귀는 확인 안 됐다. 다만 실행 과정에서
"DROP 전에는 v2가 대신 채우고 있던 기능/감지"가 **몇 곳 조용히 비게** 됐고, 그중 일부는
이미 문서화만 되고 착수는 안 된 상태다. 아래 7개 항목을 발견 경위·현재 영향·조치 방향
순으로 정리한다.

---

## 1. dq_assertions.py WARN 어서션 2건 영구 SKIP — 회귀탐지 기능 상실 ★최우선 후보

- `std_v2_controlling_ni_exceeds_net` — controlling_ni 총포괄손익 오염 재발 감지
- `fact_v2_q1_duration_col0_eq_col1` — DEF-4 Q1 전기컬럼 중복추출 감지

`fact_v2` DROP으로 두 어서션이 대상 테이블을 잃어 `scripts/dq_assertions.py`에서 상시
SKIP(방어적, ERROR 아님)이다. dead-code 정리가 아니라 **실제 회귀 탐지 기능 상실** —
두 어서션이 잡던 버그 클래스(controlling_ni 오염 R25/R26/R43 계열, EPS·주식수 Q1 중복추출)는
과거 여러 트랙에서 실제로 재발한 전례가 있다. `report_lines`/`note_lines` 기반 재구현이
필요(단순 포팅 불가 — 원래 acode 기반 조건이라 재설계 필요).

**영향도**: 높음(회귀를 놓칠 수 있는 감시 공백). **난이도**: 중간(재설계 필요하나 표면적은
좁음, 어서션 2개).

> **2026-09-02 진행 — 완료.** `std_v2_controlling_ni_exceeds_net`: `fact_v2` NOT EXISTS
> 절을 `extended_facts_v3`(is.noncontrolling_ni, §4-2 재설계로 이미 존재하는 단일 확정값)
> 로 재소싱해 복구. 실측 357건/223개사(과거 fact_v2 기준 수치와 모집단이 달라 직접비교
> 불가). `fact_v2_q1_duration_col0_eq_col1`: 재구현 **불가로 결론**하고 폐기 — `report_
> lines.py:1199 _is_loadable()`가 BS/IS/CF는 당기(col_index=0)만 적재한다는 2026-07-30
> 결정 때문에 "같은 문서 col0 vs col1 직접비교"라는 이 어서션의 판정 방식 자체를 재현할
> 데이터가 DB에 없다(SCE/note 는 전 컬럼 적재되지만 BS/IS/CF엔 해당 안 됨, 실측 확인:
> `report_lines` col_index 분포 자체는 전 statement 합산치라 착시 가능 — BS/IS/CF만 보면
> col_index=1 행 0건). 대체 신호로 이미 살아있는 `calendar_adjacent_year_cq1_identical`을
> 공식 후계로 지정(코드 주석 갱신). `scripts/dq_assertions.py` 전체 실행 exit 확인,
> 크래시 없음. 코드는 `scripts/dq_assertions.py` 워킹트리 변경(커밋 안 함).

## 2. `standard_financials` 뷰 v2 UNION 브랜치 제거 — 12,149건(73%) 영구 결측

std_v2 DROP 시 사용자가 감수하기로 결정한 트레이드오프. `report_lines`의 "당기(col_index=0)열만
적재" 정책(2026-07-30 결정)의 직접 결과로, 그 연도의 단독 필링이 없는 회사(IPO 시점이
늦어 이전 연도는 비교열로만 존재)의 과거 시계열이 통합 뷰에서 사라졌다. 표본
(`01593668` FY2021)으로 원인 확정됨.

**되돌리려면**: 2026-07-30 정책 자체를 재검토(비교열도 `report_lines`에 저장)하는 새 설계
작업 필요 — `note_periods`급 규모. **영향도**: 중간(오래된 과거 데이터 깊이 문제, 최신
데이터엔 무영향). **난이도**: 높음(정책 재검토 + 전사 재백필).

## 3. Category C 4,366건 — 표(재)백필 실행했으나 결측 순감소 0건, 진짜 원인은 파서 구조적 한계

애초 "도구(`sync_layer2_lines`)만 돌리면 되는 백로그"로 스코핑했으나 실제 실행 결과
결측이 전혀 안 줄었다. 재조사 결과 처리 필링의 99.8%가 `extract_report_lines()`의 표
탐지 로직에서 "본문 섹션 없음"으로 끝남 — 표본(`20000110000001`, 한솔전자 FY1999 H1,
22KB 구형 `<DOCUMENT>` 포맷)으로 이 시대 포맷의 표 구조를 현재 파서가 아예 인식 못 함을
확인. **기존 "pre-2015 2차패스"(`docs/plans/pre2015_layer2_backfill_plan_2026-08-10.md`,
2026-08-11 완료 표기)·"PDF-only 3차패스" 트랙과 대상이 겹치는지 아직 미확인** — 새 R-트랙
착수 전 반드시 먼저 확인해야 함(pre-2015 2차패스가 "완료"로 기록돼 있는데도 이 결측이
남아 있다는 건 그 트랙이 커버 못 한 별도 서브포맷이거나, 완료 판정 자체가 부분적이었을
가능성).

**영향도**: 중간(922개사·4,799rcept, 전부 fy≤2017 — 오래된 데이터). **난이도**: 높음
(신규 파서 확장, 조사 먼저 필요).

> **2026-09-02 진행 — 조사 완료(코드 변경 없음).** 두 표본을 실제로 `extract_report_
> lines()`에 통과시켜 비교: 한솔테크닉스 1999H1(`20000110000001`, 최초 트리아지 표본)은
> **여전히 "본문 섹션 없음"으로 실패**(0행) — pre-2015 2차패스 "완료" 표기와 무관하게
> 이 최초기(1999~2001 추정) 서브포맷은 지금도 못 읽는다. 반면 대한광통신 2006 Q3
> (`20061114000051`, 같은 `<DOCUMENT>` 루트 포맷)는 **정상 추출됨**(320행, BS/IS/CF
> 전부). **결론: Category C는 "pre-2015 `<DOCUMENT>` 포맷 전체"가 아니라 그중에서도
> 더 이른 시기의 특정 서브포맷만의 문제로 범위가 좁혀진다** — 원 스코핑("99.8% 본문
> 섹션 없음")은 표본 편향(오래된 fy 표본만 뽑았을 가능성)일 수 있어, 착수 전 fy별
> 성공/실패율을 다시 실측해야 정확한 규모가 나온다(이번엔 표본 2건만 확인, 전수 재실측
> 미실행). §5(아래)와 부분적으로 같은 뿌리(대한광통신 표본이 실제로 §5 위반 150건 중
> 하나였음)일 가능성이 있어 함께 스코핑하는 편이 효율적.

## 4. `extended_financials_n_facts_outlier` 어서션 폐기, 대체 설계 미착수

§4-2 `extended_financials` 뷰를 fact_v2(acode) 경유 → `extended_facts_v3`(라벨) 경유로
재정의하면서 이 어서션이 상시무의미화돼 함께 폐기됐다. 대체 설계는 별도 소규모 백로그로만
분리해두고 아직 손대지 않음.

**영향도**: 낮음~중간(정확히 무엇을 감지하던 어서션이었는지, 대체가 필요한지부터 재확인
필요). **난이도**: 낮음(어서션 1개 재설계).

> **2026-09-02 진행 — 완료.** 설계문서 §4-①이 제안한 대로 `std_financials_v3.conflicts`
> (canonical별 combine.py `_resolve()`가 값 충돌로 보류한 후보 목록, 코어+확장 캐노니컬
> 공통) 기반 새 WARN `std_v3_conflicts_unresolved` 신설. 실측 35,305행(전체의 11.6%)에
> 실제 충돌 존재, 최빈 canonical=bs.intangibles(12,687)/is.cogs(10,188)/is.sga(8,460)/
> is.noncontrolling_ni(3,132). 옛 어서션과 신호 성격이 다름(무관 라인 다중합산 → 값 충돌로
> 보류된 canonical 존재)을 코드 주석에 명시. `scripts/dq_assertions.py` 워킹트리 변경
> (커밋 안 함).

## 5. `statement_magnitude_impossible` 150건 위반 — std_v3 자체 기존 데이터 품질 이슈, DROP 이후 새로 가시화

std_v2 DROP 검증 중 발견. 표본(`00366942` FY2004H1 이익잉여금 9,950조원류) 확인 결과
이번 DROP이 만든 문제가 아니라 std_v3 자체의 기존 단위오염 데이터 — 이 어서션이 지금까지
v2만 보느라 몰랐던 v3측 신규 가시성일 가능성. 별도 백로그로 남겨져 있고 미착수.

**영향도**: 중간(단위오염이 실제 화면 노출 지표에 영향 줄 수 있음). **난이도**: 미확인
(원인 규명부터 필요).

> **2026-09-02 진행 — 원인규명 완료(코드 변경 없음).** 150건 전수 실측: **72개사, 전부
> fy 2000~2007 분기/반기(Q1/Q3/H1) 별도재무제표** — assets/equity는 NULL·0인데
> retained_earnings 또는 revenue 한 필드만 조(兆) 단위로 튀는 패턴이 지배적(전형적
> "일부 필드만 오염, 나머지는 결측"). 대한광통신 2006Q3(`20061114000051`) 표본을
> 원문(EUC-KR, `iconv`로 디코딩 — `sanitize_dart_xml`/[[feedback-grep-euckr-locale-trap]]
> 함정과 동일 계열)까지 대조: **root cause = 옛(`<DOCUMENT>`) 포맷 표에 붙은 단위선언이
> plain-text `(단위 : 백만원)`(XML 속성 `AUNIT` 없이 텍스트로만 존재)인 경우, 현재
> 파서가 그 표 자체의 선언을 못 읽고 문서 레벨 기본단위(doc_default)로 폴백해 ×10⁶을
> 잘못 적용**(추출 결과 실측: `unit_source='doc_default'`, `adecimal=-6`, 이익잉여금
> 5,229,469,085,000,000원 — 원문 표는 정상 파싱됐고 문제는 그 표에 붙은 단위 텍스트를
> 못 읽는 것뿐이었음, "본문 섹션 없음"으로 실패한 §3과는 다른 실패모드). 이미 알려진
> 단위오추측 버그류(a)(`unit_contamination` 어서션 주석 참고)의 **옛 포맷 전용
> 변종**으로 보임 — 정식 수정은 `_PRE2015_ROUTING_MAX_FY` 경로의 단위 추출 로직(header_
> hint) 확장이 필요해 신규 파서 작업급(별도 R-트랙), 이번엔 원인규명까지만.

## 6. `calendar_orphan_cq` 어서션 SKIP 유지 — 이산분기/달력 정책 재설계 필요

`std_financials_v2`의 `is_discrete` 개념을 묻는 어서션인데 그 쓰기 경로 자체가 Phase 2부터
멈춰 있어 v3에 포팅 대상이 없다. 이산분기·달력(`std_financials_calendar`) 자체는
**실사용 중**(`screen_window.py`/`series.py`/`quarter_change.py`/`company_page.py`, §5-d
정정 확인)이라 폐기는 아니고, 유지하려면 이 4개 소비자의 v2→v3 이식이 선행돼야 한다.

**영향도**: 낮음(현재 크래시나 데이터 손실 없음, 단 회귀 감지 공백은 있음). **난이도**:
중간(소비자 4곳 이식 + 어서션 재설계, 별도 트랙).

> **2026-09-02 진행 — 조사 결과 원 스코핑이 부정확했음을 발견, 구현 보류(사용자 결정
> 필요).** 실제로 확인해보니 4개 소비자(`screen_window.py`/`series.py`/`quarter_change.py`/
> `company_page.py`)는 `calendar_financials` 뷰(→`std_financials_calendar`, DROP 안 된
> 별개 테이블)만 읽고 `std_financials_v2`를 안 읽는다 — **이식할 소비자 자체가 없다.**
> 진짜 쓰기 경로는 `fin2/standardize/calendar.py::calendarize_corp()`(`_load_discrete()`가
> `std_financials_v2`를 SELECT)인데, 이 함수는 **§4-1(계층2 GC 조사, 커밋 `97ff39d`)에서
> 이미 RuntimeError 가드가 걸렸고, 그보다 먼저 Phase 2(2026-08-30)에서 데일리 파이프라인
> 배선 자체가 끊겨 있었다** — 즉 `std_financials_v2` DROP 훨씬 전부터 `std_financials_
> calendar`는 신규 기업/신규 분기로 자라지 않는 정지 테이블이었다(실측: `calendar_year`
> 최댓값 2026, 319,694행 — Phase 2 중단 직전까지의 데이터는 있어 당장 화면이 텅 비진
> 않지만, 그 이후 신규 공시분은 계속 안 쌓이고 있다). **이건 v2 DROP이 만든 문제가
> 아니라 그보다 먼저 있었던, 지금도 계속 진행 중인 별개의 조용한 결측이다.**
>
> 남은 선택지 2가지, 둘 다 GC 백로그보다 큰 결정이라 사용자 판단 필요:
> ① **은퇴** — 이산분기/달력 기능 자체를 접고 4개 소비 화면도 함께 정리. 근거: 원래도
>    "이산분기·달력 사용자 노출 없음"이 1차 결론이었다가 뷰 참조가 있어 정정된 것뿐,
>    실질 활용도는 재확인 필요.
> ② **v3 재설계** — `calendarize_corp()`(및 자매함수 `derive_quarters_corp()`)를
>    `std_financials_v2` 대신 `std_financials_v3`를 읽도록 다시 짜고 데일리 배선 복구.
>    새 파이프라인 작업급(런북 3층: 배선+소급백필+검증) — 이번 세션 범위를 벗어남.
> `calendar_orphan_cq` 어서션 자체는 어느 쪽을 택하든 그 이후에 따라오는 부수 작업이라
> 이번엔 SKIP 유지, 코드 변경 없음.

## 7. (참고, 보강 불요) `cf_da_sync.py` D&A 계열 은퇴 — 기능적 손실 없음 확인됨

`note.depreciation`/`amortization`/`rou_depreciation`/`da_total`는 은퇴(D) 결정됐으나,
확인 결과 이미 `std_financials_v2` DROP 시점부터 죽은 쓰기였고 v3 D&A(`note_da.py`)는
애초에 `fact_v2`를 안 읽고 `note_lines`만 읽어 만든다 — 별도 조치 불필요. (리스트에는
완결성을 위해 남겨두되, 착수 후보에서는 제외.)

---

## 2. 권장 우선순위 (제안, 착수는 사용자 선택)

| 순위 | 항목 | 이유 |
|---|---|---|
| 1 | §1 dq_assertions 2건 재구현 | 회귀탐지 공백 — 과거 실제 재발 이력 있는 버그 클래스, 표면적 좁음 |
| 2 | §5 statement_magnitude_impossible 150건 원인규명 | 실제 지표 오염 가능성, 원인규명만 먼저(저비용) |
| 3 | §3 Category C 겹침 확인 | 새 작업 벌이기 전 기존 트랙 재확인이 선행조건(저비용, 조사만) |
| 4 | §4 extended_financials_n_facts_outlier 대체설계 | 규모 작음 |
| 5 | §6 이산분기 소비자 4곳 이식 | 현재 기능 정상 작동 중이라 급하지 않음 |
| 6 | §2 v2 UNION 12,149건 정책 재검토 | 되돌릴 수 없는 트레이드오프, 가장 큰 설계 결정 필요 — 신중 |

## 참고

- 관련 메모리: `factv2-stdv2-gc-scoping-2026-09-01`, `gateb-factv2-sync-scripts-track1-2026-09-01`,
  `gateb-phaseb-line-audit-migration-phase0-1-2026-09-01`.
- 원 스코핑 문서: `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md`.
