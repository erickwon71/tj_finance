# valuation_daily 이식 블로커 2건 — 실측·원인규명·구현 설계 (2026-08-30)

> **미구현 — 승인 대기.** 이 문서는 실측과 설계까지만 담는다. 구현은 사용자가 별도로
> 지시한 뒤 착수한다([[feedback-plan-then-wait]]).
>
> **상위 문서**: [`valuation_daily_v3_migration_plan_2026-08-30.md`](valuation_daily_v3_migration_plan_2026-08-30.md)
> §Phase 0-2에서 이 두 블로커가 발견돼 이식이 중단됐다. 이 문서가 그 후속이다.

---

## 0. 요약 — ★이전 세션 기록 2건을 정정한다

이번 세션에서 두 블로커를 **원문 대조까지 내려가 규명**한 결과, 상위 문서와 메모리에
기록돼 있던 **원인 귀속이 둘 다 틀렸다**. 아래가 실측에 기반한 정정본이다.

| | 이전 기록(2026-08-30 오전) | **실측 결론(이 문서)** |
|---|---|---|
| **블로커 2**<br>`ebitda`/`da_total` | "v2 `rule_additive_da`의 결합공시(결합값+별도계상분) 합산 로직이 v3 `note_da.py`에 **미이식**된 것으로 추정 → v3에 이식 필요" | **정반대다. v2가 틀렸고 v3가 맞다.**<br>`note_extractor._add_da_total()`이 **합성한** `note.da_total`을 구성요소와 **나란히** 방출 → `rule_additive_da`가 이를 *공시된* 합계로 오인해 구성요소를 또 더한다 → **정확히 2배**.<br>v3 `note_da.py`에는 결합 병합 로직이 **이미 있고**(:139-147) 방출 형태도 올바르다. 이식할 것이 없다. |
| **블로커 1**<br>`net_debt` | "P1A(lease/borrow 카탈로그 분해) 소관. 기존 설계문서 있음 — 검토·실행만 하면 됨" | **P1A가 아니다.** `net_debt = short_term_debt + long_term_debt − cash`이고 `lease_liability`/`borrowings_*`는 **이 식에 안 들어간다**(실측 산식 확인).<br>진짜 원인 = **v3의 차입금 라벨 매핑이 2024+ DART 표준라벨을 못 받고, 만기(유동/비유동) 판정에 `section_path`를 안 쓴다**(acode 상실의 실제 발현). |

**두 정정의 공통 교훈**: 두 기록 모두 "표본 몇 건의 숫자 차이"에서 원인을 **추정**한
것이었고 원문까지 내려가지 않았다([[feedback-verify-against-source]]). 블로커 2는
숫자가 **정확히 2배**라는 산술 특징 하나만 확인했어도 방향이 바로 잡혔다.

**결론적으로 이식 난이도가 크게 낮아졌다** — 블로커 2는 "v3에 없는 로직을 새로
설계·이식"이 아니라 "**v2 쪽 버그를 고치거나, 그냥 v3로 넘어가면 자동 해소**"다.

---

## 1. 블로커 2 — `ebitda`/`da_total`

### 1-1. 근본 원인 (확정)

체인은 세 파일에 걸쳐 있고, 각 단계는 **단독으로는 타당한데 조합되면 이중계상**이다.

```
parser/xml/note_extractor.py:300  _add_da_total()
    dep + amo + rou 를 합산해 note.da_total 을 **합성**하고
    → 구성요소가 이미 들어있는 같은 facts 리스트에 append 한다.
                    ↓
fin2/extract/notes.py:83  extract_note_da_facts()
    그 리스트를 그대로 fact_v2 로 방출(source_format='note_cf').
    → 한 (corp,fy,basis)에 note.da_total + note.depreciation + note.amortization 공존.
                    ↓
fin2/standardize/rules.py:230-241  rule_additive_da()
    _DA_TOTAL_CANON(=cf.da_total, note.da_total)을 **회사가 공시한 합계**로 간주하고
        da_total = da_direct + dep + amo
    를 계산한다 → da_direct 자체가 dep+amo 이므로 **정확히 2배**.
```

★ 이건 **이미 알려져 있었고 한 번 고쳐진 함정**이다.
`fin2/extract/cf_da.py:64-69`이 바로 이 위험을 명시적으로 기록해 두었다:

> *"★ note.da_total 합성 폐지(D11, 2026-07-17). … 구버전은 dep+amo 를 note.da_total 로
> 만들어 넣었고, rule_additive_da 는 _DA_TOTAL_CANON 을 **직접 공시된 합계**로 간주해
> 우선 채택한다 → 회사가 공시한 합계와 코드가 더한 값이 DB 에서 구분 불가.
> ⟹ 구성요소만 방출하고 합산은 rule_additive_da 에 맡긴다."*

D11은 `_face_da_facts()`(본문 face 경로)에서만 합성을 폐지했고, **레거시
`note_extractor.py` 경로(`recover_cf_da()` ① 분기)에는 적용되지 않았다.** 즉
**두 생산자 중 하나만 고친 미완의 수정**이다.

### 1-2. 실측

**(a) 생산자별 — 이중계상은 `note_cf` 한 생산자에 국한된다**

| `source_format` | note.da_total 행 | 구성요소 동반 | total == 구성요소합 |
|---|---:|---:|---:|
| **`note_cf`** | 736 | **736 (100%)** | **735 (99.9%)** |
| `note_expense` | 688 | 67 (9.7%) | 2 (0.3%) |

