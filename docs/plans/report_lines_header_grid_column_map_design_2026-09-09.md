# report_lines 컬럼판정 — THEAD COLSPAN/ROWSPAN 그리드 기반 재설계 (2026-09-09)

## 0. 배경 — 왜 지금 이걸 하는가

R85(EPS 컬럼선택)·R86(else 분기 선두절삭)·R87(extract_rows 동형 결함)이 전부 같은
계열의 문제였다: **표가 몇 열이고 각 열이 어느 회계기간을 가리키는지를, 데이터 행의
공란 패턴을 보고 사후에 추측**해왔다. 추측 방식마다(cum_map의 헤더-토큰탐색·
multicol의 "원문 금액셀≥2×n_periods" 임계값·else의 "선두 None 절삭") 서로 다른
안전장치(acontext_missing·sanemax-거부증거·table_has_note_column)를 덧붙여왔지만,
사용자가 지적한 대로 **애초에 표 헤더(THEAD)가 이미 그 구조를 명시적으로 선언하고
있다** — 원문 XML을 직접 열어보면 COLSPAN/ROWSPAN, 심지어 `ENG` 속성까지 구조를
정확히 담고 있다(§1 실측).

이 문서는 그 구조를 **먼저 읽어서** 위치→회계기간 맵을 만들고, 데이터 행은 그 맵으로만
인덱싱하는 방식으로 재설계한다. 헤더를 못 읽는 표(THEAD 없음 등)는 기존 로직(cum_map/
multicol/else, R85~R87 가드 포함)으로 **그대로 폴백** — 이 세션에서 검증 못한 표까지
건드리지 않는다(회귀 위험 최소화).

## 1. 실측 — 원문 헤더 구조 카탈로그 (5개사, 서로 다른 형태)

| 회사/필링 | 표 | 구조 |
|---|---|---|
| 삼성전자 00126380, 20200330003851(2019FY) | 별도 CF | `<THEAD><TR><TH>구분</TH><TH>제51기</TH><TH>제50기</TH><TH>제49기</TH></TR></THEAD>` — COLSPAN 없음, 순수 3열 |
| 삼성전자 00126380, 20170515003806(2017Q1) | 별도/연결 CF | `<THEAD><TR><TH>　</TH><TH>제49기1분기</TH><TH>제48기1분기</TH><TH>제48기</TH><TH>제47기</TH></TR></THEAD>` — COLSPAN 없음, 순수 4열(같은 분기 IS는 COLSPAN=2로 3개월/누적 분할하지만 CF는 안 함) |
| 삼성전자 00126380, 20250814003156(2025H1) | 별도/연결 IS | `<THEAD><TR><TH ROWSPAN=2>　</TH><TH COLSPAN=2 ENG="CFHY">제57기반기</TH><TH COLSPAN=2 ENG="PFHY">제56기반기</TH></TR><TR><TH ENG="THREE MONTH">3개월</TH><TH>누적</TH><TH>3개월</TH><TH>누적</TH></TR></THEAD>` — 2행 헤더, 상단은 기간명(ENG 태그 포함), 하단이 진짜 구분(3개월/누적) |
| 삼성생명 00126256, 20170331005566(2016FY) | 연결 CF | `<THEAD><TR><TH>과목</TH><TH COLSPAN=2>제61(당)기</TH><TH COLSPAN=2>제60(전)기</TH><TH COLSPAN=2>제59(전전)기</TH></TR></THEAD>` — 1행 헤더, COLSPAN=2인데 **하위 구분 텍스트가 아예 없음**(명세/소계는 행 유형[소계행=짝수쪽만·명세행=홀수쪽만]으로만 구분됨) |
| 대한제분 00113243, 20260814002054(2026H1) | 연결 CF | `<THEAD><TR><TH>　</TH><TH ENG="FY 2026">제76기반기</TH><TH ENG="FY 2025">제75기반기</TH></TR></THEAD>` — COLSPAN 없음, 순수 2열, TE(XBRL) 렌더링에서도 동일 패턴 |
| 삼성전자 00126380, 요약연결현금흐름표(주석) | 요약표 | `<THEAD><TR><TH ROWSPAN=2>구분</TH><TH COLSPAN=2>삼성디스플레이㈜와 그 종속기업</TH></TR><TR><TH>당기</TH><TH>전기</TH></TR></THEAD>` — 상단 COLSPAN 그룹이 "기간"이 아니라 "회사명"이고, 진짜 기간 구분(당기/전기)이 **아래 행**에 있음 |

