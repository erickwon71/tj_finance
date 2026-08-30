# std_v2 폐기 준비 — v2 전용 기능·데이터의 std_v3 이식

> **범위 = 이식(포팅)까지.** v2 테이블·체인의 물리적 삭제와 데일리 배선은 이 계획 밖이며,
> 이식이 검증된 뒤 별도 계획으로 다룬다. 이 문서의 완료 조건 = **"v2를 지울 수 있는 상태"**.

## 개정 이력

- **초판 2026-08-22** — P1~P6 구성. 위치는 `~/.claude/plans/std-v3-reactive-prism.md`였다.
- **2차 개정 2026-08-22** — 프로젝트로 이관(`docs/plans/`). 사용자 문제제기
  *"v2는 이전 파서 데이터라 새 파싱 데이터와 차이가 있을 것 같다. 필요하면 v3에 새로 적재된
  데이터로 만들어 내는 것이 맞다"* 에서 출발해 재검토한 결과 **초판의 핵심 전제가 하나 뒤집혔다**:

  | 초판 | 2차 개정 |
  |---|---|
  | P1 = "저위험 이식(값 불변)" | **틀림** — 카탈로그 변경 수반(§3.7). P1C(진짜 저위험)/P1A(위험 중)로 분리 |
  | "미이식 규칙 9종을 붙이면 된다" | **불충분** — 규칙의 입력 canonical이 v3 네임스페이스에 없다(§3.7). 그대로 붙이면 **무동작**(R15) |
  | v2-only 범주 = 비교컬럼 + filing없음 | **누락 있음** — `kgaap_gap` 제3범주(§3.8) |
  | (언급 없음) | `extended_financials` long-format에 v3 등가물 없음(§3.9) |
  | (언급 없음) | 데일리가 매일 `fact_v2`에 쓴다 — v2 체인은 휴면이 아니다(§3.10) |

  추가로 §2에 **대원칙("v2 값을 복사하지 않는다")** 을 명문화하고, P0.5(정합성 조사)를 신설했다.
  발견 방법 = 3회 반복 탐색(①스키마/컬럼 축 ②로직/규칙 축 ③소비처/파이프라인 축) —
  ①은 초판 §3.2가 정확함을 재확인했고, 신규 발견은 전부 ②③에서 나왔다.

---

## 1. Context — 왜 하는가

`std_financials_v2`는 신형 파서(계층2 `report_lines`) 이전 세대의 산물이다. v3는 v2를
리팩터링한 게 아니라 **구조가 틀려서 새로 만든 것**이다 — 평면 fact(`fact_v2`)에는 표의
모양이 없어 금융업 이중섹션에서 "합산 대상"과 "제외 대상"을 원리적으로 구분할 수 없었다
(`docs/plans/rearchitecture_4layer.md:44-46`).

**v2 폐기는 새 방향이 아니라 이미 있던 로드맵의 재개다.**
`docs/plans/layer3_v3_bridge_swap_2026-07-25.md:6` — *"최종 목표 = v2 제거·v3 단독"*, §7에
6단계 폐기 로드맵이 있고 마지막 항목만 남았다. 2026-08-11에 *"v2는 지우지 말고 그대로 두자"*
(`rearchitecture_4layer.md:381`)로 미뤘던 이유는 **v3-native 품질게이트 미완성**이었는데,
이건 2026-08-18 `face_audit.source_version` 도입과 2026-08-21 전수 재감사로 해소됐다.

### 혼용이 실제로 낸 비용 (폐기를 서두를 근거)

| 시점 | 사고 | 규모 |
|---|---|---|
| 2026-08-11 | 뷰 v2 분기의 `fiscal_year<2015 OR NOT EXISTS`가 pre-2015 백필 후 무조건 중복 | **73,574 corp-period 2배 노출** |
| 2026-08-11 | v3 행이 v2 감사결과를 키 조인으로 빌려 가짜 `pass` | 22,935건 (9.5%) |
| 2026-08-18 | `source_version` 도입 후 뷰 조인이 v2/v3 감사행을 둘 다 매치 | 244,585키 중복 · 등급 오귀속 50,104 · **`fail_a` 게이트 우회 487** |

폐기의 부수 효과: `fact_v2` 55GB + `statement_source` 311MB + `std_financials_v2` 386MB +
`std_financials_calendar` 247MB ≈ **55.9GB 회수**.

---

## 2. 범위

### ★대원칙 — v2 값을 복사하지 않는다 (2026-08-22 사용자 확정)

**이 계획은 "v2 데이터의 이관"이 아니라 "v2가 하던 일을 v3가 자기 입력으로 다시 하게 만드는 것"이다.**
v2는 구세대 파서(`fact_v2` = XBRL 개념 기반)의 산물이고 v3는 신형 파서(`report_lines` = 원문 라벨
기반)의 산물이라, **두 값은 원리적으로 다를 수 있고 실제로 다르다**(§3.3 — 방향까지 섞여 있다).
v2 값을 그대로 옮기면 신형 파서로 갈아탄 의미가 없고, 구파서의 결함(comparative bleed 등)까지
같이 들어온다.

따라서 어떤 Phase도 `std_financials_v2`에서 값을 읽어 `std_financials_v3`에 쓰지 않는다.
v2는 **대조군**으로만 쓴다(P3 `version=3` vs `version=1` 대조, P6 전수 대조).
값이 v3에서 재현 안 되면 **"이식 실패"로 남겨 기록**하지, v2 값으로 메우지 않는다.

### 이번 계획에 포함 (사용자 확정, 2026-08-22)

| # | 항목 | Phase |
|---|---|---|
| 0 | **★신설** canonical 네임스페이스 정합성 조사 + 라벨 커버리지 실측 (§3.7) | **P0.5** |
| 1 | 실데이터 컬럼 3종 (`lease_liability`/`borrowings_proceeds`/`borrowings_repaid`) + `is_ifrs` 정정 | P1 |
| 2 | `is_stub` — **v3 PK 확장** | P2 |
| 3 | 이산분기(`is_discrete`) + 캘린더 계층 | P3 |
| 4 | 미이식 정규화 규칙 9종 | P4 |
| 5 | 조용한 실패(4,627 filing `done`인데 0행) 원인규명 → 계층2 재적재 | P5 |
| 6 | **★신설** `kgaap_gap` 파생행 — v3 등가물 유무 판정 (§3.8) | P0.5 조사 → 결정 |
| 7 | **★신설** `extended_financials`(long-format 확장계정) v3 등가물 (§3.9) | 별도 트랙 후보 |

### 명시적 제외

- **비교컬럼 합성(`comparative_fallback`) 자체는 이식하지 않는다.** 2026-07-30 "당기(col_index=0)만
  적재" 정책 유지(`fin2/extract/report_lines.py:1172-1176`). 대신 P5로 **원 보고서에서 직접 만든다** —
  재작성 값이 아니라 원문 값이라 더 낫다.
- v2/`fact_v2`/`statement_source`/`std_financials_calendar` **물리 삭제** — 별도 계획
- **std_v3 데일리 배선** — 별도 계획(`docs/plans/std_v3_daily_wiring_scoping_2026-08-22.md`).
  사용자 기확정: 배선 위치 = **데일리 내부 ④-6 신설**(④-4 직후 · ⑤ Gate B 직전)

---

## 3. 실측 인벤토리

### 3.1 규모

| 테이블 | 행 수 | 크기 |
|---|---:|---:|
| `fact_v2` | 74,106,510 | **55 GB** |
| `report_lines` | 61,427,076 | 30 GB |
| `std_financials_v2` | 505,047 | 386 MB |
| `std_financials_v3` | 303,859 | 307 MB |
| `std_financials_calendar` | 314,809 | 247 MB |

`std_financials_v2` 구성: version=1 당기 **243,071** · **is_discrete 259,843** · is_stub 323 ·
version=2(Phase C 잔재, 11개사) 1,810.

### 3.2 컬럼 차이

```
v2에만: version, is_ifrs, bs_rcept, is_rcept, cf_rcept, applied_rules, calculated_at,
        is_stub, is_discrete, value_lineage,
        lease_liability, borrowings_proceeds, borrowings_repaid
v3에만: source_rcepts, amended_cols, amend_chain, basis_fallback, conflicts,
        built_at, industry_lines
```

이미 동등물 있음 → 이식 불필요: `bs_rcept`류→`source_rcepts` · `calculated_at`→`built_at` ·
`value_lineage`→`conflicts`(축소판) · `version`→v3는 단일버전.

### 3.3 값 불일치 실측 (v2 ∩ v3 공통키 226,198행)