`note_cf` 는 **전건이** 구성요소를 동반하고 **전건이** 합성 합계(=구성요소합)다.
`note_expense`(비용의성격별 주석 경로)는 사실상 무해 — 별도 트랙으로도 필요 없다.

**(b) 연도별 — FY2024부터만 발생한다**

`da_total`이 v2·v3 양쪽에 있는 FY 행 기준. 이중계상 판정 = `da_total == 2×(dep+amo)`.

| fy | 양쪽 보유 | 이중계상 | 비율 | v2/v3 불일치 | 불일치 중 이중계상 몫 |
|---:|---:|---:|---:|---:|---:|
| 2015~2023 | 각 995~1,289 | **0** | 0.0% | 160~226 | 0.0% |
| **2024** | 1,748 | **222** | **12.7%** | 431 | **51.5%** |
| **2025** | 1,812 | **485** | **26.8%** | 647 | **75.0%** |

FY2024 이전에 0인 것이 원인 가설과 정확히 맞는다 — `cf_da.py`의 note_cf 복원은
**2024+ Track A 포맷 전환 갭을 메우려고 도입된 경로**라 그 이전 보고서에는 아예 안 돈다.
그리고 최근 2년의 v2/v3 `da_total` 불일치 중 **과반~3/4이 이 버그 하나**다.

**(c) 영향 범위**: 이중계상된 `da_total` 위에 `ebitda`가 얹힌 std_v2 FY 행 **735건 /
519개사**(최초 period_end 2024-12-31). 이 519개사가 `valuation_daily.ev_ebitda`에서
잘못된 배수로 보이고 있다(matview 총 11,196,547행 중 `ev_ebitda` 보유 3,763,689행,
2,514개사).

**(d) 원문 대조 — 1건 전수 확인 (`00130763` FY2024 consolidated, rcept 20250327001143)**

`note_lines` 원문(현금흐름표 주석, table_seq 605):

```
  t605 r4  감가상각비에 대한 조정        87,185,001,000
  t605 r5  무형자산상각비에 대한 조정      5,843,894,000
  t605 r6  대손상각비 조정               4,940,008,000   ← D&A 아님
```

**결합 표기('감가상각비 및 무형자산상각비') 행은 문서에 존재하지 않는다.**
그런데 `fact_v2`에는 세 행이 들어있다:

```
  note.depreciation   87,185,001,000  [note.depreciation] note_cf
  note.amortization    5,843,894,000  [note.amortization] note_cf
  note.da_total       93,028,895,000  [note.da_total]     note_cf   ← 합성물(=위 둘의 합)
```

| | 값 | 판정 |
|---|---:|---|
| 원문이 함의하는 정답 | **93,028,895,000** | 87,185,001,000 + 5,843,894,000 |
| **v3** `da_total` | **93,028,895,000** | ✅ 정확 |
| **v2** `da_total` | 186,057,790,000 | ❌ 정확히 2배 |

→ **v2가 틀렸고 v3가 맞다.** 이전 기록의 "v3에 결합공시 로직 미이식" 가설은 기각.

**(e) v3는 왜 안전한가 — 구조적으로 방출 형태가 다르다**

`fin2/layer3/note_da.py:139-147`은 결합 표기가 있을 때 **결합값 + 별도계상분을 합쳐
`DA_COMBINED` 하나로만** 내보내고 구성요소를 **따로 내보내지 않는다**
(`DA_COMBINED == "note.da_total"`, `parser/common/note_labels.py:39`).

```
v3가 rule_additive_da 에 넘기는 것:  {note.da_total: 병합값}          (구성요소 없음)
  → da_total = da_direct + 0 + 0 = 병합값                              ✅
v2가 rule_additive_da 에 넘기는 것:  {note.da_total: 합성합, note.depreciation, note.amortization}
  → da_total = 합성합 + dep + amo = 2×                                 ❌
```

즉 v2가 놓쳤다고 기록됐던 "결합공시+별도계상분" 처리는 **v3에 이미 구현돼 있다.**

### 1-3. 잔여 불일치 클래스 (이중계상이 아닌 것) — v3가 더 완전하다

FY2015~2023(이중계상 0인 구간)의 `da_total` 불일치 **1,685건**:

| | 건수 | 비율 |
|---|---:|---:|
| **v3 > v2** | **1,651** | **98.0%** |
| v2 > v3 | 34 | 2.0% |
| 평균 상대격차 | | 49.9% |

표본 12건 직접 대조 결과 **`amortization`은 12건 전부 v2·v3 동일**하고, 차이는 전부
`depreciation` 한 항목에서 난다 — v2가 **0이거나(6/12) 더 작다**. 예:

```
00118804 FY2017 separate   v2 d=            0  a=2,182,733,817  t= 2,182,733,817
                           v3 d=24,546,471,894 a=2,182,733,817  t=26,729,205,711
00148993 FY2020 cons       v2 d=133,783,254,398 …  t=136,395,975,839
                           v3 d=150,558,878,627 …  t=153,171,600,068
```

