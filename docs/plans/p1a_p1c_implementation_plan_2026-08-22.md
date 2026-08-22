# P1A/P1C 구현 계획서 (2026-08-22)

> **상위 문서**: [`std_v2_retirement_port_to_v3_2026-08-22.md`](std_v2_retirement_port_to_v3_2026-08-22.md) §3.12,
> [`std_v2_catalog_split_p0_6_todo_2026-08-22.md`](std_v2_catalog_split_p0_6_todo_2026-08-22.md)(T1~T7, 전부 완료).
>
> 상태 = **계획만, 구현 미착수.** 이 문서는 실행 순서·정확한 파일/라인·검증 기준을
> 못박기 위한 것이고, 승인 후 별도 요청으로 실행한다([[feedback-plan-then-wait]]).

---

## 1. 범위

| | 내용 | 근거 |
|---|---|---|
| **P1A** | lease/borrow canonical 분해 — `bs.lease_liability`→`bs.lease_current`/`_noncurrent`, `cf.borrowings_proceeds`/`_repaid`→`_st`/`_lt` | P0.6 T2/T3, 충돌률 14.6~49.3%→~0% 실증 |
| **P1C-1** | `combine.py`에 `_COL_PRIORITY`(interest_expense) 이식 | P0.6 T7, 오선택 182건 확정 |
| **P1C-2** | `combine.py`에 `rule_cash_with_deposits` 이식 | 마스터 계획 §3.11-(6)·§7-⑤ 인접 항목, P1C로 이미 분류돼 있음(카탈로그 무변경) |

**범위 밖**(별도 트랙, 이 문서 아님): T4(괄호 결함설 — 애초에 결함 없음, 조치 불필요) ·
T5(`additive_debt` 이름 통합, P4) · `extended_financials`(§3.9) · `fact_v2` 물리 삭제.

### 왜 P1A와 P1C를 묶는가

둘 다 §2 대원칙("v2 값을 복사하지 않는다")을 어기지 않고, **이미 v2에서 검증된 규칙을
`combine.py`로 포팅**하는 동일 패턴이다(capex/fcf/net_debt/D&A/EBITDA가 `_apply_enrichment`에
이미 이 패턴으로 들어가 있다 — `fin2/layer3/combine.py:2362-2397`). P1C는 카탈로그 변경이
전혀 없어 P1A보다 훨씬 저위험이라 **먼저 끝내고 검증까지 마친 뒤 P1A로** 넘어가는 순서를 권한다.

---

## 2. ★실행 전 필수 확인 — §6.0 스냅샷

마스터 계획 §6.0은 Phase 1 착수 전 필수로 못박아 뒀다. 이 문서의 실행도 예외 아님:

- [ ] `CREATE TABLE face_audit_snap_20260822 AS SELECT * FROM face_audit;`
- [ ] `std_financials_v3` 값 스냅샷 — 최소 `total_assets/revenue/net_income/short_term_debt/cash`
      + PK(corp_code, fiscal_year, fiscal_period, statement_type)
- [ ] 아래 §5 "기준선 수치"를 실행 직전에 다시 찍어 고정(이 문서의 수치는 2026-08-22 기준,
      며칠 지나면 데일리 적재로 자연히 움직인다)

---

## 3. 귀속 애매 라벨 4종 — ★사용자 결정 완료 (2026-08-22)

P0.6 T2가 자동 분류를 거부하고 사용자 보고로 남긴 것들. 전부 권고안대로 확정됐다:

| 라벨 | 실측 건수 | 결정 |
|---|---:|---|
| `유동성장기부채의상환`·`유동성장기부채상환` | ~93,194 | **`cf.borrow_repaid_lt`로 편입 — 확정** ("유동성"은 만기 분류일 뿐 원천은 장기) |
| `유동성장기차입금의상환`·`유동성장기차입금상환` | ~65,067 | **`cf.borrow_repaid_lt`로 편입 — 확정**(기존 v3 카탈로그 선례와 일관) |
| `단기차입금의감소` | 미실측 | **`cf.borrow_repaid_st`로 편입(상환과 동일 취급) — 확정** |
| `기타금융부채의증가`·`기타금융부채의감소` | ~17,460 | **현행 유지(총계 canonical에 그대로) — 확정**. "차입금"이 아니라 성격이 다른 금융부채라 st/lt 원천 구분 근거가 약함 |

