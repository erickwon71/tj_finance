# TODO — std_v3 data_quality·period_end·shares_out 백필 실행 체크리스트 (2026-08-09)

> 설계 = [`std_v3_dq_shares_period_backfill_plan_2026-08-09.md`](std_v3_dq_shares_period_backfill_plan_2026-08-09.md)
> (검토·확정 완료, shares_out=계층2 신설 옵션A). 마스터 허브 = [rearchitecture_4layer.md](rearchitecture_4layer.md).
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. **이 문서는 계획일 뿐 — 실행은 별도 승인 후 착수.**
> [파서/로더 파이프라인 편입 절차](../runbook_new_parser_pipeline_integration.md)를 §2(shares 신설)에 그대로 적용.

---

## Phase 1 — `data_quality`·`period_end` (저위험, v2 로직 재사용 이식) — ☑ 완료(2026-08-09)

- ☑ **1-1.** `fin2/layer3/build.py`에 `_dq_cross_year_v3(session, corp_code, basis, col)`
  신설 — `fin2/standardize/build.py::_dq_cross_year`를 std_v3 테이블 대상으로 이식(대상
  `std_financials_v3`, `version`/`is_stub` 필터 없음, `corp_code`+`statement_type`+
  `fiscal_period='FY'`만). 200x→DQ3·30x→DQ2 임계값 그대로.
- ☑ **1-2.** `fin2/standardize/rules.py::validate_equations`·`fin2/standardize/build.py::_future_guard`
  를 `fin2/layer3/build.py`에서 그대로 import(공용 위치 이동은 안 함 — 두 build.py가 이름만
  같고 서로 무관한 모듈이라 순환import 위험 없이 단방향 import로 충분, 중복 정의 회피 완료).
- ☑ **1-3.** `fin2/standardize/build.py::_period_end` 를 `fin2/layer3/build.py`에서 import해
  재사용. `build_corp`가 이미 갖고 있는 `src`(=`select_canonical_rcepts` 결과, basis 무관 1회
  계산) 딕셔너리를 그대로 넘김.
- ☑ **1-4.** `build_corp`의 각 (fy, basis) 완성 지점(`row = StdFinancialV3(...)` 생성 직후,
  `session.add(row)` 직전)에 계획서 그대로 구현 완료. `_VALUE_COLS`에는 안 넣고 `row.data_quality`
  `row.period_end` 명시적 대입.
- ☑ **1-5.** 단위테스트 — `fin2/tests/test_layer3_dq_period.py` 신설: `_future_guard`(미래기간)
  4케이스(과거/오늘/미래/None). **DQ 항등식 위반**은 `validate_equations`를 v3가 그대로
  재사용(재구현 아님)이라 기존 `test_rules.py::test_validate_equations`가 이미 커버 —
  중복 안 함. **교차연도 이상치**(`_dq_cross_year_v3`)는 세션 필요(median 쿼리) — 이 리포의
  `fin2/tests/test_*.py` 관례(전부 DB-free 순수함수, v2의 동형 함수도 pytest 커버 없었음)를
  따라 pytest화 대신 **실 DB 스모크로 검증**: 삼성전자(2015~2025, 90행) 전량 `data_quality`/
  `period_end` NOT NULL 채움 확인 + 경농(00101433)·농심(00108241) FY 전기간 dq=1(현재 std_v3
  값은 이상치 없이 정상 스케일 — 알려진 v2 시절 버그가 이미 std_v3 파이프라인에서 해소된 상태로
  확인, DQ3 실제 트리거는 Phase 3 전량재빌드+실측(§3-5)에서 재확인 예정). `pytest tests/
  fin2/tests/` 전체 443 passed(신규 4건 포함) — 실패 1건(`test_biz_section.py::
  test_lxintl_facility_table_dropped`)은 `git stash`로 이번 변경 되돌려도 동일하게 재현되는
  **기존 무관 결함**(biz_section 파싱, Phase 1 범위 밖) — 별도 트랙 필요.

## Phase 2 — `shares_out` 계층2 신설 (아키텍처 준수, §3.3 확정 설계) — ☑ 전부 완료(2026-08-09)

### 2A. 스키마·모듈 — ☑ 완료
- ☑ **2A-1.** 신규 테이블 모델(`collector/models.py::ReportSharesOutstanding`,
  `report_shares_outstanding`): `rcept_no(PK,FK filings) · corp_code · fiscal_year ·
  fiscal_period · shares_out · as_of_date · source_ref · parsed_at`. 인덱스
  `ix_shares_out_corp_period(corp_code, fiscal_year, fiscal_period)`. `id` 없이 `rcept_no`를
  PK로 둠(계획의 `id` 대신 — 1 filing=1 판독값이라 `report_tables`류 자연키 관례를 따름).
  `init_db()`(`collector/db.py`)로 실제 DB에 생성 완료(신규 DB엔 create_all이 자동 생성).
