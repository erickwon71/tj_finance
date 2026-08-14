# 버그 #2 (dividends_paid 부호) — 재조사 결과, 계획 문서 가설 기각 (2026-08-13)

**상태: 구현 완료(2026-08-14, `docs/PARSING_RULES.md` R18).** 단 실제 적용률은
아래 §5의 92% 추정치보다 낮음(fail_a 36건 중 6건 적용, 전부 정답 일치·오탐 0 —
R18 항목 참고). `docs/plans/gate_b_fail_a_bugfix_2_3_plan_2026-08-13.md`의
버그 #2 가설을 코드로 구현하기 전 실측 검증한 결과, 원래 가설(부모-자식 부호상속)은 **너무
넓고 위험함이 실측으로 확인**됐고, 진짜 원인은 계획 문서가 짐작한 것보다 깊은 곳에 있다 —
**production CF 추출기(`fin2/extract/report_lines.py`)가, 원본 `document.xml`에 이미 부호까지
정확히 박혀 있는 인라인 태그(ACODE/ACONTEXT)를 아예 안 읽고 무부호 텍스트표만 읽는 것**이
핵심(2026-08-13 후속 재검증으로 §2 갱신 — `xbrl_zip`/R10/R14 트랙과는 별개 현상, §2 참고).
**§5(같은 날 후속)에서 커버리지를 실측** — ACODE/ACONTEXT는 2024년을 기점으로 급격히
보편화되고(2023 이전 0.0% → 2024 31.7% → 2025 98.3% → 2026 100.0%), 현재 dividends_paid
fail_a의 92%(36/39건)가 정확히 그 2024~2026년에 몰려 있어 **수정 방향이 확정됨**(§5) —
단 실제 코드 구현은 아직 착수 전, 사용자 승인 대기. 버그 #3(trade_payables)은 완료
(구현+테스트+PARSING_RULES R15 등재) — 이 문서는 버그 #2만 다룬다.

## 1. 계획 문서 가설이 기각된 과정

### 1-1. 원래 가설: "부모(음수 소계) → 자식(무부호 양수) 부호 상속"을 combine.py에 구현
LG(00120021) 사례 하나만 보면 그럴듯했다 — `fin2/layer3/combine.py::_resolve()`에서
CF statement 안에 `node_role='P'`+음수인 부모 옆에 정확히 같은 section_path로 중첩된
양수 자식이 있으면 부호를 뒤집는 구조 규칙을 구현했다(`_apply_cf_parent_sign_inheritance`,
이후 되돌림).

### 1-2. 실측으로 규모 확인 — 예상보다 훨씬 넓음
같은 패턴(CF, 부모 음수 소계 + 직속 자식 양수)을 SQL JOIN으로 전수 검색한 결과
**1,219,491행**이 걸렸다. 라벨 분포를 보니 `감가상각비`·`유형자산처분이익`·
`외화환산이익`·`매입채무의 증가(감소)` 등 **정상적으로 양수인 조정 항목들**이 압도적
다수였다 — `당기순이익조정을 위한 가감`·`영업활동으로인한자산·부채의변동` 같은
**혼합부호 버킷**(합계는 우연히 음수여도 개별 항목은 다 양수일 수 있음)이 부모인
케이스가 대부분이었다. 원래 가설의 "부모=순수유출버킷"이라는 전제가 구조만으로는
구별이 안 됐다.

### 1-3. `cf.dividends_paid` 하나로 좁혀도 위험함을 실측으로 확인
과도한 라벨을 걷어내고 `cf.dividends_paid` 별칭에만 한정해도 **14,678행(1,087개사,
1999~2026년 전체)**이 걸렸다. 이 중 face_audit에 이미 기록이 있는 4건은 전부 이미
알려진 LG 확정버그였지만, **200건 무작위 표본을 실제 감사기(`read_report_face_tracked`,
Track A/B)로 직접 재실행**한 결과가 결정적이었다:

