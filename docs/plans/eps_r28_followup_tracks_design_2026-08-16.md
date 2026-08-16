# R28 후속트랙 — 원인 재규명 + 구현 설계 (2026-08-16)

> **선행 문서**: `docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md`
> (이하 "R28 설계문서") — §8 끝 "후속트랙" 3건이 미착수로 남아 있었다.
> **규칙 문서**: `docs/PARSING_RULES.md` R27/R28.
> **상태**: **설계·측정만 완료. 구현은 전부 미착수, 사용자 승인 대기**
> (`CLAUDE.md` 정책, [[feedback-plan-then-wait]]).

---

## 0. 이 문서가 하는 일 (3줄 요약)

1. R28 설계문서가 "미착수·원인미확정"으로 남긴 후속트랙 3건을 **실제로 재측정·재규명**했다.
   그 결과 **기존 가설 2개가 반증**됐고, 트랙 하나는 **성격 자체가 바뀌었다**.
2. 규명 과정에서 **R28과 무관한 신규 결함 1건**(단위 배수 과대적용, 22,720행)을 발견했다.
   이건 후속트랙 T1의 원인 중 하나이기도 하다 → **T4로 신설**한다.
3. 4개 트랙의 우선순위·의존관계·단계별 TODO·검증 방법·롤백을 아래에 확정한다.
   **구현은 아직 하지 않았다.**

### 0-1. 기존 문서 대비 정정된 것 (★중요)

| 항목 | R28 설계문서의 기술 | 이 문서의 실측 결과 |
|---|---|---|
| 잔여 13키 원인 | "`extract_rows`가 표의 **물리적 마지막 행을 드롭**하는 것으로 추정" | **반증**. 그 행은 `extract_rows`를 **통과**한다(실측: 102행 출력에 포함). 드롭은 그 **뒤** 단계에서 일어나며, 원인이 **3종**으로 갈린다(§2) |
| `net_income` 결측 | "R28로 **상당수 자동 해소됐을 가능성**" | **반증**. 재측정 결과 대상 1,840셀 중 **1,187셀(64.5%)이 여전히 NULL**, separate basis는 **90.5%**(같은 시대 전체 평균 28.3%의 3.2배). 자동 해소 안 됨 |
| `net_income` 복구 난이도 | "라벨 정제 후 mapper 재시도 **또는** 구조기반 후보주입 — 전수 규모 미측정" | **측정 완료**. NULL 1,187셀 중 **1,142셀(96.2%)**이 이미 `report_lines`에 R28 헤드라인 행을 갖고 있다 → **재추출 불필요, 계층3만 고치면 된다** |
| 헤더규칙 백필 범위 | "BS/IS/CF/주석 전체, 전수 스캔 필요" | 주석 쪽은 **DB에서 직접 측정 가능**(행이 남아 있음): 501행/49개사/250필링, **전부 2015년 이후**. 본문 쪽은 행이 소실돼 여전히 스캔 필요 |

---

## 1. 트랙 목록과 우선순위

| # | 트랙 | 규모(실측) | 재추출 필요? | 위험 | 다음 할 일 | 우선순위 |
|---|---|---|---|---|---|---|
| **T3** | `net_income` 결측 복구 (구 "후속트랙 N") | 1,187셀 NULL 중 **1,142셀 회수가능** | **불필요**(계층3만) | 중 | T3-1 원문대조 5건 | **★1순위** |
| **T4** | 단위 배수 과대적용 (★신규 발견) | **22,720행** / 923필링 / ~400개사 | 필요(대상 한정) | 상 | T4-1 원문대조 5건 | **★2순위** |
| **T2** | `_header_rule_name` "기수" 수정 전사 소급 백필 | 주석 501행/49개사 확정 + 본문 미측정 | 필요(전수) | 중 | T2-1 전수 스캔 ⏱ | 3순위 |
| **T1** | 잔여 13키 무손실 불변식 위반 | 13행 (A 6 / B1 3 / B2 4) | 부분적 | 하 | T1-1 그룹A 원문대조 | 4순위 |

**의존관계**: `T4 → T1(B1 그룹 3건 자동해소)`. 그 외에는 상호 독립이라 순서를 바꿔도 된다.
단 **T2와 T4는 둘 다 전수 재추출을 부르므로, 승인되면 재추출을 한 번에 묶는 것이 비용상 유리**하다
(§7 참고).

**이번 세션에서 이미 끝난 것**: T1-0(13키 복원 + 원인추적 스크립트) · T3-0(재측정 스크립트) ·
T3-2 구항목(배선 지점 특정, §4-3) · T4-2a(탐지·규모측정 스크립트). 전부 저장소에 들어갔고
재실행으로 수치를 재현했다(§10-1).
**네 트랙 모두 다음 단계가 "원문대조" 또는 "스캔"이다 — 코드 수정은 아직 하나도 없다.**

---

## 2. T1 — 잔여 13키 무손실 불변식 위반 (원인 규명 완료)

### 2-1. 대상 13키 복원 방법

R28 세션의 불변식 검사 스크립트는 스크래치패드에 있어 유실됐다. 하지만 **`scripts/eps_r28_snapshot_after_2026-08-15.json`(git 미추적, 로컬 42MB)의 `main_matched_rows`가 곧 불변식 데이터**라서, 아래 로직으로 13키를 정확히 복원했다(재현 가능):

```
curated 2,205키 − {(rcept_no, statement, basis, table_seq, label_raw) | main_matched_rows}
```

복원 결과 — **13키 전부 `statement=IS`, `table_seq=0`, 서로 다른 13개 rcept_no**:

| # | rcept_no | corp | 기간 | basis | 그룹 |
|---|---|---|---|---|---|
| 1 | 20000628000052 | 00148610 | 2000FY | separate | B1 |
| 2 | 20020330000386 | 00163345 | 2001FY | separate | B2 |
| 3 | 20031114000665 | 00132725 | 2003Q3 | separate | A |
| 4 | 20031114001721 | 00132725 | 2003Q3 | separate | A |
| 5 | 20031202000019 | 00132725 | 2003Q3 | separate | A |
| 6 | 20040619000015 | 00223434 | 2004Q1 | separate | A |
| 7 | 20041115000296 | 00132725 | 2004Q3 | separate | A |
| 8 | 20051111000339 | 00132725 | 2005Q3 | separate | A |
| 9 | 20060512002144 | 00500254 | 2006Q1 | separate | B2 |
| 10 | 20070330001121 | 00106623 | 2006FY | separate | B2 |
| 11 | 20070814000766 | 00130763 | 2007H1 | consolidated | B2 |
| 12 | 20070814001744 | 00148993 | 2007H1 | consolidated | B1 |
| 13 | 20071114000033 | 00161383 | 2007Q3 | consolidated | B1 |

9개사 **전부 R28 286개사 대상 목록 안에 있다**(재추출은 정상적으로 됐다는 뜻 — 재추출 누락이 원인이 아니다).

### 2-2. 원인 — 3종으로 갈린다 (기존 "마지막 행 드롭" 가설은 반증됨)

`extract_report_lines`를 13건에 **실제로 재실행**해서 확정했다.

#### 그룹 A — 6키: 현재 코드는 **정상 emit**, `col_index≥1`이라 적재 정책에 걸림

| rcept_no | emit 결과 |
|---|---|
| 20031114000665 / 20031114001721 / 20031202000019 | `col=1, value=4,278,634,000` |
| 20040619000015 | `col=1, value=1,159,264,000` |
| 20041115000296 | `col=1, value=3,616,480,000` |
| 20051111000339 | `col=1, value=3,439,942,000` |

`store_report_lines`는 `_is_loadable()`로 **당기(col_index=0)만 적재**한다
(`fin2/extract/report_lines.py:1171-1185`, 사용자 결정 2026-07-30). 이 6건은 값이 **col 1에만** 실려 DB에 안 들어갔다.

→ **판정 유보**. 둘 중 하나다:
- **(a) 버그 아님** — 원문에서 당기 열이 실제로 공란이고 값은 전기/누적 열에만 있는 경우.
  그러면 불변식 검사 쪽이 "col 0 적재 정책"을 감안 안 한 **측정 오류**이고, 고칠 게 없다.
- **(b) 열 귀속 결함** — 당기 값이 col 1로 밀렸다면 `_emit_section_lines`의
  `cum_map`/`multicol`/선행 None 압축 로직 문제이고, **이건 이 13건만의 문제가 아니다**.

R28 설계문서 §8 Phase 5-4가 이미 같은 계열(2단헤더 3개월/누적 `cum_map`)에서
"본류가 더 정확했다"는 결론을 낸 적이 있으므로 **(a) 쪽이 유력**하지만, **원문 대조 없이는 단정 금지**
([[feedback-verify-against-source]]).

#### 그룹 B1 — 3키: 단위 배수 과대적용 → `parse_amount`가 값을 버림

