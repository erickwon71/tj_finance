# 설계 — Gate B 버그#2(dividends_paid 부호): document.xml 인라인 XBRL 사실(fact) 오버레이 (2026-08-13)

> **상태: 구현 완료(2026-08-14).** `fin2/extract/report_lines_inline_xbrl_overlay.py`
> + `docs/PARSING_RULES.md` R18. 단 실제 적용률은 설계 예상(92%)보다 낮음(fail_a
> 36건 중 6건 적용, 전부 정답 일치·오탐 0) — R18 항목 "★설계 예상치보다 실제
> 적용률이 훨씬 낮음" 참고. 잔여 30건은 이 설계 범위 밖(다른 원인).
> 전제 = [`gate_b_bug2_dividends_paid_findings_2026-08-13.md`](../qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md)
> (§1~§5, 가설 기각 경위+커버리지 실측). 이 문서는 그 §5 권고를 실제 구현 가능한 설계로
> 구체화한 것 — 이번 세션에 LG 원문(`raw_report/.../20260318001025.xml`)을 다시 직접 열어
> 확인한 내용으로 메커니즘을 한 단계 더 정밀화했다.

---

## 0. 한 줄 요약

CF 본문표의 "배당금의 지급" 셀 자체는 회사별 확장 개념(`entity{corp}_...`)으로 태깅돼 있어
부호가 신뢰할 수 없지만(§2), **같은 문서 안 다른 위치**(자본변동 내역/배당 상세 표)에
**표준 IFRS 개념**(`ifrs-full_DividendsPaidClassifiedAsFinancingActivities`)으로 부호까지
정확히 태깅된 사실(fact)이 이미 존재한다 — Gate B 감사기(`face_audit.py`)가 정답으로 삼는
값이 바로 이것이다. **production 계층2 추출기(`fin2/extract/report_lines.py`)가 감사기와
같은 방식으로 이 사실을 읽어, canonical 개념·기준(연결/별도)·컬럼이 일치하는 텍스트
추출행을 발견하면 그 값으로 대체(override)한다** — 이게 이번 설계의 핵심이다. 새로운
파싱 로직을 만드는 게 아니라 **감사기가 이미 갖고 있고 검증된 리더를 production 쪽도
쓰게 한다**는 것에 가깝다.

---

## 1. 배경 — 지금까지 확인된 사실 (요약, 근거는 findings 문서)

- 원래 가설("CF 부모 음수 소계 → 자식 무부호 자식에 부호 상속")은 실측(1,219,491행/
  14,678행 전수조사 + 200건 감사기 재실행)으로 **기각**됨 — 구조만으로는 "부모=순수
  유출버킷"을 구별할 수 없고, 감사기 자신도 같은 맹점을 공유해 고치면 새 fail_a가 남.
- 진짜 원인: production 추출기(`report_lines.py`)가 `document.xml`에 이미 있는 인라인
  `TE[@ACODE]/[@ACONTEXT]` 태그를 전혀 안 읽고(`table_extractor.py` 자체 docstring이
  "TE 태그: ACODE 속성 있는 데이터 셀 — Track A 전용"이라고 명시), 감사기(`face_audit.py`)
  만 이걸 읽어 정답을 얻는다.
- **커버리지 실측(이번 세션, §5)**: ACODE/ACONTEXT는 fiscal_year 2024를 기점으로 급격한
  절벽 — 2023년 이전 **0.0%**(1,439건 표본 전부), 2024년 **31.7%**, 2025년 **98.3%**,
  2026년 **100.0%**. 현재 dividends_paid fail_a 39건 중 **36건(92%)이 정확히 2024~2026년**
  — 우연이 아니라 이 태그 가용성과 직접 연동된 신호(대조군 trade_payables fail_a는
  2010~2023년에도 고르게 분포).

## 2. 원문 재확인(이번 세션, LG `20260318001025.xml` 직접 grep) — 메커니즘 정밀화