방향이 98% 한쪽이고 항목이 하나로 특정된다 → **v3가 v2가 놓친 감가상각을 회수하는
패턴**이며, [[generation-unification-layer2-layer3-2026-08-30]]에 이미 실측된
`depreciation` 74,962→81,238 커버리지 순증과 같은 현상이다. **v3 이식을 막는 요인이
아니다** — ★이 추정은 §1-4의 표본 5건 전수 원문대조로 **확정됐다**(5/5 v3 정확).

### 1-4. ★§4-1 실행 결과 — 잔여 클래스 표본 5건 원문 대조 (2026-08-30, 완료)

§1-3이 "v3가 v2가 놓친 걸 회수하는 패턴으로 **보인다**"고만 했던 부분을 원문
(`report_lines` CF 본문, col0)까지 내려가 전건 확정했다. **5/5 전건 v3가 정확하고
v2가 오류다.** 대조 대상은 v3 > v2인 FY2015~2023 행에서 무작위 추출한 것이다.

| # | 기업 | 기간 | 원문이 함의하는 정답 | v3 | v2 | 판정 |
|---|---|---|---:|---:|---:|---|
| 1 | 동진쎄미켐 `00118804` | FY2017 sepa | 26,729,205,711 | **일치** | 2,182,733,817 | v3 ✅ |
| 2 | 다스코 `00353878` | FY2017 cons | 4,022,249,828 | **일치** | 178,479,404 | v3 ✅ |
| 3 | 비트컴퓨터 `00231707` | FY2017 sepa | 531,500,604 | **일치** | 31,643,115 | v3 ✅ |
| 4 | 하이트진로홀딩스 `00148993` | FY2020 cons | 153,171,600,068 | **일치** | 136,395,975,839 | v3 ✅ |
| 5 | 국일제지 `00104573` | FY2022 cons | 2,728,861,082 | **일치** | 2,352,914,737 | v3 ✅ |

v3는 **5건 모두 원 단위까지 정확히 일치**했다.

#### 원문 근거 (대표 2건)

**#1 동진쎄미켐 FY2017 별도** — CF 본문 `영업활동현금흐름>가감`:
```
  r5  감가상각비              24,393,130,356
  r6  투자부동산감가상각비        153,341,538
  r7  무형자산상각비           2,182,733,817
```
dep = 24,393,130,356 + 153,341,538 = **24,546,471,894** = v3 dep ✅
da_total = **26,729,205,711** = v3 ✅ / v2는 감가상각을 통째로 잃고 상각비만 남았다.

**#4 하이트진로홀딩스 FY2020 연결** — CF 본문 `영업활동현금흐름>당기순이익조정을 위한`:
```
  r12  감가상각비(투자부동산)        171,457,154
  r13  감가상각비              133,783,254,398
  r17  무형자산상각비             2,612,721,441
  r21  감가상각비(사용권자산)     16,604,167,075
  (r5 대손상각비 2,264,405,685 · r6 기타의 대손상각비 107,808,500 — D&A 아님)
```
dep = 133,783,254,398 + 171,457,154 + 16,604,167,075 = **150,558,878,627** = v3 dep ✅
v2와의 격차 16,775,624,229 = 투자부동산 171,457,154 + 사용권자산 16,604,167,075 **정확히 일치**.
★부수 확인: `note_da_canonicals()`가 독립적으로 `{note.da_total: 153,171,600,068}`을
반환해 **본문 산출값과 원 단위까지 일치** — 주석이 본문을 교차검증해 준다.

#### v2의 실패 양상은 두 가지다 (둘 다 **stale**, 현행 코드 버그 아님)

| 양상 | 해당 | 내용 |
|---|---|---|
| (i) **충돌 폐기** | #1 #2 #3 | `fact_v2`에 `감가상각비`·`투자부동산감가상각비` 두 행이 **다 있는데** std_v2 출력은 `dep=0`. `rules.py:53-60`이 기록한 바로 그 증상 — *"단일값으로 취급하면 충돌 판정에 걸려 canonical 이 통째로 폐기된다"*. `ADDITIVE_CANON` 선언(2026-07-28)으로 **v2 코드는 이미 고쳐졌으나** 이 FY2017 행들은 재표준화된 적이 없다 |
| (ii) **라벨 누락** | #4 #5 | `감가상각비(사용권자산)`·`감가상각비(투자부동산)` 행이 `fact_v2`에 **아예 없다**(계층2 추출 시점 매핑 실패). 현행 매퍼는 둘 다 `cf.depreciation`으로 매핑한다(fuzzy 0.94/0.97) → 역시 stale |

현행 매퍼 실측(`fs_section='cf'`):
```
감가상각비            -> cf.depreciation  exact (1.00)
투자부동산감가상각비      -> cf.depreciation  exact (1.00)
감가상각비(투자부동산)    -> cf.depreciation  fuzzy (0.97)
감가상각비(사용권자산)    -> cf.depreciation  fuzzy (0.94)
무형자산상각비          -> cf.amortization exact (1.00)
대손상각비            -> unknown          (0.00)   ← D&A 아님, 올바르게 배제
기타의 대손상각비        -> unknown          (0.00)   ← 동일
```

#### 결론

- **잔여 클래스 1,685건은 "v3의 리스크"가 아니라 "std_v2의 stale 데이터"다.**
  v2 코드는 이미 고쳐졌고 소급 백필만 안 됐을 뿐이다
  ([[parser-pipeline-integration-runbook]] ②의 전형적 사례).
- 따라서 §3의 `ev_ebitda` v3 이식은 **§1-2(d) 이중계상 정정**과
  **여기 stale 회복** 두 방향 모두에서 정당화된다.
