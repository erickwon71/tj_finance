# 조사 — (a)옵션: 구형 IFRS taxonomy 확장으로 ②(1,548건) 회수 가능성 (2026-08-12)

> 배경 = [`pdf_only_parser_plan_2026-08-11.md`](../plans/pdf_only_parser_plan_2026-08-11.md) §6-0,
> [`pdf_only_structure_probe_2026-08-11.md`](pdf_only_structure_probe_2026-08-11.md) §6-7 항목3.
> **읽기전용 조사** — `fin2/extract/report_lines_xbrl.py`·`parser/xbrl_instance/role_map.py`
> 등 소스 코드는 이 조사에서 **한 줄도 수정하지 않았다**(스크래치패드에서 in-process
> monkeypatch로 실험). Phase 2 착수는 별도 승인 필요([정책](../../CLAUDE.md)).

## 결론 — (a)옵션 **유력**, 단 기존 예상과 다른 진짜 원인 2건 확정 + 후속 품질이슈 2건 발견

애초 가설("`ifrs-full` 하드코딩만 확장하면 된다")은 **절반만 맞았다**. 실제로는 **독립된
두 버그**가 겹쳐 있었고, 둘 다 확인·재현·수정 실험까지 마쳤다. 두 버그를 함께 우회하면
36건 표본(2015~2020 층화, 연 6건) **100% 성공**(0/36 → 36/36, report_lines 120~820행/건)
으로 확인됐다.

---

## 1. 버그 ① — `nsmap.get("ifrs-full")` 리터럴 접두사 하드코딩 (가설대로 확인)

`fin2/extract/report_lines_xbrl.py:814`가 인스턴스 문서의 네임스페이스 접두사 문자열이
정확히 `"ifrs-full"`인지만 확인한다. 실제로 확인한 결과:

| 세대 | 접두사 | 네임스페이스 URI |
|---|---|---|
| 신형(2019-10-01+) | `ifrs-full` | `http://xbrl.ifrs.org/taxonomy/2019-03-27/ifrs-full` |
| 구형(2010~2013 계열, 2015~2020 필링 다수) | `ifrs` | `http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs` |

**핵심 확인 사항 — 같은 축/멤버 개념이 로컬명 그대로 존재**: 층화표본 48건(2015~2020, 연 8건)
전수에서 구형 접두사 인스턴스 문서를 직접 grep한 결과:
- `ConsolidatedAndSeparateFinancialStatementsAxis` — **48/48 (100%)** 태깅 확인(파일당
  20~124회)
- `ConsolidatedMember`/`SeparateMember` — 48/48 전부 확인(연결만 있는 필링·별도만 있는
  필링 혼재, 둘 다 정상 패턴)
- `ifrs-full` 접두사는 48/48 전부 **없음**(구형 세대는 예외 없이 `ifrs`)

즉 XBRL 스키마 관점에서 이 축 개념은 신형/구형 taxonomy 버전이 달라도(네임스페이스 URI
자체는 다름 — IASB가 도메인을 `xbrl.iasb.org` → `xbrl.ifrs.org`로 이전하며 버전도 갈아엎음)
**로컬명은 안정적으로 유지**됐다는 뜻 — 확장 자체는 근거가 확실하다.

**수정 방향**: 리터럴 `"ifrs-full"` 문자열 매치 대신, nsmap 값(네임스페이스 URI)이
`iasb.org/taxonomy` 또는 `ifrs.org/taxonomy` 패턴을 포함하는 접두사를 찾도록 일반화.
코드 나머지 부분(`_emit_statement_lines`/`_emit_sce_lines` 등)은 이미 프리픽스 문자열이
아니라 **해석된 네임스페이스 URI 값**(`ifrs_full_ns` 변수)을 인자로 주고받는 구조라, 이
한 곳만 고치면 하위 로직은 그대로 재사용된다(별도 리팩터 불요).

---

## 2. 버그 ② — ★신규 발견: 외부 taxonomy BFS(Phase 5-A)의 fetch 예산 소진/순서 문제

버그 ①만 우회해서 재실행하면 **여전히 report_lines 0행**(36/36 전부, 에러 없이 조용히
빈 결과)이었다 — 가설을 스스로 뒤집은 지점([[feedback-verify-against-source]] 원칙대로
표본 결과를 그대로 믿지 않고 원인을 추적).