| 컬럼 | 불일치 | 추정 원인 |
|---|---:|---|
| `short_term_debt` | 41,286 | `rule_additive_debt` 미이식 (v3 작음 8,933 · v3 NULL 9,395 · v2 NULL 19,332) |
| `long_term_debt` | 16,600 | 동상 |
| `cash` | 14,761 | `rule_cash_with_deposits` 미이식 (금융사 예치금 미합산) |
| `interest_expense` | 5,915 | `_COL_PRIORITY` 미이식 (v3 작음 4,523 · 큼 1,392) |
| `rd_expense` | 4,022 | `rule_rd_fallback` 미이식 (주석 R&D 경로 없음) |

> ⚠ **방향이 섞여 있다 — "v2가 맞다"가 자동으로 성립하지 않는다.** P4는 원문대조를 선행한다.

### 3.4 `is_stub` — 조용한 병합 (확정 오염)

v3 PK에 `is_stub`이 없어 `_period_filings_chrono`(`fin2/layer3/combine.py:1342-1352`)가
**서로 무관한 두 원본 보고서를 "최초등록본 + 정정본"으로 병합**한다.

전수 실측 — v2에 정상행·stub행이 둘 다 있는 (기업,연도,FY,basis) 쌍:

```
충돌쌍 107 │ 총자산 stub유래 97 · 정상유래 3 · 혼합행 확정 11
```

**국제약품 2011 FY(별도)**:

| | period_end | total_assets | net_income |
|---|---|---:|---:|
| v2 정상 (2010.4~2011.3, 12개월) | 2011-03-31 | — | **43.1억** |
| v2 stub (2011.4~12, 9개월) | 2011-12-31 | **1,409억** | — |
| **v3 (병합)** | 2011-12-31 | **1,409억** ←stub | **43.1억** ←정상연도 |

재무상태표는 2011-12 말인데 손익은 9개월 앞선 기간 → ROA/ROE가 곧바로 틀린다.
같은 유형: 대구백화점 2017, 유유제약 2017(연결·별도), 강원에너지 2011, 삼성증권 2013.

**Gate B가 구조적으로 못 잡는다** — 감사기는 `source_rcepts`가 가리키는 그 한 보고서만
열어 대조하므로 `total_assets`는 일치해 `pass`가 난다. 다른 보고서에서 온 `net_income`이
섞인 건 검사 대상이 아니다. 게다가 v2 stub 323행은 **애초에 감사된 적이 없다**
(`scripts/gateb_audit.py:242`가 `"is_stub": False` 하드코딩, 조회도 `NOT is_stub`).

### 3.5 이산분기 — 최대 갭

| 기간 | 행 수 | 기업 수 | 연도 |
|---|---:|---:|---|
| Q1/Q2/Q3/Q4 | 68,017 / 66,324 / 62,715 / 62,787 | 2,537 | 1998–2027 |

생성: `fin2/standardize/quarterly.py::derive_quarters_corp` — `Q1=Q1누적`, `Q2=H1−Q1`,
`Q3=Q3누적−H1`, `Q4=FY−Q3누적` (`_QUARTER_SPEC`, `quarterly.py:46-51`).
flow는 차분, stock은 기말 스냅샷 복사, 한쪽이라도 NULL이면 NULL(보간 없음).

소비: `std_financials_calendar` → `calendar_financials` 뷰 → **앱의 유일한 분기 데이터원**
(`app/data/quarter_change.py`, `app/data/series.py:62`, `app/data/screen_window.py:186,204`,
`app/views/company_page.py:899-989` 분기표+TTM 멀티플, `chart_builder_page.py:280,360,447-480`).

**v3에 등가물 전무.**

### 3.6 조용한 실패 — P5 대상

비교컬럼 유래 행 중 뷰가 실제로 노출하는 것 16,822행 = **13,154기간**:

| 구분 | 기간 | v3 자체 생성 |
|---|---:|---|
| `report_lines` 이미 있음 | 92 | ✅ 즉시 |
| **자기 XML 원문 보유, `report_lines` 0행** | **3,986** | ⚠ 원인규명 필요 |
| 자기 filing 자체가 없음 | 9,095 | ❌ 구조적 불가 |
| PDF만 | ~73 | ❌ 별도 트랙 |

손실 모양(FY 4,996건): **앞머리 잘림 4,497(90%) · 중간 구멍 499(10%)**.
그리고 **중간 구멍 499건 중 458건(92%)이 XML 원문 보유** — 즉 차트에 구멍이 뚫리는
케이스는 거의 전부 "받아뒀는데 파싱 안 된 것"이다.

`report_line_load_progress` 상태: **`done` 4,627 filing(본문 0행·주석 0행) · `skip` 18(file missing)**.
연도는 1999~2003에 81% 집중.

> 표본 1건(티로보틱스 `20180402000209`) 확인: 503KB·`<TABLE>` 148개. 인코딩 함정을
> 의심했으나 **기각** — `parser/xml/dart_xml_parser.py:320-348`이 strict UTF-8 실패 시
> euc-kr로 올바르게 넘어간다. EUC-KR 해석 시 `재무상태표` 12회는 나오는데 `자산총계` 0회.
> **원인 미확정.**

### 3.7 ★canonical 네임스페이스가 둘로 갈라져 있다 (2026-08-22 발견, 이 계획의 전제를 바꿈)

**초판의 "규칙만 이식하면 된다"는 전제가 5개 항목 중 2개에서 성립하지 않는다.**

v2와 v3는 canonical 이름 집합 자체가 다르다:

| | v2 (Track A) | v3 (계층2) |
|---|---|---|
| 입력 | `fact_v2` = XBRL 개념명 | `report_lines` = 원문 한글 라벨 |
| 매핑 | `fin2/taxonomy/concept_map.py` | `account_maps/*.py` (`parser/common/account_mapper.py`) |
| 리스부채 | `bs.lease_current` + `bs.lease_noncurrent` (**분리**) | `bs.lease_liability` (**통합**, `bs_accounts.py:258`) |
| 차입 세부 | `bs.current_lt_debt`·`current_bonds_plain`·`current_bonds_conv`·`bs.bonds` | `bs.current_portion_lt_debt`·`bs.current_bond`·`bs.bond` (**이름 다름**) |
| CF 차입 | `cf.borrow_proceeds_st` + `_lt` (**분리**) | `cf.borrowings_proceeds`/`_repaid` (**통합**, `cf_accounts.py:229`) |

**두 이름 집합은 서로 전혀 겹치지 않는다**(grep 상호검증, 2026-08-22):
`bs.lease_current` 등 v2 규칙의 입력 canonical → `account_maps/` 에 **0건**.
`bs.lease_liability`·`cf.borrowings_proceeds`·`bs.bond` 등 v3 카탈로그 이름 → `rules.py`·
`concept_map.py` 에 **0건**.

**따라서 v3에 이 컬럼이 없는 건 "데이터가 없어서"가 아니다.** 라벨은 이미 카탈로그에 있고
(`"리스부채","금융리스부채","유동성리스부채"`) 파싱돼 `report_lines`에 들어와 있는데,
그 canonical을 **소비하는 컬럼이 `DIRECT_MAP`에 없어서 버려지는 것**이다.
⟹ v3 자체 생성은 **가능**하다. 다만 필요한 작업이 "규칙 이식"이 아니다.

#### 함정 — 통합 canonical에 두 행이 들어오면 값이 사라진다

v2가 리스를 유동/비유동으로 굳이 쪼갠 이유가 `rules.py:78-79`에 적혀 있다:
> *"서로 다른 항목이라 한 canonical 로 collapse 하면 값충돌(보류)이므로 별도 canonical 로 두고 합산."*

v3 카탈로그의 **face BS 쪽**은 정확히 그 collapse를 하고 있다(유동성리스부채 →
`bs.lease_liability`, `bs_accounts.py:258-262`). 그리고 v3 `_resolve()`는 한 canonical에 값이
다른 행이 둘 오면 **충돌로 HOLD → NULL**이다. 가산 예외(`ADDITIVE_CANON`)는 **D&A 계열
전용**이며 `combine.py:1728`에 "이 가드는 D&A 전용"이라고 명시돼 있다.

#### ★정정(같은 날 3차 탐색) — 리스는 v3 카탈로그에 **이미 분리돼 있다**

