"""원문 표의 **행** 중 파서가 못 실은 것 탐지 — 결측을 원문 쪽에서 센다(행 단위).

## 왜 필요한가 — `orphan_tables` 로도, 사람 대조로도 안 잡히던 것

`fin2/audit/orphan_tables.py` 는 **표** 단위만 본다. 표는 정상 귀속되고 그 안의 **행**만
사라지는 결함은 못 잡는다 — R149(EPS 행 통째 결측)가 그 예다.

그리고 사람이 원문을 성실히 열어봐도 못 잡는다. 캠페인의 원문대조 판정 기준이
"**CSV 의 라벨을 기준으로** 화면에서 찾아 금액을 비교"(`docs/plans/layer2_review_browser_
agent_automation_design_2026-09-18.md` §4-3)라서 방향이 CSV → 원문 **단방향**이기
때문이다. CSV 에 있는 행이 화면에 없으면 잡히지만, 화면에 있는데 CSV 에 없는 행은
순회 대상에 아예 들어오지 않는다. 실증(2026-09-20): 신한지주 13건은 "전 항목 원문
대조" 규칙 시행 **후**에 pass 됐는데도 EPS 결측이 걸리지 않았다.

그래서 이 감사는 방향을 반대로 놓는다 — **원문 행 → 적재 결과**.

## ★설계상 가장 중요한 점 — `parse_amount()` 를 쓰지 않는다

"이 행에 금액이 있나"를 파서와 같은 함수로 판정하면, **파서가 못 읽는 셀은 이 감사도
못 읽어** 같은 맹점을 그대로 물려받는다. R149 가 정확히 `parse_amount()` 의 결함
('2,564원' → None)이었고, 그때 이 감사가 `parse_amount` 를 썼다면 아무것도 못 잡았다.
그래서 **사람 눈 기준의 느슨한 숫자 판정**(`_LOOSE_NUM`)을 따로 둔다 — 숫자처럼
보이는 칸을 가진 행인데 적재 결과에 라벨이 없으면 그게 신호다.

## 라벨 대조 — 정규화가 필요한 실측 사유

파서는 원문 셀 텍스트를 그대로 저장하지 않는다. 실측으로 확인된 차이 3종을 정규화한다:
 (1) **SCE 복합라벨** — '총포괄손익' 행을 `'총포괄손익>당기순이익(손실)'` 로 부모를
     앞에 붙여 저장한다(R134/R135). → `>` 조각도 후보로 본다.
 (2) **주석번호** — 원문 `'유동매도가능금융자산 (주5,16)'` ↔ 적재 `'유동매도가능금융자산'`.
 (3) **꼬리 기호** — `'총포괄손익:'` ↔ `'총포괄손익'`.
정규화를 안 하면 이 3종만으로 발화율이 17.5% → (정규화 후) 12.5% 로, SCE 계열
거짓양성이 대부분 사라진다(시총순 40개사 최신 필링 측정).

## 어느 행을 대상으로 삼나 — 거짓양성과 세 번 싸운 기록 (2026-09-20)

초판은 "금액칸이 있는데 적재 안 된 행"을 전부 올렸다가 **정상 동작을 결함으로 신고**했다.
적재되지 않는 **열**에만 값이 있는 행이 그렇다:
· 고려아연 20220816001335 `['장기파생상품금융부채', '', '1,928,974,207']` —
  당기(2022-06-30)엔 그 부채가 없다. BS 는 당기만 적재한다.
· NAVER 20180515002682 `['유동매도가능금융자산 (주5,16)', '', '79,435,727,110']` —
  IFRS 9 이 2018-01-01 시행돼 그 계정 자체가 당기부터 사라졌다.
· NAVER 20150515001873 — 분기 CF 의 '조정사항' 세부행이 **연간 열에만** 값을 싣는다.
  분기보고서라 파서는 분기 열만 적재한다 → 거짓 발화 113건.

두 번의 실패한 접근을 남겨둔다(같은 함정을 다시 밟지 않도록):
 (1) **최빈값** — "당기 열 = 행들이 값을 넣은 위치의 최빈값". 위 분기 CF 에서 연간
     열만 채운 행이 다수라 최빈값이 연간 열로 잡혀 정상 동작이 통째로 뒤집혔다.
 (2) **최좌측 + 비율 임계값** — 임계값 경계에서 표마다 결과가 갈렸고(index 1 이 20행,
     임계 21행이라 탈락), 무엇보다 **전제 자체가 틀렸다**: DART 표는 값 사이에 빈 칸을
     끼워서 같은 표 안에서도 행마다 당기 값의 물리 위치가 다르다(신한지주 [연결] IS 는
     index 1 인 행 21개와 index 2 인 행 27개가 섞여 있다). "표당 당기 열 하나" 모델로는
     풀리지 않는다 — 파서는 이걸 헤더 그리드(R88/R144)로 푼다.
 (3) **채택 — 파서 자신의 결과를 기준으로 자기교정**. `_loaded_value_positions()` 가
     "적재된 행들이 값을 놓은 위치"를 모으고, 적재 안 된 행은 그 위치에 값이 있을
     때만 결측으로 본다. 헤더를 해석하지 않으므로 추측이 끼지 않는다.

## 실측 (2026-09-20, (3) 적용 후)

· 검출력 — R149 수정만 끈 상태(=EPS 결측 재현)에서 신한지주 20220516002487 의
  EPS **3행 전부**([연결] 기본·희석주당순이익, [별도] 기본 및 희석주당이익)를 적출.
  수정 적용 상태에서는 0건.
· 거짓양성 — 위 3개 사례 전부 0건.
· 발화율 — 회사별 1건씩 453건 센서스에서 5건(1.1%)이었고, 그중 4건이 위 거짓양성
  계열이었다. (3) 적용 후 남는 것은 신한지주 20150515002196 의 `'4,244, 863'`
  (숫자 안에 공백이 든 원문 서식) 계열뿐 — 실제 결함 후보다.

## 센서스 실측 (2026-09-20) — 회사별 1건씩 400개사 (5차 수정 **이전** 수치)

발화 3건(**0.8%**). 원문 셀을 덤프해 분류한 결과 **2건은 진짜 결함, 1건은 거짓양성**:
· 대신증권 20150515002053 · 코리안리 20150515002691 — 원문이 **3개 논리행을 1개 `<TR>`
  로 압축**한 서식(라벨 3개 병합 + 금액 3개 병합). 예:
  `['4. 연결이익잉여금(주석25) (대손준비금 적립액) (대손준비금 적립예정금액)',
    '581,929,430 5,320,412647,720', '', '576,044,2464,652,625667,787', '']`
  → `parse_amount` 가 (정당하게) 결측 처리하고 **연결이익잉여금 행이 통째로 유실**된다.
  금융업 대손준비금·비상위험준비금 서식. 별도 결함으로 조사 필요.
· 한화에어로스페이스 20150515001451 — 아래 "남은 거짓양성".

## 적재 위치는 **값으로** 찾는다 — 5차이자 마지막 수정 (2026-09-20)

위 (3)은 적재된 행의 **첫 금액 위치**를 적재 위치로 봤다. 그게 마지막 오답이었다.
중간보고서 손익계산서는 열이 `[당기3개월, 당기누적, 전기3개월, 전기누적, 전기연간,
전전기연간]` 이고 파서는 **누적** 열을 적재한다(R144). 그런데 첫 금액은 3개월 열
(index 1)이라 적재 위치가 1 로 잡히고, 그러면 **3개월만 채우고 누적이 빈 행**이
결측으로 둔갑한다.

이 하나가 남은 거짓양성 전부였다 — 실측: 제닉·HDC랩스·형지I&C·엘컴텍·덕우전자·
한화에어로스페이스·큐렉소. 전부 "당기 누적 칸이 공란" 이었고 파서는 옳게 동작했다.
(초기 조사에서 이 중 3건을 "진짜 결함" 으로 잘못 보고했다 — 원문 셀만 보고 열 의미를
확인하지 않은 탓이다.)

→ `_matches_loaded_value()` 로 **적재된 값이 실제로 놓인 칸**을 찾는다. 값은 단위
배수만 다르므로 자릿수 스케일을 허용해 맞댄다. 이러면 누적 열(index 2)이 잡히고,
3개월만 있는 행은 대상에서 빠진다. 헤더 해석이 아니라 값 대조라 추측이 끼지 않는다.

이 검산은 **차단하지 않는다**(`GRADE_INFO`) — 남은 발화분은 사람이 원문을 봐야
판단되는 것들이고, 차단하면 캠페인 흐름이 끊긴다. 가시화·기록만 하고 실제 처리는
전수 센서스(`scripts/census_row_coverage.py`)로 모아서 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from parser.xml.dart_xml_parser import _parse_xml_file

from fin2.audit.layer2_selfcheck import (CheckResult, FAIL, GRADE_INFO, NA,
                                         PASS)

CODE = "SOURCE_ROW_NOT_LOADED"

# 사람 눈 기준 "숫자 칸" — 숫자+콤마(+괄호/음수기호), 뒤에 '…원' 단위만 허용.
# '제22기'·'2015년'·'3개월' 같은 기간 표기는 원으로 끝나지 않아 걸리지 않는다.
# ★파서의 `parse_amount()` 를 쓰지 않는 것이 핵심이다(위 docstring).
_LOOSE_NUM = re.compile(r"^[(\[]?\s*[-−△▲]?\s*\d[\d,\.\s]*\s*[)\]]?\s*(?:[가-힣]{0,3}원)?$")

_HEADER_LABELS = frozenset({"과목", "계정과목", "구분", "내용", "항목"})

# ★"숫자처럼 보인다"로는 부족하다 — 재무제표 표에는 **주석번호 열**이 있고 거기엔
#   '31' 같은 작은 정수가 들어간다. 그걸 금액으로 세면 절 제목 행이 결측으로 잡힌다
#   (실측: 삼성증권 20160516003030 `['ⅩⅧ. 지배기업소유주지분주당손익','31','','','','']`
#   — '31' 은 주석번호이고 그 행은 EPS 절 제목이다. 거짓 발화 6건).
#   그래서 **금액다움**을 따로 본다: 천단위 콤마가 있거나 / 4자리 이상이거나 /
#   괄호·부호로 음수를 표시했거나. 주석번호(1~3자리 맨숫자)는 여기서 빠진다.
#   한계: 진짜로 작은 금액(예: 백만원 단위 표의 '449')만 가진 행이 유실되면 놓친다 —
#   선별 도구의 의도된 절충이다(거짓양성이 거짓음성보다 비싸다, R6 주석과 같은 이유).
_AMOUNT_LIKE_RE = re.compile(
    r"^[(\[]?\s*[-−△▲]?\s*(?:\d{1,3}(?:[,\s]\d{3})+|\d{4,})[\d,\.\s]*\s*[)\]]?"
    r"\s*(?:[가-힣]{0,3}원)?$")


def _looks_like_amount(cell: str) -> bool:
    """그 칸이 **금액**으로 보이는가(주석번호·기간표기 제외)."""
    s = (cell or "").strip()
    if not s:
        return False
    if _AMOUNT_LIKE_RE.match(s):
        return True
    # 괄호/부호로 음수를 표시한 작은 수도 금액이다('(31)' 은 주석번호가 아니다).
    return bool(_LOOSE_NUM.match(s)) and (s[0] in "(-[−△▲")

# 당기 열로 인정하려면 그 위치가 "숫자를 가진 행"의 이 비율 이상에서 채워져 있어야 한다
# (한 행의 오타성 숫자나 주석번호 한두 개에 끌려 왼쪽으로 밀리지 않도록).
_MIN_COLUMN_SHARE = 0.25
_NOTE_REF_RE = re.compile(r"[\(（]\s*주\s*석?\s*[\d,\.\s·]*\s*[\)）]")

_SECTION_META = {
    "BS_C": ("consolidated", "BS"), "IS_C": ("consolidated", "IS"),
    "CF_C": ("consolidated", "CF"), "SCE_C": ("consolidated", "SCE"),
    "APPR_C": ("consolidated", "APPR"),
    "BS_S": ("separate", "BS"), "IS_S": ("separate", "IS"),
    "CF_S": ("separate", "CF"), "SCE_S": ("separate", "SCE"),
    "APPR_S": ("separate", "APPR"),
}


def _first_number_index(cells: list[str]) -> int | None:
    """그 행에서 **처음으로 금액인 칸**의 위치(라벨칸 0 은 제외). 없으면 None.

    판정은 `_looks_like_amount()` — 주석번호 열('31')을 금액으로 세지 않기 위해서다.
    """
    for i, c in enumerate(cells):
        if i == 0:
            continue
        if _looks_like_amount(c):
            return i
    return None


_UNIT_STEPS = (1, 1_000, 1_000_000, 100_000_000, 1_000_000_000, 1_000_000_000_000)


def _cell_digits(cell: str) -> int | None:
    """셀 텍스트에서 숫자만 뽑아 정수로(부호 무시). 비교용이라 부호·괄호는 안 본다."""
    digits = re.sub(r"[^\d]", "", cell or "")
    return int(digits) if digits else None


def _matches_loaded_value(cell: str, values: set[int]) -> bool:
    """그 셀이 적재된 값 중 하나와 **단위 배수만 다르게** 같은가."""
    d = _cell_digits(cell)
    if d is None or d == 0:
        return False
    return any(d * step == v for v in values for step in _UNIT_STEPS)


def _loaded_value_positions(rows_cells: list[list[str]],
                            loaded_by_label: dict[str, set[int]]) -> set[int]:
    """그 표에서 **이미 적재된 행들이 값을 놓은 물리 위치들**.

    ★왜 이렇게 하는가(2026-09-20 3차 수정) — "표의 당기 열은 index N" 이라는 모델이
      애초에 틀렸다. DART 표는 값 사이에 빈 칸을 끼우거나 colspan 을 쓰기 때문에 **같은
      표 안에서도 행마다 당기 값의 물리 위치가 다르다**(실측: 신한지주 20220516002487
      [연결] IS 는 첫 숫자 위치가 index 1 인 행 21개, index 2 인 행 27개가 섞여 있다).
      파서는 이걸 헤더 그리드(R88/R144 `header_cols`)로 푼다 — 감사가 그 해석을 다시
      추측하면 그 추측이 또 하나의 결함원이 된다.

    그래서 기준을 **파서 자신의 결과**에서 가져온다: 적재된 행들이 실제로 값을 놓은
    위치 집합을 모으고, 적재 안 된 행은 **그 위치 중 하나에 값이 있을 때만** 결측으로
    본다. 자기교정이라 서식마다 따로 맞출 필요가 없다.

    이 방식이 앞선 두 판(최빈값 / 최좌측+임계값)에서 틀렸던 것들을 전부 바로잡는다:
    · 분기보고서 CF 의 '조정사항' 세부행 — 연간 열에만 값이 있고(index 3), 적재된 행은
      분기 열(index 1)을 쓴다 → 위치 불일치로 제외(NAVER 20150515001873 에서 거짓
      발화 113건 → 0건).
    · BS 의 '당기 공란' 행 — 값이 전기 열에만 있다 → 같은 이유로 제외(고려아연·NAVER).
    · 신한지주 EPS 행 — 적재된 '총포괄이익' 등과 **같은 위치**에 값이 있다 → 그대로
      적출(R149 검출력 유지, 연결·별도 양쪽).

    ★집합을 **적재행 다수가 쓰는 위치로 좁힌다**(2026-09-20 4차) — 적재된 행의 "첫 금액
      위치"는 그 행이 *적재된 열*과 같지 않다. 당기가 비고 전기에만 값이 있는 행도
      (IS/CF 는 전기열까지 적재하므로) 적재되는데, 그 행의 첫 금액 위치는 전기 열이다.
      그래서 소수 행 때문에 전기·연간 열까지 집합에 들어오고, "연간 열에만 값이 있는
      행"이 다시 결측으로 잡혔다(실측: NAVER 20150515001873 [연결] IS — 적재행 대부분은
      index 1 인데 소수가 3·5 를 써서 집합이 {1,3,5} 가 되고, index 5 에만 값이 있는
      세후기타포괄손익 행 4건이 거짓 발화). 비율 문턱으로 그 꼬리를 자른다.
    """
    counts: dict[int, int] = {}
    n_loaded = 0
    for cells in rows_cells:
        if not cells:
            continue
        label = normalize_label(cells[0])
        values = loaded_by_label.get(label)
        if not values:
            continue
        # ★적재된 **값**이 실제로 놓인 칸을 찾는다(2026-09-20 5차). "첫 금액 위치"를
        #   쓰면 틀린다 — 중간보고서 손익계산서는 열이
        #   [당기3개월, 당기누적, 전기3개월, 전기누적, 전기연간, 전전기연간] 인데
        #   파서는 **누적** 열을 적재한다(R144). 첫 금액은 3개월 열(index 1)이라
        #   적재 위치가 1 로 잡히고, 그러면 "3개월만 채우고 누적이 빈 행"이 결측으로
        #   둔갑한다(실측 거짓양성: 제닉·HDC랩스·형지I&C·엘컴텍·덕우전자 —
        #   전부 당기누적 칸이 공란이었다). 값으로 맞대면 index 2(누적)가 잡힌다.
        for i, c in enumerate(cells):
            if i == 0:
                continue
            if _matches_loaded_value(c, values):
                counts[i] = counts.get(i, 0) + 1
                n_loaded += 1
                break
    if not counts:
        return set()
    floor = max(1, n_loaded * _MIN_COLUMN_SHARE)
    return {idx for idx, n in counts.items() if n >= floor}


def _current_period_index(rows_cells: list[list[str]]) -> int | None:
    """표의 **당기 열 위치**를 행들의 다수결로 정한다(구버전, 참고용).

    ★실사용 경로에서는 쓰지 않는다 — `_loaded_value_positions()` 로 교체됐다.
      남겨둔 이유는 왜 이 접근이 실패하는지가 회귀 테스트로 고정돼 있기 때문이다.

    ★왜 필요한가(2026-09-20, 초판의 체계적 거짓양성 수정) — BS 는 설계상 당기
      (`col_index=0`)만 적재한다(`_PERIOD_AXIS_STATEMENTS` 정책). 그래서 **당기가
      공란이고 전기에만 값이 있는 행**은 적재될 것이 애초에 없다. 초판은 이걸
      "결측"으로 올려 정상 동작을 결함으로 신고했다:
        · 고려아연 20220816001335 `['장기파생상품금융부채', '', '1,928,974,207']`
          — 당기(2022-06-30)엔 그 부채가 없다.
        · NAVER 20180515002682 `['유동매도가능금융자산 (주5,16)', '', '79,435,727,110']`
          — IFRS 9 이 2018-01-01 시행돼 그 계정 자체가 당기부터 사라졌다.
      둘 다 원문이 당기를 비워둔 것이고 파서는 옳게 동작했다.
    ★그래서 "당기 칸에 숫자가 있는 행"만 대상으로 삼는다. 열 위치는 표마다 다르므로
      (주석 열이 끼거나 값 사이에 빈 칸이 끼는 서식이 흔하다) **행들이 실제로 값을 넣은
      위치**에서 유도한다. DART 는 당기를 **맨 왼쪽**에 인쇄하므로 *가장 작은* 위치를
      쓴다 — 단, 한 행의 오타성 숫자에 끌려가지 않도록 그 위치가 숫자를 가진 행의
      `_MIN_COLUMN_SHARE` 이상에서 채워져 있어야 한다.

    ★최빈값을 쓰면 안 된다(2026-09-20 2차 수정) — 분기보고서 현금흐름표는 열이
      [당기분기, 전기분기, 전기연간, 전전기연간] 인데 '조정사항' 세부행 다수가
      **연간 열에만** 값을 싣는다. 그러면 최빈값이 연간 열로 잡혀, 분기 열만 적재하는
      정상 동작이 결측으로 뒤집힌다(실측: NAVER 20150515001873 에서 CF 113행이
      거짓 발화). 가장 왼쪽 기준이면 같은 표에서 0건이 된다.
    """
    counts: dict[int, int] = {}
    n_rows_with_numbers = 0
    for cells in rows_cells:
        idx = _first_number_index(cells)
        if idx is not None:
            counts[idx] = counts.get(idx, 0) + 1
            n_rows_with_numbers += 1
    if not counts:
        return None
    floor = max(1, int(n_rows_with_numbers * _MIN_COLUMN_SHARE))
    solid = [idx for idx, n in counts.items() if n >= floor]
    return min(solid) if solid else min(counts)


@dataclass(frozen=True)
class MissingRow:
    basis: str
    statement: str
    label: str
    amounts: tuple[str, ...]


def normalize_label(text: str) -> str:
    """원문 셀과 적재 라벨을 같은 자리에 놓기 위한 정규화(위 docstring (1)~(3))."""
    s = _NOTE_REF_RE.sub("", text or "")
    s = re.sub(r"\s+", "", s)
    return s.rstrip(":：·.")


def loaded_label_keys(label_raw: str) -> set[str]:
    """적재 라벨 하나가 원문 셀과 맞을 수 있는 형태들. 복합라벨('부모>자식')은
    전체와 각 조각을 모두 후보로 둔다.

    ★조각도 **각각** 정규화한다(2026-09-20) — 안 하면 꼬리 기호가 붙은 부모 이름이
      원문 셀과 안 맞는다. 실측: 두산 20150515002498 [연결] SCE 는 라벨이 **두 칸**으로
      나뉘어 있고(`['자본에 직접 반영된 소유주와의 거래 등:', '주식선택권의 행사', ...]`,
      R134/R135 다중라벨 서식) 파서는 이를
      `'자본에 직접 반영된 소유주와의 거래 등:>주식선택권의 행사'` 로 옳게 저장한다.
      전체 문자열만 정규화하면 맨 끝 ':' 만 떨어져 조각은 `'…거래 등:'` 으로 남고,
      원문 첫 칸(`'…거래 등:'` → 정규화하면 콜론 제거)과 달라져 거짓 발화가 났다.
    """
    n = normalize_label(label_raw)
    keys = {n}
    if ">" in n:
        keys.update(normalize_label(part) for part in n.split(">") if part.strip())
    keys.discard("")
    return keys


def find_missing_rows(file_path: str | Path, lines) -> list[MissingRow]:
    """원문 본문표의 '금액 있는 행' 중 `lines` 에 라벨이 없는 것.

    `lines` = `extract_report_lines()` 결과(=파서가 지금 뽑아낸 것). ★DB 를 읽어
    비교하면 안 된다 — 이미 검토된 건의 DB 는 옛 코드로 적재된 것이고,
    `store_report_lines()` 의 `col_index=0` 필터(BS/IS/CF)까지 걸려 있어 둘 다
    "결측"으로 오인된다(실측: DB 비교 시 발화 13/14건 → 추출 비교 시 5/40건).
    """
    from fin2.extract.text import (_detect_body_statement_tables,
                                   _detect_fin_type)

    path = Path(file_path)
    root = _parse_xml_file(path)
    if root is None:
        return []
    fin_type = _detect_fin_type(root, file_path=path)
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)

    loaded: dict[tuple[str, str], set[str]] = {}
    # 라벨 → 적재된 **당기 값**들. 적재 위치를 값으로 되찾기 위해 쓴다
    # (`_loaded_value_positions` docstring).
    values_by_label: dict[tuple[str, str], dict[str, set[int]]] = {}
    for line in lines:
        scope = (line.basis, line.statement)
        keys = loaded_label_keys(line.label_raw)
        loaded.setdefault(scope, set()).update(keys)
        if line.col_index == 0 and line.value_won is not None:
            bucket = values_by_label.setdefault(scope, {})
            for k in keys:
                bucket.setdefault(k, set()).add(abs(line.value_won))

    out: list[MissingRow] = []
    for code, tables in groups.items():
        meta = _SECTION_META.get(code)
        if meta is None:
            continue
        basis, statement = meta
        known = loaded.get((basis, statement), set())
        by_value = values_by_label.get((basis, statement), {})
        for (tbl, *_rest) in tables:
            rows_cells = [[" ".join("".join(td.itertext()).split()) for td in tr]
                          for tr in tbl.findall(".//TR")]
            positions = _loaded_value_positions(rows_cells, by_value)
            if not positions:
                # 그 표에서 적재된 행이 하나도 없다 = 표 단위 문제다 →
                # `orphan_tables` 의 영역이므로 행 단위로 중복 신고하지 않는다.
                continue
            for cells in rows_cells:
                if not cells:
                    continue
                label = normalize_label(cells[0])
                # 라벨 자리가 비었거나 표 머리행이거나 숫자면 데이터 행이 아니다.
                if not label or label in _HEADER_LABELS or _LOOSE_NUM.match(cells[0].strip()):
                    continue
                if label in known:
                    continue
                # ★적재된 행들이 쓰는 위치 **중 하나**에 값이 있을 때만 결측으로 본다
                #   (위 `_loaded_value_positions` docstring).
                #
                # ★"집합의 최솟값(=당기 열)만 인정" 으로 좁히는 안을 실측으로 기각했다
                #   (2026-09-20): 거짓양성은 0 이 되지만 **진짜 결함까지 놓친다** —
                #   코리안리 20150515002691 의 3행압축 결측이 사라지고, R149 EPS 검출도
                #   3행 → 1행으로 줄었다(같은 표 안에서 행마다 당기 값의 물리 위치가
                #   다르기 때문에 당기 값이 최솟값 위치에 없는 행이 흔하다).
                #   이건 선별 도구이고 발화분은 사람이 원문을 덤프해 확인하므로,
                #   **재현율을 지키고 남는 거짓양성 1계열은 문서로 알린다**(모듈 docstring
                #   "남은 거짓양성" 참고).
                idx = _first_number_index(cells)
                if idx is None or idx not in positions:
                    continue
                amounts = tuple(c for c in cells[1:] if _looks_like_amount(c))
                out.append(MissingRow(basis=basis, statement=statement,
                                      label=cells[0].strip()[:60], amounts=amounts[:3]))
    return out


_SCOPE = "전체(원문 행 적재여부)"


def scan(file_path: str | Path | None, lines) -> tuple[list[MissingRow], CheckResult]:
    """한 번만 훑어 **(결측행 목록, 검산결과)** 를 같이 돌려준다.

    ★검산과 검토 CSV 가 반드시 **같은 목록**을 봐야 한다 — 검산은 "3개 있다"고 하는데
      CSV 엔 다른 게 실리면 검토자가 무엇을 믿을지 알 수 없다. 그래서 호출부가 두 번
      훑지 않도록 여기서 한 번에 준다.
    """
    if not file_path:
        return [], CheckResult(code=CODE, scope=_SCOPE, grade=GRADE_INFO, verdict=NA,
                               message="원문 경로를 알 수 없어 확인하지 않음")
    try:
        missing = find_missing_rows(file_path, lines)
    except Exception as exc:                  # 감사 실패가 재적재를 막으면 안 된다
        return [], CheckResult(code=CODE, scope=_SCOPE, grade=GRADE_INFO, verdict=NA,
                               message=f"확인 실패: {type(exc).__name__}: {exc}")
    if not missing:
        return [], CheckResult(code=CODE, scope=_SCOPE, grade=GRADE_INFO, verdict=PASS,
                               message="원문 본문표의 금액 있는 행이 전부 적재됨")
    head = missing[0]
    where = ", ".join(sorted({f"{m.basis[:3]}/{m.statement}" for m in missing}))
    return missing, CheckResult(
        code=CODE, scope=_SCOPE, grade=GRADE_INFO, verdict=FAIL,
        message=(f"원문에 있는데 적재 안 된 행 {len(missing)}개({where}) — "
                 f"예: [{head.basis[:3]}/{head.statement}] {head.label!r} "
                 f"{list(head.amounts)}. 검토 CSV 끝의 '★원문만' 블록에 전부 실렸다."))


def check(file_path: str | Path | None, lines) -> CheckResult:
    """검산 1건만 필요할 때. **차단 등급이 아니다**(위 docstring 마지막 단락)."""
    return scan(file_path, lines)[1]
