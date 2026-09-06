# 설계: 원문 자기모순 필링의 수동 단위 교정(unit override) 메커니즘

- 상태: **설계안 — 구현 대기 (사용자 승인 필요)**
- 관련: `docs/PARSING_RULES.md`, 메모리 `v2-drop-remaining-backlog-2026-09-03.md` §2 (가+라) 그룹
- 대상 문제: `statement_magnitude_impossible` 잔존건 중 "표 자신이 인쇄한 단위 라벨이
  실제 숫자 자릿수와 안 맞는" 케이스(예: "(단위:백만원)"이라 써놓고 실제 값은 원 단위).
  파서는 원문 선언을 정확히 그대로 따랐을 뿐이라 **코드 버그가 아니라 원문 필링 자체의
  표기 오류** — 지금까지 9건+신규 2개사가 이 그룹으로 확인됨(00138516/00138701×2/
  00143226/00204226/00378363/00400121/00487546/00198697/00260958).

## 문제

지금까지 이런 케이스는 두 가지 선택지만 있었음: ①`data_quality>=3`으로 격리해 값을
숨기거나, ②아예 손 안 댐(현재 상태 — 잘못된 값이 그대로 노출 중인 41건 중 다수).
사용자 요청: 원문을 직접 확인해 올바른 단위를 판정한 뒤, **그 판정을 DB에 반영해서
정확한 값이 적재**되도록 하고, 수동 교정이 적용된 셀임을 **별도로 표시**하자.

## 설계

### 1. 적용 레이어: `combine.py` (report_lines는 불변 유지)

`report_lines`는 "원문 그대로 추출"이 원칙(계층2 불변 원칙, CLAUDE.md 아키텍처 규칙과
일치)이므로 여기는 손대지 않는다. 대신 이미 R16/R20/R21/R72 같은 curated override들이
사는 층인 `fin2/layer3/combine.py`(report_lines → std_financials_v3 집계 단계)에서
교정한다 — 후보 값을 `_resolve()`에 넘기기 전에 curated 배수로 재계산.

### 2. 신규 모듈: `fin2/layer3/unit_overrides.py`

기존 curated override들(코드에 박힌 dict/frozenset + 근거 주석, git으로 이력 추적)과
같은 패턴. 예:

```python
# 키: (corp_code, fiscal_year, fiscal_period, statement_type, concept)
# 값: 교정된 배수 지수(10^n) — declared adecimal을 무시하고 이 값으로 강제.
# 각 항목은 원문 대조 근거(rcept_no, 확인한 사람/일자, 무엇을 봤는지)를 주석으로 남긴다.
UNIT_OVERRIDES: dict[tuple[str, int, str, str, str], UnitOverride] = {
    ("00138516", 2006, "FY", "consolidated", "is.revenue"): UnitOverride(
        corrected_adecimal=0,
        note="표 선언 '(단위:백만원)'이나 인쇄값 2,146,172,472는 이미 원단위. "
             "원문대조: annual/2006/20070330000181.xml, 2026-09-06.",
    ),
    ...
}
```

concept 단위까지 키에 넣는 이유: 나이스디앤비 사례처럼 같은 필링 안에서도
revenue(하류버그)와 total_assets(원문모순)의 원인이 서로 다를 수 있어, statement 전체가
아니라 개념 단위로 좁게 교정해야 안전.

### 3. 시각적 추적: 신규 컬럼 `std_financials_v3.unit_overrides` (jsonb, nullable)

`conflicts`/`amended_cols`와 같은 자리에 나란히 신설. 실제로 교정이 적용된 셀만
기록:

```json
{"revenue": {"declared_adecimal": -6, "corrected_adecimal": 0,
             "note": "원문 자기모순, 수동 단위교정 적용(2026-09-06)"}}
```

- 이렇게 하면 "이 값은 수동 교정됨"을 나중에도 SQL로 바로 조회 가능하고,
  시각화 화면에 배지/각주로 노출할 수 있음(개발목표의 "원하는 모양으로 visualize"와
  부합).
- `data_quality` 컬럼(자동 항등식검증 점수)은 건드리지 않음 — 의미가 다른 컬럼이라
  재사용하면 나중에 헷갈림.

### 4. 반복 가능한 작업 절차 (다음에 새 사례가 나올 때마다)

1. `dq_assertions.py` 샘플 또는 전수스캔으로 후보 발견.
2. **SD카드 원문(`/Volumes/dart_data/raw_report`)을 사용자와 함께 대조** — 어느 쪽이
   맞는 배수인지 확정. (이 프로젝트의 기존 원칙 [[feedback-verify-against-source]]
   그대로.)
3. `unit_overrides.py`에 항목 추가(근거 주석 필수) + `docs/PARSING_RULES.md`에
   R-번호로 등재.
4. 회귀테스트 추가(해당 corp/fy/fp 스코프, 기존 `test_combine_curated_overrides.py`
   패턴 재사용).
5. 영향받는 corp만 스코프 좁혀 재빌드(`build_std_v3.py --corp <corp_code>`,
   report_lines는 안 건드리므로 재추출 불필요) + `calendarize_corp_v3` 동기화.
6. `dq_assertions.py` 전수 재검증(PK조인 전이표로 회귀 0건 확인, 총량비교 금지
   원칙 [[gateb-full-reaudit-is-required-to-close]] 축소판 — 이번엔 스코프가
   개별 corp라 전수 대신 해당 corp 전체 이력만 재조회).
7. 커밋(`Co-Authored-By` 포함).

새 케이스 추가가 "코드 1곳 수정 + 스코프 재빌드"로 끝나므로, 매번 새 파서를 만드는 게
아니라서 `runbook_new_parser_pipeline_integration.md`의 대상은 아님(참고로 언급만).

## 열린 결정 사항 (승인 필요)

1. **신규 컬럼 `unit_overrides` 신설 동의 여부** — 대안: `conflicts` 컬럼을
   재사용(비권장, 의미가 섞임) / 아예 표시 없이 값만 조용히 교정(비권장, 나중에
   "왜 이 값이 원문 선언과 다른가"를 추적 못 함).
2. **지금 파악된 9건+2건을 이번에 전부 원문 재대조해서 등록할지, 메커니즘만 먼저
   만들고 사례별로 다음 세션부터 하나씩 추가할지** — 후자를 권장(원문 대조는
   건마다 사용자 확인이 필요한 작업이라 한 세션에 몰아넣기보다 점진적으로).

## 구현 순서 (승인 후)

1. 마이그레이션: `std_financials_v3`에 `unit_overrides jsonb` 컬럼 추가.
2. `fin2/layer3/unit_overrides.py` 신설(빈 dict로 시작, 타입만 정의).
3. `combine.py`에 override 적용 지점 배선 + `build.py`에서 `row.unit_overrides` 채우기.
4. 회귀테스트(빈 override일 때 기존 동작 100% 불변 확인).
5. 첫 사례(사용자와 원문 대조 확정된 것부터, 예: 00138516) 등록 → 위 반복 절차 4~7 실행.
