# 계획 — 보고서→DB 적재 구멍 메우기 + 전수 검증 체계 + 용량 낭비 회수

## Context

**목표(사용자).** 원본 보고서에서 기업 평가에 필요한 정보를 **뽑을 수 있는 만큼 전부** DB 로
가져온다. **현재 구현되어 있는 것에 한계를 두지 않는다** — 명시하지 않아서 파서가 안 만들어진
항목들이 있고, 그 구멍을 메우는 것이 이 계획의 본체다. 단 **불필요한 데이터로 용량을 키우지
않는다.**

**왜 이 계획이 필요한가.** 지금까지의 검증은 "만들어 둔 파서가 제 일을 하는가"만 봤다.
보고서에 있는데 **파서 자체가 없는 것**은 어떤 지표에도 나타나지 않는다. 실제로 이 계획을
준비하며 원문 섹션을 전수로 뽑아보니, 40/40 보고서에 존재하는 섹션 중 **추출기가 아예 없는
것이 10종 이상**이었다(사채 미상환 잔액·감사의견·종속회사·계열회사·특수관계자 거래·우발부채·
파생상품 등). 동시에 DB 109 GB 중 **약 45 GB 가 회수 가능한 낭비**임도 실측했다.

**오늘(2026-07-30) 이미 두 번의 전량 재적재가 있었다.** 이 계획은 그 결과를 반영한 상태에서
쓴 것이다 — 아침에 측정한 수치는 전부 무효이므로 재측정했다.

---

## 1. 오늘 이미 닫힌 구멍 — **다시 제안하지 않는다**

워킹트리 미커밋 변경 4파일(`git status`)이 아래를 이미 해결했다. 재적재 2회
(`logs/full_reload_driver.log`, `driver2.log`)로 DB 에도 반영됐다.

| 결함 | 수정 | 효과 |
|---|---|---|
| `int(float())` 정밀도 손실 | 정수는 float 우회 (`amount_normalizer`) | 날조 17,771 행 제거 |
| 셀 병합 날조 | R1 공백분리 다중숫자 거부 | — |
| 후행 콤마·그룹 파괴 | R2 (값은 채택 — 숫자열은 안 바뀜) | — |
| 타당성 상한 9×10¹⁸ | R3 → 1경원 | 자릿수 폭발 차단 |
| `'2006.02~'` → 2,006원 | R4 범위표기 거부 | 실측 319건 |
| `<주석5,42>` 라벨 오염 | `normalize_account_name` literal 제거 | 8.5경 카나리아 회귀 |
| **열절단** `_NOTE_MAX_COLS` 8, `_SCE_MAX_COLS` 12 | **→ 200** | 주석 3,592,401 셀 회복(1.62%) |
| **같은 표 중복 순회** | `dict.fromkeys(tables)` | 중복키 1,076,974 그룹 제거 |
| `_is_header_cell` 날짜/개월 과잉매칭 | 한글 잔존 검사 · `fullmatch` | 실데이터 행 회복 |
| BS/IS/CF 전기·전전기 적재 | `_is_loadable` col_index=0 만 | `report_lines` 29 → **17 GB** |

현재 상태: **DB 109 GB** · `note_lines` 84 GB(≈220.6M행) · `report_lines` 17 GB(≈37.6M행).
⚠ **미커밋** 상태다 — 계획 착수 전에 커밋하고 회귀 테스트를 통과시켜야 한다.

---

## 2. 아직 열린 구멍 — 세 부류

### 2-A. 계층2 값 정확성 — 단위 판정기 3종 결함 ★신규 발견(오늘 미조치)

`parser/common/amount_normalizer.py:62` 단 한 줄. 오늘 변경분에 **포함되지 않았다.**

```python
_UNIT_DECL_RE = re.compile(r'단위\s*[:：]?\s*\(?\s*(억원|백만원|만원|천원|원)')
```

`단위` **직후**에 금액 토큰이 와야 매칭한다. FY2024 보고서 60건 원문 grep 실측:

| 선언 패턴 | 실측 | 현재 동작 | 결함 |
|---|---|---|---|
| `천원`/`원`/`백만원` 단독 | ~10,700 | 정상 | — |
| `주`·`사`·`명`·`톤`·`%`·`시간`·`KAU` 단독 | ~950 | **표 통째 폐기** | 비금액 정보 전량 누락 |
| `백만원, %` · `원, 주` · `백만원, 주, %` | ~540 | 첫 토큰 배수를 **전 열**에 적용 | 이자율·지분율·주식수가 금액으로 **오염** |
| `매, 백만원` · `주, 천원` (금액이 뒤) | ~60 | **매칭 실패 → 표 폐기** | 금액표가 조용히 사라짐 |
| `백만원, 천USD` | ~30 | 백만원 매칭 → USD 열 ×10⁶ | **외화가 원화로 적재** |