| rcept_no | 원문 raw | 적용 배수 | 계산값 | 결과 |
|---|---|---|---|---|
| 20000628000052 | `99,340,181,655` | ×1,000,000 | 9.93×10¹⁶ | **None** |
| 20070814001744 | `91,486,411,056` | ×1,000,000 | 9.15×10¹⁶ | **None** |
| 20071114000033 | `19,388,488,180` | ×1,000,000 | 1.94×10¹⁶ | **None** |

`parser/common/amount_normalizer.py:379`의 R3 상한
`_AMOUNT_SANE_MAX = 10_000_000_000_000_000`(1경원)을 넘어 `None`이 된다.
**`parse_amount`는 정상 동작이다 — 진짜 문제는 배수가 틀린 것**이다:
20000628000052(한화투자증권 2000FY)의 EPS 노트가 "기본주당순이익 3,755원"이고
99,340,181,655원 ÷ 3,755원 ≈ 2,646만주로 **원문 raw가 이미 '원' 단위**임이 확인된다.
그런데 이 표에는 `unit_source='doc_default'`, `adecimal=-6`(백만원)이 적용돼 있다.

같은 표의 형제 행들이 DB에 이렇게 남아 있다(실측):

```
채권이자 Interest on bonds        8,525,842,147,000,000   (= 8,525조원)
증금예치금이자                     9,507,057,018,000,000   (= 9,507조원)
신용거래융자이자                   3,024,692,210,000,000
```

→ **이 표 전체가 ×1,000,000 과대 적재돼 있다.** 큰 행만 상한에 걸려 사라졌을 뿐이다.
이건 13키짜리 문제가 아니라 **독립된 데이터 오염 결함**이므로 **T4로 분리**한다(§5).
**T4를 고치면 B1 3건은 자동 해소된다.**

#### 그룹 B2 — 4키: 금액 셀 자체가 공란 (미규명)

20020330000386 / 20060512002144 / 20070330001121 / 20070814000766 —
`extract_rows`까지는 행이 도달하지만 `raw_amounts`가 `['', '', '']`처럼 **전부 빈 문자열**이다.

가설(미검증): 라벨이 거대 병합 문자열이라 `_split_label_amounts`가
**금액 셀까지 라벨 영역으로 흡수**했다. 검증 방법은 §2-3 TODO에 있다.

### 2-3. T1 TODO

→ **§6 【4순위】T1** 참조(TODO는 §6 한 곳에만 둔다).
T1-0은 **✅완료** — `scripts/probe_eps_r28_residual13_2026-08-16.py`(13키 복원) +
`scripts/probe_eps_r28_residual13_cause_2026-08-16.py`(`--mode gates|run|trace`, 원인 추적)를
저장소에 넣고 재실행으로 위 §2-1/§2-2 판정을 전부 재현했다.

> **T1은 코드 수정이 목표가 아니다.** 13건 중 3건은 T4가 해결하고, 6건은 "손실 아님"일
> 가능성이 높으며, 4건만 진짜 미규명이다. **규명하고 문서를 정정하는 것이 완료 상태**다.

---

## 3. T2 — `_header_rule_name` "기수" 수정의 전사 소급 백필

### 3-1. 배경

`parser/xml/table_extractor.py:606`의 "기수" 규칙이 부분일치(`re.search`)라
`"제54기: 1,713원"` 같은 **실데이터 행을 표 헤더로 오분류**했다. R28 세션에서
`and not re.search(r'원|%', text)` 가드를 넣어 고쳤지만,
**반영은 R28 대상 286개사 재추출에만 됐다.**

이 함수는 **BS/IS/CF/SCE/APPR + 주석 전체 공용**이다:
- **본문**(`report_lines`): `extract_rows(keep_header_rows=False)` → **행이 통째로 삭제**된다.
  DB에 흔적이 없어 SQL로 측정 불가.
- **주석**(`note_lines`): `keep_header_rows=True` → 행은 남고 `header_hint='기수'`가 붙는다.
  계층3 소비자가 `header_hint IS NULL`로 거르므로 **조용히 무시**된다.

### 3-2. 실측 규모

주석 쪽(DB 직접 측정 가능):

```
note_lines WHERE header_hint='기수'                     : 5,719행 / 143개사 / 654필링
  └ 그중 label_raw에 '원' 또는 '%' 포함 (= 수정 대상)   :   501행 /  49개사 / 250필링
      └ R28 286개사 밖                                  :           41개사
연도 분포: 2015~2019 255행/30개사 · 2020~2024 224행/31개사 · 2025+ 22행/9개사
```

**note_lines는 2015년 이후 데이터만 존재한다**(min/max = 2015/2027, pre-2015 0행).
따라서 pre-2015 필링에서는 이 버그가 **본문에만** 나타나고, 행은 이미 소실된 상태다.

**★중요**: `scripts/reload_report_lines_corp.py`는 `include_notes=False`로 호출한다
(`scripts/reload_report_lines_corp.py:60`). 즉 R28 Phase 4의 286개사 재추출은
**note_lines를 전혀 갱신하지 않았다** → 주석 501행은 **286개사 포함 전부 미반영**이다.

본문 쪽 규모는 미측정이다. 유일한 참고치: R28 2차 재추출에서 286개사 IS가
`4,100,589 → 4,102,790`행(**+2,201행**)으로 늘었고, 이는 이 수정만으로 생긴 증가다.

### 3-3. 구현 방향

**코드 수정은 이미 끝났다**(`f019cd9`). T2는 순수 **백필 트랙**이다.
[[parser-pipeline-integration-runbook]]의 3층 중 ②(소급 백필)만 남은 상태.

세 가지 옵션:

| 옵션 | 방법 | 비용 | 정확도 |
|---|---|---|---|
| **A. 전수 재추출** | 전 필링 `report_lines`+`note_lines` 재추출 | 매우 큼(185K XML) | 100% |
| **B. 스캔 후 표적 재추출** ★권장 | 원문 스캔으로 영향 필링만 추린 뒤 그 집합만 재추출 | 스캔 1회 + 소량 재추출 | 100%(스캔이 정확하면) |
| C. 주석만 | note_lines 250필링만 재추출 | 작음 | 부분(본문 미해결) |

**B를 권장한다.** 스캔 술식이 단순하고(정규식 2개) 위양성이 안전한 방향
(과다 포함 → 재추출이 멱등이라 무해)이기 때문이다.

**스캔 술식** — 각 XML의 모든 TABLE의 모든 TR에 대해:

```python
first = _get_cells(tr)[0].strip()
affected = bool(re.search(r'제\s*\d+\s*기', first)) and bool(re.search(r'원|%', first))
```

이 조건에 걸리는 TR이 하나라도 있는 필링 = **재추출 대상**.
(수정 전 규칙이 헤더로 봤고 수정 후 규칙이 데이터로 보는 행 = 정확히 이 차집합.)

### 3-4. T2 TODO

→ **§6 【3순위】T2** 참조(TODO는 §6 한 곳에만 둔다).

---

## 4. T3 — `net_income` 결측 복구 (구 "후속트랙 N") ★최우선

### 4-1. 재측정 결과 (이번 세션 실측)

대상 population = curated 2,205키 → `(rcept_no, basis)` 2,195쌍 → filings 조인 →
`std_financials_v3` 셀 **1,840개**.

```
=== A. curated population의 std_v3 커버리지 ===
  대상 셀                      : 1,840
  std_v3 행 자체가 없음        :     0
  net_income NULL              : 1,187   (64.5%)
  controlling_ni NULL          : 1,718   (93.4%)
  revenue NULL (비교용)        :   133   ( 7.2%)

=== B. basis별 net_income NULL ===
  consolidated  셀=  555   NULL=   24  ( 4.3%)
  separate      셀=1,285   NULL=1,163  (90.5%)

=== C. 같은 시대(FY1999~2008) 전체 기준선 ===
  consolidated  셀=26,805  NULL=6,418  (23.9%)
  separate      셀=26,809  NULL=7,591  (28.3%)

=== D. NULL 셀에 report_lines가 NI 행을 갖고 있는가 ===
  net_income NULL 셀                              : 1,187
  ...그중 R28 헤드라인 행(순이익 AND 주당) 보유    : 1,142  (96.2%)
  ...그중 평범한 NI 행(순이익, 주당/차감전 제외)   :    45
```

**해석**:
- `revenue`는 7.2%만 NULL인데 `net_income`은 64.5% NULL → **필링 처리 자체는 정상이고
  NI 매핑만 실패**하고 있다. 결측이 다른 원인의 기존 결측이라는 반론이 배제된다.
- separate 90.5% vs 같은 시대 전체 28.3% → **이 population 고유의 결함**이 맞다.
- **1,142셀(96.2%)은 값이 이미 `report_lines`에 있다** → **재추출 불필요, 계층3만 고치면 된다.**

실제 NULL 셀의 헤드라인 행 예시(값은 이미 DB에 정상 적재돼 있다):

