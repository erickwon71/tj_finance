# Category C 잔존 (A) SECTION-3 서브헤딩 리셋 + (C) "요약" 접두 — 실측 기반 설계 (2026-09-05)

> **상태: (C)+(A-1)+(A-2) 구현·드라이런·백필·검증 완료(사용자 승인 후 진행,
> 2026-09-05). PARSING_RULES.md R70 등재 완료.** (A-3, 통짜-셀 레거시 표
> 재구성)은 여전히 미착수 — §2-4 참고, 별도 설계·별도 승인 필요.
>
> **최종 결과**: report_lines 백필(`scripts/backfill_a1_a2_c_2026-09-05.py`,
> fy2004~2017 전체 재스캔) — 대상 1,285건 중 **218건 성공(17.0%), 130,770행,
> 영향 114개사**, 오류 0, 파일소실 32건(별개 트랙). `build_corp(year_min=1999)`
> 114개사 전체 재빌드(21,964행) + `calendarize_corp_v3()` 재동기화(신규
> `calendar_orphan_cq` 46건 발견→해소). `dq_assertions.py` 최종: R70으로 인한
> 신규 ERROR **0건**(회귀 없음, 40건 잔존 `statement_magnitude_impossible`는
> 전부 이번 스코프 밖의 기존 이슈로 확인). `pytest tests/ fin2/tests/` 748
> passed(무관 기존실패 1건 제외). 상세는 `docs/PARSING_RULES.md` R70.

## 0. 배경과 이 문서의 목적

`v2-drop-remaining-backlog-2026-09-03`(메모리) 항목 1-b 잔존 2건:

