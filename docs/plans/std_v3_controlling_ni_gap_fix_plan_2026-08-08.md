# 수정 계획 — `std_financials_v3` controlling_ni 대량 공백 (2026-08-08 작성, **미실행**)

> ⚠**이 문서는 계획이다. 승인 전 어떤 코드/DB 변경도 하지 않는다.**
> (CLAUDE.md: 계획 작성 후 자동 실행 금지 — 실행은 별도 요청으로 받는다.)

배경: `docs/qa/handoff_post_r11_next_steps_2026-08-08`(메모리 `handoff-post-r11-next-steps-2026-08-08`)
§1 "재설계 본류 다음 액션"을 착수하기 전 상태 점검(①controlling_ni 소급 재표준화·D&A 커버리지
확인) 중 발견. `docs/qa/triage_controlling_ni_residual_2026-07-14.md` 이래 이어진
`[[bug-controlling-ni-total-comprehensive]]` 계열의 **연장선**이지만, 대상 테이블이 다르다
(v2가 아니라 v3).

---

## 0. 요약

- 구(old) 체인 `std_financials_v2`는 7월에 이 버그를 완전히 고쳤다(P1~P3, Class A/B/C).
  **하지만 앱은 지금 v2를 안 본다** — 사용자 확인: Streamlit 앱을 실제로 조회하고 있지 않음.
  v2 잔여(18건, 소액·2012~2016년 소형사)는 이번 계획 범위 밖(우선순위 낮음, 별도 트리아지 대상).
- 신(new) 체인 `std_financials_v3`(재설계 §5 "뷰 브리지 전환" 이후 앱이 옮겨갈 목표 테이블)에는
  **같은 버그가 다른 증상으로 남아있다**: v2는 "틀린 값으로 덮임"이었는데, v3는 충돌을
  보류(hold)하는 설계라 **"NULL로 사라짐"**이다. v2에서 만든 수정 로직 2종이 v3
  파이프라인(`fin2/layer3/combine.py`)에 **이식되지 않았다**.
- 커버리지: `controlling_ni` 전체 184,580행 중 23.0%(42,502행)만 non-NULL. 최신FY 연결
  기준 45.2%(1,138/2,520). **삼성전자 FY2023 연결도 NULL.**

---

## 1. 원인 — 확정 (원문·코드 대조 완료)

### 1-A. 별도재무제표(separate) — 강제 규칙 자체가 없음 (전체 공백의 주 원인, 큰 win)

| 축 | 수치 |
|---|---|
| separate 전체 행 | 92,290 |
| net_income 있음 | 91,896 (99.6%) |
| controlling_ni 있음 | **755 (0.8%)** |
| 있는 755건 중 net_income과 다른 값 | 209건(오염 가능성, v2에서 봤던 스케일/오매핑류) |

별도재무제표는 회계 정의상 비지배지분이 없어 `controlling_ni ≡ net_income`이다. v2는
`fin2/standardize/rules.py::rule_controlling_ni_fill`(line 246)로 이를 **항상 강제**한다
(별도는 무조건 net_income 대입, NULL이든 오염값이든). **v3에는 이 규칙이 없다** —
`fin2/layer3/combine.py`에 `separate` 분기 처리가 전무(grep 확인, "controlling" 매치 1건뿐,
`_LOSS_CANON` 목록 안).

### 1-B. 연결재무제표(consolidated) — 라벨 충돌 재선택 규칙 부재 (v2 버그의 직계 재발)

`_map_label()`을 직접 호출해 재현(삼성전자 FY2023 연결):

```
report_lines 원문(둘 다 실재, 섹션 다름):
  '당기순이익(손실)의 귀속' 섹션 → "지배기업의 소유주에게 귀속되는 당기순이익(손실)" = 14,473,401,000,000  (정답)
  '포괄손익의 귀속'         섹션 → "지배기업 소유주지분"                              = 17,845,661,000,000  (총포괄분)

_map_label() 결과 — 둘 다 exact match, confidence=1.0:
  '지배기업 소유주지분'                          → is.controlling_ni
  '지배기업의 소유주에게 귀속되는 당기순이익(손실)' → is.controlling_ni
```

값이 19% 차이 나서 `_reduce_conflict()`의 범용 해소(동일값 병합→EPS 유사중복→최상위깊이
선호)가 못 고르고 **보류(held conflict)** → `confirmed`에 안 들어감 → std_v3엔 NULL.

v2의 `fin2/standardize/build.py::_collect`는 이 상황 전용 규칙이 있다 — 후보가 여럿이면
항등식 `controlling_ni + noncontrolling_ni = net_income`에 가장 가까운 값을 선택(커밋
`22d21f9`). **이 규칙도 v3에 이식되지 않았다.**