- 부수 확인 2가지: ① `대손상각비` 계열이 D&A에서 올바르게 배제된다(#2 #3 #4 #5에서
  원문에 함께 있었으나 v3 da_total에 안 들어갔다). ② 본문 D&A가 있을 때 주석 주입이
  차단되는 가드(`combine.py:2835 _BODY_DA_CANON`)가 실제로 동작한다 — #3은 주석이
  `{note.da_total: 168,234,000}`을 내놨지만 v3 da_total은 본문값 531,500,604로 남았다.

### 1-5. 설계

#### B2-D1. 수정 위치 = **fin2 경계**(`fin2/extract/notes.py`), 레거시 파서는 건드리지 않는다

`parser/xml/note_extractor.py::_add_da_total()`을 직접 지우는 안은 **기각**한다 —
`extract_da_from_cf_notes()`의 소비자가 둘이다:

| 소비자 | 영향 |
|---|---|
| `fin2/extract/notes.py:83` | **이 문서의 대상** |
| `parser/xml/dart_xml_parser.py:674` | 레거시 파서. 이번 트랙 범위 밖 — 회귀 위험만 떠안는다 |

→ **fin2 쪽 경계에서 걸러낸다.** 레거시 동작은 불변이므로 회귀면이 최소다.

#### B2-D2. 합성물 식별은 **추측이 아니라 표식**으로

`_add_da_total()`이 만드는 행은 고유한 표식을 이미 달고 있다
(`note_extractor.py:319-320`):

```python
account_name_raw="D&A 합계 (감가상각비+무형자산상각비)"   # synthesized-total marker
unit_multiplier=1                                        # already absolute
```

이 문자열은 코드가 붙인 리터럴이라 **원문 라벨과 충돌할 수 없다**. "구성요소가 있으면
버린다" 같은 값 기반 휴리스틱(합이 우연히 일치할 수 있음)보다 안전하다.

```python
# fin2/extract/notes.py — inside extract_note_da_facts(), when folding `fs` into by_code.
#
# `note_extractor._add_da_total()` SYNTHESIZES note.da_total = dep+amo+rou and appends it
# next to the components it was built from. rule_additive_da() treats _DA_TOTAL_CANON as a
# *disclosed* total and adds the components on top -> exactly 2x (measured: 735/736 note_cf
# rows, FY2024 12.7% / FY2025 26.8% of all rows). Same hazard D11 (2026-07-17) removed from
# the CF-face path in cf_da.py; the legacy note path was never covered.
# Emit components only and let rule_additive_da do the summing, exactly as D11 prescribes.
_SYNTHETIC_DA_TOTAL_NAME = "D&A 합계 (감가상각비+무형자산상각비)"
...
for f in fs:
    if (f.account_code == "note.da_total"
            and f.account_name_raw == _SYNTHETIC_DA_TOTAL_NAME):
        continue        # synthesized rollup - would double-count in rule_additive_da
    ...
```

**주의 — 단위보정 앵커는 그대로 둔다.** `_unit_factor()`가 쓰는 `da_total`은
`by_code.get("note.da_total")`이고, 걸러내면 폴백(`_DEP_LIKE` 합)으로 넘어가는데
합성물의 정의상 **두 값은 같다** → 배율 판정 불변. 그래도 회귀 여부를 §4-2에서
명시적으로 확인한다.

#### B2-D3. **소급 백필이 필요한가 — 필요 없다(권고)**

이 수정은 `fact_v2`의 기존 `note.da_total` 행과 std_v2의 기존 `da_total`/`ebitda`를
**자동으로 고치지 않는다**([[parser-pipeline-integration-runbook]] ②). 그런데:

- std_v2의 유일한 살아있는 소비자가 `valuation_daily.ev_ebitda`인데,
  **그건 이 트랙에서 v3로 옮긴다**(§3) → 옮기는 순간 오염값이 화면에서 사라진다.
- 상위 문서 §D3까지 끝나면 std_v2는 **쓰기 0**이 된다 → 재발 없음.

→ **std_v2 백필은 하지 않는다.** 다만 `fact_v2`의 합성 `note.da_total` 행은
`extended_financials` 뷰가 `note.%`를 (statement='IS' 조건으로) 노출하므로
**"코드가 만든 값이 공시값처럼 보이는" 출처 오염**이 남는다. 이건 숫자 오류가 아니라
provenance 문제라 심각도가 낮다 → **§6 후속 백로그**로 분리(삭제 SQL은 §4-4에 첨부).

#### B2-D4. 그러면 이 수정을 왜 하는가 (범위 정당화)

이식만 하면 화면은 고쳐지므로 "안 고쳐도 되는 것 아닌가"가 정당한 질문이다. 그래도
고치는 이유는 하나다: **`_sync_cf_da` 잔여 경로를 끊기(상위 문서 §D3) 전까지는
데일리가 매일 이 오염행을 새로 만든다.** §D3이 먼저 끝나면 이 수정은 불필요해진다.
→ **순서 권고: §D3(3줄 제거)을 먼저, B2 수정은 그 뒤 선택.** §5에 반영.

---

## 2. 블로커 1 — `net_debt`

### 2-1. P1A가 아니다 (기각 근거)

`net_debt` 산식은 `short_term_debt + long_term_debt − cash`다. 실측으로 확인:

