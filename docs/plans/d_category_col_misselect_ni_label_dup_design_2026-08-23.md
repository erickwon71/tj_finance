# D 카테고리 — 컬럼오선택(tax_expense 등) + NI라벨중복(01497869) 수정 설계 (2026-08-23)

> 상태: **설계만, 구현 미착수** (`CLAUDE.md` "계획 후 대기" 원칙).
> 배경 메모리: [[fy2024-46-regression-a-b-fixed-2026-08-23]], [[d-category-tax-expense-01201970-01497869-rootcause-2026-08-23]].
> 원문대조 방법론: `docs/PARSING_RULES.md` R9(`feedback-verify-against-source`) 준수.
>
> **★다음 세션 시작점 — 여기부터 Phase 0**: 구현 착수 전, 아직 안 한 것은 "코드
> 실행경로 자체를 실측 재확인"뿐이다(지금까지는 정적 코드분석 + DB값 대조로
> 추정). 버그①은 §1-6 Phase 0(00104573·01201970 두 건, `text.py`에 임시
> 디버그로그), 버그②는 §2-3 Phase 0(01497869 2025Q1 재실행, report_lines 단계
> vs combine.py 단계 확정)부터 그대로 실행하면 된다. Phase 0 결과로 §1-5/§2를
> 갱신한 뒤에도 실제 코드변경은 별도 승인 필요.

## 0. 배경

같은 세션에서 fy≥2024 46건 회귀의 D 카테고리(9건: tax_expense 5·01201970 스케일불일치
2·01497869 계속/중단영업 3항구조 2)를 원문대조로 재조사한 결과 **이전 가설이 둘 다
틀렸고, 서로 다른 두 개의 확정 버그**로 밝혀졌다(①컬럼오선택, ②NI라벨중복). tax_expense
클러스터는 fy≥2024 라이브 `face_audit` fail_a 89건 중 15건 표본 원문대조 **15/15(100%)
동일 패턴**으로 규모까지 확인됐다. 이 문서는 두 버그의 수정을 설계한다.

## 1. 버그 ① — 당기 3개월(Q) 미공시 시 전기 3개월(PFY) 컬럼을 잘못 채택

### 1-1. 확정된 메커니즘 (코드 추적 완료)

DART XBRL(2024+ 필링)의 반기/분기 IS 표는 통상 `[당기3개월, 당기누적, 전기3개월,
전기누적]` 4열 헤더를 갖는다. `fin2/extract/text.py::_interim_cumulative_cols()`
(L90-116)가 헤더 텍스트에서 "누적" 토큰의 **위치**를 찾아
`cum_map = {header_position: period_offset}` (예 `{1: 0, 3: 1}` = 헤더위치1→당기,
헤더위치3→전기)을 만든다. 이 `cum_map`은 소비 시점(`_emit_section`, L899/L931-951)에서
`row.amounts[pos]`로 그 헤더위치를 **데이터 행의 값 배열에 그대로 인덱싱**한다.

문제: 이 인덱싱은 "데이터 행의 값 배열 길이 == 헤더 열 개수"를 암묵 전제한다. 그런데
당기 3개월(Q) 셀이 **원문에 disclosure 자체가 없는** 경우(법인세비용은 분기 단독값
생략이 흔함 — 원문대조로 확인) 그 값이 `row.amounts`에서 **placeholder 없이
통째로 드롭**되어 배열이 3칸으로 압축된다. 이때 `cum_map={1:0, 3:1}`로 이 압축된
3칸 배열을 인덱싱하면:
- `row.amounts[1]` = (압축 후) **전기3개월** 값인데 `off=0`(당기) 라벨로 emit됨 ← **버그 재현 지점**
- `row.amounts[3]`은 범위 밖이라 조용히 드롭(`pos < len(row.amounts)` 가드, L933) — 전기누적 소실

**원문 3건 독립 재현**(모두 이 정확한 메커니즘):
- `00104573`(국일제지, 2025Q3, `20251113000801.xml`): 법인세비용 행 — 당기3개월 TE가
  `ACONTEXT` 자체가 없는 빈 셀. db_won=-138,250,046(`PFY2024dTQQ`=전기3개월)로 저장,
  진짜 값은 report_won=-2,310,052,284(`CFY2025dTQA`=당기누적).