CF 본문표(연결, "배당금의 지급") 행:
```xml
<TE ACODE="entity00120021_PaymentOfDividendOfudf_CF_201711315364636_CashFlowsFromUsedInFinancingActivities"
    ACONTEXT="CFY2025dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    ADECIMAL="-6" ANEGATED="N">745,599</TE>
```
- ACODE가 `ifrs-full_`/`dart_`가 아니라 **`entity00120021_...`**(회사 고유 확장 개념) —
  기존 `_XBRL_PREFIXES = ("ifrs-full_", "dart_")` 필터(face_audit.py·이번 세션 프로브
  둘 다 사용)에 **안 걸린다**. `ANEGATED="N"`이지만 실제로는 유출(음수) 항목 — 이 필드
  하나만 보고 부호를 결정하면 안 된다는 뜻(회사별 확장 개념의 ANEGATED는 그 개념 자신의
  표시 관례일 뿐, 상위 트리 문맥과 무관할 수 있음 — 실측으로 확인, 짐작 아님).

같은 문서, 완전히 다른 위치(배당 내역/자본변동 인접 표)의 표준 개념:
```xml
<TE ACODE="ifrs-full_DividendsPaidClassifiedAsFinancingActivities"
    ACONTEXT="CFY2025dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
    ADECIMAL="-6" ANEGATED="Y">(632,384)</TE>
```
- 표준 IFRS 개념 + `ANEGATED="Y"` + 괄호표시 `(632,384)` = 음수, **fail_a 케이스가 기대하는
  정답(`report_won = -632,384,000,000`)과 정확히 일치**(별도기준, 이 필링의 statement_type과
  일치).
- `fin2/taxonomy/concept_map.py`가 이미 이 구분을 알고 있다 — bare `ifrs-full_DividendsPaid`는
  **SCE(자본변동표) 개념이라 매핑 제외**, `ifrs-full_DividendsPaidClassifiedAsFinancingActivities`
  만 `cf.dividends_paid`로 매핑(주석 "★A(2026-07-18)"로 이미 문서화돼 있음, line 128-131).
  즉 **이 설계가 필요로 하는 개념 매핑은 이미 존재하고 이미 테스트됨**(`fin2/tests/
  test_concept_map.py`) — 새로 만들 필요 없음.
- `ANEGATED` 속성은 현재 **어느 코드에서도 안 읽는다**(전체 grep 결과 0건) — 지금은
  `parse_displayed()`가 셀 텍스트의 괄호/마이너스 기호만 보고 부호를 정하는데, 표준 개념
  쪽은 이미 괄호로 표시돼 있어 이 경로로도 음수를 얻을 수 있다(ANEGATED는 보조 신호로만
  쓰면 충분, 필수 아님).

**결론**: "같은 셀의 ACODE에 부호를 더 물어본다"가 아니라, **"문서 전체에서 canonical
개념이 일치하는 더 신뢰할 수 있는 별도의 fact를 찾아, 텍스트 추출 행과 대사(매칭)한 뒤
있으면 그걸 우선한다"**가 맞는 그림이다 — 이게 바로 `face_audit.py::read_report_face_xbrl()`
가 이미 하고 있는 일이다(표 위치와 무관하게 문서 전체의 `TE[@ACODE]`를 훑어 canonical
개념별로 사실을 재구성). 새로 설계할 게 아니라 **이미 있는, 테스트된 리더를 production
쪽에도 연결**하는 문제로 재정의된다.

## 3. 왜 "combine.py 부모-자식 상속"이 아니라 이 방향인가

| | 원래 가설(기각됨) | 이 설계 |
|---|---|---|
| 신뢰 근거 | 표 구조(부모 음수+자식 무부호)만 보고 **추론** | 문서에 **이미 태깅된 부호 있는 사실**을 직접 관찰(R0 "관찰이지 판단 아니다") |
| 오탐 위험 | 혼합부호 버킷이 부모인 절대다수 케이스(1.2M행)에서 오적용 | canonical 개념+basis+col_index가 **정확히 일치하는 fact가 있을 때만** 적용 — 불일치 시 아무것도 안 함 |
| 감사기와의 정합성 | 감사기는 안 바뀌므로 "고치면 새로 깨짐" 위험 실측 확인(200건 중 0건 도움/25건 새로 깨짐) | 감사기가 쓰는 것과 **동일한 사실 소스**를 production도 쓰게 되므로 이 비대칭이 구조적으로 해소됨 |
| 적용 범위 | 전 연도(추론 기반이라 시대 무관하게 오적용 가능) | 자연히 **2024+로 한정**(그 이전엔 태그 자체가 없어 overlay가 no-op) |

