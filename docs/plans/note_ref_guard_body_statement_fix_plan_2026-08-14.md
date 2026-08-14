# 계획 — `_split_label_amounts()` 주석번호 가드 오탐 수정 (2026-08-14)

> 배경 = [`gate_b_revenue_bugB_note_ref_guard_root_cause_2026-08-14.md`](../qa/gate_b_revenue_bugB_note_ref_guard_root_cause_2026-08-14.md)
> — 근본원인 확정 + 전수스캔(185,067건 XML) 완료: 후보 **1,260,353건**, 필링
> **89,430건(48.3%)**, 영향 회사 유니버스 90%대. **이 계획은 문서일 뿐 — 실행은 별도
> 승인 후 착수**([정책](../../CLAUDE.md), 계획 작성 자체가 실행 지시 아님).

## 목표

`parser/xml/table_extractor.py::_split_label_amounts()`가 재무제표 **본문**(BS/IS/CF/SCE)
표에서, 콤마 없는 1~3자리 당기 금액을 "주석번호"로 오인해 드롭하는 오탐을 없애고, 이미
잘못 적재된 과거 데이터를 재파싱으로 바로잡는다.

## 수정 대상 코드 — 정확히 어디를 왜 바꾸는가

`parser/xml/table_extractor.py:490-497`:
```python
if (not amount_cells
        and _NOTE_REF_PATTERN.match(cell_nospace)
        and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
    continue
```

이 가드가 겨냥한 원래 포맷(함수 docstring, line 474-476)은 **정확히 6칸**(라벨 1 + 주석번호
1 + 당기명세/당기합계/전기명세/전기합계 4)이고, **주석번호는 항상 라벨 바로 다음 칸(i==1)**
에만 온다. 그런데 실제 코드는 두 조건을 전혀 확인하지 않는다:
1. 표가 진짜 6칸 구조인지(`len(cells)` 미확인).
2. 지금 보고 있는 칸이 정말 "라벨 바로 다음"인지(`not amount_cells` 라는 **간접** 조건만
   써서, 앞선 칸들이 전부 이미 같은 이유로 드롭됐으면 i==2, 3 에서도 계속 발동 — 실측:
   `4.단기미수수익, 총액 | 992 | 766` 처럼 2칸 다 드롭되는 사례도 확인됨, root-cause 문서
   §5 스캔 로그).

> ⚠ **Phase 0에서 폐기됨(2026-08-14)** — 아래 diff(`i==1 and len(cells)>=6`)는 실제 프로덕션
> 회귀 테스트(부국증권 사례)를 깨뜨리는 것으로 확인됐다. 상세 근거·대안은 Phase 0 결론 절 참고.
> 이 절은 최초 가설을 남겨두는 기록용이며 더 이상 구현 대상이 아니다.

**제안 수정(v1, 폐기)** — 두 조건을 코드로 명시:
```python
if (i == 1
        and len(cells) >= 6
        and not amount_cells
        and _NOTE_REF_PATTERN.match(cell_nospace)
        and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
    continue
```
- `i == 1`: 라벨 바로 다음 칸에서만 "주석번호"를 의심한다(문서화된 포맷과 일치).
- `len(cells) >= 6`: 진짜 6칸(그 이상 포함, 병합 등으로 칸이 더 있을 가능성 대비) 표에서만
  발동. 본문 BS/IS/CF/SCE 의 압도적 다수(3~5칸)는 이 가드 자체가 아예 안 걸리게 된다.
- `not amount_cells` 는 그대로 둔다(i==1 이면 사실상 항상 참이라 중복이지만, 안전망으로 유지).

## Phase 0 — 구현 전 확인(읽기전용, 승인 후 제일 먼저) — ★완료(2026-08-14), 결론: v1 수정안 폐기

