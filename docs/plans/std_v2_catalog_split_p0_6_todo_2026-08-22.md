# P0.6 — 카탈로그 분해 착수 전 추가 조사 + 실행 체크리스트 (읽기전용)

> **상위 문서**: [`std_v2_retirement_port_to_v3_2026-08-22.md`](std_v2_retirement_port_to_v3_2026-08-22.md)
> — v2 폐기 준비 마스터 계획(P0.5까지의 실측은 그 문서 §3.11).
> 이 문서는 그 계획의 **P0.6(착수 전 추가 조사)** 실행 체크리스트다.
>
> 작성 2026-08-22. 상태 = **조사 미착수 · 사용자 결정 A/B/C 반영 완료**.

---

## 1. Context

`std_v2` 폐기 트랙의 P0.5에서 **v3가 리스·차입금 값을 이미 대량으로 버리고 있다**는 사실이
실측으로 드러났다.

원인: `유동리스부채`(exact 1.0)와 `비유동리스부채`(fuzzy 0.977)가 **둘 다
`bs.lease_liability`로 매핑**되어 값이 다른 두 행이 한 canonical에 모이고 →
`fin2/layer3/combine.py::_resolve()`가 충돌로 HOLD → 값이 통째로 사라진다.
실측 **lease 97.4%(301/309) · CF차입 81.7%(245/300)**.
게다가 이 손실은 `conflicts` 컬럼에도 안 남는다 — `combine.py:1770`이 `CONSUMED_CANON`에
있는 canonical만 기록하는데 `bs.lease_liability`·`cf.borrowings_proceeds`는
`fin2/standardize/rules.py`에 아예 없기 때문이다(**조용한 손실**).

### 사용자 결정 (2026-08-22)

| 결정 | 내용 |
|---|---|
| **A. 경로** | **이름표 분해 채택.** 유동/비유동을 별도 canonical로 분리하고 **이름은 v2와 동일하게**(`bs.lease_current`/`bs.lease_noncurrent`, `cf.borrow_proceeds_st`/`_lt`) 지어 `rules.py`의 `_LEASE_PARTS`·`_BORROW_*_PARTS`가 **수정 없이** 맞물리게 한다 |
| **B. 착수** | **지금 구현하지 않는다.** 미측정 항목을 먼저 실측한 뒤 착수 범위를 정한다 |
| **C. 잔여 4건** | 분기 저장 위치 / `applied_rules` / `value_lineage` / `rd_fallback`·`extended_financials` 는 **해당 Phase에 도달했을 때 각각 논의**. 지금 닫지 않는다 |

### 왜 조사가 먼저인가

`AccountMapper`는 3단계(exact → normalized → **fuzzy ≥0.88**)로 매핑한다. canonical을
쪼개면 **퍼지 이웃이 재배치**된다 — 지금 `비유동리스부채`가 0.977로 끌려오듯, 분해 후엔
**다른 라벨이 새 canonical로 잘못 끌려올 수 있다.** 이 파급을 먼저 측정하지 않으면 P1A는
"값이 늘었는지"만 보고 **"다른 값이 틀어졌는지"를 놓친다.**

---

## 2. ★선결 확인 — 대조군 오염 방지 (T1보다 먼저)

**`account_maps/*.py` 는 v3 전용이 아닐 수 있다.** 만약 v2 체인(Track B 폴백 등)도
`AccountMapper`를 쓴다면, 카탈로그를 고치는 순간 **v2 값도 같이 움직여 대조군이 오염된다**
(§2 대원칙 "v2는 대조군으로만"이 깨진다).

- [x] `get_mapper()` / `AccountMapper` 호출처 전수 grep → **v2 적재 경로에 걸리는지 판정**
  ```bash
  grep -rn "get_mapper\|AccountMapper(" --include='*.py' . | grep -v '/.venv/'
  ```
- [x] 걸린다면: 분해를 **v3 전용 오버레이**로 넣는 설계로 전환
      (`account_maps` 원본 불변 + `fin2/layer3` 쪽에서 덧씌우기) → 설계 변경이므로 사용자 보고
