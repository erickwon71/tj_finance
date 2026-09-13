# THEAD 없는 표의 배너/캡션행 건너뛰기 (R95, 2026-09-12)

## 배경

사용자가 `scripts/reload_report_lines_2015plus_2026-09-12.py` 실행 결과를 원문과
직접 대조하던 중, 특수건설(00186939) `20151116001903`(2015Q3 별도재무상태표)에서
발견:

> 표안에 단위도 있고 계정명:주석:당기:전기 이런 구조이고 당기아래에는 흔한 2열
> 구조야. 그런데, 당기에 비어있는 경우 전기 데이터를 가져오는 오류가 아직 남아
> 있네.

원문(제45기=당기, 제44기=전기) 대조 결과, **미착품·장기차입부채·장기차입금** 등
다수 계정이 당기(2열) 전부 공백인데 전기(2열째)만 값이 있었고, DB엔 그 전기값이
당기값으로 그대로 들어가 있었다.

## 근본원인

`parser/xml/table_extractor.py::parse_header_columns()`(R88) → THEAD 없으면
`_headerless_header_trs()`(R89 §7)가 TBODY 선두 TR들을 훑어 헤더 대용을 모은다.

이 표의 실제 TBODY 순서:

```
TR0 <TD COLSPAN=6>재무상태표</TD>                              ← 표제목(배너)
TR1 <TD COLSPAN=6></TD>                                        ← 공백행
TR2 <TD COLSPAN=6>제 45기 2015년 09월 30일 현재</TD>            ← 기준일(배너)
TR3 <TD COLSPAN=6>제 44기 2014년 12월 31일 현재</TD>            ← 기준일(배너)
TR4 <TD>회사명 : (주)특수건설</TD><TD COLSPAN=4></TD><TD>(단위:원)</TD>  ← 회사명/단위(배너)
TR5 <TD>계정명</TD><TD>주석</TD><TD COLSPAN=2>제45(당)기</TD><TD COLSPAN=2>제44(전)기</TD>  ← 진짜 헤더행
TR6 <TD>자산</TD><TD></TD>×5                                   ← 진짜 섹션행(값 전부 공란)
TR7 <TD>유동자산</TD>...(당기/전기 값)...                        ← 진짜 데이터행
```

`_looks_like_header_row()`는 라벨열(cell[0])을 뺀 나머지 셀 중 금액이 있으면
"데이터"(False), 기간마커가 있으면 "헤더"(True), **둘 다 없으면 "데이터"(False)**로
판정한다 — TR0(라벨열 뺀 나머지가 아예 없음)부터 곧바로 False가 나와
`_headerless_header_trs()`가 **첫 줄에서 멈춘다**. `header_trs=[]` →
`parse_header_columns()`가 `None`.

`None`이면 `report_lines.py`(`_emit_section_lines`)가 legacy `_detect_period_
layout()`/multicol 폴백으로 떨어진다. 이 표는 기간당 2열(spacer+값) 인쇄 방식이라
"raw(4) ≥ 2×n_periods(2×2=4)" 조건에 걸려 multicol 로 오판되고, 그 압축 로직은:

```python
present = [a for a in row.amounts if a is not None]
pairs = list(enumerate(present[:n_periods]))
```

— **어느 기간그룹에 속했는지 따지지 않고** 왼쪽부터 채워 넣는다. 당기 2열이
통째로 비면, 전기 2열째의 유일한 값이 `present[0]`이 되어 `pairs`의 `(0, 값)` =
**당기 자리**로 들어간다.

### 왜 TR0~TR4가 전부 "False(데이터)"로 오판되는가

TR6("자산", 진짜 섹션행)도 신호가 완전히 같다 — 라벨 뺀 나머지 전부 공란, 마커
없음. 텍스트 내용만으론 배너행과 진짜 빈 섹션행을 구분할 수 없다.

## 수정

구분 기준을 **모양**(물리 셀 개수)으로 바꾼다: `<COLGROUP>`이 선언한 표의 총
열수 대비, 이 행의 실제 TD 개수가 적으면 COLSPAN 병합이 있다는 뜻 — 배너/캡션행은
항상 이렇게 병합돼 있고, TR6("자산")처럼 값이 전부 공란인 진짜 섹션행은 그래도
칸 자체는 표 전체 폭(물리 셀 수 = 선언 열수)을 채운다.