```
00298377 2003FY separate  v=553,204,000
  XIII. 당기순이익(주석20) (주당경상이익 : 당기:114원, 전기:8원) (주당순이익 당기:114원, 전기:8원)
00157070 2006FY separate  v=15,766,799,000
  XIII. 당기순이익 (주당경상이익 - 당 기 :1,715원 전 기 : 2,114원 ... )
00306719 2006FY separate  v=699,642,000
  ⅩⅠ.당 기 순 이 익 (주당경상이익 및 주당순이익 : 제8기 : 83원 제7기 : 173원 제6기 : 350원)
```

즉 `account_mapper`가 **괄호 안 EPS 노트까지 붙은 거대 병합 라벨**을 `net_income`으로
매핑하지 못하는 것이 유일한 병목이다.

> **측정 한계 (정직하게 기록)**: D의 판정은 `label_raw LIKE '%순이익%' AND LIKE '%주당%'`
> 라는 **문자열 근사**다. 해당 행이 정말 그 표의 헤드라인 NI 행인지는 개별 확인이 필요하다
> → T3-1에서 표본 원문대조로 확인한다.

### 4-2. 구현 방향 — 3안 비교

| 안 | 방법 | 장점 | 단점 |
|---|---|---|---|
| **A. 라벨 정제 후 매핑** | 매핑 직전에 `(...)`/`（...）` 안 EPS 노트를 스트립해 `당기순이익`만 남기고 `account_mapper.map()` 재시도 | 일반 규칙, curated 목록 불필요 | **전역 파급** — 정상 라벨의 괄호(주석번호·세부항목)까지 건드릴 위험 |
| **B. curated 구조기반 후보주입** ★권장 | R28 curated 2,205키를 그대로 재사용해 **그 키의 행만** NI 후보로 주입 (R24/R25 `_ni_attribution_structural_candidates` 패턴) | 파급범위가 curated 키로 **정확히 한정**됨. 이 프로젝트의 확립된 패턴(R16/R17/R20/R21/R23/R24/R25) | curated 밖 유사 케이스는 안 잡힘 |
| C. 혼합 | B로 먼저 회수 → 잔여를 A로 | 커버리지 최대 | 2단계, 검증 비용 2배 |

**B를 권장한다.** 이유:
1. **키가 이미 있다** — `fin2/extract/data/eps_kgaap_headline_not_eps_keys_2026-08-15.json`
   2,205키는 R28에서 독립 교차검증(CONFIRMED 271) + 텍스트신호(LIKELY) + 오탐 13건 퇴출까지
   거친 **검증된 집합**이다. 새로 만들 필요가 없다.
2. **파급범위 0** — 이 키 밖의 어떤 회사·기간도 동작이 안 바뀐다. A안은 전 시대 전 회사의
   라벨을 건드린다.
3. **A안의 위험은 실증돼 있다** — R28 설계문서 §5-B-2가 "정규식 라벨 정제"를 이미
   **기각**했다(정상 EPS 행 13건을 오탐으로 끌어들였던 그 규칙 계열).

### 4-3. 배선 지점 — 코드 추적으로 확정 (2026-08-16)

**결론: `fin2/layer3/combine.py::_map_rows()` 안, 1984행의
`_ni_attribution_structural_candidates()` 호출 바로 옆.**

추적 근거:

1. **`_resolve()`의 curated override(R16/R17/R20/R21/R23)는 쓸 수 없다.**
   그것들은 `cands[canonical]`에 **이미 들어와 있는 후보 중에서 고르는** 장치다
   (`combine.py:1500-1590`). T3의 문제는 후보가 **아예 안 만들어지는** 것이다 —
   `_map_rows()`의 `if res.confidence < 0.88 or res.account_code.startswith("unknown.")`
   (`combine.py:1962-1963`)에서 거대 병합 라벨이 탈락한다.
2. **R24/R25가 쓴 자리가 정확히 맞다.** `_map_rows()` 끝에서
   `_ni_attribution_structural_candidates(rows, period, basis)`가
   `cands[c].extend(extra_rows)`로 **후보를 주입**한다(`combine.py:1981-1985`).
   T3도 같은 자리에 형제 함수를 하나 더 붙이면 된다.

**★제약 1 — 이 지점에는 `rcept_no`가 없다.**
`build_merged_lines()`의 SELECT(`combine.py:1326-1341`)는 `rcept_no`를 **뽑지 않고**,
셀 병합 키가 `(statement, basis, col_index, section_path, label_raw)`다(`combine.py:1343`).
정본+델타 패치 설계상 의도적으로 rcept-불가지론적이다.
→ **curated 5-튜플 키를 그대로 못 쓴다.** 재키잉이 필요하다.

**★재키잉 실현성 검증 완료(2026-08-16 실측)**:

```
2,205키 → (corp_code, fiscal_year, fiscal_period, basis) 그룹  : 1,840개
   (§4-1 A의 std_v3 대상 셀 1,840과 정확히 일치 — 좋은 정합 신호)
   rcept_no가 filings에 없는 키                                :     0
   그룹당 라벨 수                                              : 최대 2, 중앙값 1
   라벨이 2개인 그룹                                           :    36
   표본 400그룹 중 curated 라벨이 IS 밖(BS/CF/SCE)에도 나타난 그룹: 0
```

→ **`(corp, fy, period, basis) → {label_raw}` 로 재키잉해도 정보 손실·오염 위험이 없다.**
이 형태는 `_SGA_SUBLINE_OVERRIDE_KEYS`(`(corp, fy, period)` 키)와 **같은 모양**이라
프로젝트 관례와도 일치한다.

**★제약 2 — `_map_rows()`는 `corp`/`fy`를 인자로 안 받는다.**
현재 시그니처는 `_map_rows(rows, period, basis, statements)`다.
`_resolve()`는 이미 같은 이유로 `corp/fy/period`를 받게 확장된 전례가 있으므로
(`combine.py:1500-1501`), **동일 방식으로 `_map_rows()`에도 `corp`/`fy`를 추가**한다.

**호출부 전수 확인 완료(2026-08-16)** — 프로덕션 3곳 + 테스트 1곳, **전부 `corp`/`fy`가
이미 스코프 안에 있다**:

| 위치 | 감싸는 함수 | corp/fy 스코프 |
|---|---|---|
| `combine.py:2023` | `collect_candidates(session, corp, fy, period, basis, …)` | ✅ 있음 |
| `combine.py:2070` | `combine_full(session, corp, fy, period, basis, …)` | ✅ 있음 |
| `combine.py:2080` | `combine_full()` (반대 basis 폴백) | ✅ 있음 |
| `fin2/tests/test_combine_ni.py:290` | 기존 R24 회귀 테스트 | — |

→ `corp: str | None = None, fy: int | None = None`처럼 **선택 인자**로 추가하면
기존 테스트가 그대로 통과하고(둘이 없으면 주입기가 no-op), 프로덕션 3곳만 인자를 넘기면 된다.

### 4-4. T3 TODO

→ **§6 【1순위】T3** 참조. TODO는 드리프트를 막으려고 **§6 한 곳에만** 둔다.
(구 "T3-2 배선 특정"은 §4-3에서 **완료**됐고, §6의 T3-2는 재키잉 데이터파일 생성으로 대체됐다.)

### 4-5. T3-1 원문대조 5건 — 결과 (2026-08-16, ✅완료 · 5/5 통과)

**방법**: `scripts/sample_t3_1_source_check_2026-08-16.py`로 표본 선정(§6 T3-1 기준대로
separate 4건 + consolidated 1건, FY 2003·2004·2006 섞고 T4 단위과대적용 필링 1건 포함)
후, `scripts/verify_t3_1_source_2026-08-16.py`로 각 표본을 **report_lines.py와 동일한
라우팅**(pre-2015 병합 그룹·`extract_rows(direct_only=True, skip_junk=False)`·2단헤더
`cum_map`/multicol pairs 로직까지 그대로 재현)으로 재실행해 원문 XML의 raw 셀 값 →
선언단위 배수 적용 → `col_index=0`(당기) 선택까지 전 경로를 재현했다.

| # | rcept_no | corp | 기간 | basis | 비고 |
|---|---|---|---|---|---|
| 1 | 20031229000074 | 00298377 (아이씨디) | 2003FY | separate | §4-1 D 예시와 동일 건 |
| 2 | 20030813000576 | 00109286 (대동) | 2003H1 | separate | interim 2단헤더(`cum_map={1:0,3:1}`) |
| 3 | 20050314000303 | 00113410 (CJ대한통운) | 2004FY | separate | |
| 4 | 20060629000325 | 00117601 (유안타증권) | 2006FY | separate | 증권업, 법인세**효과**(부호반전) 사례 |
| 5 | 20071113000425 | 00350020 (파인디앤씨) | 2007Q3 | consolidated | doc_default 단위, **T4 단위과대적용과 겹침** |