아래 §4.1 `SPLIT_DRAFT`가 이 결정을 그대로 반영한 최종본이다.

---

## 4. P1A 구현 단계

### 4.1 카탈로그 분해 — `account_maps/bs_accounts.py`, `account_maps/cf_accounts.py`

`SPLIT_DRAFT`(§3.12, `std_v2_retirement_port_to_v3_2026-08-22.md`) 그대로 + 위 §3 결정 반영.

```python
# account_maps/bs_accounts.py — "bs.lease_liability" 항목을 아래로 교체
"bs.lease_current": [
    "유동리스부채", "유동성리스부채", "유동 리스부채",
],
"bs.lease_noncurrent": [
    "비유동리스부채", "비유동 리스부채", "비유동성리스부채", "비유동금융리스부채",
],
"bs.lease_liability": [          # 총계는 그대로 남긴다 — DIRECT_MAP/CONSUMED_CANON
    "리스부채", "금융리스부채",    # 어디에도 없어 이미 미소비 상태(§3.12 T0), 무해
],
```

```python
# account_maps/cf_accounts.py — "cf.borrowings_proceeds"/"cf.borrowings_repaid" 항목 조정
# (§3 결정 2026-08-22 확정 반영 — 최종본)
"cf.borrow_proceeds_st": ["단기차입금의증가", "단기차입금의차입"],
"cf.borrow_proceeds_lt": ["장기차입금의증가", "장기차입금의차입"],
"cf.borrowings_proceeds": ["차입금의증가", "차입금의차입", "차입금차입",
                            "기타금융부채의증가"],   # 총계 + 미분류 확정분(§3)

"cf.borrow_repaid_st": ["단기차입금의상환", "단기차입금의감소"],   # §3: 상환과 동일 취급 확정
"cf.borrow_repaid_lt": ["장기차입금의상환",
                         "유동성장기부채의상환", "유동성장기부채상환",
                         "유동성장기차입금의상환", "유동성장기차입금상환"],  # §3: lt 편입 확정
"cf.borrowings_repaid": ["차입금의상환", "차입금상환",
                          "기타금융부채의감소", "기타금융부채의상환"],  # 총계 + 미분류 확정분
```

**주의**: alias는 각 canonical에서 **한 번만** 등장해야 한다(`AccountMapper._build_index`가
섹션별 dict에 그대로 넣으므로 중복 등록 시 나중 것이 이긴다 — 조용한 실수). 편집 후
`scripts/diag_canonical_collapse_scan.py diff --offline --family all`을 **다시 돌려서**
"예상 밖 변경 0건"을 재확인할 것(SPLIT_DRAFT가 위 §3 결정으로 바뀌었으니 T3 재현 필수).

### 4.2 스키마 마이그레이션 — `std_financials_v3`에 컬럼 3개 추가

`std_financials_v3`는 이미 존재하는 테이블(데이터 있음)이라 `create_all()`로는 컬럼이 안
생긴다 — `biz_metrics channel` 선례(`collector/db.py` 마이그레이션
`"2026_07_biz_metrics_channel"`)와 동일하게 **ALTER 마이그레이션 신설**:

```python
# collector/db.py, MIGRATIONS 리스트 끝에 추가(기존 마이그레이션 수정 금지 — §9 롤백 원칙)
("2026_08_std_v3_lease_borrow_cols",
 # P1A — lease/borrow canonical 분해로 rule_additive_lease/_borrowings가 값을 내게 되는데
 # std_financials_v3에 이 컬럼이 없으면 combine이 값을 내도 테이블에 안 들어간다
 # (fin2/layer3/build.py:32 경고 참고).
 "ALTER TABLE std_financials_v3 ADD COLUMN IF NOT EXISTS lease_liability BIGINT, "
 "ADD COLUMN IF NOT EXISTS borrowings_proceeds BIGINT, "
 "ADD COLUMN IF NOT EXISTS borrowings_repaid BIGINT"),
```

`collector/models.py::StdFinancialV3`에도 동일 3개 `Column(BigInteger, nullable=True)` 추가
(cff/dividends_paid 근처, `:57-58` 뒤).

### 4.3 `fin2/layer3/combine.py` — additive 규칙 이식

`_apply_enrichment`(`:2362-2397`)에 capex/fcf/net_debt/da/ebitda와 **같은 자리**에 추가:

