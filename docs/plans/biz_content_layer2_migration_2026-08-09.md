# 계획 — '사업의 내용' 원문 read를 계층2로 편입 (R1 위반 해소) 2026-08-09

> 상태: **계획 확정 (미실행)**. 사용자 결정(2026-08-09): §6 확정 결정 절의 "R1 '사업의 내용'이
> 계층2를 우회" 미결 항목에 대해 **전면 재설계**(경량 수정 아님) 선택, §7 열린 결정 3건도 확정.
> 실행 체크리스트 = [`biz_content_layer2_migration_todo_2026-08-09.md`](biz_content_layer2_migration_todo_2026-08-09.md).
> 마스터 허브 [`rearchitecture_4layer.md`](rearchitecture_4layer.md) §6·§7 후속 트랙 밖의 별도 트랙.
> 선례: [`layer2_notes_transcription_2026-07-25.md`](layer2_notes_transcription_2026-07-25.md)
> (주석 전사 — 같은 유형의 편입을 재무제표 쪽에서 이미 완료).

---

## 0. 한 줄 요약

`fin2/extract/{biz_section,sales_section,biz_catalog,order_backlog}.py` 4개 파서가 로컬 XML을
**직접 read**해 `biz_metrics`/`order_backlog`에 적재한다(R1 위반: "원문 read = 계층2 전용").
조사 결과 **4개 중 3개(biz_section·sales_section·biz_catalog)는 이미 원본 grid를
`biz_section_tables`에 무손실 저장하고 있어** 사실상 계층2 스토어가 존재한다 — 다만 "원문 read →
구조화 매핑"이 **한 함수 호출 안에서 함께** 일어나 진짜 두 단계로 분리돼 있지 않다. `order_backlog`만
원본 grid 저장이 전혀 없는 진짜 공백이다. 이 계획은 그 경계를 **DB 왕복으로 실제로 끊어서**
"계층2=원문 read 전담, 계층3=DB만 읽어 구조화" 를 강제한다.

## 1. 아키텍처 기준

| 계층 | 책임 | 이 계획의 위치 |
|---|---|---|
| **2 (신설)** | 원문 XML → 소제목 창 탐지 + ROWSPAN/COLSPAN 확장 grid → **판단 없이** DB 저장 | `find_biz_subsections`/`find_order_subsections`/grid 확장 로직 이관 |
| **3 (기존 재배선)** | DB의 grid만 읽어 `map_biz_table`/`map_order_table` 구조화 + R0/R2 정본정책(`filing_select.py`/`biz_merge.py`) | `collector/biz_metrics.py`/`collector/order_backlog.py` |

⇒ 원칙: **"어느 표를 찾을지"(소제목 창 탐지)는 구조 사실 → 계층2**, **"표를 어떻게 해석할지"(품목·부문·
metric 매핑, 정본 병합)는 값 판단 → 계층3**. report_lines/std_v3와 동일한 경계.

## 2. 현 상태 실측 (2026-08-09)

| 대상 | 원문 직접 read 지점 | 이미 grid 저장? | 저장 테이블 |
|---|---|---|---|
| `biz_section.py` (생산능력/실적/가동률) | `_load_root`(L62 `open(file_path,"rb")`) | ✅ | `biz_section_tables` |
| `sales_section.py` (매출 채널) | `parse_biz_metrics` 내부에서 공유 `root` 재사용, read 지점은 biz_section과 동일 1회 | ✅ (`extract_sales_from_root`가 `grid` 포함 dict 반환) | `biz_section_tables` |
| `biz_catalog.py` (27항목 카탈로그) | 〃 | ✅ (`extract_catalog_from_root`가 `grid` 포함 dict 반환) | `biz_section_tables` |
| `order_backlog.py` (수주상황) | 별도 `_load_root` 호출(독립 파일 read, 위 3개와 공유 안 함) | ❌ 저장 안 함 | 없음(신설 필요) |

현재 행 수: `biz_section_tables` 528,564 / `biz_metrics` 7,809,228 / `order_backlog` 24,682.
사업보고서(annual, XML 있음) 필링 53,952건.

**핵심 발견 — 구조화 매핑 함수는 이미 순수 데이터 함수다**:
- `map_biz_table(bt: BizTable, fiscal_year)` — `BizTable`은 `(metric, narrative, grid)` 뿐인
  plain dataclass, **live `etree` 참조 없음**. `biz_section_tables`의 컬럼과 1:1 대응.
- `map_order_table(grid, default_unit=None)` — grid만 받음, live element 불필요.
⇒ 두 함수 모두 **DB row → dataclass 재구성 → 그대로 호출**로 바꿀 수 있다. 매핑 로직 자체는
   **한 줄도 안 고쳐도 된다** — 입력 출처만 파일→DB로 바뀐다. 이게 이 재설계가 note 전사보다
   작은 이유(계층3 쪽 새 매핑 개발이 사실상 0).

## 3. 목표 아키텍처