- ☑ **2A-2.** 신규 추출 모듈 `fin2/extract/shares_transcribe.py` —
  `fin2/extract/shares.py`에 `extract_issued_common_shares_detailed(path) ->
  (shares, matched_label) | None`을 신설(기존 `extract_issued_common_shares`는 내부적으로
  이를 호출하도록 리팩터, **리턴값·동작 100% 하위호환** — 실측 삼성전자 2025 FY로 검증:
  5,919,637,922 동일). **별도 패스**로 결정(계획의 "같은 자리 재오픈 회피" 옵션 대신) —
  report_lines(lxml tree)와 shares(raw-text regex)는 파싱 방식이 근본적으로 달라 같은
  파싱결과를 공유할 수 없고, 파일 재오픈 비용(작은 XML, ~30-40ms/건)이 낮아 기존 검증된
  `note_lines_sync.py`를 건드리지 않는 독립 실패격리가 더 안전하다고 판단.
- ☑ **2A-3.** `store_report_shares(session, rcept_no, ...)` — rcept_no 단위
  delete-then-insert. `shares_out`이 없으면(섹션 미발견) delete만 하고 insert 스킵(R0, 짐작
  금지 — zombie row 방지).

### 2B. 파이프라인 배선 (runbook 체크리스트 A) — ☑ 완료
- ☑ **2B-1.** A1 — `sync_shares_transcribe(corps, year_min, recheck)` (corp 리스트 인자,
  파일 단위 try/except로 개별 filing 실패 격리, corp 바운드 loaded-체크로 재실행 시 자동 재개).
- ☑ **2B-2.** A2 — `collect_new.py::_sync_shares_transcribe(corps)` 래퍼 추가(비치명적
  `try/except Exception` + `logger.warning`, `_sync_layer2_lines` 패턴 그대로).
- ☑ **2B-3.** ★A3 — **두 call site 모두** 배선 완료: 메인 경로(④-5, `_sync_xbrl_instance_lines`
  직후) + 재개 경로(`--standardize-only` 분기 안, 동일 위치). `python -c` import 스모크로
  두 곳 다 확인.

### 2C. 소급 백필 (runbook 체크리스트 B) — ☑ 실행 완료(2026-08-09)
- ☑ 스크립트 `scripts/backfill_shares_transcribe.py` 작성 — `sync_shares_transcribe`를 전체
  기업에 20개씩 배치 호출. **재개는 자동**(rcept 단위 loaded 체크가 내장이라 별도 progress
  테이블·`--skip-existing` 플래그 불요). `--limit`(시험) · `--shard a/n`(병렬) · `--status`
  (진행 현황) 지원.
- ☑ **2C-1.** ★사용자 지시로 Claude 가 Monitor 로 진행상황 스트리밍하며 실행(장시간 잡이라
  원칙은 사용자 실행이나, 이번엔 "네가 모니터 걸고 실행해" 명시 지시 — [[feedback-long-running-commands]]
  예외). 완료: **기업 2,529 · 필링 101,489 · 적재 95,862(94.5%) · 오류 0 · 소요 3,826초(63.8분)**.
  DB 확인: `report_shares_outstanding` 총 97,087행(시험분 포함) · 2,535개 corp_code.
- ☑ **2C-2.** 볼륨 실측 완료(사전 추정 65-75분 vs 실제 63.8분, 근접). 나머지 5.5%(필링
  101,489건 중 5,627건)는 원문에 '주식의 총수' 섹션 자체가 없거나 3-TABLE 탐색 창을 벗어난
  케이스로 추정(R0, 짐작 없이 NULL 유지) — 개별 원인 규명은 후순위(Phase 3 검증에서 스크리너
  영향 재확인 시 필요하면 추가 조사).

### 2D. 계층3 연결 — ☑ 완료
- ☑ **2D-1.** `fin2/layer3/build.py::build_corp`에 `_select_shares_out(session, corp, fy,
  period, src)` 신설, `row.shares_out` 채움(없으면 NULL 유지). 삼성전자 스모크(rollback):
  45행 중 36행 채움(추출 성공분과 정확히 일치), 나머지 9행(섹션 미발견 filing)은 NULL 유지 확인.