측정: `controlling_ni IS NULL AND conflicts ? 'is.controlling_ni'` = 26,420행(전체 NULL
142,078행의 18.6%). `noncontrolling_ni`도 라벨('비지배지분' vs '비지배지분에 귀속되는
당기순이익(손실)')이 같은 패턴으로 충돌하므로 동일 결함일 가능성이 높음(미측정 — 조사범위).

### 1-C. 파일 상단 주석과의 불일치

`fin2/layer3/combine.py:8` 주석: "Port the old chain's conflict resolution
(build._resolve / _reduce_conflict)". 실제로는 **범용** 충돌해소만 옮겨졌고, 계정별
전용 규칙(controlling_ni 재선택 · separate 강제)은 이식 대상에서 빠졌다. 의도적 축소인지
누락인지는 커밋 이력에서 확인 안 됨(범위 밖).

---

## 2. 예상 회수 규모 (추정 — 실측 아님)

| 수정 | 예상 회수 | 근거 |
|---|---|---|
| A) separate 강제 규칙 이식 | +~91,100행 | net_income 있는데 controlling_ni 없는 separate 행 수 |
| B) consolidated 재선택 규칙 이식 | +~26,400행 | held conflict + net_income 존재 행 수 |
| **합계(추정)** | 42,502 → **~160,000행 (86.7%)** | net_income coverage(99.0%)에 근접 |

B는 net_income이 먼저 확정돼 있어야 해서 A보다 구현이 까다롭다(§3-2 참고). 나머지
잔여(~24,500행, 13.3%)는 net_income 자체가 없거나(비금액), 라벨이 카탈로그에 아예 없는
케이스로 별도 트리아지 대상.

---

## 3. 수정 방향 (구현 시 참고 — 아직 코드 안 건드림)

### 3-1. A) separate 강제 — 낮은 위험, 즉시 가능

`fin2/layer3/build.py::build_corp()`가 `combine_full()` 호출 후 컬럼을 채우는 지점
(현재 `for c in _VALUE_COLS: if c in col: ...` 근처)에 `basis == "separate"` 분기 추가.
v2 규칙 그대로 포팅(별도는 무조건 net_income 대입). 위험 낮음 — v2에서 이미 검증된 규칙,
회계 정의상 항상 참.

### 3-2. B) consolidated 재선택 — 순서 의존성 있음

`_resolve(cands)`는 canonical들을 **개별적으로**(순서 무관하게) 한 번에 처리한다
(`for c, rows in cands.items()`). `is.controlling_ni`/`is.noncontrolling_ni`를 항등식으로
재선택하려면 `is.net_income`이 이미 `confirmed`에 들어있어야 한다. 옵션:

1. **2-패스**: 1차 패스로 `is.net_income`(및 다른 모든 canonical) 확정 → 2차 패스에서
   `is.controlling_ni`/`is.noncontrolling_ni`만 confirmed net_income 참조해 재선택.
2. `_resolve` 내부에서 처리 순서를 강제(net_income을 먼저 처리하도록 정렬).

옵션 1이 기존 구조를 덜 건드림. `noncontrolling_ni`도 같은 패턴이면 **먼저 조사 필요**
(현재 결함이 controlling_ni에만 있는지, 두 canonical 모두에 있는지 §1-B 끝의 미측정 항목).

### 3-3. 백필

`std_financials_v3`는 `(corp, fy, period, basis)` 단위로 idempotent
delete-then-insert(`fin2/layer3/build.py::build_corp`, line 60~66)이므로, 코드 수정 후
`scripts/build_std_v3.py --all` 재실행이면 전체 재빌드된다(현재 184,580행, 규모상 시간
소요 — 사용자 터미널 직접 실행 대상, `[[feedback-long-running-commands]]`).

---

## 4. 검증 계획

- **알려진 케이스 재확인**(v2 수정 때 썼던 표본 재사용):
  - 삼성전자 00126380 FY2023 연결 → 14,473,401,000,000 나와야 함(현재 NULL)
  - 삼성물산 00140312 2023Q3 연결 → 18,305억(=net−nci) 나와야 함
  - 현대해상 2022FY 연결 → 5,746억(=net) 나와야 함
  - 기업은행(별도) → controlling_ni = net_income(자본값 138,722억이 아니라 분기순이익)
- **전수 회귀**: 수정 전/후 `controlling_ni` non-NULL 카운트 증가분이 §2 추정치(±상당폭)와
  부합하는지, 그리고 **기존 non-NULL 값이 하나도 안 바뀌는지**(2-패스가 이미 확정된 값을
  덮지 않는지) 확인.