`account_maps/note_accounts.py:49-54`:
```
"note.lease_liability_current":    ["유동리스부채"],
"note.lease_liability_noncurrent": ["비유동리스부채"],
```
**소비처 grep 결과 0건** — 정의만 돼 있고 아무도 안 읽는다. `AccountMapper._build_index()`가
`_exact_by_prefix`로 섹션(bs/is/cf/note)을 분리 보관하므로 같은 "유동리스부채" 라벨이
BS 문맥에선 `bs.lease_liability`, 주석 문맥에선 `note.lease_liability_current`로 **충돌 없이**
갈린다.

⟹ 리스에는 **두 가지 선택지**가 있고, 카탈로그 분해가 유일한 길이 아니다:
- **(a) 주석 경로** — `note.lease_liability_*`를 `note_da.py`와 같은 방식으로 태운다.
  기존 face BS 매핑을 **건드리지 않으므로 위험이 낮다**. 단 주석 커버리지에 의존.
- **(b) face BS 카탈로그 분해** — `bs.lease_liability`를 유동/비유동으로 쪼갠다.
  커버리지는 넓지만 **이미 검증된 컬럼까지 영향권**.

CF 차입(`cf.borrowings_proceeds` 통합)은 아직 이런 대안이 확인되지 않았다 — P0.5에서 확인한다.

#### 항목별 재판정

| 항목 | v3 자체 생성 | 실제 필요한 작업 | 위험 |
|---|---|---|---|
| `lease_liability` | ✅ | 규칙 이식 **아님** — 카탈로그 분해 선행 | **중** |
| `borrowings_proceeds`/`repaid` | ✅ | 동상 | **중** |
| `rule_additive_debt` | ✅ | 카탈로그 이름 정합(`current_portion_lt_debt`↔`current_lt_debt`) | **중** |
| `rule_cash_with_deposits` | ✅ | **그대로 포팅 가능** — `bs.deposits`·`bs.cash_deposits_combined`가 양쪽에 존재 | 저 |
| `_COL_PRIORITY`(이자비용) | ✅ | **그대로 포팅 가능** — 양쪽에 존재. **현존 버그 수정임**(아래) | 저 |
| `is_ifrs` | ⚠️ **불확실** | v2 근거 = `fact_v2.source_format='xbrl_acode'`, v3는 `fact_v2`를 원리적으로 안 읽음 | — |
| filing 자체 없음 9,095 기간 | ❌ **원리적 불가** | v2 삭제 시 잃는 것으로 명시 | — |

★ `_COL_PRIORITY`는 이식이 아니라 **실버그 수정**이다. `is.interest_expense`와
`is.finance_cost`가 둘 다 `interest_expense`로 매핑되는데(`rules.py:32`), v3의 직접매핑
루프(`combine.py:2301-2305`)엔 우선순위가 없어 **dict 순서에 따라 금융원가(상위개념·더 큼)가
이자비용을 조용히 덮는다**. 카탈로그 변경이 필요 없으므로 P1으로 승격한다.

### 3.8 ★`kgaap_gap` 파생행 — v2-only 범주 누락 (2026-08-22 2차 탐색)

`fin2/standardize/build.py:433 standardize_kgaap_gap_corp()` — **§3.6의 v2-only 키 분류
(비교컬럼 유래 + filing 없음)에 안 잡힌 제3의 범주**다.

K-GAAP(pre-IFRS) 자기보고서를 `statement_source`에서 읽어 **기존 std_v2 행이 없는 키만**
채우는 백필 경로. 파생행 표식 = `applied_rules @> ['kgaap_gap']` · `is_ifrs=False` · DQ≥2.
호출처는 `scripts/archive/backfill/fin2_kgaap_gap.py` 등 **아카이브된 백필 스크립트뿐**
(데일리 아님) — 즉 과거에 한 번 만들어져 눌러앉은 행이다. 대상은 "pre-2011 FY 보고서가
있으나 std_v2 행이 없던 480기업".

- [ ] **P0.5에서 실측**: `applied_rules @> '["kgaap_gap"]'` 행수·기업수·연도분포, 그중
      v3가 이미 커버한 키가 몇 %인가(pre-2015 2차 패스로 112,849행이 이미 채워졌으므로
      상당수는 이미 해소됐을 가능성이 높다 — **측정 전 단정 금지**)
- [ ] 잔여가 있으면: v3가 `report_lines`로 자체 생성 가능한지(=원문 XML 보유 여부) 판정 →
      P5와 같은 성격의 작업으로 편입할지 결정

### 3.9 ★`extended_financials` — v3에 등가물 없음 (2026-08-22 3차 탐색)

`app/registry/extended.py` — **`DIRECT_MAP` wide 컬럼으로 승격되지 않은 canonical 계정 전체**를
long-format으로 노출하는 카탈로그. 뷰 `extended_financials`(마이그레이션
`2026_07_extended_financials_view`) = **`fact_v2` × `statement_source`** 조인이고,
**차트빌더가 이걸 소비**한다(`source="ext_column"`).

v3에 등가물이 없다. v3의 `industry_lines`는 **매출 구성요소 전용**이라 대체물이 아니다.
⟹ `fact_v2`(55GB) 폐기의 실질 차단 요인이며, 규모상 이 계획에 넣지 말고 **별도 트랙**으로
분리하는 것이 맞다(=`report_lines` 기반 long 뷰 신설). P0.5에서 노출 지표 수만 실측한다.

### 3.10 v2 체인은 휴면이 아니다 — 데일리가 매일 `fact_v2`에 쓴다 (2026-08-22 3차 탐색)

`scripts/collect_new.py:118 _sync_cf_da()` (④-2)가 매일 다음을 실행한다:
`collector/cf_da_sync.py` → `collector/expense_nature_sync.py` → 둘 다 **`fact_v2` upsert 후
`standardize_corp`(v2) → `derive_quarters_corp` → `calendarize_corp` 재전파**.

**데이터 자체는 v3가 이미 더 넓게 커버한다** — v3 `fin2/layer3/note_da.py`는
`note_topics.DA_SOURCE_BROAD`(=`EXPENSE_BY_NATURE` 1순위 → `CASH_FLOW` → `SGA`) +
`DA_SOURCE_COMPONENT`(PPE/무형/투자부동산/리스 증감표)를 읽으므로, v2의 cf_da·expense_nature
2경로를 **포함하는 상위집합**이다. ⟹ 이식할 로직은 없다.

문제는 **배관**이다: v2를 지우려면 이 데일리 단계를 걷어내야 하는데, 그러면 `fact_v2` 갱신도
같이 멈춘다(→ §3.9 `extended_financials`가 stale). 순서 의존이 있으므로 **폐기 계획에서
반드시 §3.9와 함께 다룰 것**.

**★2026-08-30 후속(std_v3_daily_wiring_plan_2026-08-30.md Phase 2)** — 데일리 표준화
소비계층을 std_v2→v3로 전환하면서(`process_corp`의 `stages`를 `("extract","reconcile")`
로 축소, `standardize`/`quarterly`/`calendar` 제외) 이 잔여 경로를 실측으로 재확인했다:
- 브랜드뉴 기간(오늘 처음 생긴 fy/period)은 애초에 std_v2 행이 없어 `_sync_cf_da`의
  SELECT(`std_financials_v2 WHERE depreciation IS NULL`) 대상이 되지 않는다 →
  **신규 std_v2 쓰기는 실제로 사라졌다**(표본 corp으로 검증: 실행 전후 행수 무변동).
- 하지만 Phase 2 이전에 이미 만들어진 std_v2 행 중 depreciation NULL인 것은, 그 corp이
  이후 다른 이유로 데일리 `ok_corps`에 다시 잡힐 때마다 계속 재표준화된다 — 이 문단이
  예견한 그대로다. **위 결론("이식할 로직은 없다, 걷어내려면 §3.9와 함께")에 따라 이번엔
  건드리지 않았다** — `fact_v2`/`extended_financials`를 §8에서 함께 이식할 때 처리.

### 3.11 ★P0.5 실측 결과 (2026-08-22, DB 복구 후 실행)

> 2차 개정 시점엔 로컬 postgres가 죽어 있어 전부 미측정이었다. 복구 후 실측한 결과다.
> **§3.7의 가설이 전부 실증됐고, §3.8은 소멸했다.**

#### (1) `kgaap_gap` — **0행. 범주 소멸**

```sql
SELECT count(*) FROM std_financials_v2 WHERE applied_rules @> '["kgaap_gap"]';  -- 0
```
마커 상수는 맞다(`build.py:427 _KGAAP_MARKER = "kgaap_gap"`). 이후 전수 재표준화 과정에서
사라진 것으로 보인다. ⟹ **§3.8 트랙 종료, 미결 결정 ⑦ 해소(조치 불필요).**