**★ 기존 검증 도구 2종이 구조적으로 못 잡는다.** 역방향 검사는 `av % m == 0 and str(av//m) in src`
로 "DB 값이 원문 숫자에서 파생됐나"만 본다 — 이자율 `5` → `5,000,000원` 은 `5` 가 원문에
있으므로 **통과**한다. 정방향 셀 검사는 폐기된 표를 스코프 밖으로 세지 않는다.

### 2-B. ★★보고서에 있는데 추출기가 없는 항목 — 이 계획의 본체

FY2024 보고서 40건의 `<TITLE>` 전수 추출 결과 대비 DB 테이블 매핑(코드 grep 로 확인):

| 보고서 섹션 (40/40 존재) | DB | 상태 | 투자 활용 |
|---|---|---|---|
| 연결재무제표·재무제표 | `report_lines` | ○ | — |
| 주석 | `note_lines` | △ 단위선언 조건 | §2-A |
| **회사채 미상환 잔액** | — | **✗ 없음** | **차입금 만기구조** |
| **단기사채·기업어음 미상환 잔액** | — | **✗ 없음** | **유동성 위험** |
| **신종자본증권·조건부자본증권 미상환** | — | **✗ 없음** | 자본 성격 판단 |
| **채무증권 발행실적** | — | **✗ 없음** | 조달 이력 |
| **회계감사인의 감사의견 등 / 외부감사** | — | **✗ 없음** (`감사의견` 은 섹션 제외 키워드로만 존재) | **감사의견·핵심감사사항 = 리스크 1차 신호** |
| **대주주 등과의 거래내용** | — | **✗ 없음** | **특수관계자 거래(터널링)** |
| **연결대상 종속회사 현황(상세)** | — | **✗ 없음** (`종속회사` grep 0건) | 연결 구조 |
| **계열회사 현황(상세)** | — | **✗ 없음** (`계열회사` grep 0건) | 지배구조 |
| **우발부채 등에 관한 사항** | — | **✗ 없음** (`우발` grep 0건) | 소송·보증 |
| **위험관리 및 파생거래 / 파생상품거래 현황** | — | **✗ 없음** | 헤지·평가손익 |
| **이사회·감사제도에 관한 사항** | — | **✗ 없음** | 지배구조 스코어 |
| **증권의 발행을 통한 자금조달·사용실적** | — | **✗ 없음** | 자금 사용 검증 |
| **기타 재무에 관한 사항** | — | **✗ 없음** | 대손충당금·재고 현황·공정가치 |
| **원재료 가격 변동** | — | **✗ 없음** (`biz_section` 은 표만 grid 저장) | 원가 선행지표 |
| 매출 및 수주상황 | `order_backlog`·`biz_metrics(sales)` | △ 미검증 | — |
| 원재료 및 생산설비 | `biz_metrics(capacity/output/utilization)` | △ **1,513/2,534사만** | 가동률 |
| 주요계약 및 연구개발활동 | `rd_note` | △ 미검증 | R&D |
| 배당 / 주주 / 임원·직원 / 보수 / 타법인출자 | `dividend_facts`·`major_shareholders`·`retail_ownership`·`shareholder_changes`·`executives`·`employee_stats`·`exec_pay_*`·`other_investments` | ○ | — |
| 자본금 변동·전환사채 | `capital_events` | △ 부분 | 희석 |
| 요약재무정보 | — | 의도적 제외 | — |

**★ 부수 발견 — 프로젝트 원칙 위반.** ○ 로 표시된 항목 다수가 `collector/dart_client.py` ·
`dart_periodic.py` 의 **DART API 유래**다(배당·최대주주·소액주주·자기주식·직원). CLAUDE.md 는
"DB화할 정보는 모두 local folder 문서로부터"라고 못 박고 있다. API 유래는 **원문 대조 검증이
불가능**하고 API 스펙 변경에 조용히 깨진다. 어느 항목이 문서 유래인지 API 유래인지 **표로
확정**하고, 문서에서 뽑을 수 있는 것은 문서로 옮긴다.

