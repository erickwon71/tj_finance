# 헤더 먼저 읽기(R88 방식) 확장 — 전체 표 파서 대상 설계 (2026-09-10)

> 상태: **설계만, 미구현.** 사용자 승인 후 착수(CLAUDE.md "계획 후 대기" 원칙).
> R88(`docs/plans/report_lines_header_grid_column_map_design_2026-09-09.md`)이 XML
> BS/IS/CF 하나에만 적용한 "헤더를 먼저 읽어 구조를 파악하고 값을 선택" 방식을,
> 프로젝트 안의 **나머지 표 파서 전체**로 넓힐지/어떻게 넓힐지 정리한다.

## 0. 왜 대상마다 접근이 다른가

R88의 핵심은 "`<THEAD>` 를 COLSPAN/ROWSPAN 그리드로 해석 → 위치→기간 맵을 만든 뒤
데이터 행을 그 맵으로 인덱싱"이다. 이게 그대로 이식되려면 **원문에 진짜 표 마크업이
있어야** 한다. 지난 조사(대화 로그)로 확인한 대상별 현황:

| 대상 | 표 마크업 | 헤더 판정 현황 | R88 이식 가능성 |
|---|---|---|---|
| XML BS/IS/CF(`table_extractor.py`) | `<THEAD>` COLSPAN/ROWSPAN | ✅ R88 적용 완료(2026-09-09) | (완료) |
| **HTML 웹뷰어(`html_viewer.py`)** | `<TABLE><TR><TD>`, **`<THEAD>` 없음** — 헤더행도 `<TBODY>` 안 첫 `<TR>`(들)로 옴(실측 확인, §1) | 헤더 무시, 행별 "첫 숫자셀" 값-위치 휴리스틱 | **가능 — 이번 설계의 핵심 대상** |
| PDF(`fin2/extract/pdf.py`) 주경로 | 없음(좌표 텍스트, 표 개념 자체가 없음) | 앵커+텍스트패턴 휴리스틱 | **불가능**(대상 자체가 없음) |
| PDF 표-격자 폴백(`pdfplumber.extract_tables()`) | 있음(그리드는 나오나 헤더행 식별 안 함) | `row[1:]` 물리위치 그대로 사용 | 가능하나 실사용 빈도 낮음(텍스트 게이트 실패시만) |
| `biz_section.py`/`sales_section.py`/`order_backlog.py` | XML COLSPAN/ROWSPAN(자체 `expand_table_grid`) | **이미 자체 헤더선독**(`_is_period_header_cell` 등, R88보다 먼저 만들어짐) | 이식이 아니라 **중복 통합** 검토 대상 |
| `note_extractor.py`/`shares.py`/`rd_note.py`/`expense_nature.py` | 제각각(단일값 스칼라·라벨:값 1쌍 등, "기간 열" 구조가 아닌 경우 다수) | 개별 휴리스틱 | 이번 스코프 밖(§5) |

## 1. HTML 웹뷰어(`fin2/extract/html_viewer.py`) — ★최우선 대상

