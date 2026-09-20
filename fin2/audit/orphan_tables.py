"""본문 재무제표 섹션에 있는데 **어느 재무제표에도 귀속되지 않은 금액표** 탐지.

## 왜 필요한가 — 캠페인이 구조적으로 못 보는 것

계층2 원문대조 캠페인은 "적재된 값이 원문과 맞는가"는 본다. 그러나 **"원문에 있는데
적재되지 않은 표"** 는 구조적으로 못 본다: 검토 CSV 도, `pass --verified-scopes`
체크리스트도 전부 **적재 결과(DB)에서** 만들어지기 때문이다. 감사 대상이 감사 범위를
스스로 정하는 셈이라, 표가 통째로 유실되는 결함은 사람이 DART 원문을 끝까지 읽지 않는
한 드러나지 않는다 — 실제로 R148(신한지주 SCE 당기 롤포워드 유실)은 캠페인이 같은
결함을 7번 재발견하는 동안 한 번도 자동으로 잡히지 않았다. R141(KB금융 연결 손익계산서
전체 유실)도 같은 모양이다.

이 탐지기는 방향을 뒤집는다 — **원문 쪽에서** 센다. 본문 섹션(`2.연결재무제표` /
`4.재무제표`)에 있는 금액표 중 파서가 어느 재무제표에도 붙이지 못한 것을 지목한다.
파서의 표 귀속 로직이 틀렸을 때 그 결과물(DB)을 아무리 들여다봐도 안 보이던 신호가,
원문 표 목록과 귀속 결과를 맞대면 바로 드러난다.

## 실측 (2026-09-20)

· **결함 적출력** — R148 규칙(`_looks_like_equity_changes_header` 기반 SCE 연속표
  연결)만 끈 상태(=수정 전 재현)로 신한지주 4건(20220316000748·20190401004307·
  20211115002302·20210317001127)을 돌리면 **전부 2건씩**(연결·별도 당기 롤포워드 SCE
  표) 적출된다. 현재 HEAD(R148 적용)에서는 같은 4건이 전부 0건. 즉 이 탐지기가 있었다면
  R148 은 첫 건에서 잡혔다.
· **거짓양성** — 시총순 회사별 pending 1건씩 160건(최신 80 + 최고령 80) 측정: 발화
  1건(0.6%). 그 1건도 데이터 유실이 아니라 아래 `_BENIGN` 의 은행 신탁계정이었다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_FS, SEC_SEP_FS,
                                         assign_tables_to_dart_sections,
                                         table_has_amount_rows)

from fin2.audit.layer2_selfcheck import (CheckResult, FAIL, GRADE_SUSPECT, NA,
                                         PASS)

CODE = "ORPHAN_BODY_TABLE"

# 본문 섹션에 있지만 4대 재무제표가 **아닌 것이 맞는** 표 — 적출해도 결함이 아니다.
# ★추가할 때는 반드시 "왜 재무제표가 아닌가"를 근거와 함께 적을 것. 여기에 넣는 순간
#   그 패턴은 영구히 안 보이게 되므로, "노이즈라서"가 아니라 "재무제표가 아니라서"만
#   사유가 된다.
_BENIGN: tuple[tuple[str, re.Pattern], ...] = (
    # 이익잉여금처분계산서·결손금처리계산서 — IFRS 4대 재무제표가 아니라서 분류기가
    # 이미 의도적으로 제외한다(`statement_titles._APPROPRIATION_RE` 와 같은 근거).
    # 표제가 빈 서식이 있어(두산에너빌리티 20240327001228) 표 본문 텍스트로도 본다.
    ("이익잉여금처분계산서/결손금처리계산서",
     re.compile(r"이익잉여금처분|결손금처리|미처분이익잉여금|처분예정일|처분확정일"
                r"|처리예정일|처리확정일")),
    # 은행 신탁계정 — 신탁재산은 고객 자산이라 은행 **자신의** 재무상태표에 인식되지
    # 않는다. DART 는 "(1) 은행계정 / (2) 신탁계정" 을 같은 표제 아래 나란히 싣지만
    # 은행 자체 재무제표는 (1) 이고, 파서가 (2) 를 안 붙이는 것은 결함이 아니다.
    # 실측: 기업은행 20150515002437 — 8개 scope 가 전부 정상 적재된 채 (2) 만 남았다.
    ("은행 신탁계정", re.compile(r"신탁계정")),
)

# 표제는 직전 형제 하나에 있다는 보장이 없다 — '(2) 신탁계정' 처럼 제목 형제와 데이터표
# 사이에 기간/단위만 든 형제가 끼는 서식이 흔하다(기업은행 실측). 몇 개 거슬러 올라가
# 문맥을 모은다.
_CONTEXT_SIBLINGS = 3


@dataclass(frozen=True)
class Orphan:
    basis: str          # 'consolidated' | 'separate'
    title: str          # 표 앞쪽 문맥(표제로 보이는 텍스트)
    preview: str        # 표 본문 앞부분 — 사람이 무슨 표인지 알아보기 위한 것


def _context_text(tbl) -> str:
    """표 자신 + 바로 앞 형제 몇 개의 텍스트(표제 판정용)."""
    parts: list[str] = []
    node = tbl.getprevious()
    for _ in range(_CONTEXT_SIBLINGS):
        if node is None:
            break
        parts.append(" ".join("".join(node.itertext()).split()))
        node = node.getprevious()
    parts.reverse()
    parts.append(" ".join("".join(tbl.itertext()).split())[:400])
    return " ".join(parts)


def _benign_reason(context: str) -> str | None:
    squished = re.sub(r"\s+", "", context)
    for name, pattern in _BENIGN:
        if pattern.search(squished):
            return name
    return None


def find_orphans(file_path: str | Path) -> list[Orphan]:
    """본문 섹션의 금액표 중 어느 재무제표에도 귀속되지 않은 것.

    ★`_detect_body_statement_tables` 를 **그대로** 다시 돌려 귀속 결과를 받는다 —
      파서와 다른 판정식을 새로 쓰면 그 판정식 자체가 또 하나의 추측이 된다. 여기서
      보는 것은 "파서가 무엇을 안 집었나"이지 "무엇이 옳은가"가 아니다.
    """
    # 순환 import 회피 — text 모듈은 이 패키지를 import 하지 않지만, 파서 내부 함수를
    # 감사 목적으로 쓰는 방향이므로 호출 시점에 가져온다.
    from fin2.extract.text import (_detect_body_statement_tables,
                                   _detect_fin_type)

    path = Path(file_path)
    root = _parse_xml_file(path)
    if root is None:
        return []
    fin_type = _detect_fin_type(root, file_path=path)
    sec_tables = assign_tables_to_dart_sections(root)
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    assigned = {id(t) for tables in groups.values() for (t, *_rest) in tables}

    out: list[Orphan] = []
    for sec_kind, basis in ((SEC_CONSOL_FS, "consolidated"), (SEC_SEP_FS, "separate")):
        for tbl in sec_tables.get(sec_kind, []):
            if id(tbl) in assigned or not table_has_amount_rows(tbl):
                continue
            context = _context_text(tbl)
            if _benign_reason(context) is not None:
                continue
            body = " ".join("".join(tbl.itertext()).split())
            out.append(Orphan(basis=basis, title=context[-160:], preview=body[:160]))
    return out


def check(file_path: str | Path | None) -> CheckResult:
    """검산 1건으로 포장 — `layer2_review.py` 가 다른 검산과 같이 저장/출력한다."""
    scope = "전체(원문 본문표 귀속)"
    if not file_path:
        return CheckResult(code=CODE, scope=scope, grade=GRADE_SUSPECT, verdict=NA,
                           message="원문 경로를 알 수 없어 확인하지 않음")
    try:
        orphans = find_orphans(file_path)
    except Exception as exc:                      # 감사 실패가 재적재를 막으면 안 된다
        return CheckResult(code=CODE, scope=scope, grade=GRADE_SUSPECT, verdict=NA,
                           message=f"확인 실패: {type(exc).__name__}: {exc}")
    if not orphans:
        return CheckResult(code=CODE, scope=scope, grade=GRADE_SUSPECT, verdict=PASS,
                           message="본문 섹션의 금액표가 전부 재무제표에 귀속됨")
    where = ", ".join(sorted({o.basis for o in orphans}))
    head = orphans[0]
    return CheckResult(
        code=CODE, scope=scope, grade=GRADE_SUSPECT, verdict=FAIL,
        message=(f"원문 본문표 {len(orphans)}개가 어느 재무제표에도 안 붙음({where}) — "
                 f"표가 통째로 유실되는 결함(R141/R148)과 같은 모양. "
                 f"첫 건: {head.preview[:90]!r}"))
