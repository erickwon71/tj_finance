# Gate B fail_a 482건 백로그 — 클러스터 A(cash)·B(두산밥캣 FX) 설계 (2026-08-27)

상태: **✅ 사용자 승인 후 구현·검증 완료.** A-3(①concept_map.py 등록 ②P1C-2 게이트 완화)
+ B-2(최소안, 카탈로그 1행 추가) 전부 구현. `pytest` 632 passed(회귀 0). 영향받은
31개사 재감사 결과 DB 전체(fy≥1999, v3) fail_a **482→170(−312, −65%)**, std_v3
재백필 없이 검증기 수정만으로 달성. `docs/PARSING_RULES.md` R50 등재 완료.
잔존 cash 8건(00245472 단위스케일 버그·00148832 제주은행 반대방향 패턴)은
클러스터A와 다른 원인으로 분리, 클러스터C(~137건)는 여전히 미착수.

배경: R49 트랙 종료([[gateb-r49-stale-hypothesis-falsified-two-real-bugs-2026-08-27]])
직후 발견된 별도 백로그. `face_audit` 테이블 기준 fy≥1999·source_version='v3'·
gate_status='fail_a' 482행을 필드별로 트리아지했다(전체 분포는 세션 대화 참고).
cash 필드가 324건(전체의 67%)으로 압도적 1위, 두산밥캣(01032486) 1개사가 단일
필링에서 21개 필드를 동시에 fail시키는 것이 그다음 특이 케이스. 이 문서는 이
두 클러스터만 다룬다 — 잔여 ~158건(trade_payables/dividends_paid/revenue/
inventory 등 산발 클러스터 C)은 범위 밖(다음 세션 별도 조사).

**핵심 결론(양쪽 클러스터 공통): std_v3 자체는 정답이고, `face_audit.py`(Gate B
독립 검증기)가 최신 필링 포맷/기간을 못 따라가 오탐하고 있다.** 즉 데이터
재백필은 필요 없고, 검증기 코드만 고치면 된다.

---

## 클러스터 A — cash 324건: `concept_map.py`에 금융업 XBRL 개념 누락

### A-1. 근본원인

두 개의 서로 다른 매핑 사전이 존재한다:

- **std_v3 실값 경로**: `report_lines`(Layer2, 라벨 텍스트) →
  `parser/common/account_mapper.py` → `account_maps/bs_accounts.py`. 여기엔
  "현금및예치금" → `bs.cash_deposits_combined` 별칭이 **이미 등록돼 있다**
  (`account_maps/bs_accounts.py:46-52`, 2026-07-18 사용자 확정,
  `fin2/standardize/rules.py::rule_cash_with_deposits`가 최종 합산).
- **face_audit 독립 검증 경로**: `read_report_face_xbrl()`
  (`fin2/audit/face_audit.py:653`)이 `TE[@ACODE]` 태그만 읽고, canonical은
  `fin2/taxonomy/concept_map.py`(XBRL 개념명 → canonical, 라벨 텍스트 무관)로
  결정한다. 이 사전엔 cash 관련 항목이 3개뿐이다:
  ```python
  "ifrs-full_CashAndCashEquivalents": "bs.cash",                              # :24
  "dart_CashAndCashEquivalentsAtBeginningOfPeriodCf": "cf.beginning_cash",     # :163
  "dart_CashAndCashEquivalentsAtEndOfPeriodCf": "cf.ending_cash",              # :164
  ```
  금융업(증권/캐피탈/지주) 전용 확장개념 **`dart_CashAndDuefromBanks`**
  ("현금및예치금" 결합 라인)가 없다.

### A-2. 실측 검증

한국금융지주(00432102) 2023 FY 별도 원문(`raw_report/.../20250320000836.xml`)
대조:

| 위치 | ACODE | 표시값 | 원화환산 |
|---|---|---|---|
| BS 별도, 유동자산 첫 줄("현금및예치금") | `dart_CashAndDuefromBanks` | 941,413,038 | 941,413,038 |
| (동일 표, 참고용 하위 개념) | `ifrs-full_CashAndCashEquivalents` | 937,413,038 | 937,413,038 |

