# ① Gate B — 업종 프로파일 파생 `revenue` 검증 설계 (2026-08-17)

> **착수 순위 1** (`gateb_view_source_version_join_fix_design_2026-08-17.md` §9).
> **선행 문서**: `financial_sector_revenue_standards.md`(2026-07-24 사용자 결정, 살아있는 문서).
> **후속**: ③(감사 성능) → ②(증거강도 재정의). 본 문서는 ②의 등급 체계를 **바꾸지 않고**
> 기존 확장점만 쓴다(§3-E).
> **신설 예정 규칙**: `docs/PARSING_RULES.md` **R32**.

---

## 0. 이 문서가 하는 일 (3줄 요약)

1. Gate B 실패 3,348건 중 **2,721건(81.3%)이 금융섹터**이고, 그 실체는 데이터 오류가 아니라
   2026-07-24 확정된 **업종 revenue 표준**(증권 순영업수익 등)을 계층3이 정확히 적용한
   결과다. 감사기에 "파생값" 개념이 없어 구조적으로 통과할 수 없다.
2. 이를 **면제(pending)로 덮지 않는다.** `std_financials_v3.industry_lines` 에 이미 기록된
   파생 근거(profile + 구성성분)를 읽어, **그 성분들을 원문 face 에서 찾아 재계산**해
   일치하면 PASS 를 준다 — 진짜 원문대조다(R0·R9 준수).
3. 트리거는 **curated 기업 목록이 아니라 행에 이미 있는 데이터**(`industry_lines->>'profile'`)다.
   신규 상장 증권사도 자동 커버된다 — R16~R21 식 키 열거를 반복하지 않는다.

---

## 1. 문제

### 1-A. 규모 (2026-08-17 실측, `face_audit` source_version='v3')

```
전체 fail            3,348   (fail_a 394 / fail_b 2,954)
  └ 금융섹터(KSIC 64/65/66)  2,721  = 81.3%
        fail_b 2,543 / fail_a 178

revenue 실패          2,702
  └ industry_lines.profile 보유   2,666 = 98.7%
        (profile 미보유 36건은 본 문서 범위 밖 — 일반 매핑 결함)

profile 보유 행의 실패 구성:
   revenue 단독 실패   2,651  (99.2%)
   revenue + 기타         15
   revenue 무관            5
```

프로파일 적용 모집단 = **4,539행 / 46개사**:

| profile | 행 | 기업 |
|---|---|---|
| securities | 3,230 | 20 |
| bank | 801 | 10 |
| insurance | 278 | 12 |
| credit_finance | 230 | 4 |

### 1-B. 원인 — 감사 판정식에 파생 개념이 없다

`fin2/audit/face_audit.py:1014-1015`:

```python
won_vals = {ln.amount_won for ln in cands}
if val in won_vals:      # ← 판정 전부. "원문 라인 집합에 그 값이 있는가"
```

계층3은 `fin2/layer3/industry_profiles.py::compose()` 로 revenue 를 **합성**한다. 증권의 경우
`net_op_formula` = **영업이익 + 판매관리비**(`industry_profiles.py:100-112`)이며, 이 값은
정의상 원문에 단일 라인으로 존재하지 않는다.

실측 — 미래에셋증권(00111722) 2026Q1 연결:

```
std_v3 revenue          1,624,073백만원   ← 순영업수익(파생)
원문 '영업수익' 라인    14,428,703백만원   ← 트레이딩 총액 포함 gross
판정                    fail_a  (= 확정버그, 메인뷰 차단)
```

### 1-C. 왜 지금 시급한가

- 감사 신호의 **81%가 노이즈**라 나머지 627건(비금융 fail)이 묻힌다. 지난 2주(R15~R31)가
  전체의 6%짜리 표면을 정밀하게 판 직접적 원인이다.
- ③(전수 재감사 성능)을 먼저 해도, 노이즈 비율이 그대로면 **잡음만 빨리 쌓인다**.

---

## 2. 핵심 발견 — 파생을 "면제"가 아니라 "검증"할 수 있다

### 2-A. 파생 근거가 이미 DB 에 있다

`std_financials_v3.industry_lines`(JSONB)는 **299,651행 전부** 채워져 있고, 프로파일이
적용된 행에는 `profile` 과 **구성성분**이 그대로 남아 있다.

```json
// 미래에셋증권 2026Q1 consolidated
{"profile": "securities", "operating_income": 1375040000000, "sga": 249033000000}
```