### 3.1 새 계층2 쓰기 (per-filing, 무조건, R0/R2 무관)
- 모듈: `fin2/layer2/biz_raw_tables.py`(신설, 구현 완료 2026-08-09) — **정본정책·병합 없음.**
  구현 시 원안(탐지 코드 물리적 이관)에서 **재사용으로 조정**: production/sales/catalog는
  `biz_section.parse_biz_metrics()`(탐지+매핑 결합, 검증된 코드)를 그대로 호출해 raw grid 절반만
  취함(매핑 결과는 버림, 계층3가 재계산) — 강하게 얽힌 탐지/매핑을 무리하게 분리하는 리스크를
  피함. order_backlog는 원본 저장이 없었던 진짜 신규분이라 `find_order_subsections`를 직접
  호출. 표본검증(`scripts/probe_biz_raw_tables_parity.py`) 658행 불일치 0건.
- 대상 필링: `annual` report_type의 **모든** 완료된 XML(=R0, `is_final` 필터 없음 — 기존
  `find_annual_reports`와 동일 원칙).
- 쓰기: `biz_section_tables`를 **rcept_no 단위 delete-then-insert**로 스코프 변경(현재는
  `(corp,fiscal_year)` 스코프 — period 병합 결과를 함께 지우던 구조라 그랬음. 계층2 전용이 되면
  원문-필링 단위가 자연스럽다. `UniqueConstraint(rcept_no, table_ord)`는 이미 그 스코프 전제).
- `domain` 컬럼 신설(`production`/`sales`/`catalog`/`order_backlog`) — 지금은 `metric` 필드가
  이 역할을 부분적으로 겸하고 있어 order_backlog 편입 시 구분이 필요.
- order_backlog 도메인은 `default_unit` 판정에 필요한 `narrative`(단위 서술)도 함께 저장.

**Phase 3 완료(2026-08-09)** — 재배선 자체는 계획대로였으나, parity 검증 중 이 계획과 무관한 기존
버그 2건을 발견해 함께 수정했다(상세는 TODO 문서 Phase3 절): ①Phase1 도메인 분류가 `metric` 값만
봐서 `metric='sales'`를 sales_section/biz_catalog 양쪽 출처 구분 없이 한 도메인으로 묶었던 것
(6,148행 재분류) ②`biz_catalog.py`가 narrative를 4000자로 잘라 저장하던 기존 코드(3,128행,
0.95%)가 무손실 원칙을 어기고 있던 것(절단 제거). 표본 30개사 79,463행 재검증 최종 대칭차
4건(0.005%, 원인 규명 완료 — 아직 재추출 안 된 과거 행, Phase3 로직 결함 아님). order_backlog는
0/0 완전 일치.

### 3.2 계층3 재배선 (DB만 읽음)
- `collector/biz_metrics.py::sync_biz_metrics_corp` — `Path(f.file_path)` 로 파일을 여는 대신,
  그 period-group에 속한 rcept들의 `biz_section_tables` 행을 조회 → `BizTable(metric, narrative,
  grid)` 재구성 → `map_biz_table` 그대로 호출. `find_annual_reports`/`period_groups`(R0)와
  `merge_filings`(R2, `collector/biz_merge.py`)는 **무변경**(이미 원칙 준수 — 이번 위반은 그 앞
  단계인 "무엇을 읽나"에만 있었음).
- `collector/order_backlog.py::sync_order_backlog_corp` — 동일 패턴, `map_order_table` 호출부만
  DB 조회로 교체. 이 모듈은 원본 grid 저장이 없었으므로 **신규 배선**.
- `fin2/extract/{biz_section,sales_section,biz_catalog,order_backlog}.py`에서 구조화 매핑 함수
  (`map_biz_table`/`map_order_table`/관련 헬퍼)만 남기고 `_load_root`/탐지 함수는 §3.1로 이관.

### 3.3 두 단계 사이의 계약
- 계층2 산출물(`biz_section_tables`, `domain` 포함)이 유일한 인터페이스. 계층3는 이 테이블 밖의
  어떤 파일도 열지 않는다(검증 스크립트 예외는 R1 그대로 유지).

## 4. 백필 필요량

| 항목 | 상태 | 조치 |
|---|---|---|
| `biz_section_tables`(production/sales/catalog) | 기존 53,952건 필링 중 이미 로드된 것은 **grid 존재**(현재 구조가 이미 함께 씀) — but `domain` 컬럼은 신설이라 기존 528,564행에 소급 채움 필요 | 마이그레이션으로 `metric` 값 기반 역산 채움(생산 3종=production, `metric='sales'`=sales, 그 외=catalog) — 원문 재파싱 불필요 |
| `order_backlog` 원본 grid | **전량 없음**(0/24,682) | 전 대상 필링 재파싱해 신규 저장 — 유일하게 "진짜" 백필 |
| `biz_metrics`/`order_backlog`(구조화 결과) | 재배선 후 **재생성해서 현재 값과 diff** | 값이 하나도 안 바뀌어야 정상(매핑 로직 무변경) — 회귀 검증 |

## 5. 검증 계획