- ☑ **2D-2.** 정본선택 규칙 확정·구현: ① 그 (fy,period)의 재무제표 정본 filing(`src` —
  BS>IS>CF 우선순위, period_end 산출과 동일 우선순위 재사용)과 **같은 rcept**의 값 우선
  (provenance 일관성). ② 없으면 그 corp+fy+period를 보고한 아무 filing 중 **rcept_no 최대
  (최신 정정 우선)**로 폴백. `as_of_date`(=filings.period_end_date 근사값, 2A-1 모델독스트링
  참고)는 같은 기간 내 filing 간 사실상 동일값이라 정렬 기준으로는 무의미해 rcept_no 로 대체
  (원안 "as_of_date 최근값 우선"에서 실측 근거로 수정).

## Phase 3 — 전량 재빌드 + 검증 — ☑ 완료(2026-08-09)

- ☑ **3-1.** `build_std_v3.py --all` 실행(사용자 지시로 Claude가 Monitor 걸고 실행). 결과:
  **2,525개 corp · 184,580행 · 3,717초(62분)**. 재빌드 전후 총행수 동일(184,580) — 값 컬럼
  무변경 방증.
- ☑ **3-2.** 컬럼 채움 확인: `data_quality` **100.0%**(184,580/184,580) · `period_end`
  **100.0%** · `shares_out` **94.7%**(174,768/184,580, 2C 백필 성공률 94.5%와 근접). DQ
  분포: 1=184,191(99.8%) · 2=257 · 3=132 — 전부 DQ1로 깔린 맹목적 통과가 아님(§3-5에서 실제
  작동 확인).
- ☑ **3-3.** 스크리너 모집단: `load_population()` **1,852 → 2,520개사**(계획 §1의 기대치와
  정확히 일치, 668개사 전부 회복).
- ☑ **3-4.** 개별 재확인 — 기업은행 FY2025 연결매출 **19,034,517,000,000(19.0조)**, 계획 §1의
  원문 실측값과 정확히 일치(이전 버그: 6,797억, 약 28배 축소). 삼성증권·한국캐피탈도
  population/`load_screening_window` 양쪽에 정상 등장, op_margin 등 비율 정상 범위(기업은행
  19.2%, 이전 757.6% 오류 해소).
- ☑ **3-5.** ★오탐 방지 — 실제 DQ=3 표본 확인(경농 2024·농심 2018은 std_v3에서 이미 정상 스케일로
  해소된 상태라 재현 불가, 대신 신규 발견 사례로 검증): **동국홀딩스**(2023 인적분할로 별도매출
  7.7조→156억 급감, 진짜 구조단절을 정확히 DQ3/DQ2로 플래그 — 오탐 아님) · **제주은행**
  별도재무제표(자산=부채 항등식이 실제로 깨져있음, `validate_equations`가 정확히 캐치 — 이건
  Phase1/2가 만든 문제가 아니라 combine 레이어의 기존 데이터결함을 처음으로 드러낸 것). DQ
  시스템이 실제로 작동함을 확인, 맹목적 전체통과 아님.
- ☑ **3-6.** Gate B 무영향 — 값 컬럼 코드경로 미변경(`_VALUE_COLS` 루프·`combine_full` 호출
  그대로) + 재빌드 전후 총행수 동일(184,580) + 삼성전자 실측값(2015/2020/2025 FY revenue 등)
  재빌드 전후 불변 확인. **전체 XML 대조 Gate B 정식감사(`scripts/gateb_audit.py`)는 별도 장시간
  작업이라 이번엔 미실행** — 필요시 후속 요청.
- ☑ **3-7.** C-1 렌더 스모크 — `load_population`·`load_screening_window`·`load_standard_financials`
  +`compute_ratios`로 기업은행·삼성증권·한국캐피탈·삼성전자 재확인. 원래 버그리포트의 3개 기업
  전부 정상값 확인. `build_tearsheet_pdf`(PDF 렌더 자체, 값 계산과 무관한 표시 레이어)는
  미실행 — 필요시 후속.
  **부수 발견(범위 밖, Phase1/2 무관 기존 이슈)**: 삼성증권 FY2025 `net_income` NULL(다른
  연도는 정상) — combine 레이어 매핑 갭으로 추정, 별도 트랙 필요.

## Phase 4 — 마감 — ☑ 완료(2026-08-09)

- ☑ **4-1.** `docs/PARSING_RULES.md`에 **R12**(발행주식수 — 계층2 cross-cutting 스칼라 전사)
  신설: 색인표·본문 규칙 섹션·부록B 원출처 전부 반영.
- ☑ **4-2.** 마스터 허브(`rearchitecture_4layer.md`) §4(타임라인에 이 트랙 항목 추가)·§5
  (최신 갱신 블록 + 항목2 "shares_out ✅ 완료" 표기) 갱신.
- ☑ **4-3.** 메모리 갱신 — [[std-v3-dq-shares-period-null-2026-08-09]] 완료로 전환, 결과 요약
  + 커밋 해시 + 잔여 항목 링크.