securities 3,230행 중 `sga` 를 가진 2,731행 **전부**에서 다음 항등식이 성립한다(불일치 0):

```
revenue == operating_income + |sga|
```

### 2-B. 성분은 원문 face 에 실재한다 (실측)

미래에셋증권 2026Q1 원문(`20260515003041.xml`, Track A) 직접 재추출:

| 성분 | 원문 존재 | 비고 |
|---|---|---|
| `operating_income` 1,375,040백만 | ✅ 정확히 일치 | `is.operating_income` + `is.operating_income_ifrs` 양쪽 |
| `sga` 249,033백만 | ⚠ 값은 있으나 **canonical=None** | acode `ifrs-full_SellingGeneralAndAdministrativeExpense` 가 **concept_map 미등재** |

→ 즉 **성분 재계산 검증이 가능**하고, 막고 있는 것은 concept_map 갭 1건뿐이다.

### 2-C. concept_map 갭 (§3-A 에서 수정)

`fin2/taxonomy/concept_map.py:104` 에 SGA 매핑이 **1개뿐**이다:

```python
"dart_TotalSellingGeneralAdministrativeExpenses": "is.sga",
#  ifrs-full_SellingGeneralAndAdministrativeExpense ← 없음
```

`fact_v2` 사용 빈도: `dart_...` 2,771 fact / 386 rcept vs **`ifrs-full_...` 190 fact / 22 rcept**.
Track B(텍스트) 리더는 같은 파일에서 `판매관리비 (주35,44)` → `is.sga` 로 이미 잡는다 —
Track A 만 못 잡는 순수 매핑 누락이다.

**파급 범위**: `map_acode()` 소비자는 `fin2/audit/face_audit.py` 와 `fin2/audit/line_audit.py`
**둘뿐**이다(전수 grep). 계층3(`combine.py`)은 이 표를 참조하지 않는다 — R23 주석
(`concept_map.py:66-71`)이 같은 사실을 이미 기록. 즉 **표준화 값에 영향 없음, Gate B 전용**.

---

## 3. 설계

### 3-A. Phase 1 — concept_map 갭 해소 (선행)

```python
"ifrs-full_SellingGeneralAndAdministrativeExpense": "is.sga",
```

R23 과 동일한 부류(원문대조로 확정된 갭)이고, 후보 추가는 집합 멤버십 판정에서 단조
개선이다. **단 R23 의 교훈(우연일치로 진짜 버그가 가려짐)** 을 §6-C 에서 명시 검사한다.

### 3-B. Phase 2 — 파생 검증 경로

`audit_fields()` 의 `is.revenue` 분기에 **파생 재계산**을 추가한다. 위치는 기존
`if not cands and canon == "is.revenue"`(revenue = cogs+gp 폴백, `face_audit.py:984-992`)
**바로 옆** — 같은 성격의 기존 확장점이다.

의사코드:

```python
# ★R32 — industry-profile derived revenue.
# The value is composed by fin2/layer3/industry_profiles.py::compose(), so it is NOT a
# single face line by construction. Verify the DERIVATION instead: locate each recorded
# component in the face and re-add them. This is a real source reconciliation (R0/R9),
# not an exemption -- a wrong std value still fails.
il = db_row.get("industry_lines") or {}
if canon == "is.revenue" and il.get("profile") and not _matched_normally:
    recomputed = _recompute_profile_revenue(il, by_canon)   # None if any component missing
    if recomputed is None:
        reason = "DERIVED_COMPONENTS_UNVERIFIED"   # pending — 감사 불가(차단 아님)
    elif abs(recomputed - val) <= tol:
        PASS                                       # 원문 성분으로 재계산 일치
    else:
        reason = "VALUE_DIFF"                      # ★진짜 버그 — 계속 fail
```

**profile 별 재계산 규칙** (`industry_profiles.py` 의 `compose()` 와 1:1 대응):

| profile | 재계산식 | 필요한 face canonical |
|---|---|---|
| securities (`net_op_formula`) | `operating_income + \|sga\|` | `is.operating_income`(또는 `_ifrs`), `is.sga` |
| bank / credit_finance | Σ 기록된 성분 | `is.interest_revenue`·`is.fee_revenue`·`is.other_op_revenue` 등 — **Phase 0 에서 매핑 존재 실측** |
| insurance | Σ 기록된 성분 | `is.insurance_revenue`·`is.investment_revenue` — 동상 |
| 모든 profile 의 `revenue_basis="gross_fallback"` | **적용 안 함** | 공시 총계를 그대로 쓴 행이라 기존 경로로 이미 통과(§3-D) |