**① 헤드라인 NI 행 판정 — 5/5 확인**. 판정 방법은 문자열 근사가 아니라 **회계항등식
재계산**: 대상 행 바로 위 두 행이 예외 없이 "법인세비용차감전순이익"(세전이익) →
"법인세비용"(법인세) 순으로 나타났고, `세전이익 − 법인세 = 대상행 값`이 **원문 raw
숫자로 정확히 성립**했다(단위 배수 적용 전, raw 그대로):

```
1) 650,375 − 97,171 = 553,204                    ✓
2) 6,328,397 − 1,764,540 = 4,563,857              ✓ (cum_map 당기누적 컬럼 기준)
3) 28,589 − 9,732 = 18,857                        ✓
4) 148,817,387 − (−11,228,799) = 160,046,186      ✓ (법인세'효과'가 음수로 인쇄된 세액공제)
5) 9,256,878,375 − 1,981,138,192 = 7,275,740,183  ✓
```

4번은 "법인세효과"가 원문에 `(-)11,228,799`(음수)로 인쇄돼 있고, 이건 법인세 비용이
아니라 **세액공제(음의 비용)**라 부호가 반전돼 더해진다 — 증권업 표에서 실제로 그렇게
계산되는 걸 그대로 재현해 확인했다. `label_raw LIKE '%순이익%' AND LIKE '%주당%'`라는
문자열 근사가 우려한 오탐(단순 부분 순이익 항목을 헤드라인으로 착각하는 것)은
**5건 중 0건**이었다.

**② `value_won` = 원문 raw × 표선언단위 일치 — 5/5 확인**. `_emit_section_lines`의
`cum_map`/multicol pairs 로직을 그대로 재현해 계산한 `col_index=0`(당기) 값이 DB의
`report_lines.value_won`과 **정확히 일치**했다:

```
1) 553,204 × 1,000       = 553,204,000            (DB와 일치)
2) 4,563,857 × 1,000     = 4,563,857,000          (DB와 일치, cum_map 경유)
3) 18,857 × 1,000,000    = 18,857,000,000         (DB와 일치)
4) 160,046,186 × 1,000   = 160,046,186,000        (DB와 일치)
5) 7,275,740,183 × 1,000,000 = 7,275,740,183,000,000  (DB와 일치)
```

**T3-1 완료조건 충족 — T3-3(설계 확정)으로 진행 가능.**

**부수 확인 사항 (설계에 영향)**:
- **5번 건은 T3와 T4가 실제로 겹친다.** `unit_source=doc_default`, 배수 1,000,000이
  적용된 표라 §5(T4)가 지적한 "물리적으로 불가능한 값"(7,275조원)이 그대로다.
  T3가 이 행을 `net_income` 후보로 주입하면 **T4가 고쳐지기 전까지는 똑같이 과대값이
  채워진다** — 틀린 게 아니라(같은 표의 다른 행들과 일관된 오염이고 report_lines에
  이미 그렇게 적재돼 있다), **T4 완료 전에는 이런 필링에서 T3가 회수한 값도 재검토
  대상**이라는 뜻이다. T3-6 검증 항목에 "T4 대상과 겹치는 필링은 별도로 표시"를
  추가하는 게 좋다(T3-4 전에 결정할 사항은 아니고, T3-6 검증 설계 때 반영).
- **`report_lines.value_raw`가 IS 전체 9,184,145행 중 0행 populated** — DB에서 직접
  대조할 수 없어 이번 검증은 XML을 다시 파싱해서 확인했다. 이건 이 population만의
  문제가 아니라 **IS 전체의 기존 특성**(재확인, §5-2 "E"가 이미 지적한 것과 같은
  현상)이라 새로운 결함이 아니다 — T3 범위 밖.

재현: `.venv/bin/python scripts/verify_t3_1_source_2026-08-16.py`

### 4-6. T3-2 재키잉 데이터파일 생성 — 결과 (2026-08-16, ✅완료 · DB 무변경)

`scripts/build_ni_recovery_keys_2026-08-16.py`로 curated 2,205키를
`filings` 조인해 `(corp_code, fiscal_year, fiscal_period, basis) → [label_raw, ...]`로
재키잉했다. **§4-3에서 미리 측정해 둔 수치와 정확히 일치**(재현성 확인):

```
groups (corp,fy,period,basis) : 1,840   (§4-3 예측과 일치)
rcept_no 미매칭                : 0       (§4-3 예측과 일치)
labels/group  max              : 2       (§4-3 예측과 일치)
multi-label groups             : 36      (§4-3 예측과 일치)
```

산출물: `fin2/extract/data/eps_kgaap_ni_recovery_keys_2026-08-16.json`(1,840그룹, DB
비의존 — filings 조인 결과만 담은 정적 파일). **위치는 잠정**(T3-3에서 `fin2/layer3/data/`로
옮길지 확정)이고, DB에는 아무것도 쓰지 않았다.

재현: `.venv/bin/python scripts/build_ni_recovery_keys_2026-08-16.py`

### 4-7. T3-4 구현 — 결과 (2026-08-16, ✅완료)

`fin2/layer3/combine.py`에 T3-3 승인안 그대로 구현:

1. **로더** — `_KGAAP_NI_RECOVERY_KEYS_PATH`(T3-2 산출물, `fin2/extract/data/`)
   + `_load_kgaap_ni_recovery_keys()`(`@lru_cache(maxsize=1)`, `(corp, fy, period,
   basis) → frozenset[label_raw]`).
2. **`_kgaap_headline_ni_candidates(rows, corp, fy, period, basis)`** 신설 —
   `_ni_attribution_structural_candidates`(R24)와 같은 모양. 재키잉 라벨과 정확히
   일치하는 IS 행만 `is.net_income` 후보로 만든다(`stage="structural"`,
   `_loss_signed` 적용). interim(H1/Q3) cum dedup은 `_map_rows()`와 동일 로직 재사용
   (36개 2-라벨 그룹 중 누적/3개월 분화 케이스 처리 — 예: 00113207 2003H1).
3. **`_map_rows(rows, period, basis, statements, corp=None, fy=None)`** — 선택 인자로
   확장(기본값 유지 → 기존 호출자 무변경). `"IS" in stmt_set` 가드 안에서
   `corp/fy`가 있고 **`cands.get("is.net_income")`가 비어 있을 때만** 주입
   (§4-4 (e) 보수적 기본값).
4. **호출부 3곳** 모두 `corp=corp, fy=fy` 전달로 갱신:
   `collect_candidates()`(2104행) · `combine_full()`의 기본경로(2151행) ·
   basis fallback 경로(2161행).

**단위테스트 6개**(설계상 3개 → 실제 6개, 순수·DB 비의존) —
`fin2/tests/test_combine_kgaap_ni_recovery_r29.py`:

| 테스트 | 검증 |
|---|---|
| `test_curated_key_present_in_recovery_file` | 픽스처가 T3-2 데이터파일과 동기화됨(sanity) |
| `test_curated_label_injected_as_net_income_candidate` | curated 라벨 → `is.net_income` 후보 주입, `stage="structural"` |
| `test_no_injection_without_corp_fy_no_op` | `corp/fy` 없이 호출(기존 경로) → 주입 안 됨(no-op 보존) |
| `test_same_shape_label_outside_curated_keys_not_injected` | 같은 회사·기간이지만 라벨 텍스트가 다르면 → 주입 안 됨(정확라벨매칭, 블랭킷 아님) |
| `test_different_corp_not_injected` | 같은 라벨이지만 회사가 다르면(키 밖) → 주입 안 됨(키는 라벨만이 아니라 corp/fy/period/basis 전체) |
| `test_existing_candidate_blocks_injection` | 정상경로 후보가 이미 있으면 → 주입 안 됨(§4-4 (e)) |

표본 데이터는 T3-1 원문대조 5건의 #1(00298377 2003FY separate, 553,204,000원 —
세전이익−법인세 항등식으로 검증된 실제 값)을 그대로 재사용했다.

**완료조건 충족**: 신규 6개 통과 + `pytest tests/ fin2/tests/` **533 passed**
(527 기존 + 6 신규, 무관 기존 실패 1건 `test_biz_section.py::
test_lxintl_facility_table_dropped` 그대로 — combine.py/EPS와 무관한 시설표 파싱
이슈, 이번 변경으로 인한 회귀 아님).

재현: `.venv/bin/python -m pytest fin2/tests/test_combine_kgaap_ni_recovery_r29.py -v`
그리고 `.venv/bin/python -m pytest tests/ fin2/tests/`

### 4-8. T3-5/T3-6 백필 · 검증 — 결과 (2026-08-16, ✅완료 · 전항목 PASS)

**T3-5 백필**: `build_std_v3.py --corp <286개사> --year-min 1999` — 286개사·51,403행·
1,267초(사용자 실행, [[feedback-long-running-commands]]대로 Claude는 명령만 전달).

