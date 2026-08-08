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
당기순이익(손실)')이 같은 패턴으로 충돌하므로 동일 결함일 가능성이 높음 —
**Phase B 착수 전 선행조사로 확정함(2026-08-08, §3-2 앞 문단 참고)**.

### 1-B-부록. 선행조사 결과 — noncontrolling_ni도 동일 결함 확정 (2026-08-08)

`account_maps/is_accounts.py`의 `is.noncontrolling_ni` alias 목록에 맨 라벨 `'비지배지분'`이
들어있다(`is.controlling_ni`의 `'지배기업 소유주지분'`과 완전히 같은 함정). 삼성전자 FY2023
연결로 직접 확인:

```
report_lines 원문(둘 다 실재, 섹션 다름):
  '포괄손익의 귀속'         섹션 → "비지배지분"                    = 991,750,000,000   (총포괄분, 오답)
  '당기순이익(손실)의 귀속' 섹션 → "비지배지분에 귀속되는 당기순이익(손실)" = 1,013,699,000,000 (정답)

검산: 14,473,401,000,000(정답 controlling) + 1,013,699,000,000(정답 noncontrolling)
     = 15,487,100,000,000 = net_income ✓
     17,845,661,000,000(오답 controlling) + 991,750,000,000(오답 noncontrolling)
     = 18,837,411,000,000 ≠ net_income (총포괄이익, 다른 개념)
```

DB 전수 측정(현재 std_v3, consolidated, 92,290행 기준):
| 축 | 수치 |
|---|---|
| `is.controlling_ni` held conflict (controlling_ni NULL) | 26,420행 (consolidated 26,112 + separate 잔류 308) |
| `is.noncontrolling_ni` held conflict | 16,825행 |
| 위 두 conflict가 **동시에** 걸린 행 | 13,809행 |
| controlling_ni-conflict 중 net_income 있는 행 | 25,865행 |
| — 그중 noncontrolling_ni도 동시 conflict | 13,704행 |
| — 그중 noncontrolling_ni는 clean(단일확정 또는 후보없음) | 12,161행 |

항등식 재선택 실현가능성 표본검증(13,704행 **전수**, `controlling+noncontrolling==net_income`
정확매칭 여부 — ⚠최초 300건 표본에서 "복수매칭 2.7%"로 측정했었으나 **버그였다**: 동일
값이 candidate 리스트에 중복으로 들어간 걸 별개 매칭으로 잘못 셈. 값 기준 dedupe 후 전수
재측정한 아래 표가 정답):
| 결과 | 건수 | 비율 |
|---|---|---|
| 후보조합 중 **유일하게** 일치 | 13,175 | 96.1% |
| **복수** 조합이 일치(진짜 동률) | 8 | 0.06% |
| 일치하는 조합 **없음**(보류 유지가 안전) | 521 | 3.8% |