- `01201970`(셀레스트라, 2026H1, `20260814003475.xml`): revenue/cogs/gross_profit/
  controlling_ni **4개 필드 전부** 동일 — db가 `PFY2025dHYQ`(전기 2분기단독)와 정확히
  일치, 진짜 값은 `CFY2026dHYA`(당기누적). 어제 메모의 "스케일불일치"는 오판 —
  배수가 아니라 완전히 다른 기간값이었음(우연히 자릿수가 비슷해 배수처럼 보였을 뿐).
- 같은 필지 필드(EBT, 바로 위 행)는 4열 전부 disclosure가 있어 **정상 추출됨** —
  행 단위 결함임을 확인(테이블 전체가 밀리는 게 아니라, 빈 셀이 있는 행만 밀림).

### 1-2. 규모 재검증 (같은 세션)

fy≥2024 tax_expense 단일필드 fail_a 89건(라이브 `face_audit`, 대부분 2025 Q3) 중
15건 균등샘플을 스크립트(`verify_tax_expense_cluster.py`, 값을 콤마포맷 문자열로
원문에서 grep 후 ACONTEXT의 rel/accum 태그로 분류)로 검증 — **15/15(100%)** 동일
패턴 확정(report_won=0인 4건은 스크립트 로직상 자동판정 불가했으나 2건 수동
원문대조로도 동일 패턴 재확인). 즉 **tax_expense 클러스터는 "패턴 불명확"
(`docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md` §3)이 아니라 사실상 단일
근본원인**이다.

### 1-3. 이미 알려진 인접 사례·자매결함

- `docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md`(00874803, 2025Q3
  tax_expense, "당기 대신 전기 비교컬럼 채택")가 **바로 이 버그의 앞선 목격 사례**였다
  — 당시 "T22와 무관한 별개 트랙"으로 범위 밖 처리되고 재론 지점만 남겨졌다
  (`fin2/layer3/combine.py`의 ACONTEXT 선택 로직부터 — 단, 실제 추적 결과 진짜 위치는
  `combine.py`가 아니라 **`fin2/extract/text.py`**였다, 위 1-1 참고).
- `docs/PARSING_RULES.md` 부록A **T22**(순수 하이픈 음수 `-N` 미인식)는 **동일한
  `cum_map`/`row.amounts` 밀림 메커니즘의 다른 트리거**였다 — T22는 "값이 있지만
  `_NUMBER_PATTERN` 게이트가 숫자로 인식 못 해 드롭"이 트리거였고, **R31로 이미 수정
  완료**(2026-08-17, `_NUMBER_PATTERN`에 하이픈 대안 추가). 이번 버그는 트리거가
  다르다 — **"disclosure 자체가 없어 셀이 진짜로 빈 것"**(파싱 실패가 아니라 원문
  자체가 공란)이라 R31의 수정 범위 밖이고, 별도 트리거로 남아 있었다.

### 1-4. 수정 옵션 비교

**옵션 A — `text.py`/`report_lines.py` 파서 근본수정**: `cum_map` 인덱싱 전에
`row.amounts`를 **항상 헤더 폭만큼 None-padding**해서 위치 정합을 보장(빈 셀을
드롭이 아니라 `None` placeholder로 명시 보존). 근본적이지만:
- `report_lines.py`(L440-499)에도 유사한 별개 `cum_map`/`n_cols` 로직이 있어(T22
  부록A 2026-08-17 "신규 발견·미착수" 메모가 이미 지목) **두 곳을 함께 확인**해야
  누락이 없다 — 파악 안 된 제3의 소비 지점이 있을 위험.
- pre-2024(ACONTEXT 없는 필링)에도 영향 범위가 걸쳐 있어 회귀 위험이 R31급으로 큼
  (R31은 pre-2010 775개사·82,402행 재적재가 필요했음 — 유사 규모 가능성).

