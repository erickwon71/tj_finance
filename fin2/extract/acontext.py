"""
ACONTEXT 구조 파서 (fin2 E-레이어의 핵심).

DART XBRL 의 TE 태그 ACONTEXT 속성을 **추론이 아닌 구조 파싱**으로 분해한다.
연결/별도·기간(연도/종류/instant·duration)·차원(축/멤버)을 권위있게 추출한다.

실측 포맷 (신흥에스이씨 2024 등):
    CFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember
    PFY2023eFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember
    CFY2024dFY_..._ConsolidatedMember_ifrs-full_ComponentsOfEquityAxis_ifrs-full_RetainedEarningsMember

구성: {prefix}[_{ns}_{Axis}_{ns}_{Member}]*
  prefix = (C|P|BP) FY{year} (d|e) F (Y|Q|H) (A?)
    - C/P/BP : 당기/전기/전전기  → col_index 0/1/2
    - FY{year}: 절대 회계연도
    - d|e     : duration(기간, IS·CF) | instant(시점, BS)   ← e/d 가 BS vs IS/CF 권위
    - Y|Q|H   : 연간/분기/반기
    - A       : 누적(cumulative_ytd)
  dimension = (axis, member) 쌍. ns ∈ {ifrs-full, dart}.

★ 현 파이프라인 버그(dart_xml_parser.py:495) 수정:
  `"Consolidated" in acontext` 는 축 이름 ConsolidatedAndSeparateFinancialStatementsAxis
  때문에 SeparateMember 컨텍스트까지 연결로 오분류한다. 여기서는 **멤버 토큰**
  (SeparateMember / ConsolidatedMember)으로만 판정한다.

  또한 ConsolidatedAndSeparate 축 외의 축(ComponentsOfEquityAxis 등)이 있으면
  SCE 내역 분해 행이므로 extra_dims 로 분리해 합계에서 제외할 수 있게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 연결/별도 판정을 담당하는 축
_CONSOL_AXIS = "ConsolidatedAndSeparateFinancialStatementsAxis"

# prefix: (C|P|BP) FY{4} (d|e) F (Y|Q|H) (A?)   — BP 를 P 보다 먼저 매칭
_PREFIX_RE = re.compile(
    r"^(?P<rel>BP|C|P)FY(?P<year>\d{4})(?P<kind>[de])F(?P<ptype>[YQH])(?P<accum>A?)"
)

# 차원 토큰: ns_Name 반복. ns = ifrs-full | dart. Name 은 다음 ns 직전까지.
_DIM_TOKEN_RE = re.compile(r"(?:ifrs-full|dart)_(?P<name>.+?)(?=_(?:ifrs-full|dart)_|$)")

_REL_TO_COL = {"C": 0, "P": 1, "BP": 2}


@dataclass
class AContext:
    """ACONTEXT 파싱 결과."""
    raw: str
    parsed: bool = False
    basis: str | None = None             # "consolidated" | "separate" | None(불명→파일 fin_type 폴백)
    rel: str | None = None               # "C" | "P" | "BP"
    col_index: int | None = None         # 0 | 1 | 2
    fiscal_year: int | None = None       # 절대 회계연도 (예: 2024)
    period_kind: str | None = None       # "instant"(BS) | "duration"(IS·CF)
    period_type: str | None = None       # "FY" | "FQ" | "FH"
    is_cumulative: bool = False          # FQA/FHA 누적
    extra_dims: list[tuple[str, str]] = field(default_factory=list)  # 연결/별도 축 외 (axis, member)

    @property
    def is_dimensional(self) -> bool:
        """연결/별도 외 차원(SCE 내역 등)을 가져 statement 합계에서 제외해야 하면 True."""
        return bool(self.extra_dims)


def _split_dims(remainder: str) -> list[tuple[str, str]]:
    """차원 구간 문자열 → [(axis, member), ...]. 축은 'Axis', 멤버는 'Member' 로 끝남."""
    names = [m.group("name") for m in _DIM_TOKEN_RE.finditer(remainder)]
    dims: list[tuple[str, str]] = []
    i = 0
    while i < len(names):
        name = names[i]
        if name.endswith("Axis"):
            member = names[i + 1] if i + 1 < len(names) and names[i + 1].endswith("Member") else ""
            dims.append((name, member))
            i += 2 if member else 1
        else:
            # 축 없이 등장한 멤버(비정형) — 차원 없이 단독 멤버로 기록
            dims.append(("", name))
            i += 1
    return dims


def parse_acontext(acontext: str | None) -> AContext:
    """ACONTEXT 문자열을 구조 파싱. 실패 시 parsed=False 로 반환(상위에서 폴백)."""
    raw = acontext or ""
    ctx = AContext(raw=raw)
    if not raw:
        return ctx

    m = _PREFIX_RE.match(raw)
    if not m:
        return ctx  # parsed=False — 미지원 포맷(구형 등). 상위에서 처리.

    ctx.parsed = True
    ctx.rel = m.group("rel")
    ctx.col_index = _REL_TO_COL[ctx.rel]
    ctx.fiscal_year = int(m.group("year"))
    ctx.period_kind = "instant" if m.group("kind") == "e" else "duration"
    ctx.period_type = "F" + m.group("ptype")          # FY / FQ / FH
    ctx.is_cumulative = bool(m.group("accum"))

    # prefix 이후가 차원 구간
    remainder = raw[m.end():]
    dims = _split_dims(remainder.lstrip("_")) if remainder else []

    for axis, member in dims:
        if axis == _CONSOL_AXIS:
            # ★ 멤버 토큰으로만 연결/별도 판정 (substring 'Consolidated' 금지)
            if member == "SeparateMember":
                ctx.basis = "separate"
            elif member == "ConsolidatedMember":
                ctx.basis = "consolidated"
        else:
            ctx.extra_dims.append((axis, member))

    return ctx