```
00130684 cons FY2024: st 1,295,860,000 + lt 5,565,900,000 − cash 48,227,977,477
                    = −41,366,217,477  =  v2 net_debt  ✅ (lease/borrowings 미개입)
```

P1A가 다루는 것은 `bs.lease_liability`(리스부채 유동/비유동)와
`cf.borrowings_proceeds/_repaid`(차입 유입·상환 단기/장기) **세 컬럼의 분해**이고,
이들은 `net_debt` 식에 **들어가지 않는다**. 부수 확인: `std_financials_v3`에는
`lease_liability`/`borrowings_proceeds`/`borrowings_repaid` **컬럼 자체가 없다**
(P1A §4.2가 ALTER를 요구하는 이유) — 그런데도 v3는 `net_debt`를 정상 산출한다.
→ **P1A는 `net_debt`와 무관.** 이전 기록의 귀속은 기각.

### 2-2. 실측 — FY2024에서 절벽이 생긴다

| fy | 양쪽 보유 | 불일치 | 비율 |
|---:|---:|---:|---:|
| 2018 | 2,578 | 111 | 4.3% |
| 2019 | 2,670 | 108 | 4.0% |
| 2020 | 2,858 | 119 | 4.2% |
| 2021 | 2,993 | 125 | 4.2% |
| 2022 | 3,108 | 154 | 5.0% |
| 2023 | 2,938 | 188 | 6.4% |
| **2024** | 2,714 | **1,836** | **67.6%** |
| **2025** | 2,677 | **1,864** | **69.6%** |

`cash`는 표본 12건 **전건 동일**했다 — 격차는 전부 `short_term_debt`/`long_term_debt`에서
난다. 방향은 양쪽으로 갈린다(FY2024 기준):

| | 값 있음 | |
|---|---:|---|
| v2만 ST 보유 | 1,002 | v3가 놓침 |
| v3만 ST 보유 | 596 | **v2가 놓침** |
| v2만 LT 보유 | 301 | |
| v3만 LT 보유 | 282 | |
| 둘 다 있는데 ST 값이 다름 | 880 | |

FY2022~2023에서는 `only_v3_st`가 302/287로 `only_v2_st`(11/51)를 압도했다 —
**FY2024에 방향이 뒤집힌다.** 2024 Track A 포맷 전환과 정확히 일치한다.

### 2-3. 근본 원인 — 두 개의 별개 하위원인

FY2024 연결 표본 60건에서 "v2는 값이 있는데 v3는 없는" 금액이 원문의 어느 라벨에
실려 있는지 역추적한 뒤, 그 라벨을 v3 매퍼에 직접 통과시켰다.

```
raw                                   normalized              v3 매핑 결과              stage
유동 차입금(사채 포함)          (21건)  유동차입금(사채포함)      unknown.…                unknown  ← ★A
비유동차입금(사채 포함)의 비유동성 부분 (4건)  …                    unknown.…                unknown  ← ★A
비유동성 차입금                        비유동성차입금            unknown.…                unknown  ← ★A
유동차입금                            유동차입금               bs.current_portion_lt_debt  fuzzy 0.90 ← ★A(오매핑)
장기금융부채                    (2건)  장기금융부채             bs.other_current_payables   fuzzy 0.89 ← ★A(오매핑)
장기차입금(사채 포함), 총액      (13건)  장기차입금(사채포함), 총액  bs.long_term_debt        normalized ✅
장기차입금                      (5건)  장기차입금               bs.long_term_debt         exact ✅
단기차입금                            단기차입금               bs.short_term_debt        exact ✅
차입금                               차입금                  bs.short_term_debt        exact ✅   ← ★B
```

#### 원인 A — 2024+ DART 표준라벨이 v3 카탈로그에 없다 (미매핑·오매핑)

`account_maps/bs_accounts.py`는 `장기차입금(사채포함), 총액`은 갖고 있는데
(`:258`, 2026-07-18 추가) **유동 쪽 대응물 `유동차입금(사채포함)`이 없다** — 가장 흔한
라벨(표본 60건 중 21건, 최다)인데 통째로 `unknown`이다. `비유동성 차입금`,
`비유동차입금(사채포함)의 비유동성 부분`도 같다.

더 나쁜 두 건은 **조용한 오매핑**이다:
- `유동차입금` → `bs.current_portion_lt_debt` (fuzzy 0.90) — 유동성장기부채로 오분류
- `장기금융부채` → `bs.other_current_payables` (fuzzy 0.89) — **비유동을 유동으로**

> 정규화는 정상 동작한다(`normalize_account_name()`의 한글 사이 공백 제거로
> `유동 차입금(사채 포함)` → `유동차입금(사채포함)`, 번호 접두 `(2)`도 제거됨).
> **순수한 alias 카탈로그 갭**이다.

#### 원인 B — 만기 판정에 `section_path`를 안 쓴다 (acode 상실의 실제 발현)

`장기차입금`·`장기차입금(사채포함), 총액`처럼 **정상 매핑되는데도** v3가 값을 잃는
클래스가 있다. `00130763` FY2024로 전수 추적했다.

`report_lines`(BS, col0) 원문 구조 — **`section_path`에 만기 구분이 그대로 있다**:

```
  r25  d2  부채>유동부채     단기차입금      113,802,813,293
  r28  d1  부채              비유동부채      111,195,376,571
  r30  d2  부채>비유동부채   차입금          101,825,482,368   ← 라벨엔 '장기'가 없다
```