**원인**: `role_map.py::_resolve_external_roles()`가 로컬 zip에 `<link:roleType>`이 아예
없는 구형 세대에서 DART 공유 taxonomy를 BFS로 따라가며 BS/IS/CF/SCE 역할(role) 정의를
찾는데(Phase 5-A, 원래 2019-10-01 웰킵스하이텍 사례로 설계됨), `_EXTERNAL_FETCH_BUDGET = 12`
로 예산이 제한돼 있다. 그런데 DART 자체 역할 정의(`D210000`류, 실제 재무제표 역할)는
`dart_{vintage}.xsd`가 import하는 **~47개 파일 중 맨 마지막 2개**
(`rol_dart_{vintage}.xsd`, `rol_dart-added_{vintage}.xsd`)에만 들어 있고, 그 앞의 ~40개는
전부 개별 IAS/IFRS/IFRIC/SIC 표준별 **주석 role**(core 재무제표와 무관, `_role_types_in`이
전부 0건 분류)이다. `dart_first()`가 dart.fss.or.kr URL을 우선하긴 하지만, 이 파일들은
전부 dart.fss.or.kr 도메인이라 그 정렬로는 구분이 안 되고, 결국 **원본 스키마 파일에 적힌
import 순서 그대로** 큐가 소진돼 필요한 두 파일에 도달하기 전에 예산이 바닥난다.

**직접 검증**(00257732/한국정밀기계, 20150109000344):
- 예산 12(현재값) → `role_map = {}`, `core_roles = {}` (0행 결과의 직접 원인)
- 예산 60(실험) → 47번째 fetch에서 `rol_dart_2013-03-31.xsd` 도달, roleType 260개 중
  26개 core 분류 성공 → `core_roles`에 BS/IS/CF/SCE(별도) **4개 전부** 채워짐
- `rol_dart_2013-03-31.xsd`를 직접 fetch해 확인: `[D210005] Statement of financial
  position, current/non-current - Separate financial statements` 등 필요한 정의가 실제로
  존재(영문 전용 정의, `role_map.py`의 기존 영문 폴백 패턴과 이미 호환).

**수정 방향(둘 중 하나, Phase 2에서 결정)**:
(i) 예산을 늘린다(12 → 60+) — 단순하지만 매 filing마다 최대 47회 순차 fetch를 시도할 수
있어 느리고(단, taxonomy vintage당 1회만 필요 — `external_taxonomy.py`가 디스크 캐시하므로
같은 vintage를 쓰는 나머지 필링은 캐시 히트, 실질 비용은 vintage 종류 수(약 5~10개) ×
47회 정도로 유한).
(ii) **BFS 큐 우선순위에 "rol_dart"/"dart-gcd"류 파일명 패턴을 얹어 먼저 시도**(현재
`dart_first()`가 도메인 단위로만 우선하는 것을 파일명 단위로 한 단계 더 세분화) — 예산을
그대로 두고도 필요한 파일에 먼저 도달, 더 빠르고 우아함. 두 방식 다 `role_map.py`
한 파일 안의 지역적 변경.

---

## 3. 두 버그를 함께 우회한 e2e 실측 — 36건 표본 100% 성공

층화 표본(2015~2020, 연 6건, 총 36건 — ②(xbrl_zip 다운로드됐지만 report_lines 0행)
모집단에서 무작위 추출) 대상으로, 소스 코드를 수정하지 않고 스크래치패드 스크립트에서
`extract_report_lines_xbrl()`의 로직을 그대로 복제하되 (a) 네임스페이스 해석을 URI 패턴
매칭으로 일반화, (b) `_EXTERNAL_FETCH_BUDGET`을 60으로 임시 상향한 두 조건으로 직접 호출:

| 결과 | 건수 |
|---|---:|
| report_lines 생성 성공(120~820행/건) | **36/36 (100%)** |
| 크래시 | 0 |
| 빈 결과 | 0 |

두 버그 우회 전(버그①만 우회)에는 같은 36건이 전부 0행이었던 것과 대비된다 — **두 원인
모두 필요조건**이었다는 뜻(하나만 고치면 여전히 0행).

---

## 4. 값 품질 스팟체크(1건) — 정상 범위이나 후속 이슈 발견(★§4-1에서 60건 표본으로 정량화·재분류됨)

한 건(20150817000077, BS/별도)의 실제 라인을 열어 확인:
- **금액값(`value_won`) 자체는 정상적으로 채워짐**(예: `CurrentAssets` 40,419,766,353,
  `NoncurrentLiabilities` 1,539,579,362 — 크기가 상장 중소형사 규모와 합치), `None`이
  아니었음(초기 점검 시 `value_raw`—원문 텍스트 폴백 컬럼—를 잘못 확인해 "값 전부 None"
  으로 오판했다가 재확인으로 정정 — [[feedback-verify-against-source]]대로 짐작하지 않고
  실제 필드를 다시 찍어 확인함).