## 4. 설계

### 4-1. 재사용할 기존 컴포넌트 (신규 구현 최소화)
- `fin2/extract/acontext.py::parse_acontext()` — ACONTEXT 문자열 → basis/col_index/
  is_dimensional/extra_dims 구조 파싱. 이미 테스트됨(`test_acontext.py`).
- `fin2/taxonomy/concept_map.py::map_acode()`/`ACODE_TO_CANONICAL` — ACODE → canonical
  개념(`cf.dividends_paid` 등). 이미 SCE/CF 구분 반영, 이미 테스트됨(`test_concept_map.py`).
- `parser/xml/dart_xml_parser.py::_parse_xml_file()` — sanitize + lxml parse. 이미 production
  경로(`report_lines.py`도 이미 이 파일의 다른 헬퍼를 쓰고 있을 가능성 높음, 없으면 같은
  sanitize 함수를 import).
- `fin2/audit/face_audit.py::read_report_face_xbrl()` — **알고리즘을 그대로 참고**(직접
  import는 안 함, audit 모듈에 production이 의존하는 건 방향이 어색함) — 문서 전체
  `TE[@ACODE]` 순회 → prefix 필터 → ACONTEXT 파싱 → 비차원(col_index=0/all_cols)만 채택
  → dedup 로직을 **`fin2/extract/` 쪽에 별도 헬퍼로 옮겨 양쪽이 공유**하는 안을 권고
  (아래 4-2 참고, 코드 중복 방지).

### 4-2. 배선 위치 — 계층2(`report_lines.py`), 신규 헬퍼 모듈 권고
- **왜 계층2인가**: [[architecture-report-read-layer2-only]] 불변식 — 원문(document.xml)을
  읽는 건 계층2 전용. combine.py(계층3)는 `report_lines` 저장값만 소비해야 한다. 이 설계는
  여전히 원문을 읽으므로(단지 텍스트 대신 인라인 XBRL 태그를 본다는 차이) 계층2 소관이다.