핵심 관찰: **"상단 행=기간, 하단 행=세부구분"이 항상 성립하지 않는다**(마지막 사례는
반대). 그래서 파서는 "N번째 행이 기간"이라고 가정하면 안 되고, **각 열의 헤더 텍스트
전체(위→아래)를 훑어 기간 패턴("제 N 기"/"당기"/"전기"/"전전기" 등)이 어디서 나오든
찾아내야** 한다(§3 알고리즘).

## 2. 데이터 구조

```python
@dataclass
class HeaderColumn:
    position: int              # 0-based, 라벨열 제외한 "원시" 금액셀 위치
                                # (keep_all_amount_cells=True 로 뽑은 row.amounts 와 같은 인덱스)
    period_key: str            # 기간 식별 텍스트("제 51 기"/"제 49 기 1분기"/"당기" 등, 원문 그대로)
    period_rank: int           # 0=당기(가장 왼쪽 최초등장 기간), 1=전기, 2=전전기, ...
    subtype: str | None        # "cumulative"|"three_month"|None(구분 텍스트 없음=병합군)
    is_note: bool = False      # 주석참조 열(TH 텍스트에 "주석") — period_rank 없음
```

`parse_header_columns(table) -> list[HeaderColumn] | None` — 실패(THEAD 없음, 기간
패턴 인식 실패, 라벨열 뒤에 인식 못한 열 존재 등)면 `None`(호출측이 기존 로직 폴백).

## 3. 알고리즘

### 3-1. 그리드 해석 (`_resolve_header_grid`, `parser/xml/table_extractor.py`)

표준 HTML 표 ROWSPAN/COLSPAN 해석 — THEAD 의 각 TR 을 순서대로 훑으며, 이미 이전
행의 ROWSPAN 이 차지한 열은 건너뛰고, 새 셀은 (COLSPAN×ROWSPAN) 크기의 사각 영역에
그 셀 텍스트를 채운다. 결과: `grid[row][col] -> str`(텍스트, 스팬 영역엔 같은 텍스트
반복). THEAD 가 없으면 `None`(폴백).

### 3-2. 라벨열 판정

grid 의 0번 열부터, 그 열의 텍스트 스택(§3-3)에 기간 패턴이 **전혀** 없는 동안은
라벨열(구분/과목/공란)로 보고 건너뛴다. 기간 패턴이 처음 나오는 열부터가 진짜 데이터
열이다 — `position=0`은 그 열부터 시작.

### 3-3. 열별 헤더스택 → 기간/서브타입 판정

각 데이터 열에 대해, 위→아래로 grid 를 읽어 빈 문자열과 ROWSPAN 으로 인한 연속중복을
제거한 "스택"을 만든다. 스택에서 **처음** 기간 패턴(정규식 `제\s*\d+\s*\(?[가-힣]{0,3}\)?\s*기`
또는 `당기|전기|전전기|전전전기` 단독)에 매치하는 항목을 `period_key`로 삼는다.
- `period_key`가 하나도 없으면: 그 열이 "주석" 텍스트를 포함하면 `is_note=True`,
  아니면 표 전체를 인식 실패로 보고 `None` 반환(안전 폴백).
- `period_rank`: `period_key` **텍스트가 처음 등장하는 열 순서**로 0,1,2,... 매김
  (같은 텍스트를 쓰는 열은 자동으로 같은 그룹 — COLSPAN 으로 이미 반복돼 있으므로
  별도 매칭 로직 불필요).
- `subtype`: `period_key` 매치 지점 **이후** 스택에 남은 텍스트. "누적"/"누계" 포함 →
  `"cumulative"`. "3개월"/"3 개월"/"삼개월" 포함 → `"three_month"`. 아무 것도 안 남으면
  `None`(구분 텍스트 없는 병합군 — 삼성생명류).

### 3-4. 데이터 행 소비 (`_select_by_header_columns`, `fin2/extract/report_lines.py`)