- **★후속이슈 A — 라벨 일부가 한글로 해석 안 됨**: `NoncurrentAssets`, `PropertyPlant
  AndEquipment`, `CashAndCashEquivalents` 등 여러 행이 한글 라벨 대신 영문 개념명 그대로
  나옴 — `taxonomy_linkbase.py::resolve_external_labels()`(별도의 더 얕은 BFS, 예산 8)가
  일부 개념의 라벨 linkbase를 못 찾은 것으로 보임. `labelArc references undeclared loc/
  label` 경고가 다수 찍힘(라벨 linkbase 파일 자체의 구조적 파싱 이슈로 추정, 버그②와는
  다른 원인일 가능성). **레이어3의 한글 키워드 매퍼가 영문 라벨을 인식 못 하면 std_v3
  집계에서 조용히 누락**되므로(모듈 docstring이 이미 경고하는 정확히 그 실패모드) Phase 2
  설계 전 별도로 원인 확인 필요.
- **★후속이슈 B — 일부 행이 정확히 중복**(같은 개념·같은 값이 두 번 나옴, 예: `Current
  Assets` 40,419,766,353이 2행, `PropertyPlantAndEquipment`/`무형자산`/`OtherCurrent
  FinancialAssets` 등도 동일 패턴). presentation tree walk 중 같은 element를 가리키는
  arc가 두 번 순회되는 것으로 추정(P/F role 판정이나 트리 구조 이슈) — 저장 시
  `_is_loadable()`이 이 중복을 걸러내는지 별도 확인 필요.
- **자산총계/부채총계/자본총계(Assets/Liabilities/Equity 최상위 합계) 행 자체가 안 보임**
  — 이 필러의 `_pre.xml` 프레젠테이션 트리에 그 개념이 실제로 없어서인지(구성요소만
  태깅하고 합계 라인 자체는 트리에 없는 필링일 가능성), 아니면 다른 필터링 때문인지
  미확정 — Phase 2 이전에 원문(`_pre.xml`) 직접 대조로 확인 필요
  ([[architecture-report-read-layer2-only]] 위반 아님 — 이 조사 자체가 검증 목적의 예외
  범주).

이 두 이슈는 **버그①·②(taxonomy 확장 자체의 타당성)와는 독립적인, 더 아래 단계의 품질
이슈**다 — 옵션 (a)를 "채택할지 말지"의 판단을 뒤집을 정도는 아니라고 보이지만(구조는
붙고 금액은 정상), Phase 2 설계 문서에서 정식으로 다뤄야 한다.

---

## 4-1. 후속이슈 A/B/C 정량화(2026-08-12, 같은 날 재요청 — 표본 확대 60건)

1건 스팟체크로는 판단 불가했던 후속이슈 3건을 60건 표본(2015~2020 층화, 연 10건, 두 버그
모두 우회 적용)으로 정량화하고, 심각도가 큰 두 건은 근본원인까지 직접 원문 대조로 추적했다.
소스 코드는 여기서도 전혀 수정하지 않았다.

### A) 라벨 미해석 — 24.6%지만 **taxonomy vintage에 강하게 편중**, 원인 확정

전체 23,661행 중 5,820행(24.6%)이 "라벨 못 찾음" 최종 폴백(영문 개념명 그대로)이었다.
단, 분포가 이분법적이다 — 파일별 비율의 **중앙값은 0%**인데 평균은 26.4%(최소0%~최대
94.4%)로, "대다수 필링은 문제없고 일부가 심하게 나쁜" 구조. 6건을 직접 원문 대조한 결과
**taxonomy vintage와 정확히 일치**:

| vintage(`dart` 네임스페이스) | 표본 | bare rate |
|---|---|---|
| `2013-03-31` | 3건 | 90~94% |
| `2017-10-01`/`2018-07-01` | 3건 | 0% |

