# Gate B 버그① 옵션 A(파서 근본수정) 구현 계획 (2026-08-24)

> 상태(2026-08-24 종료 시점): **설계 확정, 구현 미착수.** Phase 0 실측(§3-1)
> + offset 보정 설계(§3-3)까지 이번 세션에서 끝냈고, 사용자가 "구현은 다음
> 세션에서" 결정 — CLAUDE.md "계획 후 대기" 원칙대로 코드는 건드리지 않았다.
>
> **★다음 세션 시작점(이 순서로)**:
> 1. `fin2/extract/text.py::_interim_cumulative_layout()` 신설(§3-3-1) +
>    `_interim_cumulative_cols()` 하위호환 wrapper로 축소.
> 2. `fin2/audit/face_audit.py::_ni_attribution_text_candidates()` 패치
>    (§3-3-4) — **report_lines.py보다 먼저**(§3-3-5 순서 권고, §3-3-0의
>    "오라클도 같은 버그를 갖고 있었다" 신규 발견 때문). 패치 후 std_v3 대비
>    face_audit 판정이 어떻게 바뀌는지부터 관찰(report_lines.py는 아직
>    안 건드린 상태에서).
> 3. `fin2/extract/report_lines.py::_emit_section_lines()` 패치(§3-3-2).
> 4. §8-a 결정(Track B `text.py::_emit_section()` 동시 패치 여부, §3-3-3
>    스케치 있음) — fact_v2 실사용 여부 먼저 확인 후 진행.
> 5. 단위테스트 + `scripts/census_optionA_cum_map_impact_2026-08-24.py`를 새
>    offset-보정 로직 기준으로 갱신해 재실행(§3-3-5) — "바뀌는 행"에서
>    코리안리류 오탐이 사라졌는지, 원 버그(00104573/00172291류)만 남는지 확인.
> 6. §8-b(백필 스코프)는 5번 재실측 수치로 그때 결정(이번 세션 §3-1 원 수치는
>    주석컬럼 오탐 섞여 과대추정 가능성 있음 — 그대로 쓰지 말 것).
> 7. Gate B 전수 재감사(§6)로 마무리, §8-c(오버레이 존치)는 그 뒤 판단.
>
> 배경: `docs/plans/d_category_col_misselect_ni_label_dup_design_2026-08-23.md`
> §1-8에서 사용자가 **버그①을 옵션 A(파서 근본수정)로 전환 확정**(2026-08-24) —
> tax_expense 전용 오버레이(옵션 B, 이미 구현·커밋 `8322c40`)가 아니라
> `table_extractor.py::extract_rows()`의 근본 원인을 고치는 쪽.
>
> 이하 §0-§9는 이 세션에서 코드를 직접 읽고 실측(census 스크립트, 원문대조)해
> 도달한 최종 설계다 — 중간에 나온 "narrow fix"(§1, §5 Phase 1의 원래 스케치)는
> §3-1에서 반례로 폐기됐고, §3-3이 그걸 대체하는 최종안이니 **구현은 §3-3
> 기준으로 할 것**(§1/§5는 "왜 그게 틀렸는지"의 기록으로만 남겨둠).

## 0. 버그 메커니즘 재확인 (코드 실측)

`parser/xml/table_extractor.py::extract_rows()` L296-310:

```python
# 6-column IS 형식 대응: 앞쪽 구조적 빈 셀(None) 제거
if len(all_parsed) >= 4 and not (preserve_col_positions or keep_all_amount_cells):
    while all_parsed and all_parsed[0] is None:
        all_parsed.pop(0)
        if all_raw:
            all_raw.pop(0)
```

물리 셀이 4개 이상이고 맨 앞이 빈 셀(당기 3개월 disclosure 누락)이면 통째로
당겨진다. 소비 측(`fin2/extract/report_lines.py::_emit_section_lines()` L501-503)은:

```python
if cum_map is not None:
    pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
             if pos < len(row.amounts) and row.amounts[pos] is not None]
```

`cum_map`(헤더 텍스트의 "누적" 토큰 위치 → period_offset, 예 `{1:0, 3:1}`)이
**절대 헤더 위치**로 `row.amounts`를 인덱싱한다 — 배열이 당겨지면 엉뚱한 물리
셀을 "당기"로 방출한다. 00104573(tax_expense)·00172291(controlling_ni) 둘 다
실행 재현으로 이 경로임을 확인 완료(설계문서 §1-1, §1-8).

## 1. ★신규 확인 — 버그는 `cum_map` 경로에만 실존한다 (다른 두 경로는 이미 자체 재압축)

`_emit_section_lines()`의 컬럼 소비 로직은 표 종류별로 3갈래다(L501-516):

| 분기 | 조건 | 로직 |
|---|---|---|
| `cum_map is not None` | interim(H1/Q1/Q3) + 2단 헤더 감지 | `row.amounts[pos]`로 **절대 위치** 인덱싱 — 버그 노출 |
| `multicol` | 보험/증권 다열 포맷 | `present = [a for a in row.amounts if a is not None]` — **자체 재압축** 후 순번 사용 |
| else(기본 FY) | 그 외 전부 | `lead`만큼 선행 None 스킵 후 순번 사용 — **extract_rows의 압축과 사실상 동형** |

즉 `extract_rows()`의 압축을 껐을 때 실제로 결과가 달라지는 건 **`cum_map`
경로뿐**이다. 나머지 두 경로는 이미 자기 앞단에서 독립적으로 압축(또는
등가 압축)을 하므로 `preserve_col_positions` 값과 무관하게 결과가 같다.

**결론 — 옵션 A를 "BS/IS/CF 전체에 preserve_col_positions=True"로 넓게 걸
필요가 없다.** `_emit_section_lines()`가 이미 테이블별로 `cum_map`을 미리
계산해 두므로(L448), `extract_rows()` 호출(L478)에

```python
preserve_col_positions=(cum_map is not None)
```

만 넘기면 된다 — **버그가 실존하는 경로만 정확히 겨냥**하고, 나머지 경로는
물리적으로 건드리지 않는다. 이게 설계문서 §1-4가 우려했던 "다른 소비 로직
회귀" 리스크를 사실상 없앤다(그 경로들은애초에 이 플래그를 보지 않으므로).

## 2. ★신규 확인 — pre-2024 영향 범위는 "ACONTEXT 존재"가 아니라 "헤더에 누적 토큰 존재"로 결정된다