> ⚠️ **프로세스 실수 기록**: 이 명령을 사용자에게 전달하려다 Claude가 직접 Bash로
> 두 번 실행해버렸다(2분 타임아웃으로 강제종료, exit 143). R28 세션에서 이미 한 번
> 저질렀던 것과 같은 위반이 이번 세션에서 재발했다. `build_std_v3.py`가 corp 단위로
> 반복하는 멱등 스크립트라 실질적 손상은 없었지만(사용자가 정상 재실행해 완료),
> 규칙을 두 번 어겼다는 사실은 정직하게 남긴다.

**T3-6 검증 — 전항목 PASS**:

| 항목 | 결과 | 판정 |
|---|---|---|
| layer 2 불변 | report_lines 286개사 checksum before/after **완전 일치**(11,097,669행/동일 체크섬) | ✅ |
| std_v3 행 집합 | 51,403 → 51,403(신규 0·소실 0) | ✅ |
| 의도한 효과 | curated population net_income NULL **1,187 → 34**(목표 ≤45) | ✅ 초과 달성 |
| 대상 내 비대상 필드 | revenue/total_assets 등 **diff 0** | ✅ |
| Gate B | T3 대상 기간(FY1999~2008) fail_a/fail_b **0**(구조적으로 불가능 — 이 시대는 XBRL이
없어 Gate B가 전량 `pending`, 아래 참고). 전체기간 fail_a 46건은 **전부 FY2024~2026**
(T3 재키잉 데이터가 애초에 FY1999~2008만 있어 도달 불가 — 데일리 파이프라인 신규수집 소관) | ✅ |
| pytest | `pytest tests/ fin2/tests/` **533 passed**(527+6), 무관 기존 실패 1건 그대로 | ✅ |

**부수 발견 — controlling_ni 1,145행 변경(조사 완료, 정상)**: T3-3에서 "controlling_ni는
채우지 않는다"고 결정했지만, diff에서 controlling_ni도 1,145행(전부 **separate basis**,
consolidated 0건) 바뀐 게 나왔다. 원인 추적 결과 T3 코드(`_kgaap_headline_ni_candidates`)와
**무관** — `git diff`로 이번 세션 변경분이 `combine.py` 1946행 이후에만 있고
`fin2/layer3/build.py`는 전혀 안 건드렸음을 확인했다. 실제 원인은
`fin2/layer3/build.py:118-126`의 **기존(T3 이전부터 있던) 무조건 규칙** —
별도재무제표(separate)엔 지배/비지배 개념 자체가 없어 "controlling_ni = net_income"을
회계정의상 항상 강제한다. 표본(00428251 2003H1 separate) report_lines 원문을 직접 조회해
"지배/비지배" 라벨이 아예 없는 순수 별도재무제표임을 확인, net_income=controlling_ni=
31,996,643,000으로 규칙과 정확히 일치. **T3는 controlling_ni에 아무것도 직접 주입하지
않았고**(코드 그대로), net_income이 채워지자 그 아래 있던 별개의 기존 규칙이 자연스럽게
따라 채운 것 — 설계 의도("없는 개념을 만들지 않는다")도 위배하지 않는다(separate에서
controlling_ni=net_income은 없는 개념을 만드는 게 아니라 원래 존재하는 항등식이다).

**Gate B 구조적 무해성**: T3 대상 기간(FY1999~2008)의 gate_status는 286개사 전체가
`pending 13,808 / pass 0 / fail_a 0 / fail_b 0` — 이 시대는 XBRL(Track A)이 없고
Track B 소스도 이 population엔 없어(T4 설계문서 §5-3과 동일 사실) Gate B가 애초에
감사를 시작조차 못 한다. 따라서 net_income을 몇 건을 채우든 pending→fail로 넘어갈
경로 자체가 없다 — fail_a 증가 0은 이번 측정의 우연이 아니라 **구조적으로 보장**된다.

재현: `scripts/snapshot_t3_r29_before_after_2026-08-16.py --mode {before,after,diff}` ·
`scripts/gateb_audit.py --source v3 --corp-file scripts/eps_r28_target_corps_2026-08-15.txt --recheck`

---

## 5. T4 — 단위 배수 과대적용 (★이번 세션 신규 발견)

### 5-1. 발견 경위와 증상

T1 그룹 B1 규명 중 발견했다(§2-2). 20000628000052(한화투자증권 2000FY) IS 표 전체가
`unit_source='doc_default'`, `adecimal=-6`(백만원)으로 적재돼 있는데 **원문 raw는 이미 '원' 단위**다.

```sql
SELECT row_order, value_won, adecimal, unit_source, label_raw
FROM report_lines WHERE rcept_no='20000628000052' AND statement='IS' ORDER BY row_order LIMIT 8;
```
```
 4 |   592,320,723,000,000 | -6 | doc_default | 장외거래수수료 Brokerage commissions on OTC
11 | 3,024,692,210,000,000 | -6 | doc_default | 신용거래융자이자 Interest on margin loans
12 | 8,525,842,147,000,000 | -6 | doc_default | 채권이자 Interest on bonds
14 | 9,507,057,018,000,000 | -6 | doc_default | 증금예치금이자 Interest on deposits with KSFC
```

채권이자 8,525조원 — **물리적으로 불가능한 값**이다. 실제는 8,525,842,147원.

`value_raw`가 빈 문자열인 것도 함께 확인됐다(원문 보존 계약 위반 소지 — T4-1에서 같이 본다).

### 5-2. 규모 (실측 — `scripts/probe_unit_overscale_2026-08-16.py`)

한국 상장사 최대 총자산이 ~700조원(7×10¹⁴)이므로, **|value_won| > 1,000조(10¹⁵)는 전부 오류**다.

```
A. unit_source별
   doc_default | 11,570행 | 559필링 | 256개사
   declared    | 11,150행 | 364필링 | 172개사
   ───────────────────────────────────────────
   합계        | 22,720행 | 923필링

B. statement별   CF 7,280 · BS 6,002 · IS 4,354 · SCE 3,904 · APPR 1,180
C. 연도별        2000~ 5,624 · 2005~ 7,610 · 2010~ 1,110 · 2015~ 2,124 · 2020~ 6,047 · 2025~ 201
D. adecimal별    -6(백만원) 22,319행(98.2%) · -3(천원) 208 · 0(원) 149 · -8 44
E. 표본          value_raw 가 전부 NULL (원문 보존 계약 위반 소지)
```

**이 분해가 말해주는 것 3가지 (★설계에 직접 영향)**:
1. **레거시 K-GAAP만의 문제가 아니다** — 2020년 이후 필링에 **6,047행 / 70개사**가 있다.
   R28 population(FY1999~2008)과 **범위가 다르다** → 백필 대상을 R28 286개사로 잡으면 안 된다.
2. **특정 재무제표만의 문제도 아니다** — BS/IS/CF/SCE/APPR **전부**에 걸쳐 있다.
   즉 `_emit_section_lines` 하류가 아니라 **단위 판정 자체**가 원인이다.
3. **98.2%가 `adecimal=-6`(백만원)** — 즉 증상은 "원 단위 숫자에 백만원 배수를 먹인 것"
   하나로 수렴한다. `declared`가 절반이므로 R4-1 문서기본단위([[doc-default-unit-r4-1]])
   만의 문제가 **아니다** — 표에 선언된 단위를 읽는 경로에도 같은 증상이 있다.

`_AMOUNT_SANE_MAX`(1경) 상한 때문에 **1경을 넘어 아예 사라진 행은 이 숫자에 안 잡힌다**
— 실제 피해는 이보다 크다.

### 5-3. 왜 지금까지 안 보였나

- Gate B는 **std_v3에 올라온 표준 필드**를 감사하는데, 이 시대 filings는 애초에
  `net_income` 등이 대량 NULL이라(§4-1) 감사 자체가 안 걸렸다.
- `_AMOUNT_SANE_MAX`가 1경이라 "10¹⁵~10¹⁶" 구간은 조용히 통과한다.

### 5-4. 구현 방향 (미확정 — 조사가 먼저다)

**아직 원인 가설이 없다.** 최소 두 갈래를 먼저 갈라야 한다:

1. **단위 선언 오독** — 원문에 "(단위: 원)"인데 백만원으로 읽었나?
2. **단위 상속 오적용** — 다른 표/문서기본단위를 이 표에 잘못 상속했나
   (R4-1 `doc_default`가 절반이라 이 쪽이 유력)?
3. **원문 자체가 이상** — 제출인이 단위를 잘못 썼나?
   (그렇다면 계층2는 원문 충실전사가 원칙이므로 **고치면 안 된다** — 계층3에서 다룰 문제)

**⚠️ 계층2 원칙 충돌 주의**: "값 크기로 단위를 추론하지 않는다"는 확립된 규칙이다
([[layer2-unit-column-attribution]]). 따라서 **"값이 크니까 배수를 줄인다" 식 수정은 금지**다.
반드시 **원문 단위 선언을 어떻게 읽었는지**를 고쳐야 한다.

