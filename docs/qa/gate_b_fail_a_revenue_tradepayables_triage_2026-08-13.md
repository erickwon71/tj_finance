# Gate B fail_a — revenue(186)·trade_payables(300) 잔여 triage (2026-08-13)

## 0. 범위 정정(선행)

지시받은 "revenue 2,700 / trade_payables 367"은 직전 세션 메모리 기록 오류로 확인됨 —
실제로는 `gate_status IN ('fail_a','fail_b')`(REVIEW 포함) 합산 수치였고, `fail_b`라는
라벨을 "fail_a"로 잘못 적어놓은 것. 진짜 `gate_status='fail_a'`(확정버그, 차단)만 세면
revenue **186건**·trade_payables **300건**으로, 오늘 오전 784건 triage
(`docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md`)와 정확히 같은 모집단이다.
본 문서는 그 784건 triage에서 미확정으로 남겨둔 잔여(revenue 32건, trade_payables 248건)
를 원문(raw XML)까지 내려가서 확정한 결과다.

또한 지금 DB 스냅샷(`std_financials_v3.built_at` 최댓값 08-13 01:08)은 버그#3
(`f2d232c`, trade_payables stage-rank, 08-13 08:30) **수정 전** 상태 — 사용자가
`build_std_v3.py --all --year-min 1999` + `gateb_audit.py --recheck` 백필을 별도로
진행 중이며, 완료되면 trade_payables 근접-0 52건(§2 기존 확정 버그)은 자동 해소된다.
아래 원문대조는 그 52건과 무관한 **잔여 248건**을 다룬다.

## 1. revenue 잔여 32건 — industry profile별 재확인

`std_financials_v3.industry_lines->>'profile'`로 분류(SQL, 짐작 아님):

| profile | 건수 | corp수 |
|---|---:|---:|
| securities | 154 | 15 |
| (none, 비금융) | 18 | 6 |
| insurance | 6 | 3 |
| bank | 4 | 1 |
| credit_finance | 4 | 1 |

securities 154건은 이미 확정(버그 아님, 오전 triage). 나머지 32건을 전부 원문대조.

### 1-1. ★확정버그 A — parent(총계) 대신 child(수수료수익) 선택
**대상: 00159254 한국전자홀딩스(별도 6건), 00340096 미래에셋벤처투자(연결+별도 2건) = 8건**

`report_lines`에 다음 두 행이 공존(2024FY 별도, 00159254 예):
```
('separate', 0, 'I. 영업수익', 14825987964, ..., node_role='P')   ← report_won과 정확히 일치
('separate', 0, '수수료수익', 6241740125, 'I. 영업수익', node_role='F')  ← db_won과 정확히 일치
```
canonical revenue 매핑이 **부모(P) 총계가 아니라 자식(F) 서브라인("수수료수익")을 선택**하고
있음. 00340096(미래에셋벤처투자)도 연결/별도 양쪽에서 동일 패턴("수수료수익" 자식이 선택됨,
"I. 영업수익" 부모가 무시됨) 확인. 두 회사 전 기간(FY/H1/Q1/Q3)에서 재현 — 일회성 아님.

**원인 추정**: `수수료수익`이 revenue의 별칭(alias)으로 등재돼 있고, 총계 라벨
("I. 영업수익", 로마숫자 접두)보다 stage-rank가 높게 잡히는 것으로 보임 — trade_payables
버그#3(R15)의 "숏컷이 필터를 우회" 패턴과 같은 계열이나 축이 다름(현재/비유동이 아니라
총계/하위항목). `fin2/layer3/combine.py`의 stage-rank·별칭 우선순위 확인 필요.

### 1-2. ★확정버그 B — 반기 4열 비교표에서 전기 3개월(비누적) 열 선택
**대상: 00163673 한진중공업홀딩스(별도, H1+Q3 = 2건)**

원문 XML(`20250814001174.xml`)의 별도 손익계산서는 4열 구조 `[당반기 3개월, 당반기 누적,
전반기 3개월, 전반기 누적]`이고, XBRL ACODE 4건이 정확히 이렌더링과 일치:
```
CFY2025dHYQ(당기 3개월)=654    CFY2025dHYA(당기 누적)=9,097
PFY2024dHYQ(전기 3개월)=629    PFY2024dHYA(전기 누적)=9,069
```
db_won=629,000,000(전기 3개월, **비교 목적의 prior-year 열**) — report_won=9,097,000,000
(당기 누적, **정답**)과 다른 열. `report_lines`엔 이 라벨에 대해 col_index=0 단일 행만
있고 `is_cumulative=True`로 잘못 표시돼 있음(실제로는 is_cumulative=False인 전기열) —
열/컨텍스트 선택 자체가 잘못됨. 1-1과는 다른 메커니즘(총계선택이 아니라 기간/컬럼 오선택).