- **v2**: XBRL acode `dart_LongTermBorrowingsGross`가 만기를 말해준다 →
  `bs.long_term_debt = 101,825,482,368` ✅
- **v3**: 라벨 `차입금`이 `bs.short_term_debt`에 **exact** 매핑된다
  (`bs_accounts.py:211`, 주석: *"일반 차입금 (유동/비유동 불분명 시 유동 우선)"*).
  그 뒤 `combine.py:1598`의 `_CURRENT_STRICT` 가드가 `_is_noncurrent()`로
  `section_path='부채>비유동부채'`를 읽고 **후보에서 제외**한다.
  → `short_term_debt`는 113,802,813,293로 **올바르게** 남지만,
    **제외된 101,825,482,368은 `long_term_debt`로 재라우팅되지 않고 그대로 소실된다.**
  → `net_debt` 138,172,206,622(v2) vs 36,346,724,254(v3), 차이 = 정확히 101,825,482,368.

즉 `_CURRENT_STRICT`는 **오염은 막지만 회수는 안 한다.** 가드가 "이건 유동이 아니다"를
이미 알고 있는데 그 정보를 버리는 것이라, 필요한 신호는 전부 손에 있다.

### 2-4. 설계

#### B1-D1. 원인 B 우선 — `_CURRENT_STRICT` 제외분을 비유동 대응 canonical로 **재라우팅**

`_is_noncurrent()`(`combine.py:1276-1288`)가 이미 `section_path` 기반 만기 판정을 하고
있으므로 **새 판정 로직을 만들 필요가 없다.** 버리는 대신 짝 canonical로 넘긴다.

```python
# fin2/layer3/combine.py, near _CURRENT_STRICT (:1270)
#
# _CURRENT_STRICT drops non-current rows so a current canonical cannot absorb them, but it
# only PREVENTS contamination - the dropped amount is not recovered anywhere. Measured
# (00130763 FY2024): '차입금' under section_path='부채>비유동부채' maps exact to
# bs.short_term_debt, gets dropped by the guard, and the 101,825,482,368 never reaches
# bs.long_term_debt -> net_debt short by exactly that amount. fact_v2 got it right only
# because the XBRL acode (dart_LongTermBorrowingsGross) carried the maturity that the
# label text omits. section_path carries the same signal - route, don't discard.
_NONCURRENT_SIBLING = {
    "bs.short_term_debt": "bs.long_term_debt",
    "bs.current_bonds":   "bs.bonds",
}
```

`_CURRENT_STRICT` 필터 자리(`:1598`, `:1749` **두 곳 모두**)에서 탈락 행을
`cands[_NONCURRENT_SIBLING[canon]]`에 **추가**한다.

> **★구현 시 변경 — 코드 위치.** 아래 설계는 `_CURRENT_STRICT` 필터 두 자리(`:1598`,
> `:1749`)에서 인라인 처리를 제안했으나, 실제 구현은 **`_resolve()` 본문 루프 앞
> pre-pass**로 옮겼다: canonical 순회 순서가 보장되지 않아(짝 canonical이 먼저
> 처리되면 재라우팅이 이미 늦음) `for c, rows in cands.items()` 도중 `cands`에 없던
> 키를 추가하면 `RuntimeError`(dict 크기 변경)가 난다. 순서 무관하게 항상 짝
> canonical이 재라우팅된 후보를 보도록 pre-pass로 재설계했다(순도는 동일, R57 참고).
> **가드도 3개가 아니라 4개**다 — 구현 중 "`_src`가 전부 비유동이면 재라우팅
> 안 함"(기존 `_is_noncurrent()`의 MISSING 방지 안전장치와 충돌해 2배가 될 수 있음)
> 이 추가로 필요함을 발견했다.

**필수 가드 3가지(설계 시점 — 구현 후 4개로 확정, 위 note 참고)**:
1. **짝 canonical에 이미 후보가 있으면 추가하지 않는다** — 회사가 `장기차입금`을
   별도 행으로 이미 공시했는데 여기에 또 넣으면 `rule_additive_debt`가 이중계상한다.
2. **`label_raw`에 이미 `장기`/`비유동`이 있으면 추가하지 않는다** — 그런 행은 애초에
   짝 canonical로 정상 매핑됐을 것이고, 여기 온 건 다른 이유다.
   (= `section_path`만으로 비유동인 행, 즉 `00130763`형만 대상)
3. **`rule_additive_debt`의 기존 `total_liabilities × 1.05` 이중계상 가드**
   (`rules.py:~300`)가 최종 방어선으로 계속 동작하는지 확인.

#### B1-D2. 원인 A — alias 카탈로그 보강 (`account_maps/bs_accounts.py`)

```python
"bs.short_term_debt": [
    ...,
    # 2024+ DART standard labels (Track A). Measured FY2024: '유동 차입금(사채 포함)' is the
    # single most common dropped label (21/60 sampled) and lands in `unknown` today.
    # normalize_account_name() collapses the inner spaces, so register the collapsed form.
    "유동차입금", "유동차입금(사채포함)", "유동성차입금",
],
"bs.long_term_debt": [
    ...,
    "비유동차입금(사채포함)", "비유동차입금(사채포함)의비유동성부분", "비유동성차입금",
],
```