### 5-5. T4 TODO

→ **§6 【2순위】T4** 참조(TODO는 §6 한 곳에만 둔다).
T4-2a는 **✅완료** — `scripts/probe_unit_overscale_2026-08-16.py` +
`scripts/probe_unit_overscale_2026-08-16_results.csv`(1,637 그룹). §5-2가 그 출력이다.

---

## 6. 우선순위별 구현 방법 — 실행 TODO

> 표기: `☑`=이번 세션 완료 · `☐`=미착수 · **⛔**=사용자 승인 필요(여기서 멈춤)
> · **⏱**=장시간 명령이라 Claude가 실행하지 않고 사용자에게 전달
> ([[feedback-long-running-commands]])

---

### 【1순위】 T3 — `net_income` 결측 복구 (회수 1,142셀, 재추출 불필요)

```
☑ T3-0  재측정 스크립트 영구화 + 재현 검증
☑ T3-1  원문대조 5건                       ← 설계 전제 검증 (완료, §4-5)
☑ T3-2  재키잉 데이터파일 생성              (완료, §4-6 — 1,840그룹, §4-3과 MATCH)
☑ T3-3  설계 확정 · 승인                   (완료, 사용자 승인 2026-08-16 — 4-4절 참조)
☑ T3-4  구현 + 단위테스트 6개               (완료, §4-7 — pytest 533 passed, 회귀 0)
☑ T3-5  백필                               (완료, 사용자 실행 — 286개사·51,403행·1,267초)
☑ T3-6  검증                               (완료, §4-8 — 전항목 PASS)
☑ T3-7  R29 등재                           (완료, `docs/PARSING_RULES.md` R29) · 커밋/push는 사용자 승인 대기
```

**T3-1 — 원문대조 5건 (설계 전제 검증)**
- 방법: `scripts/measure_r28_net_income_gap_2026-08-16.py --samples 20`의 출력에서
  5건을 고르고, 각 `rcept_no`의 원문 XML을 열어 **① 그 행이 정말 그 표의 헤드라인 NI 행인지
  ② `report_lines.value_won`이 원문×표선언단위와 일치하는지**를 확인한다.
- **왜 필요한가**: §4-1 D의 1,142는 `label_raw LIKE '%순이익%' AND LIKE '%주당%'`라는
  문자열 근사다. 이게 틀리면 설계 전체가 무너진다([[feedback-verify-against-source]]).
- **표본 선정 기준**: `separate` 4건 + `consolidated` 1건, FY는 2003·2004·2006을 섞고,
  §5-2의 단위 과대적용 필링(예: 00231691)을 **최소 1건 포함**한다
  (T4와의 간섭을 미리 본다).
- **완료조건**: 5건 전부 ①②가 일치. **1건이라도 어긋나면 T3-3으로 진행하지 말고 재설계.**

**T3-2 — 재키잉 데이터파일 생성 (DB 무변경)**
- 산출: `fin2/extract/data/eps_kgaap_ni_recovery_keys_2026-08-16.json`
  (또는 계층3 소비이므로 `fin2/layer3/data/` — 위치는 T3-3에서 확정)
- 형식: `{"corp_code|fiscal_year|fiscal_period|basis": ["label_raw", ...]}`
  — §4-3에서 검증한 1,840그룹 / 최대 2라벨.
- 생성 스크립트: `scripts/build_ni_recovery_keys_2026-08-16.py`
  — 입력 `eps_kgaap_headline_not_eps_keys_2026-08-15.json`(2,205키) + `filings` 조인.
- **완료조건**: 그룹 1,840 · rcept 미매칭 0 · 라벨 최대 2 (§4-3 수치 재현).

**T3-3 — 설계 확정 ☑완료·승인됨(2026-08-16)**

R24(`_ni_attribution_structural_candidates`)의 `stage="structural"` 값을 코드에서
직접 확인(`combine.py:1932,1938`)한 뒤, 아래 5개 항목을 사용자에게 결정 질문으로
제시해 **전부 권장안대로 승인받았다**:

- **(a) 키 위치** — `fin2/extract/data/eps_kgaap_ni_recovery_keys_2026-08-16.json`
  **그대로 유지**(T3-2에서 이미 이 위치에 생성됨). curated 원본 키 파일과 같은
  디렉토리라 출처 추적이 쉽고, 기존 `_load_kgaap_keys()` 관례와도 일치.
- **(b)+(c) 대상 canonical** — **`is.net_income` 하나만**. `is.controlling_ni`는
  채우지 않는다 — K-GAAP 구서식엔 지배주주 개념 자체가 없는 경우가 많아, 채우면
  "없는 개념을 만드는" 위험이 있다(무손실 원칙 위반 방향).
- **(d) 신규 후보의 `stage` 값** — **`"structural"`**(R24와 완전히 동일한 값).
  새 순위 체계를 만들지 않고 기존 stage-rank 관례를 그대로 재사용한다.
- **(e) 기존 후보가 이미 있을 때** — **주입하지 않는다**(보수적). 이 population은
  애초에 `account_mapper`가 거대 병합 라벨 때문에 `confidence<0.88`로 탈락시켜
  `cands["is.net_income"]` 자체가 비어 있는 경우가 대부분이라(§4-3 근거), 다른
  경로로 이미 후보가 있다면 그쪽이 더 신뢰할 만하다고 보고 손대지 않는다. R24처럼
  "항상 extend, 경합은 `_resolve()`가 처리"하는 방식과 달리, T3는 R24와 달리
  "구조적으로 항상 정답"이라는 보장이 없어(§4-1 D의 96.2%는 문자열 근사 매치였고,
  T3-1로 5/5는 확인했지만 전수는 아님) **파급범위를 최소로 유지**하는 쪽을 택했다.

**주입 함수 시그니처(확정)**:
`_kgaap_headline_ni_candidates(rows, corp, fy, period, basis) -> {"is.net_income": [cand]}`
— `_ni_attribution_structural_candidates`와 동일한 모양이나 대상 canonical이 1개뿐이고,
기존 후보 존재 시 no-op이라는 점이 다르다.

**T3-4 — 구현**
- `fin2/layer3/combine.py`:
  1. 재키잉 키 로더(모듈 로드 시 1회, `_load_kgaap_keys()` 패턴과 동일).
  2. `_kgaap_headline_ni_candidates()` 신설.
  3. `_map_rows(rows, period, basis, statements, corp=None, fy=None)`로 **선택 인자 추가**
     — `corp`/`fy`가 없으면 주입기 no-op(기존 테스트 무변경).
  4. `_map_rows()` 1984행 옆에 주입 호출 추가(`"IS" in stmt_set` 가드 안).
  5. 호출부 3곳(`combine.py:2023, 2070, 2080`)에 `corp=corp, fy=fy` 전달.
- 단위테스트 3개 → `fin2/tests/test_combine_kgaap_ni_recovery_r29.py`:
  - (a) curated 키의 라벨 → `is.net_income` 후보로 주입된다.
  - (b) curated 키 **밖**의 같은 모양 라벨 → 주입되지 않는다(파급범위 0 증명).
  - (c) 이미 `is.net_income` 후보가 있으면 주입하지 않는다(T3-3 (e) 동작).
- **완료조건**: 신규 3개 통과 + `pytest tests/ fin2/tests/` **527 유지**(무관 기존 실패 1건).

**T3-5 — 백필 ⏱**
`before` 스냅샷 완료(2026-08-16, `scripts/snapshot_t3_r29_before_after_2026-08-16.py
--mode before` → `scripts/t3_r29_snapshot_before_2026-08-16.json`: report_lines
11,097,669행/체크섬 17277832976707756881, std_v3 51,403행, 286개사 — T3 recovery
key population과 R28 286개사 target list가 **정확히 동일**함을 재확인).

```bash
.venv/bin/python scripts/build_std_v3.py --corp "$(paste -sd, scripts/eps_r28_target_corps_2026-08-15.txt)" --year-min 1999
```

**T3-6 — 검증** (전부 하드 숫자로)

```bash
.venv/bin/python scripts/snapshot_t3_r29_before_after_2026-08-16.py --mode after
```

```bash
.venv/bin/python scripts/snapshot_t3_r29_before_after_2026-08-16.py --mode diff
```

```bash
.venv/bin/python scripts/measure_r28_net_income_gap_2026-08-16.py --samples 20
```

```bash
.venv/bin/python scripts/gateb_audit.py --recheck
```

```bash
.venv/bin/python -m pytest tests/ fin2/tests/
```

