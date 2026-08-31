# `bs.current_portion_lt_debt` 개념분리 설계 (가칭 R60, 2026-08-31)

## 0. 배경 — §6 후속 백로그에서 승격

`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §6:

> **`bs.current_portion_lt_debt` 개념 분리**(순서4-① 검증 중 신규 발견, 2026-08-31,
> `00102858`/`00115977` 원문대조) — 지금은 `유동성장기부채`/`유동성장기차입금`/
> `유동성사채` 3개 서로 다른 개념이 한 canonical에 있어... v3도 `유동성사채`를
> 별도 canonical(가칭 `bs.current_bond_plain`)로 분리하면 회수율이 더 올라갈 것으로
> 보이나, 순서4-①~③ 범위 밖 — **규모 미실측**, 별도 트랙으로.

이 문서는 그 "규모 미실측"을 실측하고 구체적인 수정안을 확정한다.

## 1. 증상

`account_maps/bs_accounts.py`의 `bs.current_portion_lt_debt`는 개념이 다른 두
계열을 한 canonical에 등록하고 있다:

```python
"bs.current_portion_lt_debt": [
    "유동성장기부채", "유동성장기차입금",      # 장기"부채/차입금"의 유동성 대체분
    "유동성사채",                              # 사채의 유동성 대체분 (별개 개념!)
    "비유동차입금(사채포함)의유동성대체부분",
    "비유동차입금의유동성대체부분",
],
```

R58/R58-순서4-③에서 이미 4번 반복된 것과 같은 병리(전환사채/교환사채/신주인수권부사채를
각각 별도 canonical로 분리한 이유와 동일): 한 회사가 "유동성사채"와
"유동성장기부채"(또는 "유동성장기차입금")를 **같은 필링에 별도 줄로 동시 공시**하면,
두 값이 하나의 canonical로 몰려 `_resolve()`가 서로 다른 값을 가진 두 후보로 보고
**canonical 전체를 HELD**(=None) 처리한다 — 유동성사채분만 버려지는 게 아니라
유동성장기부채분까지 통째로 소실된다.

**실측 사례**(`00102858`, FY2008 연결, `report_lines` 원문 대조):

| label_raw (각주 제거 후) | value_won |
|---|---:|
| 유동성사채 | 75,056,000,000 |
| 유동성장기부채 | 53,884,912,604 |

두 줄이 별도 BS 항목으로 동시 존재 → 현재 코드는 `bs.current_portion_lt_debt`
전체를 HELD, net_debt 계산에서 약 1,289억원이 통째로 빠진다.

**v2와의 비교**: v2는 XBRL acode 기반으로 애초에 `bs.current_lt_debt`(장기부채/
차입금의 유동성대체분)와 `bs.current_bonds_plain`(사채의 유동성대체분)을 **별도
canonical**로 분리해 이 충돌 자체가 없다(`fin2/taxonomy/concept_map.py:59` —
`dart_CurrentPortionOfBonds → bs.current_bonds_plain`). v3만 이 둘을 하나로 합쳐
회귀가 생긴 형태다.

## 2. 실측 — 영향 규모

`report_lines` 전수(BS, 각주참조 `(주14)` 류 제거 후 정규화 라벨 기준, 2001~2026):

| 측정 | 값 |
|---|---:|
| "유동성사채" + "유동성장기부채류"(유동성장기부채/유동성장기차입금/비유동차입금(사채포함)의유동성대체부분/비유동차입금의유동성대체부분) 동시존재 필링 | **3,405건** |
| 영향받는 서로 다른 기업 수 | **487개사** |
| 연도별 분포 | 연 100~270건, 고르게 분포(FY2024: 259건, FY2025: 269건) — 최근 연도도 예외 아님 |

**"기존 `bs.current_bond`로 그냥 합치면 안 되는 이유"도 실측 확인**:
`bs.current_bond`(현재 등록: 유동성회사채/단기사채/사채(유동)/유동사채)와 "유동성사채"가
동시 존재하는 필링은 227건(90개사)인데, 그중 **176건은 값이 서로 다르다**(51건만
우연히 값이 같아 충돌 없이 넘어감). 즉 단순 병합은 3,405건의 기존 버그를 고치는
대신 176건의 **새 버그**를 만든다 — 반드시 완전히 새로운 leaf canonical이어야 한다.

**다른 이미 분리된 사채계열과의 co-occurrence**(참고, 충돌 위험 아님 — 각각 별도
canonical이라 후보 풀을 공유하지 않음): 유동성사채 ∩ 전환사채(유동)류 544건,
∩ 교환사채(유동)류 68건, ∩ 신주인수권부사채(유동)류 161건. 이미 정착된
전환사채/교환사채/신주인수권부사채 분리 패턴과 정합적 — "유동성사채"도 그 계열의
다섯 번째 leaf가 되는 셈이다.

## 3. 수정안

### 3-1. 신규 canonical 등록 (`account_maps/bs_accounts.py`)

```python
"bs.current_portion_lt_debt": [
    "유동성장기부채", "유동성장기차입금",
    # "유동성사채"는 아래 bs.current_bond_plain으로 이관(개념분리, R60) — 여기 남기지 않는다.
    "비유동차입금(사채포함)의유동성대체부분",
    "비유동차입금의유동성대체부분",
],
...
# R60 (2026-08-31): "유동성사채"(사채의 유동성 대체분)는 "유동성장기부채/차입금"
# (장기부채·차입금의 유동성 대체분)과 개념이 다르다 — v2는 XBRL acode로 애초에
# bs.current_lt_debt/bs.current_bonds_plain 2개로 분리돼 있다(fin2/taxonomy/
# concept_map.py:59 dart_CurrentPortionOfBonds). 같은 필링에 두 라벨이 동시
# 공시되는 사례가 3,405건/487개사 실측돼 bs.current_portion_lt_debt에 합쳐두면
# `_resolve()` 충돌로 canonical 전체 HELD(00102858 FY2008 연결: 유동성사채
# 750.56억 vs 유동성장기부채 538.85억 동시존재 → 전액 소실). 기존 bs.current_bond
# (유동성회사채/단기사채/사채(유동)/유동사채)로 병합하는 안은 기각 — 실측 227건 중
# 176건이 값 충돌(새 버그 유발). 전환사채/교환사채/신주인수권부사채와 같은 패턴으로
# 완전히 새로운 leaf canonical로 분리한다.
"bs.current_bond_plain": [
    "유동성사채",
],
```

### 3-2. `combine.py` 배선 — `_V3_ST_DEBT_PARTS`에 편입

```python
_V3_ST_DEBT_PARTS = ("bs.short_term_debt", "bs.current_portion_lt_debt", "bs.current_bond",
                     "bs.current_convertible_bond", "bs.current_exchange_bond",
                     "bs.current_warrant_bond",
                     "bs.current_bond_plain")   # R60