```python
from fin2.standardize.rules import (DIRECT_MAP, CONSUMED_CANON, StdContext,
                                    rule_additive_capex, rule_derive_fcf,
                                    rule_derive_net_debt, rule_additive_da,
                                    rule_derive_ebitda, ADDITIVE_CANON,
                                    rule_additive_lease, rule_additive_borrowings)  # ← 추가
...
    rule_additive_capex(ctx)
    rule_derive_fcf(ctx)
    rule_derive_net_debt(ctx)
    rule_additive_da(ctx)
    rule_derive_ebitda(ctx)
    rule_additive_lease(ctx)         # ← 추가 — lease_liability = |유동| + |비유동|
    rule_additive_borrowings(ctx)    # ← 추가 — borrowings_proceeds/_repaid 각각 합산
    for k in ("capex", "fcf", "net_debt",
              "depreciation", "amortization", "da_total", "ebitda",
              "lease_liability", "borrowings_proceeds", "borrowings_repaid"):  # ← 3개 추가
        v = ctx.col.get(k)
        if v is not None:
            col[k] = v
```

`rule_additive_lease`/`rule_additive_borrowings`는 **수정 없이 그대로** 재사용(둘 다
`fin2/standardize/rules.py`에 이미 존재·검증됨, `_LEASE_PARTS`/`_BORROW_*_PARTS`도 이미
목표 이름으로 정의돼 있어 카탈로그 이름을 v2와 맞춘 §4.1 덕에 **rules.py는 한 글자도 안
바뀐다** — v2 대조군 오염 걱정 없음, P0.6 T0 결론 그대로).

### 4.4 `fin2/layer3/build.py` — `_VALUE_COLS`에 컬럼 3개 추가

```python
_VALUE_COLS = (
    "... (기존 그대로) ..."
    "capex fcf net_debt depreciation amortization da_total ebitda "
    "lease_liability borrowings_proceeds borrowings_repaid"   # ← 추가
).split()
```

이거 빠뜨리면 `combine`이 값을 내도 **테이블에 안 들어간다**(`build.py:32` 경고 그대로 재현).

### 4.5 확인만 하면 되는 것(코드 변경 불필요)

- `rules.py`의 `CONSUMED_CANON`은 `_LEASE_PARTS`/`_BORROW_PROCEEDS_PARTS`/
  `_BORROW_REPAID_PARTS`를 **이미** 포함(P0.6 조사 중 확인) — 그대로 두면 새 canonical의
  충돌이 `conflicts`에 정상 기록된다.
- `rules.py`의 `RULES` 리스트(v2용, `:376-377`)도 `additive_lease`/`additive_borrowings`를
  이미 포함 — v2쪽은 **아무것도 안 건드려도** 분해 즉시 (지금 못 받던 값을) 받기 시작한다.

---

## 5. P1C 구현 단계

### 5.1 P1C-1 — `interest_expense` 우선순위

`combine.py`의 기존 직접-매핑 루프(`:2296-2303`, 현재 순회 순서로 그냥 덮어씀)는 **그대로
두고**, 그 루프 직후에 명시적 우선순위 패스를 추가한다(v2 `rule_map_direct`와 동일 결과,
루프 재작성보다 안전):

```python
from fin2.standardize.rules import _COL_PRIORITY   # 추가 import

# ... 기존 for canon, value in confirmed.items(): ... col[std_col] = value 루프 뒤에:

for std_col, priority in _COL_PRIORITY.items():
    for canon in priority:
        if canon in confirmed:
            col[std_col] = confirmed[canon]
            break
```

`_COL_PRIORITY = {"interest_expense": ("is.interest_expense", "is.finance_cost")}` —
`is.interest_expense`가 있으면 그걸, 없으면 `is.finance_cost`를 쓴다. 기존 루프가 이미
`col["interest_expense"]`를 (순서 무관하게) 채워놨어도 이 패스가 **마지막에 덮어써서** 항상
올바른 우선순위로 확정된다.

### 5.2 P1C-2 — `cash_with_deposits`

`_apply_enrichment`에 한 줄 추가(순서 무관 — `rule_cash_with_deposits`는 `ctx.col["cash"]`가
이미 채워진 뒤 실행되면 됨, `_apply_enrichment` 진입 시점엔 이미 그렇다):