#### (2) `applied_rules` 분포 — P1/P4 대상 규모 확정

| 규칙 마커 | 행 수 | 함의 |
|---|---:|---|
| `opinc_kifrs` | 421,068 | 미결 ②(`applied_rules` 컬럼)의 실제 규모 |
| `map_direct_proxy:interest_expense=is.finance_cost` | **187,478** | v2가 금융원가를 **대용치로 명시 채택**한 행 |
| `additive_debt` | 169,314 | P4 최대 항목 |
| `additive_lease` | **20,761** | P1A 대상 |
| `additive_borrowings` | **19,502** | P1A 대상 |
| `comparative_fallback` | 29,270 | 이식 제외 대상(§2) |
| `cash_from_combined` + `cash_plus_deposits` | 2,292 + 1,007 | **P1C 대상 — 작다** |
| `revenue_from_cogs_gp` | 2,245 | P4 |
| `revenue_fallback` | 137 | 어차피 이식 불필요 판정 |
| `rd_fallback` | **35** | ★거의 무의미 — P4에서 **"이식 불필요"로 기각 권장** |

#### (3) 라벨 커버리지 — v3 자체 생성 **가능** 실증

v2가 `additive_lease`로 값을 만든 키 200개 무작위 표본:
- **196/200 (98%)** 이 `report_lines` **BS 본문에 `리스부채` 라벨 보유** ⟹ §3.7의 "데이터는
  이미 있다"가 실증됐다.
- 주석(`note_lines`)에도 200/200 라벨은 있으나, `note.lease_liability_*` alias가 요구하는
  **정확 라벨(`유동리스부채`/`비유동리스부채`)은 54/200 = 27%뿐**.

⟹ **§3.7이 제시한 (a) 주석 경로는 커버리지 27%로 약하다 — 사실상 기각.**

#### (4) ★붕괴 메커니즘 실측 — AccountMapper 직접 호출

| 라벨 | → canonical | stage |
|---|---|---|
| `유동리스부채` | `bs.lease_liability` | exact 1.0 |
| `비유동리스부채` | `bs.lease_liability` | **fuzzy 0.977** |
| `유동성리스부채`/`금융리스부채`/`리스부채` | `bs.lease_liability` | exact 1.0 |
| `단기차입금의증가` | `cf.borrowings_proceeds` | exact 1.0 |
| `장기차입금의증가` | `cf.borrowings_proceeds` | exact 1.0 |
| `리스부채(유동)` / `리스부채(비유동)` | **`unknown.리스부채_유동_`** | **unknown 0.0** |

유동과 비유동이 **같은 canonical로 붕괴**한다(비유동은 alias에도 없어 **퍼지가 유동 쪽으로
끌어간다**). 부수 발견: **괄호 표기는 매핑 자체가 실패**(정규화가 괄호를 `_`로 바꿈) —
관측 표본에서 `리스부채(유동)` 42건·`리스부채(비유동)` 42건.

#### (5) 충돌 = 값 소실 실측 (R16이 이미 현실)

| 대상 | 표본 | 서로 다른 값 2개 이상 = 충돌 HOLD | 비율 |
|---|---:|---:|---:|
| 리스부채 (BS, col0) | 309 | **301** | **97.4%** |
| 차입금 유입 (CF, col0) | 300 | **245** | **81.7%** |

⟹ **R16은 "이식하면 생길 위험"이 아니라 이미 벌어지고 있는 손실**이다. 지금 v3는 이
canonical들을 대부분 HOLD하고 있고, 컬럼이 없으니 아무도 눈치채지 못했다.

★**게다가 이 충돌은 `conflicts` 컬럼에도 안 남는다** — `combine.py:1770`이 `CONSUMED_CANON`에
있는 canonical만 기록하는데 `bs.lease_liability`·`cf.borrowings_proceeds`는 `rules.py`에
아예 없어서 거기 없다. **조용한 손실**(메모리 `layer2-silent-loss-patterns` 계열).

#### (6) P1C 규모

`이자비용`과 `금융원가`가 **둘 다 있는** 키 = 400 표본 중 **15건(3.8%)**(fy2015+).
`_COL_PRIORITY` 부재가 실제로 오선택할 수 있는 모집단이다(v3 303,859행 기준 대략 1만 행대).
나머지는 한쪽만 있어 순서와 무관하다.

#### (7) `extended_financials` 규모 (§3.9)

`SELECT count(DISTINCT canonical_account)` = **152종**. 단 이 쿼리 자체가 **114초** 걸렸다
(`fact_v2` 74M 전수 스캔) — 뷰가 비싸다는 것도 별도 트랙에서 고려할 것.

#### 미측정으로 남은 것 (2026-08-22 P0.6로 전부 해소 — §3.12 참고)

- ~~§3.6 v2-only 키 재분류(비교컬럼/filing없음) 재확인~~ → §3.12 T6
- ~~`rule_additive_debt`(169,314행)의 카탈로그 이름 불일치 실측~~ → §3.12 T5

### 3.12 ★P0.6 조사 결과 (2026-08-22, T1~T7 전부 완료)

전체 실행 로그·SQL·재현 스크립트는
[`std_v2_catalog_split_p0_6_todo_2026-08-22.md`](std_v2_catalog_split_p0_6_todo_2026-08-22.md)에
있다. 여기는 결론만.

**T0(선결 확인, 재검토로 결론 번복)**: `account_maps`(`AccountMapper`)는 v2/v3 공통 소스인
`fact_v2` 추출단에서도 쓰이지만, **오염은 없다**. `fin2/extract/text.py::_canonical_of()`가
fuzzy 매치에 canonical을 아예 안 줘서(NULL 저장) v2는 애초에 collapse된 canonical(`bs.lease_
liability`·`cf.borrowings_*`)의 fuzzy 후보(예: `비유동리스부채`)를 못 받는다 — v3의
`combine.py`만 필터 없이 받아서 진짜 충돌을 겪는다(아래 conflict 표). 카탈로그 분해는 v2엔
**순이득**(지금 못 받던 값을 앞으로 받게 됨), 과거 `fact_v2`(재추출 전까지 불변)도 안 흔들림
→ **오버레이 설계 불필요, 카탈로그 직접 분해(원안)로 진행.**

**T2/T3(분해 안전성·효과)**: diff 798라벨 중 예상 밖 변경 2건(개선 방향, 위험 아님). 충돌률
실측 — `bs.lease_liability`(collapse) 14.6%, `cf.borrowings_proceeds` 42.1%,
`cf.borrowings_repaid` 49.3% vs 이미 분리된 `bs.lease_current`/`_noncurrent`(XBRL) ~0%.
**분해 자체가 충돌을 없앤다는 걸 직접 증명.**

**T4(괄호 결함, §7-⑤에서 언급했던 가설 기각)**: `normalize_account_name`에 괄호를 `_`로
바꾸는 규칙은 **존재하지 않는다**(코드 확인, 가설 틀림). 전수 기준 미매핑 63.29%는 CF
간접법 운전자본조정·EPS 라벨이라는 **리스/차입과 무관한 별개의 기존 공백** — P1A와 분리.

**T5(additive_debt 169,314행)**: lease/borrow와 **반대 방향** — 같은 개념이 추출경로별로
이미 두 canonical로 갈라져 있다(`bs.current_lt_debt`↔`bs.current_portion_lt_debt` 등).
**분해가 아니라 통합(alias 정합)**으로 푼다 → P4 범위, 이번 착수와 무관.

**T6(§3.6 재확인)**: `standard_financials` 뷰 정의를 역산해 원 쿼리를 정확히 재현(16,822행
일치). 재분류 결과 원판과 거의 동일 — report_lines 있음 92→88·XML만 3,986·filing없음
9,095·PDF만 73. **최종 기준선으로 확정.**

**T7(★신규 발견 — P1C 재정의)**: `combine.py`가 `rules.py`의 `_COL_PRIORITY`(2026-07-17
v2 버그수정)를 **이식받은 적이 없다** — `DIRECT_MAP`만 import하고 우선순위 로직은 안 가져와,
`is.interest_expense`/`is.finance_cost` 후보가 둘 다 있으면 dict 순회 순서로 아무거나
덮어쓴다. 실측(정확 카운트, 위 §3.11-(6)의 400표본 추정치를 대체): 둘 다 후보인 키 2,894 ·
값이 다른 키 2,198 · **오선택(finance_cost로 과대계상) 182건(8.3%)** · 정선택 1,997건.
수정은 `_COL_PRIORITY` 패턴을 `combine.py`로 포팅하는 것 — 간단·저위험.