1. **파일-경로 대조 표본**: 재배선 전/후로 동일 표본(예 150개사)에 대해 `biz_metrics`/
   `order_backlog` 산출을 diff — 0건 불일치가 성공 기준(매핑 로직이 안 바뀌므로).
2. **원문 대조**(`feedback-verify-against-source` 원칙): 신규 편입되는 order_backlog 도메인은
   grid 저장이 처음이므로, 표본 수 건을 원문 XML과 직접 대조.
3. **Gate B**(항등식 등 기존 감사기) — 이 트랙은 std_v3/financial statements를 건드리지 않으므로
   원칙적으로 무영향. 확인만.
4. pytest 전체(`pytest tests/ fin2/tests/`) 회귀 없음 확인.

## 6. 파이프라인 배선 체크리스트 (`docs/runbook_new_parser_pipeline_integration.md` 준수)

- ① **두 call site**: `scripts/collect_new.py`
  - 메인 경로 L804-808 (`_sync_biz_metrics(affected)` / `_sync_order_backlog(affected)`)
  - `--standardize-only` 재개 경로 L690-691 (동일 두 함수)
  - 이번 재설계는 이 두 함수의 **내부 구현만** 바뀌고 호출부는 무변경 — 배선 누락 위험 낮음, 그래도
    체크리스트대로 명시 확인.
  - **(실행 결과, Phase4 2026-08-09) 계획 변경**: 별도 배선 불필요로 판명 — `ensure_biz_raw_tables`
    를 `sync_biz_metrics_corp`/`sync_order_backlog_corp` 내부(필링별 루프, DB 조회 직전)에 심어
    "계층2 쓰기 → 계층3 읽기" 순서를 함수 자체가 보장하므로, 그 두 함수를 부르는 기존 두 call
    site는 무변경으로 유지됐다. 상세 = `biz_content_layer2_migration_todo_2026-08-09.md` Phase4.
- ② **소급 백필**: §4 표 그대로 — `domain` 역산 채움(전체) + order_backlog grid 신규 백필(전체
  53,952건 대상 재파싱, 규모는 note 전사보다 훨씬 작음 — 표 하나짜리 섹션).
- ③ **검증**: §5.

## 7. 열린 결정 — 확정 (2026-08-09)

1. **`biz_section_tables` 컬럼 확장(신규 테이블 아님)** — **확정**. order_backlog도 "본문 표의
   원본 grid"라는 성격이 production/sales/catalog와 동일해 테이블 스프롤을 피한다. `domain`
   컬럼(`production`/`sales`/`catalog`/`order_backlog`) 신설.
2. **delete-then-insert 스코프 `(corp,fiscal_year)` → `rcept_no`** — **확정, 안전 확인 완료**.
   `biz_section_tables`의 기존 소비처 전수 조사(`scripts/probe_merged_recoverable.py`·
   `diag_cell_merge_defect.py`·`probe_merged_column_tables.py`·`audit_document_census.py`·
   `purge_foreign_corps.py`) — 전부 `rcept_no` 또는 `corp_code`/`fiscal_year`로 **읽기만** 하고
   쓰기 스코프 자체에 의존하는 코드는 없음. 변경 안전.
3. **order_backlog 전체 재파싱 비용** — **실측 완료(2026-08-09, Phase 0)**: 표본 500건 평균
   103.8ms/필링 → 전체 53,952건 추정 **93.4분**(단일 프로세스). `build_std_v3 --all`(62분)·
   `backfill_shares_transcribe.py`(63.8분)와 같은 규모라 복잡한 샤딩 없이 단일 배치로 진행
   확정(`scripts/probe_order_backlog_reparse_cost.py`).

## 8. 구현 순서 (제안, 실행은 별도 승인 후)

1. `biz_section_tables`에 `domain` 컬럼 추가 마이그레이션 + 기존 528,564행 소급 채움(순수 SQL,
   재파싱 불필요).
2. `fin2/layer2/biz_raw_tables.py` 신설 — production/sales/catalog 3종 소제목 탐지+grid 확장
   이관(기존 `find_biz_subsections`/`extract_sales_from_root`/`extract_catalog_from_root`의
   "탐지" 부분만, 매핑 부분은 남김). order_backlog 소제목 탐지(`find_order_subsections`)도 이관.
3. `collector/biz_metrics.py`/`collector/order_backlog.py` 재배선 — DB에서 grid 읽어
   `BizTable` 재구성 → 기존 `map_biz_table`/`map_order_table` 그대로 호출.
4. order_backlog 전량 재파싱 → `biz_section_tables`(`domain='order_backlog'`) 신규 백필.
5. §5 검증 전부 통과 확인.
6. `docs/PARSING_RULES.md` R1의 "현재 예외 상태" 절 제거 + `rearchitecture_4layer.md` §6
   "미해결 위반" 표기 해소로 갱신.

---

**다음 액션**: 실행 체크리스트 =
[`biz_content_layer2_migration_todo_2026-08-09.md`](biz_content_layer2_migration_todo_2026-08-09.md).
계획은 확정됐으나 **실행은 별도 명시적 요청으로 시작**한다(CLAUDE.md 정책).
