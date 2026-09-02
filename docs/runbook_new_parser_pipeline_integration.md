# Runbook — 새 파서/로더 추가 시 데일리 파이프라인 편입 + 소급 백필 체크리스트

> **왜 이 문서인가.** 이 프로젝트는 보고서 파싱·DB 적재 로직을 새로 추가하거나 개선해도
> **자동으로 전부 반영되지 않는다.** 세 가지를 각각 챙겨야 빠짐이 없다:
> 1. **신규 공시(전방)** — `collect_new.py`(데일리 launchd, 18:00)에 **배선**해야 매일 자동 처리됨.
> 2. **과거 데이터(소급)** — 파서를 고쳐도 이미 std_v2/DB에 적재된 과거분은 **자동 재파싱 안 됨** → 전수 백필 필요.
> 3. **검증** — 회귀 테스트 + 표본 대조로 값 정확성 확인.
>
> 하나라도 빠지면 "새 항목이 신규 기업엔 들어가는데 과거엔 없다" 또는 "코드는 있는데 매일
> 안 돌아 데이터가 안 쌓인다" 같은 조용한 누락이 생긴다. **새 파서/로더를 추가하는 모든 작업은
> 이 체크리스트를 따를 것.**

---

## 배경 — 데일리 파이프라인이 실제로 하는 일

`com.tjfinance.collect` (LaunchAgent, 매일 18:00) → `scripts/collect_new.py --days 3 --timeout 600
--refresh-universe`. 실행 순서(함수명):

| 단계 | 함수 | 하는 일 |
|---|---|---|
| ⓪-1 | `_sync_regulatory` | 시장조치(관리종목/상장폐지/매매정지) |
| ⓪-2 | `_sync_capital` | 자본이벤트(증자/감자/CB·BW·EB/자기주식) |
| ⓪ | `collect.refresh_universe` | 상장 유니버스 갱신(신규상장/상폐) |
| ① | `collect.discover_recent_corps(days)` | 최근 N일 정기공시 낸 기업 탐지 |
| ② | `sync_filings(force=True)` | 공시목록 동기화 |
| ③ | `run_downloads` | 원본 XML 다운로드 |
| ④ | `_standardize_with_timeout` → `run.process_corp` | **파싱·표준화·분기·달력**(fin2 파이프라인) |
| ④-2 | `_sync_cf_da` | D&A 복원(cf_da + expense_nature) |
| ⑤ | `_verify_and_log` → `run_dq_gate` | DQ 게이트(보고서==DB 재검) |
| ⑤-1 | `_sync_biz_metrics` | 생산능력/가동률 **+ 부문·수출입 매출**(biz_metrics) |
| ⑤-2 | `_sync_order_backlog` | 수주상황(order_backlog) |
| ⑤-3 | `_sync_periodic_apis` | 주주환원 API 6종(배당/자기주식/직원/출자/보수) |
| ⑥ | `_refresh_valuation_daily` | valuation_daily matview 갱신 |

### ★ 결정적 사실 두 가지

1. **④는 "아직 std_v2에 없는 (기업, 연도, 기간)"만 처리한다.**
   `collect.needs_standardize_corps()` 의 SQL이 `NOT EXISTS (SELECT 1 FROM std_financials_v2 ...)`
   라서, **이미 표준화된 과거 데이터는 파서를 고쳐도 재처리되지 않는다.** 개선은 앞으로 들어올
   신규 공시에만 자동 적용된다.

2. **⑤-x 로더들은 collect_new.py에 명시적으로 호출을 추가해야 돈다.**
   새 로더 모듈(`fin2/extract/*.py`, `collector/*_sync.py` 등)을 만들어도, `collect_new.py`의
   ④/⑤ 구간에 `_sync_xxx(affected)` 호출을 넣지 않으면 데일리에 **절대** 편입되지 않는다.

---

## 체크리스트 A — 데일리 파이프라인 배선 (신규 공시 전방 반영)

새 파서/로더가 매일 신규 공시에 자동 적용되게 하려면:

