# Track C 최우선/확인필요 34건 — 수동 채움 진행 현황 (짬날 때 하나씩)

**상태**: 진행 중 트래킹 문서(계획 문서 — 자동실행 대상 아님, 세션마다 이 표만 보고 이어서
진행). 배경: `docs/plans/html_viewer_extractor_design_2026-09-07.md` §8-17~8-20,
[[feedback-manual-review-show-dart-link-and-csv-path]].

## 왜 이 34건인가

[원문대조 대기열 아티팩트](https://claude.ai/code/artifact/e3147239-ed8c-4c8b-9c87-dcb09f1abe1a)
130행 중 **①최우선(16) + ②확인필요(18) = 34건만** — 전부 **별도(separate)** basis.
③참고(28)·④낮음(68)은 연결(consolidated) basis라 우선순위 낮거나(③) 대부분 애초에
연결재무제표 자체가 없는 정상 결측(④)이라 이 목록에서 제외.

## 작업 방식(매 건 반복)

1. `fin2/extract/manual_report_lines.py` §"CSV 파일 저장 위치" 관례대로
   `manual_review/<시장>/<corp_code>_<회사명>/<report_type>/<연도>/<rcept_no>_manual_review.csv`
   생성(라벨·단위 채움, 값은 비움) — 없으면 먼저 생성.
2. 사용자가 DART 원문(웹뷰어 또는 PDF) 보고 값 채움.
3. Claude가 실제 제출 PDF(좌표기반, 웹뷰어 거대셀보다 신뢰도 높음 — YBM넷 사례로 확인)와
   대조해 항등식 검산 + 밀림 여부 확인 → 필요하면 정정.
4. `python scripts/load_manual_report_lines.py <csv> --dry-run` 통과 확인 →
   (승인 후) `--overwrite`로 실제 적재.
5. 이 표의 상태 컬럼 갱신.

**상태값**: 대기 / CSV생성됨 / 값입력중 / 검증중 / 완료(미적재) / 적재완료

## ①최우선 (16건 — 별도, 값은 나왔는데 HTML·PDF가 서로 다름)

| # | 회사 | corp_code | rcept_no | 기간 | DART 원문 | 상태 |
|---|---|---|---|---|---|---|
| 1 | YBM넷 | 00307222 | 20020814000872 | FY2002 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020814000872) | **적재완료(2026-09-08)** — BS/IS 실값 + CF 결측확정 적재, std_v3+calendar_v3 재빌드 완료. 상세는 진행로그 참고 |
| 2 | 대호특수강 | 00166175 | 20010813000085 | FY2001 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010813000085) | 대기 |
| 3 | 더라미 | 00205687 | 20020514000517 | FY2002 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020514000517) | 대기 |
| 4 | 보성파워텍 | 00267881 | 20010814000217 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010814000217) | 대기 |
| 5 | 보성파워텍 | 00267881 | 20010820000006 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010820000006) | 대기 |
| 6 | 보성파워텍 | 00267881 | 20010829000027 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010829000027) | 대기 |
| 7 | 삼천당제약 | 00128546 | 20010331000162 | FY2000 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010331000162) | 대기 |
| 8 | 삼천당제약 | 00128546 | 20010514000217 | FY2001 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010514000217) | 대기 |
| 9 | 삼천당제약 | 00128546 | 20011112000095 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20011112000095) | 대기 |
| 10 | 삼천당제약 | 00128546 | 20020515000121 | FY2002 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020515000121) | 대기 |
| 11 | 삼천당제약 | 00128546 | 20020814001084 | FY2002 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020814001084) | 대기 |
| 12 | 삼천당제약 | 00128546 | 20021114000391 | FY2002 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20021114000391) | 대기 |
| 13 | 양지사 | 00139685 | 20010514000316 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010514000316) | 대기 |
| 14 | 일진디스플 | 00198697 | 20010331000458 | FY2000 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010331000458) | 대기 |
| 15 | 한솔로지스틱스 | 00140946 | 20020813000679 | FY2002 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020813000679) | 대기 |
| 16 | 한솔로지스틱스 | 00140946 | 20021111000163 | FY2002 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20021111000163) | 대기 |

## ②확인필요 (18건 — 별도, HTML·PDF 둘 다 완전공백)

| # | 회사 | corp_code | rcept_no | 기간 | DART 원문 | 상태 |
|---|---|---|---|---|---|---|
| 17 | 롯데지주 | 00120562 | 20010814000538 | FY2001 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010814000538) | 대기 |
| 18 | 신일전자 | 00173698 | 20000629000089 | FY2000 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000629000089) | 대기 |
| 19 | 신일전자 | 00173698 | 20000629000140 | FY2000 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000629000140) | 대기(18과 중복 접수 가능성 — 확인 시 참고) |
| 20 | 신일전자 | 00173698 | 20000811000116 | FY2001 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000811000116) | 대기 |
| 21 | 신일전자 | 00173698 | 20010214000008 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010214000008) | 대기 |
| 22 | 씨아이테크 | 00127158 | 20000124000002 | FY1999 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000124000002) | 대기 |
| 23 | 한솔홈데코 | 00203582 | 20000329000320 | FY1999 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000329000320) | 대기 |
| 24 | 한솔홈데코 | 00203582 | 20000515000269 | FY2000 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000515000269) | 대기 |
| 25 | 한솔홈데코 | 00203582 | 20000814000140 | FY2000 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20000814000140) | 대기 |
| 26 | 한솔홈데코 | 00203582 | 20010331000623 | FY2000 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010331000623) | 대기 |
| 27 | 한솔홈데코 | 00203582 | 20010515000415 | FY2001 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010515000415) | 대기 |
| 28 | 한솔홈데코 | 00203582 | 20010814000358 | FY2001 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20010814000358) | 대기 |
| 29 | 한솔홈데코 | 00203582 | 20011114000657 | FY2001 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20011114000657) | 대기 |
| 30 | 한솔홈데코 | 00203582 | 20020401000165 | FY2001 사업보고서 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020401000165) | 대기 |
| 31 | 한솔홈데코 | 00203582 | 20020514000885 | FY2002 1분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020514000885) | 대기 |
| 32 | 한솔홈데코 | 00203582 | 20020814000471 | FY2002 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020814000471) | 대기 |
| 33 | 한솔홈데코 | 00203582 | 20020820000124 | FY2002 반기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20020820000124) | 대기(32와 근접 접수일 — 정정 관계 가능성 확인) |
| 34 | 한솔홈데코 | 00203582 | 20021114000443 | FY2002 3분기 | [링크](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20021114000443) | 대기 |