- [x] **0-1. 보험/증권 6-column 표 1~2건 원문 재확인** — **결정적 반례 발견.**
      `fin2/tests/test_section_p_header.py::test_multi_note_ref_column_not_parsed_as_amount`가
      이미 이 가드의 **실제 동기가 된 진짜 사례**를 회귀 테스트로 고정해 두고 있었다(root-cause
      문서가 몰랐던 사실 — git log로 원커밋 `0964f9be`, 2026-06-13, "금융업 다중 주석참조 컬럼
      오인 → 금액 1칸 밀림 해소" 확인, 실제 회사=**부국증권**):
      ```python
      cells = ["Ⅰ. 현금 및 예치금", "2,4,32,34,35,36",
               "496,412,633,753", "125,529,986,707", "148,432,981,080"]
      ```
      **`len(cells)`는 5, 6이 아니다.** 즉 문서화된 "6-column 구조"(라벨+주석+당기명세+당기합계+
      전기명세+전기합계)와 실제 프로덕션에서 검증된 진짜 사례(라벨+주석+당기+전기+전전기=5칸)가
      다르다. `len(cells)>=6` 조건을 그대로 적용해 시뮬레이션한 결과(소스 미수정, 스크립트로
      동일 로직 재현):
      - 부국증권 5칸 케이스: 주석번호 스킵이 아예 발동 안 함 → `amounts[0]` 이 다시
        `"2,4,32,34,35,36"`가 되어 **버그 재발**(이 커밋이 고쳤던 정확히 그 버그).
      - 같은 테스트의 `["자산", "34", "1,000,000"]`(len=3, 단일 주석번호) 케이스도 동일하게
        재발.
      - `["기타", "2,433", "1,000"]`(len=3, `_AMOUNT_GROUPED_PATTERN` 보호)만 무사.
      → **`pytest fin2/tests/test_section_p_header.py` 가 v1 수정안을 그대로 넣으면 즉시
      FAIL**(직접 실행해 베이스라인 PASS 확인 후 시뮬레이션으로 재현, 소스는 안 건드림).
- [x] **0-2. 전수스캔 소표본 진위 확인** — 5개 샤드 CSV(`cells` 컬럼) 셀개수 분포를 집계하고,
      셀개수 구간(2/3/4/5/6/7/8/9)별 계층 샘플 **29건**을 뽑아 DB에서 `file_path`를 조회,
      그중 대표 2건(크라운해태홀딩스 BS "2.기타자본잉여금", SIMPAC BS "대손충당금")은 원문
      XML을 직접 열어 셀 값이 CSV와 일치함을 확인.
      **결과: 29/29(100%) 전부 "진짜 버그"(정상 당기/전기 금액이 주석번호로 오인되어 드롭)로
      판정, "진짜 주석번호였던 것"은 0건.** 또한 5,005행 전체 표본에서 `dropped_cell`에
      쉼표가 들어간(=부국증권 유형처럼 다중 그룹 참조로 의심되는) 행은 단 3건뿐이었고, 그
      3건도 실제로는 OCR/원문 오탈자로 보이는 기형 숫자("54,13,838,836")였지 진짜 다중
      주석참조가 아니었다 — **표본 전체에서 부국증권형 진짜 사례는 0건**(모집단 1.26M건
      대비 극히 희소하다는 뜻, 0건=없다는 뜻은 아님, 표본 한계 인정).
      셀개수별 분포(5,005행): len=2:41, 3:385, 4:2145, **5:1531**, 6:7, 7:680, 8:114, 9:97.
      len≥7 은 pre-2015 병합표(당기/전기/전전기 × [총액,순액] 등 페어가 한 행에 나열된
      구조)로, 첫 페어의 "총액" 이 콤마 없는 1~3자리일 때 이 가드에 걸려 드롭되는 동일
      메커니즘의 변형 — 진짜 주석번호 열이 아니다(원문 확인: SIMPAC 1999 BS "대손충당금"
      행, XML에 `678|10,628|340|4,772|156|17,877` 6개 순수 금액 셀만 존재, 주석 열 없음).
- [x] **0-3. `not amount_cells` 캐스케이드 재현 케이스 재확인** — `i==1` 제한만으로 캐스케이드
      (2칸 이상 연쇄 드롭)는 원천 차단됨을 로직상 확인(이후 인덱스는 애초에 가드 대상이 아님).
      다만 `len(cells)>=6` 제한과 결합하면 len<6 인 표는 가드 자체가 통째로 꺼져 부수적으로도
      막힘 — 그러나 0-1 반례 때문에 이 결합 방식 자체를 폐기.

### ★Phase 0 결론 — v1 수정안(`i==1 and len(cells)>=6`) 폐기, 재설계 필요

**핵심 문제**: 셀 개수(`len(cells)`)는 "진짜 버그 행"과 "진짜 주석번호 행"을 구분하는 신뢰할
수 있는 기준이 아니다. 두 케이스가 **같은 셀개수 구간(특히 len=5)에 섞여 있다** — 한진중공업홀딩스
버그 케이스(라벨+금액4=5칸)와 부국증권 정상 케이스(라벨+주석+금액3=5칸)가 셀 개수만으로는
구별 불가능.

**대안(제안, 사용자 결정 필요)**: 0-1/0-2 증거를 보면 실제 구별 신호는 **콤마 유무**다 —
- 부국증권형 진짜 주석번호는 항상 **콤마로 구분된 다중 그룹**("2,4,32,34,35,36") — 이미
  `_AMOUNT_GROUPED_PATTERN`이 못 거르는 "쉼표는 있지만 3자리 그룹이 아닌" 패턴.
- 버그로 확인된 29건은 전부 **콤마가 아예 없는 단일 숫자**("654", "992", "26"...).
- 즉 `len(cells)>=6` 대신 **"드롭 후보 셀 자체에 콤마가 있는지"**를 조건에 추가하면(예:
  `',' in cell_nospace`), 0-1의 부국증권 케이스는 계속 보호되면서 29건 버그는 전부 해소된다.
- 단, 이러면 **단일 주석번호**("34" 한 자리, 콤마 없음) 매칭은 사실상 무력화된다. 이 단일
  케이스의 진짜 프로덕션 동기는 git 히스토리상 원커밋(`c6299fe`, 압축 스쿼시 커밋)에 묻혀
  있어 추적 불가 — `0964f9be` 커밋 메시지는 "단일 주석번호 동작 불변"이라고만 적어 이미
  존재하던 동작을 그대로 유지했다고만 확인될 뿐, 실제 유발 사례는 확인 못 함. 0-2 표본(29건)에
  이 유형(콤마 없는 단일 소액)의 "진짜 버그"만 있고 "진짜 주석번호"는 하나도 없었다는 게
  이 매칭을 없애도 안전하다는 정황 증거이지만, 표본 한계상 100% 확신은 아니다.

### ★단일 주석번호 케이스 추가조사(2026-08-14, 사용자 요청) — 결론: comma 기반 조건 채택 권고

사용자 결정("단일 주석번호 케이스 더 조사 후 결정")에 따라 이 가드의 **실제 원조 모집단**
(보험·증권·캐피탈 34개사, `raw_report`에서 corp_name 매칭 — 흥국화재·삼성증권·삼성생명·
DB증권·부국증권·현대차증권·롯데손해보험 등)의 **전체 필링 3,752건**을 스캔 스크립트로
전수 재현(스크래치패드, DB/소스 미변경). 이 회사군은 6-column 구조가 가장 많이 나올
것으로 기대되는 정확한 표적 모집단이다.

| 지표 | 값 |
|---|---:|
| 스캔 필링 | 3,752건 |
| 총 후보(가드 발동) | 136,347건 |
| 콤마 있는 후보(다중 그룹, 부국증권형) | 36,290건(26.6%) |
| **콤마 없는 후보(단일 숫자)** | **100,057건(73.4%)** |

- **콤마 있는 후보 30건 무작위 대조**(현대차증권·삼성증권·다올투자증권·흥국화재·DB증권·
  미래에셋생명 등): **30/30 전부 진짜 다중 주석참조로 보임**("17, 25, 45", "15,33,34,36,37"
  처럼 짧은 오름차순 숫자열 + 뒤이은 셀 전부 정상 3자리그룹 금액) — 이 부분은 가드가
  **의도대로 정확히 동작**하고 있다.
- **콤마 없는 후보 중 "가장 6-column스러운 모양"(라벨+주석후보+금액3, 나머지 전부
  `_AMOUNT_GROUPED_PATTERN` 매치, 9,107건) 20건 무작위 대조**: **20/20 전부 진짜 버그**
  (정상 당기 금액이 드롭됨 — 예: 진원생명과학 `"7.미지급배당금(주석15)" | 512 | 2,174 |
  455,208 | 455,208"`에서 라벨 자체에 이미 "(주석15)"가 박혀 있어 뒤따르는 숫자는 주석과
  무관한 실제 금액임이 라벨 텍스트로 직접 확인됨).
- **종합**: 이 가드의 원조 모집단(보험·증권 34개사)만 봐도 콤마 없는 단일숫자 후보가
  100,057건이나 되는데, 그중 무작위 표본(20건, "가장 그럴듯한 모양"만 골라서도)에서
  진짜 주석번호는 0건. 콤마 있는 후보는 반대로 30/30 전부 진짜. **일반 모집단 표본(29건,
  0-2)까지 합치면 총 49건 대조 중 "콤마 없는 단일숫자가 진짜 주석번호인 사례"는 0건.**

**최종 제안(v2, `len(cells)` 조건 대신)**:
```python
if (not amount_cells
        and ',' in cell_nospace          # ★신규: 진짜 주석참조는 항상 콤마로 구분된 다중 그룹
        and _NOTE_REF_PATTERN.match(cell_nospace)
        and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
    continue
```
- `len(cells)>=6`·`i==1` 조건은 전부 제거(콤마 조건 하나로 충분 — 0-3의 캐스케이드도
  `not amount_cells`가 이미 첫 후보 이후엔 이 분기 자체에 안 들어가므로 부수적으로 계속 막힘).
  **한 줄 추가**로 끝나는 최소 변경.
- 기존 회귀 테스트 3개 중 2개(부국증권 다중참조, `"2,433"` 비참조) 그대로 통과, **1개
  (`["자산","34","1,000,000"]`, 단일주석 "34" 드롭 기대)는 의도적으로 동작이 바뀜** — 이제
  "34"는 드롭되지 않고 금액으로 유지된다. 이 기대값 자체가 위 49건 실측 증거와 배치되므로
  **테스트 기대값을 갱신**해야 함(회귀 아님, 근거 있는 설계 변경 — Phase 1에서 명시적으로
  처리).
- 시뮬레이션(소스 미수정, 스크립트로 이 조건 직접 재현)으로 7개 케이스(기존 회귀테스트 3개 +
  한진중공업홀딩스 + 캐스케이드 + 현대차증권 실사례 + 진원생명과학 실사례) 전부 기대대로
  동작함을 확인 완료.

## Phase 1 — 코드 수정 + 유닛 테스트 — ★완료(2026-08-14), v2도 폐기·**v7(표 단위 컨텍스트)**로 구현

Phase 1 실행 중 v2(콤마 조건 단독)도 실사례(한양증권 무형자산, `extract_facts()` 로 직접
검증)에서 회귀함을 추가로 발견 — 콤마 없는 단일 숫자는 **행 하나의 셀 내용만으로 원리적으로
판정 불가능**함을 실측 반례(한양증권 "11"=진짜 주석 vs 진원생명과학 "512"=진짜 금액, 셀
모양 동일·정답 반대)로 확정. 사용자 결정("표 단위 컨텍스트로 제대로 구현")에 따라 최종
구현은 **v7**:

```python
def _table_has_comma_note_column(rows_cells: list[list[str]]) -> bool:
    """표를 한 번 미리 훑어 콤마 다중참조("2,4,32,…")가 있는 행이 하나라도 있으면 True."""
    for cells in rows_cells:
        if len(cells) < 2:
            continue
        cell_nospace = _TRAIL_DECOR_RE.sub('', cells[1].replace(' ', ''))
        if (',' in cell_nospace and _NOTE_REF_PATTERN.match(cell_nospace)
                and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
            return True
    return False

def _split_label_amounts(cells, table_has_note_column: bool = False):
    ...
    if (i == 1 and not amount_cells
            and _NOTE_REF_PATTERN.match(cell_nospace)
            and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)
            and (',' in cell_nospace or table_has_note_column)):
        continue
    ...
```
- 콤마 다중참조("4,28", "2,4,32,…")는 행 하나만 보고 **항상** 주석으로 확정(오탐 0건 실측).
- 콤마 없는 단일 숫자("34", "11")는 **같은 표의 다른 행에 콤마 다중참조가 있다고 확인됐을
  때만**(`table_has_note_column`) 주석으로 본다 — `extract_rows()`가 표 순회 전 한 번
  미리 `_table_has_comma_note_column()`으로 판정해 모든 행에 전달(성능: 표 1개당 1회
  선스캔, 표 크기가 작아 비용 무시 가능).
- `i == 1` 제한도 유지 — 콤마 없는 후보가 연달아 나올 때(캐스케이드) 첫 칸만 대상이 되게
  해 둘째 칸 이후까지 번지는 연쇄 오탐을 막는다(Phase 0-3에서 이미 확인한 메커니즘).
- v1(`len(cells)>=6`)·v2(콤마 단독)·v3~v6(`len==6`+"나머지 깔끔함" 조합, 여러 변형)는 전부
  실사례 대조 과정에서 폐기됨 — 근거는 위 "Phase 0 결론"·"단일 주석번호 추가조사" 절 및
  대화 로그 참고. `parser/xml/table_extractor.py`의 `_split_label_amounts`/
  `_table_has_comma_note_column`/`extract_rows` docstring에도 근거를 남겨둠.

- [x] **1-1. `_split_label_amounts()` 조건 수정** — 위 v7 diff. `extract_rows()`가
      표 순회 전 `table_has_note_column`을 한 번 계산해 매 행 호출에 전달하도록 배선.
      `fin2/extract/report_lines.py`의 다른 두 호출부(`_detect_period_layout`·
      `_emit_eps_lines`)는 기본값(False, 콤마 단독 규칙)을 그대로 둠 — 전자는 내부 휴리스틱
      (period 수 감지)에만 쓰여 최종 값에 영향 없고, 후자(EPS 행)는 구조상 진짜 주석 컬럼이
      나올 일이 없어(주석은 라벨 인라인 표기) 콤마 조건만으로 충분·더 안전.
- [x] **1-2. 기존 회귀 테스트 기대값 갱신** —
      `fin2/tests/test_section_p_header.py::test_multi_note_ref_column_not_parsed_as_amount`
      의 `["자산", "34", "1,000,000"]` 케이스: "34 드롭"→"34를 금액으로 유지"(`table_has_note_column`
      기본값 False이므로). `test_interim_is_cumulative_table_wins_over_annual_comparative`도
      합성 XML에 실제 부국증권 원문처럼 콤마 다중참조 형제 행("1. 수수료수익 | 2,21 | …")을
      추가해 `table_has_note_column=True`가 되도록 보정(원문 구조와 일치시킴, 회귀 아님).
- [x] **1-3. 회귀 테스트 추가** — `test_note_ref_guard_r19_comma_required()`에 6가지 케이스:
      (a) 한진중공업홀딩스 실사례, (b) 캐스케이드(콤마有/無 컨텍스트 둘 다), (c) 현대차증권
      콤마 다중참조 실사례, (d) 진원생명과학 실사례(표에 주석 컬럼 없음), (e) 한양증권
      실사례(표에 주석 컬럼 있음, `table_has_note_column=True`/`False` 양쪽 다 확인),
      (f) `_table_has_comma_note_column()` 헬퍼 자체(한양증권형 vs 진원생명과학형 표).
      추가로 `extract_facts()`를 부국증권 H1 2018·한양증권 2014 Q1·한진중공업홀딩스 2025 H1
      원문 XML에 직접 돌려 최종 값이 맞는지 end-to-end 확인 완료(원문대조).
- [x] **1-4. `pytest tests/ fin2/tests/` 전체 통과 확인** — 515 passed, 1 failed(무관 기존
      실패 `test_biz_section.py::test_lxintl_facility_table_dropped` — `git stash`로 내 변경
      없이도 동일하게 실패함을 확인, biz_section.py는 table_extractor 를 아예 안 씀).

## Phase 2 — 소급 백필(전수) — ★완료(2026-08-14, 17:18~20:50 KST, 약 3시간32분)

이번 결함은 **report_lines 를 만드는 계층2 추출기 자체**의 버그라, 영향받은 89,430건은
**report_lines 재추출**(그리고 이를 소비하는 계층3 std_v3 재표준화)이 필요하다 — 단순
값 패치가 아니라 파서를 고치고 다시 돌리는 근본 수정(R0 원칙과 일치).

- [x] **2-1. 백필 방식 확정** — 러너북 B1 표의 "fin2 추출·매핑" 행(`run.py parse-reset`
      류)은 **std_v2/fact_v2 경로**(`dart_xml_parser.py`)를 재파싱하는 명령이라 대상이
      다르다(v2는 이번 트랙 범위 밖 — Phase 0 사용자 결정). 이번 버그는 **`report_lines`**
      (계층2)의 버그이므로 정확한 명령은 `scripts/load_report_lines.py`(report_lines
      전량적재 드라이버, 기존 1차 패스·pre-2015 2차 패스 실사용) — `--recheck`(done 포함
      전량 재처리)·`--fy-min`/`--fy-max`(연도 범위)·`--shard a/n`(병렬) 지원 확인.
- [x] **2-2. 대상 축소 옵션** — **사용자 결정(2026-08-14): 전체 185,067건 전수 재추출**
      (부분 후보만 vs 전수 중 후자 선택 — 단순·안전, 짐작 리스크 없음).
- [x] **2-3. std_v3 재표준화** — `scripts/build_std_v3.py`(corp 단위로 report_lines →
      std_financials_v3 재빌드, `--year-min`·`--shard a/n` 지원) 확인. report_lines 가
      먼저 전부 갱신된 **후** 실행해야 함(순서 의존).
- [x] **2-4. 재개 안전성** — `load_report_lines.py`는 `report_line_load_progress`에 rcept
      단위로 기록해 중단 시 재개 가능(`--recheck` 없이 재실행하면 done/skip 스킵). 실행은
      **사용자가 백그라운드로**([[feedback-long-running-commands]], 러너북 B4).

### 실행 커맨드(사용자 실행)

두 단계(report_lines 전량재추출 → std_v3 재표준화, 각 5-shard 병렬)를 순서대로 묶은
러너 스크립트: `scripts/run_r19_backfill_parallel_2026-08-14.sh`(1단계 5-shard 전부 정상
종료 확인 후에만 2단계 시작, 실패 시 자동 중단·재실행하면 이어감). 백그라운드 실행:
```bash
nohup caffeinate -i bash scripts/run_r19_backfill_parallel_2026-08-14.sh &
```
(최초 시도 시 `> logs/r19_backfill_wrapper.log 2>&1` 리다이렉션을 붙였다가 복사-붙여넣기
과정에서 줄바꿈이 끼어들어 `bash: syntax error near unexpected token 'newline'`로 깨짐 —
프로세스는 전혀 안 뜬 채로 죽어 데이터는 안전했음. 리다이렉션 없이 nohup 기본 출력
(`nohup.out`)만 쓰는 위 짧은 형태로 재실행해 해결. **교훈**: 이 환경에서 `nohup ... > file
2>&1 &`처럼 긴 리다이렉션이 들어간 한 줄 명령은 붙여넣기 중 깨질 수 있음 — 가능하면
리다이렉션 없는 짧은 형태 우선.)

진행 확인(아무 때나):
```bash
tail -f nohup.out
```
```bash
.venv/bin/python scripts/load_report_lines.py --status
```

- 대상 185,067건(1999~2027) 확인 완료(`report_line_load_progress` 현재 183,750건 done/skip
  — 이미 대부분 1차·2차 패스로 적재돼 있어 `--recheck` 없이는 전부 스킵됨, 그래서
  `--recheck` 필수).
- 멱등(rcept/corp 단위 delete-then-insert) — 중단 후 그냥 스크립트 재실행하면 이어감(단
  `--recheck`는 done 필터를 아예 안 걸어서, 중간에 죽으면 그 샤드는 처음부터 다시 도는
  점은 감안 — 값은 항상 정확하게 남지만 재개가 "이어서"는 아니고 "처음부터 재검사"임).

### 실행 결과(2026-08-14 17:18~20:50 KST)

**Stage 1 — report_lines 전량 재추출**: 대상 185,067건 전부 처리(2015+ 103,266건 +
pre-2015 82,005건, 5-shard 전부 정상 종료). `report_lines` 60,534,978행(29GB), 이상치
표시 10,113건, **에러 0건**.

**Stage 2 — std_v3 재표준화**: 5-shard 전부 정상 종료, 총 2,537개사·약 299,565행 재빌드
(샤드별 507~508개사, 59,341~60,487행), **에러 0건**(로그의 `!`(실패) 라인 전 샤드 0건).

## Phase 3 — 검증(다음 세션, 미착수)

- [ ] **3-1. Gate B 재감사** — `scripts/run_gateb_audit_parallel.sh`(이번 세션에서 이미 쓴
      5-shard 패턴 재사용) 로 fail_a/fail_b 전수 재확인. **기대 효과**: revenue 확정버그 B
      (한진중공업홀딩스 2건)는 해소. 그 외 fail_a/fail_b population 전반의 변화도 관찰
      (이 결함이 지금까지 다른 계정의 fail_a/fail_b 로도 이미 새어나왔을 가능성 — Phase 0-2
      진위확인에서 규모 가늠).
- [ ] **3-2. 항등식 재검사** — BS 항등식(자산=부채+자본), IS/CF 표본 대조 — 회귀 없는지.
- [ ] **3-3. `docs/PARSING_RULES.md`에 신규 규칙 등재**(R19 후보) — 구현·백필·검증 완료
      **후**에 등재(R14~R18과 동일 순서 — 미리 등재하지 않음).
- [ ] **3-4. 이번 스캔에서 나온 부수 발견(있다면) 별도 기록** — 예: 특정 회사군에 유난히
      집중된 패턴이 있으면 후속 조사 항목으로 분리.

## 리스크 / 열린 질문(사용자 결정 필요)

1. **Phase 2-2 백필 범위** — 스캔 결과 기반 부분 재추출 vs 전체 185K 전수 재추출. 후자를
   권고(단순·안전, 이 프로젝트의 기존 대규모 백필 관행과 일치)하나 시간이 더 걸림.
2. ~~**Phase 0-1 진짜 6-column 표 검증 대상 회사**~~ — Phase 0에서 확인 완료: 부국증권
   (`0964f9be` 커밋, 5칸 구조). 결과가 v1 수정안을 무효화함 — 상세는 Phase 0 결론 절.
3. ~~**legacy std_v2/fact_v2 경로**~~ — Phase 0에서 확인 완료(2026-08-14): **살아있는 소비처
   있음, 짐작 아님.** `parser/xml/dart_xml_parser.py:28`가 `table_extractor.extract_rows`를
   그대로 import해 std_v2/fact_v2도 **동일한 버그 함수**(`_split_label_amounts`)를 공유한다.
   `app/data/extended.py`("확장 재무항목" 기능, `extended_financials`=`fact_v2×
   statement_source`)가 **`amount_won` 자체를 fact_v2에서 직접 로드**(`app/data/extended.py:25-38`),
   `app/data/shareholder_return.py`도 같은 조인 패턴 — `standard_financials` 뷰의 v2→v3
   스왑([[bridge-swap-view-executed-2026-08-09]])은 표준 재무제표(METRIC_REGISTRY 캐노니컬
   계정)만 커버하고 이 기능은 안 커버함. **사용자 결정(2026-08-14): v2는 결국 폐기 예정이라
   이 버그 수정 범위에서 신경 쓰지 않는다** — Phase 2 백필은 report_lines/std_v3만 커버,
   std_v2/fact_v2·`extended_financials` 재적재는 이번 트랙 범위 밖(의도적 미해결로 기록).

## 근거
`docs/qa/gate_b_revenue_bugB_note_ref_guard_root_cause_2026-08-14.md`(근본원인+전수스캔),
`docs/runbook_new_parser_pipeline_integration.md`(백필 절차), 기존 R14~R18 사례(계획→승인
→구현→백필→검증→PARSING_RULES 등재 순서 전례).