```python
from fin2.standardize.rules import rule_cash_with_deposits   # 추가 import
...
    rule_cash_with_deposits(ctx)   # 금융사 현금+예치금 합산 (2026-07-18 규칙, v2 이미 검증)
```

`cash`는 이미 `_VALUE_COLS`에 있으므로 §4.4 같은 컬럼 추가는 불필요.

---

## 6. 실행 순서 (권장)

```
①§2 스냅샷 → ②P1C-1 → ③P1C-2 → ④(P1C 검증 통과 확인) → ⑤P1A §4.1 카탈로그(§3 결정 반영판) →
⑥diag_canonical_collapse_scan.py diff 재실행 → ⑦§4.2 스키마 마이그레이션 →
⑧§4.3+4.4 combine.py/build.py → ⑨P1A 재빌드+검증
```
(§3 애매 라벨 4종은 2026-08-22 확정 완료 — 더 이상 별도 단계 아님, §4.1에 반영됨)

P1C를 P1A보다 먼저 끝내는 이유: **카탈로그 변경이 전혀 없어** 실패해도 롤백이 `git
checkout`뿐이고, v2/대조군에 영향 없음이 자명하다(코드만 도는 v3 전용 계산). P1A로 넘어가기
전에 이 패턴(rules.py 함수를 `_apply_enrichment`로 포팅)이 실제로 잘 도는지 검증 삼아
먼저 확인하는 효과도 있다.

---

## 7. 검증 (마스터 계획 §6.2 재사용 + 구체 수치)

### P1C

| 항목 | 확인 |
|---|---|
| interest_expense | 재빌드 후 §3.12/T7에서 잡은 **182개 (corp,fy,period,basis)** 키를 다시 조회 — 전부 `is.interest_expense` 값으로 바뀌었는지(원문표본 5건 대조) |
| cash | `cash_from_combined`/`cash_plus_deposits` 해당 기업만 변화, 그 외 전 기업 **불변**(diff 0) — 일반기업 cash가 흔들리면 즉시 중단 |
| 불변식 | §6.1 I1~I6 재확인 |

### P1A

| 항목 | 확인 |
|---|---|
| 신규 3컬럼 채움 | `lease_liability`/`borrowings_proceeds`/`borrowings_repaid` NULL이 아닌 행 수 — 지금 0에서 최소 XBRL 분(70,377+70,257쌍/49만+57만 xml_text 분 상당수)만큼 증가해야 함 |
| v2 대비 일치율 | 공통키 기준 측정 — **일치율 낮음 = 실패 아님**(§2 대원칙), 불일치는 원문대조로 판정 |
| 기존 컬럼 무변경 | `short_term_debt`/`long_term_debt` 등 다른 컬럼 전이 **0건** 확인(이 분해가 다른 컬럼을 안 건드림을 실증) |
| diff 재현 | `diag_canonical_collapse_scan.py diff --offline --family all` 예상 밖 변경 0건(§4.1 편집 후 최종본 기준 재확인) |
| 전수 재감사 | §6.3 규약대로 pass→fail 전이 0건 (5-shard `scripts/run_gateb_audit_parallel.sh`) |

---

## 8. 롤백

- P1C-1/P1C-2/P1A 각각 **독립 커밋**(§9 원칙)
- P1A는 값변경 Phase — 백필(재빌드) 전 §2 스냅샷 필수, 문제 시 `git checkout <이전커밋> --
  fin2/layer3/combine.py fin2/layer3/build.py account_maps/bs_accounts.py
  account_maps/cf_accounts.py` (★`git stash` 금지 — [[feedback-git-stash-pop-hazard]])
- 스키마 마이그레이션은 컬럼 **추가만**(DROP 없음) — 롤백해도 데이터 유실 없음, 그냥 다시
  NULL로 둔 채 방치 가능

---

## 9. 이 문서에서 하지 않는 것

- 실제 파일 수정 — **승인 후 별도 요청**으로 실행
- T4(괄호 결함) — P0.6에서 이미 "결함 없음"으로 결론, 조치 자체가 없음
- T5(`additive_debt` 이름 통합) — P4 범위, 별도 계획 필요

---

## 10. 실행 결과 (2026-08-22) — ★P1C 완료, P1A는 미착수