- [ ] **A1. 로더 함수 작성** — 멱등(rcept 또는 corp+fy 단위 delete-then-insert), corp 리스트를
      인자로 받는 형태. 개별 기업 실패는 격리(`try/except`, 로그 후 계속)해서 전체 파이프라인을
      막지 않게 한다(기존 `_sync_biz_metrics` 등과 동일 패턴).

- [ ] **A2. `collect_new.py`에 `_sync_xxx(corps)` 래퍼 추가** — **비치명적**으로 감쌀 것
      (`try/except Exception` + `logger.warning`). 실패해도 본 수집은 계속되어야 한다.

- [ ] **A3. ★ 두 call site 모두에 배선** — collect_new.py의 ④/⑤ 구간은 **두 군데**서 호출된다:
  - **메인 경로** (`main()` 하단, ⑤-1~⑤-3 나열된 곳)
  - **재개 경로** (`--standardize-only` 분기 안, `_sync_cf_da`~`_refresh_valuation_daily` 나열된 곳)
  - **둘 다에 추가하지 않으면** 재개 모드(타임아웃 스킵분 재처리 등)에서 누락된다.

- [ ] **A4. 순서 주의(파이프라인 접점 로더)** — std_v2 컬럼에 영향을 주는 로더(D&A처럼
      표준화 규칙이 소비하는 note.* 등)는 **추출 → store_facts → standardize_corp →
      derive_quarters_corp → calendarize_corp** 순서를 지켜야 한다. `calendar` 단독은 stale.
      (참고: `collector/cf_da_sync.py`, `collector/expense_nature_sync.py` 가 정석 패턴.)

- [ ] **A5. 이중 계상 방지** — 같은 canonical을 여러 소스가 방출하면(예: cf_da vs expense_nature),
      뒤 로더는 앞 로더가 못 채운 잔여만 타겟(`WHERE ... IS NULL`)하고, acontext 토큰을 맞춰
      `ON CONFLICT` 갱신이 되게 한다(`uq_fact_v2_cell = rcept_no+acode+acontext_raw`).

---

## 체크리스트 B — 과거 데이터 소급 백필 (retroactive)