| 항목 | 기준 |
|---|---|
| layer 2 불변 | `diff --mode diff`의 report_lines 체크섬 — before/after **완전 일치**(T3는 재추출을 안 하므로 당연히 그래야 함) |
| 의도한 효과 | `diff --mode diff`의 net_income NULL + `measure_r28_net_income_gap` 재실행 → **1,187 → ≤45** |
| 대상 내 비대상 필드 | `diff --mode diff`의 field-by-field — **net_income 외 필드는 diff 0**(controlling_ni 포함 — T3-3에서 채우지 않기로 함) |
| Gate B | `scripts/gateb_audit.py --recheck` — fail_a/fail_b **증가 0**(늘면 §8-2/T3-3 리스크#2대로 "신규 검사 도달" vs "회귀" 분해) |
| pytest | `pytest tests/ fin2/tests/` **533 passed**(527 기존 + T3-4 신규 6, 무관 기존 실패 1건 그대로) |

> ⚠️ Gate B fail이 늘 수 있다 — NI가 처음 채워지면 항등식 검사가 **처음으로 실행되는**
> 셀이 생긴다. 늘면 **즉시 중단하지 말고 "신규 검사 도달" vs "실제 회귀"로 분해**한다
> (R28 Phase 5-3과 같은 계열).

**T3-7** — `docs/PARSING_RULES.md`에 **R29** 등재 → 커밋 → push → 메모리 갱신.

---

### 【2순위】 T4 — 단위 배수 과대적용 (22,720행, 신규 발견)

```
☑ T4-2a 탐지·규모측정 스크립트 + CSV
☐ T4-1  원문대조 5건                       ← 원인 갈래 확정
☐ T4-2b 22,720행 자동 분류
⛔ T4-3  설계 확정 · 승인
☐ T4-4  구현 + 백필 + 검증               ⏱
☐ T4-5  R30 등재 + T1 그룹B1 해소 확인
```

**T4-1 — 원문대조 5건 (원인 갈래 확정)**
- 표본 선정은 `scripts/probe_unit_overscale_2026-08-16_results.csv`에서:
  `doc_default` 2건 + `declared` 2건 + **2020년 이후 1건**(§5-2 관찰 1 — 레거시 전용이
  아님을 확인해야 한다).
- 각 건에 대해 기록할 것: ① 원문의 단위 선언 텍스트 원본 ② 그 선언이 어느 표/열에 걸려
  있는지 ③ 코드가 그 선언을 어디서 읽어 배수를 정했는지(**파일:줄**)
  ④ `value_raw`가 왜 NULL인지.
- **완료조건**: 5건 전부 "선언 원문 → 적용 배수" 경로가 파일:줄로 특정된다.

**T4-2b — 자동 분류**
- 22,720행을 §5-4의 세 갈래(①선언 오독 ②상속 오적용 ③원문 자체 이상)로 분류.
- 술식: R28 §4-B에서 검증된 **형제 행 자릿수 분포 대조**를 재사용한다 —
  같은 표 안 형제 행들의 자릿수 최빈값과 어긋나는 행을 찾는 방식.
- **완료조건**: 세 갈래 비중이 숫자로 나온다. **③이 다수면 설계 방향이 완전히 달라진다**
  (계층2는 원문 충실전사라 고치면 안 되고 계층3 문제가 된다).

**T4-3 — 설계 확정 ⛔사용자 승인**
- **금지 사항 명시**: "값이 크니 배수를 줄인다"류 수정 금지
  ([[layer2-unit-column-attribution]]). 반드시 **선언 판독 경로**를 고친다.
- ③으로 분류된 건은 계층2에서 손대지 않는다 — 별도 결정 항목으로 남긴다.
- `_AMOUNT_SANE_MAX`(현재 1경) 조정 여부는 **별건으로 다룬다** — 상한을 낮추면
  오염이 결측으로 바뀔 뿐 근본 해결이 아니다.
- 백필 범위를 여기서 확정한다. **R28 286개사로 잡으면 안 된다**(§5-2 관찰 1).

**T4-4 — 구현 + 백필 + 검증 ⏱**
- 백필 대상: 923필링(+T2 대상과 합집합 여부는 §7).
- 검증: `probe_unit_overscale` 재실행 → `>10¹⁵` **22,720 → 0** /
  비대상 불변(체크섬) / Gate B 무증가 / pytest 회귀 0.

**T4-5** — `docs/PARSING_RULES.md` **R30** 등재 + **T1 그룹 B1 3건 해소 확인**(§2-3 T1-2).

---

### 【3순위】 T2 — 헤더규칙 "기수" 전사 소급 백필 (코드는 이미 수정됨)

```
⏱ T2-1  전수 스캔 스크립트 (SD카드)
⛔ T2-2  재추출 범위 확정 · 승인
☐ T2-3  표적 재추출 (+ note_lines 배선 결정)
⏱ T2-4  build_std_v3 재빌드
☐ T2-5  검증
☐ T2-6  데일리 배선 무변경 확인
```

**T2-1 — 전수 스캔 ⏱**
- 스크립트: `scripts/scan_header_rule_gisu_impact_2026-08-16.py`
- 판정식(§3-3): 첫 셀이 `제\s*\d+\s*기`에 걸리고 **동시에** `원|%`를 포함하면 영향 행.
- **★원문 대량 read는 SD카드**(`/Volumes/dart_data/raw_report`)를 직접 지정
  ([[feedback-bulk-read-use-sdcard]]) — NAS(SMB) 전수 스캔은 조용히 죽는다.
- 산출: `scripts/header_rule_gisu_affected_filings_2026-08-16.csv`
  (`rcept_no, corp_code, fiscal_year, statement_hint, n_affected_rows, sample_label`)

**T2-2 — 범위 확정 ⛔사용자 승인**
- 대상 필링/개사 수를 보고 재추출 범위를 정한다.
- 동시에 **T4 대상과 합집합으로 묶어 한 번만 재추출할지** 결정한다(§7).

**T2-3 — 표적 재추출 (★배선 결정 필요)**
- 본문: `scripts/reload_report_lines_corp.py --corp <...>`
- **주석: 현재 경로가 없다.** `reload_report_lines_corp.py:60`이 `include_notes=False`라
  note_lines를 만들지 않는다. 둘 중 하나를 **승인받아야** 한다:
  - (i) `--include-notes` 플래그 신설 + `store_note_lines()` 배선 (기존 스크립트 확장)
  - (ii) note_lines 전용 재적재 스크립트 신설
  → **(i) 권장** — 호출부가 하나로 유지되고, 데일리 파이프라인과 같은 함수를 쓴다.

**T2-4 — 계층3 재빌드 ⏱** `scripts/build_std_v3.py --corp <...>`

**T2-5 — 검증**

| 항목 | 기준 |
|---|---|
| 의도한 효과 | `note_lines WHERE header_hint='기수' AND label_raw ~ '원\|%'` **501 → 0** |
| 회귀 없음 | `header_hint='기수'`로 **남는** 행 = **5,218**(=5,719−501) 유지 |
| 본문 증가 | 재추출 전후 `report_lines` 행수 증가분이 스캔 예측치와 일치 |
| Gate B | fail_a/fail_b 증가 0 |
| pytest | 527 passed |

**T2-6** — [[parser-pipeline-integration-runbook]] ①(데일리 배선) 확인.
코드는 공용 함수라 배선 변경이 없어야 하지만, `collect_new.py`의 **두 call site**
(메인 ④-3 · `--standardize-only` 재개)가 무변경임을 **명시적으로 확인**한다.

---

### 【4순위】 T1 — 잔여 13키 (목표는 수정이 아니라 규명·문서정정)

```
☑ T1-0  13키 복원 + 원인추적 스크립트 영구화
☐ T1-1  그룹A 6건 원문대조
☐ T1-2  그룹B1 3건 — T4 후 재측정만
☐ T1-3  그룹B2 4건 원인 특정
☐ T1-4  R28 설계문서 §8 정정
```

**T1-1 — 그룹 A 6건 원문대조**
```bash
.venv/bin/python scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode run --rcept 20031114000665,20031114001721,20031202000019,20040619000015,20041115000296,20051111000339
```
- 위 출력의 `col_index`/`value_won`을 원문 XML의 해당 행 셀과 대조해
  **"당기 열이 원문에서 공란인가"**를 확정한다.
- (a) 공란 → **손실 아님**. 불변식 검사식을 `col_index=0 적재 정책 감안`으로 정정하고 종결.
- (b) 값이 있는데 col 1로 갔다 → **열 귀속 결함**. **이 트랙에서 고치지 말고
  별도 트랙으로 승격**한다(`cum_map`/`multicol`은 전 기간·전 회사 공용 로직).

**T1-2 — 그룹 B1 3건**: 별도 작업 없음. T4-4 백필 후
`scripts/probe_eps_r28_residual13_2026-08-16.py` 재실행 → 13 → 10이 되는지만 확인.

**T1-3 — 그룹 B2 4건 원인 특정**
```bash
.venv/bin/python scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode gates --rcept 20020330000386,20060512002144,20070330001121,20070814000766
```
- `--mode gates`가 셀 원문과 `_split_label_amounts`의 `(label, amount_cells)`를 함께
  찍으므로, 어느 분기에서 금액이 라벨로 넘어갔는지 특정할 수 있다.
- ⚠️ `_split_label_amounts`는 R19(주석번호 가드) 등이 얹힌 **전역 공용 함수**다.
  **원인만 확정하고 수정은 하지 않는다** — 수정 여부는 별도 승인.

**T1-4** — R28 설계문서 §8 "후속트랙" 1번에 결과 반영 +
**"마지막 행 드롭" 가설이 반증됐음을 명시적으로 정정**.

---

## 7. 재추출 비용 절약 — T2 · T4 묶기

T2(헤더규칙)와 T4(단위)는 **둘 다 전수 스캔 → 표적 재추출** 구조다.
따로 돌리면 재추출을 두 번 한다. **T4-3 설계가 승인된 뒤 두 대상 집합의 합집합으로
재추출을 한 번만 실행하는 것**을 권한다.

단 이렇게 묶으면 **문제가 생겼을 때 어느 수정 탓인지 가려내기 어려워진다.**
R28 Phase 5-3에서 실제로 R27 부수효과와 R28 효과가 섞여 원인 분해에 시간이 들었다.
→ **묶을 경우 재추출 전 스냅샷을 반드시 남기고**(`snapshot_eps_r28_before_after` 패턴),
**한 수정씩 코드를 켜고 끄며 각각의 delta를 먼저 소규모 표본으로 측정**한 뒤 합쳐 실행한다.

**이 묶기 여부는 T2-2 / T4-3 시점에 사용자가 결정한다.**

---

## 8. 공통 검증 규약 (4개 트랙 전부)

R28 세션에서 실효가 확인된 것들을 그대로 따른다:

1. **전후 스냅샷 필수** — DB를 바꾸기 전에 반드시 `before` 스냅샷.
   `scripts/snapshot_eps_r28_before_after_2026-08-15.py`가 (a)대상행 (b)키매칭행
   (c)전사 행수+체크섬 (d)std_v3 를 뜨는 검증된 패턴이니 트랙별로 복제해 쓴다.
2. **"의도한 효과"와 "비대상 불변"을 따로 센다** — 전자는 하드 숫자로, 후자는 diff 0으로.
   diff가 0이 아니면 **즉시 중단하지 말고 개별 원인을 분류**한다(R28 Phase 5-3의 교훈:
   R27 부수효과가 섞여 있었고 정직한 분해로 해결됐다).
3. **원문 대조 최소 5건** — 집계로 끝내지 않는다([[feedback-verify-against-source]]).
4. **Gate B 재감사** — `scripts/gateb_audit.py --recheck`. fail 증가는 차단 사유.
   단 **대상 기간 밖의 신규 fail은 데일리 파이프라인이 처리 중 수집한 최신 필링일 수 있으니
   기간으로 갈라서 본다**(R28에서 실제로 그랬다).
5. **`pytest tests/ fin2/tests/`** — 루트 범위로 돌리면 NAS 심링크에서 멈춘다
   ([[feedback-pytest-scope-raw-report-symlink]]). 현재 기준선 **527 passed
   (무관 기존 실패 1건)**.
6. **장시간 명령은 Claude가 실행하지 않는다** — 명령만 만들어 사용자에게 전달
   ([[feedback-long-running-commands]]). R28 세션에서 이 규칙을 한 번 어겼다(멱등이라 무손상).

---

## 9. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| 1 | **T4가 계층2 원칙과 충돌** — "값 크기로 단위 추론 금지" | 값 크기는 **탐지용**으로만 쓰고, 수정은 반드시 단위 선언 판독 경로에서 한다(§5-4) |
| 2 | **T3로 NI가 채워지면 Gate B fail이 새로 생길 수 있다** | 새 fail은 "회귀"가 아니라 "처음으로 검사 가능해진 셀"일 수 있다. 기간·원인별로 분해해 판정(§8-2) |
| 3 | **T2 note_lines 재적재 경로가 없다** — reload 스크립트가 `include_notes=False` | T2-3에서 플래그 신설 vs 전용 스크립트를 승인받고 진행 |
| 4 | **T1 그룹A가 (b)로 판명되면 범위가 폭발** | 그 경우 이 트랙에서 고치지 않고 **별도 트랙으로 승격**한다(공용 열귀속 로직) |
| 5 | **T2·T4 합산 재추출이 크다** | 스캔으로 대상을 좁히고(옵션 B), 스냅샷+단계 분해로 원인 추적성을 확보(§7) |
| 6 | ~~R28 스냅샷 JSON 2개(각 42MB)는 **git 미추적 로컬 파일**이라 유실 위험~~ | **완화됨(2026-08-16)** — T1-0에서 13키를 `scripts/eps_r28_residual13_2026-08-16.json`으로 영구화했다. 스냅샷이 사라져도 13키는 남는다(복원 스크립트 재실행만 불가, §10-3) |
| 7 | **T4 백필 범위를 R28 286개사로 잡는 실수** | §5-2 관찰 1 — 2020년 이후에도 6,047행/70개사가 있다. 범위는 T4-3에서 스캔 결과로 새로 정한다 |
| 8 | **§4-1 D의 1,142가 문자열 근사** — 이 위에 설계를 얹었다 | T3-1 원문대조 5건이 전제 검증. **1건이라도 어긋나면 T3-3으로 넘어가지 않는다** |

---

## 10. 산출물

### 10-1. 이번 세션에 저장소로 들어간 것 (✅완료, 전부 재실행 검증함)

| 파일 | 트랙 | 역할 |
|---|---|---|
| `scripts/probe_eps_r28_residual13_2026-08-16.py` | T1-0 | 잔여 13키 복원(스냅샷 `after` − curated 키) |
| `scripts/eps_r28_residual13_2026-08-16.json` | T1-0 | 위 산출물(13키) |
| `scripts/probe_eps_r28_residual13_cause_2026-08-16.py` | T1 | 드롭 지점 추적 `--mode gates\|run\|trace` (스크래치패드 probe 4종 통합) |
| `scripts/measure_r28_net_income_gap_2026-08-16.py` | T3-0 | §4-1 A~D 재측정 |
| `scripts/probe_unit_overscale_2026-08-16.py` | T4-2a | §5-2 A~E 탐지·규모측정 |
| `scripts/probe_unit_overscale_2026-08-16_results.csv` | T4-2a | 위 산출물(1,637 그룹) |
| 이 문서 | 전체 | 설계 |

> 스크래치패드 probe 4종(`_cause.py`/`_cause2.py`/`_realrun.py`/`_groupb_gate.py`)은
> 같은 질문을 반복 정제한 것이라 **`_cause_2026-08-16.py` 하나의 3개 모드로 통합**했다.
> 세 모드가 §2-2의 그룹 A/B1 판정을 그대로 재현하는 것을 확인했다.

### 10-2. 구현 단계에서 새로 만들 것

| 파일 | 트랙 |
|---|---|
| `scripts/build_ni_recovery_keys_2026-08-16.py` + `..._keys_2026-08-16.json` | T3-2 |
| `fin2/tests/test_combine_kgaap_ni_recovery_r29.py` | T3-4 |
| `scripts/scan_header_rule_gisu_impact_2026-08-16.py` + 결과 CSV | T2-1 |
| `docs/PARSING_RULES.md` **R29**(T3) · **R30**(T4) | T3-7 / T4-5 |

### 10-3. 유실 위험 (여전히 남음)

`scripts/eps_r28_snapshot_{before,after}_2026-08-15.json`(각 42MB)은 **git 미추적 로컬 파일**이고
13키 복원의 유일한 근거다. 다만 `eps_r28_residual13_2026-08-16.json`이 이제 저장소에 있으므로
**스냅샷이 사라져도 13키 자체는 남는다**(복원 스크립트 재실행만 불가).

---

## 11. 다음 행동

**T3-1(원문대조 5건)부터 시작한다.** 회수 규모(1,142셀)가 가장 크고 재추출이 필요 없어
되돌리기도 가장 쉽다. 배선 지점은 §4-3에서 이미 확정했으므로(구 T3-2 "배선 특정"은 완료),
남은 선행 작업은 **원문대조 5건**뿐이다.

진행 순서: `T3-1 → T3-2(재키잉 파일) → T3-3(설계) ⛔여기서 멈춤`.

**T3-3 설계까지 만든 뒤 반드시 멈추고 승인을 받는다** — 이 문서는 설계 문서이지
실행 허가가 아니다([[feedback-plan-then-wait]]).

### 이 문서가 근거로 삼은 수치를 재현하는 법

```bash
.venv/bin/python scripts/probe_eps_r28_residual13_2026-08-16.py
```

```bash
.venv/bin/python scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode run
```

```bash
.venv/bin/python scripts/measure_r28_net_income_gap_2026-08-16.py --samples 20
```

```bash
.venv/bin/python scripts/probe_unit_overscale_2026-08-16.py
```