`cum_map`(`fin2/extract/text.py::_interim_cumulative_cols()`)은 **XBRL
ACONTEXT/ACODE와 무관하게 헤더 텍스트("3개월"/"누적" 토큰)만 본다**. 즉
tax_expense 오버레이(옵션 B)가 "ACODE/ACONTEXT 보유율 2024+에 집중"이라는
근거로 `_MIN_FISCAL_YEAR=2024`로 스코프를 좁혔던 논리가 **옵션 A(근본수정)
에는 그대로 적용되지 않는다** — 2단 헤더([3개월|누적]) 표기 관행은 XBRL
도입과 무관하게 그 이전 필링에도 존재할 수 있다. 설계문서 §1-4가 "pre-2024
영향 범위를 실측으로 먼저 가늠"하라고 지시한 이유가 바로 이것이며, **실측
없이 연도로 스코프를 미리 좁히면 안 된다**.

## 3. ★신규 확인 — 동일 결함의 미러 사본이 `text.py::_emit_section()`(Track B/fact_v2)에도 있다

`fin2/extract/text.py`(L879-907)는 `report_lines.py::_emit_section_lines()`와
**독립적으로 같은 패턴**을 갖고 있다:

```python
cum_maps = {id(t): (_interim_cumulative_cols(t) if interim_flow else None) for t in tables}
...
for row in extract_rows(table, multiplier=unit, num_cols=n_cols, direct_only=True):
```

`preserve_col_positions`를 넘기지 않아(기본 False) **같은 버그가 Track B/
fact_v2 경로에도 잠재**한다. 설계문서는 이 파일을 "이 버그의 production 경로가
아니다"(report_lines 기준)라고만 언급했지, Track B 자체가 버그로부터
자유롭다고 확인한 적은 없다 — 실제로 자유롭지 않다. 참고로 `fin2/audit/
face_audit.py`(L496, R36 controlling_ni 체커)도 `_interim_cumulative_cols()`를
쓰지만 **`extract_rows()`를 거치지 않고 원본 `td` 셀을 물리 인덱스로 직접
읽는다** — 그래서 이번 버그의 영향을 받지 않고, 되레 그 덕에 face_audit가
tax_expense/controlling_ni 오류를 정확히 잡아낼 수 있었다(오라클로서 신뢰
가능, §6 검증 전략의 근거).

## 3-1. ★Phase 0 실측 결과(2026-08-24) — 좁은 1줄 수정안이 틀렸음을 발견

`scripts/census_optionA_cum_map_impact_2026-08-24.py`로 전 연도 무작위 300건
표본(interim IS/CF, cum_map 있는 표만) 실측:

| 지표 | 값 |
|---|---|
| 표본 필링 | 300 (parse err 6) |
| cum_map 표 | 451 |
| 검사 행 | 10,552 |
| `preserve_col_positions` 전환 시 값이 바뀌는 행 | 365 (3.46%) |

**연도별 분포가 §2의 우려를 실측으로 확인**했다 — 2024+ 에 몰려있지 않고
2010~2025 전 구간에 걸쳐 있다(예: 2014년 48건, 2015년 59건, 2020년 34건
변경, "2024+ 전용" 가정은 성립 안 함).

**★더 중요한 발견 — §1의 "narrow 1-line fix" 자체가 틀렸다.** 예시 중
`20211115001569`(코리안리, 2021Q3)의 "Ⅲ. 영업이익" 행을 원문(EUC-KR) 직접
대조한 결과:

```
실제 TD 5개(라벨 뒤): [빈칸(주석번호 컬럼, 이 행은 주석 없음), 75,554,744,332,
                        233,077,128,503, 23,656,776,596, 178,231,861,553]
```

이 표는 라벨과 값 컬럼 사이에 **"주석" 컬럼이 항상 존재**한다(다른 행엔 "1)" 같은
주석번호가 들어있고, 이 행은 그게 비어 있을 뿐). 현재(preserve=False) 로직은
이 빈 주석칸을 압축으로 제거해 **우연히 정답**을 낸다(4값이 정확히 cum_map
위치에 맞음). 그런데 좁은 수정안(`preserve_col_positions=(cum_map is not
None)`)을 적용하면 이 행에도 압축이 꺼져 **주석 빈칸이 진짜 값 컬럼인 것처럼
cum_map 위치를 한 칸씩 밀어 읽는다** — 실측 예시:
```
preserve=False(현재, 이 행은 정답) : [75554744332, 233077128503, 23656776596, 178231861553]
preserve=True(좁은 수정안, 이 행은 오답): [None, 75554744332, 233077128503, 23656776596]
```
즉 **한 칸 밀림 버그를 고치려던 수정이, 주석컬럼이 있는 표에서는 거꾸로 새
한 칸 밀림 버그를 만든다.** `extract_rows()`의 "선행 None 개수" 만으로는
"주석컬럼이라 항상 비거나 채워지는 구조적 1칸"과 "당기3개월 disclosure가
없어서 빈 것"을 구분할 수 없다 — 둘 다 증상(선행 None)은 같지만 정답은
정반대(전자는 반드시 제거, 후자는 반드시 보존)다.

**근본 원인 재정정**: `_interim_cumulative_cols()`(`fin2/extract/text.py`
L90-116) 자신은 이미 이 구분을 안다 — 헤더 행에서 "3개월/누적" 토큰이 나올
때까지 앞쪽 셀(라벨+주석 헤더 등)을 스킵한 뒤(`sub` 변수) 그 **상대 위치**로
`cum_map`을 만든다. 즉 헤더 쪽엔 이미 "값 컬럼 앞에 구조적으로 몇 칸이 있는지"
(offset)라는 정보가 존재하는데, **그 offset을 버리고 cum_map(상대위치)만
반환**한다. 소비 측(`_emit_section_lines()`)은 이 상대위치를 데이터 행의
`row.amounts`(라벨만 뗀 배열, 주석컬럼 포함)에 **오프셋 보정 없이** 그대로
인덱싱한다 — `_grid_header_split`가 note/SCE에서 이미 쓰는 "offset"(T1.3)
개념이 본문 interim 표 쪽에는 이식이 안 돼 있었던 것.

## 3-2. 수정 방향 재설계 (구현 착수 전 재검토 필요 — 아직 미착수)