**★`유동차입금`은 지금 fuzzy 0.90으로 `bs.current_portion_lt_debt`에 붙고 있다** —
exact alias를 등록하면 stage가 `exact`로 올라가 fuzzy를 이긴다(오매핑 교정).

**미결로 남기는 것 — `장기금융부채`**: 현재 `bs.other_current_payables`(fuzzy 0.89)로
가는데, `bs_accounts.py:257`이 *"⚠ '장기금융부채'는 제외(금융부채>차입금이라 debt
과대 우려 = 오염)"*라고 **의도적 배제**를 기록해 뒀다. 배제 의도는 맞지만 지금
착지점(유동 기타채무)은 명백히 틀렸다. **`bs.long_term_debt` 편입이 아니라
fuzzy 차단(`_FUZZY_BLOCK`)이 옳은 조치**로 보이나, 규모 미실측이라
**§6 후속**으로 분리한다(`단기금융부채`도 같은 증상, 같이 처리).

#### B1-D3. 실행 순서 — B1-D1(원인 B) → 측정 → B1-D2(원인 A)

카탈로그 변경(D2)은 [[gateb-full-reaudit-is-required-to-close]]와
[[gateb-r51-posco-steelion-total-equity-complete-2026-08-27]]가 보여주듯 **다른 계정으로
회귀가 번지는 유형**이다(리노공업 사례). D1은 `bs.short_term_debt`/`bs.current_bonds`
두 canonical에 국한돼 면적이 훨씬 작다. → **작은 것부터, 각각 재감사 사이에 두고.**

또한 D1을 먼저 하면 D2의 실제 잔여 규모가 줄어든 채로 측정된다(두 원인이 같은
행에 겹쳐 있는 경우가 있다 — 예: `차입금` 행이 D1으로 회수되면 그 행의 `unknown`
라벨 통계도 바뀐다).

---

## 3. 이식 결정 갱신 — 상위 문서 D1-a/D1-b 재정리

상위 문서 §2 D1은 `ebitda`/`net_debt`를 "v2 값을 계속 써야 한다"고 보류했다.
**§1의 정정으로 `ebitda`는 보류할 이유가 사라졌다.**

| 컬럼 | 상위 문서(오전) | **이 문서의 결론** |
|---|---|---|
| `per`/`pbr`/`psr`/`eps`/`bps`/`dps`/`dividend_yield` | D1-a 안전 | 변경 없음 — **v3로 이식** |
| **`ev_ebitda`** (`ebitda` 경유) | D1-b 보류 | **보류 해제 → v3로 이식.** v2가 519개사에서 틀린 값(2배 D&A)이라 **v2를 계속 쓰는 것이 더 위험**하다 |
| `ev`/`ev_ebitda`/`ev_ebit` (`net_debt` 경유) | D1-b 보류 | **보류 유지.** 단 사유는 P1A가 아니라 §2의 원인 A/B — 그것이 해소되면 이식 |

→ **matview를 두 LATERAL로 쪼갤 필요가 §2 해소 시점까지로 줄었다**(상위 문서 §D1
말미의 우려). `net_debt`만 v2에 남기면 되고, 그마저도 §2 구현이 끝나면 단일 v3
LATERAL로 되돌릴 수 있다.

> **판단 근거를 명시**: `ev_ebitda`를 v3로 옮기면 519개사의 EV/EBITDA 배수가 **눈에
> 띄게(대략 절반 방향으로) 움직인다.** 이건 회귀가 아니라 **오류 정정**이다 —
> §1-2(d)의 원문 대조가 근거다. 사용자가 밴드 차트에서 이 변화를 볼 것이므로
> §4-5에 육안 확인을 명시적으로 넣었다.

---

## 4. 검증 계획

- [x] **4-1.** §1-3 잔여 클래스 원문 대조 — **완료(2026-08-30). 5/5 전건 v3가 정확,
      v2가 오류.** 상세는 §1-4. **§3의 `ev_ebitda` 이식이 정당화됨.**
- [ ] **4-2.** B2 수정 후 `_unit_factor()` 회귀 확인 — 합성 `note.da_total`을 거른 뒤
      배율 판정이 바뀐 (rcept, basis)가 **0건**인지(§B2-D2의 논증대로면 0이어야 한다).
- [ ] **4-3.** 회귀 테스트 `pytest tests/ fin2/tests/` — 루트 범위 없이 돌릴 것
      ([[feedback-pytest-scope-raw-report-symlink]]).
- [ ] **4-4.** B1 각 단계(D1, D2) **직전에 `face_audit` 스냅샷**을 뜨고, 구현 후
      **전수 재감사**로 등급 전이를 본다([[gateb-full-reaudit-is-required-to-close]] —
      표본으로 닫으면 다음 전수에서 재등장). 기준: **pass→fail 전이 0**.
      ```sql
      CREATE TABLE face_audit_snap_20260830 AS SELECT * FROM face_audit;
      ```
- [ ] **4-5.** matview 이식 후 표본 corp의 `per`/`pbr`/`ev_ebitda` 시계열 전후 비교.
      **§1-2(c)의 519개사 중 하나를 반드시 포함**해 `ev_ebitda`가 예상대로(≈2배 방향)
      움직이는지 확인. 밴드 차트 육안 확인 권장(`streamlit run app/main.py`).
- [ ] **4-6.** `scripts/dq_assertions.py::valuation_daily_stale` 통과 유지.

