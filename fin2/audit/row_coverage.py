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

## 당기 열만 본다 — 초판의 체계적 거짓양성 (2026-09-20 같은 날 수정)

초판은 "금액칸이 있는데 적재 안 된 행"을 전부 올렸다가 **정상 동작을 결함으로 신고**했다.
BS 는 설계상 당기(`col_index=0`)만 적재하므로(`_PERIOD_AXIS_STATEMENTS` 정책), 당기가
공란이고 전기에만 값이 있는 행은 적재될 것이 애초에 없다:
· 고려아연 20220816001335 `['장기파생상품금융부채', '', '1,928,974,207']` —
  당기(2022-06-30)엔 그 부채가 없다.
· NAVER 20180515002682 `['유동매도가능금융자산 (주5,16)', '', '79,435,727,110']` —
  IFRS 9 이 2018-01-01 시행돼 그 계정 자체가 당기부터 사라졌다.
둘 다 원문이 당기를 비워둔 것이고 파서는 옳게 동작했다. → `_current_period_index()` 로
**당기 칸에 값이 있는 행만** 대상으로 삼는다(그 docstring 에 열 위치 판정 근거).

## 실측 (2026-09-20)

· 검출력 — R149 수정만 끈 상태(=EPS 결측 재현)에서 신한지주 20220516002487 의
  EPS 3행([연결] 기본·희석주당순이익, [별도] 기본 및 희석주당이익)을 정확히 적출.
  수정 적용 상태에서는 0건. 위 두 거짓양성 사례도 수정 후 0건.
· 발화율 — 시총순 회사별 1건씩 80건(최신 40 + 최고령 40)에서 발화 2건(2.5%).

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
    """그 행에서 **처음으로 숫자인 칸**의 위치(라벨칸 0 은 제외). 없으면 None."""
    for i, c in enumerate(cells):
        if i == 0:
            continue
        if _LOOSE_NUM.match(c):
            return i
    return None


def _current_period_index(rows_cells: list[list[str]]) -> int | None:
    """표의 **당기 열 위치**를 행들의 다수결로 정한다.

    ★왜 필요한가(2026-09-20, 초판의 체계적 거짓양성 수정) — BS 는 설계상 당기
      (`col_index=0`)만 적재한다(`_PERIOD_AXIS_STATEMENTS` 정책). 그래서 **당기가
      공란이고 전기에만 값이 있는 행**은 적재될 것이 애초에 없다. 초판은 이걸
      "결측"으로 올려 정상 동작을 결함으로 신고했다:
        · 고려아연 20220816001335 `['장기파생상품금융부채', '', '1,928,974,207']`
          — 당기(2022-06-30)엔 그 부채가 없다.
        · NAVER 20180515002682 `['유동매도가능금융자산 (주5,16)', '', '79,435,727,110']`
          — IFRS 9 이 2018-01-01 시행돼 그 계정 자체가 당기부터 사라졌다.
      둘 다 원문이 당기를 비워둔 것이고 파서는 옳게 동작했다.
    ★그래서 "당기 칸에 숫자가 있는 행"만 대상으로 삼는다. 열 위치는 표마다 다르고
      (주석 열이 끼거나 값 사이에 빈 칸이 끼는 서식이 흔하다) 헤더 해석은 또 하나의
      추측이 되므로, **행들이 실제로 값을 넣은 위치의 최빈값**으로 정한다.
      실측: 신한지주 EPS 표는 값 사이에 빈 칸이 끼어 당기 열이 index 2 인데, 이
      방식이면 EPS 행도 그대로 잡힌다(R149 재검출 확인).
    """
    counts: dict[int, int] = {}
    for cells in rows_cells:
        idx = _first_number_index(cells)
        if idx is not None:
            counts[idx] = counts.get(idx, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]


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
    전체와 각 조각을 모두 후보로 둔다."""
    n = normalize_label(label_raw)
    keys = {n}
    if ">" in n:
        keys.update(part for part in n.split(">") if part)
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
    for line in lines:
        loaded.setdefault((line.basis, line.statement), set()).update(
            loaded_label_keys(line.label_raw))

    out: list[MissingRow] = []
    for code, tables in groups.items():
        meta = _SECTION_META.get(code)
        if meta is None:
            continue
        basis, statement = meta
        known = loaded.get((basis, statement), set())
        for (tbl, *_rest) in tables:
            rows_cells = [[" ".join("".join(td.itertext()).split()) for td in tr]
                          for tr in tbl.findall(".//TR")]
            current = _current_period_index(rows_cells)
            if current is None:
                continue
            for cells in rows_cells:
                if not cells:
                    continue
                label = normalize_label(cells[0])
                # 라벨 자리가 비었거나 표 머리행이거나 숫자면 데이터 행이 아니다.
                if not label or label in _HEADER_LABELS or _LOOSE_NUM.match(cells[0].strip()):
                    continue
                # ★당기 칸에 값이 있는 행만 본다(위 `_current_period_index` docstring).
                if current >= len(cells) or not _LOOSE_NUM.match(cells[current]):
                    continue
                if label in known:
                    continue
                amounts = tuple(c for c in cells[1:] if _LOOSE_NUM.match(c))
                out.append(MissingRow(basis=basis, statement=statement,
                                      label=cells[0].strip()[:60], amounts=amounts[:3]))
    return out


def check(file_path: str | Path | None, lines) -> CheckResult:
    """검산 1건으로 포장. **차단 등급이 아니다**(위 docstring 마지막 단락)."""
    scope = "전체(원문 행 적재여부)"
    if not file_path:
        return CheckResult(code=CODE, scope=scope, grade=GRADE_INFO, verdict=NA,
                           message="원문 경로를 알 수 없어 확인하지 않음")
    try:
        missing = find_missing_rows(file_path, lines)
    except Exception as exc:                  # 감사 실패가 재적재를 막으면 안 된다
        return CheckResult(code=CODE, scope=scope, grade=GRADE_INFO, verdict=NA,
                           message=f"확인 실패: {type(exc).__name__}: {exc}")
    if not missing:
        return CheckResult(code=CODE, scope=scope, grade=GRADE_INFO, verdict=PASS,
                           message="원문 본문표의 금액 있는 행이 전부 적재됨")
    head = missing[0]
    where = ", ".join(sorted({f"{m.basis[:3]}/{m.statement}" for m in missing}))
    return CheckResult(
        code=CODE, scope=scope, grade=GRADE_INFO, verdict=FAIL,
        message=(f"원문에 있는데 적재 안 된 행 {len(missing)}개({where}) — "
                 f"예: [{head.basis[:3]}/{head.statement}] {head.label!r} "
                 f"{list(head.amounts)}. 원문↔적재 결측이면 fail 로 보고할 것."))