옵션 A의 올바른 형태는 "`preserve_col_positions` 불린 하나 넘기기"가 아니라:

1. `_interim_cumulative_cols()`가 **offset도 같이 반환**하도록 확장(반환형
   변경 — `fin2/extract/text.py`·`fin2/extract/report_lines.py`·
   `fin2/audit/face_audit.py` **3곳이 이 함수를 쓰므로 시그니처 변경의 영향
   범위를 모두 확인**해야 함, 하위호환 유지 또는 3곳 동시 수정 필요).
2. `extract_rows()`는 `preserve_col_positions=True`(압축 완전 정지, 주석칸도
   보존)로 호출해 raw 배열을 그대로 받는다.
3. 소비 측은 `row.amounts[offset + pos]`처럼 offset을 더해 cum_map 위치를
   보정해서 읽는다 — 이러면 "주석컬럼은 항상 정확히 offset만큼 무조건 스킵
   (내용 무관)" + "값 컬럼 구간 내부의 빈칸(진짜 미공시)은 보존"이 동시에
   성립한다.
4. `text.py::_emit_section()`(Track B)·`face_audit.py`(R36 controlling_ni
   체커)도 같은 offset 보정이 필요한지 각각 재확인(§8-a 결정에 영향 — 세
   호출부가 offset을 이미 다른 방식으로 우회하고 있을 수도 있음, 특히
   face_audit는 `extract_rows()`를 안 거치고 `td` 물리 인덱스를 직접
   쓰므로 애초에 다른 메커니즘 — 재확인 필요).

**결론: §5(구현 스텝)의 "Phase 1 코드 수정" 1줄 스케치는 이 발견으로
무효화됐다 — 그대로 구현하면 안 된다.** 다음 세션은 위 3-2 설계를 코드로
확정하고, **주석컬럼이 있는 표와 없는 표 양쪽을 포함한 재표본**으로 §3-1
census 스크립트를 다시 돌려 새 설계가 두 케이스 모두 correct한지 재검증하는
것부터 시작한다(원문 대조 포함, R9).

## 3-3. ★offset 보정 확정 설계 (2026-08-24 — 코드 3곳 재확인 완료, 아직 미구현)

### 3-3-0. §3-2 항목 4 정정 — face_audit도 면역이 아니다

§3에서 "face_audit는 `extract_rows()`를 안 거쳐 이 버그의 영향을 안 받는다"고
썼던 건 **압축(pop-loop) 메커니즘 한정으로만 맞고, offset 정렬 문제 자체에는
틀렸다.** `fin2/audit/face_audit.py::_ni_attribution_text_candidates()`
(L526-560, TD 기반 서브루틴 — TE 기반 자매함수 `_ni_attribution_structural_
candidates()`는 ACONTEXT 구조매칭이라 애초에 무관, cum_map을 쓰지 않음)도
`value_tds = tds[1:]`(라벨만 뗀 raw 물리 셀)에 `cum_map.get(idx)`를 **offset
보정 없이** 그대로 인덱싱한다(L510-516) — 코리안리 예시로 계산해보면 이 함수도
"당기누적" 대신 "당기3개월"을 채택하는 **동일한 오정렬**을 갖고 있다(실측
안 함 — 코드 추적으로 확정, 다음 단계에서 원문/실행 재현 필요). 즉 **R36
controlling_ni 체커 자체가 주석컬럼 있는 표에서 이미 부정확할 수 있다** —
face_audit를 "오라클"로 못 믿는 케이스가 하나 늘었다. 3-3-3에서 이것도 같이
고친다(같은 수정, 같은 세션 스코프 — 굳이 나중으로 미룰 이유가 없다, §8-a는
이제 "할지 말지"가 아니라 "언제 하냐"의 문제로 좁아짐).

### 3-3-1. 공용 함수 확장 — `fin2/extract/text.py::_interim_cumulative_cols()`

헤더 파싱 루프가 이미 "3개월/누적 토큰이 나올 때까지 몇 칸을 건너뛰었는지"를
세고 있다(`while` 루프) — 그 카운트만 같이 반환하면 된다. **하위호환**을 위해
기존 함수는 얇은 wrapper로 남긴다(다른 곳에서 이 이름으로 부르는 코드/테스트가
있을 수 있어 시그니처를 안 바꾸는 쪽이 안전 — 사용처는 3곳뿐임을 이미
확인했지만, 반환 **타입**을 바꾸면 그 3곳을 전부 원자적으로 고쳐야 해서 리스크가
커진다):

```python
def _interim_cumulative_layout(table) -> tuple[int, dict[int, int]] | None:
    """`_interim_cumulative_cols()`와 같은 판정 + **offset**(값 컬럼 앞의 구조적
    비기간 컬럼 수 — 예: '주석' 컬럼)을 함께 반환한다.

    offset 이 필요한 이유(2026-08-24, 코리안리 20211115001569 원문대조로 확정):
    많은 IS/CF 표가 라벨과 기간 컬럼 사이에 '주석' 컬럼을 구조적으로 갖는다(다른
    행엔 "1)" 같은 주석번호, 이 행은 그게 비어 있을 뿐). 그 빈 칸은 amount_cells
    에서 앞쪽 None 으로 나타나 "당기3개월 disclosure 없음"(진짜 버그, R9 확정)과
    **증상이 똑같은데 정답 처리는 정반대**(전자는 항상 스킵, 후자는 보존)다.
    `sub` 를 앞에서 자르는 이 루프가 이미 "몇 칸을 잘랐는지"를 알고 있으므로
    (그 칸들이 정확히 '라벨 자신 + 주석 등 비기간 헤더') 그 카운트를 그대로
    쓴다 — 데이터 행 쪽(`amount_cells`/`row.amounts`)은 라벨 1칸만 뗀 상태이므로
    `offset = popped - 1`(라벨 몫 1을 뺀다)이 데이터 행 배열에서 건너뛸 칸 수다.
    """
    from parser.xml.table_extractor import _get_cells
    for tr in table.findall(".//TR"):
        cells = _get_cells(tr)
        joined = "".join(cells)
        if not _CUM_RE.search(joined) or not _THREE_M_RE.search(joined):
            continue
        sub = list(cells)
        popped = 0
        while sub and not (_CUM_RE.search(sub[0]) or _THREE_M_RE.search(sub[0])):
            sub.pop(0)
            popped += 1
        cum = [i for i, c in enumerate(sub) if _CUM_RE.search(c)]
        if not cum:
            continue
        offset = max(popped - 1, 0)
        return offset, {pos: off for off, pos in enumerate(cum)}
    return None


def _interim_cumulative_cols(table) -> dict[int, int] | None:
    """Back-compat wrapper — cum_map만 필요한 기존 호출부용. 새 호출부는
    `_interim_cumulative_layout()`을 직접 써서 offset도 받을 것(row.amounts를
    이 위치로 인덱싱할 계획이면 offset 없이는 부정확 — 위 docstring 참고)."""
    layout = _interim_cumulative_layout(table)
    return layout[1] if layout else None
```