### 1-1. 실측 확인(이번 세션)
`scripts/probe_html_viewer_layout_sample_2026-09-07.py`/`scan_html_viewer_layout_93_
2026-09-07.py` 코드 확인 결과, 레이아웃 B(행별-`<TR>`형) 표는 `<THEAD>` 없이 헤더행도
`<TBODY>` 안의 **첫 `<TR>`(들)**로 들어온다(제일기획 00148276 주석 — "헤더가 제28기/
제27기/제26기"). 즉 R88의 "`<THEAD>` 존재 여부로 시도/폴백을 가른다"는 전제가 그대로
안 맞는다 — **"헤더행인지 아닌지"부터 내용으로 판정**해야 한다.

이건 사실 R88 설계문서 §7이 이미 다음 확장 지점으로 찜해둔 문제와 동일하다:
> "THEAD 없는 구형(K-GAAP, TD-only 무헤더) 표 지원 — 첫 데이터행 앞의 '헤더 패턴에
> 걸리는 TR들'을 THEAD 대용으로 삼는 방식 검토."

pre-2015 K-GAAP XML과 html_viewer.py가 **같은 문제**(THEAD 없이 헤더행이 본문과 섞여
있음)를 갖고 있으므로, 판정 로직을 공유 유틸로 뽑아 두 곳에서 같이 쓰는 게 맞다(§3).

### 1-2. 현재 알려진 결함과의 연결
`html_viewer.py` 모듈 docstring이 이미 자인하고 있는 갭 — "interim(H1/Q1/Q3) IS/CF의
'3개월 vs 누적' 2단 헤더 컬럼 구분을 이 모듈은 아직 안 한다(항상 col0)" — 은 R85~R87이
XML에서 겪었던 것과 **완전히 같은 클래스의 버그**다. 헤더를 먼저 읽으면 이 갭이
자연스럽게 같이 해소된다(부가 효과이지 별도 작업이 아님).

### 1-3. 제안 설계 방향(구현 세션에서 확정)
1. `<TABLE>` 안에서 "헤더행 후보"를 판정하는 함수 신설 — 한 `<TR>`의 모든 셀이
   기간패턴(`_PERIOD_KEY_RE`와 동일 어휘, table_extractor.py에서 가져옴)에 매치하거나
   빈칸/라벨열이면 헤더행. 그 다음 진짜 계정 라벨이 나오는 `<TR>`부터 데이터 시작.
2. 헤더행(들)을 모으면 R88과 동일하게 `HeaderColumn` 리스트(position/period_rank/
   subtype/is_note)를 만들 수 있다 — COLSPAN/ROWSPAN 해석도 `table_extractor.py`의
   `_resolve_header_grid()`를 그대로 재사용(BeautifulSoup Tag에서 COLSPAN/ROWSPAN 속성
   읽는 어댑터만 새로 필요, 알고리즘은 동일).
3. 실패(헤더행 후보를 못 찾음·기간패턴 인식 실패)하면 **기존 "첫 숫자셀" 휴리스텁으로
   완전히 폴백** — R88과 동일한 안전원칙(회귀 위험 최소화).
4. 레이아웃 A(거대-셀형, `<BR>` 세그먼트)는 애초에 헤더가 데이터와 함께 있지 않은
   구조라 대상 아님(현행 유지).

## 2. PDF 표-격자 폴백(`fin2/extract/pdf.py::_table_rows_for_span`)

`pdfplumber.extract_tables()`가 반환하는 grid는 헤더/본문 구분이 안 된 `list[list]`
그대로다. 지금은 이 폴백 자체가 **텍스트 라인 파싱이 앵커 라벨을 못 찾았을 때만**
발동하는 드문 경로(§0 표)라, 헤더 판정을 붙여도 효과 범위가 좁다. 붙인다면 1번(html_
viewer)에서 만든 "헤더행 후보 판정 + HeaderColumn 매핑" 로직을 재사용하되, **우선순위는
낮게** 잡는다(사용 빈도 대비 구현 비용).

PDF **주경로**(텍스트 anchor + `_iter_data_lines`)는 대상에서 제외한다 — 표 마크업 자체가
없어 "헤더를 먼저 읽는다"는 개념이 성립하지 않는다(이미 사용자와 확인된 사실).

## 3. 공유 인프라 제안 — "헤더행을 내용으로 판정"하는 공용 유틸

`parser/xml/table_extractor.py`에 다음을 신설해 XML(pre-2015 확장, R88 §7)과 html_
viewer.py 양쪽이 같이 쓴다:

```python
def _looks_like_header_row(cell_texts: list[str]) -> bool:
    """라벨열을 제외한 모든 셀이 기간패턴(_PERIOD_KEY_RE)에 매치하거나 빈칸이면 헤더행."""
```

이 판정 + 기존 `_resolve_header_grid`/`_header_column_stack`/`parse_header_columns`의
"헤더 텍스트 스택 → HeaderColumn" 로직을 **THEAD 유무와 무관하게** 쓸 수 있도록
`parse_header_columns()`를 "THEAD가 있으면 그걸 쓰고, 없으면 선두 TR들 중 `_looks_like_
header_row`에 걸리는 것들을 THEAD 대용으로 모은다"로 확장한다 — 이러면 R88 §7(pre-2015
XML)과 이번 html_viewer.py 확장이 **같은 코드 경로**를 타게 된다(중복 구현 회피).

## 4. `biz_section.py`/`sales_section.py`/`order_backlog.py` — 통합 검토(선택, 별도 트랙)

이미 R88 이전(2026-07-04)부터 자체 `expand_table_grid()`(ROWSPAN/COLSPAN 확장, `table_
extractor.py`의 알고리즘과 사실상 동일 로직 중복 구현)와 `_is_period_header_cell()`(헤더
판정)을 갖고 있다. **새 기능 추가가 아니라 코드 중복 제거** 성격이라, 이번 "헤더파싱
추가" 작업과는 목적이 다르다 — 원하시면 별도 리팩터링 트랙으로 분리 제안. 이번 설계
스코프에는 포함하지 않는다(행동 변경 없는 순수 정리라 회귀 검증 방식도 다름).

## 5. 스코프 제외 — 주석/스칼라 계열

`note_extractor.py`(CF 주석 D&A), `shares.py`(주식총수, **raw-text 정규식** 스캔이라
애초에 lxml 표 그리드 경로가 아님), `rd_note.py`, `expense_nature.py`는 "기간 열이
반복되는 표" 구조가 아니라 "라벨:값 한 쌍" 또는 표 자체가 성격이 다른 경우가 섞여
있다. 일괄 적용하면 오히려 위험 — 대상별 개별 조사가 먼저 필요하다. **이번 설계
스코프에서 제외**, 필요시 후속 세션에서 개별 검토.

## 6. 제안 순서(우선순위)

1. **html_viewer.py**(§1) — 효과 최대(현재 알려진 interim 3개월/누적 갭도 같이 해소),
   Track C 잔여 스코프라 영향 범위가 격리돼 있어 회귀 위험 낮음.
2. **공유 유틸 추출 + `parse_header_columns()`의 THEAD-없음 폴백 확장**(§3) — 1번의
   부산물로 얻어지며, R88 §7(pre-2015 K-GAAP XML)도 같이 커버.
3. `biz_section.py` 계열 중복 통합(§4) — 선택 사항, 별도 트랙 제안.
4. PDF 표-격자 폴백(§2) — 우선순위 낮음, 사용 빈도가 작아 마지막.

## 7. 검증 계획(각 단계 공통)

- 합성 HTML/XML fixture로 단위테스트(R88이 `test_header_grid_column_map_r88.py`에서
  한 것과 동일 패턴 — 헤더행 후보 판정, HeaderColumn 매핑, 폴백 케이스 각각).
- 실측 파일 회귀 — html_viewer.py는 기존 93건 census(`scan_html_viewer_layout_93_
  2026-09-07.py`) 재실행으로 무회귀 확인, 특히 레이아웃 B 표본(제일기획·DB증권 등
  이미 알려진 함정 케이스) 개별 재확인.
- `pytest tests/ fin2/tests/` 전체 무회귀.
- 사용자 원문대조(R9 원칙 — 검증은 집계가 아니라 원문 대조로) 최소 1~2건.

## 8. 다음 단계

이 문서 승인 후: (1) §1 html_viewer.py부터 구현 → (2) §3 공유 유틸 리팩터링 → (3)
PARSING_RULES.md에 새 규칙(R89)으로 결과 기재(프로젝트 관행) → (4) §4/§2는 사용자
결정에 따라 별도 착수 여부 확정.