> 재계산은 `industry_lines` 에 **기록된 성분 키만** 쓴다. 감사기가 프로파일 로직을
> 재구현하지 않는다(그러면 §줄기⑤ '독립성 침식'을 되풀이한다) — 계층3이 **무엇을 썼다고
> 주장하는지**를 읽고, 그 주장을 **원문에서 확인**하는 구조다.

### 3-C. 왜 curated 키가 아닌가 (★ 설계 의도)

R16~R21 은 (corp, fy, period) 키 **5,090개**를 코드에 열거했고, 그 키들은 신규 필링을
커버하지 못한다(반복 재발의 직접 원인). 본 설계의 트리거는 **감사 대상 행 자신이 들고
있는 `industry_lines`** 이므로:

- 신규 상장 증권사 → 프로파일이 적용되는 순간 감사도 자동으로 따라온다
- 프로파일 표준이 바뀌면(예: 증권 공식 변경) `industry_lines` 가 바뀌고 감사도 자동 추종
- **추가할 키 0개**

### 3-D. 단조성 보장

파생 검증은 **일반 경로가 실패한 뒤에만** 실행한다. 따라서:

- securities 기존 `pass` **217행** 무영향
- `gross_fallback` **499행**(pass 217 / pending 280 / fail_b 2) 무영향 — 실제 공시 총계를
  쓴 행이라 일반 경로로 이미 맞는다
- 기존 PASS 가 FAIL/PENDING 으로 뒤집히는 경로 **없음**

### 3-E. ②(등급 재정의)와의 관계

새 reason `DERIVED_COMPONENTS_UNVERIFIED` 는 기존 `_PENDING_REASONS`
(`face_audit.py:724-726`)에 **문자열 하나를 추가**할 뿐이다 — `FX_PRESENTATION_CURRENCY`·
`COGS_SGA_CONCEPT_MISMATCH` 와 같은 확장점. **등급 체계(pass/fail_a/fail_b/pending)는
건드리지 않는다.** ② 가 나중에 taxonomy 를 바꿔도 충돌하지 않는다.

---

## 4. Phase

| Phase | 내용 | 산출물 | 비고 |
|---|---|---|---|
| **0** | 성분 face 존재율 census — 46개사 전수. profile 별로 `industry_lines` 성분이 face canonical 로 잡히는 비율 측정 | `docs/qa/industry_profile_component_census_2026-08-17.md` | **읽기 전용.** bank/insurance/credit_finance 의 매핑 갭을 여기서 확정 |
| **1** | concept_map 갭 해소(§3-A) + Phase 0 이 찾은 추가 갭 | `fin2/taxonomy/concept_map.py` | 소규모 |
| **2** | `_recompute_profile_revenue()` 구현 + `audit_fields()` 배선 + 단위 테스트 | `fin2/audit/face_audit.py`, `fin2/tests/test_gateb_derived_revenue.py` | 본체 |
| **3** | 46개사 표적 재감사(`gateb_audit.py --source v3 --corp-file`) + §6 검증 | 재감사 로그 | ③ 없이 수 시간 |
| **4** | `docs/PARSING_RULES.md` **R32** 등재 + `financial_sector_revenue_standards.md` §5 에 감사 연동 기록 | 문서 | — |

> Phase 0 을 먼저 두는 이유: securities(3,230행)는 성분 검증 가능이 **실측 확인**됐지만,
> bank·insurance·credit_finance(1,309행)는 **아직 미확인**이다. 짐작으로 설계하지 않는다
> ([[feedback-verify-against-source]]).

---

## 5. 예상 효과

```
현재    fail 3,348  (fail_a 394 / fail_b 2,954)
        pass 197,097 / pending 99,206

목표    fail   ~660  (profile revenue 2,666 중 성분검증 성공분 제거)
        그중 fail_a ≈ 216  ← 비금융, 실제 조사 가치가 있는 모집단
```

**성분 재계산이 불일치하는 행은 계속 fail 로 남는다** — 그건 진짜 계층3 버그이고, 지금은
노이즈에 묻혀 보이지 않던 것이다. 이 설계의 부수 효과로 **새 진짜 결함이 드러날 수 있다**
(그것이 목적이다).

---

## 6. 검증 규약

**A. 단조성 (기계적)** — 재감사 전후 `face_audit` 스냅샷 비교