| 결과 | 건수 |
|---|---|
| report_won도 이미 음수(수정이 도움됨) | **0건** |
| report_won이 여전히 양수(수정하면 새 불일치 발생) | **25건** |
| 값이 여러 개 갈림(불명확) | 99건 |
| 데이터 없음/에러 | 76건 |

**표본 200건 중 판정 가능한 25건 전부가 "고치면 새로 깨짐" 쪽이었다(0건이 "도움됨").**
즉 Track B(구형 필링, 텍스트 감사기)뿐 아니라 **Track A(XBRL) 케이스 1건조차** 감사기가
report_won을 여전히 양수로 읽었다(`00126937` 2024FY) — "부모가 음수면 자식도 음수"라는
구조적 추론은 실제 다수 필링에서 **틀린 결론**을 낸다는 뜻이다. 감사기 자신도 같은
원문의 같은 무부호 텍스트 셀을 읽으므로, DB만 고치고 감사기는 그대로 두면 **지금
"pass"인 행이 새로 fail_a가 될 위험이 실측으로 확인됐다** — 계획 문서가 우려했던
"43,590건 오염" 시나리오와 정확히 같은 종류의 위험.

## 2. LG 확정 케이스의 진짜 원인 — combine.py가 아니라 CF 추출 자체의 공백

LG(`20260318001025`)를 더 깊이 파보니 `report_lines`에 이 필링의 "배당금의 지급" 관련
행이 **세 곳**에 따로 존재했다:

| 출처(`source_ref`/`context_raw`) | 값 | 부호 |
|---|---|---|
| CF 본문표(텍스트 추출, `text:CF:sep:...`) | 632,379,000,000 | **양수(버그)** |
| SCE(자본변동표) 로그(`sce:separate:...`) | 632,384,000,000 | 음수(정확) |
| **`document.xml` 인라인 ACODE/ACONTEXT 태그**(`ifrs-full_DividendsPaidClassifiedAsFinancingActivities`, `face_audit`의 Track A가 직접 읽음) | 632,384,000 (천원단위 표시) | **음수, `(632,384)` — 원본에 이미 정확히 부호가 있음** |

즉 **원본 문서 자체엔 이 계정에 대한 부호 있는 값이 이미 존재한다**(face_audit Track A가
이걸 직접 읽어 report_won=-632,384,000,000을 얻는다 — 이게 Gate B가 쓰는 "정답"이다).

### ★정정(2026-08-13 후속) — "CF는 XBRL에서 0건 추출"은 필터 실수였다

처음 이 문서를 쓸 때 "`report_lines`의 CF 행 13,803,204건 전부가 텍스트 추출이고 XBRL
출처는 0건"이라고 썼는데, `context_raw LIKE 'xbrl%'`라는 필터가 실제 XBRL context_ref
표기(`CFY2019dTQA_ifrs-full_...` 형태, 리터럴 "xbrl"로 시작하지 않음)와 안 맞아 생긴
**오탐**이었다. 올바른 필터(`NOT LIKE 'text:%' AND NOT LIKE 'sce:%'`)로 다시 세어보면:

| statement | 진짜 XBRL(`xbrl_zip`) 출처 rcept | 전체 rcept | 비율 |
|---|---|---|---|
| BS | 1,613 | 162,712 | 0.99% |
| IS | 1,613 | 169,188 | 0.95% |
| CF | 1,613 | 168,911 | 0.95% |

세 statement가 정확히 같은 1,613건이라는 게 핵심 — **CF만 빠지는 게 아니라 필링당
전부-아니면-전무**다. `fin2/extract/report_lines_xbrl.py`(R10/R14)는 `document.xml`이
아니라 **별도로 다운로드받는 `xbrl_zip` 파일**(`download_tasks.file_type='xbrl_zip'`)을
소스로 쓰는데, 이 zip 자체가 **전체 168,911건 중 1,655건에서만 다운로드돼 있다**(DB
확인). 즉 이건 `report_lines_xbrl.py`의 파싱 로직 결함이 아니라 **원천 다운로드 커버리지
한계**(1%) — R14가 이미 그 1,655건 안에서의 taxonomy 인식률을 높인 것이지, 애초에 zip
자체가 없는 나머지 99%엔 적용 대상이 아니다. **LG(`20260318001025`)도 이 1,655건에
안 들어있음을 재확인**(`download_tasks`에 이 rcept의 `xbrl_zip` 행 자체가 없음) — 즉
LG 사례는 xbrl_zip 트랙과 무관하다.

