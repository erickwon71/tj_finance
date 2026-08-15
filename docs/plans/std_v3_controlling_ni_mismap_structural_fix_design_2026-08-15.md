# 설계 — `controlling_ni` 그룹A 하위메커니즘①(mismap) 구조기반 후보보강 수정 (2026-08-15 작성)

> **이 문서는 설계뿐이다. 코드는 전혀 건드리지 않았다. 실행은 별도 승인 필요**
> (정책상 계획 문서 작성이 곧 실행 허가가 아님).
> 배경 전체 조사 내역 = 메모리 `gateb-controlling-ni-groupa-rootcause-2026-08-15`
> (사용자 세션 내 접근 가능, 원문대조 로그 포함). 읽기전용 검증 스크립트 3개를
> `scripts/`에 커밋 전 상태로 남겨둠(§6).

---

## 0. 요약

- **대상**: Gate B `controlling_ni` fail_a 86건 → 그룹A(78건) → 그중 하위메커니즘①
  "mismap"(정답 후보가 `report_lines`엔 존재하지만 AccountMapper가 엉뚱한 canonical로
  잘못 매핑) — **51건**(원래 CSV 재가공 1차 분류로는 53건 추정이었으나, 이번 설계용
  정밀 재분류에서 51건으로 소폭 조정됨, 판정 로직 차이 원인 미상·우선순위 아님).
- **근본원인**: `fin2/layer3/combine.py::_map_rows()`가 report_lines 라벨을
  AccountMapper로 canonical에 매핑할 때 **section_path(섹션 구조)를 전혀 안 씀** — 순수
  라벨 텍스트 매칭만 한다. 그 결과 "지배기업 소유주지분" 행이 `당기순이익의 귀속`(정답)
  섹션 라벨을 원문 자체가 재사용하거나(라벨이 그냥 '당기순이익'), fuzzy 매칭이 라벨의
  '지배'/'비지배' 방향을 헷갈려서, 정답 값이 `is.controlling_ni`가 아니라
  `is.net_income`/`is.noncontrolling_ni` 후보풀로 새버린다. 정작 `is.controlling_ni`
  풀엔 오답(총포괄손익 섹션 값) 단 1개만 남아 `_resolve()`가 그대로 자동확정 —
  5dbecac(2026-08-12)이 만든 항등식 안전망(`_resolve_ni_attribution`)은
  `conflicts`에 걸린 경우만 호출되므로, 후보가 1개뿐인 이 케이스들에선 **호출 자체가
  안 됨**(5dbecac이 고친 것과는 다른, 더 앞선 선행조건 실패).
- **제안 설계**: 새 선택 로직을 만들지 않는다. 대신 `_map_rows()`에 **구조기반 후보보강
  단계**를 추가해, `당기순이익...귀속` 계열 섹션에서 라벨과 무관하게 지배/비지배 두 행을
  구조적으로 식별하고, 그 값을 `is.controlling_ni`/`is.noncontrolling_ni` 후보풀에
  **추가로 끼워넣기만** 한다. 이후는 기존에 이미 검증된(5dbecac, 유닛테스트 12개)
  `_resolve()` → `_resolve_ni_attribution()` 파이프라인이 그대로 처리한다 — 새 오답을
  낼 수 있는 새 코드 경로를 만들지 않는다는 뜻.
- **측정된 커버리지**: mismap 51건 중 **32건(63%) 오탐 0건**으로 해결 확인(읽기전용
  프로브, `_match_ni_identity()` 실제 함수로 재현). 나머지 19건은 이번 설계의 섹션판정
  규칙이 못 잡는 다른 포맷(§4) — Phase 2, 이번 설계 범위 밖.
- **부수 효과(범위 밖이지만 측정됨)**: 같은 규칙이 하위메커니즘②(완전미매핑, 24건) 중
  11건, 하위메커니즘③(안전망자체오류, 3건) 중 1건도 같이 회복시킨다 — AccountMapper를
  아예 안 거치기 때문. 이번 승인 범위에는 안 넣지만 구현 시 자연히 같이 좋아짐.

---

## 1. 근본원인 상세

### 1-A. mismap 사례 두 갈래 (원문 XML 직접대조 확인, 4개사)