std_v3 `cash` = **941,413,038** = BS 원문 "현금및예치금" 라인과 정확히 일치
(정답). face_audit `cands`(canon=`bs.cash`)엔 `ifrs-full_CashAndCashEquivalents`
값(937,413,038)만 잡히고 `dart_CashAndDuefromBanks`(941,413,038)는 canonical
resolution 자체가 안 돼 후보에 못 들어간다 → 차액 정확히 4,000,000
(예치금 성분) → `VALUE_DIFF` 오탐.

같은 ACODE(`dart_CashAndDuefromBanks`)가 KB금융·iM금융지주·JB금융지주·
하나금융지주·대신증권·유안타증권·삼성카드·제주은행·한화투자증권·한국캐피탈·
교보증권 등 클러스터 A의 다수 기업 원문에서 공통 확인됨(grep 표본). 연결
basis에서 db_won/report_won 비율이 1.2~5배대로 흩어지는 것도 "예치금 성분
비중이 회사마다 다름"과 일치(순수 스케일/단위 버그였다면 비율이 10/100/1000
배수로 딱 떨어져야 하는데 실측 분포는 그렇지 않음 — 성분 누락 가설과 부합).

★ 2026-08-22 `bs.cash` 감사 코드에 이미 "P1C-2 cash+deposits identity
check"(`fin2/audit/face_audit.py:1485-1505`)가 들어가 있으나, 이건
`by_canon["bs.deposits"]`가 **비어있지 않을 때만** 동작한다. `concept_map.py`
갭 때문에 `bs.deposits`도 `bs.cash_deposits_combined`도 애초에 채워지지
않으므로 이 우회로직 자체가 트리거되지 않는다 — P1C-2는 설계 시점에 이
갭을 몰랐던 것으로 보임.

### A-3. 제안 수정 (2곳, 둘 다 필요)

**① `fin2/taxonomy/concept_map.py`에 1줄 추가**:
```python
"dart_CashAndDuefromBanks": "bs.cash_deposits_combined",
```
(account_maps/bs_accounts.py의 기존 라벨 별칭과 동일 canonical로 맞춤 —
새 canonical 신설 아님, 기존 P1C-2 로직이 그대로 소비 가능한 키.)

**② `fin2/audit/face_audit.py`의 P1C-2 게이트(:1485 부근) 완화** — 현재는
"예치금 후보(`bs.deposits`)가 있을 때만" 우회 체크를 시도한다. ①만 추가하면
`bs.cash_deposits_combined`는 채워지지만 `bs.deposits`가 계속 비어있는
필링(예: 예치금이 결합 라인 하나로만 태깅되고 별도 개념이 없는 경우)은 여전히
안 잡힌다. `dep_vals`가 비어 있어도 `combined_vals`가 `val`과 **직접 정확히
일치**하면 PASS하도록 분기 추가:
```python
if not dep_vals and combined_vals and val in combined_vals:
    results.append(FieldAudit(field, canon, val, True, None,
                              report_value_won=val, evidence=EVIDENCE_E4_IDENTITY))
    continue
```

### A-4. 미확인 사항 (구현 전 확인 필요)

- ①만으로 324건 중 몇 건이 실제로 해소되는지 **정식 스크립트로 전수 재시뮬레이션
  안 함**(세션 중 25건 수동 표본 대조는 ADECIMAL 스케일 처리를 안 해 신뢰 못함,
  버려야 함). 구현 직후 `gateb_audit.py --recheck`로 실측 필요.
- `dart_CashAndDuefromBanks` 외에 예치금 계열의 다른 미등록 ACODE(예: 순수
  "예치금" 단독 개념)가 있는지는 표본 2개사만 확인했고 전수는 안 함.
- ②의 "직접 일치" 폴백이 과관용(다른 계정과의 우연일치)을 일으킬 위험은
  exact-won 일치 요구로 낮다고 보이나, 기존 R23/R32 트랙처럼 실측 검증 없이
  단정하지 않음.

---

## 클러스터 B — 두산밥캣(01032486) 2026H1: FX 카탈로그 미갱신

### B-1. 근본원인

