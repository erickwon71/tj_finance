# TODO — '사업의 내용' 계층2 신설 실행 체크리스트 (2026-08-09)

> 설계 = [`biz_content_layer2_migration_2026-08-09.md`](biz_content_layer2_migration_2026-08-09.md)
> (검토·확정 완료, §7 열린 결정 3건 확정). 마스터 허브 = [rearchitecture_4layer.md](rearchitecture_4layer.md).
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. **이 문서는 계획일 뿐 — 실행은 별도 승인 후 착수.**
> [파서/로더 파이프라인 편입 절차](../runbook_new_parser_pipeline_integration.md)를 Phase 3(신규
> 계층2 배선)·Phase 4(소급 백필)에 그대로 적용.

---

## Phase 0 — 실측 선결 (계획 §7-3) — ☑ 완료(2026-08-09)

- ☑ **0-1.** `scripts/probe_order_backlog_reparse_cost.py` 신설(단, `_load_root`+
  `find_order_subsections`만 시간측정 — `map_order_table`은 순수 리스트 처리라 비용 무시 가능).
  전체 모집단(annual, XML 있음) = **53,952건**, 표본 500건(seed=42) 결과: 평균 **103.8ms**·
  중앙값 71.7ms·p95 337.8ms, 결측 0·오류 0, 소제목표 586건 발견(표본 전체 합계).
  → **전체 추정 소요시간 = 5,602초(93.4분)**, 단일 프로세스 순차 실행 기준.
- ☑ **0-2.** 93.4분은 "수 시간대"가 아니라 기존 유사 백필들(`build_std_v3 --all` 62분,
  `backfill_shares_transcribe.py` 63.8분)과 같은 규모 — **복잡한 샤딩 불필요, 단일 실행으로
  충분**하다고 판단. Phase 5 실제 백필 시점에 필요하면 기존 `--shard a/n` 패턴을 언제든 붙일 수
  있으나 기본안은 단일 배치.

## Phase 1 — 스키마 변경 (계획 §8-1) — ☑ 완료(2026-08-09)

- ☑ **1-1.** `collector/models.py::BizSectionTable`에 `domain` 컬럼 추가
  (`String(20)`, `nullable=False`, 인덱스 `ix_biz_sec_domain` 추가). docstring을 "생산능력/
  생산실적/가동률" 한정 문구에서 4개 도메인(production/sales/catalog/order_backlog) 공용으로
  갱신(현행 데이터가 이미 sales/catalog를 담고 있었는데 문서만 stale했던 것도 같이 정리).
- ☑ **1-2.** 마이그레이션 `2026_08_biz_section_tables_domain`(`collector/db.py`) — 기존
  528,564행 소급 채움, **순수 SQL, 재파싱 불필요**(계획 §4). 매핑은 구현 전 `SELECT DISTINCT
  metric`(35개 값) + 각 파서 소스코드(`biz_section.py`/`sales_section.py`/`biz_catalog.py`)의
  literal 대조로 **실측 검증**(R0, 짐작 금지):
  - `biz_section.py`는 `capacity`/`output`/`utilization`(+4가지 조합) **만** 방출 → `production`
  - `metric='sales'`는 **두 파서가 공유**(`sales_section.py` 전용이 아님!) —
    `biz_catalog.py:266` 주석이 "매출개요/매출유형별 등 카탈로그 보강 라인도 sales_section과
    같은 `'sales'`로 의도적으로 통일한다"고 명시 → `sales`(출처 무관 통일, 다운스트림
    `biz_metrics.metric='sales'` 소비 방식과 일치)
  - 그 외 나머지(전부 `biz_catalog.py`의 `CATALOG` 규칙표 라벨) → `catalog`
  - `init_db()` 실행 결과: `production` 141,646 · `sales` 63,167 · `catalog` 323,751 · NULL
    **0건**, 합계 528,564 = 마이그레이션 전 총행수와 정확히 일치.