- ☑ **4-4.** git 커밋 — 브랜치 `fix/std-v3-dq-period-shares-backfill` 커밋 `9f7f2aa`
  (main 아님 — CLAUDE.md 정책상 default 브랜치 직커밋 금지, 별도 브랜치 생성). **main
  머지·push는 아직 안 함.**

---

## 잔여 작업 (다음 세션 — 이 트랙 자체는 종료, 아래는 후속 필요 항목)

- ☑ **제주은행(00148832) 별도재무제표 자산=부채 항등식 위반** — 원인규명+수정+검증 완료
  (2026-08-09 같은 날 후속 세션). 원인 = 은행 필링에 본표 외 **신탁계정(trust account)
  보조 재무상태표**가 별도 table_seq로 함께 실림(신탁계정은 자산=부채가 정상, 자기자본 없음).
  옛 서식 본표의 "총계" 라벨이 글자간격 삽입이라 `stage='normalized'`에 머무는 반면 신탁계정의
  깨끗한 라벨은 `stage='exact'`로 잡혀 `_resolve`가 신탁계정을 우선시 → 자산/부채는 신탁계정,
  자본총계는 본표에서 오는 식으로 표가 섞임. `fin2/layer3/combine.py`에
  `_trust_account_table_seqs`(같은 table_seq 안에서 자산총계==부채총계이고 total_equity
  후보가 아예 없을 때만 제외 — 좁고 자기검증 가능한 신호) 신설로 수정. **교훈**: 처음
  "table_seq=0 우선"이라는 일반 규칙을 시도했으나 네오셈(01170865)에서 정반대 사례(table_seq=1이
  정답)를 발견해 회귀 직전 되돌림. 실측: 항등식 위반 41행→0행(기업은행 00149646도 같은
  패턴으로 동반 발견·수정). 상세 = [[std-v3-side-findings-trust-account-net-income-2026-08-09]].
- ☑ **삼성증권(00104856) FY2025 `net_income` NULL** — 원인규명+수정+검증 완료(같은 세션).
  원인 = v3 포팅 시 std_v2의 `rule_net_income_fill`(net_income NULL이면
  controlling_ni+noncontrolling_ni 합산) 이식 누락 — `rule_controlling_ni_fill`(반대방향)만
  포팅됨. 비표준 순이익 라벨('보통주 당기순이익')이 매퍼를 못 통과하면 net_income NULL로
  남던 문제. `combine_full`에 폴백 추가로 수정. 웰크론(00362159) 사례로 EBT−법인세 독립계산과
  정확히 일치 검증(부호반전 케이스 포함). 실측: NULL(controlling_ni는 있음) 470행/119개사→0/0.
- ☑ **DB 반영·재검증** — 영향 119개사(9,734행)만 scoped rebuild(`--corp` 콤마구분, 254초,
  전체 `--all` 62분 불필요 — 두 버그 모두 발동조건이 SQL로 완전히 특정되고 enrichment(capex/
  fcf/net_debt/D&A/EBITDA)는 total_assets/liabilities/equity/net_income을 전혀 참조하지 않아
  scoped rebuild가 곧 완전한 rebuild임을 코드 검토+19개사 전수 대조로 확인). 전체 184,580행
  불변, pytest 443 passed(무관 기존결함 1건 그대로). main 커밋 `9dd4851`.
- ☐ **push 여부 결정** — 로컬 `main`이 `origin/main` 대비 **2커밋** 앞섬(`d707a03`
  data_quality/period_end/shares_out 백필, `9dd4851` 신탁계정+net_income 폴백). working tree
  clean. `git push origin main`으로 동기화할지 사용자 결정 필요(2026-08-09 세션에서 "다른
  할일부터" 선택으로 보류됨).
- ☐ **재설계 본류 복귀** — 이 트랙은 §5 "4번 C-1 렌더 확인" 작업 중 발견된 병행 트랙이었음.
  본류로 복귀하려면: ① C-1 렌더 확인 재개(데이터 정상화 완료로 재개 가능) ② Streamlit UI
  풀스모크.
- ☐ **(별개 트랙, 우선순위 낮음) `layer2_note_heading_fix_verify.py` REGRESSED 2건**
  (00121969·00133812) 원인규명 — [[verification-tools-4-refresh-2026-08-09]] 참고.
- ☐ **(선택) Gate B 정식 XML 대조 감사** — 이번엔 코드경로 미변경 근거로 대체 검증했음
  (§3-6). 더 엄격한 확인이 필요하면 `python scripts/gateb_audit.py --sample 200` 등으로
  원문 재대조(장시간, 사용자 실행 권장).