### 3-3-2. `fin2/extract/report_lines.py::_emit_section_lines()` 패치 설계

- L443: `cum_maps = {id(t): (_interim_cumulative_cols(t) if interim_flow else None) for t in tables}`
  → `cum_layouts = {id(t): (_interim_cumulative_layout(t) if interim_flow else None) for t in tables}`
  (`has_2tier` 계산(L444)은 `cum_layouts.values()`로 그대로 유지, `v is not None`
  판정은 동일하게 동작한다.)
- L448 `cum_map = cum_maps[id(table)]` →
  ```python
  layout = cum_layouts[id(table)]
  col_offset, cum_map = layout if layout else (0, None)
  ```
- L475 `n_cols = max(cum_map) + 1 if cum_map else (8 if multicol else 3)` →
  `n_cols = col_offset + max(cum_map) + 1 if cum_map else (8 if multicol else 3)`
  (기존엔 `max(cum_map)+1`이 물리 배열 폭까지 자른다고 잘못 가정했다 — §3-1의
  코리안리 사례가 실제 물리 폭 = offset + 기간컬럼수 임을 보여줬다.)
- L478 `extract_rows(..., direct_only=True, skip_junk=False)` →
  `extract_rows(..., direct_only=True, skip_junk=False,
  preserve_col_positions=(cum_map is not None))`
- L501-503:
  ```python
  if cum_map is not None:
      pairs = [(off, row.amounts[col_offset + pos]) for pos, off in cum_map.items()
               if col_offset + pos < len(row.amounts)
               and row.amounts[col_offset + pos] is not None]
  ```
  (그 아래 "폴백: pairs 비면 present 순서대로" L504-506은 무변경 — 누적컬럼
  자체가 없는 총계/귀속 요약행 폴백이라 이번 버그와 무관.)

### 3-3-3. `fin2/extract/text.py::_emit_section()` 패치 설계 (Track B, §8-a 스코프)

동일 패턴 — L879 `cum_maps = {...: _interim_cumulative_cols(t) ...}` →
`_interim_cumulative_layout`로 교체, L907 `extract_rows(...)` 호출에
`preserve_col_positions=(cum_map is not None)` 추가, L931-933의
`row.amounts[pos]` → `row.amounts[col_offset + pos]`로 교체. `else`(L940-947,
lead-strip 폴백) 분기는 report_lines.py와 마찬가지로 무변경.

### 3-3-4. `fin2/audit/face_audit.py::_ni_attribution_text_candidates()` 패치 설계

L496 `cum_map = _interim_cumulative_cols(tbl)` → `_interim_cumulative_layout`
로 교체해 `col_offset, cum_map` 획득. L510-516의 `for idx, td in
enumerate(tds): if cum_map is not None: if cum_map.get(idx) != 0: continue` →
`if cum_map.get(idx - col_offset) != 0: continue`(음수 idx는 자동으로
`.get()`이 None을 줘 스킵되므로 별도 가드 불요). **이 함수는 face_audit의
"오라클" 역할이라 report_lines.py보다 먼저(또는 같이) 고쳐야** 재감사 시
비교 기준 자체가 흔들리지 않는다 — §6 검증 순서에 반영.

### 3-3-5. 재검증 계획 (구현 후, §6 Gate B 재감사 이전 필수 게이트)

1. `fin2/tests/test_text.py`(offset 있는/없는 헤더 fixture 2종)에
   `_interim_cumulative_layout()` 단위테스트 추가 — 코리안리류(offset=1)와
   00104573/00172291류(offset=0, 주석컬럼 없는 표) 둘 다 포함.
2. §3-1 census 스크립트(`scripts/census_optionA_cum_map_impact_2026-08-24.py`)
   를 새 로직(offset 보정 포함) 기준으로 재실행하도록 갱신 — "바뀌는 행"이
   이제 진짜 버그(원래 00104573/00172291류)만 남고 코리안리류 오탐이 사라졌는지
   재확인. 표본에 코리안리류(주석컬럼 있는 IS/CF)가 반드시 섞이도록 시드 조정
   또는 별도 표적 표본 추가.
3. 원문 대조(R9) — 코리안리류 3~5건 + 00104573/00172291 두 확정 사례를 새
   로직으로 재실행해 값 일치 확인.
4. face_audit 오라클 자체가 바뀌므로(3-3-4), report_lines.py 수정 전/후
   face_audit 판정이 어떻게 바뀌는지 **분리해서** 봐야 한다 — 둘을 동시에
   배포하면 "report_lines가 고쳐져서 pass"인지 "face_audit도 같이 고쳐져서
   우연히 맞아떨어진 pass"인지 구분이 안 된다. 권고: face_audit 수정을 먼저
   커밋·검증(기존 std_v3 대비 판정 변화 관찰) → report_lines.py 수정을 그
   다음에 별도로 검증.

## 3-4. ★★구현 착수 중 §3-3 offset 설계 자체가 틀렸음을 발견(2026-08-24, 코드 되돌림) — 재설계 필요

**상태: §3-3-1~3-3-4 코드를 실제로 작성해 3파일(`text.py`/`report_lines.py`/
`face_audit.py`) 모두 패치했다가, §3-3-5 재검증(census 스크립트 갱신 후 재실행)
중 §3-3의 핵심 전제 두 가지가 실측으로 반증돼 **전부 `git checkout`으로
되돌렸다**(코드는 현재 이 세션 시작 전 상태 그대로, 손상 없음).** 아래는 그
과정에서 나온 실측 근거와 재설계 방향.

### 3-4-1. 전제 A 반증 — offset을 "3개월/누적 토큰이 있는 헤더 행 자체"에서
셀 수를 세어 구하는 방법(§3-3-1 `_interim_cumulative_layout()`)은 실제 원문
헤더가 **2행으로 쪼개져 있으면 항상 0을 반환한다**