### 진짜 유망한 실마리 — `xbrl_zip`과 무관한 제3의 경로(document.xml 인라인 태그)

LG의 정답값은 `xbrl_zip`이 아니라 **`document.xml` 자체에 이미 박혀 있는 인라인
`ACODE`/`ACONTEXT` 태그**에서 나왔다(추가 다운로드 불필요 — LG도 이미 갖고 있는 파일).
`fin2/audit/face_audit.py::read_report_face_xbrl`(Track A)가 `<TE ACODE="...">` 태그를
직접 읽어 `ifrs-full_DividendsPaidClassifiedAsFinancingActivities` fact를
`(632,384)`(이미 괄호로 음수 표시)로 얻는다. 그런데 **production Layer 2 추출기
(`fin2/extract/report_lines.py`, 실제로 std_v3에 적재되는 경로)는 이 태그를 전혀 안 쓴다**
— `parser/xml/table_extractor.py` 자체 docstring에 "TE 태그: ACODE 속성 있는 데이터 셀
(Track A 전용)"이라고 명시돼 있어, 지금은 감사기(face_audit)만 쓰고 production 추출은
순수 텍스트/표 구조 스캔(`fin2/extract/text.py`)만 쓴다.

**결론(정정판): 버그 #2의 진짜 원인은 두 갈래다.**
1. `xbrl_zip`(R10/R14 트랙) — 원천 다운로드가 1%뿐이라 애초에 대부분 필링엔 적용 안 됨.
   LG는 여기 해당 안 함.
2. **`document.xml` 인라인 ACODE/ACONTEXT — 추가 다운로드 없이 이미 갖고 있는 필링이
   많을 것으로 보이는데(정확한 커버리지 미측정), production 추출기가 이걸 아예 안
   읽는다.** LG 사례가 여기 해당 — combine.py 패치가 아니라 `fin2/extract/report_lines.py`
   (또는 `parser/xml/table_extractor.py`)가 CF(및 다른 statement) 셀 파싱 시 ACODE/
   ACONTEXT가 있으면 그 부호를 권위로 삼도록 확장하는 작업. 커버리지 실측이 우선
   과제(다음 세션 착수 시 1순위).

## 3. 지금 상태

- 시도했던 combine.py 구조규칙(`_apply_cf_parent_sign_inheritance`)은 **코드에서 제거**
  (되돌림 완료, 커밋 안 됨).
- `docs/plans/gate_b_fail_a_bugfix_2_3_plan_2026-08-13.md`의 버그 #2 원인 가설
  ("부모-자식 부호상속 누락")은 **기각** — 이 문서로 대체.
- 버그 #2는 **미구현 상태로 남겨둠**. LG의 4건은 여전히 fail_a.

## 4. 다음 선택지 (사용자 결정 필요, 2026-08-13 후속으로 갱신)

1. **(★가장 유망, 다음 세션 1순위 후보) `document.xml` 인라인 ACODE/ACONTEXT를 production
   추출기가 읽도록 확장** — `fin2/extract/report_lines.py`(또는
   `parser/xml/table_extractor.py`)가 셀 텍스트만 보지 말고, `<TE ACODE=...
   ACONTEXT=...>` 태그가 있으면(추가 다운로드 불필요, face_audit Track A가 이미 같은
   파일에서 읽고 있음) 그 값/부호를 권위로 삼는다. 착수 전 **커버리지 실측 필수** —
   전체 필링 중 몇 %가 ACODE/ACONTEXT를 갖고 있는지, dividends_paid 외 다른 계정에도
   같은 부호누락 패턴이 있는지 먼저 확인. `xbrl_zip`(1%)보다 커버리지가 넓을 가능성.