- ☑ **1-3.** UniqueConstraint `(rcept_no, table_ord)` 재검토 완료 — 현재 한 필링 안에서
  production→sales→catalog 순으로 `table_ord`가 이어붙는 방식(`biz_section.parse_biz_metrics`)
  이라 domain 간 번호 충돌 없음. `order_backlog` 편입(Phase 2)도 같은 필링의 이어붙이기 순번에
  포함시키면 제약 변경 불필요 — 별도 스키마 변경 없이 진행 가능 확인.

## Phase 2 — 계층2 신설 모듈 (계획 §3.1, §8-2) — ☑ 완료(2026-08-09, 2-4는 Phase 3로 재배치)

- ☑ **2-1.** `fin2/layer2/biz_raw_tables.py` 신설(+`fin2/layer2/__init__.py`). **당초 계획과
  다르게 구현**: 탐지 함수를 물리적으로 이관하지 않고, production/sales/catalog 3도메인은
  기존 `biz_section.parse_biz_metrics()`(탐지+매핑 동시 수행, 이미 검증된 코드)를 **그대로
  호출**해 반환값의 `section_rows`(raw grid) 절반만 취하고 `metric_rows`는 버림 — 계층3(Phase 3)가
  그 grid를 다시 읽어 재계산하므로 여기서 버려도 무손실. order_backlog는 원본 grid 저장이
  전혀 없었으므로(§2) `find_order_subsections`를 직접 호출하는 신규 코드로 구현. **이관 대신
  재사용을 택한 이유**: `map_biz_table`/`extract_sales_from_root`/`extract_catalog_from_root`
  내부에서 탐지와 매핑이 강하게 얽혀 있어 물리적으로 뽑아내는 리스크가, 이미 그림자로 존재하는
  결과값 중 절반만 취하는 쪽보다 훨씬 큼(검증된 코드 무변경 유지).
- ☑ **2-2.** `extract_biz_raw_tables(file_path, corp_code, fiscal_year) -> list[dict]` 구현.
  order_backlog 도메인은 `narrative`에 `"{heading} (단위 : {unit})"` 형태로 단위를 함께
  인코딩(전용 unit 컬럼 없이도 `_narrative_unit()`으로 Phase 3가 그대로 복원 가능 — 기존
  `map_biz_table`이 `bt.narrative`에서 단위를 뽑는 것과 동일 패턴 재사용, 스키마 변경 불필요).
- ☑ **2-3.** `store_biz_raw_tables(session, rcept_no, rows)` — **rcept_no 단위**
  delete-then-insert(계획 §7-2 확정 스코프 반영) 구현 완료.
- ☑ **검증(신규 추가, `scripts/probe_biz_raw_tables_parity.py`)**: 표본 50개 필링 —
  production/sales/catalog **658행 대조, 불일치 0건**(기존 `parse_biz_metrics` 결과와 완전
  동일 — 재사용 방식이 안전함을 실측 확인). order_backlog 표본 10개 필링(35개 표) — narrative
  경유 단위 복원 26/35건(나머지 9건은 원래도 `default_unit=None`이었던 케이스와 일치 —
  `find_order_subsections`가 코마 포함 등으로 이미 `None` 처리한 걸 그대로 재현, 회귀 아님).
  pytest 전체 443 passed(기존 무관 결함 1건 그대로, 무변화).
- ◐ **2-4.** (원 계획: 원 파서 모듈에서 탐지 로직 제거) — **Phase 3로 재배치**. 2-1에서 실제로는
  아무 것도 이관하지 않았으므로 제거할 것도 없음 — 대신 Phase 3에서 `collector/biz_metrics.py`/
  `collector/order_backlog.py`가 DB로 재배선되고 나면 `parse_biz_metrics`/`parse_order_backlog`
  (파일 직접 read하는 **오케스트레이션** 함수, 탐지 함수 자체 아님)가 아무도 안 부르는 죽은
  코드가 됨 — 그 시점에 실제 삭제 여부를 Phase 3에서 결정.