- [ ] 안 걸린다면: 카탈로그 직접 수정으로 진행(원안) — **해당 없음(걸림, 아래 참고)**

> 이 확인이 끝나기 전엔 T3(분해안 diff) 결과를 "안전하다"고 해석하지 말 것.

### ★ T0 판정 결과 (2026-08-22, 오염 확정 — v3 전용 오버레이로 설계 전환 필요)

**걸린다.** `account_maps`(`get_mapper`/`AccountMapper`)는 v3 전용이 아니라 **fact_v2 추출단(E-레이어)** 에서
쓰인다 — v2/v3 공통 소스 테이블이다:

- `fin2/extract/text.py:20` 주석: "`canonical_account` = account_mapper 결과(텍스트의 concept_map 역할)".
  즉 **텍스트/PDF 폴백 추출(P2, Track B — 주로 pre-2015)** 은 XBRL의 `concept_map.map_acode`가
  아니라 `AccountMapper`로 `canonical_account`를 정하고 그 값을 `fact_v2`에 그대로 저장한다
  (`fin2/extract/text.py:208`, `fin2/extract/pdf.py:253`).
- v2의 `fin2/standardize/build.py:502`는 `SELECT canonical_account, amount_won, mapping_stage, acode
  FROM fact_v2` 로 **그 canonical_account를 그대로 읽어** `std_financials_v2`를 조립한다
  (`rules.py`의 `_BS_MAP`/`_IS_MAP`/`_CF_MAP`은 canonical→std컬럼 매핑만 하고, canonical 자체 판정에는
  관여하지 않음).
- 대조: XBRL 경로(`fin2/extract/xbrl.py`, Track A)는 `concept_map.map_acode`를 쓰고 `AccountMapper`는
  안 쓴다 — 이 경로는 오염 없음.

**결론**: pre-2015·Track B(텍스트/PDF 폴백)로 적재된 `fact_v2` 행에 한해 v2·v3가 **같은
`AccountMapper` 판정을 공유**한다. `account_maps/*.py`(카탈로그)를 직접 고치면 그 행들의
`canonical_account`가 바뀌어 **v2의 `std_financials_v2`도 함께 움직인다** → 대조군 오염 확정.

→ **P1A는 카탈로그 직접 분해가 아니라 v3 전용 오버레이로 설계를 전환해야 한다**
(`account_maps` 원본은 무변경, 분해 로직은 `fin2/layer3/combine.py` 쪽 — 아마
`_apply_enrichment` 근처 — 에서 canonical을 얹는 방식). 오버레이 설계는 **아직 미착수**(사용자
보고·논의 필요 — T1 스캐너를 오버레이 기준으로 다시 설계해야 할 수도 있음).

### ★ T0 재검토 (2026-08-22, 사용자와 논의 후) — 결론 번복: 오버레이 불필요, 원안(직접분해) 진행

사용자 논의("v3에 필요한 수정이면 v2가 깨져도 되지만, 더 좋은 방법 있으면 그쪽으로") 중 두 가지
추가 사실이 드러나 위 결론을 뒤집었다:

1. **`canonical_account`는 추출 시점에 한 번 저장되고, `standardize_corp`(v2)는 그 저장값을
   그냥 읽기만 한다** — `get_mapper()`를 재호출하지 않는다. 카탈로그를 고쳐도 **이미 쌓인
   과거 `fact_v2` 행(118,640+491,527+577,598건)은 재추출 전까지 안 움직인다.** 재추출은
   `store_facts`의 `ON CONFLICT DO UPDATE`(`fin2/extract/xbrl.py:213`)를 통해서만 일어나고,
   이 프로젝트는 소급 재추출을 **수동 실행 원칙**으로 이미 못박아 뒀다(CLAUDE.md 런북) — v2
   쪽 과거분 재추출을 이 트랙에서 돌리지 않으면 대량 오염 자체가 발생하지 않는다.
