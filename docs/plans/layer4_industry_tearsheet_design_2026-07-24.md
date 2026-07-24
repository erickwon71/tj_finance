# 설계 — P2 계층4: 업종별 tearsheet + 스크리너 정규화 revenue (2026-07-24)

> 상태: **설계 초안 (미실행)**. handoff §4.2 의 "P2 계층4" 준비 작업. `--recheck`/재빌드와 독립.
> **마스터 허브: [`rearchitecture_4layer.md`](rearchitecture_4layer.md)** (전체 현황·문서 맵).
> 참조: `docs/qa/handoff_layer3_profiles_2026-07-24.md` · `fin2/layer3/industry_profiles.py` ·
> `docs/prd/05_visualization.md` · `docs/prd/06_screener.md` · 메모리 [[rebuild-phase-a3-done]]

---

## 0. 한 줄 요약
금융업(보험·은행·증권)의 std_v3 **조립 revenue + `industry_lines` 성분**을 tearsheet 과
스크리너에 반영해, 일반기업 단일 `매출액` 틀로는 왜곡되는 금융사 매출을 업종 네이티브 항목으로
표시·정규화한다. **한국금융지주형(revenue NULL)은 op_income 로 대체 표시.**

---

## 1. 문제 정의 (왜 필요한가 — 실측 근거)

앱은 tearsheet(`analyzer.ratio_engine.load_standard_financials`)·스크리너
(`standard_financials` 뷰) 모두 **std_v2 (구 체인)** 를 읽는다. std_v2 에는 업종 조립 revenue 도
`industry_lines` 성분도 없다. 그래서 금융사 매출이 왜곡·과소·오선택된다.

| corp | 연도 | std_v2 revenue | std_v3 조립 revenue | profile |
|---|---|---|---|---|
| 미래에셋생명 | 2025 | 1.10조 | **5.19조** | insurance |
| 현대해상 | 2025 | 14.73조 | **17.89조** | insurance |
| 코리안리 | 2025 | 5.80조 | **6.70조** | insurance |
| 한국금융지주(연결) | 2024 | **21.2조**(수수료 오선택) | **NULL**(매출 개념 없음) | — |

- **보험/은행/증권**: std_v2 는 IFRS17 분할 IS 의 서브토탈 하나만 잡거나 순액만 잡아 과소 → std_v3
  프로파일이 `보험수익+투자수익`(보험), `이자+수수료+…`(은행), `수수료+이자+트레이딩+…`(증권) 을
  GROSS 합산(사용자 결정).
- **한국금융지주형**: std_v2 는 수수료수익 등을 revenue 로 오선택해 21조 같은 허수. std_v3 는 NULL
  (`NO_REVENUE_CORPS`, 사용자: "NaN=사실").

즉 계층4는 **금융사에 한해 std_v3 를 소비**해야 성립한다.

## 2. 데이터 계약 (std_v3 이 제공하는 것)

`std_financials_v3` (grain = corp_code, fiscal_year, fiscal_period, statement_type):

- `revenue` — 프로파일 적용 시 **조립 완료된 GROSS revenue**. 한국금융지주형은 **NULL**.
- `industry_lines` JSONB — 프로파일 성분 보존:
  - `{"profile": "insurance",  "insurance_revenue": <원>, "investment_revenue": <원>}`
  - `{"profile": "bank",       "interest_revenue": <원>, "fee_revenue": <원>, "insurance_revenue"?: <원>, "other_op_revenue"?: <원>}`
  - `{"profile": "securities", "fee_revenue": <원>, "interest_revenue": <원>, "trading_revenue"?: <원>, "other_op_revenue"?: <원>}`
  - 일반기업·미적용 = `NULL`.
- `operating_income` 이하(op_income/net_income/BS/CF)는 프로파일과 무관하게 정확 적재.

성분 키 → 한글 라벨 매핑(표시용):

| key | 라벨 |
|---|---|
| insurance_revenue | 보험수익 |
| investment_revenue | 투자수익 |
| interest_revenue | 이자수익 |
| fee_revenue | 수수료수익 |
| trading_revenue | 트레이딩손익 |
| other_op_revenue | 기타영업수익 |

> ⚠ **현 std_v3 는 stale.** 이번 세션 프로파일(securities 전체, 은행 확장 신한/KB/하나/우리/BNK/iM/JB,
> 한국금융지주 NULL)이 아직 미반영 — insurance 12사·bank 3사·securities 0사뿐. **§0 재빌드
> (`build_std_v3.py --all`) 이후에야 이 계약이 전량 성립**한다. 계층4 구현/검증은 재빌드 완료가 전제.

## 3. 아키텍처 결정 (★확정: Path A, 2026-07-24 정정)

`industry_lines`·조립 revenue 는 std_v3 에만 있다. 앱이 현재 std_v2 를 읽는다는 사실은 **무관**하다 —
**사용자는 앱을 사용 중이지 않고, std_v2 는 std_v3 교차검증용으로만 보존**된 상태이기 때문이다.
따라서 "앱을 std_v2 로 계속 돌리며 std_v3 를 부가로 얹는다"는 사이드채널(구 Path B)의 존재 이유가
없다 — 그것은 순수한 임시 이중 read 낭비다.