**옵션 B — R18(dividends_paid XBRL 인라인 오버레이) 패턴 재사용**: 2024+ 필링은
동일 원문에 `TE[@ACODE][@ACONTEXT]`로 이미 올바른 Track A 사실(`fin2/extract/
xbrl.py`+`acontext.py`, 구조파싱 정확성 직접 확인함)이 존재한다.
`fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_dividends_paid_sign()`
와 완전히 같은 방식으로 — **narrow keyword 후보 필터 + `read_report_face_xbrl()`
canonical 사실 + "후보 1개·사실 1개·크기 1% 이내 일치할 때만 override"** —
`is.tax_expense`용 오버레이 함수를 추가한다.

**권고: 옵션 B를 우선 채택**. 근거:
1. 이미 검증된 안전한 설계 원칙(R0 계층2 canonical-mapping-free 유지, 블랭킷 수정
   금지)을 그대로 재사용 — 새 리스크 표면이 작다.
2. 버그 발생 필링이 **전부 2024+**(ACODE/ACONTEXT 보유율 0.0%→31.7%→98.3%+,
   R18 문서 §5 실측)라 옵션 B의 커버리지가 이 클러스터 거의 전체와 일치한다.
3. 옵션 A(파서 근본수정)는 pre-2024까지 건드릴 잠재 범위가 있어 이번 스코프를
   벗어난다 — 별도 세션 과제로 분리 권고(아래 §4 범위 밖).

단, **R18 자신의 교훈**(설계 예상 92%였는데 실제 적용률은 fail_a 36건 중 6건뿐 —
후보가 2개 이상이면 모호 처리로 스킵)을 그대로 적용해, 이번에도 **구현 후 실측
적용률을 반드시 별도 보고**한다(낙관치를 그대로 믿지 않음).

### 1-5. 구현 스케치 (Phase 1)

- `fin2/extract/report_lines_inline_xbrl_overlay.py`에
  `overlay_tax_expense_value()` 신설 (기존 `overlay_dividends_paid_sign()`와
  병렬 구조):
  - `_TARGET_CANONICAL = "is.tax_expense"`, `statement == "IS"`
  - 후보 키워드: `"법인세비용"`(교집합 아님, 단일 키워드 — dividends_paid의
    "배당"+"지급" 이중키워드와 다름, `is.tax_expense` alias 실측 후 확정)
  - `(basis, is_cumulative)` 키에서 텍스트후보 1개·XBRL사실 1개·크기 1% 이내
    일치할 때만 override(R18과 동일 원칙, §5 블랭킷 금지)
  - `_MIN_FISCAL_YEAR = 2024` 그대로 재사용(같은 커버리지 절벽)
- `extract_report_lines()`(또는 그 호출부) 직후 호출부에 배선 —
  `overlay_dividends_paid_sign()` 호출부와 같은 지점.
- **다른 필드로 확장할지 여부(revenue/cogs/gross_profit/controlling_ni)는
  Phase 1 실측 후 별도 판단** — 01201970 사례가 있지만 발생빈도가 tax_expense보다
  훨씬 낮을 것으로 예상(당기 3개월 disclosure 생략이 세금비용만큼 흔하지 않음).
  Phase 1에서 tax_expense만 먼저 넣고 실측 규모를 본 뒤 §1-4 원칙 그대로
  `is.revenue`/`is.cogs`/`is.gross_profit`/`is.controlling_ni`로 확장 여부를
  사용자와 재상의(범위 확장은 이 설계의 승인 범위 밖 — 별도 승인 필요).

### 1-6. 검증 계획

1. **Phase 0 (구현 전 필수 게이트)** — `_row_to_fact`/`_emit_section` 흐름에
   디버그 로그를 임시로 심어 00104573(정본), 01201970(정본) 두 건에서 §1-1의
   메커니즘을 **실행 중 실측 재현**(지금까지는 정적 코드분석+DB값 대조로 추정,
   실제 실행경로 확인은 아직 안 함). 다른 원인일 가능성을 배제.
2. 단위 테스트(R18 관례대로 `fin2/tests/test_report_lines_inline_xbrl_overlay.py`에
   추가) — 00104573 실측 재현 케이스 포함.