**완료**: P1C-1(`interest_expense` 우선순위)·P1C-2(`cash_with_deposits`) 코드 반영 +
전체 연도(1999+) 재빌드 + Gate B 전수 재감사. P1A(§4, lease/borrow 분해)는 **이 세션에서
착수 안 함** — §6 순서상 P1C 검증까지만 진행하고 여기서 멈추기로 결정.

**계획서 대비 실장 시 보강한 것 2건** (§4.3/§5.1/§5.2 스니펫엔 없던 것, 구현 중 발견):
1. §5.1 우선순위 패스가 `col[std_col]` 값만 덮어쓰고 `amend_chain`/`amended_cols`(기재정정
   감사추적)는 갱신 안 하면 두 후보가 각각 다른 정정이력을 가질 때 값과 출처가 어긋남 →
   우선순위 패스 안에서 감사추적도 함께 재계산하도록 보강.
2. §5.2 "순서 무관"은 틀림 — `_apply_enrichment` 안의 기존 `rule_derive_net_debt`가
   `ctx.col["cash"]`를 읽으므로 `rule_cash_with_deposits`는 그보다 **먼저** 실행해야 함
   (v2 `RULES` 순서와 동일하게 배치). 또한 `_apply_enrichment` 끝의 결과회수 루프가
   `"cash"`를 안 챙겨서 계산해도 버려지는 문제도 같이 수정.

**검증 중 발견한 것(★중요, 다음 세션 인계)**:
- **전수 재빌드(`--all --year-min 1999`)를 한 번에 돌리면 안 된다는 R4 교훈이 재현됨**
  (`std_v2_retirement_port_to_v3_2026-08-22.md:751`). P1C만 검증하려 했는데 최근 커밋된
  R29/R34/R39/R41/R42 등 다른 Gate B 수정이 아직 표적백필 안 된 기업들에 한꺼번에 적용돼
  버림 — `total_assets`/`revenue`/`net_income`/`short_term_debt` 등 P1C가 안 건드리는
  컬럼까지 값이 바뀜.
- Gate B 전수 재감사 결과 pass→fail 전이 **999건** 확인, 3차례 독립 재실행(단독 1개사,
  49개사, 5-shard 병렬 재실행)으로 **131건에 수렴·재현 확인**(999는 최초 1회차만의 예외치 —
  원인 미상, 그 실행의 상세 로그를 재검사로 덮어써서 재조사 불가. 재발 시 **재검사 전에
  face_audit 스냅샷부터 뜰 것**).
- 131건 중 **69건(cash)**: P1C-2 버그 아님. `fin2/audit/face_audit.py`의 `"cash":"bs.cash"`
  체커가 `rule_cash_with_deposits`(2026-07-18 확정, 금융사 현금+예치금 합산)를 몰라서
  enrichment된 정답을 오탐 — v2도 같은 이유로 이미 다수 fail_b였음(715/992). 항등식 재구성
  체크(`bs.cash == bs.cash 후보 + bs.deposits 후보`)를 `audit_fields()`에 추가해 972→69로
  해소(같은 파일의 `is.revenue`/`is.net_income` 파생검증 패턴과 동일 구조).
- **남은 62건(controlling_ni 46·cogs 14·net_income 3·기타 7)은 P1C 무관 — 미해결, 다음
  세션 과제.** P1C 코드는 이 컬럼들을 전혀 안 건드리므로 위 "전수 재빌드 한꺼번에" 부작용으로
  추정되나 원인 미규명. 특히 `00580667`(2025 FY 연결)은 `total_assets/current_assets/
  total_liabilities/current_liabilities/total_equity/retained_earnings/tax_expense/
  net_income/controlling_ni` **9개 필드가 동시에** fail — 개별적으로 더 심각해 보여 우선
  조사 권장. 대상 corp 목록은 세션 스크래치(`regressed_corps.txt`, 49개사)에 있었으나 세션
  종료 시 소실 — 재조사 시 `face_audit_snap_20260822` vs 현재 `face_audit` diff로 다시 뽑을 것.
- DB에 남겨둔 진단용 스냅샷 테이블(정리 안 함): `face_audit_snap_20260822`(P1C 착수 전
  기준선, 재조사 시 diff 기준으로 재사용 가능), `std_financials_v3_snap_20260822`,
  `face_audit_recheck1_20260822`(중간 디버그용, 삭제해도 무방).