- **(A) SECTION-3 서브헤딩 리셋** — fy2004~2006, 943건 추정. 배경문서
  (`docs/plans/factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3, 2026-09-05 블록)는
  "원인 이미 규명됨(호텔신라 `20050915000066`·SK네트웍스 `20080331001324` 원문대조
  완료), 설계·구현만 남음"이라고 적어뒀다.
- **(C) "요약" 접두** — fy2014류(삼성증권 `20140515001582` 표본). "`_LEGACY_HEAD`
  수식어 목록에 '요약' 추가, R69와 같은 함수·같은 패턴이라 난이도 낮음"이라고
  적어뒀다.

이번 세션에서 실제 코드로 두 표본 + 추가 표본을 **직접 재현**한 결과 — (C)는
기존 기록대로 낮은 난이도가 맞지만 **게이트가 하나가 아니라 둘**이었고, (A)는
기존 기록보다 **훨씬 복잡하다**: 원인이 하나가 아니라 **최소 3개**이고, 그중
하나(§2-3)는 이번에 새로 발견한 것으로 기존 943건 대부분을 막고 있을 가능성이
높으며 위험도가 다른 둘보다 훨씬 크다. 이 문서는 그 실측 과정과 결론을 그대로
적는다 — 짐작 없이 원문·코드로 재현한 것만 적는다(`feedback-verify-against-source`
원칙).

---

## 1. (C) "요약" 접두 — 실측 검증 결과

### 1-1. 재현

삼성증권 `20140515001582`(2014 Q1)을 `extract_report_lines()`로 직접 호출 →
**0행**(현재 코드). 원문(`XI. 재무제표 등` 섹션 내부)의 실제 헤딩 텍스트:

```
1. 연결재무제표
요 약 분 기 연 결 재 무 상 태 표
제33기 1분기 2014년 3월 31일 현재 제32기 2013년 12월 31일 현재
삼성증권 주식회사와 그 종속기업 (단위 : 원)
과 목 주석 제33기 1분기 제32기
자 산 I. 현금및현금성자산 5,38 305,233,853,874 221,091,992,553 ...
```

(공백은 글자 사이 전부 삽입된 옛 인쇄 관행 — `classify_legacy_statement_heading`
쪽 whitespace 전제거 정규화와는 무관하게 뒤에 실제 계정과목·금액이 이어지는
**완전한 본문 재무상태표**다. "요약"이 붙어도 축약표가 아니다 — 배경문서의
가설 그대로 확인.)

### 1-2. 원인 — 게이트가 **둘**이다 (배경문서는 하나만 지목했음)

`fin2/extract/statement_titles.py::classify_legacy_statement_heading()`
(현재 L458-511)의 판정 순서:

```
1. 번호 접두 거부           (무관)
2. 가나다 열거접두 제거      (무관 — 이 표본엔 없음)
3. _LEGACY_EXCLUDE 검사      ← ★여기서 이미 거부됨(L489, 정규식 L422)
4. _LEGACY_HEAD 매치         ← 배경문서가 지목한 곳(L491, 정규식 L424-427)
...
```

`_LEGACY_EXCLUDE = re.compile(r"분할|합병|요약|명세|부속|주석|검토보고서|감사보고서")`
(L422) — **"요약"이 이미 3단계에서 하드 거부어**다. `_LEGACY_HEAD`(4단계)에 "요약"을
수식어로 추가해도 **3단계에서 먼저 걸려 절대 도달하지 못한다.** 배경문서
("_LEGACY_HEAD 수식어 목록에 없음")는 이 3단계 게이트를 놓쳤다 — 실제로 두 곳을
같이 고쳐야 한다.

### 1-3. 코드 변경안 (2곳, R69 (B)/(D)와 같은 패턴 — 추가적)

**(C-1) `_LEGACY_EXCLUDE`에서 "요약"을 예외 처리** — 무조건 빼면 안 된다. 진짜
"요약재무정보"(`SEC_SUMMARY` 섹션, 계정과목 3~5줄짜리 축약표, 의도적으로 본문
배제 대상)까지 통과시키면 안 되기 때문이다. 이 함수는 `SEC_LEGACY_FS`/
`SEC_LEGACY_APPENDIX`(XI.재무제표 등/부속명세서) **본문 컨테이너 안에서만**
호출되므로(§3-3 참고), "요약"이 재무제표명 **바로 앞**에 붙은 경우만 통과시키고
그 외(예: "요약재무정보" 단독, "연결재무제표 요약" 등 다른 조합)는 계속 배제하는
좁은 예외가 필요:

```python
# ★2026-09-05(설계) — "요약"이 재무제표명 바로 앞 수식어로만 쓰이면(증권/보험
# 분기보고서 관행, 삼성증권 20140515001582 실측: "요약분기연결재무상태표"가
# 완전한 본문표) 배제하지 않는다. 그 외 위치("연결재무제표 요약", "요약재무정보")는
# 계속 배제 — 이 함수가 보는 텍스트는 이미 SEC_LEGACY_FS/APPENDIX 본문 컨테이너
# 안이므로(§3-3), SEC_SUMMARY 섹션 자체는 애초에 이 함수에 들어오지 않는다.
_LEGACY_EXCLUDE = re.compile(
    r"분할|합병|명세|부속|주석|검토보고서|감사보고서|"
    r"요약(?!(?:연결|별도|개별|반기|분기|중간|당|전)*"
    r"(?:재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표))"
)
```

**(C-2) `_LEGACY_HEAD`에 "요약" 수식어 추가**(배경문서가 이미 제안한 부분,
L424-427):

```python
_LEGACY_HEAD = re.compile(
    r"^(?:요약|연결|별도|개별|반기|분기|중간|당|전)*"
    r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표)"
)
```

두 변경 다 **추가적**이다 — "요약"이 전혀 없던 기존 통과 케이스는 정규식 매치가
그대로라 결과가 안 바뀐다.

### 1-4. 회귀 위험 — 드라이런에서 반드시 확인할 것

이 함수가 스캔하는 컨테이너(`SEC_LEGACY_FS`="재무제표등"/`SEC_LEGACY_APPENDIX`
="부속명세서") **안에** 실제 축약 미리보기 표(진짜 "요약" 3~5줄)와 전체 본문표가
**둘 다** 순서대로 나오는 서식이 있는지는 이번 표본 1건으로는 확인 못 했다.
있다면 두 표 모두 "BS"로 판정돼 하나는 덮어써지거나 중복 행이 생길 위험 —
드라이런에서 반드시 "요약" 매치 헤딩 뒤에 오는 표가 **정말 완전한 본문**인지
(계정과목 수·금액 자릿수가 그 문서의 다른 정상표와 비슷한지) 표본 검사 필요.

---

## 2. (A) SECTION-3 서브헤딩 리셋 — 실측 결과, 배경문서보다 훨씬 복잡함

### 2-1. 먼저 확인한 것 — 이미 있는 R13 depth-aware 경로가 왜 안 통했는가

`fin2/extract/legacy_pre2015.py`(R13, 2026-08-11)가 이미 fy≤2010 문서를
`iter_section_span_depth_aware()` + `detect_pre2015_body_statement_tables()`로
라우팅하고 있고(`report_lines.py:1191` `_PRE2015_ROUTING_MAX_FY=2010`), 이 경로는
**바로 이 SECTION-3 리셋 문제를 고치려고 설계된 것**이었다(같은 파일 모듈
docstring). fy2004~2006이 이 범위에 들어가므로 "이미 고쳐져 있어야 정상"인데
실측(현재 코드, `extract_report_lines()` 직접 호출)하면:

| 표본 | 결과 |
|---|---|
| 호텔신라 `20050915000066`(fy2005 H1) | **0행** |
| SK네트웍스 `20080331001324`(fy2007 FY) | **0행** |

즉 **R13이 이미 배포·백필됐음에도 배경문서가 지목한 943건이 여전히 안 뚫린다**
— 배경문서의 "원인 규명 완료"는 `assign_tables_to_dart_sections()`(R13 **이전**
경로)를 격리 호출한 결과였을 가능성이 높고, R13 경로 자체의 결함은 못 봤다.
아래는 두 표본을 **원문 XML 직접 대조**로 다시 판 결과다.

### 2-2. (A-1) `iter_section_span_depth_aware()` 자체 버그 — 컨테이너 통짜블롭

**재현(호텔신라)**: SECTION-2 `'4. 재무제표'` 안에 SECTION-3
`'가. 대차대조표'`가 중첩된 구조. `iter_section_span_depth_aware()`를 직접
호출하면 이 SECTION-3 진입 시점에 **SECTION-3 요소 자신**이 `out`에 append되는데,
`el.itertext()`는 lxml에서 **하위 서브트리 전체 텍스트를 재귀로 합친 것**이라
"가.대차대조표" + "대차대조표"(TABLE-GROUP) + 표 헤더 + **표 데이터 전체**가 한
문자열로 뭉쳐 나온다. 이 통짜문자열을 `classify_pre2015_statement_heading()`에
넣으면 "대차대조표" 뒤에 기간마커가 아니라 **또 "대차대조표..."가 이어져** 5번째
통과조건(`_PRE2015_PERIOD_AFTER`)에서 거부된다 — 결국 헤딩 판정 자체가 실패.

**근본원인**: 함수 자신의 docstring(L48-49)은 "하위표제(entry_depth 보다 깊은
SECTION)는 통과시키고 **그 TITLE 텍스트도 요소로 낸다**"고 약속하지만, 실제
코드는 `tag != "TITLE"`인 경우만 append하는 필터만 있고, **SECTION 컨테이너
자신을 append 대상에서 빼는 로직이 없다** — docstring이 이미 옳게 설계했던 것을
구현이 놓친 진짜 버그다(새 설계가 아니다).

**패치안**(`fin2/extract/legacy_pre2015.py:54-88`, `iter_section_span_depth_aware`
본문):

```python
# 현재 (L58-88 요약)
for event, el in etree.iterwalk(root, events=("start", "end")):
    tag = el.tag.upper() if isinstance(el.tag, str) else ""
    is_section = tag.startswith("SECTION")
    if event == "end":
        if is_section:
            depth -= 1
        continue
    if is_section:
        depth += 1
        title_elem = el.find("TITLE")
        norm = (normalize_dart_section_title("".join(title_elem.itertext()))
                if title_elem is not None else None)
        if inside and norm is not None and depth <= entry_depth and norm != normalized_title:
            inside = False
            entry_depth = None
        elif not inside and norm == normalized_title:
            inside = True
            entry_depth = depth
            continue
    if inside and tag != "TITLE":            # ← SECTION 컨테이너도 여기 걸려 append됨(버그)
        ...
        out.append((tag, el))