**타이브레이크는 도입하지 않기로 함(2026-08-08, 사용자 결정 반영)**: 위 진짜 동률 8건을
`amended`(기재정정) 여부로 재확인했더니 **전부 `amended=False`** — 기재정정과 무관했다(최초
가설 오류, 정정). 대신 8건 전부 §1-B와 동일한 라벨충돌(같은 라벨이 "순이익 귀속"/"포괄손익
귀속" 두 섹션에 동시 존재)이었고, 우연히 그 기간 기타포괄손익(OCI)이 작아 두 섹션 합계가 둘 다
net_income과 맞아떨어져 항등식으로도 못 갈랐을 뿐. "섹션명에 '포괄'이 있으면 버린다"는
대안도 검토했으나(149건 표본 중 96.6% 항등식과 일치) **반례 2건(0.5%)을 발견**해 기각—
DH오토웨어(00110583, 2022반기, https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220812001066)
· 에프알텍(00442561, 2017반기, https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170814000908)은
**원문 자체에서 "순이익의 귀속"/"총포괄손익의 귀속" 두 섹션 라벨이 서로 뒤바뀌어 있다**(사용자가
원문 표로 직접 대조·확인). 섹션명 필터였다면 이 2건에서 오답을 골랐을 것 — 항등식 교차매칭은
net_income 실값에 고정돼 있어 라벨이 뒤바뀌어도 정답을 찾아낸다. **결론**: 타이브레이크
규칙을 새로 만들지 않는다 — 진짜 동률 8건(0.06%)·무매칭 521건(3.8%) 둘 다 그냥 보류(NULL
유지)한다("결측 > 오염" 원칙, 규모도 무시할 만큼 작음).

**§3-2 재선택 로직 확정**: `is.controlling_ni` 단독이 아니라 `is.controlling_ni`+
`is.noncontrolling_ni` **후보쌍을 함께** 놓고 confirmed net_income과의 항등식으로 재선택.
유일 매칭이면 채택, 아니면(0건·2건 이상 모두) 보류.

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

옵션 1이 기존 구조를 덜 건드림. **선행조사 결과(§1-B-부록, 2026-08-08 완료)**: `noncontrolling_ni`도
동일 결함 확정(라벨 `'비지배지분'` 충돌). 2차 패스는 `is.controlling_ni` 후보 하나만 보지 말고
**`is.controlling_ni`×`is.noncontrolling_ni` 후보쌍을 교차**해 confirmed net_income과 정확히
합이 맞는 조합을 찾는다(전수 96.1%는 유일 매칭 → 즉시 채택, 0.06%(진짜 동률)·3.8%(무매칭)는
타이브레이크 없이 그대로 보류 — 근거는 §1-B-부록 끝부분). noncontrolling_ni 자체는 std 컬럼이
아니므로(DIRECT_MAP에 없음) 저장 대상이 아니라 재선택 판정에만 쓰인다.

**구현 완료(2026-08-08)**: `fin2/layer3/combine.py::_resolve_ni_attribution()` 신설,
`combine_full()`에서 `_resolve()` 직후 호출. 삼성전자·삼성물산·현대해상·기업은행(§4 표본) +
라벨스왑 2사(DH오토웨어·에프알텍) + 진짜동률 1건(00684802, 보류 유지 확인) 전부 검증 통과.
150개 기업(5,724행) 재빌드 회귀 대조 — 기존 non-NULL 값 변경 0건, 신규 채움 1,538건.
pytest 439 passed / 1 failed(무관 — `test_lxintl_facility_table_dropped`, 사업개황 파싱,
`fin2/layer3/combine.py`와 무관).

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

### Phase B — consolidated 라벨충돌 재선택 (§3-2, 순서 의존성 있음) — ✅완료(2026-08-08)
- [x] **선행조사**(2026-08-08 완료): `noncontrolling_ni`도 같은 라벨충돌 패턴(§1-B) 확정 —
      alias `'비지배지분'`이 `is.noncontrolling_ni`에 등재돼 있어 controlling_ni와 동일 함정.
      DB 전수측정 16,825행 held-conflict, controlling_ni-conflict와 동시발생 13,809행.
      항등식 재선택 전수측정(13,704행): 유일매칭 96.1%·진짜동률 0.06%·무매칭 3.8%.
      타이브레이크 불필요 결론(라벨스왑 반례 2사 발견, §1-B-부록 끝부분). 상세 = §1-B-부록.
- [x] `_resolve()`를 2-패스로 재구성: `combine.py::_resolve_ni_attribution()` 신설,
      `_resolve()` 직후 호출. `is.controlling_ni`×`is.noncontrolling_ni` 후보쌍을 confirmed
      net_income과 교차해 유일 매칭만 채택(§3-2 옵션 1, 타이브레이크 없음)
- [x] 기존 non-NULL 값이 하나도 안 바뀌는지 회귀 확인 — 150개 기업(5,724행) 재빌드 대조,
      **변경 0건**·신규 채움 1,538건
- [x] 단위 검증: 삼성전자 FY2023 연결(14,473,401,000,000) ✓ · 삼성물산 2023Q3(1,830,533,213,586
      ≈18,305억) ✓ · 현대해상 2022FY(574,557,219,967=net) ✓ · 기업은행 별도 재확인(Phase A
      무회귀) ✓ · 라벨스왑 2사(DH오토웨어·에프알텍) 정답 채택 ✓ · 진짜동률(00684802) 보류 유지 ✓
- [x] pytest 439 passed / 1 failed(무관, 사업개황 파싱)
- [ ] 커밋(B만 단독)

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