**확정된 alias 목록(P1A 입력, `SPLIT_DRAFT`)**:
```python
SPLIT_DRAFT = {
    "bs.lease_current":    ["유동리스부채", "유동성리스부채", "유동 리스부채"],
    "bs.lease_noncurrent": ["비유동리스부채", "비유동 리스부채", "비유동성리스부채",
                            "비유동금융리스부채"],
    "bs.lease_liability":  ["리스부채", "금융리스부채"],          # 총계는 그대로
    "cf.borrow_proceeds_st": ["단기차입금의증가", "단기차입금의차입"],
    "cf.borrow_proceeds_lt": ["장기차입금의증가", "장기차입금의차입"],
    "cf.borrow_repaid_st":   ["단기차입금의상환", "단기차입금의감소"],
    "cf.borrow_repaid_lt":   ["장기차입금의상환"],
    "cf.borrowings_proceeds": ["차입금의증가", "차입금의차입", "차입금차입"],  # 총계는 그대로
    "cf.borrowings_repaid":   ["차입금의상환", "차입금상환"],                 # 총계는 그대로
}
```
(출처: `scripts/diag_canonical_collapse_scan.py`. T2 labels로 확인된 "분해안에 없는 변형"
— `기타금융부채의증가/감소`·`유동성장기부채(의)상환`·`유동성장기차입금(의)상환` 등 —
은 st/lt 귀속이 애매해 이 목록에 **의도적으로 미포함**, P1A 구현 시 사용자 결정 필요.)

**착수 범위 재결정(T9, 권고안 — 사용자 확정 대기)**: ①lease/borrow 카탈로그 분해(P1A)
②`combine.py` interest_expense 우선순위 포팅(신규, P1C 재정의) — 이 둘은 조사로 안전성·
근거가 갖춰졌다. T4(괄호)·T5(debt 이름)는 각각 별도 트랙/해당 Phase로 이연 권고. 최종
착수 범위는 사용자 결정 필요.

---

## 4. Phase 구성

각 Phase는 **앞 Phase 검증 통과 후** 진행. 병렬 금지.

```
P0.5 정합성 조사(읽기전용)  →  P1C 저위험(카탈로그 무변경)  →  P1A/B 이식(카탈로그 변경)
                                                                        ↓
                              P3 이산분기+캘린더  ←  P2 is_stub PK 확장
                                      ↓
P6 동등성 전수검증  ←  P5 조용한실패 규명+재적재  ←  P4 규칙 (9종 − P1로 이동한 2종)
```

P4를 P3 뒤에 두는 이유: 규칙 이식이 v3 값을 대규모로 바꾸므로, 이산분기(v3를 입력으로
차분)가 **먼저 안정화**돼야 재작업이 없다.

**P0.5를 맨 앞에 둔 이유(2026-08-22 추가)**: §3.7에서 canonical 네임스페이스가 갈라져
있음이 드러나, "규칙을 붙이면 값이 나온다"는 전제 자체가 미검증이다. 실측 없이 P1을
열면 **규칙을 붙였는데 무동작**이거나(이름 불일치) **기존 값이 NULL로 바뀌는**(충돌 HOLD)
두 가지 실패 모드가 있다.

---

## 5. TODO

### Phase 0.5 — ★canonical 정합성 조사 (읽기전용, P1 착수 전 필수)

> 2026-08-22 신설. §3.7~3.9의 발견 때문에 생겼다.
> **★2026-08-22 실행 완료 — 결과는 §3.11.** 남은 것은 미결 결정 ⑤ 승인뿐.

- [x] **라벨 커버리지 실측** — 5개 대상별로 해당 라벨이 `report_lines`에 실제 있는가.
      **결과: lease 98%(196/200) — "v3 자체 생성 가능"이 실증됨**(§3.11-3)
- [x] **이름 대조표 작성**(리스/CF차입 계열) — `concept_map.py`(v2) ↔ `account_maps/*.py`(v3).
      **결과: 유동/비유동이 같은 canonical로 붕괴 확인**(§3.11-4).
      ★나머지 계열 전수 대조는 **P4 착수 시로 이월**
- [x] **충돌 위험 사전측정** — 통합 canonical에 값이 다른 행이 2개 이상인 케이스.
      **결과: lease 97.4%(301/309) · borrow 81.7%(245/300) — R16은 위험이 아니라 이미
      벌어지고 있는 손실**(§3.11-5)
- [x] **`kgaap_gap` 실측**(§3.8) — **결과: 0행, 범주 소멸.** 미결 결정 ⑦ 해소
- [x] **`extended_financials` 실측**(§3.9) — **결과: 152종**(뷰 자체가 114초)
- [x] 결과를 §3.11에 반영 완료. **P1 범위 확정은 미결 결정 ⑤ 승인 후**

### Phase 1 — 이식 (★2026-08-22 재분류: "저위험·값 불변"이 아니다)

> 초판은 P1 전체를 "저위험 이식(기존 v3 값 불변)"으로 분류했으나 §3.7 발견으로 뒤집혔다.
> **1A는 카탈로그(account_maps) 변경을 수반하므로 저위험이 아니다.** 진짜 저위험인 1C를
> 분리해 먼저 처리한다.

**1C. 진짜 저위험 — 카탈로그 변경 없음 (★먼저)**

- [ ] **`_COL_PRIORITY` 이식 = 현존 버그 수정**. `combine.py:2301-2305`의 직접매핑 루프에
      우선순위가 없어 `is.finance_cost`(금융원가·상위개념)가 `is.interest_expense`를 dict
      순서에 따라 조용히 덮는다. `rules.py:120-121`의 `_COL_PRIORITY`를 그대로 적용하고
      대용치 채택 시 표시를 남긴다
- [ ] **`rule_cash_with_deposits` 이식** — `bs.deposits`·`bs.cash_deposits_combined`가
      `account_maps/bs_accounts.py:46,51`에 **이미 존재**하므로 규칙만 태우면 된다
- [ ] 위 둘의 영향 범위 사전측정(변경 행수) → 표적 백필 → Gate B scoped 재감사

**1A. 실데이터 컬럼 3종 (★카탈로그 분해 선행 — 위험 중)**

- [ ] **선행: 리스 경로 결정** — (a)주석 경로(`note.lease_liability_current`/`_noncurrent`,
      **이미 카탈로그에 있고 소비처 0건**) vs (b)face BS 카탈로그 분해 vs (c)`ADDITIVE_CANON`
      편입(가장 작은 변경이나 `combine.py:1728`이 "D&A 전용"이라 경고).
      **P0.5의 커버리지·충돌 실측 후 결정** → **미결 결정 ⑤(§7-5)**
- [ ] **선행: CF 차입 경로 확인** — `cf.borrowings_proceeds`/`_repaid`에 리스 같은 분리
      대안(주석 경로)이 있는지 P0.5에서 확인. 없으면 (b)/(c) 중 택일
- [ ] `collector/models.py` `StdFinancialV3`에 `lease_liability`/`borrowings_proceeds`/`borrowings_repaid` 추가 (v2 정의 `:797-800` 참조)
- [ ] `collector/db.py` 마이그레이션 신설 (기존 v2용 `:464-473` 패턴 재사용, **기존 마이그레이션 수정 금지** — 신규 키)
- [ ] `fin2/layer3/build.py:21-34` **`_VALUE_COLS`에 3개 추가** ★ 이 목록에 없으면 combine이 값을 내도 저장 안 됨(`:32` 경고)
- [ ] `fin2/layer3/combine.py:2389-2400` `_apply_enrichment`에 `rule_additive_lease`·`rule_additive_borrowings` 추가
      — ★단 규칙이 참조하는 `_LEASE_PARTS`/`_BORROW_*_PARTS`는 **v2 이름**이므로, 위 분해
      결정에 맞춰 **규칙 쪽 상수도 v3 카탈로그 이름으로 고쳐야 한다**(그대로 붙이면 무동작)
- [ ] `combine.py:2347-2350` 주석 갱신 — "debt/lease additive rules are NOT run here" 서술이 더 이상 사실이 아님
- [ ] 백필: `build_std_v3.py --corp <대상> --year-min 1999`
- [ ] ★**값 불변 아님** — 기존 검증된 컬럼(`short_term_debt` 등)이 같이 움직일 수 있으므로
      스냅샷 대비 전이표 필수(§6.3)

**1B. `is_ifrs` 정정**

현재 뷰의 v3 분기가 `true AS is_ifrs`로 하드코딩(`collector/db.py:930` 부근) → v3가 1999년까지
백필돼 **pre-2011 K-GAAP 66,705행 / 1,392개사가 IFRS로 오표기**.