## Phase 3 — 계층3 재배선 (계획 §3.2, §8-3) — ☑ 완료(2026-08-09)

- ☑ **3-1.** `collector/biz_metrics.py::sync_biz_metrics_corp` 재작성 — 파일을 전혀 열지 않고
  `biz_section_tables`(domain IN production/sales/catalog)만 읽어 `BizTable`/`SalesTable`/
  `CaptionedTable`을 재구성 후 기존 `map_biz_table`/`map_sales_table`/`map_catalog_table`을
  그대로 호출(신설 `_map_row()` 디스패처). `find_annual_reports`/`period_groups`(R0)·
  `merge_filings`(R2, `collector/biz_merge.py`)는 **무변경**.
- ☑ **3-2.** `collector/order_backlog.py::sync_order_backlog_corp` 재작성 — `domain='order_backlog'`
  행 조회(`narrative`에서 `_narrative_unit()`으로 단위 복원) → `map_order_table`+
  `_aggregate_if_detail`(기존 로직, 처음엔 빠뜨렸다가 재검토 중 발견해 추가) 호출부만 DB 조회로 교체.
- ☑ **3-3.** `fin2/layer2/biz_raw_tables.py::ensure_biz_raw_tables(session, rcept_no, file_path,
  corp_code, fiscal_year)` 신설 — 이 rcept의 `biz_section_tables` 행이 전혀 없을 때만 온디맨드로
  `extract_biz_raw_tables`+`store_biz_raw_tables` 호출. `sync_biz_metrics_corp`/
  `sync_order_backlog_corp` 양쪽 모두 DB 조회 직전에 호출 — **원문 파일을 여는 지점은 이 가드
  하나뿐**(R1 준수), Phase4 파이프라인 배선 전에도 신규 필링에서 안전.

### 검증 중 발견 + 수정한 버그 2건(계획에 없던 추가 작업)

- ☑ **버그①(Phase1 소급 적용, 도메인 오분류)** — parity 검증(`scripts/probe_biz_layer3_rewire_parity.py`)
  초기 결과 biz_metrics 대칭차 1883/1572건(≈2.4%). 원인 추적: Phase1 마이그레이션이 `metric`
  값만으로 domain을 나눴는데, `metric='sales'`가 **sales_section.py 전용이 아니라 biz_catalog.py도
  공유**(Phase1에서 이미 실측했던 사실 — 그런데 "공유하니까 같은 도메인"으로 잘못 적용, 실제로는
  "어느 파서가 만들었는지"가 domain의 진짜 의미였어야 함)한다는 게 원인. 재구성 시 `map_sales_table`
  vs `map_catalog_table` 중 **틀린 쪽**을 호출하고 있었음.
  **수정**: `fin2/extract/biz_catalog.py::extract_catalog_from_root`가 narrative를
  `"[subsection] caption_raw :: narrative"` 합성 포맷으로 쓰는 걸 이용 — 이 포맷 매치 여부를
  `metric` 값보다 **우선하는 신호**로 승격(`_classify_domain()`에 정규식 검사 추가, 실측:
  production 141,646행 오탐 0·기존 catalog 300,000행 표본 매치 100%로 안전성 확인). 신규 마이그레이션
  `2026_08_biz_section_tables_domain_sales_catalog_fix`로 기존 6,148/63,167(9.7%)건 소급 재분류
  (sales→catalog). 재검증: 대칭차 1883/1572 → **82/82**(0.1%)로 감소.