**★확정 = Path A: 계층4 컴포넌트는 std_v3 를 직접 소비한다.**
- tearsheet 금융 블록·스크리너 revenue 는 std_v3 (`revenue` + `industry_lines`)를 직접 읽는다.
- 별도 사이드채널 reader·이중 read 없음. 버릴 코드 없음.
- 앱이 라이브가 아니므로 swap(L3-5)의 리스크도 낮다. L4 배선과 L3-5 swap 은 자연히 함께/순차로
  진행 가능(둘 다 소스를 std_v3 로 두는 동일 방향).
- 지금 단계 = 이 문서(계약·레이아웃·규칙) 확정. 구현은 재빌드(§0) 완료 후 별도 실행요청 시.

## 4. tearsheet 설계 (금융 프로파일별)

현 `build_tearsheet_pdf` 는 고정 5행(매출액/영업이익/순이익/자산총계/자본총계)만 표시. 프로파일이
있으면 **매출액 행을 업종 매출 구성 블록으로 치환**한다(일반기업은 무변경).

### 4.1 프로파일 감지
- meta 에 `induty_code`(현재 미노출 → `corporations` 조인 추가) + `industry_lines.profile` 사용.
- profile 존재 → 금융 레이아웃, 없음 → 기존 일반 레이아웃.

### 4.2 매출 구성 표 (프로파일별 행)
- 보험: `보험수익` / `투자수익` / **매출(합계)**
- 은행: `이자수익` / `수수료수익` / (`보험수익`) / (`기타영업수익`) / **매출(합계, GROSS)**
- 증권: `수수료수익` / `이자수익` / (`트레이딩손익`) / (`기타영업수익`) / **매출(합계, GROSS)**
- 괄호 성분은 해당 연도 값 존재 시에만 행 노출.
- 하단 공통행: 영업이익 / 순이익 / 자산총계 / 자본총계 (기존 유지).

### 4.3 한국금융지주형 (revenue NULL)
- 매출 구성 블록 **비노출**, 대신 "영업이익"을 대표 상단 지표로. 캡션: "증권 주력 금융지주 —
  매출액 개념이 없어 영업이익 기준 표시".
- 밸류에이션 PSR 은 N/A 처리(§5.3 와 동일 규칙).

### 4.4 차트
- 금융 프로파일: 차트1(매출·영업이익)의 "매출액" 을 조립 revenue 로. 성분 스택은 v1 범위 밖(추후).
- 한국금융지주형: 차트1 을 영업이익·순이익 추이로 대체.

## 5. 스크리너 정규화 revenue 배선

### 5.1 revenue 소스(std_v3 직접)
- 스크리너 윈도우가 std_v3 를 소스로 읽으면 revenue 는 이미 프로파일 조립값 → 금융사도 정확.
- 영향 지표: **PSR**(=시총/매출), **매출성장률**, **R&D/매출**(금융사는 통상 N/A).

### 5.2 한국금융지주형 revenue NULL 처리
- revenue NULL → PSR·매출성장률 = **N/A**(0 나눗셈/허수 금지). 스크리너 랭킹에서 해당 지표는 제외되고
  다른 지표로만 평가(기존 결측 처리 기조 유지).

### 5.3 검증
- 비금융사 revenue·PSR 이 std_v2 기준과 동일함 확인(std_v3 일반기업 revenue = std_v2 와 일치해야).
- 금융사 PSR 이 std_v2 대비 std_v3 조립 revenue 로 바뀌어 **작아지는(분모↑)** 방향 확인.

## 6. 완료기준 (DoD)
1. 재빌드 후 std_v3 프로파일 전량 성립(insurance/bank/securities + 한국금융지주 NULL) 재확인.
2. 보험·은행·증권 대표 각 1사 tearsheet 가 업종 매출 구성 블록으로 정확히 렌더(값=DART 원문 대조).
3. 한국금융지주 tearsheet = 영업이익 기준 표시, PSR N/A.
4. 스크리너에서 금융사 PSR 이 조립 revenue 기준으로 정정, 비금융사 전량 불변(회귀 0).

## 7. 리스크 / 주의
- ⚠ **재빌드 선행 필수** — stale std_v3 로 구현/검증하면 securities·한국금융지주가 빠져 오판.
- ⚠ **V2는 정답 아님** — 검증은 DART 원문 기준(handoff §5). std_v2 는 교차검증 참고용으로만 보존.
- ⚠ induty_code 스코프 신뢰(프로파일이 primary-business 로 self-gate). 자회사 연결로 보험수익을
  물린 일반지주가 오조립되지 않는지 스팟체크.
- 성분 스택 차트·업종별 전용 비율(NIM/합산비율/자기자본이익률 등)은 v1 범위 밖(후속).

## 8. 다음 액션 (이 문서 검토 후, 별도 실행요청 대기)
1. ~~Path A/B 결정~~ → **Path A 확정**(§3). 계층4 는 std_v3 직접 소비, 사이드채널 없음.
2. **선행: `--recheck` 완료 → `build_std_v3.py --all` 재빌드**(handoff §0). 재빌드 전 구현 착수 금지
   (stale std_v3 = securities·한국금융지주 미반영).
3. 재빌드 후 프로파일 전량 성립 확인 → **구현 착수(별도 실행요청 시)**:
   ① tearsheet 금융 블록(std_v3 `revenue`+`industry_lines` 직접 read) ② 스크리너 윈도우 std_v3 소스화
   ③ 검증(비금융 revenue=std_v2 일치, 금융 PSR 정정).
   ※ L4 배선이 앱을 std_v3 로 향하게 하므로 L3-5 swap 과 자연히 수렴 — 순서/범위는 재빌드 후 확정.