3. fy≥2024 tax_expense fail_a 89건 전수(또는 최소 R18급 무작위 표본) 재실행 —
   적용 건수·전부 report_won 일치(오탐 0)·미적용 건은 근거 있는 스킵인지 확인.
4. pytest 전체(`fin2/tests fin2 tests/` 스코프, [[feedback-workflow]] 준수) 통과.
5. 소급 백필 — `load_report_lines.py`류 재실행 범위는 "fy≥2024 전체"(오버레이가
   no-op 아닌 필링 전부). 정확한 rcept 목록은 Phase 1 구현 시 재산정.

## 2. 버그 ② — 01497869: net_income에 controlling_ni(귀속)값이 오채택

### 2-1. 확정된 증상 (코드 추적은 Phase 0 대상, 아직 미완료)

01497869(티와이홀딩스) 2025 Q1·H1 두 기간 모두 db_won(net_income)이 원문의
`ifrs-full_ProfitLoss`(총계, 지배+비지배 합산 — 진짜 net_income)이 아니라
`ifrs-full_ProfitLossAttributableToOwnersOfParent`
/`ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent`(지배기업
소유주지분 **귀속**분 — controlling_ni 개념)과 정확히 일치했다. 이 회사 IS는
계속/중단영업 분리와 지배/비지배 귀속분리가 **동시에** 있어, "계속영업손실"이라는
동일 라벨이 (a) 총계 레벨(`ifrs-full_ProfitLossFromContinuingOperations`)과
(b) 귀속 레벨(`ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent`,
원문 표시는 "　　계속영업손실"로 들여쓰기됨) **두 번** 등장한다.

어제 메모의 "EBT−세금 2항 항등식으로 못 푸는 3항 구조"라는 결론은 **오판**이었다
— 계속/중단영업 분리 자체는 실패 원인이 아니다. 진짜 원인은 net_income/
controlling_ni 라벨 혼동이며, 이번 주 계속 수정해 온
[[fy2024-46-regression-a-b-fixed-2026-08-23]] "A"(net_income/controlling_ni
컨플릭트, `_resolve_ni_attribution`) 계열의 **잔여 변종**으로 추정된다.

### 2-2. 유력 가설(미확정 — Phase 0에서 코드 추적 필요)

`fin2/extract/text.py::_emit_section()`(L908-930)에 이미 "귀속" 라벨 처리 가드가
있다 — 단, 그 가드는 **"당기순이익의 귀속" vs "총포괄손익의 귀속"**(comp_attr
플래그)만 구분한다. "계속영업손실"/"중단영업손실"처럼 **총계 레벨과 귀속 레벨에
동일 라벨이 중복 등장하는 경우**는 이 가드의 대상이 아니다 — `label_raw`가 (선행
공백 유무만 다르고) 사실상 같은 문자열이면 AccountMapper 퍼지매칭이 depth/귀속여부
구분 없이 둘 다 같은 canonical로 매핑할 가능성이 있다. 이게 사실이라면 combine.py의
NI귀속 충돌해소(`_resolve_ni_attribution`)가 두 후보 중 하나를 골라야 하는데,
이번 주 고친 로직(controlling_ni/noncontrolling_ni 컨플릭트 우선)이 이 특정
2x1축(계속/중단 × 총계/귀속) 조합을 못 잡아냈을 가능성이 있다.

**단, 이건 가설이다 — 실제 코드경로(text.py 단계에서 라벨이 이미 병합되는지,
아니면 combine.py 단계의 conflict resolution 결과인지)는 아직 추적하지 않았다.**

### 2-3. Phase 0 요구사항 (구현 전 필수)

1. 01497869 2025Q1 `20250515002319.xml`을 실제 파이프라인(`run.py extract2` 또는
   동등 경로)으로 재실행해 `report_lines`에 "계속영업손실" 라벨이 몇 개 행으로,
   어떤 `canonical_account`로 emit되는지 직접 확인.
2. 만약 report_lines 단계에서 이미 손실(귀속 레벨만 남고 총계 레벨이 드롭 또는
   병합)됐다면 원인은 text.py의 "귀속" 가드 갭 — §1-4의 comp_attr 로직처럼
   "계속영업"/"중단영업" 라벨도 depth 또는 섹션 헤더("…의 귀속") 기준으로
   총계/귀속을 구분하는 가드 추가.