파서를 새로 추가/개선했으면, 과거 전수에 적용하려면 **반드시 별도로** 백필을 돌려야 한다.
(자동 안 됨 — 위 ★결정적 사실 #1 참조.)

- [ ] **B1. 백필 방식 선택:**

  | 개선 대상 | 소급 백필 명령 |
  |---|---|
  | 재무제표 face/note 파싱(fin2 추출·매핑) | `run.py parse-reset --all` → `run.py parse`, 또는 `run.py fin2-all [--skip-existing]` |
  | Track B 텍스트 재분류(새 계정 alias) | `run.py parse-reset --track-b` → `run.py parse` |
  | 생산/매출(biz_metrics) | `scripts/collect_biz_metrics.py` / `scripts/collect_sales_metrics.py --latest --skip-existing` |
  | 수주(order_backlog) | `scripts/collect_order_backlog.py --skip-existing` |
  | 주주환원 API | `scripts/collect_periodic_apis.py --api <..> --years 2015-<올해> --skip-existing` |
  | 대주주/지분 | `scripts/collect_shareholders.py --year <..> --skip-existing` |
  | D&A(cf_da/expense_nature) | `python -c "from collector.cf_da_sync import sync_cf_da; sync_cf_da(year_min=..)"` 등 |
  | 계층3(`combine.py`) 규칙 변경 — std_v3 값 자체가 바뀜 | `build_std_v3.py --corp <대상> --year-min ..` **다음에 반드시** 같은 corp 목록으로 달력 재동기화도(아래 참고) — 둘 중 하나만 하면 `dq_assertions.py::calendar_orphan_cq`(ERROR) 유령행 발생 |

- [ ] **B2. `--skip-existing` 재개 안전성 확인** — 장시간 백필은 중단 후 재개가 가능해야 한다.
      DB만으로 "이미 시도함"을 구분 못 하는 경우(예: 매출표 자체가 없는 기업)는 별도 상태파일로
      추적(예: `scripts/nightly_gap_fill_backfill.py`의 Phase 3 로컬 JSON).

- [ ] **B3. DART 쿼터 유무 판단** — 로컬 파일 파싱(fin2/biz_metrics/order_backlog/expense_nature)은
      쿼터 무관·수시간. **DART API 호출(주주환원/대주주)** 은 하루 40,000콜 공유 한도라 야간
      분할 필요. 연속 `020`(사용한도초과) circuit breaker가 있는지 확인.

- [ ] **B4. 장시간 잡은 사용자 실행/야간 자동화로** — 에이전트가 백그라운드로 장시간 잡을 넘기지
      않는다(운영 교훈). 반복 백필은 launchd 야간 잡으로(예: `com.tjfinance.gapfill`, 완료 시
      자기해제). 상세: `deploy/launchd/README.md`.

- [ ] **B5. std_v3 값을 바꾸는 백필이면 `calendar_v3` 재동기화도 같은 세트** —
      `fin2.standardize.calendar_v3.calendarize_corp_v3(session, corp)`가 corp+basis
      단위 delete-then-insert라서, std_v3만 바꾸고 그 corp의 달력을 다시 안 돌리면
      예전 std_v3 행을 가리키던 달력분기가 유령행으로 남는다(`dq_assertions.py::
      calendar_orphan_cq`, ERROR). 실측 사례(R63, `docs/PARSING_RULES.md`): std_v3
      백필(1,117개사) 직후 orphan 345건 발생 → 같은 corp 목록으로
      `calendarize_corp_v3()` 재실행해 0건으로 해소. **std_v3 백필 스크립트 자체엔
      이게 자동 배선돼 있지 않다** — 매번 수동으로 이어서 돌릴 것.

---

## 체크리스트 C — 검증

- [ ] **C1. 회귀 테스트 추가** — `fin2/tests/test_*.py`(실측 파일 기반, DB 비의존) 또는
      `tests/test_*.py`(합성 오라클). `python fin2/tests/test_xxx.py`, `python tests/run_all.py`.
- [ ] **C2. 표본 원문 대조** — 유명 기업 몇 곳을 DART 공시 원문과 값 대조(스케일/단위 포함).
- [ ] **C3. Gate B 무영향 확인** — note.*/합성 fact 등 non-face 추가는 face 재감사(gb_fail_a,
      line_value_diff)에 변화가 없어야 한다. `run_dq_gate` 표본 실행으로 확인.
- [ ] **C4. AppTest 무예외** — 앱에 노출한 경우 `streamlit.testing.v1.AppTest`로 렌더 확인.
- [ ] **C5. 단위/항등식 가드** — 값이 매출 대비 현실 범위인지, EBITDA=영업이익+D&A 같은 항등식이
      성립하는지 표본 확인.

---

## 요약 — 새 항목 추가 시 "3층 모두" 확인

```
① 배선(A)    : collect_new.py 두 call site + 비치명 래퍼 + (파이프라인 접점이면) S→Q→C 순서
② 소급(B)    : 과거 전수 백필 명령 실행(자동 아님) + 재개 안전성 + 쿼터 판단
③ 검증(C)    : 회귀 테스트 + 원문 대조 + Gate B 무영향 + 단위/항등식
```

**하나라도 빠지면 조용한 데이터 누락이 생긴다.** 특히 자주 잊는 것: **A3(두 call site)** 와
**B(소급 백필은 자동이 아님)**.

## 참고 — 실제 사례(정석 패턴)

- Phase 2(주주환원): `collector/dart_periodic.py` + `scripts/collect_periodic_apis.py` + collect_new ⑤-3 배선
- Phase 3(매출): `fin2/extract/sales_section.py`(→ `parse_biz_metrics`에 통합) + ⑤-1 재사용 + `scripts/collect_sales_metrics.py`
- Phase 4(D&A): `fin2/extract/expense_nature.py` + `collector/expense_nature_sync.py` + collect_new ④-2 배선 + `extended_financials` 뷰 확장
- 소급 백필 자동화: `scripts/nightly_gap_fill_backfill.py`(야간, 완료 시 자기해제)
