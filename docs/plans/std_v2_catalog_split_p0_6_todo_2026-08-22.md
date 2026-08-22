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

- [ ] `get_mapper()` / `AccountMapper` 호출처 전수 grep → **v2 적재 경로에 걸리는지 판정**
  ```bash
  grep -rn "get_mapper\|AccountMapper(" --include='*.py' . | grep -v '/.venv/'
  ```
- [ ] 걸린다면: 분해를 **v3 전용 오버레이**로 넣는 설계로 전환
      (`account_maps` 원본 불변 + `fin2/layer3` 쪽에서 덧씌우기) → 설계 변경이므로 사용자 보고
- [ ] 안 걸린다면: 카탈로그 직접 수정으로 진행(원안)

> 이 확인이 끝나기 전엔 T3(분해안 diff) 결과를 "안전하다"고 해석하지 말 것.

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

### T6. 조사 ⑤ — §3.6 v2-only 키 재분류 재확인 (SQL 단발, 스크립트 불필요)

- [ ] 초판 분류(`report_lines` 있음 92 / XML은 있는데 0행 3,986 / filing 자체 없음 9,095 /
      PDF만 73)를 재실행. 그 사이 pre-2015 백필·R34~R42가 들어갔으므로 수치가 움직였을 수 있다
- [ ] 산출 = **"v2 삭제 시 원리적으로 잃는 것"의 최종 기준선**(P6 산출물)

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