- **권고: `fin2/extract/report_lines_inline_xbrl.py` 신규 모듈**(가칭) — 이유:
  - `read_report_face_xbrl()`의 dedup/ambiguous-home 판정 로직(`face_audit.py` §"2026-08-12
    회귀#1+#2" 대응 코드, 상당히 정교함)을 그대로 재사용하되, audit 전용 모듈에서
    production이 import하는 건 결합 방향이 이상함 → 공용 로직을 새 모듈로 옮기고
    `face_audit.py`가 거기서 import하도록 리팩터(또는 최소 변경으로 `face_audit.py`의
    해당 함수를 이 새 모듈로 이동 후 `face_audit.py`가 재-export) — **face_audit.py의
    기존 동작(회귀#1/#2가 고친 그 정교한 판정)은 한 글자도 안 바꾸는 순수 이동**이어야
    함(회귀 재발 방지).
  - `report_lines_xbrl.py`(R14, `xbrl_zip` 소스)와 이름을 나란히 둬 "같은 종류의 XBRL
    사실 소스인데 파일이 다르다"는 관계를 명확히 함.
- `fin2/extract/report_lines.py::extract_report_lines()`가 기존 텍스트 추출로 face
  ReportLineRow 목록을 만든 **직후**, 이 신규 모듈의 오버레이 함수를 호출해 canonical
  개념이 일치하는 행의 값/부호를 대사·보정한다.

### 4-3. 알고리즘

```
1. document.xml에서 read_report_face_xbrl() 방식으로 canonical 개념별 사실 테이블을 만든다:
     facts[(canonical, basis, col_index)] = signed_value_won
   (§2에서 확인한 대로 ifrs-full_/dart_ 접두만 — entity{corp}_ 확장 개념은 이 테이블에
   안 들어간다. 이게 맞다 — 그 확장 개념은 신뢰 못 하니까 애초에 후보에서 제외.)

2. 기존 텍스트 추출 결과(ReportLineRow, statement in {BS,IS,CF})를 순회.
   각 row가 이미 combine.py 단계에서 canonical 매핑되는 것과 "같은" 매핑을
   report_lines.py 수준에서 미리 알 필요는 없다 — label_raw로는 안 되므로,
   **이 오버레이는 canonical 매핑이 가능한 raw XBRL 출처 행(즉 이미 원문에 ACODE가
   달려있던 행)에 한정**한다. 텍스트 전용(순수 <TD>, ACODE 자체가 없는) 행은
   대사 대상에서 제외(비교할 canonical이 없음 — 라벨 매칭은 계층3 소관이라 계층2에서
   안 함, R0 원칙 유지).

3. 각 (canonical, basis, col_index) facts 항목에 대해:
   - 매칭되는 텍스트 추출 행이 있고, 그 행의 절대값과 facts 값의 절대값이
     "같은 자릿수"(예: 0.5~2배 범위, verified_adecimal의 관용 오차보다 느슨한
     자릿수 sanity check)면 → facts 값(부호 포함)으로 override.
   - 절대값이 자릿수부터 다르면(개념 불일치·컨텍스트 오매칭 의심) → **손대지 않고
     원래 텍스트값 유지**, 나중 조사를 위해 conflicts 필드에 기록(기존
     `ReportLineRow`/std_v3의 `conflicts` 컬럼 재사용 — combine.py가 이미 이 필드를
     씀).
   - facts에 해당 (canonical, basis, col_index) 자체가 없으면(2023년 이전 등) → no-op,
     기존 텍스트 추출값 그대로.
4. source_ref에 출처 표기(R14 선례: "header_hint 대신 source_ref로 무필터 기록" 패턴
   재사용) — 예: 기존 "text:CF:sep:..." → "text:CF:sep:...;xbrl_inline_override" 같은
   접미사, combine.py 쪽 `header_hint IS NULL` 가드와 충돌 안 나게(R14 때 발견한 바로
   그 함정 — 이번에도 header_hint는 절대 안 건드림).
```

### 4-4. 스코프(1차)
- **statement = CF 한정, 우선 `cf.dividends_paid`로 검증 후 CF 전체 canonical 개념으로
  자연 확장**(3단계 알고리즘 자체가 canonical 특정 계정에 하드코딩돼 있지 않으므로,
  검증만 통과하면 dividends_paid 외 다른 CF 계정도 같은 매커니즘 혜택을 받을 것으로
  기대 — 단 각 계정별로 §5 안전장치가 실제로 잘 작동하는지 회귀 diff에서 반드시 확인).
- BS/IS/SCE 확장은 **이번 설계 범위 밖**(다른 걸림돌 가능 — 예: BS는 instant라 basis
  매칭은 되지만 col_index 의미가 다를 수 있음, IS는 누적/분기 구분(`is_cumulative`)까지
  얽힘) — 필요성 재평가 후 별도 설계.
- 자연히 2024+ 필링에만 적용(§1 커버리지 절벽) — 2023년 이전은 no-op이므로 회귀 위험 자체가
  없음(고칠 데이터가 없음).

### 4-5. 저장/추적성
- `source_ref` 접미사로 오버레이 적용 여부 기록(위 4-3-4).
- 몇 건이 오버레이 적용됐는지 로그(R14의 "1,603건·317,947행" 같은 집계 습관 재사용).

## 5. 위험 및 안전장치

- **★블랭킷 수정 금지 원칙 재적용**(기존 가설이 걸려 넘어진 지점) — 이 설계는 canonical+
  basis+col_index가 **정확히 일치하는 fact가 있을 때만** 손댄다. dividends_paid 43,590건
  중 원문이 실제로 양수인 필링(대다수는 pre-2024라 애초에 대상 아님, 혹시 2024+ 중에
  있다면 해당 fact 자체도 양수로 태깅돼 있을 것이므로 override해도 결과가 안 바뀜)에
  영향 없어야 함 — **회귀 diff로 반드시 실측**(추정 금지).
- **자릿수 sanity check 없이 그대로 override하면 위험**: ACONTEXT 매칭이 basis/col_index
  텍스트 파싱 버그로 엉뚱한 기간을 가리킬 가능성 존재(예: 당기/전기 착오) — 3단계의
  "절대값 자릿수 근사 확인" 없이는 적용 안 함.
- **회사 확장 개념(entity{corp}_...)은 애초에 신뢰 후보에서 제외**(§2에서 실측으로 확인된
  이유) — 이 필터를 완화하고 싶은 유혹이 있어도 하지 않는다(ANEGATED만으론 부족함이
  실측으로 확인됨).
- **face_audit.py 리팩터 시 회귀 위험**: 4-2에서 공용 로직을 새 모듈로 옮기자고 제안했는데,
  이 함수엔 2026-08-12에 두 번 회귀를 겪고 고친 정교한 판정(ambiguous_home·산술 항등식
  검증)이 들어있다 — **순수 이동(동작 변경 없음)만 하고, `fin2/tests/test_face_audit.py`
  전체가 이동 전/후 그대로 통과하는지 확인 필수**. 자신 없으면 이동 대신 "새 모듈이
  face_audit.py 함수를 그대로 import해서 재사용"(단방향 의존)으로 낮춰도 됨 — 코드
  중복보다 안전 우선.

## 6. 검증 계획

1. 코드 구현(신규 모듈 + `report_lines.py` 연결 지점).
2. **LG(00120021) rcept 20260318001025 재현** — 오버레이 적용 후 `report_lines`의
   dividends_paid(별도) 값이 -632,384,000,000이 되는지 직접 확인.
3. **dividends_paid 전체 회귀 diff**(수정 전/후) — 43,590건 기존 양수행 중 몇 건이
   바뀌는지 집계, 바뀐 건 전부(0건이 이상적, 있다면) 원문대조.
4. `pytest tests/ fin2/tests/` 전체(루트 스코프 필수, [[feedback-pytest-scope-raw-report-symlink]]).
5. `docs/PARSING_RULES.md` 신규 규칙 등재(R16 예상).
6. 소급 재추출: 2024+ CF face가 이미 `report_lines`에 적재된 필링 대상
   (`docs/runbook_new_parser_pipeline_integration.md` 체크리스트 — 두 call site 배선 +
   소급 백필).
7. `build_std_v3.py --all --year-min 1999` → `gateb_audit.py --source v3 --recheck` —
   dividends_paid fail_a 39건 중 36건(2024~2026)이 해소되는지, 2023년 이전 잔여 3건은
   그대로 남는지(이 설계 범위 밖이므로 예상된 결과) 확인.

## 7. 확인 필요/미결 사항 (구현 착수 전)

- `report_lines.py::extract_report_lines()`가 지금 각 face 행에 원본 XML 엘리먼트(또는
  최소한 ACODE 속성값)를 어디까지 들고 있는지 확인 필요 — 3단계 알고리즘이 "이 텍스트
  추출 행이 애초에 ACODE가 달려있던 셀에서 나왔는지"를 알아야 canonical 매칭 후보를
  좁힐 수 있음(모르면 label_raw로 근사 매칭해야 하는데 이건 계층3 영역 침범 위험 — R0
  재확인 필요).
- CF 외 다른 canonical 개념(예: `cf.dividends_received`, 다른 CF 조정항목)에도 같은
  "회사 확장개념 vs 표준개념 이중태깅" 패턴이 있는지 3~5건 추가 원문대조로 확인
  (dividends_paid 하나만 보고 일반화하지 않는다, [[feedback-verify-against-source]]).
- `ANEGATED` 속성을 보조 신호로 쓸지(표준개념 쪽만이라도) 여부 — 3단계는 괄호 표시만으로도
  충분해 보이나, 괄호 없이 마이너스 부호도 없이 ANEGATED만 있는 케이스가 있는지 미확인.

## 8. 다음 액션

이 설계에 승인하면 다음 세션에서: §7 확인 항목(읽기전용) → 신규 모듈 구현 →
`report_lines.py` 배선 → §6 검증 순서대로 진행. **승인 전까지 미착수.**