`extract_rows(table, ..., keep_all_amount_cells=True)`로 위치보존 원시 배열을 얻는다
(이미 있는 기능 — 주석 전용으로 쓰이던 것을 재사용, 신규 아님). `period_rank`별로
`HeaderColumn` 그룹을 묶어:
- 그룹에 `subtype`이 있는 열이 하나라도 있으면(구분된 그룹): **"cumulative" 열만**
  선택(R85 정책 그대로) — 그 열이 이 행에서 `None`이어도 다른 서브타입으로 대체하지
  않는다(원문이 실제로 그 값을 비웠다는 사실을 그대로 존중, R3 원칙). "cumulative"
  서브타입 열이 그룹에 없으면(예: 3개월만 있고 누적 열 자체가 없는 표) 유일한 서브타입
  열을 그대로 쓴다.
- 그룹에 `subtype`이 전부 `None`이면(병합군, 삼성생명류): 그 그룹 열들 중 **값이
  있는 것 하나**를 쓴다(정상적으로 정확히 1개만 있어야 함 — 2개 이상 값이 있으면
  판정 불가로 보류, R6 원칙).

## 4. 통합 지점

`fin2/extract/report_lines.py::_emit_section_lines()` — 표 하나당 한 번:

```python
header_cols = parse_header_columns(table)
if header_cols is not None:
    # 신규 경로: header_cols 로 직접 인덱싱, cum_map/multicol/else 전부 우회
    ...
else:
    # 기존 경로 완전히 그대로(cum_map/multicol/else, R85~R87 가드 포함) — 무변경
    ...
```

`statement in ("BS","IS","CF")`에만 적용(SCE 는 열이 기간이 아니라 자본 구성요소
축이라 대상 아님 — 기존과 동일하게 제외). EPS(`_emit_eps_lines`)도 같은 `header_cols`를
넘겨받아 R85 로직을 이걸로 대체할 수 있으나, **이번 구현 스코프에서는 보류** — 이미
R85로 해결된 경로라 이번엔 안 건드리고, `header_cols`가 있으면 cum_map 대신 우선
쓰도록 인터페이스만 열어둔다(다음 세션 확장 지점).

## 5. 폴백 정책(안전장치)

- THEAD 없음 → `None` → 완전히 기존 로직.
- 기간 패턴 인식 실패(알 수 없는 헤더 텍스트) → `None` → 완전히 기존 로직.
- 병합군에서 값이 2개 이상(판정 불가) → 그 특정 (row, period_rank)만 결측 처리(표
  전체를 폴백시키지 않음 — 국소적 보류).
- 이 세션에서 실측 검증한 회사는 5곳(§1)뿐 — 다른 회사/기간에서 새 헤더 모양이 나오면
  `parse_header_columns`가 `None`을 반환해 안전하게 기존 로직으로 빠지고, 그 사례를
  나중에 캐치해 §3-3 패턴을 넓히면 된다(사용자 지시: "다른 모양이 나오는 것은 다른
  기업, 다른 기간에 혹시 문제가 발생하면 추가로 고칠 수 있게").

## 6. 검증 계획

1. 단위테스트(합성 XML) — §1 카탈로그 6개 형태 각각 최소 1개, `parse_header_columns`
   출력이 기대한 `HeaderColumn` 리스트와 일치하는지.
2. 실측 파일 회귀(이미 있는 R85~R87 테스트 파일 재사용) — 신규 경로 적용 후에도
   기존 정답값(삼성전자 2025H1 EPS 누적값, 2019FY 장기매도가능금융자산, 2017Q1
   자기주식의 처분, 삼성생명 명세/소계 등)이 전부 동일하게 나오는지 — **cum_map/
   multicol/else 3갈래를 이 신규 경로로 대체해도 기존 정답이 안 바뀌는지가 핵심
   회귀가드**.
3. `pytest tests/ fin2/tests/` 전체 — 무관 기존실패 2건 외 회귀 0 확인.
4. `rcpNo=20170515003806`(삼성전자 2017Q1) 재적재 — 사용자가 직접 확인.

## 7. 다음 세션 확장 지점(이번엔 미착수)

- THEAD 없는 구형(K-GAAP, TD-only 무헤더) 표 지원 — 첫 데이터행 앞의 "헤더 패턴에
  걸리는 TR들"을 THEAD 대용으로 삼는 방식 검토.
- EPS(`_emit_eps_lines`)를 `header_cols` 기반으로 통합(R85 대체).
- 전사 census(THEAD 있는 표 중 `parse_header_columns`가 `None` 반환하는 비율/원인
  분류) — 폴백 비율이 얼마나 되는지 실측해 다음 확장 우선순위 결정.