```
통과선: pass → (fail_a|fail_b|pending) 로 전이한 행 = 0
```

**B. 원문 대조 (수동, 집계 금지 — R9)** — profile 4종 × 각 2개사 = **8개사**를 원문에서
손으로 확인한다. 특히 `PASS` 로 바뀐 행이 **정말 그 성분값을 원문에 갖고 있는지**.

**C. ★R23 교훈 검사 — 우연일치로 진짜 버그가 가려지지 않는가**

`is.sga` 매핑 추가로 새 후보가 생긴다. R23 에서는 새 후보값이 우연히 `0` 이라 진짜 버그
(아이텍 trade_payables=0)가 가짜 PASS 로 가려졌다(`face_audit.py:776-786`). 같은 검사를 한다:

```
Phase 1 적용 전후로 is.sga 후보가 새로 생긴 행 중,
db_won == 0 이거나 새 후보와의 일치가 '값 0' 으로 성립한 행을 전수 나열 → 원문 확인
통과선: 그런 행 0건, 또는 전건 원문확인 완료
```

**D. fail_a 증가 0** — 프로젝트 공통 통과선.

**E. 회귀** — `pytest tests/ fin2/tests/` (NAS 심링크 회피, [[feedback-pytest-scope-raw-report-symlink]]).
현재 549 통과 기준선 유지 + Phase 2 신규 테스트.

**F. 신규 테스트가 반드시 덮어야 할 것**

- securities 재계산 PASS
- **재계산 불일치 → 여전히 fail** (면제로 퇴화하지 않음을 고정)
- 성분 결측 → `DERIVED_COMPONENTS_UNVERIFIED`(pending), fail 아님
- `gross_fallback` 행은 이 경로를 **타지 않음**
- profile 없는 행 무영향

---

## 7. 리스크

| 리스크 | 대응 |
|---|---|
| **프로파일 자체가 잘못 적용된 회사를 감사가 덮어준다** | 본 설계는 "계층3이 주장한 성분이 원문에 있는가"만 검증한다. **"이 회사에 이 업종 표준이 맞는가"는 검증하지 않는다** — §8 미결로 명시. 프로파일 적용 판정(`applies_to`/`signature_labels`)의 정합성은 별도 트랙 |
| 재계산이 관용오차에 기대 느슨해진다 | 허용오차는 기존 `tol`(표시단위 1단위, `face_audit.py:1029`)만 쓴다. 새 관용 도입 금지 |
| Phase 0 에서 bank/insurance 성분이 face 에 없다고 나옴 | 그 profile 은 `DERIVED_COMPONENTS_UNVERIFIED`(pending) 로 남긴다 — **면제가 아니라 "미검증" 표시**이고, ③ 이후 재도전 |
| `industry_lines` 를 감사가 신뢰한다 = 파이프라인 산출물 의존 | 이것은 **의도된 것**이다. 감사기는 계층3의 *주장*을 입력으로 받고 *원문*으로 판정한다 — 주장을 원문 없이 믿는 게 아니다. 단 `industry_lines` 가 비거나 손상되면 재계산 불가 → pending(안전측) |

---

## 8. 미결 / 범위 밖

- **프로파일 적용 자체의 정합성**(어느 회사에 어느 업종 표준이 맞는가)은 검증하지 않는다.
  현재 `CORP_INDUTY_OVERRIDE` 는 1건(다올투자증권)뿐이고, KSIC 오분류 탐지는 별도 과제.
- profile 미보유 revenue 실패 **36건**(fail_a 12 / fail_b 24)은 일반 매핑 결함 — 본 문서
  범위 밖. ② 이후 비금융 627건과 함께 다룬다.
- `is.sga` 를 `STD_FIELD_CANONICAL` 에 **정식 감사 필드로 추가하지 않는다**(별도 결정 필요).
  본 설계는 `by_canon` 후보 조회에만 쓴다.
- 계층3이 `industry_lines` 를 남기지 않는 pre-2015 행은 대상이 아니다(그 구간은 애초에
  대부분 `SOURCE_NOT_TRACK_A` pending).

---

## 9. 다음 문서

`gateb_audit_performance_design_2026-08-1x.md`(③) — corp 1개 36분+ 를 낮춰 **전수 재감사**를
가능하게 한다. 본 문서 Phase 3 은 46개사 표적이라 ③ 없이 수행 가능하지만, ② 이후의
전수 재검증은 ③ 이 전제다.