- [ ] **선행 조사**: v3가 근거 기반으로 IFRS를 판정할 수단이 있는가?
      v2는 `_derive_is_ifrs`(`fin2/standardize/build.py:398-423`)가 Track A(`xbrl_acode`) source
      유무로 판정하는데, v3는 `fact_v2`를 안 읽는다. 대안 후보 = `download_tasks.file_type`
      / `report_lines.unit_source`·`source_ref` / `filings` 메타. **연도 추론은 금지**
      (v2가 명시적으로 폐지한 방식 — "없으면 None")
- [ ] `StdFinancialV3.is_ifrs` 컬럼 + 마이그레이션
- [ ] 판정 로직 구현 + 뷰의 `true AS is_ifrs` → `v3.is_ifrs` 교체
- [ ] 소비처 확인: `analyzer/display/table_view.py:120`("K-IFRS / K-GAAP" 표기)

### Phase 2 — `is_stub` v3 PK 확장

- [ ] `collector/models.py` `StdFinancialV3`에 `is_stub` 추가 + PK를 `(corp_code, fiscal_year, fiscal_period, statement_type, is_stub)`로 확장
- [ ] `collector/db.py` 마이그레이션 — PK drop→recreate (v2용 `:110-122` 패턴)
- [ ] `fin2/layer3/build.py::_periods()` — `report_lines`엔 `is_stub`이 **없다**. `filings`를 조인해 `(fy, period, is_stub)`을 반환하도록 확장
- [ ] `fin2/layer3/combine.py::_period_filings`(`:1332`)·`_period_filings_chrono`(`:1342`)에 `is_stub` 인자 추가 → `AND COALESCE(f.is_stub,false)=:st`
- [ ] `build_corp` — `(fy, period, is_stub)` 순회, DELETE 조건에도 `is_stub` 포함
- [ ] `scripts/gateb_audit.py:140-144` v3 조회에 `is_stub` 반영 · `:242`의 `"is_stub": False` 하드코딩 제거 → 행의 실제 값 사용
- [ ] `collector/db.py` `standard_financials` 뷰 v3 분기 — `is_stub` 투영 + `face_audit` 조인 조건을 `NOT COALESCE(fa.is_stub,false)`에서 `fa.is_stub = v3.is_stub`로
- [ ] ✅ **`face_audit` PK는 이미 `is_stub` 포함** — 마이그레이션 불필요
- [ ] ★ **스테일 행 청소**: `build_corp`는 데이터가 안 나오면 DELETE 전에 `continue`한다(`build.py:110-117`).
      PK 확장 전에 만들어진 **`is_stub` 없는 단일행**이 그대로 남으므로, 백필 전에 대상 85개사의
      기존 v3 행을 명시적으로 삭제한 뒤 재빌드
- [ ] 백필: 85개사 재빌드 + `gateb_audit.py --recheck` 재감사

### Phase 3 — 이산분기 + 캘린더

> **미결 결정 ①(§7-1)**: 저장 위치. 아래는 권장안 = **별도 테이블**.
> 근거: 이산분기는 Gate B 감사 대상이 아니고(v2도 아님) 뷰가 어차피 제외하므로, v3 본표
> PK에 `is_discrete`를 넣으면 모든 소비자에 `NOT is_discrete` 필터를 다시 깔아야 한다.
> `std_financials_calendar`가 이미 별도 테이블인 선례도 있다.

- [ ] 신규 테이블 `std_financials_v3_quarterly` — PK `(corp_code, fiscal_year, fiscal_period, statement_type, is_stub)`, 값 컬럼은 v3와 동일
- [ ] `fin2/layer3/quarterly_v3.py` 신설 — `fin2/standardize/quarterly.py`의 `_QUARTER_SPEC`(`:46-51`)·`_FLOW_COLS`(`:32-35`)·`_STOCK_COLS`(`:37-39`)·`_build_discrete`(`:73-112`) **로직 그대로 재사용, 입력만 std_v3**
  - 컬럼 목록은 P1에서 늘어난 3종을 포함해야 함
- [ ] `fin2/standardize/calendar.py::_load_discrete`(`:49-54`)를 v3 소스로 전환
  - ★ **`version` 컬럼을 안전 swap에 재사용**: v3 유래분을 `version=3`으로 병행 적재 → v1과 값 대조 → 검증 통과 후 `calendar_financials` 뷰(`collector/db.py:206-208`)를 `version=3`으로 교체
- [ ] `scripts/build_std_v3_quarterly.py` 드라이버 신설 (`build_std_v3.py` 패턴 — `--corp`/`--shard`/`--year-min`)
- [ ] 전수 빌드 + v1 대조

### Phase 4 — 정규화 규칙 이식 (최고 위험)

v2는 `RULES` 전체(`fin2/standardize/rules.py:369-386`)를 돌리지만 v3는 **5개만** 돌린다
(`combine.py:2389-2400`: capex/fcf/net_debt/da/ebitda). 별도로 `rule_net_income_fill`(`combine.py:2291-2299`)과
`rule_controlling_ni_fill`(`build.py:118-126`)이 인라인 이식돼 있다.

2026-08-22 재분류 — 카탈로그 변경 필요 여부로 갈랐다(§3.7):

| 규칙 | rules.py | 처리 | 카탈로그 변경 |
|---|---|---|---|
| `rule_additive_lease` | `:294-299` | **P1A** | **필요**(v2 이름 `bs.lease_current/_noncurrent` 부재) |
| `rule_additive_borrowings` | `:302-311` | **P1A** | **필요**(`cf.borrow_proceeds_st/_lt` 부재) |
| `_COL_PRIORITY`(interest_expense) | `:115-149` | **→P1C 승격** | 불필요 — **현존 버그 수정** |
| `rule_cash_with_deposits` | `:163-194` | **→P1C 승격** | 불필요 — canonical 양쪽 존재 |
| `rule_additive_debt` | `:267-291` | P4 | **필요**(`bs.current_lt_debt`↔`bs.current_portion_lt_debt` 등 이름 불일치) |
| `rule_revenue_from_cogs_gp` | `:258-264` | P4 | 불필요(`ctx.col`만 읽음) |
| `rule_rd_fallback` | `:334-341` | P4 | **확인 필요** — `note.rd_expense`는 v2에서 `fin2/extract/rd_note.py`가 만든 **합성 fact**다. v3는 `note_lines`에서 같은 표를 직접 읽어야 하므로 **경로 신설**이지 규칙 이식이 아니다 |
| `rule_mark_opinc_kifrs` | `:152-160` | P4 — `applied_rules` 컬럼 선행 필요 | 불필요 |
| `rule_revenue_fallback` | `:314-331` | **이식 불필요** — v3의 `industry_profiles.py::apply_revenue_profile`(`:215-230`)이 더 나은 대체물 | — |

각 규칙마다:

- [ ] **원문대조 선행** — 불일치 표본 5~10건을 원문과 대조해 "v2가 맞나 v3가 맞나" 확정.
      §3.3의 방향 혼재를 보면 무조건 v2가 정답은 아니다
- [ ] 이식 (또는 "이식 불필요" 판정 + 근거 기록)
- [ ] `fin2/tests/`에 회귀 테스트 추가
- [ ] 표적 백필 + Gate B scoped 재감사
- [ ] `docs/PARSING_RULES.md`에 R번호로 등재

★ `_COL_PRIORITY` 주의: v3는 v2와 **같은 `DIRECT_MAP`을 import**하는데(`combine.py:33`),
`is.interest_expense`와 `is.finance_cost`가 **둘 다** `interest_expense`로 매핑된다(`rules.py:32`).
v3의 `for canon, value in confirmed.items()` 루프(`combine.py:2301-2305`)에는 우선순위가 없어
dict 순서에 따라 금융원가(상위개념·더 큼)가 이자비용을 조용히 덮을 수 있다.

- [ ] `applied_rules` 컬럼을 v3에 추가할지 결정 → **미결 결정 ②(§7-2)**

### Phase 5 — 조용한 실패 규명 + 계층2 재적재

- [ ] 대상 확정: `report_line_load_progress`에서 `status='done' AND n_lines=0` + `report_lines` 0행인 filing 전수 추출 (관측 4,627건)
- [ ] **패턴 분류** — 표본 20~30건을 연도대(1999-2003 / 2004-2010 / 2011+)별로 열어 원인 분류.
      확인된 것: 인코딩은 원인이 **아님**(§3.6). 후보 = 구서식 표 구조 · 재무제표가 별도 첨부 · 섹션 표제 미인식