### 2-C. 파이프라인 구멍

| 구멍 | 근거 | 심각도 |
|---|---|---|
| **데일리에 본문 미배선** — `scripts/collect_new.py` 는 주석만 증분 적재(`_sync_note_lines`), `report_lines` 는 배치 전용 | `docs/qa/layer2_fidelity_full_2026-07-30.md` §5-6 | **★P0 — 신규 보고서 본문이 자동 적재되지 않는다** |
| 신 체인에 비교컬럼 폴백 없음 | 같은 문서 §6. `standardize_comparative_corp` 는 `fact_v2`(삭제됨) 소스 | 상장 후 첫 보고서의 이전 기간 부재 |
| `header_hint` B안 미실행 | `docs/plans/layer2_header_hint_lossless_2026-07-30.md` | 헤더 오판 잔여 |
| 소수 절단 `1,106.52 → 1,106` | 0.109% · `adecimal` 보존 미결 | 환율·주가 |

### 2-D. pre-2015 82,005 filing (1,613사)

FY2015+ 한정은 **안정된 서식으로 계층 골격을 한 번 세우려는 의도**였다(사용자 확인).
이번엔 타당성만 측정하고 적재는 그 숫자를 보고 별도 결정.

---

## 3. 용량 낭비 — 약 45 GB / 109 GB (재측정 완료)

| # | 낭비 | 실측 | 회수 | 재적재 |
|---|---|---|---|---|
| W1 | `table_title` 행마다 반복 | note 141 B × 220.6M(distinct **35,345**)<br>report 164 B × 37.6M(distinct 16,115) | **~37 GB** | 예 |
| W2 | 사실상 미사용 인덱스 | `note_lines_pkey` 4,727 MB **scan 0**<br>`note_lines_corp_fy_basis_idx` 1,523 MB **0**<br>`report_lines_pkey` 805 MB **0**<br>`ix_report_lines_context_fiscal_year` 327 MB **0**<br>`ix_report_lines_report_fiscal_year` 353 MB **5** | **~7.7 GB** | 아니오 |
| W3 | 상수·파생 컬럼 | `note_lines.statement`='note'(5 B)·`unit_source`='declared'(9 B)·`corp_code`(rcept_no 파생, 9 B)·`rcept_no` varchar(14)→bigint(−7 B)·`parsed_at`(8 B) | **~6 GB** | 예 |
| W4 | 튜플 정렬 패딩 | int8 이 int2 사이에 흩어짐 | 측정 필요 | 예 |

**W2 의 `scan 0` 은 신뢰할 수 있다** — 인덱스는 오늘 20:42 재생성됐고 같은 창에서
`note_lines_rcept_no_idx` 는 **1,304,588 회** 스캔됐다. 즉 창은 유효하고 그 안에서 0 이다.
그래도 drop 전 코드 grep 로 참조를 확인한다(`idx_scan=0` 자체가 증명은 아니다).

---

## 4. Phase 계획

### Phase 0 — 오늘 변경분 고정 (선행 필수) · **std_v3 빌드와 병행 가능**
미커밋 4파일 커밋 + `pytest tests/ fin2/tests/` 253건 통과 확인. 이게 안 되면 이후 측정의
기준선이 흔들린다. 현재 DB 가 바로 이 코드로 적재된 것이므로 **코드와 데이터를 같은 시점에
고정**하는 의미가 있다.

> **실행 중인 `build_std_v3 --all` 은 끝까지 둔다**(20:47 시작·약 60분). 두 가지 이유:
> ① `scripts/build_std_v3.py:64-67` 이 **200 corp 마다 commit** 하므로 중단하면 std_v3 가
> corp 단위로 신·구(12:20 빌드) 혼재 상태가 된다. ② 이 빌드가 Phase 2·4 합격 기준
> ("행 수 185,268 ±α · **값 변화는 증가 방향만**")의 **기준선**이다 — 죽여도 다시 만들어야 한다.
> Phase 0 은 DB 를 안 건드리므로 지금 병행하고, **Phase 1 스윕은 빌드 종료 후** 시작한다
> (T1·T2 는 102,633 filing 재파싱이라 CPU·DB 경합이 크다).

### Phase 1 — 검증 도구 3종 (읽기 전용, 서로 독립·병행 가능)