2. **더 결정적으로 — v2는 지금 이 collapse된 canonical을 애초에 전혀 소비하지 않는다.**
   `fin2/standardize/rules.py`의 `CONSUMED_CANON`/`DIRECT_MAP`에 `bs.lease_liability`·
   `cf.borrowings_proceeds`·`cf.borrowings_repaid`(collapse된 이름)가 **아예 없다** — 오직
   분해된 이름(`_LEASE_PARTS`/`_BORROW_*_PARTS` = `bs.lease_current`/`_noncurrent`,
   `cf.borrow_proceeds_st`/`_lt`, `cf.borrow_repaid_st`/`_lt`)만 소비한다. 실측
   (`std_financials_v2` 505,047행): `lease_liability` 20,761 / `borrowings_proceeds` 17,104 /
   `borrowings_repaid` 17,137건만 채워져 있고, 전부 **XBRL(Track A)이 이미 분리 태깅한** 값이다.
   텍스트 추출(AccountMapper/Track B) 경로로 들어오는 행은 v2가 **지금 이미 통째로 버리고
   있다** — 카탈로그 분해는 v2의 기존 값을 바꾸는 게 아니라 **v2가 원래 못 쓰던 값을 향후
   신규분부터 새로 채워주는 것**(순수 이득, 손실 없음).

**결론(최종)**: 오버레이 설계는 **불필요**. 원안(카탈로그 직접 분해)으로 T1부터 진행한다.
가드레일 2가지만 유지: ① 이 트랙에서 `fact_v2` 과거분 소급 재추출/백필을 돌리지 않는다
(v3 쪽 백필만 실행), ② §6.0 "P0 기준선 스냅샷"은 카탈로그 변경 직전에 뜬다(향후 신규 filing
으로 인한 점진적 v2 개선을 "예상된 변화"로 문서화해두기 위함).

---

## 3. TODO — 실행 체크리스트

### T1. 진단 스크립트 신설 — `scripts/diag_canonical_collapse_scan.py`

**★스크래치에 두지 않는다.** 2026-08-20 세션에서 전사 스캔 스크립트를 세션 스크래치에
두었다가 소실해 재작성했던 전례가 있다(메모리 `p3-1-trackd-failb-rootcause-2026-08-20` 부록A).

- [ ] 파일 신설. CLI 구조:
  ```
  python scripts/diag_canonical_collapse_scan.py <subcommand> [options]

  subcommands:
    labels    ①④ 라벨 지도 (DB 필요)
    diff      ②  분해 전/후 매핑 diff (--offline 가능, DB 불필요)
    paren     ③  괄호 표기 정규화 결함 범위 (DB 필요)
    conflict  충돌 재측정(P0.5 재현·확대)

  options:
    --family {lease,borrow,debt,paren,all}   대상 계열
    --sample N        기본 400 (키 표본)
    --all             전수 스캔 (★장시간 — 사용자 실행)
    --statement {BS,CF,IS,NOTE}
    --csv PATH        결과 CSV 저장
  ```
- [ ] **재사용할 기존 자산**(새로 만들지 말 것):
  | 대상 | 경로 | 용도 |
  |---|---|---|
  | `get_mapper()` | `parser/common/account_mapper.py:303` | 3단계 매핑 그대로 |
  | `AccountMapper(fuzzy_threshold=...)` | 동 `:54` | 분해안 인스턴스 별도 생성 |
  | `normalize_account_name` | `parser/common/amount_normalizer.py` | ③ 괄호 처리 규칙 확인 |
  | `_LEASE_PARTS`·`_BORROW_*_PARTS`·`_ST_DEBT_PARTS`·`_LT_DEBT_PARTS` | `fin2/standardize/rules.py:76-82` | **분해안의 목표 이름**(하드코딩 금지, import) |
  | `get_session` | `collector/db.py` | DB 세션 |
- [ ] **읽기전용 보장**: `SELECT` 외 문장 금지. 세션은 `session.execute(text("SELECT ..."))`만
      사용하고 커밋하지 않는다. 코드 리뷰 시 `INSERT|UPDATE|DELETE|CREATE|ALTER|DROP` grep 0건 확인.