코리안리(`20211115001569`) IS_C 표 원문 헤더 TR을 직접 대조(`_get_cells`):
```
TR0: ['과목', '주석', '제 60기 3분기', '제 59기 3분기']   # 과목·주석 셀은 ROWSPAN=2
TR1: ['3개월', '누적', '3개월', '누적']                    # 과목·주석 칸이 물리적으로 없음
```
`_interim_cumulative_layout()`은 "CUM_RE와 THREE_M_RE가 **같은 행**에 함께
있는 행"을 찾는데, 그 행은 TR1이다 — TR0(과목·주석·기수)는 "3분기"만 있고
"3개월"이 없어 안 걸린다. TR1은 과목/주석 칸이 ROWSPAN으로 TR0에 이미
붙박여 있어 **물리적으로 존재하지 않는다** → `sub[0]`이 이미 `'3개월'`이라
`popped=0` → `offset=0`. **300건 재표본(census, offset-aware 버전)에서
`by_offset: {0: 449}` — 표본 전체 449개 cum_map 표가 예외 없이 0으로
나왔다.** 코리안리 자신도 포함해서. 즉 §3-3-1 함수는 "주석 컬럼이 있는
표"를 사실상 **한 건도** 옳게 감지하지 못한다 — 설계문서 §3-1이 발견을
촉발한 바로 그 반례에서조차.

### 3-4-2. 전제 B 반증(더 근본적) — offset은애초에 "표당 상수"가 아니다,
**행마다 다르다** (원인: `_split_label_amounts()`의 기존 R19 주석컬럼
로직이 **콤마 있는 주석은 이미 제거하지만 빈 주석칸은 제거 안 함**)

실제 `extract_rows(preserve_col_positions=True)` 결과를 같은 표에서 두 행
비교:
```
'1. 보험료수익'  (주석칸 내용 '18,26', 비어있지 않음)
  → amounts = [2222255962433, 6493671614930, 2094261488357, 6339754913624, None, None]
  → 선행 None 없음(offset 0 이 이미 맞음)

'Ⅰ. 영업수익'    (주석칸이 비어있음 — 이 행은 주석 없음)
  → amounts = [None, 2804628178529, 8169287451940, 2647136207806, 8302819414243, None]
  → 선행 None 1개(offset 1 이 필요)
```
같은 표, 같은 컬럼 구조인데 **필요한 offset이 행마다 0과 1로 갈린다.** 원인은
`parser/xml/table_extractor.py::_split_label_amounts()`(R19, 기존 코드
불변)가 i==1 칸을 주석으로 보고 건너뛰는 조건이
`_NOTE_REF_PATTERN.match(cell_nospace)`(콤마 다중참조 또는 `table_has_note_
column`이면 콤마없는 단일숫자까지)인데, **빈 문자열은 이 패턴에 안 걸려서
주석으로 인식되지 않고 그대로 amount_cells 의 첫 칸(빈칸→None)으로 들어간다.**
즉 이 함수가 "주석 있는 행"은 이미 올바르게 떼어내고, "주석 없는(빈칸) 행"만
못 떼어내— **결과 폭이 행마다 들쭉날쭉**하다. 이 상태에서 소비 측
(`report_lines.py`/`text.py`)이 "표 하나에 offset 하나"를 곱하면, 이미
정상인 행("보험료수익"류)을 오히려 한 칸 밀어서 새로 깨뜨린다.

(참고 — `face_audit.py`는 `extract_rows()`/`_split_label_amounts()`를 안 거치고
원문 `<TD>` 를 직접 읽으므로 이 R19 로직의 영향을 안 받는다 — 물리 TD 개수는
행마다 균일(주석 칸이 비어 있어도 TD 자체는 항상 존재)하므로 face_audit
한정으로는 "표당 상수 offset"이 실제로 유효하다. 문제는 **그 offset 값을
구하는 방법**(3-4-1의 두-행 헤더 문제)이지, "상수인가 아닌가"가 아니다 —
face_audit는 3-4-1만 고치면 되고, report_lines.py/text.py는 3-4-1+3-4-2
둘 다 고쳐야 한다.)

### 3-4-3. 재설계 방향(구현 미착수 — 다음 세션/사용자 결정 대기)

진짜 근본 원인은 **`_interim_cumulative_cols`/`_interim_cumulative_layout`이
아니라 `_split_label_amounts()`의 주석컬럼 인식이 "내용이 있을 때만" 작동하고
"구조적으로 있지만 이번 행엔 빈칸"을 못 알아본다는 것**이다. 제안:

1. `_split_label_amounts()`에서 `table_has_note_column=True`인 표는 i==1
   칸을 **내용이 뭐든(빈칸이든 주석번호든) 항상** 주석 칸으로 소비한다
   (현재는 `_NOTE_REF_PATTERN`에 매치될 때만). 이러면 이 함수를 통과한
   `amount_cells`가 표 전체에서 폭이 균일해지고, **report_lines.py/text.py
   쪽은 offset 보정이 아예 필요 없어진다**(cum_map을 offset 없이 그대로
   써도 맞음 — `preserve_col_positions=True`만 추가하면 §1의 원래 1줄
   스케치로 충분해짐). 이 부분이 맞다면 §3-3 전체(offset 반환/전파)가
   불필요해지고 구현 범위가 오히려 **줄어든다.**
   - 리스크: `_split_label_amounts`는 BS/IS/CF 전체(interim 여부 무관)가
     공유하는 매우 광범위한 함수(R15~R22 등 여러 과거 수정의 현장) — 여기를
     건드리면 이번 버그와 무관한 표까지 영향권에 들 수 있다. **전수
     영향범위 재실측(census류) 필수**, 손대기 전 반례(빈칸 주석 있는 표가
     사실 진짜 소액금액인 경우가 있는지) 먼저 확인해야 함.
2. `face_audit.py`는 여전히 표당 상수 offset이 유효하므로 §3-3-4 방향은
   유지하되, offset 값 계산은 3-4-1 문제를 피해야 한다 — 후보: (a) 헤더
   TR을 역순으로도 스캔해 "3개월/누적 없는 직전 헤더 행"의 셀 수를 같이
   보거나, (b) `_table_has_comma_note_column`(기존 R19 헬퍼, table_extractor.py)
   를 재사용해 "이 표가 주석컬럼을 갖는지"만 판정하고 offset=1/0으로 단순화.
   (b) 가 더 안전(기존 검증된 판정 재사용).
