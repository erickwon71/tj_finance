# D 카테고리 — 컬럼오선택(tax_expense 등) + NI라벨중복(01497869) 수정 설계 (2026-08-23)

> 상태: **버그①은 완전 종결**(구현+테스트+커밋 `8322c40`+소급백필+DB실값검증까지
> 전부 완료, 아래 §1-7). **버그②는 미착수**(Layer 2 무죄 확정 + 잘못된 가설 소거만
> 완료, 진짜 원인 미확정, §2-3).
>
> 배경 메모리: [[fy2024-46-regression-a-b-fixed-2026-08-23]], [[d-category-tax-expense-01201970-01497869-rootcause-2026-08-23]].
> 원문대조 방법론: `docs/PARSING_RULES.md` R9(`feedback-verify-against-source`) 준수.
>
> **★버그① 최종 결과(2026-08-23)** — §1-5 구현대로 진행하다 **설계 문서 자체의
> 결함 2건을 실행/원문 대조로 발견해 그 자리에서 수정**했다(§1-7). fy≥2024
> tax_expense fail_a 89건 전수 재실행 — **85/89(95.5%) 적용, 오탐 0건**, 미적용
> 4건은 별개 증상(§1-7-3, 스코프 밖으로 분리). 단위테스트 7건 신설, pytest 전체
> 603 passed. 소급 백필(`load_report_lines.py --fy-min 2024 --recheck` 4.82h→
> `build_std_v3.py --all --year-min 2024 --shard 0-3/4` 137초) 완료, 00104573
> 실 DB 값(`tax_expense=-2,310,052,284`) 직접 조회로 최종 검증.
>
> **★버그① Gate B 전수 재감사 완료(2026-08-24)** — §1-8 참고. tax_expense
> fail_a→pass/pending 전환은 설계대로(85/91), 오탐 0. 단, 재감사 도중
> **버그①과 완전히 동일한 근본 메커니즘이 controlling_ni(00172291)에서도
> 실행으로 재현 확인**됐다 — bug①은 tax_expense 전용이 아니라 "당기 3개월
> disclosure 누락 시 컬럼오선택"이라는 **계정 무관 파서 결함**임이 새로 확정.
> §1-8에 상세, §4 범위결정에 사용자 재상의 필요.
>
> **★사용자 결정(2026-08-24) — 버그① 옵션 A(파서 근본수정)로 전환 확정.**
> §1-8의 controlling_ni 재현(00172291)으로 옵션 B(계정별 오버레이 땜질)가
> 아니라 근본 원인(`table_extractor.py::extract_rows()`의
> `preserve_col_positions` 기본값)을 고치는 쪽으로 방향을 잡았다. **아직
> 미착수 — 구현 계획 초안조차 안 나온 상태**(CLAUDE.md "계획 후 대기" 원칙,
> [[feedback-plan-then-wait]]). 다음 세션은 §1-4 옵션 A의 상세 구현계획부터
> 작성한다(바로 코드 착수 금지).
>
> **★옵션 A 구현계획 작성 완료(2026-08-24)** —
> `docs/plans/gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md`.
> 코드 재확인으로 §1-4 시점엔 몰랐던 사실 3건을 추가 확정: (1) 버그는
> `_emit_section_lines()`의 `cum_map` 소비 경로에만 실존 — 나머지 두 경로는
> 이미 자체 재압축이라 넓게 플래그를 걸 필요 없음(회귀범위 대폭 축소), (2)
> pre-2024 영향범위는 ACONTEXT 존재가 아니라 헤더 텍스트("누적" 토큰)로
> 결정돼 옵션 B의 "2024+" 스코프 논리가 그대로 적용 안 됨(실측 필수), (3)
> `fin2/extract/text.py::_emit_section()`(Track B/fact_v2)에 동일 결함의 미러
> 사본 존재. **아직 미착수** — 구현 전 사용자 결정 3건 대기(그 문서 §8).
>
> **★다음 세션 시작점(우선순위 순, 갱신)**:
> 1. **버그① 옵션 A 구현 착수** — 위 계획 문서 §8의 결정 3건(Track B 동시
>    수정 여부·백필 스코프·오버레이 존치 여부)을 사용자와 확정한 뒤 Phase 0
>    (영향범위 실측)부터. §1-4가 지목한 두 파일
>    (`parser/xml/table_extractor.py::extract_rows()` `preserve_col_positions`
>    파라미터, `fin2/extract/report_lines.py::_emit_section_lines()` L475
>    호출부)을 대상으로 설계 상세화. 필수로 다룰 것:
>    - 기간축(BS/IS/CF) 표로 의미를 확장했을 때 `preserve_col_positions=True`가
>      건드리는 다른 소비 로직(라벨 영역 판정 등) 회귀 여부(§1-4가 이미 지적).
>    - pre-2024(ACONTEXT 없는 필링) 포함 전체 연도 영향 범위 — R31급(775개사·
>      82,402행) 재적재 리스크를 실측으로 먼저 가늠(표본 재추출 diff부터).
>    - §1-5 옵션 B로 이미 고친 tax_expense 오버레이와의 상호작용(중복 수정
>      방지 — 옵션 A가 근본원인을 고치면 오버레이가 이제 항상 no-op이어야
>      정상, 이걸 회귀테스트로 고정).
>    - `docs/runbook_new_parser_pipeline_integration.md` 체크리스트(배선 2곳+
>      소급 백필+검증) 그대로 적용.
> 2. **버그② — §2-3의 "Phase 0.5"부터**(미착수, 조사조차 안 끝남).
>    `_derive_net_income_from_ebt`/`_resolve_ni_attribution`(둘 다
>    `fin2/layer3/combine.py`, 8월 중 이미 여러 번 수정한 함수들) 두 곳에 디버그
>    프린트를 심어 01497869 2025Q1을 재현해야 한다.
>    `scripts/phase0_probe_combine_2026-08-23.py`를 참고/재사용 — 이 스크립트가
>    왜 std_v3 실값과 다른 결과를 냈는지부터 먼저 확인(진짜 build 경로 재현).