- [ ] **분해안은 스크립트 안 dict로만 표현** — 이 단계에서 `account_maps/*.py` 를 고치지 않는다:
  ```python
  # Proposed split (draft, to be refined by T2 results).
  SPLIT_DRAFT = {
      "bs.lease_current":    ["유동리스부채", "유동성리스부채", "유동 리스부채"],
      "bs.lease_noncurrent": ["비유동리스부채", "비유동 리스부채", "비유동성리스부채",
                              "비유동금융리스부채"],
      "bs.lease_liability":  ["리스부채", "금융리스부채"],          # total kept as-is
      "cf.borrow_proceeds_st": ["단기차입금의증가", "단기차입금의차입"],
      "cf.borrow_proceeds_lt": ["장기차입금의증가", "장기차입금의차입"],
      "cf.borrow_repaid_st":   ["단기차입금의상환", "단기차입금의감소"],
      "cf.borrow_repaid_lt":   ["장기차입금의상환"],
      "cf.borrowings_proceeds": ["차입금의증가", "차입금의차입", "차입금차입"],  # total
      "cf.borrowings_repaid":   ["차입금의상환", "차입금상환"],                 # total
  }
  ```

### ★ T2/T3/conflict 실행 결과 (2026-08-22, `scripts/diag_canonical_collapse_scan.py`)

**T3(diff, 가장 중요·완료)**: `diff --family all`(오프라인 alias 우주 780종 + DB 관측 acode 18종,
총 798라벨) — 예상 밖 매핑 변경 **2건**: 순수 BS 잔액 라벨 `단기차입금`/`장기차입금`(CF섹션 힌트로
호출 시)이 fuzzy-포함관계로 `cf.borrowings_proceeds`(총계) 대신 `cf.borrow_proceeds_st`/`_lt`로
착지 — 기존에도 이미 fuzzy로 총계 쪽에 붙던 라벨이 더 정밀한 부품 쪽으로 리다이렉트되는 것뿐이라
**개선이지 새 오염이 아니다**. 그 외 796개 라벨은 무변화. → **합격**(risk 0에 가까움).