`2013-03-31` vintage 하나를 직접 추적(`resolve_external_labels()` 호출)한 결과: 외부
label linkbase 파일(`dart_entry_point_2013-03-31-label.xml`) 자체는 1회 fetch로 바로
찾아지지만(버그②처럼 예산 소진이 아님), 그 파일을 파싱할 때 `labelArc references
undeclared loc/label` 경고가 다수(수십 건) 발생하며 skip되고, 최종적으로 **개념 18개
분량의 라벨만 확보**된다 — 이마저 `dart:`(DART 확장 개념) 라벨뿐이고, 정작 문제였던
`ifrs:NoncurrentAssets`류 **표준 IFRS 개념 라벨은 이 파일에 아예 없다**(신형 vintage의
"6개 label linkbase(lab_ifrs-ko/en, lab_dart-ko/en, lab_dart-gcd-ko/en)를 전부 찾아
합친다"는 구조와 달리, 이 구형 vintage는 파일 하나만 찾고 멈추는데 그 파일 구조 자체가
다른 것으로 보인다). **버그②(예산 소진)와는 다른, 독립된 세 번째 결함** — `resolve_
external_labels()`가 "첫 번째로 찾은 labelLinkbaseRef 파일이면 충분"이라고 가정하는데,
이 vintage는 그 가정이 깨진다.

**모집단 영향 규모 추정**: category②(1,551건) 중 filed_at 2018년 이전이 890건(57.4%) —
vintage와 filed_at이 1:1은 아니지만 대략적 규모감으로는, ②의 절반 이상이 이 라벨 결함의
영향권일 가능성이 있다(정확한 vintage별 건수는 추후 전수 스캔 필요).

### B) "중복 행" — 32.9%지만 ★재확인 결과 대부분 진짜 버그 아님(포지션 재사용)

전체 행의 32.9%(7,776/23,661)가 (statement, basis, col_index, label_raw, value_won)
기준 "중복"으로 잡혔고, 거의 모든 필링(범위 5~43%)에 고르게 나타나 처음엔 시스템적
추출 버그로 의심했다. **그러나 3개 사례를 직접 원문 대조한 결과 — row_order·depth·
section_path가 전부 다른 진짜 서로 다른 트리 위치였다**:

```
'매출채권' 35,662,459,070  →  ①row_order=5,  depth=1, section_path=유동자산
                              ②row_order=16, depth=2, section_path=유동자산>매출채권 및 기타유동채권
```

즉 같은 개념(예: 매출채권)이 ①유동자산 아래 직접 롤업된 요약 라인, ②그 아래 세부
분해표(매출채권 및 기타유동채권) 안의 상세 라인, 두 자리에 필러 자신이 실제로 그렇게
공시한 것 — `report_lines_xbrl.py`의 `PresentationNode` docstring이 이미 명시한 "동일
개념이 한 role 안에서 두 자리 이상 나올 수 있다(주석 rollforward 표가 대표 사례)"는
설계 전제가 본문(face) 재무제표에도 그대로 적용된 사례. **"버그"가 아니라 "필러의
프레젠테이션 구조 자체가 값을 두 번 보여준다"**로 재분류한다.

다만 이게 저장 계층에서 어떻게 다뤄져야 하는지(둘 다 저장 vs 하나만)는 Phase 2에서
결정할 설계 질문으로 남는다 — 수정이 필요한 "버그"라기보다 "정책 결정" 항목.

### C) ★최상위 합계(자산총계/부채총계/자본총계) 행 부재 — 가장 심각, 원인 확정(구조적 결손)

60건 표본(basis별 조합 최대 113개, 실측 107개) 기준:

| 개념 | row_present ∧ fact_present | row_present ∧ ¬fact_present | ¬row_present ∧ fact_present |
|---|---:|---:|---:|
| Assets(자산총계) | 2 | 1 | **104 (97%)** |
| Liabilities(부채총계) | 2 | 2 | **103 (96%)** |
| Equity(자본총계) | 12 | 0 | **95 (89%)** |

즉 **97%의 경우 원문 XBRL에 자산총계 fact가 실제로 태깅돼 있는데도(기준: 이 축 하나만
걸린 단일차원 컨텍스트 — 추출기 자체의 basis 판정 규칙과 동일 기준) report_lines 행으로
안 나온다.** 원인을 직접 추적(20200228006031, BS/연결 프레젠테이션 트리 545개 노드
전수 스캔): **필러가 제출한 `_pre.xml`에 `Assets`/`Liabilities`/`Equity` 개념이
노드로 아예 없다** — 트리가 13개의 분리된 "root" 그룹(CurrentAssets, NoncurrentAssets,
CurrentLiabilities, IssuedCapital, RetainedEarnings 등)으로만 구성되고, 이들을 하나로
묶는 "자산총계" 상위 노드 자체가 없는 **flat 구조**. → **추출기 버그가 아니라 이
vintage대(2015~2019 다수)의 진짜 데이터 특성** — 다만 fact 자체는 존재하므로 정보
손실은 아니고, **트리 워크만으로는 못 뽑는다**는 뜻.