**T1. `scripts/audit_unit_declarations.py`** — §2-A 를 정면 측정. 기존 도구가 구조적으로 못 보는 곳.
- 표마다 원문 선언 문자열을 **그대로 보존**하고 4분류: `금액단독`/`비금액단독`/`혼합`/`미선언`
- 버킷별 표 수·숫자 셀 수·현재 적재 여부·대표 선언 문자열 상위 30
- **오염 확정 셀 수** = `col_label` 에 `%`·`율`·`주`·`USD`·`배`·`년` 이 있는데 `value_won` 이 채워진 셀
- 재사용: `fin2.extract.text.declared_unit`, `amount_normalizer.detect_unit_declaration`,
  `section_detector.assign_note_tables_with_titles`, `--shard a/n` 인터페이스(기존 2종과 동일)

**T2. `scripts/audit_document_census.py`** — §2-B 구멍 목록을 **표본 40건이 아니라 전수로** 확정.
- 모든 `<SECTION-2>` → 모든 `TABLE` → 숫자 셀 수. **DB 대조로 목적지 귀속**
  (`report_lines`/`note_lines`/`biz_metrics`/`order_backlog`/`other_investments`/… /**미귀속**)
- 출력: 섹션 TITLE × 목적지 매트릭스, **미귀속을 숫자 셀 수 내림차순**(큰 것부터 메운다)
- 재사용: `section_detector.detect_dart_sections`/`assign_tables_to_dart_sections`,
  `fin2.extract.biz_section.expand_table_grid`,
  `scripts/audit_table_inventory.py` 의 **ITEM_STATUS 룰북**(헤딩→항목 분류. 이미 존재)
- ⚠ 방법론: 이 도구가 §2-B 표(표본 40건 기반)를 **검증하거나 반증**해야 한다. 준비 중
  "per-topic 주석 섹션이면 주석이 통째 유실된다"는 가설을 세웠는데 실제 DB 를 보니
  **틀렸다**(SNT다이내믹스 3,824행 정상 적재). 표본 추론은 전수로 확인하기 전엔 가설이다.

**T3. `scripts/audit_db_waste.py`** — §3 을 **반복 실행 가능한 원장**으로.
- W1 반복도(`avg_width × rows` vs `n_distinct`) · W2 미사용 인덱스(+`stats_reset` 창 확인
  +코드 grep) · W3 상수/NULL 컬럼 · W4 패딩 이론치 · bloat · 코드 참조 0 테이블
- 산출: `docs/qa/db_waste_ledger_<date>.md`

**T4. pre-2015 타당성** — 층화표본 200 filing(1999~2014)에 `layer2_forward_cells.py` 로
파싱 성공률·단위 미선언 비율·셀 수/filing 측정 → 82,005건 환산. 적재는 별도 결정.

### Phase 2 — 값 정확성 수정 (T1 결과가 범위 확정)

**F1. 단위 판정을 토큰 리스트로** — §2-A 5종 동시 해결
```
detect_unit_declaration(text) -> int | None      # 기존 시그니처 유지(호출부 다수)
detect_unit_tokens(text)      -> list[str]       # 신규: ['백만원','천USD'] 순서대로 전부
```
`fin2.extract.text.declared_unit` 호출부 정책:
- 금액 토큰이 **하나라도** 있으면 표 적재 (`매, 백만원` 폐기 해소)
- 비금액 토큰만 → 적재하되 `value_won=NULL`, `unit_source='non_monetary'`, 원문 셀 문자열 보존
- 혼합 → 적재. 열별 단위를 `col_label` 로 확정 가능한 열만 `value_won` 채우고 **확정 못 하면 NULL**
  (지금은 "결측 > 오염" 원칙이 **표 단위**여서 깨끗한 열까지 함께 버렸다 — 열 단위로 내린다)
- 모든 경우 `unit_decl_raw` 로 원문 선언 보존 → 계층3 이 나중에 해석 가능

**F2. `header_hint` B안** — 이미 작성된 설계안(`docs/plans/layer2_header_hint_lossless_2026-07-30.md`)
을 그대로 실행. 계층3 가드(§4)를 **같은 커밋에** 포함.

### Phase 3 — 신규 추출기 (§2-B 구멍 메우기) · T2 셀 수 순서로

**공통 설계 — 항목마다 파서를 새로 만들지 않는다.** 오늘의 D&A 교훈(항목별 전용 추출기 금지,
공통 해석 계층)을 적용한다:

```
① 섹션·헤딩 위치 확정  →  ② 표 그리드화(expand_table_grid, 기존)  →
③ 표 형태 분류(키-값 / 행렬 / 목록)  →  ④ 항목별 얇은 매핑 카탈로그
```

- **저장 형태**: `biz_section_tables`(`grid jsonb`) 패턴을 확장한 **범용 `report_section_tables`**
  하나 + 항목별 얇은 뷰/매핑. 항목마다 테이블을 새로 만들면 스키마가 폭발하고
  용량·유지보수가 나빠진다. 205 MB 로 이미 검증된 패턴이다.
- **우선순위(투자 활용도 × T2 셀 수)**:
  1. **사채·차입금 미상환 잔액 5종** (회사채·단기사채·기업어음·신종자본증권·조건부자본증권)
     → 만기구조. 표 서식이 정형(DART 표준 서식)이라 난도 낮고 가치 높다
  2. **감사의견 + 핵심감사사항** → 리스크 신호
  3. **대주주 등과의 거래내용**(특수관계자) → 터널링
  4. **종속회사·계열회사 현황(상세)** → 연결 구조·지배구조
  5. **우발부채·약정·소송** → 표+서술 혼재. 표만 먼저
  6. **파생상품거래 현황** · **자금조달·사용실적** · **원재료 가격**
  7. **이사회·감사제도** → 지배구조 스코어
- **API→문서 전환 판정표** 작성: 각 항목의 현재 소스(API/문서)를 표로 확정하고, 문서에서
  뽑을 수 있는 것은 문서 유래로 옮긴다(CLAUDE.md 원칙 + 원문 대조 가능성 확보)

**★ 용량 규율(사용자 요구)** — 신규 항목마다 **적재 전에** 다음을 문서화하고 착수한다:
행 수 추정 · 바이트/행 · 총 GB · **그 지표를 실제로 쓰는 화면/계산식**. 쓰는 곳이 없으면
적재하지 않는다. 서술형 원문은 **표에서 얻을 수 없는 경우에만**, 그리고 요약이 아니라 원문
포인터(rcept_no + 섹션 offset)로 저장한다.

### Phase 4 — 스키마 축소 + 재적재 1회

**F3. `report_tables` 정규화** (W1·W3·W4 + F1·F2 를 **한 번의 재적재**에)
- 신규 `report_tables`: PK `(rcept_no, statement, basis, table_seq)` +
  `table_title`·`unit_decl_raw`·`declared_unit`·`parsed_at`
  → 라인 테이블에서 `table_title`·`parsed_at` **drop** (**~37 GB**)
- `statement`·`unit_source` drop(note 상수) · `corp_code` drop(filings 조인) ·
  `rcept_no` → `bigint` · 컬럼 재배치 (**~6 GB**)
- 신규 `value_raw text` — 비금액/미확정 셀 원문. 정보 손실 0 의 유일한 비용
  (`value_won IS NULL` 행에만 채우므로 회수량보다 훨씬 작다)
- `header_hint text` + 부분 인덱스 (설계안 §3)
- 미사용 인덱스 drop (**~7.7 GB** — 재적재 불필요, **먼저 해도 된다**)

⚠ **`delete-then-insert` 금지** — 2026-07-27 에 이것으로 디스크 100% → 백필 전멸.
`scripts/full_reload_after_sanitize.sh` 의 **TRUNCATE 후 순수 INSERT** 를 쓴다(오늘 2회 검증됨).

**F4. 데일리 배선 (§2-C P0)** — `docs/runbook_new_parser_pipeline_integration.md` 체크리스트:
- `report_lines` 본문을 `collect_new.py` **두 call site**(메인 + `--standardize-only` 재개)에 배선
- Phase 3 신규 추출기도 동일하게 두 call site
- 소급 백필은 자동이 아니다 → 위 전량 재적재로 처리

### Phase 5 — 회귀 방지

`scripts/dq_assertions.py` 에 추가 → `dq_nightly.py` 가 이미 호출하므로 야간 자동:

| 어서션 | 기준 | 막는 사고 |
|---|---|---|
| `bytes_per_row` | 테이블별 상한 초과 | 컬럼 추가로 조용히 비대해짐 |
| `column_repetition` | `avg_width×rows / n_distinct` 이탈 | W1 재발 |
| `unused_index` | `idx_scan=0` 30일 이상 | 인덱스 쓰레기 |
| `dead_tuple_ratio` | > 20% | bloat |
| `orphan_table` | 코드 참조 0 테이블 등장 | `financial_facts` 27 GB 재발 |
| `unit_contamination` | 비금액 `col_label` 인데 `value_won` 채워짐 | §2-A 재발 |
| `daily_body_load` | 최근 공시에 `report_lines` 0행 | §2-C P0 재발 |

T1·T2 는 전수 스윕이라 야간 부적합 → **월 1회** 실행으로 `docs/qa/` 에 절차 기록.

---

## 5. 수정 대상 파일

| 파일 | 변경 |
|---|---|
`parser/common/amount_normalizer.py` | `detect_unit_tokens()` 신규, `_UNIT_DECL_RE` 다중 토큰 |
`fin2/extract/text.py` | `declared_unit` 반환 확장, 표 폐기를 **열 단위**로 |
`fin2/extract/report_lines.py` | `value_raw`·`header_hint`·`unit_source` 방출, `report_tables` 행 |
`parser/xml/table_extractor.py` | `keep_header_rows` opt-in, `_header_rule_name()` |
`collector/models.py` · `collector/db.py` | `ReportTable` 신규 + 컬럼 재설계 + 인덱스 drop 마이그레이션 |
`fin2/layer3/combine.py` · `note_da.py` | `header_hint IS NULL` 가드, `report_tables` 조인 |
`scripts/collect_new.py` | 본문 + 신규 추출기 **두 call site** 배선 |
`scripts/dq_assertions.py` | 어서션 7종 |
신규 `fin2/extract/section_tables.py` | §2-B 범용 섹션 표 추출(항목별 파서 대신) |
신규 `scripts/audit_unit_declarations.py`·`audit_document_census.py`·`audit_db_waste.py` | 검증 3종 |

---

## 6. 검증

1. **단위 census** 전수: `비금액단독 폐기 = 0` · `금액표 폐기 = 0` · **오염 확정 셀 = 0**
2. **문서 census** 전수: 미귀속 숫자 셀 = 0, **또는** 전 버킷에 명시 사유 문서화
   (서술형 / 타 테이블 중복 / 투자 무관)
3. **충실성 2종** 전수 재실행: 역방향 100.000% / 적재누락 0 /
   열절단·헤더드롭·라벨없음·설명안됨 = 0
   ⚠ 불일치가 나오면 **먼저 검사기를 의심**한다 — 검사기 버그를 두 번, 휴리스틱 거짓양성을
   다섯 번 겪었고 오늘도 D3 오진이 있었다. `scripts/show_note_source.py` 로 원문 직접 확인
4. **원문 대조 표본**: 신규 적재된 비금액/혼합 표 30건 + 신규 항목(사채·감사의견 등) 각 10건을
   원문에서 직접 확인. 집계 통과로 끝내지 않는다
5. **용량**: `audit_db_waste.py` 재실행 → 109 GB → **목표 65 GB 이하**(`pg_database_size`).
   Phase 3 신규 적재분은 항목별 GB 를 사전 추정치와 대조
6. **회귀**: `pytest` 253/253 · std_v3 D&A FY 커버리지 97.4% 이상 유지 · 항등식 위반 0 · 음수 0
7. **Gate B**: `scripts/gateb_audit.py` value_diff = 0
8. **데일리**: `collect_new.py --days 3` 실행 후 신규 rcept_no 에 `report_lines` 행 존재 확인

---

## 7. 실행 순서

```
Phase 0  오늘 변경분 커밋 + 테스트 253/253                      (선행 필수)
Phase 1  T1·T2·T3·T4 작성·실행 ─ 전부 읽기 전용, 병행 가능
         ↓ T1 → F1 범위 확정 · T2 → Phase 3 우선순위 확정
즉시     미사용 인덱스 drop 7.7 GB                              (재적재 불필요)
Phase 2  F1 단위 + F2 header_hint (+계층3 가드 같은 커밋)
Phase 3  신규 추출기 — T2 셀 수 순서로. 항목마다 용량 사전 추정
Phase 4  F3 스키마 축소 + F4 데일리 배선 → **재적재 1회**(~5h)
Phase 5  야간 어서션 + 검증 §6 전항
         ↓
별도결정 pre-2015 82,005건 (T4 결과 보고 후)
```

**★ 재적재를 한 번만 한다.** F1·F2·F3 전부 재적재를 요구하므로 묶는다. Phase 3 는 별도 테이블
적재라 재적재와 독립적이며 병행 가능하다.

> 계획 문서는 승인 후 `docs/plans/` 로 옮기고 마스터 허브
> (`docs/plans/rearchitecture_4layer.md`)에서 링크한다.