## 진행 로그

- 2026-09-08: 목록 확정(아티팩트에서 추출), YBM넷(#1) 착수 — CSV 생성, IS 정정 완료(PDF
  대조, R2026-09-08 note 기록됨), BS/CF 남음. `manual_review/KOSDAQ/00307222_YBM넷/half/2002/
  20020814000872_manual_review.csv`.
- 2026-09-08: **std_financials_v3 재빌드 완료**(§8-16에서 미룬 것) — Track C 93건이 걸린
  41개사 전체(`scripts/build_std_v3.py --corp <41개> --year-min 1999`, 8,232행·269초) +
  같은 41개사 `calendarize_corp_v3()` 재동기화(`scripts/calendarize_track_c_41_2026-09-08.py`,
  8,786행). `calendar_orphan_cq`(41개사 한정) 0건 확인. YBM넷 BS/IS는 아직 report_lines가
  안 채워져 있어(수동입력 대기) std_v3에는 반영 안 됨 — 그건 정상(값 자체가 아직 없음).

- 2026-09-08(같은 날 이어서): 사용자가 BS/IS 값을 CSV에 직접 입력 완료 후 "부분합 확인
  결과 현재 값이 맞는 수준, 1천만원 수준 차이는 원본 자체 차이로 보임"이라고 보고.
  Claude가 CSV 값으로 독립 항등식 검산(파이썬 산술, DB 미접근) — **IS는 경상이익 이후
  전 구간 diff=0 완전정합**(매출총이익/영업이익만 반올림 ±1천원), **BS는 최상위 항등식
  (자산총계=부채총계+자본총계=5,538, 자산총계=유동자산+고정자산) 완전정합(diff=0)**.
  하위 소계(당좌자산·투자자산·무형자산·유동부채 등)에서만 0.5~3백만원(최대 3M원) 미세
  오차 — 원본이 각 줄을 개별적으로 백만원 단위 반올림해 생기는 전형적 현상, 사용자가
  본 "원본 자체 차이"라는 판단과 정합. `python scripts/load_manual_report_lines.py <csv>
  --dry-run` 통과 확인(161행/3-scope 파싱 성공, CSV 포맷 오류 없음). **CF는 이번 검증
  스코프 밖** — CSV 자체 note가 "당기(반기) 컬럼이 원문에 placeholder(ADELETETABLE=Y)로
  미기재돼있을 가능성"을 표시 중이라, 지금 채워진 CF 값이 정말 당기(FY2002 H1)인지
  제02기(FY2001 연간 비교값)인지부터 원문(PDF/웹뷰어) 재확인 필요 — 미해결 채로 둠.
  **적재는 아직 안 함**(BS/IS만 먼저 `--overwrite` 실행할지, CF까지 마저 풀고 한번에
  할지 사용자 결정 대기).

- 2026-09-08(같은 날 이어서) — **사용자 결정 + 적재 완료, #1 YBM넷 완전 종료**:
  ①CF는 "반기 당기데이터가 원문에 없음 확정 → 보고서 자체가 비어있는 것으로 표시"
  (이전에 채워뒀던 FY2001 연간 비교값은 폐기), ②IS의 "(1)상품매출원가" 하위 세부내역
  5개 행(1.기초상품재고액~4.기말상품재고액+"계")은 **원문 자체 숫자 오류로 판단**
  (사용자 확인) — 상위 (1)/(2)/(3) 3개 항목값만 신뢰, 세부는 결측 처리. CSV를
  Python csv 모듈로 일괄 수정(CF 46행 전부 value_raw 비움, IS 세부 5행 비움 — 라벨은
  감사추적용으로 유지, note에 사유 기록) → `load_manual_report_lines.py --dry-run`
  재검증(포맷 오류 없음) → `--overwrite` 실제 적재(3-scope, 161행: BS 54행/값47개,
  IS 61행/값55개, **CF 46행/값0개=확정결측**) → `build_std_v3.py --corp 00307222` +
  `calendarize_corp_v3` 재실행. **결과 검증**: std_financials_v3 FY2002/H1 확인 —
  total_assets=5,538,000,000·total_equity=4,758,000,000·total_liabilities=780,000,000·
  revenue=4,365,914,000·cogs=841,310,000·operating_income=1,163,297,000·
  net_income=924,669,000(전부 CSV 산술검산값과 정확 일치), **cfo=NULL**(CF 결측
  의도대로 반영 확인), data_quality=1. 신규 스크립트
  `scripts/calendarize_ybmnet_2026-09-08.py`. **#1 YBM넷 완전 종료.**

## 다음 세션에서

이 표만 보고 "대기" 상태인 것 중 아무거나(또는 사용자가 지정한 것) 골라서 §"작업 방식"
1번부터 반복. 완료된 건은 상태를 "적재완료"로 바꾸고 진행 로그에 한 줄 추가.