| 회사 | 정답이 새는 곳 | 원문 상 이유 |
|---|---|---|
| 삼성전자(00126380) | `is.net_income` | `당기순이익의 귀속` 섹션의 지배지분 행이 원문 라벨 자체를 상위 라벨('분기순이익')과 동일하게 재사용(들여쓰기로만 구분) — ACODE는 정확히 `ifrs-full_ProfitLossAttributableToOwnersOfParent` |
| KPX홀딩스(00587466) | `is.net_income` | fuzzy stage, 압축라벨('...의 귀속 - 지배기업의 소유주') |
| 동성케미컬(00679314) | `is.noncontrolling_ni` | 라벨에 '지배'가 있는데도([[key-bugs-fixed]] #8류) fuzzy가 비지배로 오매칭 |
| KG에코솔루션(00366137) | `is.net_income` | fuzzy stage, 라벨 '보통주반기순이익(손실)' |

### 1-B. 왜 5dbecac 안전망이 여기선 무력한가

`_resolve()`(`fin2/layer3/combine.py`)의 `is.controlling_ni`/`is.noncontrolling_ni`
전용 분기(5dbecac 신설, `_NI_ATTRIBUTION_CANON`):

```python
if c in _NI_ATTRIBUTION_CANON:
    vals = {r["value"] for r in rows}
    if len(vals) == 1:
        confirmed[c] = next(iter(vals))
    else:
        conflicts[c] = sorted(...)
    continue
```

mismap 케이스는 `is.controlling_ni`의 원시 후보(`rows`)가 **처음부터 1개뿐**이다(정답
후보가 애초에 이 리스트에 들어온 적이 없으므로). `len(vals) == 1` → 무조건
`confirmed`로 직행, `conflicts`엔 절대 안 들어간다. `_resolve_ni_attribution()`의
첫 줄은:

```python
if "is.controlling_ni" not in conflicts:
    return
```

— 그래서 호출되자마자 리턴한다. 5dbecac은 "후보가 여러 개인데 stage-rank가 잘못
고르는" 문제를 고쳤지, "정답 후보가 아예 안 들어오는" 이 문제는 애초에 다루지 않았다.

---

## 2. 제안 설계 — 구조기반 후보보강(structural candidate injection)

### 2-1. 핵심 아이디어

라벨 텍스트를 신뢰하지 않는다(라벨 재사용·fuzzy 오분류가 근본원인이므로). 대신
**섹션 구조**를 신뢰한다: 한국 IFRS 재무제표의 당기순이익 귀속 섹션은 실무상 거의
항상 정확히 2행(지배+ 비지배)이고, 그중 '비지배'가 라벨에 명확히 들어간 행은
헷갈릴 여지가 없다. 이 앵커를 이용해 **나머지 한 행은 라벨이 무엇이든 지배지분
행으로 구조적으로 확정**한다.

이 신호로 뽑은 후보를 `is.controlling_ni`(및 `is.noncontrolling_ni`)의 기존
account_mapper 기반 후보 리스트에 **추가**만 한다(대체·직접확정 아님). 그 다음은
손대지 않는다 — 이미 검증된 `_resolve()`/`_resolve_ni_attribution()`이 나머지를
처리한다.

### 2-2. 판정 규칙 (읽기전용 프로브로 측정, 오탐 0건)

`report_lines`에서 해당 필링의 IS statement, `col_index=0`, `header_hint IS NULL`
행들을 모아 `(table_seq, section_path)`로 그룹핑하되, 다음 조건을 만족하는
section_path만 후보 섹션으로 채택:

- `"귀속"` 포함 **AND** `"순이익"` 포함 **AND** `"포괄"` 미포함
  (예: `당기순이익의 귀속`/`분기순이익의 귀속`/`반기순이익의 귀속` — OK.
  `총포괄손익의 귀속`/`포괄손익의 귀속`은 "포괄" 때문에 자동 제외)

그 섹션의 멤버 행 중:
- 라벨에 `"비지배"`가 포함된 행이 **정확히 1개**
- 라벨에 `"비지배"`가 없는 행이 **정확히 1개**

이 두 조건이 모두 성립할 때만 발동. 그 외 모양(행이 0/1개뿐, 비지배 행이 2개
이상, 섹션명이 이 패턴에 안 맞음 등)은 **아무것도 안 하고 조용히 건너뜀**
(결측 > 오염, 짐작 금지 원칙 유지) — Phase 2 대상으로 남김.

발동 시: `비지배` 행의 값 → `is.noncontrolling_ni`에 후보로 추가(stage는 예:
`"structural"` 신설, `_STAGE_RANK`에 낮은 우선순위로 등록해 기존 exact 매칭을
방해 안 하게 함). 나머지 행의 값 → `is.controlling_ni`에 후보로 추가.

### 2-3. 측정된 안전성

- **오탐 0건**: 규칙이 발동한 모든 케이스(그룹A 78건 전체 대상 재검증)에서 규칙이
  고른 값이 Gate B의 독립 원문값(`report_won`, XBRL 직접추출 — 4개사는 XML로 추가
  교차확인)과 정확히 일치(±2원 이내). 값이 다르게 나온 경우는 **0건**이었다(초기
  버전은 섹션명 필터가 느슨해 5건 오답이 났으나, `"순이익"` 포함 조건을 추가해
  총포괄손익 섹션과의 혼동을 제거한 뒤 0건으로 정리됨 — 이 필터링 과정 자체가
  설계의 일부로 기록됨).
- **기존 안전망 재사용**: 삼성전자 사례로 실제 `_match_ni_identity()` 함수를 직접
  호출해 검증 — 후보 보강 후 `(controlling=8,028,407,000,000,
  noncontrolling=194,471,000,000)` 쌍이 유일하게 항등식을 만족해 정확히 선택됨.
  새 선택 로직의 회귀 리스크가 없다(5dbecac의 12개 유닛테스트가 이미 이 함수를
  검증해뒀음).

---

## 3. 구현 스케치 (미착수, 승인 후 진행)

- **위치**: `fin2/layer3/combine.py::_map_rows()` — AccountMapper 매핑 루프 이후,
  반환 직전에 신설 함수 `_ni_attribution_structural_candidates(rows, statements)`
  호출해 `cands["is.controlling_ni"]`/`cands["is.noncontrolling_ni"]`에 `extend`.
- **신설 함수 시그니처(안)**:
  ```python
  def _ni_attribution_structural_candidates(rows: list[dict]) -> dict[str, list[dict]]:
      """섹션 구조(§2-2)로 지배/비지배 귀속 행을 라벨과 무관하게 식별해 추가 후보를
      반환. 발동 조건 미충족 시 빈 dict. combine.py 원문 표기 규칙 R? 로 PARSING_RULES
      등재 예정."""
  ```
- **중복 제거**: `_resolve()`의 `vals = {r["value"] for r in rows}`가 이미 값
  기준 dedup이라, account_mapper가 우연히 같은 값을 이미 올바르게 잡아둔 경우
  자동으로 합쳐짐(추가 처리 불필요).
- **스코프 제약**: `is.controlling_ni`/`is.noncontrolling_ni` 두 canonical에만
  적용 — 다른 필드에 영향 없음.
- **테스트**: `fin2/tests/test_combine_ni.py`(5dbecac이 만든 파일)에 케이스 추가 —
  section-구조 매칭 성공/실패/모호 3종 + 삼성전자류 실제 라벨 재사용 회귀 픽스처.

---

## 4. 이번 설계 범위 밖 (Phase 2 후보, 미설계)

- **mismap 잔여 19건**: §2-2 규칙이 못 잡는 형태 확인됨(스팟체크):
  - 섹션명에 "순이익"이 없고 "귀속"이 라벨 안에 박혀있는 경우(제이스코홀딩스:
    section=`총포괄이익`, label=`지배기업의 소유주에게 귀속되는 당기순이익(손실)`)
  - 귀속 섹션이 1행뿐(비지배 행이 별도로 없거나 0으로 안 보임 — 카스·신도리코류)
  - 컴팩트 단일라벨 포맷(section_path 자체가 없고 라벨 문자열에
    `...의 귀속 - 지배기업의 소유주` 통째로 들어있는 경우 — KPX홀딩스류)
  - 이들은 서로 다른 패턴이라 하나의 규칙으로 안 묶임 — 개별 조사 필요.
- **하위메커니즘②(완전미매핑, 24건)**: AccountMapper가 라벨을 아예 어떤
  canonical에도 안 붙임. §2 규칙이 11/24를 부수적으로 살리지만 전수 보장 아님.
- **하위메커니즘③(안전망자체오류, 3건)**: `is.controlling_ni`에 후보가 이미
  2개 이상인데도 identity 매칭이 틀린 값을 고름 — 5dbecac 로직 자체의 잔여
  버그 가능성, 원인 미규명.
- **그룹B(7건/6개사, 부호 자체가 다름)**: 원문대조 아직 0건, 이 메커니즘과 무관.

---

## 5. 검증 계획 (구현 승인 시)

1. `fin2/tests/test_combine_ni.py`에 유닛테스트 추가 후 pytest 전체 통과 확인.
2. 32건 표본 재계산(`combine_full()` 직접 호출) — `report_won`과 일치 확인(현재
   이미 읽기전용으로 확인됐지만 실제 함수 경로로 재확인).
3. **DB는 이 시점까지 미변경** — 승인 시에만 std_financials_v3 소급 백필
   ([[parser-pipeline-integration-runbook]] 절차: 두 call site 배선 + 백필 + Gate B
   재검사).
4. Gate B 재검사: `controlling_ni` fail_a 86 → 예상 86-32=54 (그룹A 46 + 그룹B 7 +
   그룹C 1, 안전망③ 3건은 겹쳐 카운트 주의).

---

## 6. 산출물 (읽기전용, 미커밋)

- `scripts/probe_gateb_controlling_ni_groupA_scale_2026-08-15.py` — 78건 전수
  메커니즘 분류(단독후보/다중후보 × mismap/미발견).
- `scripts/probe_gateb_controlling_ni_mismap_design_verify_2026-08-15.py` — 구조규칙
  단독 검증(1차, 44/78 성공 → 필터 보정 후 재실행).
- `scripts/probe_gateb_controlling_ni_crosstab_2026-08-15.py` — 메커니즘×구조규칙
  정밀 교차표(최종, 32/51 mismap 성공 확인용).

관련: 메모리 `gateb-controlling-ni-groupa-rootcause-2026-08-15`,
`gateb-controlling-ni-triage-handoff-2026-08-15`,
`std_v3_controlling_ni_oci_section_fix_design_2026-08-12.md`(5dbecac 설계문서).