```

`_V3_LT_DEBT_PARTS`는 변경 없음(비유동측엔 이미 `bs.bond`가 있고, "유동성사채"는
정의상 유동 항목만).

`bs.current_bond_plain`은 net_debt 전용 파생 집계에만 쓰이는 leaf라 DIRECT_MAP에는
연결하지 않는다(기존 `bs.current_portion_lt_debt`/`bs.current_bond`와 동일 — §2-7
wiring 주석 "DIRECT_MAP has no destination for any of the three" 참고).

### 3-3. 소급 백필

파서/로더 변경이므로 [[parser-pipeline-integration-runbook]] 절차 적용:
① 데일리 파이프라인은 `combine.py`/`bs_accounts.py`를 매 실행 참조하므로 별도
배선 불필요(신규 필링부터 자동 반영). ② 과거분(1999~현재)은 표준 std_v3
전수 재표준화(`standardize_corp` 류 재실행)로 소급 백필 필요 — 영향 487개사
한정 재빌드(전사 재빌드 불필요, R58/R59와 동일 방식).

## 4. 검증 계획

- [x] **4-1.** 사전 확인(2026-08-31) — `fin2/audit/face_audit.py`에 `debt` 관련
      `field=` 등록 0건(grep 실측). R59와 동일하게 face_audit(Gate B)은
      `long_term_debt`/`short_term_debt`/`current_portion_lt_debt`를 애초에 감사
      대상에 포함하지 않는다 → Gate B pass→fail_a 전이는 참고용일 뿐, 값 복구
      검증은 **std_financials_v3(경유 net_debt) 전/후 스냅샷 직접비교**가 주된
      방법이다(4-4).
- [ ] **4-2.** 단위 테스트 — `bs.current_bond_plain` 신규 canonical 매핑 확인
      + `00102858` FY2008류 합성 케이스로 회귀 테스트 추가(R57/R58/R59 선례처럼
      `fin2/tests/test_combine_debt_*` 계열에 추가).
- [ ] **4-3.** 영향 487개사 재표준화 후 Gate B 전수재감사 — pass→fail_a 전이 **0건**
      확인(4-1에서 audit 대상이면 이 게이트가 핵심, 아니면 참고용).
- [ ] **4-4.** `std_financials_v3.current_portion_lt_debt`(신설 컬럼 없음 — net_debt
      합산 중간값이라 별도 컬럼화하지 않음, R58/R59와 동일) 대신 **net_debt** 자체의
      전/후 스냅샷 비교 — 3,405건 중 표본(00102858 포함 5~10개사)을 원문대조.
- [ ] **4-5.** `pytest tests/ fin2/tests/` — 루트 범위 없이, 회귀 0건 확인.
- [ ] **4-6.** net_debt v2/v3 불일치율(§2-10 최종치 40.6%/51.4%) 재측정 — 이번
      회수분이 그 지표에 미치는 영향 정량화(단, §2-10 교훈대로 "지표 악화/개선"을
      곧바로 버그 유무 판단에 쓰지 않는다 — 원문대조 우선).

## 5. 위험도

**낮음~중간** — 코드 변경 자체는 alias 1개 이관 + 신규 canonical 1개 등록(패턴은
기존 4개 사채계열 분리와 완전히 동일, 이미 검증된 접근). 위험 요소는 영향 규모가
487개사로 이전 트랙들(수십~수백 개사)보다 크다는 점 — 4-3 전수재감사를 반드시
거친다([[gateb-full-reaudit-is-required-to-close]]).

---

이 문서는 계획이며, 사용자 승인 없이 구현에 착수하지 않는다.