2. **CF statement `xbrl_zip` 추출 확장**(R10/R14급 별도 작업) — 원천 다운로드가 전체의
   1%(1,655건)뿐이라 이걸 손봐도 LG 같은 대다수 필링엔 적용 안 됨. 우선순위 낮춤.
3. **좁은 임시 땜빵**: `cf.dividends_paid` 후보에 SCE(자본변동표) 값을 추가로 포함시키고,
   CF-텍스트값과 SCE값이 크기는 비슷한데(예: 5% 이내) 부호만 다를 때만 SCE를 우선 —
   LG류 확정 4건은 고치지만 위 1-3에서 본 위험(감사기도 같은 맹점 공유)이 여전히
   존재해 **face_audit.py 쪽도 함께 손보지 않으면 새로운 fail_a를 만들 수 있음**. 검증
   비용이 여전히 크다.
4. **보류** — 버그 #2는 스킵하고 버그 #3만 반영(완료, 백필 대기 중)한 채로 두고, 별도
   계획 문서를 새로 써서 다음 세션에 착수(위 1번 실마리부터).

## 5. ACODE/ACONTEXT 커버리지 실측 완료(2026-08-13, 같은 날 후속 — §4 항목1 착수)

`scripts/probe_bug2_acontext_coverage_2026-08-13.py`(읽기전용)로 `fiscal_year × report_type`
층화 표본 1,649건(셀당 최대 20건, 파싱 실패 0건)을 `parser/xml/dart_xml_parser.py::_parse_xml_file`
(face_audit.py와 동일한 리더, sanitize 포함) + `fin2/extract/acontext.py::parse_acontext`로
직접 읽어 `TE[@ACODE]`(`ifrs-full_`/`dart_` 접두, `ACONTEXT` 비어있지 않음) 존재 여부를 확인.

**결론 — 전체 평균(8.3%)은 오해의 소지가 있다. 실제로는 2024년 기점의 급경사(cliff)다:**

| fiscal_year | Track A(ACODE+ACONTEXT) 보유율 |
|---|---|
| 1999~2023 (25개 연도, 연 29~60건 표본) | **0.0%** (0/1,439, 전 연도 예외 없음) |
| 2024 (전환기) | **31.7%** (19/60) |
| 2025 | **98.3%** (59/60) |
| 2026 | **100.0%** (55/55) |

`report_type`(annual/half/quarter)별로는 7.3~9.5%로 큰 차이가 없다 — 전체 8.3%라는 평균은
report_type 차이가 아니라 이 fiscal_year 절벽 하나로 거의 다 설명된다. 이미 코드 곳곳
(`fin2/extract/expense_nature.py`·`cf_da.py` docstring)이 "2024+ Track A(iXBRL) 전환"이라고
언급해온 것과 정확히 일치 — 이번 실측은 그 서술을 처음으로 정량화했다(DART의 인라인 XBRL
의무화 시행 시점과 부합하는 패턴).

**★dividends_paid fail_a 모집단과 직접 대조 — 정확히 같은 절벽에 몰려 있다**: 현재 `face_audit`
(2026-08-12 12:21 스냅샷, std_v3 세 수정 반영 전이라 재검증 필요하지만 fiscal_year 분포
자체는 안정적일 것으로 봄)의 `dividends_paid` fail_a 39건 중 **36건(92%)이 2024~2026년**
(2024: 8 · 2025: 20 · 2026: 8)이고, 나머지는 2011·2013·2021 각 1건뿐(다른 원인일 가능성,
이 트랙 범위 밖). 대조군으로 `trade_payables` fail_a(버그#3, ACODE/ACONTEXT와 무관한
원인)를 같이 뽑아보면 2010~2023년에도 고르게 분포(합계 67건) — dividends_paid만 2024년
이후로 급격히 쏠리는 건 "최근 필링이 원래 더 많다"는 표본 편향이 아니라 **ACODE/ACONTEXT
가용성과 진짜로 연동된 신호**라는 뜻.