### 1-3. Gate B 리더(감사기) 쪽 문제로 판정 — std_v3 버그 아님

- **01032486 두산밥캣(연결 6건, ratio ~1364배)**: 원문 확인 결과 이 회사 손익계산서가
  **같은 문서 안에 USD표(단위:천USD, table_seq=0)와 원화환산표(단위:백만원, table_seq=2,
  둘 다 제목 "연결 손익계산서" 동일, DART 관행상 외화표시 법인의 원화환산 병기)**로
  두 번 실림. `combine.py`의 외화가드(2026-08-05, `unit_source='fx_declared'` 행 제외)가
  USD표를 걸러내는 건 의도된 정책이고, 그 결과 db_won은 원화환산표(정당한 회사 공시치,
  8,551,207,000,000)를 취함 — 이건 옳다. 반대로 **Gate B의 Track A(XBRL) 리더는 USD로
  태깅된 XBRL fact(`ifrs-full_Revenue`=6,269,305, ADECIMAL=-6)를 통화단위 확인 없이
  그대로 "report_won"으로 스케일링**해서, 실제로는 USD 6.27십억(약 8.5조원 상당, 실제
  Bobcat 2024 매출과 부합)인 값을 "6,269,305,000원"이라는 터무니없이 작은 값으로 왜곡함.
  → **`fin2/audit/face_audit.py::read_report_face_xbrl`이 XBRL fact의 `unitRef`/통화를
  확인하지 않는 것이 근본원인**(std_v3 아님). 동일 유형 회사(외화표시+원화환산 병기)
  전부 재발 가능.
- **00139214 삼성화재해상보험(1건)**: 오전 triage에서 이미 "Gate B 리더 측 adecimal
  오탐지"로 판정된 것 재확인, 추가 조사 안함(중복).
- **00159102 DB손해보험(1건)**: ratio=1.0000001(diff 2백만원/17.47조) — 근사오차 수준,
  `face_audit.py`의 tolerance 로직(`tol=10**(-adecimal)`) 문제로 추정, 값 자체는 문제없음.
- **00126256 삼성생명(4건)**: ratio 0.987~0.990(1~1.3% 근접), 하위계정 정의차 의심 —
  낮은 우선순위, 미확정 상태 유지.

### 1-4. 미확정(우선순위 낮음, 원문대조 미실시)
- 00382199 신한지주(bank, 4건)·00126292 삼성카드(credit_finance, 4건): 오전 triage에서
  이미 "report_lines에 영업수익 총계 라인 자체가 없어 부분성분합산(fallback)으로
  대체됨" 확인(신한지주: 이자수익+수수료수익+보험수익 3개 성분 합만 db_won, report_won은
  더 큰 총계). 오늘 재확인만 하고 근본원인(레이어2가 왜 총계라인을 못 잡는지)은 미착수 —
  뱅킹/카드사 IS 레이아웃 전용 조사 필요, 범위가 커서 별도 세션 권장.
- 01203659 이뮨온시아(1건)·01305869 세니젠(1건): 원문대조 미실시(시간 제약).

## 2. trade_payables 잔여 248건(근접-0 52건 제외) — 체계적 확인

248건 전체를 코드로 스캔(짐작 아님): 각 fail_a 행에 대해 같은 rcept_no·basis의
`report_lines`(BS, col_index=0) 안에 **report_won과 정확히 일치하는 다른 행이 이미
존재하는지** 확인.

| 분류 | 건수 | 비율 |
|---|---:|---:|
| **report_won과 정확히 일치하는 다른 행이 이미 report_lines에 존재**(순수 선택 문제) | **191** | 77% |
| — 그중 그 일치 행이 node_role='P'(부모/총계) | 42 | |
| — 그중 그 일치 행이 node_role='F'(다른 라벨의 형제/개별 항목) | 149 | |
| 원문 추가조사 필요(note 등 다른 소스, 또는 진짜 미포착) | 57 | 23% |

**핵심 발견**: 248건 중 191건(77%)은 **데이터 자체는 이미 정확히 DB에 있다** — 계층3
(combine.py)이 여러 후보 라인 중 엉뚱한 걸 canonical `bs.trade_payables`로 골랐을
뿐이다. 대표 사례(원문 라벨 예시, 전부 SQL 실측):

- **00210856(12건)**: `매입채무 및 기타유동채무`(P, 부모, =report_won) vs
  `매입채무및기타채무`(F, 자식, 거의 같은 라벨인데 공백만 다름, =db_won) — 1-1과 완전히
  같은 "부모 총계 대신 자식 선택" 버그.
- **00971726·01494154 등**: `단기매입채무및기타채무`/`단기기타채무` 등 이형 라벨의 F행이
  report_won과 일치 — db는 다른 더 작은 행을 선택.