```python
def _row_has_amount(cell_texts): ...          # 신규 — 기존 로직에서 분리
def _table_colgroup_ncols(table): ...          # 신규 — <COLGROUP><COL/>.. 개수

def _headerless_header_trs(table):
    n_cols_declared = _table_colgroup_ncols(table)
    for tr in candidate_trs:
        cells = _get_cells(tr)
        is_banner = n_cols_declared is not None and 0 < len(cells) < n_cols_declared
        if is_banner:
            if _row_has_amount(cells[1:]):
                break                           # 안전장치 — 배너 모양이라도 금액 있으면 데이터
            if _looks_like_header_row(cells):
                header_trs.append(tr)
            continue                            # 마커 없는 배너 — 건너뛰고 계속 스캔
        if not _looks_like_header_row(cells):
            break                               # 기존 동작 그대로(TR6류)
        header_trs.append(tr)
```

`<COLGROUP>`이 없는 표는 `n_cols_declared=None` → `is_banner`가 항상 False →
기존 동작 그대로(R6 원칙 — 판정 근거 없으면 확장 안 함).

## 검증

1. **직접 재현**: 수정 전 `parse_header_columns(bs_table)` → `None`. 수정 후 →
   `[주석(is_note), 당기×2(rank0), 전기×2(rank1)]` 정확히 매핑.
2. **실 필링 재적재**: `extract_report_lines()` + `store_report_lines()` +
   `store_report_tables()`를 특수건설 `20151116001903`에 재실행 →
   - 미착품·장기차입부채·장기차입금·저장품평가손실충당금 — 잘못된 당기 행 소멸,
     진짜 결측으로 남음(R3 원칙, 오염보다 결측).
   - 자산총계(148,659,906,395) = 부채총계+자본총계 항등식 그대로 PASS.
   - BS 행수 110→92(오적재 18행 제거), IS 71행 불변.
3. **회귀 테스트** — `fin2/tests/test_header_grid_column_map_r88.py`:
   - `test_headerless_banner_rows_skipped_before_real_header` — 특수건설 구조
     합성 재현, 배너행 건너뛰고 헤더 도달 + 미착품류 당기 결측 확정.
   - `test_headerless_banner_rows_without_colgroup_still_falls_back` —
     `<COLGROUP>` 없으면 확장 비활성.
   - `test_headerless_full_width_blank_section_row_still_stops_scan` — 진짜
     빈 섹션행("자산")은 여전히 스캔 중단(기존 안전장치 유지).
4. **전체 스코프**: `pytest tests/ fin2/tests/` 973 passed(970 대비 +3, 기존
   무관 실패 2건 그대로 — `git checkout HEAD -- parser/xml/table_extractor.py`로
   수정 전 버전에 대조해 이번 변경과 무관함을 직접 확인).

## 후속 — 손익계산서 표는 여전히 안 고쳐짐 (같은 날, 사용자 지적)

수정 직후 사용자가 "손익계산서쪽은 수정이 안되었는데, 대손상각비, 연구개발비
부분 확인해봐"라고 정확히 지적했다. 확인해보니 지적이 맞았다 — 대손상각비/
연구개발비도 원문 당기(제45기) 값이 완전공백이고 전기(제44기)만 있는데 여전히
전기값이 당기로 오적재되고 있었다.

원인: 이 필링의 포괄손익계산서 표는 BS와 달리, 표제목("포괄손익계산서") 바로
다음 줄이 **COLSPAN 병합이 아니라 개별 빈 `<TD>` 5개를 나열한 완전공백행**이었다.

```
TR0 <TD COLSPAN=5>포괄손익계산서</TD>                    ← 배너(1셀<5, is_banner 걸림)
TR1 <TD></TD><TD></TD><TD></TD><TD></TD><TD></TD>       ← 완전공백행(5셀=5, is_banner 안 걸림!)
TR2 <TD COLSPAN=5>제45기2015...부터...까지</TD>          ← 배너
TR3 <TD COLSPAN=5>제44기2014...부터...까지</TD>          ← 배너
TR4 <TD>회사명...</TD>...<TD>(단위:원)</TD>              ← 배너(3셀<5)
TR5 <TD>계정명</TD><TD COLSPAN=2>제45(당)기</TD><TD COLSPAN=2>제44(전)기</TD>  ← 진짜 헤더행
```

