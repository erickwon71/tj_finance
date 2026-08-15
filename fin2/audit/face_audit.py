"""
Gate B — 보고서 face 표 독립 재추출 + DB(std_v2) 100% 일치 감사.

이 모듈의 핵심 원칙(PRD 04):
  - **표준화 파이프라인과 독립**: reconcile(source 선택)·standardize(규칙) 를 거치지 않고
    원본 보고서의 face 표를 직접 다시 읽는다 → 같은 버그를 양쪽이 공유하지 않음.
  - **보고서 표시단위 정확 일치**: round(DB_amount_won × 10^ADECIMAL) == 보고서 표시값.
    Track A(XBRL) 는 ADECIMAL 권위라 won-공간에서 동치 비교가 정확하다. 단, 무차원(홈/합계)
    fact 가 문서에 **유일하게** 등장하고, 그와 어긋나는 ADECIMAL 을 가진 차원분해 fact 들을
    각자의 ADECIMAL 로 합산한 값이 **실제로 그 합계와 산술적으로 일치할 때만**(항등식,
    §8-A `_adecimal_signals` 참고) 그 ADECIMAL 로 override 한다 — "권위"는 파일 전체가
    아니라 **검증된 합산 항등식**이 이긴다("형제 태그가 서로 일치"만으로는 부족했다 — 회귀
    이력은 `_adecimal_signals` docstring 참고).
  - 감사 대상은 std_v2 의 **최종 소비값**(시각화에 쓰는 표준 계정). 이 값이 그 statement 의
    source 보고서 face 표에 **실제로 그 계정 부류로 등장**하는지 검증한다.

iteration 1 = Track A(xbrl_acode) 백엔드. Track B(xml_text) 백엔드는 후속.

숫자 파싱은 추출기(parse_amount)를 재사용하지 않고 본 모듈 자체의 리터럴 파서를 쓴다
(독립성 — 추출기의 숫자/단위 버그를 감사가 공유하지 않도록).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from parser.xml.dart_xml_parser import _parse_xml_file
from fin2.extract.acontext import parse_acontext
from fin2.taxonomy.concept_map import map_acode

_XBRL_PREFIXES = ("ifrs-full_", "dart_")

# std_v2 표준 필드 → canonical 계정 (앵커/고신뢰 셋 우선).
# basis(statement_type) 와 무관하게 계정 부류 일치만 본다.
STD_FIELD_CANONICAL: dict[str, str] = {
    # ── BS ──
    "total_assets": "bs.total_assets",
    "current_assets": "bs.current_assets",
    "cash": "bs.cash",
    "inventory": "bs.inventory",
    "ppe": "bs.ppe",
    "total_liabilities": "bs.total_liabilities",
    "current_liabilities": "bs.current_liabilities",
    "total_equity": "bs.total_equity",
    "controlling_equity": "bs.controlling_equity",
    "retained_earnings": "bs.retained_earnings",
    "trade_payables": "bs.trade_payables",
    # ── IS ──
    "revenue": "is.revenue",
    "cogs": "is.cogs",
    "gross_profit": "is.gross_profit",
    "operating_income": "is.operating_income",
    "ebt": "is.ebt",
    "tax_expense": "is.tax_expense",
    "net_income": "is.net_income",
    "controlling_ni": "is.controlling_ni",
    # ── CF ──
    "cfo": "cf.operating",
    "cfi": "cf.investing",
    "cff": "cf.financing",
    "capex": "cf.capex",
    "dividends_paid": "cf.dividends_paid",
}

# 앵커(가장 중요·라벨↔계정 모호성 없음) — 감사를 먼저 신뢰가능하게 채우는 부분집합.
ANCHOR_FIELDS = (
    "total_assets", "total_liabilities", "total_equity",
    "revenue", "operating_income", "net_income",
    "cfo", "cfi", "cff",
)

# DIRECT = 단일 보고서 face 라인에 1:1 대응(strict 100% 일치 대상).
# 제외:
#  - 합성 필드(capex=cf.capex+cf.capex_intangible 등) → 단일 라인 아님, 자기일관성으로 별도 검증.
#  - controlling_*(지배지분) → 별도(separate) 재무제표엔 지배/비지배 구분 없어 face 라인 부재
#    (std 는 net_income/total_equity 동일값으로 채움) → CONSOLIDATED 에서만 face 라인 존재.
DIRECT_FIELDS = tuple(
    f for f in STD_FIELD_CANONICAL if f not in ("capex",)
)
# 연결에서만 face 라인이 존재하는 지배지분 필드.
_CONSOLIDATED_ONLY = ("controlling_equity", "controlling_ni")

# canonical 접두어 → statement(BS/IS/CF)
def _statement_of(canonical: str | None) -> str | None:
    if not canonical:
        return None
    if canonical.startswith("bs."):
        return "BS"
    if canonical.startswith("is."):
        return "IS"
    if canonical.startswith("cf."):
        return "CF"
    return None


@dataclass
class FaceLine:
    """보고서 face 표의 한 라인(독립 재추출 산출). col_index=0(당기)만 수집."""
    statement: str | None      # BS/IS/CF (canonical 기준; 미매핑은 period_kind 추정)
    basis: str | None          # consolidated/separate/None
    acode: str
    canonical: str | None
    label: str
    displayed_value: int       # 보고서 표시값(단위 미환산, 리터럴)
    adecimal: int | None       # 표시단위(원 환산용)
    is_cumulative: bool = False  # 반기/3분기 누적(YTD) 셀 — std_v2 IS/CF 가 저장하는 값
    from_gapfill: bool = False   # 표제기반 실패→detect_sections 갭필로 찾은 표(휴리스틱, 저신뢰)

    @property
    def amount_won(self) -> int | None:
        """표시값 → 원. amount_won = 표시값 × 10^(-adecimal)."""
        if self.adecimal is None:
            return self.displayed_value
        if self.adecimal < 0:
            return self.displayed_value * (10 ** (-self.adecimal))
        return self.displayed_value  # adecimal>=0: 표시값이 이미 원(반올림 자리)


_NUM_RE = re.compile(r"[0-9][0-9,  ]*\.?[0-9]*")
_NEG_MARK = ("△", "▲", "▵", "−", "-", "(")


def parse_displayed(text: str) -> int | None:
    """
    보고서 셀 텍스트 → 표시 정수값(리터럴, 단위 미환산). 추출기와 독립한 자체 파서.
    음수: 괄호 (1,234) / △ / − / 선행 '-'. 소수는 반올림. 비수치/공란 None.
    """
    if not text:
        return None
    t = text.strip().replace(" ", " ")
    if not t:
        return None
    neg = t.startswith("(") and t.rstrip().endswith(")")
    if not neg and t[:1] in ("△", "▲", "▵", "−", "-"):
        neg = True
    m = _NUM_RE.search(t)
    if not m:
        return None
    digits = m.group(0).replace(",", "").replace(" ", "")
    if not digits or digits == ".":
        return None
    try:
        val = float(digits)
    except (ValueError, OverflowError):
        return None
    import math
    if not math.isfinite(val):   # 비정상 셀(자릿수 과다 → inf) 방어
        return None
    iv = int(round(val))
    return -iv if neg else iv


def _cell_text(te) -> str:
    raw = (te.text or "").strip()
    if not raw:
        p = te.find("P")
        if p is not None:
            raw = (p.text or "").strip()
    if not raw:
        raw = "".join(te.itertext()).strip()
    return raw


def _parse_adecimal(te) -> int | None:
    try:
        return int(te.get("ADECIMAL", ""))
    except (ValueError, TypeError):
        return None


def _amount_won(displayed: int, adecimal: int | None) -> int:
    if adecimal is not None and adecimal < 0:
        return displayed * (10 ** (-adecimal))
    return displayed


def _adecimal_signals(root) -> tuple[dict[tuple, int], set[tuple]]:
    """(acode, basis, col_index, is_cumulative) 키 단위로 두 신호를 한 번의 순회로 모은다:

      1. verified_adecimal — 차원분해(멤버) fact 들이 **같은 축(axis) 아래 실제로 그 무차원
         합계에 더해져서 일치하는지(항등식)** 검증된 ADECIMAL 만 담는다.
      2. ambiguous_home — 무차원(홈) fact 가 **같은 키로 2개 이상, 서로 다른 값으로** 등장한
         키의 집합(override 를 아예 하지 말아야 할 키 — 아래 참고).

    ★2026-08-12(§8-A, docs/plans/std_v3_native_gate_b_plan_2026-08-11.md Phase3-부록) —
    노루페인트(00583442) 등 실측(trade_payables·inventory)으로 확정된 DART 렌더러 결함:
    같은 acode 의 **무차원(홈/합계) fact** 가 ADECIMAL=0(원 단위)으로 잘못 태깅되는 반면,
    바로 옆 **차원분해**(카테고리 등 멤버) fact 들은 정확한 배율(예: -3=천원)을 갖는다 —
    표시 리터럴은 둘 다 같고 배율 태그만 다르다.

    ★★2026-08-12 회귀 #1+수정 — "형제가 ADECIMAL 에 만장일치"만으로 신뢰했던 최초 구현은
    00583442 cash 를 111,779,270,286원(정답)에서 ×1000 으로 **망가뜨렸다**. 원인: 같은
    acode+context 가 문서 안에서 본문 재무상태표 표(전체정밀도)와 주석표(천원 반올림, 오태깅)
    에 각각 **무차원**으로 중복 등장 — dedup 은 정답(본문표)을 골랐는데 형제 맵은 acode 만
    보고 주석표 쪽 형제를 끌어와 덮어썼다. → 무차원 fact 가 같은 키로 서로 다른 값으로
    2번 이상 나오면(ambiguous_home) override 후보에서 제외.

    ★★★2026-08-12 회귀 #2+재수정 — ambiguous_home 가드를 더해도 00146861 cash 등에서
    **또** 망가졌다: 이번엔 무차원 fact 는 유일(문서에 1번뿐)했지만, "차원분해 형제"라고
    믿은 fact 들이 사실은 이 합계의 **구성요소가 아니라** 전혀 무관한 다른 주석(예: 공정가치
    서열 주석이 우연히 같은 acode+ACONTEXT 접두를 재사용)이었다 — "형제 ADECIMAL 만장일치"
    는 그 fact 들이 진짜 합계-구성요소 관계인지는 전혀 증명하지 못한다. **그래서 신뢰
    기준을 "태그 일치"에서 "산술 항등식"으로 바꾼다**: 같은 축(axis) 이름 조합을 공유하는
    차원분해 fact 들을 모아 **각자 자신의 ADECIMAL 로 원화 환산해 합산**했을 때, 그 합이
    무차원 합계를 **어떤 후보 ADECIMAL 로 환산한 값과 실제로 일치**할 때만 그 ADECIMAL 을
    신뢰한다(허용오차: 그 자리수 1단위, 발행사 반올림 관용). 구성요소가 2개 미만이면(=진짜
    분해가 아니라 단일 재태깅일 수 있음) 증거 부족으로 보류. 같은 (축조합,멤버조합) 이
    서로 다른 값으로 중복 등장하면(=00146861 cash 처럼 무관한 fact 재사용 신호) 그 멤버는
    폐기한다 — 짐작 금지, [[feedback-verify-against-source]].
    """
    dims_by_key: dict[tuple, dict[tuple, set]] = {}
    home_groups: dict[tuple, set[tuple]] = {}
    for te in root.findall(".//TE[@ACODE]"):
        acode = te.get("ACODE", "")
        if not acode.startswith(_XBRL_PREFIXES) or len(acode) > 255:
            continue
        ctx = parse_acontext(te.get("ACONTEXT", ""))
        if not ctx.parsed:
            continue
        key = (acode, ctx.basis, ctx.col_index, ctx.is_cumulative)
        displayed = parse_displayed(_cell_text(te))
        if displayed is None:
            continue
        if ctx.is_dimensional:
            edims = tuple(ctx.extra_dims)
            dims_by_key.setdefault(key, {}).setdefault(edims, set()).add(
                (displayed, _parse_adecimal(te)))
        else:
            home_groups.setdefault(key, set()).add((displayed, _parse_adecimal(te)))

    ambiguous_home = {k for k, v in home_groups.items() if len(v) > 1}

    verified_adecimal: dict[tuple, int] = {}
    for key, home_vals in home_groups.items():
        if key in ambiguous_home:
            continue
        (home_disp, home_ade), = home_vals
        by_axis_sig: dict[tuple, list[tuple[int, int | None]]] = {}
        for edims, vals in dims_by_key.get(key, {}).items():
            if len(vals) != 1:
                continue   # 같은 멤버조합이 서로 다른 값으로 중복 등장 → 이 멤버 자체가 불신
            axis_sig = tuple(a for a, _m in edims)
            by_axis_sig.setdefault(axis_sig, []).append(next(iter(vals)))
        for member_vals in by_axis_sig.values():
            if len(member_vals) < 2:
                continue   # 구성요소 2개 미만 = 합산 항등식으로 검증할 증거 부족
            adecimals = {a for _d, a in member_vals}
            if any(a is None for a in adecimals):
                continue
            total_won = sum(_amount_won(d, a) for d, a in member_vals)
            for cand in adecimals:
                if cand == home_ade:
                    continue
                cand_won = _amount_won(home_disp, cand)
                tol = max(1, 10 ** max(0, -cand))
                if abs(cand_won - total_won) <= tol:
                    verified_adecimal[key] = cand
                    break
            if key in verified_adecimal:
                break
    return verified_adecimal, ambiguous_home


def read_report_face_xbrl(file_path: str | Path, all_cols: bool = False) -> list[FaceLine]:
    """
    Track A(XBRL) 보고서의 face 라인을 독립 재추출. 기본 col_index=0(당기)·비차원만.

    all_cols=True: col_index 0/1/2(당기·전기·전전기) 모두 포함 — 비교컬럼 폴백 행 검증용
    (그 행 값은 후속 보고서의 전기/전전기 컬럼에 있으므로 col0 만으론 대조 불가).
    Track A 가 아니면(=ifrs/dart ACODE+ACONTEXT 셀 없음) 빈 리스트.

    ADECIMAL 은 원칙상 권위(모듈 docstring)지만, **무차원 합계 fact 가 문서에 유일하게(=같은
    값으로만) 등장하고, 그 값과 어긋나는 ADECIMAL 을 가진 차원분해 fact 들이 실제로 그
    합계에 산술적으로 더해져 일치할 때만**(항등식 검증, `_adecimal_signals`) 그 ADECIMAL 로
    override 한다 — 태그가 서로 "일치"하는 것만으론 부족하다(회귀 #2, 함수 docstring 참고).
    무차원 fact 가 같은 키로 **서로 다른 값**으로 여러 번 나오면(본문표/주석표 중복 재사용
    신호, 회귀 #1) 그 키는 애초에 후보에서 제외한다. 그래도 남는 빈 ADECIMAL(진짜 미태깅)만
    문서 전체 기본단위(R4-1, `document_default_unit`)로 최후 보충한다.
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []

    verified_adecimal, _ambiguous_home = _adecimal_signals(root)
    _doc_default_cache: list[tuple] = []   # lazy, at most 1 회 계산(못 찾을 파일에서 재스캔 방지)

    def _doc_default() -> tuple:
        if not _doc_default_cache:
            from fin2.extract.text import document_default_unit
            _doc_default_cache.append(document_default_unit(root))
        return _doc_default_cache[0]

    dedup: dict[tuple, FaceLine] = {}
    for te in root.findall(".//TE[@ACODE]"):
        acode = te.get("ACODE", "")
        if not acode.startswith(_XBRL_PREFIXES) or len(acode) > 255:
            continue
        acontext = te.get("ACONTEXT", "")
        if not acontext:
            continue
        ctx = parse_acontext(acontext)
        if not ctx.parsed or ctx.is_dimensional:
            continue
        if not all_cols and ctx.col_index != 0:
            continue
        text = _cell_text(te)
        displayed = parse_displayed(text)
        if displayed is None:
            continue
        adecimal = _parse_adecimal(te)
        key = (acode, ctx.basis, ctx.col_index, ctx.is_cumulative)
        verified = verified_adecimal.get(key)   # already excludes ambiguous_home keys
        if verified is not None and verified != adecimal:
            adecimal = verified
        elif adecimal is None:
            unit, _decl = _doc_default()
            if unit is not None:
                adecimal = _adecimal_from_unit(unit)
        canonical = map_acode(acode)
        stmt = _statement_of(canonical)
        if stmt is None and ctx.period_kind == "instant":
            stmt = "BS"
        line = FaceLine(
            statement=stmt, basis=ctx.basis, acode=acode, canonical=canonical,
            label=text[:80], displayed_value=displayed, adecimal=adecimal,
            is_cumulative=ctx.is_cumulative,
        )
        # 반기/3분기는 같은 (acode,basis)에 누적·3개월 셀이 공존 → is_cumulative 도 키에 포함.
        # all_cols 시 col_index 도 키에 포함(전기/전전기 셀 보존).
        key = (acode, ctx.basis, ctx.is_cumulative, ctx.col_index if all_cols else 0)
        if key not in dedup:
            dedup[key] = line
    return list(dedup.values())


_HANGUL_RE = re.compile(r"[가-힣]")

# 텍스트 섹션코드 → (basis, statement)
_TEXT_SECTION_META = {
    "BS_C": ("consolidated", "BS"), "IS_C": ("consolidated", "IS"), "CF_C": ("consolidated", "CF"),
    "BS_S": ("separate", "BS"), "IS_S": ("separate", "IS"), "CF_S": ("separate", "CF"),
}


def _adecimal_from_unit(unit: int) -> int:
    """단위 배수 → ADECIMAL. 1→0, 1000→-3, 1000000→-6."""
    import math
    if unit <= 1:
        return 0
    return -int(round(math.log10(unit)))


def read_report_face_text(file_path: str | Path) -> list[FaceLine]:
    """
    Track B(텍스트) 보고서의 **본문 재무제표 face 표** 라인을 독립 재추출.

    표 위치·basis(연결/별도) 식별 = 추출기(`fin2.extract.text._detect_body_statement_tables`)와
    **공유**(2026-08-07 수정). 예전엔 이 함수가 독자적으로 "전체 TABLE 스캔 +
    `classify_statement_title(title_text(tbl))`"(표제=데이터표의 **직전 형제 1개**만 봄)를 1차로
    쓰고, 실패하면 `section_detector.detect_sections/find_section_tables`(복잡문서에서 주석·조정표를
    오연결하는 것으로 이미 알려진 legacy 함수) 로 폴백했다. 재무제표명(TITLE)과 기간·단위 표가
    **서로 다른 두 형제 노드**로 분리된 서식(예: `<TITLE>재무상태표</TITLE>` 다음에 별도
    "(단위:원)" 표)에서 표제 텍스트에 재무제표명 토큰 자체가 안 잡혀 1차가 통째로 실패 →
    legacy 폴백이 연결 표 값을 별도 basis 로 오귀속(또는 아예 못 찾음)해 Gate B 가 **오탐
    value_diff** 를 냈다(실측 2023-11 제출 3분기보고서 10개사 479건 — DB 값은 원문과 정확히
    일치했고 감사기만 틀렸다).
    `_detect_body_statement_tables` 는 DART 챕터 섹션(`2.연결재무제표`/`4.재무제표`) 을
    basis 의 권위 있는 근거로 삼아(표제 텍스트의 "연결" 유무에 의존하지 않음) 2026-07-17 재설계
    이후 이 문제 부류를 이미 해결했다 — 감사기가 구버전에 머물러 있었을 뿐이다.

    독립성(유지): 표 **위치**는 추출기와 공유하되, 셀은 table_extractor 컬럼로직 비재사용하고
    **행 내 모든 숫자 셀 리터럴** 읽기(any-column). is_cumulative=True 로 interim 필터 통과.
    요약재무정보표·주석표는 제외(본문만, `_detect_body_statement_tables` 가 이미 보장).
    """
    from parser.xml.table_extractor import _get_cells
    from parser.common.account_mapper import get_mapper
    from fin2.extract.text import declared_unit, _detect_body_statement_tables, _detect_fin_type

    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []
    mapper = get_mapper()
    lines: list[FaceLine] = []
    seen: set[tuple] = set()

    def _read_table(tbl, basis, stmt, unit, from_gapfill=False):
        fs_section = stmt.lower()
        adecimal = _adecimal_from_unit(unit or 1)
        for tr in tbl.findall(".//TR"):
            cells = _get_cells(tr)
            label = None
            nums: list[int] = []
            for cell in cells:
                if label is None and _HANGUL_RE.search(cell):
                    label = cell.strip()
                    continue
                if label is None:
                    continue
                v = parse_displayed(cell)
                if v is not None:
                    nums.append(v)
            if not label or not nums:
                continue
            mapping = mapper.map(label, fs_section=fs_section)
            canon = mapping.account_code
            if not canon or canon.startswith("unknown."):
                continue
            if _statement_of(canon) != stmt:
                continue
            if canon == "is.tax_expense" and "차감전" in label:
                continue  # 세전이익 오매핑 가드
            for v in nums:
                # ★ dedup 키는 표시값(v)이 아니라 won 환산값으로(단위만 다른 중복표가 표시값 같아도
                # won 다름 → 잘못된 단위표가 올바른 표 가리는 ×10^6 false-fail 방지, 아이티센씨티에스).
                won = v * (10 ** (-adecimal)) if adecimal < 0 else v
                key = (canon, basis, won)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(FaceLine(
                    statement=stmt, basis=basis, acode=label[:80], canonical=canon,
                    label=label[:80], displayed_value=v, adecimal=adecimal,
                    is_cumulative=True, from_gapfill=from_gapfill,
                ))

    # ── DART 섹션 기반 본문표 식별 (추출기와 공유, 단일 진실원) ──
    fin_type = _detect_fin_type(root)
    groups = _detect_body_statement_tables(root, fin_type)
    for section_code, tables_with_unit in groups.items():
        stmt = section_code.split("_")[0]
        if stmt not in ("BS", "IS", "CF"):
            continue   # SCE 등은 이 감사 대상 아님(include_sce=False 라 기본은 안 나오지만 방어)
        basis = "consolidated" if section_code.endswith("_C") else "separate"
        for tbl, unit, _kind in tables_with_unit:
            # 단위: 섹션 그룹이 이미 준 것 우선, 없으면 표 자기 선언으로 재시도(추측 금지 —
            # strict 추출기와 동일, Phase A §3-C). 둘 다 없으면 스킵.
            u = unit if unit is not None else declared_unit(tbl)
            if u is None:
                continue
            _read_table(tbl, basis, stmt, u)
    return lines


def _supplement_with_text(a_lines: list[FaceLine], file_path: str | Path) -> list[FaceLine]:
    """Track A 라인에 Track B(텍스트) face 라인을 **보충** 병합한다.

    배경: 일부 보고서(지주·하이브리드)는 BS/CF 는 XBRL ACODE 로 태깅하나 **IS(손익) face 는
    텍스트표만** 제공 → Track A 만 읽으면 매출/순이익이 통째로 빠져 LABEL_UNMATCHED(pending).
    Track A 가 못 잡은 계정의 텍스트 라인을 합치면 그 값이 보고서에 실재함을 검증할 수 있다.

    안전성(단조성): 추가하는 Track B 라인은 모두 from_gapfill=True 로 표시 → 그 계정에 Track A
    후보가 없던 경우(LABEL_UNMATCHED)의 불일치는 GAPFILL_UNVERIFIED(pending)로 남고 **fail 로
    승격되지 않는다**. 후보 추가는 매칭 기회만 늘릴 뿐 기존 매칭을 없애지 못한다 → fail=0 보존.

    성능: Track A 가 BS/IS/CF **3개 statement 를 모두** 커버하면(각 ≥1 canonical 라인) 보충해도
    얻을 게 없으므로 텍스트 재파싱을 건너뛴다(완전한 Track A=대다수 → 이중 파싱 회피). 하나라도
    누락된 하이브리드(지주·금융 등 IS 텍스트표) 보고서에서만 Track B 를 읽는다.
    """
    covered = {_statement_of(ln.canonical) for ln in a_lines if ln.canonical}
    covered.discard(None)
    if {"BS", "IS", "CF"} <= covered:
        return a_lines
    try:
        b_lines = read_report_face_text(file_path)
    except (FileNotFoundError, OSError):
        return a_lines
    if not b_lines:
        return a_lines
    a_keys = {(ln.canonical, ln.basis, ln.amount_won) for ln in a_lines}
    for bl in b_lines:
        if (bl.canonical, bl.basis, bl.amount_won) in a_keys:
            continue
        bl.from_gapfill = True
        a_lines.append(bl)
    return a_lines


def read_report_face(file_path: str | Path) -> list[FaceLine]:
    """Track A 우선(+텍스트 보충), 0행이면 Track B(텍스트) 폴백. 감사 러너의 단일 진입점."""
    lines = read_report_face_xbrl(file_path)
    if lines:
        return _supplement_with_text(lines, file_path)
    return read_report_face_text(file_path)


def read_report_face_tracked(file_path: str | Path,
                             all_cols: bool = False) -> tuple[list[FaceLine], str | None]:
    """read_report_face 와 동일하되 **어느 track 으로 읽었는지** 함께 반환.

    track = "A"(XBRL) / "B"(텍스트) / "C"(PDF) / None(0행).
    promote 게이트가 fail 의 신뢰도(Track A=확정버그 / B·C=휴리스틱)를 구분하는 데 쓴다.
    all_cols=True: 비교컬럼 폴백 행 검증용으로 Track A 전 컬럼 포함(Track B 는 본래 전 셀 읽음).
    """
    # PDF-only 보고서(.pdf source) → Track C 독립 reader. PDF 라인은 from_gapfill → 불일치 pending.
    if str(file_path).lower().endswith(".pdf"):
        lines = read_report_face_pdf(file_path)
        return (lines, "C") if lines else ([], None)
    lines = read_report_face_xbrl(file_path, all_cols=all_cols)
    if lines:
        # 텍스트 보충: Track A 가 못 잡은 계정(IS face 텍스트표 등)을 Track B 라인으로 보충.
        # all_cols(비교행)도 보충 — Track B 는 행 내 전 셀(전기/전전기 포함)을 any-column 으로
        # 읽으므로 비교컬럼 대조에 그대로 부합. 비교행 분기는 불일치를 fail 로 승격하지 않음
        # (COMPARATIVE_ROW pending) → 후보 추가는 매칭만 늘려 단조 개선.
        lines = _supplement_with_text(lines, file_path)
        return lines, "A"
    lines = read_report_face_text(file_path)
    if lines:
        return lines, "B"
    return [], None


def read_report_face_pdf(file_path: str | Path) -> list[FaceLine]:
    """Track C(PDF) 보고서의 본문 재무제표 face 라인을 **독립** 재추출(감사용).

    독립성: 추출기(`fin2.extract.pdf.extract_pdf_facts`)는 행에서 col0(당기 1개 셀)만 취하지만,
    감사 reader 는 같은 본문표에서 **행 내 모든 숫자 셀(any-column)**을 후보로 읽는다 → std 값이
    그 계정 라인의 어느 컬럼과든 일치하는지 검증(추출기의 컬럼 선택 오류를 잡는다). 숫자 파싱은
    감사 자체 `parse_displayed` 사용. 라인은 from_gapfill=True → 불일치는 GAPFILL_UNVERIFIED
    (pending)로 남고 **fail 로 승격 안 됨**(fail=0 보존). 통계표 식별(앵커·단위)은 추출기와 공유.
    """
    from fin2.extract.pdf import (
        _read_pdf_text, _find_anchors, _iter_data_lines,
        _region_has_anchor_labels, _adecimal_from_unit,
    )
    from parser.common.account_mapper import get_mapper

    text = _read_pdf_text(file_path)
    if not text:
        return []
    anchors = _find_anchors(text)
    if not anchors:
        return []
    mapper = get_mapper()
    lines: list[FaceLine] = []
    seen: set[tuple] = set()
    for i, anc in enumerate(anchors):
        if anc.statement == "SCE":
            continue
        end = anchors[i + 1].start if i + 1 < len(anchors) else len(text)
        region = text[anc.start:end]
        if not _region_has_anchor_labels(region, anc.statement):
            continue
        adecimal = _adecimal_from_unit(anc.unit)
        fs_section = anc.statement.lower()
        for label, nums in _iter_data_lines(region):
            mapping = mapper.map(label, fs_section=fs_section)
            canon = mapping.account_code
            if not canon or canon.startswith("unknown."):
                continue
            if _statement_of(canon) != anc.statement:
                continue
            if canon == "is.tax_expense" and "차감전" in label:
                continue
            for v in nums:                       # ★ any-column(추출기 col0 선택과 독립)
                won = v * (10 ** (-adecimal)) if adecimal < 0 else v
                key = (canon, anc.basis, won)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(FaceLine(
                    statement=anc.statement, basis=anc.basis, acode=label[:80],
                    canonical=canon, label=label[:80], displayed_value=v,
                    adecimal=adecimal, is_cumulative=True, from_gapfill=True,
                ))
    return lines


# ── 감사 비교 ───────────────────────────────────────────────────────────────

@dataclass
class FieldAudit:
    field: str
    canonical: str
    db_amount_won: int
    match: bool
    reason: str | None          # None=match. VALUE_DIFF/LABEL_UNMATCHED/...
    report_value_won: int | None  # 가장 가까운 보고서 라인의 won 값(진단)


# 감사 상태(field·row 레벨). PASS/FAIL 만 promote 게이트에 반영,
# PENDING_* 는 iteration 1 범위 밖(차단도 통과도 아님 — 후속 백엔드가 처리).
STATUS_PASS = "pass"
STATUS_FAIL = "fail"          # Track A own-report col0 에 계정 라인 존재하나 값 불일치(진짜 오류)
STATUS_PENDING = "pending"    # 아직 감사 불가(범위 밖)

# field reason → 분류
_FAIL_REASONS = {"VALUE_DIFF"}
_PENDING_REASONS = {"COMPARATIVE_ROW", "SOURCE_NOT_TRACK_A", "LABEL_UNMATCHED",
                    "GAPFILL_UNVERIFIED", "COGS_SGA_CONCEPT_MISMATCH"}

# ★R21 Phase 3(a)(2026-08-15, 사용자 결정) — 이 4개사는 XBRL `ifrs-full_CostOfSales`가
# 순수 COGS가 아니라 **COGS+SGA 결합 총계**에 태깅돼 있다(`docs/plans/is_sga_cogs_holding_
# co_label_mismap_plan_2026-08-15.md` §3). `is.cogs`(std)를 아무리 정확히 계산해도(순수
# COGS) report_won(결합 총계)과 구조적으로 못 맞는다 — std_v3 데이터 버그가 아니라 비교
# **개념 자체가 다른** 케이스라 pending 처리한다(값 오류 감사가 아니라 감사 범위 밖 표시).
# (b)(cogs+sga 합을 report_won과 비교)는 4개사 중 두산 1개사만 SGA XBRL개념이 태깅돼
# 적용 가능하고 나머지 3개사는 그 개념 자체가 없어 채택 안 함(plan Phase 3 결정 근거 참고).
# 키는 (corp_code, fiscal_year, fiscal_period, basis) 4-튜플 — R16~R21 override와 같은
# 원칙(curated, 블랭킷 금지). Probe(`scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py`)
# 로 확정한 14건 전부 `report_won == is.cogs + is.sga`(±1) 항등식 실측 확인 완료.
_COGS_CONCEPT_MISMATCH_KEYS: frozenset[tuple[str, int, str, str]] = frozenset({
    ("00108940", 2025, "FY", "separate"),
    ("00108940", 2026, "Q1", "separate"),
    ("00117212", 2024, "FY", "separate"),
    ("00117212", 2025, "FY", "separate"),
    ("00117212", 2025, "H1", "separate"),
    ("00117212", 2025, "Q1", "separate"),
    ("00117212", 2025, "Q3", "separate"),
    ("00117212", 2026, "Q1", "separate"),
    ("00143527", 2024, "FY", "consolidated"),
    ("00143527", 2025, "H1", "consolidated"),
    ("00143527", 2025, "Q1", "consolidated"),
    ("00143527", 2025, "Q3", "consolidated"),
    ("00163673", 2025, "H1", "consolidated"),
    ("00163673", 2025, "Q3", "consolidated"),
})


@dataclass
class RowAudit:
    """std_v2 한 행(corp,fy,fp,basis)의 감사 롤업."""
    status: str                 # pass/fail/pending
    n_pass: int
    n_fail: int
    n_pending: int
    fields: list[FieldAudit]
    fail_fields: list[str]


# ── promote gate_status (task #5) ────────────────────────────────────────────
# 뷰 게이팅용 상태. fail 은 source track 으로 신뢰도 분리:
#   fail_a = Track A(XBRL ADECIMAL 권위) 값불일치 = **확정 버그** → 메인뷰 차단.
#   fail_b = Track B(텍스트 reader 휴리스틱) 값불일치 = false-fail 가능 → 메인뷰 노출·REVIEW.
GATE_PASS = "pass"
GATE_FAIL_A = "fail_a"
GATE_FAIL_B = "fail_b"
GATE_PENDING = "pending"


def gate_status_for_row(ra: RowAudit, fail_field_tracks: dict[str, str]) -> str:
    """RowAudit + 실패필드별 track('A'/'B') → promote gate_status.

    pass→pass / pending→pending / fail→ 실패필드 track 중 하나라도 'A' 면 fail_a(확정버그),
    아니면 fail_b(Track B 휴리스틱). track 미상(None/누락)은 보수적으로 'A' 취급(차단).
    """
    if ra.status == STATUS_PASS:
        return GATE_PASS
    if ra.status == STATUS_PENDING:
        return GATE_PENDING
    # fail: 실패필드 중 하나라도 Track A(또는 track 미상) → 확정버그로 차단.
    # Track B(텍스트)·C(PDF)는 휴리스틱 → fail_b(REVIEW). (PDF 라인은 from_gapfill 이라 실제론
    # fail 미발생·pending 이지만 방어적으로 분류.)
    if any(fail_field_tracks.get(f) not in ("B", "C") for f in ra.fail_fields):
        return GATE_FAIL_A
    return GATE_FAIL_B


def _statement_face(field: str, bs_face, is_face, cf_face) -> list:
    canon = STD_FIELD_CANONICAL.get(field, "")
    if canon.startswith("bs."):
        return bs_face
    if canon.startswith("is."):
        return is_face
    if canon.startswith("cf."):
        return cf_face
    return []


def audit_std_row(
    db_row: dict,
    *,
    basis: str,
    bs_face: list[FaceLine],
    is_face: list[FaceLine],
    cf_face: list[FaceLine],
    is_comparative: bool,
    fields: tuple[str, ...] | None = None,
) -> RowAudit:
    """
    std_v2 한 행을 statement 별 source face 와 대조하여 행 상태로 롤업.

    범위 게이팅(iteration 1):
      - 비교컬럼 폴백 행(is_comparative): 값이 후속 보고서 col1/2 에 있어 col0 감사 불가 → PENDING.
      - statement source 가 Track A 가 아니면(face 비어있음): 텍스트 백엔드 필요 → PENDING.
      - 그 외: col0 대조 → PASS / FAIL(VALUE_DIFF) / PENDING(LABEL_UNMATCHED).

    row status: 하나라도 FAIL → fail. FAIL 없고 PASS≥1 이며 PENDING 만 잔여 → pending if 모든 게
    pending, 아니면 in-scope 전부 pass 면 pass.
    """
    fields = fields or DIRECT_FIELDS
    interim = db_row.get("fiscal_period") in ("H1", "Q3")
    out: list[FieldAudit] = []
    for field in fields:
        canon = STD_FIELD_CANONICAL.get(field)
        if canon is None:
            continue
        if field in _CONSOLIDATED_ONLY and basis != "consolidated":
            continue
        val = db_row.get(field)
        if val is None:
            continue
        if is_comparative:
            # 비교컬럼 폴백 행: 값이 후속 보고서 전기/전전기 컬럼에 있다 → all_cols face 와 any-column
            # 대조. 일치=PASS(검증). 불일치/미발견=COMPARATIVE_ROW(pending, **fail 아님**) — 비교컬럼은
            # 컬럼-연도 정밀대조가 약해 보수적으로 미검증 유지(fail=0 불변, 커버리지만 확장).
            face = _statement_face(field, bs_face, is_face, cf_face)
            if face:
                # 비교행은 any-column 대조(검증 약 tier, 불일치=pending) → interim 누적셀 필터를 풀어
                # 모든 컬럼·셀(3개월/누적 포함)을 후보로 본다. 비교 분기는 fail 을 내지 않으므로
                # 필터 완화는 매칭만 늘리는 단조 개선(fail=0 보존).
                for f in audit_fields(db_row, face, basis=basis, fields=(field,), interim=False):
                    out.append(f if f.match else
                               FieldAudit(field, canon, val, False, "COMPARATIVE_ROW", f.report_value_won))
            else:
                out.append(FieldAudit(field, canon, val, False, "COMPARATIVE_ROW", None))
            continue
        face = _statement_face(field, bs_face, is_face, cf_face)
        if not face:
            out.append(FieldAudit(field, canon, val, False, "SOURCE_NOT_TRACK_A", None))
            continue
        fa = audit_fields(db_row, face, basis=basis, fields=(field,), interim=interim)
        out.extend(fa)

    n_pass = sum(1 for f in out if f.match)
    n_fail = sum(1 for f in out if f.reason in _FAIL_REASONS)
    n_pending = sum(1 for f in out if f.reason in _PENDING_REASONS)
    fail_fields = [f.field for f in out if f.reason in _FAIL_REASONS]
    # 엄격 게이트(PRD §6/§8): pass = in-scope 전 계정 검증되어 모두 일치(fail·pending 0).
    # pending 이 하나라도 있으면 100% 인증 불가 → 행 전체 pending(차단도 아니나 promote 도 안 함).
    if n_fail:
        status = STATUS_FAIL
    elif n_pending == 0 and n_pass:
        status = STATUS_PASS
    else:
        status = STATUS_PENDING
    return RowAudit(status, n_pass, n_fail, n_pending, out, fail_fields)


def audit_fields(
    db_row: dict,
    face_lines: list[FaceLine],
    *,
    basis: str,
    fields: tuple[str, ...] | None = None,
    interim: bool = False,
) -> list[FieldAudit]:
    """
    std_v2 한 행(db_row, statement_type=basis)의 표준 필드 값들을 face_lines 와 대조.

    PASS = 그 계정 부류(canonical)의 보고서 라인 중 won 값이 정확히 일치하는 것이 존재.
    won 동치 = displayed × 10^(-adecimal). Track A 는 ADECIMAL 권위라 표시단위 일치와 동치.

    basis 일치는 face_line.basis 가 명시된 경우만 강제(미태깅 None 라인은 양쪽 허용).
    interim=True(H1/Q3): IS/CF 는 std_v2 가 누적(YTD)을 저장하므로 누적 셀(is_cumulative)만 후보.
    """
    fields = fields or DIRECT_FIELDS
    # canonical → 그 부류 보고서 라인의 won 값 집합
    by_canon: dict[str, list[FaceLine]] = {}
    for ln in face_lines:
        if ln.canonical is None:
            continue
        if ln.basis is not None and ln.basis != basis:
            continue
        # 반기/3분기 flow(IS/CF): std 는 누적값 → 누적 셀만 대조(3개월 셀 오매칭 방지).
        if interim and (ln.canonical.startswith("is.") or ln.canonical.startswith("cf.")) \
                and not ln.is_cumulative:
            continue
        by_canon.setdefault(ln.canonical, []).append(ln)

    results: list[FieldAudit] = []
    for field in fields:
        canon = STD_FIELD_CANONICAL.get(field)
        if canon is None:
            continue
        # 지배지분 필드는 연결에서만 face 라인 존재 — 별도는 감사 제외.
        if field in _CONSOLIDATED_ONLY and basis != "consolidated":
            continue
        val = db_row.get(field)
        if val is None:
            continue  # DB 에 값 없음 — 감사 대상 아님(누락은 별도 커버리지 이슈)
        if canon == "is.cogs" and (db_row.get("corp_code"), db_row.get("fiscal_year"),
                                    db_row.get("fiscal_period"), basis) in _COGS_CONCEPT_MISMATCH_KEYS:
            # R21 Phase 3(a, 2026-08-15) — 이 키는 XBRL 총계가 COGS+SGA 결합이라 report_won
            # 과 비교 개념 자체가 다르다(위 _COGS_CONCEPT_MISMATCH_KEYS 주석 참고). std_v3 값
            # 오류가 아니므로 정상 대조를 건너뛰고 pending 처리(감사 범위 밖).
            results.append(FieldAudit(field, canon, val, False,
                                      "COGS_SGA_CONCEPT_MISMATCH", None))
            continue
        cands = by_canon.get(canon, [])
        if not cands and canon == "is.revenue":
            # ★ 매출액 단일 라인이 face 에 없고 std 가 매출원가+매출총이익 으로 파생된 경우
            # (revenue_from_cogs_gp 규칙). 회계 항등식 매출원가+매출총이익==매출액 → 보고서의
            # cogs·gross_profit 라인 합이 std 매출과 일치하면 보고서 충실 검증(PASS). 미일치=LABEL 유지.
            cogs = [ln.amount_won for ln in by_canon.get("is.cogs", []) if ln.amount_won is not None]
            gp = [ln.amount_won for ln in by_canon.get("is.gross_profit", []) if ln.amount_won is not None]
            if any(abs(c) + g == val for c in cogs for g in gp):
                results.append(FieldAudit(field, canon, val, True, None, report_value_won=val))
                continue
        if not cands and canon == "is.net_income":
            # ★ 총 당기순이익 라인이 IS face 에 깔끔히 안 잡히는 경우(보고서가 귀속분만 표기·
            # 3개월/누적 컬럼 깨짐) std=당기순이익 의 충실성을 보조 라인으로 검증:
            #   ① CF 간접법 시작 '당기순이익'(cf.net_income_cf, YTD=std 와 동일 누적기준)
            #   ② 지배+비지배 귀속 합(소수주주 없으면 지배=총NI)
            # 매칭=PASS(보고서에 값 실재 확인), 미매칭=아래 일반흐름(LABEL_UNMATCHED 유지) → fail 아님.
            alt = [ln.amount_won for ln in by_canon.get("cf.net_income_cf", [])
                   if ln.amount_won is not None]
            if val in alt or -val in alt:
                results.append(FieldAudit(field, canon, val, True, None, report_value_won=val))
                continue
            ctrl = [ln.amount_won for ln in by_canon.get("is.controlling_ni", [])
                    if ln.amount_won is not None]
            ncl = [ln.amount_won for ln in by_canon.get("is.noncontrolling_ni", [])
                   if ln.amount_won is not None] or [0]
            if any(c + n == val for c in ctrl for n in ncl):
                results.append(FieldAudit(field, canon, val, True, None, report_value_won=val))
                continue
        if not cands:
            results.append(FieldAudit(field, canon, val, False, "LABEL_UNMATCHED", None))
            continue
        won_vals = {ln.amount_won for ln in cands}
        if val in won_vals:
            results.append(FieldAudit(field, canon, val, True, None,
                                      report_value_won=val))
        elif -val in won_vals:
            # 부호만 반대 — std 의 비용/차감 정규화(매출원가·세금 등 양수화) vs 보고서 괄호표시.
            # 값(절대) 충실 → PASS(부호는 표준화 규약, 데이터 오류 아님).
            results.append(FieldAudit(field, canon, val, True, None,
                                      report_value_won=-val))
        else:
            nearest = min(cands, key=lambda ln: abs((ln.amount_won or 0) - val))
            # ★ 표시단위 ±1 허용: 보고서 표시단위(10^-adecimal) 1단위 이내 차이는 발행사 자체
            # 반올림(예 CJ제일제당 XBRL: ProfitLoss vs 지배+비지배 1천원 불일치)·파생필드 라운딩
            # 으로, 표시단위 이하 검증불가(PRD)에 해당 → PASS. 실수준 오류(>1단위)만 VALUE_DIFF.
            nw = nearest.amount_won or 0
            tol = 10 ** (-nearest.adecimal) if (nearest.adecimal or 0) < 0 else 1
            matched_won = None
            if abs(nw - val) <= tol or abs(nw + val) <= tol:
                matched_won = nw
            elif canon == "is.net_income":
                # ★ 총 당기순이익 라인이 보고서 본문에 깔끔히 안 나오는 경우(컬럼 깨짐·3개월만 표기)
                # std 는 지배+비지배 귀속 합으로 복원한다 → 보고서의 귀속 라인 합과 대조해 충실성 검증.
                ctrl = [l.amount_won for l in by_canon.get("is.controlling_ni", []) if l.amount_won is not None]
                ncl = [l.amount_won for l in by_canon.get("is.noncontrolling_ni", []) if l.amount_won is not None]
                ncl = ncl or [0]  # 비지배지분 라인 부재(소수주주 없음) → 총NI=지배지분.
                if any(abs(c + n - val) <= max(tol, 1) for c in ctrl for n in ncl):
                    matched_won = val
            if matched_won is not None:
                results.append(FieldAudit(field, canon, val, True, None, report_value_won=matched_won))
            elif all(ln.from_gapfill for ln in cands):
                # ★ 갭필(표제기반 실패→detect_sections, 휴리스틱 저신뢰)로만 찾은 표와의 불일치는
                # reader 표선택 불확실(NAVER류)일 수 있어 **fail 아닌 pending**(GAPFILL_UNVERIFIED).
                # 커버리지 확장은 단조(매칭=pass, 불일치=미검증 유지) → fail=0 보존. 잠재 std 버그는 별도.
                results.append(FieldAudit(field, canon, val, False, "GAPFILL_UNVERIFIED", nw))
            else:
                results.append(FieldAudit(field, canon, val, False, "VALUE_DIFF",
                                          report_value_won=nw))
    return results