- **00349732**: `기타유동지급채무`·`미지급금` 등 라벨명 자체가 다양해서, 이 회사는
  "trade_payables"의 실제 표시 라벨 자체가 표준 사전에 없는 변형일 가능성.

- **01412822(12건)**: 부모/자식 문제가 아니라 **BS에 "매입채무"와 "기타채무"가 애초에
  별도 라인(형제, 결합된 부모 총계 자체가 없음)**으로 표시되는 레이아웃. db_won=59.4B
  (매입채무만). `note_lines`의 만기분석표(미할인현금흐름)에서 "매입채무 합계
  59,404백만+기타채무 합계 32,798백만=92,202백만"이 report_won(92,202,000,000)과
  정확히 일치 — **canonical trade_payables는 매입채무+기타채무 결합 스코프인데, 결합
  총계 라인이 BS에 없는 레이아웃에선 두 라인을 더해야 하고, 지금은 안 더해짐.**

- **01090471(9건, 씨아이에스)**: 위 둘과 다른 방향(db > report). 원문 확인 결과 BS
  "매입채무" 단독 라인(F, XBRL ACODE=`ifrs-full_TradeAndOtherPayablesToTradeSuppliers`)
  이 db_won(29,259,356,007)과 일치, report_won(14,346,977,735)은 **주석(공정가치/만기
  공시)의 "매입채무 외의 유동채무"(non-trade!) 항목과 우연이 아니게 정확히 일치**하며
  그 항목의 XBRL ACODE는 `ifrs-full_TradeAndOtherCurrentPayables`(더 넓은 개념, 이
  회사는 주석 안에서 "매입채무 외"라는 의미로 태깅해놓음). **Gate B Track A의 concept_map
  이 이 ACODE를 전역적으로 trade_payables에 매핑**하는데, 이 필링에선 그 태그가 BS 본문이
  아니라 노트의 "비(非)매입채무" 항목에 붙어 있어 결과적으로 잘못된(더 작은, 무관한) 값을
  ground truth로 삼음 — **std_v3가 아니라 Gate B 리더 쪽 개념 모호성 문제로 추정**(단,
  확정하려면 `ifrs-full_TradeAndOtherCurrentPayables`가 다른 필링들에서도 이렇게 쓰이는지
  추가 표본 필요, 이번엔 1개사만 확인).

## 3. 결론 및 우선순위 제안

1. **★가장 임팩트 큰 수정 대상 (trade_payables 191/248 + revenue 8건, 합쳐서 ~200건)**:
   `fin2/layer3/combine.py`의 canonical 선택 로직에 **"부모(P) 총계 라인이 존재하면
   자식(F) 서브라인보다 우선"** 규칙이 다수 케이스에서 깨져 있음(정확한 원인은 별칭
   테이블 우선순위 또는 stage-rank 문제로 추정, 코드 확인 필요). trade_payables
   버그#3(R15)와 같은 파일·같은 계열의 결함이라 **같은 세션에서 함께 고칠 가치가 큼**.
2. **01412822류(결합-총계-라인이 없는 레이아웃에서 매입채무+기타채무 미합산)**:
   별도 로직 필요 — BS에 결합 부모가 없을 때 "매입채무"+"기타채무" 자매 라인을 더해야
   하는지 여부 판단 규칙. 표본 1건만 확인, 추가 확산 규모 미상.
2. **Gate B 리더(face_audit.py) 쪽 개선 후보 2건**: (a) Track A XBRL 리더가 fact의
   통화(unitRef)를 확인 안 하는 문제(두산밥캣류, 외화표시+원화환산 병기 기업 전반 영향
   가능) (b) `ifrs-full_TradeAndOtherCurrentPayables` concept_map이 노트/본문 구분 없이
   전역 매핑되는 문제(01090471류). std_v3 코드 수정이 아니라 감사기 쪽 수정.
3. **미착수**: bank/credit_finance 영업수익 총계라인 레이어2 커버리지 갭(8건, 원인
   미규명), trade_payables 잔여 57건(개별 원문대조 필요), revenue 이뮨온시아·세니젠
   (각 1건).
4. 백필(버그#3 R15) 완료 후 재검증 시 trade_payables 근접-0 52건은 자동 해소 예상 —
   본 문서의 248/191/57 숫자는 그와 무관한 별개 잔여.

## 근거
- 전부 SQL 직접 쿼리(`face_audit.fail_detail` JSON, `report_lines`, `note_lines`,
  `std_financials_v3.industry_lines`) + raw XML grep(두산밥캣 `20250318001351.xml`,
  한진중공업홀딩스 `20250814001174.xml`, 씨아이에스 `20250807000242.xml`) 원문 직접대조.
  `[[feedback-verify-against-source]]` 준수 — 짐작 없이 전부 실측.