3. 만약 report_lines엔 둘 다 정상 존재하는데 combine.py 단계에서 잘못된 쪽이
   선택된다면, 원인은 `_resolve_ni_attribution`(오늘 수정한 함수, `combine.py`)
   또는 인접 conflict-resolution 로직 — 그쪽을 재분석.
4. Phase 0 결과에 따라 수정 위치·방식을 재설계(이 문서의 §2는 그 전까지 **가설
   단계**로 표시한다).

### 2-4. 검증 계획

Phase 0 결론 이후 구체화. 최소 조건: 01497869 2025 Q1·H1 두 건 모두 report_won과
db_won 일치 확인 + 이번 주 이미 고친 A 계열 7건([[fy2024-46-regression-a-b-fixed-2026-08-23]])
회귀 없음(재실행 diff) + pytest 전체 통과.

## 3. 파이프라인 편입 체크리스트 (`docs/runbook_new_parser_pipeline_integration.md` 준수)

두 버그 다 **기존 로직의 수정**(신규 로더 아님)이지만 report_lines/std_v3 출력값이
바뀌므로 3층 전부 필요:

- [ ] **① 배선** — `overlay_tax_expense_value()`(버그①)를 `overlay_dividends_paid_sign()`과
      같은 호출부에 추가 — `scripts/collect_new.py`의 **두 call site**(메인 ④구간 +
      `--standardize-only` 재개 경로) 둘 다 자동으로 같이 타는지 확인(오버레이는
      `extract_report_lines()` 직후 호출이라 별도 call site 배선은 불필요할 가능성이
      높지만 **반드시 확인**, 지레짐작 금지 — R9).
- [ ] **② 소급 백필** — fy≥2024 전체 재적재(`load_report_lines.py` 류) + `std_v3`
      재빌드. 정확한 범위(rcept 목록)는 Phase 1 구현 시 재산정.
- [ ] **③ 검증** — §1-6/§2-4의 각 검증 계획 + Gate B 무영향(전수는 아니어도 대표
      표본 재감사) + [[gateb-full-reaudit-is-required-to-close]] 원칙(표본으로 닫지
      말고 전수까지 확인).

## 4. 범위 밖 (명시)

- **옵션 A(`text.py`/`report_lines.py` cum_map 파서 근본수정)** — 이번 스코프
  아님. pre-2024까지 영향 범위가 걸쳐 있어 리스크가 크다. 재론 시 `fin2/extract/
  text.py::_interim_cumulative_cols`/`_emit_section`(L899, L931-951)과
  `fin2/extract/report_lines.py`(L440-499, T22 부록A 2026-08-17 "신규 발견" 메모)
  두 곳을 함께 검토.
- **revenue/cogs/gross_profit/controlling_ni로의 오버레이 확장** — Phase 1
  (tax_expense) 실측 후 별도 승인.
- **01497869 §2의 실제 코드수정** — Phase 0(코드 추적) 결과 없이는 착수하지 않는다.
- fy≥2024 tax_expense fail_a 89건 중 미샘플 74건의 개별 확인 — 15/15 표본으로
  충분한 확신을 얻었다고 판단했으나, 옵션 B 구현 후 전수(또는 대규모 표본) 재실행
  결과가 최종 검증.

## 5. 참고

- `docs/PARSING_RULES.md` R18(패턴 원본), 부록A T22/R31(같은 하류 메커니즘의
  다른 트리거, 이미 고쳐진 자매결함), R24/R25(_ni_attribution_structural_candidates
  계열).
- 메모리: [[fy2024-46-regression-a-b-fixed-2026-08-23]],
  [[d-category-tax-expense-01201970-01497869-rootcause-2026-08-23]],
  [[feedback-verify-against-source]], [[feedback-plan-then-wait]],
  [[parser-pipeline-integration-runbook]].
- 스크립트: `scripts/verify_tax_expense_cluster_2026-08-23.py`(15건 표본 검증에 사용,
  향후 확장 표본 재검증 시 재사용 가능).