TR1은 물리 셀 수(5)가 `<COLGROUP>` 선언 열수(5)와 **같아서** `is_banner` 판정
(물리 셀 < 선언 열수)을 통과하지 못하고, 기존(원 branch) `_looks_like_header_row`
로 떨어진다 — 라벨 뺀 나머지 전부 공란·마커 없음 → False → **TR0(배너, 건너뜀)
다음인 TR1에서 곧바로 멈춘다.** BS의 배너행들은 전부 COLSPAN 병합(물리 셀 <
선언 열수)이라 우연히 안 걸렸을 뿐, 애초에 "물리 셀 수 비교"만으론 이 형태의
완전공백행을 못 잡는 설계였다.

### 2차 수정

배너 판정보다 먼저, **모든 셀(라벨 포함)이 빈 행은 무조건 건너뛴다.** "자산"류
진짜 섹션행은 값이 전부 공란이어도 라벨(`cells[0]`)은 반드시 있으므로 이 규칙과
절대 충돌하지 않는다 — 라벨 유무가 완전히 배타적인 신호이기 때문에 폭 비교 같은
간접 신호보다 오히려 더 안전하다.

```python
for tr in candidate_trs:
    cells = _get_cells(tr)
    if cells and not any(c.strip() for c in cells):
        continue                                # 완전공백행 — 무조건 건너뜀
    is_banner = ...
```

### 검증 (2차)

- `parse_header_columns()`가 IS 표에서 `None`→성공(당기 2열(rank0)+전기 2열
  (rank1))으로 바뀜을 직접 재현.
- 재적재 후 DB: 대손상각비·연구개발비의 잘못된 당기 행 소멸(진짜 결측으로 남음).
  매출액(109,300,142,706)·매출총이익·영업이익 등 당기값이 실제 있는 항목은 불변,
  `is_waterfall`(매출액−매출원가=매출총이익) PASS 유지. IS 71→61행(오적재 10행
  제거).
- 신규 회귀 테스트 `test_headerless_fully_blank_row_skipped_even_at_full_width`
  (IS 구조 합성 재현) 추가.
- `pytest tests/ fin2/tests/` 974 passed(973 대비 +1, 무관 실패 2건 그대로).

### 교훈

"배너/캡션행은 물리 셀이 항상 병합돼 있다"는 첫 가설이 **이 표 하나 안에서도
안 맞는 반례**(완전공백행은 병합 없이 개별 빈 셀로도 나온다)가 바로 있었다.
1차 수정을 "이 필링 BS에서 재현 확인됨"만으로 종료 보고했으면 놓칠 뻔했다 —
같은 필링의 다른 statement(IS)까지 원문으로 재확인하라는 사용자 지시가 실제
잔여 결함을 잡아냈다(메모리 `feedback-verify-against-source`, `feedback-
consider-pipeline`과 같은 맥락 — 표 하나 고쳤다고 그 파서가 다루는 전체 문서
클래스를 다 고쳤다고 가정하면 안 된다).

## 미조치 / 다음 결정 필요

- **전사 census 안 함** — "THEAD 없는 표 중 배너행 때문에 실패하던 비율"을 아직
  세지 않았다. R89와 마찬가지로 `parse_header_columns()`가 이미 모든 BS/IS/CF
  호출 경로에 배선돼 있어 이 확장은 자동으로 전사 적용되지만(추가 배선 불필요),
  **기존에 이미 잘못 적재된 데이터는 소급 재적재해야만 정정된다**.
- 이번 세션엔 특수건설 `20151116001903` 1건만 직접 재적재해 정정 확인. 같은 구조
  (THEAD 없음 + 배너행)의 다른 필링들은 `scripts/reload_report_lines_2015plus_
  2026-09-12.py`(또는 동등 배치)를 다시 돌려야 반영된다 — 범위(2015+ 전체 재실행
  vs 표적 표본)와 시점은 사용자 결정 필요.