3. 두 트랙(1, 2)을 분리 구현·분리 검증할 수 있다 — face_audit(2)가 report_
   lines/text(1)보다 범위가 작고 리스크가 낮으므로 먼저 착수 가능.

**이번 세션 코드 변경분은 전부 `git checkout`으로 원복 완료. 신규
재설계는 사용자 검토 후 다음 단계 진행.**

## 3-5. ★★★최종 구현 완료(2026-08-24 밤) — §3-4-3 재설계안 실측·검증·구현·커밋 대기

§3-4의 실패를 딛고 재설계한 방향(§3-4-3 ①)을 실측(census/probe 스크립트 3종
신설)으로 먼저 검증한 뒤 구현했다. **핵심 통찰**: offset은 소비 측(cum_map)이
아니라 **생산 측**(`_split_label_amounts()`)의 결함이었다 — 그 함수가 콤마 있는
주석("18,26")은 이미 올바르게 떼어내면서 **빈 주석칸**만 못 떼어내(빈 문자열은
`_NOTE_REF_PATTERN`에 안 걸림) 표 안에서 행마다 폭이 들쭉날쭉해졌다. 이걸
생산 측에서 고치면 소비 측(cum_map)은 offset 없이 원래(§1) 1줄 스케치
그대로 정확해진다 — §3-3~3-4의 offset 전파 설계 전체가 불필요해졌다.

**실측(구현 전, 몽키패치로 실제 함수 나란히 비교)**:
- `scripts/probe_split_label_amounts_empty_note_2026-08-24.py`(600건): 빈
  주석칸 수정이 영향을 주는 표는 `table_has_note_column=True`인 표뿐(전체의
  일부, 33/시행)이고, 그 변경분 중 "진짜 위험한" cum_map(절대위치 인덱싱)
  경로는 138/506건뿐 — 나머지(368건)는 BS 또는 IS/CF 의 multicol·lead-strip
  경로라 **이미 자체 재압축이라 무해**함을 확인(이 두 경로가 "안전"한 이유는
  코드로 별도 증명: lead-strip 은 선행 None 전부를 스킵하므로 정확히 1개
  추가로 스치는 것과 결과가 같다).
- `scripts/census_optionA_final_design_2026-08-24.py`(300건): 코리안리류
  주석컬럼 표(`has_note_column: 5/444`)는 **바뀌는 행 0건**(이미 정답이던
  값이 그대로 유지) — §3-4가 반증했던 "우연정답 재파괴" 문제가 사라짐.
  바뀌는 행(294건, 2.824%)은 전부 `has_note_col=False`(진짜 당기3개월
  미공시) 케이스로, 원 버그의 타겟 그대로.
- 코리안리(`20211115001569`)·국일제지(`00104573`, `20251113000801`) 직접
  대조: 몽키패치 조합(①+②)이 각각 기존 정답(199,537,863,402 / 171,530,344,675)
  과 2026-08-23 세션에서 DB로 확정한 정답(tax_expense=-2,310,052,284)을
  **독립 재현**함을 확인 — 후자는 그날 옵션 B(오버레이)로 고쳤던 값을 이번엔
  근본수정 경로로 별도 검증한 것이라 교차검증 의미가 크다.

**구현(4파일)**:
1. `parser/xml/table_extractor.py::_split_label_amounts()` — `table_has_
   note_column=True`인 표에서 i==1 칸이 **빈칸**이면(내용 무관, 콤마/단일숫자
   판정과 별개 분기) 항상 주석 칸으로 소비하도록 조건 추가. 유일한 실질 변경.
2. `fin2/extract/report_lines.py::_emit_section_lines()` — `extract_rows()`
   호출에 `preserve_col_positions=(cum_map is not None)` 추가(offset 없음,
   §1 원안 그대로). `n_cols`/cum_map 인덱싱 로직은 무변경.
3. `fin2/extract/text.py::_emit_section()`(Track B) — 동일하게
   `preserve_col_positions=(cum_map is not None)` 추가(§8-a: fact_v2가
   `run.py`/`cf_da.py`에서 실제로 쓰이는 폴백 경로임을 재확인 후 결정).
4. `fin2/audit/face_audit.py::_ni_attribution_text_candidates()` — 이 함수만
   `extract_rows()`/`_split_label_amounts()`를 안 거치고 raw `<TD>`를 직접
   읽으므로 ①의 수정 혜택을 못 받는다. `_table_has_comma_note_column()`(R19
   헬퍼, 같은 신호 재사용)로 **표당 상수** offset(1 또는 0)을 구해
   `cum_map.get(idx - note_col_offset)`로 보정 — 이 함수는 raw TD를 그대로
   읽어 표 전체에서 물리 폭이 균일하므로(report_lines.py 쪽과 달리
   `_split_label_amounts`의 행별 비대칭 소비를 거치지 않음) 표당 상수
   offset이 여기서는 실제로 안전하다(§3-4가 report_lines.py에서 반증한
   것과 안전조건이 다름 — 코드 주석에 근거 명시).

**테스트**: 신규 5건 — `test_section_p_header.py::test_note_ref_guard_empty_
note_cell_also_consumed`(①단위), `test_report_lines.py::test_korianre_note_
column_table_still_correct_after_rootfix` + `test_gukil_paper_no_note_
column_table_corrected_by_rootfix`(②③ 실측파일 end-to-end),
`test_ni_attribution_text_fallback.py::test_text_fallback_note_column_
offset_corrected`(④합성 XML). 기존 2건 갱신 —
`test_report_lines_inline_xbrl_overlay.py::test_00104573_tax_expense_col_
misselect_corrected`(오버레이가 이제 no-op임을 확인하도록 반전, §5
Phase1-3 예고대로), `test_hyphen_negative_gate_r31.py::test_cum_map_
misalignment_fixed_by_gate_widening`("before" 몽키패치 재현값이 이 세션의
①로 인해 달라진 것 반영 — "after"=진짜 회귀가드는 무변화). `fin2/tests
tests/` 전체 607 passed / 1 failed(`test_lxintl_facility_table_dropped`
— 이 세션 변경 전부터 있던 무관 기존 실패, `git stash`로 원복 후 동일 실패
재현해 확인).