**T2(labels, lease/borrow)**: 결정적 추가 사실 발견 — `fin2/extract/text.py::_canonical_of()`는
**fuzzy-stage 매치에 canonical을 아예 안 준다**(`None` 반환, 원문 주석 "퍼지 매치는 canonical을
주지 않는다 — 추측 금지"). 즉 `비유동리스부채`(fuzzy 0.977, 실측 69,712건+변형 다수)는 **지금
`fact_v2.canonical_account`가 NULL** — `bs.lease_liability`와 충돌조차 안 하고 그냥 버려진다.
반면 `fin2/layer3/combine.py:1249`는 `get_mapper().map()` 결과를 필터 없이 그대로 쓰고
`_STAGE_RANK`에 `"fuzzy": 1`로 후보 등재한다 — **v3만 이 fuzzy 매치를 후보로 받아 진짜 충돌을
겪는다**(P0.5의 97.4% 손실은 v3측 현상, v2/`fact_v2`는 애초에 이 라벨을 못 받아 별도 경로로
이미 잃고 있었다). 분해안이 `비유동리스부채`를 exact alias로 등재하면 confidence가 1.0으로
올라가 v2도 **처음으로 이 값을 받게 된다** — v2 관점에서도 순수 이득.

**conflict(재측정, P0.5 재현+확대)**:

| canonical | conflict_groups | total_groups | ratio |
|---|---:|---:|---:|
| `bs.lease_liability`(collapse) | 15,081 | 102,999 | **14.6%** |
| `bs.lease_current`(이미 분리, XBRL) | 16 | 50,592 | 0.0% |
| `bs.lease_noncurrent`(이미 분리, XBRL) | 14 | 50,590 | 0.0% |
| `cf.borrowings_proceeds`(collapse) | 142,826 | 339,129 | **42.1%** |
| `cf.borrowings_repaid`(collapse) | 171,092 | 347,060 | **49.3%** |

이미 분리된 이름(XBRL 태깅분)은 충돌률이 사실상 0%다 — **분리 자체가 충돌을 없앤다**는 걸
직접 증명. borrow는 collapse 상태에서 충돌률이 42~49%로 lease보다 훨씬 심각(P4 다음으로 큰
효과가 예상되는 항목).

**결론**: 분해안(SPLIT_DRAFT)은 안전하고(T3 합격) v2에도 순수 이득(T2)이며, 효과 크기도
크다(conflict 14.6~49.3% → 분리 후 ~0%). T4(paren)·T5(debt) 남았지만 착수 판단에 필요한
핵심 근거는 이미 충분.

### T2. 조사 ① — 분해 대상 라벨 전수 지도 (lease / borrow)

- [ ] `labels --family lease --statement BS`, `--family borrow --statement CF` 실행
- [ ] 산출: `label_raw | 건수 | 현재 canonical | stage | confidence | 분해안 귀속`
- [ ] **판정 기준**:
  - 표본 50개사에서 이미 관측된 12종 외에 **새 변형이 나오는지**
  - **총계 라벨과 분리 라벨의 공존 비율** — 이게 "총계를 어떻게 취급할지"를 결정한다
- [ ] ★**귀속 애매 케이스 목록화**(자동 판정 금지, 사용자 보고 대상):
  - `유동성장기차입금의상환`·`유동성장기부채상환` → `st`인가 `lt`인가
    (현재 v3 카탈로그는 `cf.borrowings_repaid`에 넣어둠, `cf_accounts.py:237-247`)
  - `단기차입금의감소` → 상환과 동일 취급 가능한가

### T3. 조사 ② — 퍼지 파급 diff (★가장 싸고 위험을 많이 걷어냄)

- [ ] `diff --offline` 실행 — **DB 불필요, 순수 코드**
- [ ] 구현:
  ```python
  # Build two mappers: current catalog vs catalog + SPLIT_DRAFT overlay,
  # then map every observed label through both and diff the results.
  before = AccountMapper()
  after  = _mapper_with_overlay(SPLIT_DRAFT)   # deep-copied dicts, no file edit
  ```
- [ ] 입력 라벨 = T2가 모은 전량 + **인접 계열**(오염 감시용):
      `유동성장기부채`·`유동성장기차입금`·`유동성사채`·`기타유동부채`·`기타금융부채`·
      `장기차입금및사채`·`사채`·`단기차입금`·`장기차입금`
- [ ] **합격 조건**: 분해 대상 라벨 외에 **매핑이 바뀌는 라벨 0건**.
      1건이라도 바뀌면 alias를 좁히거나 `_FUZZY_BLOCK`(`account_mapper.py:43`) 활용 검토

### ★ T4/T5 실행 결과 (2026-08-22)

**T4(paren)**: 스캐너에 버그 발견·수정 — `fact_v2.canonical_account`는 미매핑 시 문자열
`"unknown.*"`가 아니라 **NULL**이 저장되는데(`text.py::_canonical_of`), 스크립트가
`startswith("unknown.")`로 판정해 항상 0%로 잘못 나왔다. `canonical IS NULL`로 고쳐 재실행:
**전수(19,017종 라벨·6,214,296행) 기준 63.29% 미매핑.** 그런데 이 물량의 정체는 괄호 처리
결함이 아니다 — 상위권이 전부 **CF 간접법 운전자본 조정**(`재고자산의감소(증가)`
`매출채권의감소(증가)` `매입채무의증가(감소)` 등, 각 8~13만행)과 **EPS**(`기본주당이익(손실)`
`희석주당이익(손실)`, 각 6~9만행)다. `normalize_account_name` 코드를 직접 확인한 결과 —
**괄호를 `_`로 바꾸는 규칙은 존재하지 않는다**(체크리스트의 가설이 틀렸다). 이 함수는 접두
괄호(`(1)`·`(A)`)와 주석참조(`(주5,6)`)만 제거하고, `(손실)`·`(증가)`처럼 라벨 의미의 일부인
말미 괄호는 건드리지 않는다. **판정: 괄호발 결함 없음 — 관측된 미매핑은 CF조정/EPS라는
기존에 알려진 별개의 커버리지 공백(리스/차입과 무관)이다. P1A와 분리, 별도 트랙.**

**T5(labels --family debt)**: v2/v3 이름 불일치 실체 확인 — `additive_debt`(169,314행, P4
최대 항목)는 **lease/borrow와 반대 방향의 문제**다. 같은 개념이 추출경로(XBRL vs 텍스트)에
따라 **서로 다른 canonical 두 개로 이미 갈라져** 있다:

| 개념 | XBRL(Track A) canonical | 텍스트(Track B) canonical |
|---|---|---|
| 유동성장기차입금/부채/사채 | `bs.current_lt_debt`(30,316건) | `bs.current_portion_lt_debt`(186,003건) |
| 사채(비유동) | `bs.bonds`(14,051건) | `bs.bond`(49,228건) |
| 전환/일반사채(유동) | `bs.current_bonds_conv`/`_plain`(22,200건) | `bs.current_bond`(1,989건) |

즉 **분해가 아니라 통합(alias 정합)이 필요한 케이스** — 두 canonical을 하나로 합치거나
(v2식 `_ST_DEBT_PARTS`/`_LT_DEBT_PARTS`처럼) 합산 부품으로 명시 등록해야 양쪽 경로의 값이
전부 잡힌다. **판정: "이름 정합"만으로 풀린다(추가 분해 불필요) — P4 범위, 이번 P1A 착수와는
무관, 별도 작업.**

### T4. 조사 ③ — 괄호 표기 정규화 결함의 진짜 범위

- [ ] `paren --sample 400` → 필요 시 `--all`(사용자 실행)
- [ ] `label_raw`에 괄호가 있는 라벨을 계열별로 집계, `unknown.*` 비율 산출
- [ ] `normalize_account_name`의 괄호 처리 규칙을 코드로 확인(왜 `_`로 바뀌는지)
- [ ] **판정**: 리스 밖으로 번지는 **일반 결함이면 P1A와 섞지 말고 별도 트랙**으로 분리
      (원인이 다른 변경을 한 커밋에 넣지 않는다 — R3/R4 교훈)

### T5. 조사 ④ — `additive_debt` 계열 이름 불일치 (P4 최대 항목, 169,314행)

- [ ] `labels --family debt` 실행
- [ ] v2 이름 ↔ v3 이름 대조표 작성:
      `bs.current_lt_debt`↔`bs.current_portion_lt_debt` ·
      `bs.bonds`↔`bs.bond` · `bs.current_bonds_plain`/`_conv`↔`bs.current_bond`
- [ ] **판정**: P4가 "이름 정합"만으로 풀리는지, 여기도 분해가 필요한지

### ★ T6 실행 결과 (2026-08-22)

원 분류의 근거 쿼리를 `standard_financials` 뷰 정의(`pg_get_viewdef`)에서 정확히 역산했다 —
v2-fallback 브랜치의 WHERE절(`version=1 AND NOT is_stub AND NOT is_discrete AND gate_status
<> 'fail_a' AND NOT EXISTS(대응 v3 행)`)을 `comparative_fallback` 마커에 적용하니 **행 수
16,822가 정확히 일치**(재현 성공). 이걸로 재분류(파일 존재는 `download_tasks.file_type`로
판정 — 원문 재확인 불필요, 이미 DB에 기록돼 있었다):

| 구분 | 원판(과거) | 재실행(오늘) | 변화 |
|---|---:|---:|---|
| `report_lines` 이미 있음 | 92 | 88 | -4 |
| 자기 XML 원문 보유, `report_lines` 0행 | 3,986 | 3,986 | 0 |
| 자기 filing 자체가 없음 | 9,095 | 9,095 | 0 |
| PDF만 | ~73 | 73 | 0 |
| **합계(기간)** | 13,154 | 13,242(+88 순증분은 위 표 내 이동이 아니라 신규 유입) | +88 |

거의 완전히 안정적이다 — pre-2015 백필·R34~R42가 들어갔어도 이 특정 표본은 거의 안 움직였다.
**"v2 삭제 시 원리적으로 잃는 것"의 최종 기준선 = 위 표(2026-08-22 갱신판)로 확정.**
(참고: "자기 filing 자체가 없음" 9,095건은 정의상 v3도 원리적으로 만들 수 없다 — 구조적
한계이지 결함이 아니다.)

### T6. 조사 ⑤ — §3.6 v2-only 키 재분류 재확인 (SQL 단발, 스크립트 불필요)

- [ ] 초판 분류(`report_lines` 있음 92 / XML은 있는데 0행 3,986 / filing 자체 없음 9,095 /
      PDF만 73)를 재실행. 그 사이 pre-2015 백필·R34~R42가 들어갔으므로 수치가 움직였을 수 있다
- [ ] 산출 = **"v2 삭제 시 원리적으로 잃는 것"의 최종 기준선**(P6 산출물)

### ★ T7 — 근본원인 확정(코드 레벨, 2026-08-22), 효과크기 측정은 진행 중

**신규 발견(이번 세션): v3가 v2의 2026-07-17 버그수정을 이식받은 적이 없다.**

`fin2/standardize/rules.py`(v2 S-레이어)는 `_COL_PRIORITY = {"interest_expense":
("is.interest_expense", "is.finance_cost")}`로 **명시적 우선순위**를 둔다 — 이자비용이
있으면 그걸 쓰고, 없을 때만 금융원가(상위개념·항상 더 큼)를 대용치로 쓴다(`rule_map_direct`,
주석: "2026-07-17(C7) max-abs 폐지 — 구버전은 항상 금융원가를 골라 이자비용을 체계적으로
과대계상했다"). 이 마커가 `map_direct_proxy:interest_expense=is.finance_cost`(187,478행)다.

그런데 `fin2/layer3/combine.py:33-36`은 `rules.py`에서 `DIRECT_MAP`만 import하고
`_COL_PRIORITY`/`rule_map_direct`는 **import하지 않는다.** 대신 `combine.py:2296-2303`이
자체적으로:
```python
for canon, value in confirmed.items():
    std_col = DIRECT_MAP.get(canon)
    ...
    col[std_col] = value   # 그냥 마지막에 온 canon으로 덮어쓴다 — 우선순위 없음
```
`is.interest_expense`와 `is.finance_cost`가 둘 다 `confirmed`에 있으면 **dict 순회 순서상
나중에 처리되는 쪽이 그냥 이긴다** — v2가 고친 그 구버전 결함(우선순위 없이 아무거나 채택)이
**v3에는 애초에 이식된 적 없이 그대로 남아있다.** P1C는 "효과 크기를 재는" 문제가 아니라
**이식 누락 버그 확정** — 수정은 `combine.py`의 해당 루프에 `_COL_PRIORITY` 상당 로직을
추가하는 것(간단, 저위험 — 이미 v2에 검증된 패턴을 그대로 가져오면 됨).

**효과 크기 실측 완료** (`report_lines` 재현, `/private/tmp/.../t7_interest_expense_probe.py` —
`std_financials_v3.statement_type`이 BS/IS/CF가 아니라 consolidated/separate라는 조인
버그를 한 번 잡고 재실행):

| | 건수 |
|---|---:|
| `is.interest_expense`·`is.finance_cost` 둘 다 후보로 존재하는 키 | 2,894 |
| 그중 값이 서로 다른 키 | 2,198 |
| → v3.interest_expense == finance_cost(**오선택**) | **182 (8.3%)** |
| → v3.interest_expense == interest_expense(정선택) | 1,997 (90.9%) |
| → 둘 다 아님(다른 경로로 채워짐) | 17 |
| → v3 행 없음 | 2 |

**해석**: dict 순회 순서가 우연히 `is.interest_expense`를 나중에 처리하는 경우가 많아
"정선택"이 다수(90.9%)지만, 우선순위가 명시돼 있지 않아 **182건은 결정론적으로 이자비용이
과대계상**돼 있다(순서에 달린 문제라 매 백필/재실행마다 재현되는 진짜 버그, 요행이 아님).
절대 건수는 작지만 **수정이 간단하고 리스크가 없다**(`_COL_PRIORITY` 패턴을 `combine.py`로
그대로 포팅) — 착수 범위에 포함할 만한 항목.

### T7. 조사 ⑥ — P1C 효과 크기 (SQL 단발)

- [ ] 이자비용·금융원가가 둘 다 있는 키에서 v3 `interest_expense`가 **큰 쪽(금융원가)** 과
      일치하는 행 수 = 실제 오선택 건수
- [ ] v2의 `map_direct_proxy:interest_expense=is.finance_cost`(187,478행)와 교차 확인
- [ ] 산출 = **착수 범위 재결정의 입력**

### T8. 문서 반영

- [ ] `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` 에 **§3.12 "P0.6 조사 결과"** 추가
      — T2~T7 결과표 + **확정된 alias 목록**(P1A가 그대로 쓸 입력)
- [ ] §7 미결 결정 갱신: ⑤를 **"(b) 채택 — 사용자 확정 2026-08-22"** 로 닫고,
      잔여 4건은 **"해당 Phase에서 논의(사용자 확정)"** 로 명시
- [ ] 메모리 갱신(`std-v2-retirement-port-to-v3-plan-2026-08-22.md`)

### T9. 착수 범위 재결정 (사용자와)

- [ ] T4(괄호 결함 범위) + T7(P1C 효과) 결과를 놓고 **P1C / P1A 순서와 범위 확정**
- [ ] 이후 P1A 구현 계획은 **별도 문서**로 — 이 문서는 조사까지가 범위

---

## 4. 구현 시 주의 (P1A로 넘어갈 때 쓸 메모)

지금 구현하지는 않지만, 조사 중 확정된 사실이라 여기 남긴다.

1. **`rules.py`는 v2와 공유된다.** `rule_additive_lease` 등을 고치면 **v2 값도 변한다**
   (대조군 오염). ⟹ v3 전용 동작(예: "부품이 없으면 총계로 폴백")은 `rules.py`가 아니라
   **`fin2/layer3/combine.py::_apply_enrichment`** 쪽에 둔다.
2. **`_VALUE_COLS` 누락 함정** — `fin2/layer3/build.py:21-34`에 컬럼을 안 넣으면
   combine이 값을 내도 **테이블에 안 들어간다**(`:32`에 경고 주석 있음).
3. **`CONSUMED_CANON` 등재** — 분해한 새 canonical을 `rules.py`의 `CONSUMED_CANON`에 넣어야
   충돌이 `conflicts` 컬럼에 **기록**된다. 안 넣으면 지금과 똑같이 조용히 사라진다.
4. **`비유동리스부채` alias 명시 등재** — 현재 퍼지 0.977로 유동 쪽에 끌려오는 상태.
5. **총계-부품 이중계상 가드** — `리스부채`(총계)와 유동/비유동이 공존하는 보고서가 있다.
   v2 `rule_additive_debt`의 총부채 초과 가드(`rules.py:267-291`)와 같은 방식이 필요한지
   T2의 공존 비율을 보고 판단.

---

## 5. 검증

이 단계는 **읽기전용**이다. 완료 조건:

- [ ] 스크립트에 `SELECT` 외 문장 없음 (grep + 코드 리뷰)
- [ ] 실행 전후 `std_financials_v3` 행수(**303,859**)·`face_audit` 행수 **무변경** 확인
- [ ] `account_maps/*.py` 파일 **무변경**(`git status` clean) — 분해안은 메모리상 dict로만
- [ ] `pytest tests/ fin2/tests/` — 기존 실패 1건(`test_lxintl_facility_table_dropped`, 무관)
      외 신규 실패 0
      > ★범위 지정 필수. 루트 전체는 NAS 심링크에서 멈춘다(메모리 `feedback-pytest-scope-raw-report-symlink`)
- [ ] 장시간 스캔(`--all`)은 **사용자가 실행**. 요청 전 **이미 돌렸는지 먼저 확인**
      (메모리 `feedback-long-running-commands`)

## 6. 이 단계에서 하지 않는 것

- `account_maps/*.py` 실제 수정 (= P1A)
- `StdFinancialV3` 스키마·마이그레이션 (= P1A/P2)
- 규칙 이식·백필·Gate B 재감사 (= P1 이후)
- 잔여 4건 결정 (= 각 Phase에서 논의, 사용자 확정)