**수정 방향 확정(권고)**: `fin2/extract/report_lines.py`(또는 `parser/xml/table_extractor.py`)
확장은 **2024년 이후 필링에 좁게, 그러나 정확히 지금 fail_a가 몰려 있는 바로 그 구간에**
효과적이다. 2023년 이전 필링(3건 잔여, 다른 원인 추정)에는 이 수정이 적용되지 않는다 —
그 3건은 별도 원인 규명이 필요한 잔여 꼬리로 남긴다. `xbrl_zip`(1% 커버리지, R10/R14)보다
훨씬 넓고, 앞으로 2024+ 필링이 계속 쌓일수록 커버리지가 계속 늘어나는 구조적 수정이라는
점도 §4-1 대비 우위.

**아직 안 한 것(구현 착수 전 남은 확인 항목)**:
- dividends_paid 외 다른 CF/BS/IS 계정에도 같은 무부호 텍스트 vs 부호있는 ACODE 패턴이
  있는지(이번 프로브는 CF/Dividend 힌트만 좁게 셌음 — `n_cf_track_a`가 `n_has_track_a`와
  완전히 같게 나온 건 표본상 우연일 수 있어 재확인 필요, 다른 statement 태그 분류 안 함).
- `report_lines.py`가 텍스트 추출과 ACODE/ACONTEXT 추출을 **병행**할 때 두 값이 다르면
  어느 쪽을 권위로 삼을지(face_audit처럼 ADECIMAL 항등식 검증까지 갈지, 아니면 단순히
  ACODE 쪽을 항상 우선할지) — 설계 결정 필요.
- 회귀 범위: 이미 report_lines에 적재된 2024+ 필링(현재는 텍스트 추출값)에 대한 소급
  재추출이 필요([[parser-pipeline-integration-runbook]] 소급 백필 체크리스트).

## 근거
- `docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md` ②(원래 LG 표본 1건 원문대조)
- 본 세션 실측: SQL JOIN 전수조사(1,219,491행/14,678행), 200건 무작위 표본
  `read_report_face_tracked()` 재실행, LG 필링 `report_lines` 3-소스 대조.
- 2026-08-13 후속(사용자 질문 "pdf-only 세션 XBRL과 관련 있나" 계기로 재검증) —
  `context_raw LIKE 'xbrl%'` 필터 오류 정정: 올바른 필터로 DB 전체 재확인(BS/IS/CF
  각 1,613건, `download_tasks.file_type='xbrl_zip'` 완료 1,655건과 정합), LG rcept
  `xbrl_zip` 다운로드 부재 재확인, `read_report_face_xbrl`/`parser/xml/table_extractor.py`
  코드 확인으로 ACODE/ACONTEXT가 production 추출기(`report_lines.py`)에서 안 쓰이고
  있음을 확인. `docs/qa/pdf_only_xbrl_extraction_rate_probe_2026-08-11.md`·
  `docs/qa/pdf_only_xbrl_recoverable_probe_2026-08-11.md`(pdf-only 세션, `xbrl_zip`
  회수가능성 조사 — 이 문서의 ②번 항목(`xbrl_zip` 트랙)과 같은 자원을 다루지만
  대상 모집단이 다름: pdf-only 세션은 "본문 XML 자체가 없는 필링"의 대체소스 조사,
  본 버그는 "본문 XML은 있는데 부호가 새는" 별개 현상).
- `scripts/probe_bug2_acontext_coverage_2026-08-13.py`(§5, 2026-08-13 후속) — fiscal_year×
  report_type 층화표본 1,649건 직접 파싱, ACODE/ACONTEXT 2024년 절벽 확정 + dividends_paid
  fail_a 39건 중 36건(92%)이 2024~2026년에 몰려 있음을 face_audit 조회로 교차확인.