## 0. 배경

같은 세션에서 fy≥2024 46건 회귀의 D 카테고리(9건: tax_expense 5·01201970 스케일불일치
2·01497869 계속/중단영업 3항구조 2)를 원문대조로 재조사한 결과 **이전 가설이 둘 다
틀렸고, 서로 다른 두 개의 확정 버그**로 밝혀졌다(①컬럼오선택, ②NI라벨중복). tax_expense
클러스터는 fy≥2024 라이브 `face_audit` fail_a 89건 중 15건 표본 원문대조 **15/15(100%)
동일 패턴**으로 규모까지 확인됐다. 이 문서는 두 버그의 수정을 설계한다.

## 1. 버그 ① — 당기 3개월(Q) 미공시 시 전기 3개월(PFY) 컬럼을 잘못 채택

### 1-1. 확정된 메커니즘 (★Phase 0 — 실제 코드 실행으로 재현 완료, 2026-08-23)

`scripts/phase0_probe_col_misselect_ni_dup_2026-08-23.py`로
`fin2/extract/report_lines.py::extract_report_lines()`를 00104573 원문 파일에
직접 호출 + `_emit_section_lines()`에 임시 프린트를 심어 실행 중 값을 확인했다
(프린트는 확인 후 되돌림, 커밋 없음).

**실제 코드위치(정정 — 최초 설계 초안은 `fin2/extract/text.py`로 잘못 짚었었다)**:
production report_lines은 `fin2/extract/report_lines.py::_emit_section_lines()`
(L407-527)가 만든다. 이 함수는 `fin2/extract/text.py::_interim_cumulative_cols()`
를 **그대로 import**해 헤더 텍스트의 "누적" 토큰 위치로
`cum_map={header_position: period_offset}`(예 `{1:0, 3:1}`)를 만들고, 컬럼
소비는 **`_emit_section_lines()` 자신의 L498-503**에서
`row.amounts[pos]`로 인덱싱한다(`fin2/extract/text.py::_emit_section`은 별도
fact_v2/Track B 경로용 병렬 구현이라 이 버그의 production 경로가 아니다 —
docstring L420-421에 "text.py `_emit_section`과 동일 로직... 재사용"이라고
명시돼 있어 헷갈리기 쉽다).

실측 재현(00104573, `20251113000801.xml`, "법인세비용(수익)" 행):
```
row.amounts = [-2310052284, -138250046, -586814200, None]   # 실제 파싱된 배열
cum_map     = {1: 0, 3: 1}                                    # 헤더에서 만든 매핑
```
원문 4개 XBRL 셀은 [당기3개월(disclosure 없음, 빈 셀), 당기누적=-2,310,052,284,
전기3개월=-138,250,046, 전기누적=-586,814,200] 순서다. **당기3개월의 빈 셀이
`row.amounts`에서 placeholder 없이 드롭**되어 배열이 왼쪽으로 한 칸씩 밀렸다
— `row.amounts[0]`엔 실제로는 물리적 2번째 셀(당기누적)이, `row.amounts[1]`엔
물리적 3번째 셀(전기3개월)이 들어간 것. `cum_map={1:0}`이 이 밀린 배열의
`[1]`(=전기3개월값)을 "당기"(`off=0`)로 잘못 방출 — **이게 db_won=-138,250,046
의 정체**. `row.amounts[3]`은 `None`이라 필터링돼 전기누적 값은 조용히 소실.

**한 칸 밀림의 실제 발생 지점(추가 확인)**: `parser/xml/table_extractor.py
::extract_rows()`의 `preserve_col_positions` 파라미터 docstring(L224-225)이
정확히 이 동작을 설명한다 — "True면 앞쪽 빈 셀을 당기지 않고 열 위치를 그대로
보존한다... 기본 False = 기존 동작 보존". 즉 **기본값(False)에서는 앞쪽 빈
금액셀이 당겨진다(압축된다)** — 이게 바로 이 밀림의 근원. 이 파라미터는 지금
"열이 기간이 아니라 축(자본구성요소 등)인 행렬 표 전용"으로만 쓰이고 있고,
`_emit_section_lines()`의 `extract_rows()` 호출(L475)은 `preserve_col_positions`
를 넘기지 않아(기본 False) 기간축 IS/CF 표에서도 이 압축이 그대로 걸린다.