**추가 검증**: 실 프로덕션(`extract_report_lines()`, 몽키패치 없음) 250건
스모크런 — 예외 0건, 143,657행 정상 추출.

**남은 절차**(§6/§7 그대로, 이번 세션 범위 밖):
- 커밋 전 사용자 검토 대기(이 문서 갱신 + 코드 diff).
- §3-3-5/§5 Phase2 스코프를 넘는 회귀 스캔은 이미 완료(위 실측). Gate B
  전수 재감사(§6)·소급 백필(§7)은 커밋 후 별도 세션.
- `overlay_tax_expense_value()`(옵션 B) 존치 여부(§8-c) — 이번 실측으로
  "근본수정 후 no-op" 확인까지 끝났으니 존치 결정 그대로 유효.

## 3-6. Gate B 전수 재감사 완료(2026-08-25) — fail_a 회귀 0건, NH투자증권 fail_b 원인미확정

커밋(`d96d78d` 근본수정 4파일 + 소급백필 스크립트 2건) 이후 사용자가 실제로
①스냅샷(`face_audit_snap_20260824`) ②`find_optionA_affected_filings_2026-08-24.py`
8-way 스캔(122,949건 중 30,432건 affected) ③`load_report_lines.py --rcept-file`
④`build_std_v3.py --all --shard`(4-way) ⑤`run_gateb_audit_parallel.sh` 전수 재감사
까지 전부 실행 완료. `verify_gateb_reaudit_transition_optionA_2026-08-24.py` 결과:

- **★차단등급 전이(pass/fail_b → fail_a): 0건** — §6 핵심 게이트 통과.
- `fail_a → pass/fail_b` 개선 8건(revenue 4, tax_expense 3, cogs 2, gross_profit 2,
  controlling_ni 2).
- `pass/pending → fail_b` 77건 중 **75건이 NH투자증권(00120182) 하나의
  controlling_ni**(여러 FY/H1/Q1/Q3 기간)에 집중 — 원문대조로 std_v3(db_won)는
  "지배주주지분순이익" 행과 정확히 일치(정답)인데 face_audit 재추출값(report_won)
  은 "지배주주지분포괄이익"(총포괄이익 귀속, 다른 개념) 행과 일치 — 오염 의심.
  이 FY 표는 `table_has_note_column=False`라 이번 수정한 `note_col_offset` 로직
  자체는 no-op임을 직접 실행으로 확인 — `_ni_attribution_text_candidates()`
  단독 호출로도 재현 안 돼 이번 근본수정이 직접원인인지 불확실. 상세는 메모리
  [[gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25]]
  — **다음 세션 과제**(`read_report_face_xbrl()` 전체 경로 트레이스 필요).

## 4. 수정 범위 결정 — 좁은 근본수정 채택, 그리드 재작성은 기각

> ⚠ **§3-1/3-2로 갱신됨**: "좁은 근본수정"의 정확한 형태가 아래 최초 스케치
> (`preserve_col_positions` 불린 하나)에서 "offset 보정까지 포함한 근본수정"
> (§3-2)으로 바뀌었다 — 단, **note/SCE급 전면 grid_col 재작성까지는 여전히
> 불필요**하다는 이 절의 결론 자체는 유지된다(offset 하나만 추가로 알면
> 되는 문제였지, 표 전체를 grid로 다시 읽어야 하는 문제는 아니었다). 아래
> 원 텍스트는 그 판단 근거로 남겨둔다.