- [ ] 분류별 파서 수정 또는 **"구조적 불가" 판정 + 근거 문서화**
- [ ] `report_line_load_progress`의 **`done`인데 0행을 성공으로 기록하는 것 자체를 고친다** —
      이게 이 사고가 조용했던 이유. `status='empty'` 같은 구분 도입
- [ ] 재적재 → `build_std_v3.py --corp <대상>` → Gate B 재감사
- [ ] 결과 측정: 중간 구멍 499건 중 몇 건이 메워졌는가

### Phase 6 — 동등성 전수 검증

- [ ] v2 ∩ v3 공통키 전수 컬럼별 불일치 재측정 (P0 기준선 대비)
- [ ] v2에만 있는 키가 "설명 가능한 것"만 남았는지 확인 (= 비교컬럼 합성 + filing 없음)
- [ ] 잔여 항목을 **"v2 삭제 시 잃는 것"** 으로 명시 문서화

---

## 5-1. ★현재 위치 — P0.6(착수 전 추가 조사) 대기 (2026-08-22)

P0.5 결과를 보고 사용자가 내린 결정:

| 결정 | 내용 |
|---|---|
| **A. 경로** | **미결 ⑤ = (b) 이름표 분해 채택.** 이름은 v2와 동일하게(`bs.lease_current`/`_noncurrent`, `cf.borrow_proceeds_st`/`_lt`) → `rules.py`의 `_LEASE_PARTS`·`_BORROW_*_PARTS`가 수정 없이 맞물림 |
| **B. 착수** | **지금 구현하지 않는다.** 미측정 항목을 먼저 실측한 뒤 착수 범위를 정한다 → **P0.6 신설** |
| **C. 잔여 4건** | 미결 ①②③ + ⑥⑧ 은 **해당 Phase에 도달했을 때 각각 논의**. 지금 닫지 않는다 |

⟹ **다음 실행 단위 = P0.6.** 실행 체크리스트는 별도 문서:
**[`std_v2_catalog_split_p0_6_todo_2026-08-22.md`](std_v2_catalog_split_p0_6_todo_2026-08-22.md)**

그 문서가 담은 것: 대조군 오염 방지 선결 확인(`account_maps`를 v2도 쓰는가) ·
`scripts/diag_canonical_collapse_scan.py` 신설 명세 · 조사 T2~T7 · P1A용 함정 5건.

---

## 6. 검증 방법

### 6.0 선행 (Phase 1 착수 전, 필수)

- [ ] **`face_audit` 스냅샷 생성** — `CREATE TABLE face_audit_snap_<날짜> AS SELECT * FROM face_audit`.
      메모리 `gateb-full-reaudit-is-required-to-close`: *"재감사 **전에** 스냅샷 필수"*
- [ ] **std_v3 값 스냅샷** — 최소 5컬럼(total_assets/revenue/net_income/short_term_debt/cash) + 키
- [ ] 기준선 수치 기록 (아래 불변식의 P0 값)

### 6.1 상시 불변식 (모든 Phase 후 재확인)

| ID | 검사 | 합격 |
|---|---|---|
| I1 | `standard_financials` 중복키 | 0 (`fin2/tests/test_standard_financials_view.py::test_view_has_no_duplicate_keys`) |
| I2 | v3 행 중 v3 감사 없는 것 | **0** (현재 실측 0 — 이 값이 기준선) |
| I3 | 뷰 `gate_b_status` vs v3 `face_audit` 불일치 | 0 (`test_view_gate_b_status_matches_source_chain_audit`) |
| I4 | `face_audit` 미배선 소비자 grep | 0 (`test_face_audit_queries_declare_source_version`) |
| I5 | 뷰 행수 | 무손실 (감소분은 전건 설명 가능해야) |
| I6 | pytest | `pytest tests/ fin2/tests/` — 기존 실패 1건(`test_lxintl_facility_table_dropped`, 무관) 외 신규 실패 0 |

> ★ `pytest`는 반드시 `tests/ fin2/tests/` 로 범위 지정 — 루트 전체는 NAS 심링크에서 멈춘다
> (메모리 `feedback-pytest-scope-raw-report-symlink`).

### 6.2 Phase별 검증

| Phase | 검증 |
|---|---|
| P0.5 | 읽기전용 — 산출물은 수치표뿐. **DB 무변경 확인**(트랜잭션 없음) |
| P1C | `interest_expense` 변경 행수 = 금융원가로 덮여 있던 행 수와 일치하는가(원문 표본 5건). `cash`: 금융사만 변하고 일반기업 **불변**(§규칙 주석의 설계 의도) |
| P1A | 신규 3컬럼: v2와 값 일치율 측정(공통키) — ★**일치율이 낮다고 실패가 아니다**(§2 대원칙). 불일치는 원문대조로 어느 쪽이 맞는지 판정. **기존 컬럼(short_term_debt 등) 전이 0 확인**(값 불변 아님이 판명됐으므로 반드시 측정) |
| P1B | `is_ifrs`: pre-2011 66,705행이 더 이상 TRUE가 아님 확인 + 근거 표본대조 |
| P2 | 107 충돌쌍 전건이 **두 행**으로 분리됐는지. 혼합행 11건 소멸. 국제약품/대구백화점/유유제약 원문대조 |
| P3 | `std_financials_v3_quarterly` vs v2 `is_discrete` 값 대조. `calendar` version=3 vs version=1 대조. 앱 분기차트 스모크 |
| P4 | 규칙별 원문대조 + 표적 재감사. **전수 재감사 필수**(5-shard `scripts/run_gateb_audit_parallel.sh`, 실측 ~2.9h) |
| P5 | 재적재 후 `report_lines` 행수 · v3 신규 기간 수 · 중간구멍 해소 건수 |
| P6 | 전수 대조 리포트 |

### 6.3 전수 재감사 규약 (P2·P4 후 필수)

메모리 `gateb-full-reaudit-is-required-to-close` — *"표본으로 닫으면 다음 전수에서 신규 결함으로
재등장한다"*. 스냅샷 대비 **행단위 전이표**를 만들고, 특히 **`pass→fail` / `X→fail_a` 전이가 0**임을
증명한다(2026-08-21 Track D 재감사가 이 형식).

### 6.4 앱 스모크

- [ ] `streamlit.testing.v1.AppTest` 렌더 무예외
- [ ] 실브라우저 — 기업 시각화(연간+분기 탭) · 스크리너 · 밸류에이션 밴드
- [ ] 금융 5프로필(은행/증권/보험/여신전문/한국금융지주) + 비금융 baseline

---

## 7. 미결 결정

> **2026-08-22 사용자 결정으로 ①②③⑥⑧의 "언제 정할지"가 확정됐다**: 전부
> **해당 Phase에 도달했을 때 각각 논의**한다(지금 닫지 않음). 아래 권고안은 그때의 출발점.
> ⑤는 **확정**(아래), ⑦은 **해소**.

1. **이산분기 저장 위치** — 별도 테이블(권장·§5 P3) vs v3 PK에 `is_discrete` 추가
   → **P3에서 논의**
2. **`applied_rules`를 v3에 추가할지** — `rule_mark_opinc_kifrs` 이식과 `phase_c_integrity_check.py:74`의 `opinc_kifrs` 불변식 쿼리가 여기 걸림. 안 넣으면 그 검증은 폐기
   → **P4에서 논의**
3. **`value_lineage` 축소 수용 여부** — v3 `conflicts`는 값만 남기고 rcept/stage/acode를 버린다(`build.py:142`). 유일 소비자는 `scripts/phase_c_review_digest.py`
   → **P4에서 논의**