같은 표의 EBT 행("법인세비용차감전순이익(손실)")은 4열 전부 disclosure가 있어
`row.amounts=[137350095, 24412859, -168930592, -313358576]`로 밀림 없이 정상—
**행 단위 결함**임을 실행으로 재확인(표 전체가 밀리는 게 아니라, 앞쪽 셀이 빈
행만 밀림).

`01201970`(셀레스트라, 2026H1)도 같은 정적 대조(원문 grep, Phase 0 이전)로
revenue/cogs/gross_profit/controlling_ni 4개 필드 전부 같은 패턴 확인됨 — 아직
`extract_rows()`/`_emit_section_lines()` 실행 재현은 안 했지만(00104573으로
메커니즘 자체는 충분히 확정), 필요하면 같은 스크립트로 쉽게 재현 가능.

### 1-2. 규모 재검증 (같은 세션)

fy≥2024 tax_expense 단일필드 fail_a 89건(라이브 `face_audit`, 대부분 2025 Q3) 중
15건 균등샘플을 스크립트(`scripts/verify_tax_expense_cluster_2026-08-23.py`,
값을 콤마포맷 문자열로 원문에서 grep 후 ACONTEXT의 rel/accum 태그로 분류)로
검증 — **15/15(100%)** 동일 패턴 확정(report_won=0인 4건은 스크립트 로직상
자동판정 불가했으나 2건 수동 원문대조로도 동일 패턴 재확인). 즉 **tax_expense
클러스터는 "패턴 불명확"(`docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md`
§3)이 아니라 사실상 단일 근본원인**이다.

### 1-3. 이미 알려진 인접 사례·자매결함