두산밥캣 연결재무제표는 "지배기업 기능통화는 원화이나 연결재무제표는
달러(USD) 표시"인 특이 케이스로, 이미 R25(2026-08-15)에서 발견·처리됐다.
`face_audit.py:1134`의 정적 카탈로그:
```python
_FX_PRESENTATION_CURRENCY_KEYS: frozenset[tuple[str, int, str, str]] = frozenset({
    ("01032486", 2024, "FY", "consolidated"),
    ("01032486", 2025, "FY", "consolidated"),
    ("01032486", 2025, "H1", "consolidated"),
    ("01032486", 2025, "Q1", "consolidated"),
    ("01032486", 2025, "Q3", "consolidated"),
    ("01032486", 2026, "Q1", "consolidated"),
})
```
이 키에 해당하면 정상 대조를 건너뛰고 PENDING 처리한다(fail 아님). **2026
H1은 이 목록에 없다** — 그래서 정상 대조 경로로 떨어져 USD 원값을 원화로
착각, 21개 필드 전부가 동일 비율(~1541배)로 어긋난 것으로 fail_a 처리됐다.

std_v3 값 자체는 정답이다: `total_assets=13,590,943,000,000`은
[[p2-2026-08-19-doosanbobcat-anam-zero-rows-rootcause]]에서 이미 원문
"자산총계 13,590,943(백만원)"과 정확히 대조·확정된 값과 동일하다(2026-08-19
세션에 재다운로드+재표준화로 복구, 이후 재퇴행 없음 — DB 값은 그대로 정답,
검증기 카탈로그만 안 따라감).

### B-2. 제안 수정

**최소안(권장)**: 목록에 누락 기간 추가.
```python
    ("01032486", 2026, "H1", "consolidated"),
```
기존 패턴 그대로 유지 — 위험 거의 없음(다른 기업/기간에 전혀 영향 없는
정확 키 매칭).

**구조안(선택, 이번엔 권장 안 함)**: 매 분기 반복되는 유지보수 부담을 없애기
위해 `(corp_code, basis) == ("01032486", "consolidated")`처럼 기업+basis
단위로 일반화. **단, 두산밥캣이 향후 원화 표시로 되돌아갈 가능성을 배제 못해
과우회(진짜 버그를 pending으로 숨김) 위험이 있음** — 근거 없이 확장하지
않는다는 기존 프로젝트 원칙([[feedback-verify-against-source]])에 따라
최소안만 제안.

### B-3. 미확인 사항

- 2026 Q3(11월경 공시 예정)도 같은 이유로 재발할 것이 거의 확실 — 다음 분기
  또 놓치지 않으려면 이 문서/`docs/PARSING_RULES.md`에 "두산밥캣 신규 필링
  나올 때마다 이 카탈로그 확인" 메모를 남겨둘 필요(구조안 채택 시 불필요).

---

## §종합 — 예상 영향

| 클러스터 | 건수 | 수정 위치 | 위험도 | std_v3 재백필 필요 |
|---|---|---|---|---|
| A(cash) | 324/482(67%) | `concept_map.py` +1행, `face_audit.py` 게이트 완화 | 낮음(exact-won 매칭만 추가) | **불필요**(검증기만 수정) |
| B(두산밥캣) | 21/482(4%) | `face_audit.py` 카탈로그 +1행 | 매우 낮음 | **불필요** |

두 클러스터 합쳐 482건 중 **최대 345건(72%)**을 face_audit.py/concept_map.py
수정만으로 해소할 잠재력이 있다(A는 실측 미완이라 상한선). 잔여 클러스터 C
(~158건)는 미조사.

## §결정 필요

1. A-3 ①+②, B-2 최소안을 **구현해도 되는지** 승인.
2. A-4의 미확인 사항(전수 재시뮬레이션)을 구현 **전에** 먼저 스크립트로
   돌려볼지, 아니면 구현 후 `gateb_audit.py --recheck` 표본으로 검증할지.
3. B-3 구조안(일반화) 채택 여부 — 기본은 최소안(비채택)으로 진행 제안.

승인 전까지 코드 수정 없음([[feedback-plan-then-wait]]).