4. **P4 규칙별 "v2가 맞나 v3가 맞나"** — 원문대조 후 각 규칙 착수 시점에 결정
5. **★리스/CF차입 canonical 경로**(§3.7·P1A) — **✅ 확정: (b) 카탈로그 분해 채택**
   (사용자 결정 2026-08-22). **P0.6 조사(T1~T7) 전부 완료** → §3.12 참고,
   [`std_v2_catalog_split_p0_6_todo_2026-08-22.md`](std_v2_catalog_split_p0_6_todo_2026-08-22.md)에
   실행 로그. 판단 근거(P0.5 원판 + P0.6 갱신):
   - (a) 주석 경로 → **기각**. 정확 라벨 커버리지 27%뿐(§3.11-3)
   - (c) `ADDITIVE_CANON` 편입 → **기각 권장**. 총계 라벨(`리스부채`)이 유동/비유동과
     **공존**하므로 무조건 합산하면 이중계상(v2가 `rule_additive_debt`에 총부채 초과 가드를
     둔 것과 같은 이유)
   - **(b) face BS/CF 카탈로그 분해 → 채택, P0.6로 재확인.** 충돌률 실측(T2/T3): collapse
     canonical 14.6~49.3% vs 이미 분리된 것(XBRL) ~0% — **분해가 충돌을 없앤다는 걸 직접
     증명**. diff 798라벨 중 예상 밖 변경 2건(위험 아님, 개선 방향). ★**분해 시 canonical
     이름을 v2와 동일하게**(`bs.lease_current`/`bs.lease_noncurrent`,
     `cf.borrow_proceeds_st`/`_lt`) 두면 `rules.py`의 `_LEASE_PARTS`·`_BORROW_*_PARTS`가
     **수정 없이 그대로 맞물린다**. 확정 alias 목록 = §3.12 `SPLIT_DRAFT`.
   - 함께 처리: `비유동리스부채`를 alias에 **명시 등재**(현재 퍼지 0.977로 유동 쪽에
     끌려감).
   - ~~괄호 표기 정규화 결함~~ — **T4로 기각**: 그런 정규화 규칙 자체가 코드에 없다.
     관측된 미매핑은 CF 운전자본조정·EPS라는 별개의 기존 공백(리스/차입과 무관), P1A와 분리.
   - T0(대조군 오염 우려)도 재검토로 **기각** — v2는 fuzzy 매치에 canonical을 안 주므로
     collapse 상태를 못 받고 있었고, 분해는 v2에도 순이득. 오버레이 설계 불필요.
6. **★`extended_financials` v3 등가물을 이 계획에 넣을지**(§3.9) — 규모 실측 완료: **152종**.
   별도 트랙 권장(뷰 자체가 114초 걸릴 만큼 비쌈). 단 **`fact_v2` 폐기의 실질 차단 요인**
   → **해당 시점에 논의**
7. ~~**`kgaap_gap` 잔여 처리**~~ — **해소(2026-08-22)**: 실측 **0행**, 범주 소멸(§3.11-1)
8. **★`rd_fallback` 이식 여부** — 실측 **35행**뿐. **"이식 불필요"로 기각 권장**(§3.11-2)
   → **P4에서 논의**

---

## 8. 부작용 · 위험 항목

| # | 위험 | 근거 | 완화 |
|---|---|---|---|
| R1 | **`build_corp`가 스테일 행을 안 지운다** | `fin2/layer3/build.py:110-117` — 데이터가 안 나오면 DELETE 전에 `continue` | P2 PK 확장 시 대상 corp의 기존 v3 행을 **명시적 선삭제** 후 재빌드 |
| R2 | PK 변경 파급 | 2026-08-18 사고와 동류 | `face_audit`은 이미 `is_stub` 보유(확인됨). 뷰·`gateb_audit`·앱 소비자를 런북 체크리스트로 전수 배선 |
| R3 | **P4가 v3 값을 대규모 변경** | short_term_debt만 41,286행 | 스냅샷 선행 + 전수 재감사 + 규칙 단위 커밋(한 번에 섞지 말 것) |
| R4 | **"원인 A" 재발** — 오래 재빌드 안 된 기업이 누적 규칙변경을 한꺼번에 맞음 | `docs/PARSING_RULES.md:2389`, 실측 689건 단조성 위반 | 규칙별 표적 백필 + 전수 재감사를 매번. 전수 재빌드는 한 번에 몰지 말 것 |
| R5 | `_dq_cross_year_v3` 상태 의존 | `build.py:37-64`가 std_v3 자기 자신을 읽음 | 재빌드 순서(연도 오름차순) 유지. `data_quality` 변화는 별도 집계 |
| R6 | `valuation_daily`가 v2를 **직독** | `collector/db.py:274-283` (뷰 우회) | 이 계획 범위 밖이지만 v2 삭제 전 필수. 실측: 과거 21.5%·최근1년 0.08%가 비교컬럼 유래 |
| R7 | `needs_standardize_corps()`가 v2를 읽음 | `app/data/collect.py:109-111` → `collect_new.py:746,851` | 데일리 백로그 드라이버. v2 삭제 시 파이프라인 정지 |
| R8 | `extended_financials` 뷰 = `fact_v2 × statement_source` | `collector/db.py:366-395,475-510` | `fact_v2` 폐기 차단. `app/data/extended.py`·`shareholder_return.py`가 소비 |
| R9 | `app/data/sources.py`·`amendments.py`가 `statement_source` 직독 | 라이브 UI | v3 `source_rcepts`로 대체 설계 필요 |
| R10 | `dq_assertions.py` v2 17건 + calendar 10건 | 야간 `com.tjfinance.dqcheck` | 포팅 또는 삭제. `diag_calendar_orphans._ORPHAN_PRED`가 `dq_assertions.py:28`로 import돼 야간 경로 |
| R11 | **데일리가 v3를 안 만든다** | `collect_new.py`에 배선 없음 | 이식해도 신규 수집분엔 미반영. 별도 계획(`std_v3_daily_wiring_scoping_2026-08-22.md`) |
| R12 | `com.tjfinance.phasec.plist` = v2 `version=2` 재구축 전용 잡 | launchd | 폐기 시 언로드 |
| R13 | `deploy/launchd/com.tjfinance.collect.plist`에 아직 `--download-only`가 남음 | 설치본에선 제거됨 | 레포/설치본 불일치 — 별건이지만 같이 정리 |
| R14 | 장시간 작업 | 전수 재빌드 ~31분(2015+)·101분(1999+), 전수 재감사 5-shard ~2.9h | 사용자 실행 (메모리 `feedback-long-running-commands`). 이미 돌렸는지 **먼저 확인** |
| R15 | ★**규칙을 붙였는데 무동작** | §3.7 — 규칙의 입력 canonical(`bs.lease_current` 등)이 v3 네임스페이스에 없음 | P0.5 이름 대조표 선행. 이식 후 **"값이 실제로 늘었는가"를 반드시 측정**(코드가 돌았다≠값이 생겼다) |
| R16 | ★**이식이 기존 값을 NULL로 만듦** | §3.7 — 통합 canonical에 두 행 → `_resolve` 충돌 HOLD. `ADDITIVE_CANON`은 D&A 전용(`combine.py:1728`) | P0.5 충돌 사전측정. P1A 후 **기존 컬럼 전이표에서 값→NULL 전이 0** 확인 |
| R17 | ★**데일리 ④-2가 매일 `fact_v2`에 쓴다** | §3.10 — `collect_new.py:118 _sync_cf_da()` → `cf_da_sync`·`expense_nature_sync` → `standardize_corp`(v2)→quarterly→calendar 재전파 | v2 체인은 휴면이 아니다. 이 단계를 걷어내면 `extended_financials`(§3.9)가 stale — **폐기 계획에서 §3.9와 함께 다룰 것** |

---

## 9. 롤백

- 각 Phase는 **독립 커밋**. 값 변경 Phase(**P1A**·P2·P4·P5)는 백필 전 스냅샷 필수
  (★P1A 추가 — 초판은 P1을 "값 불변"으로 봐 제외했으나 §3.7로 뒤집힘)
- 스키마 마이그레이션은 **신규 키로만** 추가 — 기존 마이그레이션 수정 금지
  (`gateb_view_source_version_join_fix_design_2026-08-17.md:178-180`)
- 코드 A/B는 `git checkout <commit> -- <파일>`. **`git stash` 금지**(메모리 `feedback-git-stash-pop-hazard`)
- `std_financials_v2`는 이 계획 내내 **손대지 않는다** — 최종 롤백 근거이자 대조군

---

## 10. 참고

- `docs/plans/layer3_v3_bridge_swap_2026-07-25.md` §7 — v2 폐기 6단계 로드맵(원본)
- `docs/plans/rearchitecture_4layer.md` §7-3 — 2026-08-11 "지우지 말자" 결정과 그 이유
- `docs/plans/std_v3_native_gate_b_plan_2026-08-11.md` §2-4·2-5 — v2 전용 개념 최초 정리
- `docs/plans/std_v3_daily_wiring_scoping_2026-08-22.md` — 데일리 배선(별도 계획)
- `docs/runbook_new_parser_pipeline_integration.md` — 배선 3층 체크리스트
- `docs/PARSING_RULES.md` — 파싱 규칙 단일 진입점 (신규 규칙은 여기 먼저)
- `docs/prd/01a_fiscal_month_change_design.md` — `is_stub` 규약