```

```python
# 변경 후
if is_section:
    depth += 1
    title_elem = el.find("TITLE")
    norm = (normalize_dart_section_title("".join(title_elem.itertext()))
            if title_elem is not None else None)
    if inside and norm is not None and depth <= entry_depth and norm != normalized_title:
        inside = False
        entry_depth = None
    elif not inside and norm == normalized_title:
        inside = True
        entry_depth = depth
    elif inside and title_elem is not None:
        # ★2026-09-05(설계) — 하위표제(entry_depth 보다 깊은 SECTION) 통과 시
        # 컨테이너 자신(el.itertext() 가 서브트리 전체를 통짜로 합쳐 헤딩판정을
        # 깨뜨림, 실측: 호텔신라 20050915000066)을 내면 안 되고, docstring이
        # 원래 약속한 대로 TITLE 텍스트만 헤딩 후보로 낸다.
        out.append(("TITLE", title_elem))
    continue          # ★ SECTION 컨테이너 자신은 절대 append하지 않는다(항상 continue)
if inside and tag != "TITLE":
    ...
    out.append((tag, el))
```

핵심 변경: **`if is_section:` 블록 끝에 항상 `continue`를 추가**해 SECTION 컨테이너
자신이 아래 일반 append 블록에 떨어지는 경로를 원천 차단하고, 대신 통과되는
하위표제의 TITLE 텍스트만 별도로 낸다. `elif` 하나 추가 + `continue` 위치 이동뿐 —
**기존에 이미 통과하던 경로(진입/이탈 판정)는 그대로**다.

**검증(패치 프로토타입으로 직접 실행 확인)**: 호텔신라 표본에서 패치 적용 후
`classify_pre2015_statement_heading()`이 "가.대차대조표"/"나.손익계산서"/
"라.현금흐름표" 등 헤딩을 **전부 정상 매치**했다(BS/IS/CF/APPR 순서로 pending
상태 정확히 순환 확인, 아래 §2-4 트레이스 로그 참고).

### 2-3. (A-2) `normalize_dart_section_title()`가 한글 가나다 접두를 안 벗김 — 진입 자체 실패

**재현(SK네트웍스)**: 이 문서는 호텔신라와 레이아웃이 다르다 — SECTION-2가
`'2. 개별재무제표에 관한 사항'`(정규화 후 "개별재무제표에관한사항", `SEC_SEP_FS`
"재무제표"와 **불일치**)이고, 실제로 `SEC_SEP_FS`와 **정확히 일치하는 제목
"재무제표"는 그 안의 SECTION-3 `'라. 재무제표'`에 있다.**

`iter_section_span_depth_aware(root, "재무제표")`는 SECTION 태그를 깊이와 무관하게
전부 검사하므로 이론상 이 SECTION-3도 "진입" 후보가 될 수 있어야 하는데, 실제로는
**진입 자체가 안 된다**(entered=False, 실측) — 원인은
`parser/xml/section_detector.py::normalize_dart_section_title()`의 번호제거
정규식이 `_SEC_NUM_PREFIX_RE = re.compile(r"^[\dⅠ-Ⅻ IVXivx]+\s*[.．)]\s*")`로
**숫자·로마숫자만** 벗기고 한글 가나다 접두는 안 벗기기 때문 — `'라. 재무제표'`가
정규화돼도 `"라.재무제표"`로 남아 목표값 `"재무제표"`와 절대 일치하지 않는다.
결국 `detect_pre2015_body_statement_tables()`가 이 문서에서 **한 번도 "inside"
상태에 진입하지 못해 통째로 빈 결과**를 낸다 — (A-1)과 완전히 다른, 더 앞단의
차단이다.

**패치안** — 두 갈래 중 택1(승인 필요, §2-3-1/2-3-2):

- **(A-2-옵션1, 좁은 수정)**: `iter_section_span_depth_aware()`의 진입판정 시에만
  가나다 접두를 벗기고 재비교(정규화 함수 자체는 안 건드림 — 2015+ 주경로가
  `normalize_dart_section_title()`을 공유하므로 그쪽 회귀 위험을 원천 차단):

  ```python
  # iter_section_span_depth_aware() 진입판정 직전에 추가
  norm_stripped = _PRE2015_ORDINAL_PREFIX.sub("", norm) if norm else norm
  ...
  elif not inside and (norm == normalized_title or norm_stripped == normalized_title):
      inside = True
      entry_depth = depth
  ```

  (`_PRE2015_ORDINAL_PREFIX`는 이미 같은 파일 L93에 있음 — 재사용.)

- **(A-2-옵션2, 넓은 수정)**: `normalize_dart_section_title()` 자체에 가나다
  접두 제거를 추가. **회귀 위험 큼** — 이 함수는 2015+ 주경로
  (`assign_tables_to_dart_sections`/`classify_dart_section`)와 공유되고,
  `_DART_SECTION_EXACT`엔 "요약재무정보"(SEC_SUMMARY) 같은 정확일치 항목도 있어
  가나다 접두 제거가 2015+ 문서의 어떤 SECTION-3 하위표제를 실수로 승격시킬
  가능성을 배제 못함(이번 조사에서 미검증). **권장하지 않음** — (A-2-옵션1)로
  pre-2015 전용 경로만 고치는 편이 안전.

**검증 필요**: (A-2-옵션1) 프로토타입은 이번 세션에서 실측 안 함(시간 제약) —
드라이런 단계에서 SK네트웍스로 먼저 확인.

### 2-4. (A-3) ★가장 큰 문제 — "표 한 셀에 여러 줄이 통짜로 압축된" 레거시 표 포맷

(A-1) 패치를 적용해 헤딩 판정까지는 성공시킨 뒤(§2-2 검증 로그), 실제 **데이터
표**까지 도달했는데 — 호텔신라·한국팩키지(`20040528000335`, 무작위 943건
후보군에서 추출한 추가 표본) **2건 모두 데이터표가 인식되지 않는다.**

**재현**(원문 XML 직접 확인, 호텔신라 대차대조표 두 번째 TABLE):

```xml
<TD ...>자         산Ⅰ. 유  동  자  산 (1) 당  좌  자  산  1. 현금및현금등가물
  2. 단기금융상품  3. 매 출 채 권      대손충당금  4. 단기대여금 ... (계정과목
  전부가 줄바꿈 없이 한 TD 안에 이어짐)</TD>