- ☑ **버그②(narrative 4000자 절단, 무손실 원칙 위반)** — 남은 82건 추적: `biz_catalog.py`가
  narrative를 저장할 때 `[:4000]`으로 잘라온 게(2026-08-01 원 커밋부터 있던 기존 코드, 이번 트랙
  무관) 원인. 계층3 재구성이 이 **잘린** narrative에서 `_catalog_unit()`으로 단위를 복원하려 하면,
  "(단위 : 백만원)" 표기가 4000자 밖에 있는 표(실측: LG 00120021 FY2020 파생상품 거래현황, narrative
  555,655자 중 4000자 지점 이후에 단위표기 위치)에서 **unit만 유실**(값 자체는 grid에서 직접
  나오므로 무변화 확인 — LG 표본 216행 순서·값 완전동일, unit만 전부 None). 실측 스코프:
  domain='catalog' 329,899행 중 **3,128행(0.95%)**이 narrative 길이=4000(절단 가능성).
  **수정**: `Text` 컬럼이라 길이 제약이 없으므로 `[:4000]` 절단 자체를 제거(무손실 원칙 준수로
  복귀). 재검증: 82/82 → **4/4**(0.005%)로 감소, 남은 4건은 **이미 고쳐진 코드가 아직
  재추출 안 된 과거 행**(FY2012 필링, 이번 검증스크립트가 order_backlog 표가 없는 필링은
  재추출을 안 건드리는 한계 때문 — Phase3 재배선 로직 자체의 결함 아님, 직접 재현 확인:
  같은 테이블을 수정된 코드로 재추출하면 unit 정상 복원됨).
- **잔여 항목(Phase5 이후 필요)**: 위 3,128행(과 버그①로 재분류된 6,148행 포함, 전부 narrative가
  옛 코드로 쓰여진 상태)은 실제로 최신 코드로 **재추출**돼야 완전히 해소됨 — order_backlog
  전량 재파싱(Phase5)이 모든 필링을 다시 읽으므로 자연히 같이 해소될 전망이나, Phase5는 원래
  order_backlog 전용으로 스코프됐던 것이라 **명시적으로 다시 확인** 필요(§Phase5 항목에 반영).

## Phase 4 — 파이프라인 배선 (runbook 체크리스트 A, 계획 §6) — ☑ 완료(2026-08-09)

- ☑ **4-1.** (계획 대비 변경) 계획서(§6)는 "계층2 쓰기 → 계층3 읽기" 두 단계를
  `scripts/collect_new.py` 두 call site 각각에 **별도로** 배선하는 걸 전제했으나, **실제로는
  이미 배선돼 있음을 확인**하고 종료 — Phase3-3에서 `ensure_biz_raw_tables`를 신규 함수로
  collect_new.py에 얹는 대신 `sync_biz_metrics_corp`/`sync_order_backlog_corp`
  **내부**(필링별 루프, DB 조회 직전)에 심었기 때문에, 그 두 함수를 부르는 기존 두 call site
  (`_sync_biz_metrics(affected)`/`_sync_order_backlog(affected)`, 메인 경로 L804-808·
  `--standardize-only` 재개 경로 L690-691, **collect_new.py:501-536**)가 그대로 유지된
  채로 이미 "계층2 쓰기(온디맨드) → 계층3 읽기" 순서를 필링 단위로 보장한다. `scripts/collect_new.py`
  자체는 무변경.
- ☑ **4-2.** import 스모크 확인: `import scripts.collect_new` +
  `from collector.biz_metrics import sync_biz_metrics, sync_biz_metrics_corp; from
  collector.order_backlog import sync_order_backlog, sync_order_backlog_corp; from
  fin2.layer2.biz_raw_tables import ensure_biz_raw_tables` 전부 OK — 두 call site가 참조하는
  전체 임포트 체인 무결함 확인.

## Phase 5 — 소급 백필 (runbook 체크리스트 B, 계획 §4) — ☑ 완료(2026-08-09)

- ☑ **5-1.** (계획 대비 변경) 별도 SQL 불필요로 판명 — 5-2의 전량 재추출이 매 행마다
  `_classify_domain()`으로 domain 을 새로 계산하므로, Phase1/Phase3 마이그레이션이 남긴 값은
  5-2 실행과 함께 전부 최신 코드 기준으로 덮어써짐(사실상 자동 흡수).