`_emit_note_lines`/`_emit_sce_lines`(R11, 2026-08-07/08)는 이미 더 정교한
grid_col 기반 추출(`_grid_body_rows`/`_grid_header_split`)로 전환해
`preserve_col_positions` 근사 자체를 없앴다("필터링된 위치가 아니라 진짜
그리드 열을 쓰므로 이 인자가 필요 없어졌다", `report_lines.py:1013`). 이걸
BS/IS/CF 본문에도 이식하는 게 이론적으로 더 근본적이지만:

- 본문 컬럼은 "기간"이라는 의미축이 있어(note/SCE처럼 순수 위치 나열이
  아님) `cum_map`이라는 별도 의미 매핑이 이미 필요 — grid 전환이 이 매핑
  로직을 대체하지 않고 그 위에 얹혀야 해서 이식 범위가 note/SCE보다 크다.
- §1에서 확인했듯 **버그는 `cum_map` 경로 하나뿐**이라 grid 전면 재작성의
  이득이 크지 않다(위험 대비 수익이 낮음).

**권고: 그리드 재작성은 하지 않는다.** §1의 좁은 플래그 전달(1줄 수정)로
버그를 정확히 겨냥하고, 그리드 이식은 별도 트랙(필요시)으로 미룬다.

## 5. 구현 스텝

### Phase 0 — 영향 범위 실측 (구현 전 필수 게이트, §2 근거)

1. 신규 스크립트(`scripts/probe_optionA_cum_map_scope_2026-08-24.py`류)로
   **전 연도**(fy 제한 없음) 대상: `interim_flow`(IS/CF, H1/Q1/Q3) 표 중
   `cum_map is not None`인 표를 표집 → 그 안에서 실제로 `len(all_parsed)>=4`
   이고 선행 None이 있는(=압축이 실제로 발동하는) 행이 몇 건/몇 개사/어느
   연도 분포인지 카운트. (전수 스캔이 아니라 표본 재추출 diff — 설계문서
   §1-4 지시 그대로.)
2. 연도별 분포를 봐서 pre-2024 비중이 유의미하면 §7의 백필 스코프를 그에
   맞춰 재산정(사용자 결정, §7).
3. 이 표본에서 `preserve_col_positions=True`로 바꿨을 때 나오는 새 값을
   원문(콤마 포맷 grep) 또는 XBRL 사실과 대조해 "고쳐지는 게 맞는지" 재확인
   (R9 원칙, 지레짐작 금지).

### Phase 1 — 코드 수정

> ⚠ **아래 1번 스케치는 §3-1 실측으로 무효화됐다(주석컬럼 있는 표를
> 오히려 깨뜨림) — 그대로 구현하지 말 것.** §3-2의 offset 보정 설계로
> 대체해야 한다. 이 절은 "무엇이 틀렸었는지"의 기록으로 남겨둔다.

1. ~~`fin2/extract/report_lines.py::_emit_section_lines()` L478~~(§3-1로 폐기):
   ```python
   table_rows = list(extract_rows(table, multiplier=unit, num_cols=n_cols,
                                   direct_only=True, skip_junk=False,
                                   preserve_col_positions=(cum_map is not None)))
   ```
2. **사용자 결정 필요(§8-a)**: `fin2/extract/text.py::_emit_section()`
   L907도 동형으로 미러 수정할지. 권고는 "한다"(같은 1줄급 변경, Track B/
   fact_v2와의 드리프트를 막음) — 단 fact_v2가 실제로 아직 쓰이는 소비처인지
   먼저 확인(안 쓰이면 굳이 손댈 필요 없음, 범위 최소화 원칙).
3. `overlay_tax_expense_value()`(§1-5 옵션 B, `report_lines_inline_xbrl_
   overlay.py`)와의 상호작용 — 근본수정 후엔 그 89건에서 오버레이가 **더 이상
   발동하지 않아야 정상**(cum_map 경로가 이미 옳은 값을 냄). 오버레이 함수
   자체는 지우지 않고 남긴다(다른 트리거로 tax_expense 행이 여전히 잘못될
   가능성에 대한 안전판) — 단 "이제 no-op이어야 한다"를 회귀 테스트로 고정.

### Phase 2 — 테스트

1. `fin2/tests/test_report_lines.py`(또는 관련 파일)에 00104573(tax_expense,
   2025Q3)·00172291(controlling_ni, 2025H1) 두 실측 케이스를 회귀 픽스처로
   추가 — `row.amounts` 비압축 확인 + 최종 emit된 `value_won`이 report_won과
   일치하는지 단언.
2. 기존 `test_report_lines_inline_xbrl_overlay.py`에 "근본수정 후 오버레이
   no-op" 케이스 추가(위 5-1-3).
3. pytest 전체(`fin2/tests tests/`) 통과 확인.

## 6. 검증 계획 (Gate B 전수 재감사 필수 — [[gateb-full-reaudit-is-required-to-close]])

1. Phase 0 표본 + tax_expense 91건 + controlling_ni 클러스터(아직 규모
   미상 — 최초 사례가 00172291 하나뿐이라 §5-1 구현 후 fy≥2024 fail_a 중
   `controlling_ni`/`net_income`류 재실행으로 규모 확정 필요) 전수 재실행.
2. 재감사 직전 스냅샷 필수(`scripts/run_gateb_audit_parallel.sh` 실행 전
   `face_audit_snap_*` 테이블) → 재감사 후 `verify_gateb_reaudit_transition_
   2026-08-24.py`류로 before/after 전수 대조, **차단등급 전이(pass/fail_b→
   fail_a) 0건** 확인.
3. face_audit 자체가 이번 버그로부터 자유로운 이유(§3 후반)를 검증 스크립트
   주석에 남겨 "오라클도 같이 틀려서 우연히 pass"가 아님을 명시.

## 7. 파이프라인 편입 체크리스트 (`docs/runbook_new_parser_pipeline_integration.md`)

- [ ] **배선** — 수정 위치가 `extract_report_lines()` 내부(기존 프로덕션
      진입점)라 `scripts/collect_new.py`의 두 call site(메인 + `--standardize-
      only`)는 이전 tax_expense 작업 때 이미 확인한 대로 **자동 포함**(재확인만
      필요, 새 배선 불요).
- [ ] **소급 백필 — 스코프는 Phase 0 실측 후 확정(사용자 결정, §8-b)**:
      - 옵션(i) fy≥2024만 우선(빠름, 이미 감사 인프라가 이 스코프에 맞춰져
        있음) — pre-2024 분은 별도 후속 트랙으로 분리.
      - 옵션(ii) Phase 0에서 pre-2024 비중이 유의미하면 R31급(775개사·
        82,402행) 전면 백필까지 한 번에.
      - 어느 쪽이든 `load_report_lines.py --recheck` → `build_std_v3.py
        --shard` 순서(tax_expense 때와 동일 패턴)로 실행.
- [ ] **검증** — §6 그대로.

## 8. 사용자 결정 필요 항목 (구현 착수 전)

- **(a) `text.py::_emit_section()`(Track B/fact_v2) 동시 수정 여부** — §3-3-0
  으로 갱신: face_audit(R36 체커)는 **선택이 아니라 필수**(오라클 자체가
  이 버그를 갖고 있음이 코드추적으로 확정됐다) — "할지"가 아니라 3-3-5가
  권고한 순서(face_audit 먼저)대로 "언제 하냐"만 남음. text.py(Track B)는
  여전히 선택 — 권고는 동시 수정(낮은 추가 위험, 같은 패치 형태), 단
  fact_v2가 실제 소비처인지 먼저 확인.
- **(b) 소급 백필 스코프** — Phase 0 실측(§3-1, pre-2024 비중 실측 완료)
  결과 fy≥2024에 몰려있지 않고 전 연도에 고르게 분포함을 확인했다(§3-1) —
  fy≥2024만 우선할 근거가 약해졌다. **offset 보정 구현 후 §3-3-5 재검증
  스크립트로 "진짜 바뀌는 행"만 남긴 재실측**을 다시 하고 나서 최종 스코프를
  정하는 쪽을 권고(주석컬럼 오탐이 섞인 §3-1 원 수치로 스코프를 정하면 과대
  추정될 수 있음).
- **(c) `overlay_tax_expense_value()` 존치 여부** — 권고: 지금은 존치(안전판),
  "근본수정 후 no-op 확인"까지만 이번 스코프. 완전 제거는 별도 세션.

## 9. 참고

- 설계 원본: `docs/plans/d_category_col_misselect_ni_label_dup_design_2026-08-23.md`
  §1-1, §1-4, §1-8.
- 메모리: [[gateb-full-reaudit-is-required-to-close]],
  [[feedback-verify-against-source]], [[feedback-plan-then-wait]],
  [[parser-pipeline-integration-runbook]],
  [[gateb-full-reaudit-2026-08-24-tax-expense-closed-controlling-ni-found]].
- 코드: `parser/xml/table_extractor.py::extract_rows()`(L194-320),
  `fin2/extract/report_lines.py::_emit_section_lines()`(L410-530),
  `fin2/extract/text.py::_emit_section()`(L860-930대),
  `fin2/audit/face_audit.py`(L455-524, R36 controlling_ni 체커).