- **원문 대조**: 회수된 값 중 무작위 20~30건을 report_lines 원문과 직접 대조.
- Gate B는 이 체인(v3)을 구조적으로 안 본다는 게 기존 확인 사항([[xbrl-instance-parser-plan-2026-08-05]])
  — 별도 원문대조가 유일한 검증 수단.

---

## 5. 범위 밖 (이번 계획에 안 넣음)

- v2 잔여 18건 소액 불일치 — 별도 트리아지, 우선순위 낮음.
- v2의 R&D 커버리지 저하(`source_format='note_rd'` 소실) — 앱이 v2를 안 보므로 이번엔 보류.
  다음 세션 후보로만 기록.
- `noncontrolling_ni` 동일 패턴 여부 정밀 측정 — 구현 착수 시 §3-2 옵션 결정 전에 먼저
  확인 필요(구현의 일부로 포함하되, 별도 "발견"은 아님).
- 재설계 §5 본류(뷰 브리지 전환 자체) — 이 계획은 그 전제조건(v3 데이터 품질) 중 하나만
  다룬다. 브리지 전환 자체는 별도 착수.

---

## 6. TODO 체크리스트 (승인 후 실행 순서)

> 이 계획을 사용자가 검토·승인한 뒤에만 착수한다(§ 상단 경고 참고). 체크박스는 진행하며
> 갱신한다.

### Phase A — separate 강제 규칙 (§3-1, 낮은 위험) — ✅완료(2026-08-08)
- [x] `fin2/layer3/build.py::build_corp()`에 `basis == "separate"` 분기 추가 —
      v2 `rules.py::rule_controlling_ni_fill` 로직 포팅(별도는 controlling_ni=net_income 강제)
- [x] 단위/소규모 검증: 기업은행(00149646) 별도 전 기간(2015~2026Q1, 43행)에서
      controlling_ni == net_income 확인, 자본값(138,722억) 오염 없음(--corp 단일 재빌드로 검증)
- [x] 커밋(A만 단독으로, B와 분리) — 커밋 후 해시 기록 예정

### Phase B — consolidated 라벨충돌 재선택 (§3-2, 순서 의존성 있음)
- [ ] **선행조사**: `noncontrolling_ni`도 같은 라벨충돌 패턴(§1-B)이 있는지 실측
      (`_map_label()`로 '비지배지분' 계열 라벨 재현 + held-conflict 카운트)
- [ ] `_resolve()`를 2-패스로 재구성: 1차 패스 = `is.net_income` 등 일반 canonical 확정,
      2차 패스 = `is.controlling_ni`/`is.noncontrolling_ni`를 confirmed net_income 기준
      항등식 재선택(§3-2 옵션 1)
- [ ] 기존 non-NULL 값이 하나도 안 바뀌는지 회귀 확인(2-패스가 이미 확정된 값을 덮지 않는지)
- [ ] 단위 검증: 삼성전자 FY2023 연결(14,473,401,000,000), 삼성물산 2023Q3(18,305억),
      현대해상 2022FY(5,746억) 재현
- [ ] 커밋

### 전량 재빌드 + 검증
- [ ] `scripts/build_std_v3.py --all` 전량 재빌드(idempotent delete-then-insert,
      **사용자 터미널 직접 실행** — `[[feedback-long-running-commands]]`)
- [ ] 커버리지 재측정: `controlling_ni` non-NULL 카운트가 §2 추정치(~160,000행, 86.7%)에
      부합하는지
- [ ] 원문 대조: 회수된 값 중 무작위 20~30건을 `report_lines` 원문과 직접 대조
- [ ] `docs/plans/rearchitecture_4layer.md` §5에 이번 수정 완료 반영(뷰 브리지 전환의
      전제조건 중 하나 해소로 기록)

### 범위 밖(이번엔 안 함, 후속 후보로만 기록)
- [ ] (후순위) v2 R&D 커버리지 저하 원인 수정 — `fin2_extract_rd_note.py`가 `fact_v2` 대신
      `std_financials_v2.revenue`를 참조하도록 고쳐서 재실행. 앱이 v2를 안 봐서 급하지 않음
- [ ] (후순위) v2 잔여 18건 controlling_ni 소액 불일치 개별 트리아지

관련 메모리: `[[bug-controlling-ni-total-comprehensive]]` `[[handoff-post-r11-next-steps-2026-08-08]]`
`[[data-coverage-gaps]]` `[[std-v3-controlling-ni-gap-2026-08-08]]`