- ☑ **5-2.** `scripts/backfill_biz_raw_tables.py` 신설(체크포인트 재개 기능 포함) — annual
  53,952건 전량 `extract_biz_raw_tables`→`store_biz_raw_tables` 재실행 완료. **실행 중 발견**:
  `raw_report`가 저장소 루트의 NAS(SMB, `//tjkwon@192.168.0.96/tj_finance_data`) 마운트 심링크라
  전 파일이 네트워크 I/O — 배경 프로세스가 예측불가 간격(6분~60분)으로 13회 `killed`됨
  ([[feedback-pytest-scope-raw-report-symlink]]와 같은 카테고리 오판 위험 — 처음엔 "메모리
  압박"으로 오진단했다가 사용자가 과거 유사사례를 짚어줘서 NAS 원인으로 정정). 단, 그 사례와
  달리 이번은 order_backlog가 원본 저장이 전무해 **전량이 실제로 필요**해서 스코프 축소 불가 —
  체크포인트 파일(마지막 커밋 rcept_no) 로 kill 될 때마다 자동 재개, 사용자가 NAS 재마운트 후
  최종 완주. 결과: 성공 53,952 · 결측 0 · 추출오류 0 · 저장오류 0. 도메인별 최종
  catalog 331,138 · production 142,150 · sales 57,420 · order_backlog 58,864(신규).
- ☑ **5-3.** 재배선된 계층3(Phase 3)로 `biz_metrics`/`order_backlog` 전체 재생성
  (`scripts/collect_biz_metrics.py`/`collect_order_backlog.py`, 전 2,530사·전 연도) — DB만
  읽어 NAS 재접근 없음, biz_metrics 는 1회 kill 후 corp_code 정렬 기준 재개(`--corps` 파일)로
  완주. **biz_metrics**: 2,520/2,530사 적재(빈 10 = R0 정상), 7,809,228행, 오류 0.
  **order_backlog**: 2,529/2,530사 적재, 24,682행, **1건 오류**(`00633835`,
  `OverflowError: cannot convert float infinity to integer` — `_drop_out_of_range`가 이미
  overflow 인 값이 아니라 `inf` 자체를 가정 못 함, 그 회사만 갱신 안 되고 기존 값 유지) — Phase5
  범위 밖 별도 버그로 후속 필요(§ 리스크 메모에 추가).

## Phase 6 — 검증 (계획 §5) — ☑ 완료(2026-08-09)

- ☑ **6-1.** 재배선 전/후 표본(150개사) `biz_metrics`/`order_backlog` diff — `scripts/probe_phase6_before_after.py`
  신설(구코드 `parse_biz_metrics`/`parse_order_backlog`를 원문에 즉석 재실행 → 현재 DB(신규코드,
  Phase5 적재분)와 대조). 결과: `biz_metrics` 568,926행 **대칭차 0건**(완전일치). `order_backlog`
  4,666행 중 **1건**(00539274 대상홀딩스 FY2021)만 불일치 — backlog_amt(1,536,582)는 동일, `unit`만
  구코드 `None`/신규코드 `'백만원'`. 원문 XML 직접 대조(`&cr;수주현황&cr;&cr;(단위 : 백만원)</P>`,
  단위표기가 별도 문단이 아니라 표제 문단 안에 있음)로 **신규코드가 맞음**을 확인 — 구코드의 별도
  단위탐지 로직은 놓쳤던 것을 신규코드가 narrative 전체 재파싱 과정에서 우연히 회수(회귀 아니라
  미세 개선). `00633835`(§리스크 메모의 기존 OverflowError)는 구코드 계산만 스킵, 신규쪽 DB엔
  영향 없어 비교 자체엔 문제 없음.
- ☑ **6-2.** order_backlog 신규 편입 표본 5건 **원문 XML 직접 대조**([[feedback-verify-against-source]]
  원칙) — 3건(STX엔진 FY2014·아이쓰리시스템 FY2019 등) grid 레벨까지 정밀대조, 구조화값 전부
  원문과 완전일치. 부수 발견(이 트랙과 무관한 **기존** 버그): 공용 탐지기 `find_order_subsections`
  (미변경 코드, 구/신 양쪽 동일 재현)가 절 경계를 못 잡고 표제("N. 수주상황" 등)를 뒤에 나오는
  무관한 표(재무상태표·FX민감도·사채만기 등)까지 같은 이름표로 끌고 오는 현상을 3/3건에서 확인 —
  다만 `map_order_table`이 형태 불일치를 걸러내 최종 `order_backlog` 표는 오염되지 않음(6-1의
  완전일치가 그 증거). 싸이맥스 FY2017은 반대로 진짜 롤포워드형 수주현황(기초/신규수주/수익인식/
  기말)이 있는데 `map_order_table`이 그 형태를 인식 못 해 0행 — 커버리지 공백. 둘 다 이번 재배선
  범위 밖 후속과제(§리스크 메모에 추가).
- ☑ **6-3.** Gate B(std_v3 관련 감사) 무영향 확인 — `git diff --name-only`에 std_v3/Gate B 관련
  코드 없음 확인(확인 대상 자체가 없어 즉시 통과).
- ☑ **6-4.** `pytest tests/ fin2/tests/` 전체 회귀 없음 확인 — 443 passed, 1 failed
  (`test_lxintl_facility_table_dropped`, 생산능력 탐지기의 기존 오탐지 버그, 이 트랙과 무관·코드
  무변경). 회귀 0건.

## Phase 7 — 마감 — ☑ 완료(2026-08-09)

- ☑ **7-1.** `docs/PARSING_RULES.md` R1의 "현재 예외 상태" 절 제거(위반 해소 반영) — ✅ 해소 문단으로
  교체 + 부록 B·C 갱신.
- ☑ **7-2.** `docs/plans/rearchitecture_4layer.md` §6 "미해결 위반" 표기를 해소로 갱신 — §0 08-01
  병행 트랙 요약 줄도 함께 갱신.
- ☑ **Phase 2-4 최종 판단**(원 계획: 원 파서 모듈에서 탐지 로직 제거) — **삭제하지 않음**. 실측
  확인(`grep`): `parse_biz_metrics`는 죽은 코드가 아니라 `fin2/layer2/biz_raw_tables.py::extract_biz_raw_tables`
  가 그대로 재사용 중(Phase2 설계대로). `parse_order_backlog`는 프로덕션 경로(`order_backlog.py`)
  에선 더 이상 안 쓰이지만 `fin2/tests/test_order_backlog.py`(추출로직 자체 검증)와 신규
  `scripts/probe_phase6_before_after.py`(전/후 회귀검증)가 계속 사용 — 진짜 죽은 코드가 아니므로
  유지.
- ☑ **7-3.** 메모리 갱신 — 이 트랙 완료 기록 + 커밋 해시 + 잔여 항목 링크(아래 참고).
- ☑ **7-4.** git 커밋(별도 브랜치, default 브랜치 직커밋 금지 정책) — main 머지·push는 사용자
  결정 대기.

---

## 리스크 메모

- Phase 3-3(호출 순서 보장)을 빠뜨리면 데일리 파이프라인에서 신규 filing이 계층2 raw 없이
  계층3만 시도해 "빈 결과"로 조용히 실패할 수 있음 — 반드시 순서 가드 또는 자동 온디맨드 백필
  구현.
- Phase 1-2 domain 역산 채움은 **`metric` 값을 실측 후 매핑**해야 함(짐작 금지, R0) — 구현
  착수 시 첫 단계로 `SELECT DISTINCT metric` 확인.
- (Phase5 실행 중 발견, 범위 밖 후속과제) `collector/order_backlog.py::_drop_out_of_range`가
  BIGINT 상한 초과값만 가드하고 `inf`(무한대) 값 자체는 가드하지 못해 `int(v)` 에서
  `OverflowError` 발생 — `00633835` 1개사만 영향(기존 값 유지된 채 미갱신). 이 트랙과 무관한
  별도 버그, 후속 세션에서 처리.
