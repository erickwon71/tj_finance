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

## 실측 (2026-09-20)

정규화 후 발화 5/40건. 표본에서 확인한 발화분은 **거짓양성이 아니라 실제 결측**이었다:
· 고려아연 20220816001335 — 원문 [연결] BS 에 파생상품 행 4개, 적재 3개.
  `'장기파생상품금융부채'` 1,928,974,207 유실.
· NAVER 20180515002682 — `'유동매도가능금융자산'` 79,435,727,110 ·
  `'비유동매도가능금융자산'` 943,632,439,930 이 [연결] BS 에서 통째로 빠졌다.
공통 모양 = **금액칸이 1개뿐인(다른 행보다 짧은) 행**. 별도 결함으로 조사 필요.

그래서 이 검산은 **차단하지 않는다**(`GRADE_INFO`) — 발화분이 대체로 진짜라서 차단하면
캠페인이 통째로 멈춘다. 가시화·기록만 하고, 실제 처리는 전수 센서스로 모아서 한다.
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
            for tr in tbl.findall(".//TR"):
                cells = [" ".join("".join(td.itertext()).split()) for td in tr]
                if not cells:
                    continue
                label = normalize_label(cells[0])
                # 라벨 자리가 비었거나 표 머리행이거나 숫자면 데이터 행이 아니다.
                if not label or label in _HEADER_LABELS or _LOOSE_NUM.match(cells[0].strip()):
                    continue
                amounts = tuple(c for c in cells[1:] if _LOOSE_NUM.match(c))
                if not amounts or label in known:
                    continue
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