**Phase 2 수정 방향(권고)**: BS의 Assets/Liabilities/Equity(및 IS의 당기순이익 등 동급
"필수 합계" 개념)에 한해 — 트리에 노드가 없어도, 같은 basis 단일차원 컨텍스트로 태깅된
fact가 존재하면 **트리를 우회해 fact에서 직접 합성 행을 만드는 보조 규칙**을 추가.
"관찰만 하고 지어내지 않는다"(R0) 원칙에도 부합 — 값 자체는 필러가 실제로 태깅한 것을
그대로 쓰고, 트리 안에서의 위치(depth/section_path)만 없는 상태로 저장하면 된다(구조
정보 없이도 값은 정확 — 계층3 표준화 소비에는 값이 핵심이므로 실질적 개선).

---

## 5. 종합 판단

- (a)옵션의 핵심 전제("구형 taxonomy에도 같은 축 개념이 존재하는가")는 **48/48 표본으로
  확정 — 참**.
- 실제 미적재의 진짜 원인은 처음 가정한 1개(`ifrs-full` 하드코딩)가 아니라 **2개**였고,
  둘째(외부 taxonomy BFS 예산/순서)는 이번 조사로 **새로 발견**됐다 — 계획서 §6-0의
  "확인 없이 확장하면 조용히 틀린 매핑 위험" 우려가 실제로 맞았던 셈(다만 "틀린 매핑"이
  아니라 "여전히 0행"이라는 더 눈에 띄는 실패 모드로 나타나 다행히 조용히 넘어가지
  않았다).
- 두 버그(①②) 모두 **role_map.py/report_lines_xbrl.py 내부 지역적 수정**으로 우회
  가능함을 직접 실험으로 증명(소스 미수정, 36/36 성공).
- 60건 표본 정량화(§4-1)로 후속이슈 3건의 실체가 명확해졌다 — **처음 우려했던 것보다
  나은 그림**: B(중복 행)는 재확인 결과 대부분 버그가 아니라 필러의 정상 프레젠테이션
  구조(같은 개념이 두 자리에 실제로 공시됨)였다. A(라벨 미해석)·C(총계행 부재)는 실재하는
  결손이지만, 둘 다 **원인이 특정되고 좁게 국한된 결함**(A=특정 vintage의 외부
  라벨linkbase 구조 문제, C=특정 vintage들의 `_pre.xml`이 합계 노드를 안 실음)이라 —
  "PDF 파싱 없이 저비용으로 해소"라는 (a)옵션의 애초 전망은 **여전히 유효**하고, 오히려
  세 가지 결함 모두 로컬 코드 수정(BFS 예산/순서 조정, 라벨 소스 보강, fact-레벨 합계
  보조규칙)으로 대응 가능해 보인다는 쪽으로 확신이 강해졌다.
- 종합: **버그①·②(taxonomy 확장 자체)는 확정된 지역적 수정 대상**, **후속C(합계행
  부재)는 Phase 2에 반드시 포함해야 할 추가 보조규칙**, **후속A(라벨)는 영향범위(② 중
  최대 절반 이상 추정)가 커서 Phase 2에서 근본 원인을 한 번 더 정확히 규명해야 함**,
  **후속B(중복행)는 버그가 아니라 저장 정책 결정 사안**으로 재분류.

## 6. 다음 액션 (사용자 결정 대기 — 자동 착수 안 함)

1. ☑ 후속이슈 A/B/C 60건 표본 정량화 + 근본원인 추적 완료(2026-08-12, 이 문서 §4-1).
2. ☑ **Phase 2 설계 문서 작성 완료(2026-08-12, 사용자 결정 "Phase 2 설계 문서로
   편입해줘")** = [`pdf_only_parser_phase2_design_2026-08-12.md`](../plans/pdf_only_parser_phase2_design_2026-08-12.md)
   §A — 버그①·②·후속C 수정설계, 후속A 부분수정설계, 후속B는 기존 `ReportLine` 모델
   docstring이 이미 "위치 다르면 다른 행"으로 확정해둔 아키텍처라 별도 결정 불요임을
   확인. 구현착수전 확인필요 5항목(§A-8) 명시. **사용자 승인 대기 — Phase 3 미착수.**
3. (승인 시) §A-8 확인 항목(읽기전용) → 코드 수정 → 회귀 확인 → 백필 → 검증 — 이건
   이번 조사 범위 밖.