<TD ...>90,183,592,33138,221,927,31322,609,766,018-11,347,503,582555,583,606...
  (금액도 전부 줄바꿈·구분자 없이 한 TD 안에 이어짐, 개별 숫자만 콤마 3자리
  그룹으로 식별 가능)</TD>
```

즉 **표 전체가 물리적으로 TR 1개**(헤더 TR + 데이터 TR 1개)이고, 계정과목 N개·
금액 N개가 각각 **하나의 셀 안에 문자열로 다 이어붙어** 있다 — 정상 서식이면
계정과목마다 TR이 하나씩 있어야 하는데, 이 옛 레이아웃은 그렇지 않다(아마 원본
인쇄물의 줄바꿈이 XML 변환 과정에서 소실됐거나, 애초에 이렇게 인코딩된 원본).

`parser/xml/section_detector.py::table_has_amount_rows()`(계층2 전체가 "데이터표
인가"를 판정하는 유일 창구, `_AMOUNT_CELL_RE = r"^\(?-?\d{1,3}(?:,\d{3})+\)?$"`)는
**셀 전체가 숫자 하나와 정확히 일치**해야 통과한다 — 위 셀은 숫자 여러 개가
붙어 있어 이 조건을 절대 못 만족한다. 결과: 이 표 자체가 "데이터표 아님"으로
판정돼 **완전히 스킵**된다. (A-1)+(A-2)를 둘 다 고쳐도 이 표 형식인 문서는 여전히
0행이다.

**규모 추정 — 이번 조사에서 확인된 것만**: fy2004~2006 무작위 943건 후보 중
파일이 존재하는 표본 8건을 (A-1) 패치 적용 상태로 재실행 → **8건 모두 0행**(진입은
성공했는데 최종 산출이 0). 그중 직접 원문 대조한 2건(호텔신라·한국팩키지)이
전부 이 통짜-셀 포맷이었다 — **표본 수가 작아 정확한 비율은 모르지만, "943건
대부분이 (A-1)+(A-2)만으로는 안 뚫리고 이 문제에 막혀 있을 가능성"이 높다.**
정확한 비율은 §3 정량화 전에는 확정할 수 없다.

**왜 이번 설계 스코프에 안 넣는가**:
1. **위험도가 다르다** — (A-1)/(A-2)는 "헤딩을 못 찾으면 그냥 스킵"이라 최악의
   결과가 "결측 유지"다. (A-3)은 **숫자를 정규식으로 잘라 재구성**해야 하는데,
   콤마 3자리 그룹 규칙만으로 경계를 자르는 건 음수 표기(호텔신라는 ASCII
   `-`, 한국팩키지는 `△`), 공백/`-`만 있는 빈 셀, 계정과목 텍스트 안에 숫자가
   섞인 경우(예: "10. 유동성이연법인세차") 등과 얽혀 **틀린 값을 만들 위험**이
   구조적으로 있다 — "0행(결측)"보다 나쁜 "잘못된 값 적재" 실패모드
   (R69 안전성 논리 §3의 원칙과 정면으로 배치).
2. **계정과목-금액 리스트를 위치로 정렬**해야 하는데 두 리스트의 항목 수가
   항상 일치한다는 보장이 이번 표본만으로는 확인 안 됨(계정과목 쪽엔 있고
   금액 쪽엔 없는 소계/구분줄이 있을 수 있음 — 미검증).
3. 규모(943건 중 몇 %)도 모르는 채로 설계하면 배경문서와 같은 실수(표본 부족 →
   재작업)를 반복한다.

**권고**: (A-3)은 **별도 트랙**으로 분리 — 정량화(§3) 먼저, 그 다음 전용 설계
문서(이번 문서와 별개)로 사용자 승인을 다시 받는다.

---

## 3. 정량화 계획 (구현 승인 후, 드라이런 1단계)

1. fy2004~2006 943건 후보(위 DB 쿼리 재사용: `filings` × `report_lines` 없음
   기준) 전수에 대해 파일 존재 여부부터 확인 — 이번 조사에서 이미 **15건 중
   7건이 파일 자체가 없거나 PDF-only**(예: 웹젠 `20050428000577`은 `.xml`이 아니라
   `.pdf`)임을 확인했다. 이 하위집합은 (A)와 무관 — PDF 복구 트랙(항목1,
   `v2-drop-remaining-backlog` 메모리 참고) 또는 별도 `missing_file` 이슈로 분리.
2. XML이 있는 나머지에 대해 (A-1)+(A-2) 패치를 **드라이런**(DB에 안 씀) 적용해
   `extract_report_lines()` 재실행 → 회수 성공/부분성공/(A-3)에 막혀 여전히
   실패 3분류로 집계. 이 집계가 나와야 (A-3) 트랙의 실제 규모(943건 대비 비율)를
   알 수 있다.
3. (C)는 별도로 fy2014류 "요약" 접두 후보 전수(스캔 쿼리 신규 필요 — 이번
   세션은 표본 1건만 확인) 재실행 → 회수율 집계 + §1-4 회귀위험(요약표 중복)
   표본 검사.

## 4. 축소 옵션 — 무엇부터 승인받을지

| 옵션 | 내용 | 예상 회수 | 위험 |
|---|---|---|---|
| (C)만 | §1-3 두 곳 수정 | 낮은 건수(fy2014류, 정량화 전) | 낮음(추가적 변경, 요약표 중복만 드라이런에서 확인) |
| (A-1)+(A-2)만 | §2-2+§2-3 수정 | **미지수 — (A-3)에 막혀 943건 대부분 여전히 0행일 가능성 있음**(§2-4) | 낮음(추가적 변경) |
| (A) 전체(A-1+A-2+A-3) | 위 + 통짜-셀 숫자 재구성 | 943건 대부분(추정) | **높음 — 틀린 값 적재 위험, 별도 설계·별도 승인 필요** |

사용자 결정이 필요한 지점: (C)와 (A-1)+(A-2)는 지금 승인해서 진행하되, (A-3)은
정량화 결과를 먼저 보고 별도로 설계·승인받는 3단계 진행을 권장한다.

## 5. 안전성 근거 ((C), (A-1), (A-2) 공통)

- 전부 **추가적** 변경 — 기존에 이미 통과하던 케이스의 판정 경로는 그대로다
  (R69 (B)/(D)/(E)와 같은 안전 논리, 그 문서 §3 참고).
- (A-1)/(A-2)는 `iter_section_span_depth_aware`/pre-2015 전용 경로 **내부**만
  건드리고, 2015+ 주경로(`assign_tables_to_dart_sections`,
  `_detect_body_statement_tables`)는 무변경 — 회귀 스코프가 fy≤2010 문서로
  원천 제한된다(`_PRE2015_ROUTING_MAX_FY` 라우팅 게이트, 무변경).
- (C)는 `classify_legacy_statement_heading` 내부만 건드리고, 이 함수를 호출하는
  `_detect_legacy_body_statement_tables`도 무변경 — 표 선택·단위판정·
  pending-거리제한·주석마커 차단은 전부 그대로 물려받는다.

## 6. 백필 계획 (구현·검증 통과 후)

- 배선 불요 — `extract_report_lines()`/`detect_pre2015_body_statement_tables()`/
  `classify_legacy_statement_heading()` 전부 기존 함수 내부 로직 수정.
  `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①(신규 배선)은
  해당 없음, **②(소급 백필)만 필요**.
- 실행 패턴은 R69/PDF복구 트랙과 동일: `sync_layer2_lines(corps=…)` →
  `build_corp(session, corp, …)` 2단계, 멱등(rcept 단위 delete-then-insert).
- corp 목록은 §3 정량화 결과에서 "회복 성공"으로 나온 rcept만 추려 사용.

## 7. PARSING_RULES.md 반영

CLAUDE.md 규칙대로 구현 승인 시점에 R70(가칭)으로 등재하고 이 파일을 링크한다
— 지금은 계획 문서 단계라 미등재.