- `docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md`(00874803, 2025Q3
  tax_expense, "당기 대신 전기 비교컬럼 채택")가 **바로 이 버그의 앞선 목격
  사례**였다 — 당시 "T22와 무관한 별개 트랙"으로 범위 밖 처리되고 재론 지점만
  남겨졌다(`fin2/layer3/combine.py`의 ACONTEXT 선택 로직부터 — 단, Phase 0으로
  진짜 위치가 `combine.py`도 `text.py`도 아니라 **`report_lines.py`
  ::_emit_section_lines()`+`parser/xml/table_extractor.py::extract_rows()`**
  임이 확정됐다, 위 1-1 참고).
- `docs/PARSING_RULES.md` 부록A **T22**(순수 하이픈 음수 `-N` 미인식)는 **동일한
  `cum_map`/`row.amounts` 밀림 메커니즘의 다른 트리거**였다 — T22는 "값이
  있지만 `_NUMBER_PATTERN` 게이트가 숫자로 인식 못 해 드롭"이 트리거였고,
  **R31로 이미 수정 완료**(2026-08-17, `_NUMBER_PATTERN`에 하이픈 대안 추가).
  이번 버그는 트리거가 다르다 — **"disclosure 자체가 없어 셀이 진짜로 빈
  것"**(파싱 실패가 아니라 원문 자체가 공란)이라 R31의 수정 범위 밖이고, 별도
  트리거로 남아 있었다. T22 부록A가 이미 지목했던 "report_lines.py:472
  n_cols/cum_map 신규 발견·미착수"(2026-08-17 메모)가 바로 이 자리다 —
  이번 Phase 0으로 그 미착수 항목의 정확한 재현조건까지 규명된 셈이다.

### 1-4. 수정 옵션 비교

**옵션 A — `extract_rows()`/`_emit_section_lines()` 파서 근본수정**: 기간축
(BS/IS/CF) 표에서도 앞쪽 빈 금액셀을 압축하지 말고 `preserve_col_positions=True`
와 동등하게 **None placeholder로 보존**(또는 그 파라미터를 이 호출에 직접
전달). 근본적이고 파일 하나(`table_extractor.py`)만 건드리면 될 수 있어 보이나:
- `preserve_col_positions=True`는 지금 "열=축(자본구성요소 등)" 표 전용으로
  검증돼 있다 — 기간축 표로 의미를 확장하면 그 표들의 다른 소비 로직(라벨
  영역 판정 등)에 회귀가 없는지 별도 검증 필요.
- pre-2024(ACONTEXT 없는 필링)에도 영향 범위가 걸쳐 있어(이 파서는 모든 연도
  공용) 회귀 위험이 R31급으로 클 수 있음(R31은 pre-2010 775개사·82,402행
  재적재가 필요했음).

**옵션 B — R18(dividends_paid XBRL 인라인 오버레이) 패턴 재사용**: 2024+ 필링은
동일 원문에 `TE[@ACODE][@ACONTEXT]`로 이미 올바른 Track A 사실(`fin2/extract/
xbrl.py`+`acontext.py`, 구조파싱 정확성 직접 확인함)이 존재한다.
`fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_dividends_paid_sign()`
와 완전히 같은 방식으로 — **narrow keyword 후보 필터 + `read_report_face_xbrl()`
canonical 사실 + "후보 1개·사실 1개·크기 1% 이내 일치할 때만 override"** —
`is.tax_expense`용 오버레이 함수를 추가한다.

**권고: 옵션 B를 우선 채택**. 근거:
1. 이미 검증된 안전한 설계 원칙(R0 계층2 canonical-mapping-free 유지, 블랭킷
   수정 금지)을 그대로 재사용 — 새 리스크 표면이 작다.
2. 버그 발생 필링이 **전부 2024+**(ACODE/ACONTEXT 보유율 0.0%→31.7%→98.3%+,
   R18 문서 §5 실측)라 옵션 B의 커버리지가 이 클러스터 거의 전체와 일치한다.
3. 옵션 A(파서 근본수정)는 pre-2024까지 건드릴 잠재 범위가 있어 이번 스코프를
   벗어난다 — 별도 세션 과제로 분리 권고(아래 §4 범위 밖).

단, **R18 자신의 교훈**(설계 예상 92%였는데 실제 적용률은 fail_a 36건 중 6건뿐 —
후보가 2개 이상이면 모호 처리로 스킵)을 그대로 적용해, 이번에도 **구현 후 실측
적용률을 반드시 별도 보고**한다(낙관치를 그대로 믿지 않음).

### 1-5. 구현 스케치 (Phase 1 — 바로 착수 가능)

- `fin2/extract/report_lines_inline_xbrl_overlay.py`에
  `overlay_tax_expense_value()` 신설 (기존 `overlay_dividends_paid_sign()`와
  병렬 구조):
  - `_TARGET_CANONICAL = "is.tax_expense"`, `statement == "IS"`
  - 후보 키워드: `"법인세비용"`(교집합 아님, 단일 키워드 — dividends_paid의
    "배당"+"지급" 이중키워드와 다름, `is.tax_expense` alias 실측 후 확정)
  - `(basis, is_cumulative)` 키에서 텍스트후보 1개·XBRL사실 1개·크기 1% 이내
    일치할 때만 override(R18과 동일 원칙, §1-4 블랭킷 금지)
  - `_MIN_FISCAL_YEAR = 2024` 그대로 재사용(같은 커버리지 절벽)
- `extract_report_lines()`의 `overlay_dividends_paid_sign()` 호출부(L1156)
  바로 다음 줄에 `overlay_tax_expense_value()` 호출 추가.
- **다른 필드로 확장할지 여부(revenue/cogs/gross_profit/controlling_ni)는
  Phase 1 실측 후 별도 판단** — 01201970 사례가 있지만 발생빈도가 tax_expense
  보다 훨씬 낮을 것으로 예상(당기 3개월 disclosure 생략이 세금비용만큼 흔하지
  않음). Phase 1에서 tax_expense만 먼저 넣고 실측 규모를 본 뒤 §1-4 원칙
  그대로 `is.revenue`/`is.cogs`/`is.gross_profit`/`is.controlling_ni`로 확장
  여부를 사용자와 재상의(범위 확장은 이 설계의 승인 범위 밖 — 별도 승인 필요).

### 1-6. 검증 계획

1. ~~Phase 0(구현 전 필수 게이트)~~ — **완료**(위 1-1). 00104573 실행 재현
   확인. 01201970도 필요시 같은 스크립트로 재현(현재는 정적 원문대조만).
2. 단위 테스트(R18 관례대로 `fin2/tests/test_report_lines_inline_xbrl_overlay.py`
   에 추가) — 00104573 실측 재현 케이스 포함.
3. fy≥2024 tax_expense fail_a 89건 전수(또는 최소 R18급 무작위 표본) 재실행 —
   적용 건수·전부 report_won 일치(오탐 0)·미적용 건은 근거 있는 스킵인지 확인.
4. pytest 전체(`fin2/tests fin2 tests/` 스코프, [[feedback-workflow]] 준수) 통과.
5. 소급 백필 — `load_report_lines.py`류 재실행 범위는 "fy≥2024 전체"(오버레이가
   no-op 아닌 필링 전부). 정확한 rcept 목록은 Phase 1 구현 시 재산정.

### 1-7. ★Phase 1 구현 중 발견한 설계 결함 2건 + 실측 결과 (2026-08-23)

§1-5대로 그대로 구현하기 전에 00104573 실제 값으로 재검증하다가, **이 설계
문서(§1-4/§1-5)가 §1-1에서 실행으로 확인한 사실과 스스로 모순되는 두 대목을
포함하고 있음을 발견**했다 — 둘 다 코드를 쓰기 전에 실행/원문 대조로 확정하고
그 자리에서 수정 반영했다(R9 원칙, 지레짐작 금지):

1. **"크기 1% 이내 일치할 때만 override" 게이트는 이 버그에 적용하면 안 된다.**
   §1-4/§1-5는 R18(`overlay_dividends_paid_sign`)의 문구를 그대로 재사용했지만,
   R18은 **부호만** 틀린 버그(크기는 이미 일치)라 크기일치 게이트가 "다른
   사실과의 우연매칭 방지"로 타당했다. 이 버그는 반대로 **값 자체가 크게
   틀리는 게 버그의 증상**이다 — 00104573 실측: 텍스트값 -138,250,046 vs 올바른
   XBRL 사실 -2,310,052,284, 비율 5.99%(1% 게이트 통과 불가능). 그대로
   구현했다면 오버레이가 **단 한 건도 발동하지 않았을 것**이다. → 크기게이트를
   제거하고 "(basis, is_cumulative) 키에서 텍스트후보 1개·XBRL사실 1개"
   유일성만으로 override하도록 수정(이미 있는 "값이 같으면 no-op" 체크가
   자연스럽게 안전판 역할).
2. **후보 키워드 "법인세비용" 단일 문자열은 EBT 행과 충돌한다.** 같은
   00104573 문서의 "법인세비용차감전순이익(손실)"(세전이익, EBT) 라벨이
   "법인세비용"을 부분문자열로 포함한다 — 실행 재현으로 직접 확인. 이건
   **신규 함정이 아니라 기존에 이미 알려진 함정의 재발**이다:
   `parser/common/account_mapper.py`의 EBT 가드
   (`fin2/tests/test_account_mapper_ebt.py` docstring, Gate B fail_b 2026-06-18)가
   바로 이 부분문자열 충돌 때문에 111개사·2,665셀이 세전이익을 법인세비용으로
   오채택했던 걸 고친 이력이 있다. → 같은 가드("차감전" 포함 라벨은 후보에서
   제외)를 오버레이 후보 필터에도 추가.

두 수정 다 코드에 반영(`fin2/extract/report_lines_inline_xbrl_overlay.py`
`overlay_tax_expense_value()`)하고 단위테스트로 회귀 고정
(`fin2/tests/test_report_lines_inline_xbrl_overlay.py` §3, EBT행 배제 케이스
포함).

**실측 적용률(§1-6 항목 3, `scripts/verify_tax_expense_overlay_applied_
2026-08-23.py`)** — fy≥2024 tax_expense fail_a 89건(§1-2 표본검증에 쓴 TSV)
전수를 실제 프로덕션 `extract_report_lines()`(오버레이 배선 포함)로 재실행:

| 결과 | 건수 |
|---|---|
| applied_match(오버레이 적용 + report_won과 정확 일치) | 85 (95.5%) |
| applied_mismatch(오버레이는 됐는데 report_won과 불일치) | **0** |
| not_applied(오버레이 미발동) | 4 |

**오탐 0건** — R18의 "낙관치를 믿지 말고 실측 보고" 교훈(§1-4)대로면 이번엔
설계 낙관치(89건 거의 전부)에 상당히 가까운 결과다. 미적용 4건
(00144720/01075126×2/01110678, 전부 fy2025 Q3)을 원문 대조한 결과 **이 버그와
다른 증상**임을 확인했다 — 컬럼오선택이 아니라 **"법인세비용" 행 자체가
텍스트추출에서 통째로 안 만들어짐**(같은 문서에 EBT 행만 있고 tax_expense
행이 없음, XBRL 사실은 존재). 오버레이는 "이미 있는(틀린) 후보 행의 값을
XBRL로 교정"하는 설계(§5 블랭킷 금지 원칙)라 후보 행 자체가 없으면 의도대로
손대지 않는다 — **행을 새로 만드는(row synthesis) 건 이 설계의 스코프
밖**이다. 별도 원인(다른 트리거로 report_lines가 그 행 자체를 못 만드는 것)
이라 이 문서 범위 밖으로 남긴다(§4에 추가).

pytest 전체(`fin2/tests tests/`): 603 passed, 1 failed —
`test_biz_section.py::test_lxintl_facility_table_dropped`. `git stash`로 이번
변경 없이 재실행해 **base 브랜치에서도 동일하게 실패함을 확인**(무관한 기존
결함, 이번 변경이 만든 회귀 아님).

### 1-8. ★Gate B 전수 재감사(2026-08-24) — tax_expense 검증 완료 + 신규 발견(controlling_ni도 동일 메커니즘)

[[gateb-full-reaudit-is-required-to-close]] 원칙에 따라 표본이 아니라 전수로
검증했다. 사용자가 `bash scripts/run_gateb_audit_parallel.sh`를 직접 실행
(2026-08-23 22:35 ~ 2026-08-24 00:09, 약 1시간 33분, 5-shard, 2,543개사·
303,867행 전부 갱신 확인). 재감사 직전 스냅샷 `face_audit_snap_20260823`
(백필 전 상태, 303,865행) 대비 비교(`scripts/verify_gateb_reaudit_transition_
2026-08-24.py`, 전수 key 대조, 누락 0건).

**tax_expense 결과** — before(gate_status=fail_a + fail_fields에 tax_expense) 91건:
→ pass 69 / → pending 16 / → 여전히 fail_a 6건. §1-7의 89건 실측(85/89)과
일치(91건 중 4건은 §1-7 이후 추가된 케이스 — 00536888은 fy2023로 애초
스코프 밖, 01032486은 fy2026H1 신규 필링). 여전히 fail_a인 6건 중 4건
(00144720×2·01075126·01110678)은 §1-7이 이미 식별한 "행 자체가 텍스트추출
누락" 별개증상. **오탐 0.**

**전체 회귀(pass/fail_b → fail_a, 차단등급) 점검** — 전수 303,865건 중 **단
1건**: `00172291`(더존비즈온) 2025 H1 연결 `controlling_ni`
(db_won=11,111,394,247 vs report_won=29,698,844,769). 그 외 대량 전이
(`pass→fail_b` 129건, `pass→pending` 2,958건)는 각각 **100%/99.7%가 fy<2024**로
이번 fy≥2024 백필과 무관 확인(face_audit 리더 쪽 기존 변동성, 범위 밖).

**00172291 원인규명(실행 재현 완료)** — 처음엔 "오늘 13:17 백필이 2c56834
(15:28 커밋, NI귀속 구조복구)보다 먼저 돌아 stale 코드로 빌드된 것"이라는
가설을 세웠으나, **현재(post-2c56834) 코드로 `build_std_v3.py --corp 00172291`
단독 재빌드해도 값이 동일 재현**돼 그 가설은 기각. 원문(`20250814003371.xml`)
직접 grep + `extract_report_lines()`에 디버그 프린트(확인 후 원복, 커밋 없음)로
재현한 결과 — **버그①(§1-1)과 완전히 동일한 메커니즘**임을 확인:

```
"반기순이익의 귀속 > 지배기업의 소유주지분" 행(원문 4물리열):
  [당기3개월(ACONTEXT 없음, 빈 셀), 당기누적=29,698,844,769,
   전기3개월=11,111,394,247, 전기누적=27,018,212,143]
row.amounts = [29698844769, 11111394247, 27018212143, None]   # 빈 선두열 드롭 → 좌측 압축
cum_map     = {1: 0, 3: 1}
→ amounts[1](=전기3개월값 11,111,394,247)를 "당기"(off=0)로 잘못 방출
```
같은 표의 "총포괄손익의 귀속 > 지배기업의 소유주지분" 행은 4열 전부
disclosure가 있어(`amounts=[16662099147, 29645492777, 11081632735,
27026902031]`, cum_map 그대로 적용) 정상 — §1-1의 "행 단위 결함, 표
전체가 밀리는 게 아님" 관찰과 정확히 일치한다.

**결론**: 버그①은 tax_expense 전용이 아니라 **"당기 3개월 disclosure 누락
시 컬럼오선택"이라는 계정 무관(account-agnostic) 파서 결함**이며, 이번에
`is.controlling_ni`("...귀속" 섹션의 attribution 행)에서도 실측 재현됐다.
00172291은 §1-7 이전에는 알려지지 않은 신규 사례이자, [[fy2024-46-regression-
a-b-fixed-2026-08-23]]가 정리한 27+9=36건 목록에도 없는 **독립적인 열 번째
유형** — combine.py 로직 문제가 아니라 Layer 2(report_lines.py) 문제이므로
그 문서의 수정 범위와도 무관.

**§4 갱신 필요**: "revenue/cogs/gross_profit/controlling_ni로의 오버레이
확장은 Phase 1 실측 후 별도 승인" 조항이 이제 실측 근거를 확보했다 —
`is.controlling_ni`(및 유사 구조의 net_income 귀속 계열 전반)로 §1-5
옵션 B를 확장할지, 이번 기회에 §1-4 옵션 A(파서 근본수정)로 전환할지는
**사용자 결정 대기**(다음 세션 우선순위 1).

스크립트: `scripts/verify_gateb_reaudit_transition_2026-08-24.py`(before/after
전수 비교), `scripts/probe_combine_00172291_2026-08-24.py`(combine.py 후보풀
확인 — stale코드 가설 기각용, 최종 원인은 이 Layer 3 확인이 아니라 위
Layer 2 디버그 프린트 재현으로 확정됐음에 주의).

## 2. 버그 ② — 01497869: net_income에 controlling_ni(귀속)값이 오채택

### 2-1. 확정된 증상

01497869(티와이홀딩스) 2025 Q1·H1 두 기간 모두 db_won(net_income)이 원문의
`ifrs-full_ProfitLoss`(총계, 지배+비지배 합산 — 진짜 net_income)이 아니라
`ifrs-full_ProfitLossAttributableToOwnersOfParent`
/`ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent`(지배기업
소유주지분 **귀속**분 — controlling_ni 개념)과 정확히 일치했다.

### 2-2. ★Phase 0 완료분 — Layer 2(report_lines)는 무죄 확정, Layer 3(combine.py)로 좁혀짐

`scripts/phase0_probe_col_misselect_ni_dup_2026-08-23.py`로 01497869 2025Q1
(`20250515002319.xml`)을 `extract_report_lines()`에 직접 통과시켜 확인
(실행 결과, col_index=0만):

```
label='계속영업손실' depth=0 section_path=None                                      value_won=-11688071738   # ← 진짜 net_income, report_won과 일치
label='계속영업손실' depth=2 section_path='분기연결순손실의 귀속>지배기업 소유주지분'   value_won=-10889454116   # ← std_v3에 저장된 (틀린) 값
label='계속영업손실' depth=2 section_path='분기연결순손실의 귀속>비지배지분'           value_won=-798617622
```

**Layer 2는 3개 행 전부 depth/section_path로 명확히 구분해 정상 보존한다** —
어제 메모의 "text.py 귀속가드 갭" 가설(§2-2 최초 초안)은 **기각**. 총계(depth=0)
가 이미 정확한 값(-11,688,071,738)으로 존재하므로, 문제는 반드시 **Layer 3
(`fin2/layer3/combine.py`)의 후보 선택/충돌해소 단계**에 있다.

### 2-3. ★Phase 0.5 (다음 세션 첫 단계) — 최초 가설도 기각됨, 추가 추적 필요

`scripts/phase0_probe_combine_2026-08-23.py`로 `fin2/layer3/combine.py
::combine_full()`/`_map_rows()`를 01497869 2025Q1 consolidated에 직접
호출해봤다. 결과가 예상과 달랐다:

- `_map_rows()` 직후의 `is.net_income` 후보 풀이 **완전히 비어 있었다**
  (depth=0/depth=2 두 후보가 충돌하는 게 아니라, **`is.net_income`에 매핑된
  원시 후보 자체가 0개**). `is.controlling_ni`는 `value_won=None`인 구조적
  (`stage='structural'`) 후보 1개만 있었다(section_path는 잡히는데 값이 안
  채워진 상태).
- `combine_full()`의 최종 `col.get("is.net_income")`/`col.get("is.controlling_ni")`
  도 둘 다 `None`이었다 — 그런데 std_v3엔 이 corp/기간에 실제 값이 저장돼
  있다(db_won=-10,889,454,116). 즉 **이 임시 스크립트의 단독 호출이 실제
  파이프라인(std_v3를 만든 호출)과 뭔가 다르다** — `build_merged_lines()`의
  필링 선택(rcept 선택)이 다르거나, 실제 std_v3는 `combine_full()`을 더
  높은 레벨(전체 build 루틴)에서 다른 인자로 호출하고 있을 가능성이 높다.

**최초 가설("계속영업손실" 3행이 라벨 텍스트만으로 is.net_income에 동시매핑돼
depth-tie-break가 실패)도 이 실행으로 배제됐다** — 애초에 net_income 후보가
없었으므로 "여러 후보 중 잘못된 걸 고른다"는 그림 자체가 틀렸다. 유력한 다음
가설은 `_derive_net_income_from_ebt()`/`_resolve_ni_attribution()`
(`fin2/layer3/combine.py:1806/1862`, **이번 주 이미 여러 번 수정한 바로 그
함수들** — [[fy2024-46-regression-a-b-fixed-2026-08-23]] "A" 참고)이 EBT−세금
앵커로 net_income을 "유도"하는 경로이고, 그 유도 과정에서 controlling_ni
값을 잘못 채택하고 있을 가능성 — 단 **이것도 아직 실행으로 확인 안 됨**,
순수 추정이다.

**다음 세션 Phase 0.5(구현 착수 전 필수)**:
1. `scripts/phase0_probe_combine_2026-08-23.py`가 왜 std_v3 실제값과 다른
   결과를 냈는지부터 확인 — std_v3를 실제로 채운 호출부(`fin2/layer3/build.py`
   류, `run.py standardize2`/`fin2-all` 경로)를 찾아 **그 경로 그대로**
   01497869 2025Q1을 재현.
2. 재현되면 `_derive_net_income_from_ebt`/`_resolve_ni_attribution`에 디버그
   프린트를 심어 EBT/세금 후보와 net_income anchor 후보들, controlling_ni
   채택 경로를 직접 관찰.
3. 그 결과로 §2-2를 대체하고 실제 수정 위치·방식을 이 문서에 추가한 뒤
   구현 착수.

### 2-4. 검증 계획

Phase 0.5 결론 이후 구체화. 최소 조건: 01497869 2025 Q1·H1 두 건 모두
report_won과 db_won 일치 확인 + 이번 주 이미 고친 A 계열 7건
([[fy2024-46-regression-a-b-fixed-2026-08-23]]) 회귀 없음(재실행 diff) +
pytest 전체 통과.

## 3. 파이프라인 편입 체크리스트 (`docs/runbook_new_parser_pipeline_integration.md` 준수)

두 버그 다 **기존 로직의 수정**(신규 로더 아님)이지만 report_lines/std_v3 출력값이
바뀌므로 3층 전부 필요:

- [x] **① 배선** — `overlay_tax_expense_value()`(버그①)를 `overlay_dividends_paid_sign()`과
      같은 호출부(`extract_report_lines()` L1156 다음 줄)에 추가 완료. **확인 결과**:
      `scripts/collect_new.py`의 두 call site(`_sync_layer2_lines` — 메인 ④-3 +
      `--standardize-only` 재개)는 둘 다 `collector/note_lines_sync.py::
      sync_layer2_lines()`를 거쳐 `extract_report_lines()`를 직접 호출하므로
      **추가 배선 없이 자동으로 같이 탄다**(R18 때와 동일 구조 — grep으로 실제
      확인, 지레짐작 아님). `scripts/load_report_lines.py`(벌크 백필용)도 동일하게
      `extract_report_lines()`를 직접 호출해 같이 탄다.
- [x] **② 소급 백필** — 완료(2026-08-23, 사용자가 직접 실행). `scripts/
      load_report_lines.py --fy-min 2024 --recheck`(4.82h, done 27,026/skip 29/
      error 0, report_lines 9,727,495행) → `scripts/build_std_v3.py --all
      --year-min 2024 --shard {0..3}/4`(4-way 병렬, 총 137초, 2,543개사·
      49,418행, error 0). 00104573 2025Q3 std_v3 실값 직접 조회로 검증 —
      `tax_expense=-2,310,052,284`(연결·별도 둘 다) 정확히 교정 확인.
- [x] **③ 검증** — §1-6/§1-7: 단위테스트 7건 신설 통과, fy≥2024 tax_expense
      fail_a 89건 전수 재실행(85 적용·오탐0·4 별개증상), pytest 전체 603 passed(무관
      기존실패 1건 확인), 백필 후 00104573 실 DB 값 검증. **Gate B 전수 재감사
      완료**(§1-8, 2026-08-24) — tax_expense 91건 fail_a 전수 중 85건 해소(오탐0),
      전체 회귀(pass/fail_b→fail_a) 1건(00172291)은 **버그①의 다른 계정 인스턴스**로
      확정(별도 신규 버그 아님) — tax_expense용 §1-5 코드 수정 자체의 회귀는 0건.
      **tax_expense 스코프는 완결.** controlling_ni 확장 여부는 §1-8/§4 참고, 별도
      사용자 결정 대기.

## 4. 범위 밖 (명시)

- **옵션 A(`table_extractor.py::extract_rows()` 파서 근본수정)** — 이번 스코프
  아님. pre-2024까지 영향 범위가 걸쳐 있어 리스크가 크다. 재론 시
  `parser/xml/table_extractor.py::extract_rows()`(L194-, `preserve_col_positions`
  파라미터)와 `fin2/extract/report_lines.py::_emit_section_lines()`(L407-527)
  두 곳을 함께 검토.
- **revenue/cogs/gross_profit/controlling_ni로의 오버레이 확장** — Phase 1
  (tax_expense) 실측 후 별도 승인.
- **01497869 §2의 실제 코드수정** — Phase 0.5(추가 코드 추적) 결과 없이는
  착수하지 않는다.
- fy≥2024 tax_expense fail_a 89건 중 미샘플 74건의 개별 확인 — 15/15 표본으로
  충분한 확신을 얻었다고 판단했으나, 옵션 B 구현 후 전수(또는 대규모 표본) 재실행
  결과가 최종 검증. **완료(§1-7)** — 89건 전수 재실행, 85/89 적용·오탐 0.
- **미적용 4건(00144720/01075126×2/01110678)의 "법인세비용 행 자체가
  텍스트추출에서 누락"** — §1-7에서 발견한 별개 증상(컬럼오선택이 아니라 행
  자체 미생성). 이 오버레이의 스코프(기존 후보 행의 값 교정)를 벗어나므로
  원인추적·수정은 별도 세션 과제로 분리.

## 5. 참고

- `docs/PARSING_RULES.md` R18(패턴 원본), 부록A T22/R31(같은 하류 메커니즘의
  다른 트리거, 이미 고쳐진 자매결함), R24/R25(_ni_attribution_structural_candidates
  계열).
- 메모리: [[fy2024-46-regression-a-b-fixed-2026-08-23]],
  [[d-category-tax-expense-01201970-01497869-rootcause-2026-08-23]],
  [[feedback-verify-against-source]], [[feedback-plan-then-wait]],
  [[parser-pipeline-integration-runbook]].
- 스크립트: `scripts/verify_tax_expense_cluster_2026-08-23.py`(15건 표본검증),
  `scripts/phase0_probe_col_misselect_ni_dup_2026-08-23.py`(버그①/② Layer 2
  실행 재현), `scripts/phase0_probe_combine_2026-08-23.py`(버그② Layer 3
  탐침 — std_v3 실값과 안 맞아 다음 세션에서 먼저 원인규명 필요, 위 §2-3).