**전제 스냅샷 SQL**(§B2-D3 후속 백로그용 — 지금 실행하지 않는다):
```sql
-- fact_v2 synthesized note.da_total rows (provenance pollution, not a numeric error)
SELECT count(*) FROM fact_v2
WHERE canonical_account = 'note.da_total' AND source_format = 'note_cf';
```

---

## 5. 구현 순서 (권고)

| # | 작업 | 근거 | 위험 | 상태 |
|---|---|---|---|---|
| 1 | 상위 문서 **§D3** — `cf_da_sync`/`expense_nature_sync`에서 3줄 제거 | 오염행 **신규 생산 중단**. B2 코드 수정 없이 출혈을 먼저 막는다 | 낮음(제거만) | ✅ 완료(`bd39d44`) |
| 2 | **§3 이식** — matview `ni`/`eq`/`revenue`/`cfo`/`dividends_paid`/**`ebitda`** → v3, `net_debt`만 v2 LATERAL | 519개사 `ev_ebitda` **정정**. 파생 matview라 롤백 즉시 가능 | 낮음 | ✅ 완료(2026-08-30 저녁, 마이그레이션 `2026_08_valuation_daily_v3_ebitda_migration` + refresh, 표본 검증·회귀테스트 통과) |
| 3 | **B1-D1** — `_NONCURRENT_SIBLING` 재라우팅 | `net_debt` 최대 원인, 면적 좁음 | 중간 → 4-4 전수재감사 | ✅ 코드+단위테스트+표본1건(00130763) 실측 완료(R57 등재) — **전수재감사 대기** |
| 4 | **B1-D2** — alias 카탈로그 보강 | 잔여 미매핑 | 중간~높음 → 4-4 전수재감사 | 미착수 |
| 5 | matview `net_debt`도 v3로 → **단일 LATERAL 복귀** | 이식 완료 | 낮음 | 미착수(3~4 선행) |
| 6 | **B2 수정**(`fin2/extract/notes.py`) | 1이 끝났으면 **불필요할 수 있다**(§B2-D4) — 그때 재판단 | 낮음 | 재판단 대기 — 1번 완료로 신규 오염 생산은 이미 멈춤, fact_v2 기존 합성행 provenance 정리만 남음(§B2-D3, §6 후속) |

★★**다음 세션 시작점 = 순서 3(B1-D1, `net_debt` `_NONCURRENT_SIBLING` 재라우팅)**.
착수 전 `face_audit` 스냅샷 필수: `CREATE TABLE face_audit_snap_20260830 AS SELECT *
FROM face_audit;`(또는 classB 트랙에서 이미 뜬 2026-08-30 오전 재감사 결과를 베이스라인으로
재사용 가능 — 그 사이 순서1·2는 std_v2/valuation_daily만 건드려 face_audit 대상인
std_v3/report 원문 대조에는 영향 없음, 재사용 시 그 근거를 명시할 것).

---

## 6. 명시적 범위 밖 (후속 백로그)

- **`fact_v2`의 합성 `note.da_total` 행 정리**(§B2-D3) — provenance 오염, 숫자 오류 아님.
  `extended_financials`가 `note.%`를 노출하므로 언젠가는 정리 필요.
- **`장기금융부채`/`단기금융부채`의 fuzzy 오매핑**(§B1-D2) — `bs.other_current_payables`로
  가는 것은 명백히 틀렸으나 `_FUZZY_BLOCK` 조치의 파급 규모 미실측.
- **P1A(lease/borrow 분해)** — `net_debt`와 무관함이 확정됐으므로
  **이 트랙의 선행조건이 아니다.** `p1a_p1c_implementation_plan_2026-08-22.md` 그대로
  독립 트랙으로 남는다(`lease_liability`/`borrowings_*` 컬럼 자체의 정확도 개선 목적).
- **pre-1999 249행**·**`is_stub` v3 PK 재도입** — 상위 문서 §6과 동일.
- **`note_expense` 경로** — 실측상 무해(688건 중 2건만 total==parts). 조치 불필요.

---

## 7. 참고

- 상위: [`valuation_daily_v3_migration_plan_2026-08-30.md`](valuation_daily_v3_migration_plan_2026-08-30.md) §Phase 0-2(이 두 블로커의 발견 지점 — **§0 표대로 원인 귀속을 정정할 것**)
- [`std_v3_daily_wiring_plan_2026-08-30.md`](std_v3_daily_wiring_plan_2026-08-30.md) §2-3(잔여 경로) · §8(백로그)
- [`p1a_p1c_implementation_plan_2026-08-22.md`](p1a_p1c_implementation_plan_2026-08-22.md) — §2-1에서 `net_debt`와 무관함이 확정됨
- `fin2/extract/cf_da.py:64-69` — **D11(2026-07-17)**, 이 함정을 이미 기록했으나 한 경로에만 적용됨
- `fin2/layer3/note_da.py:139-147` · `parser/common/note_labels.py:39` — v3의 결합 병합(이미 구현됨)
- `fin2/layer3/combine.py:1270-1288, 1598, 1749` — `_CURRENT_STRICT`/`_is_noncurrent`
- `account_maps/bs_accounts.py:205-259` — 차입금 alias 카탈로그
- `docs/PARSING_RULES.md` — 규칙 확정 시 **먼저 여기에 등재**(R번호 부여)
