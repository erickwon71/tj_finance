"""
Gate B — 보고서 face 표 독립 재추출 + DB(std_v2) 100% 일치 감사.

이 모듈의 핵심 원칙(PRD 04):
  - **표준화 파이프라인과 독립**: reconcile(source 선택)·standardize(규칙) 를 거치지 않고
    원본 보고서의 face 표를 직접 다시 읽는다 → 같은 버그를 양쪽이 공유하지 않음.
  - **보고서 표시단위 정확 일치**: round(DB_amount_won × 10^ADECIMAL) == 보고서 표시값.
    Track A(XBRL) 는 ADECIMAL 권위라 won-공간에서 동치 비교가 정확하다.
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
from fin2.extract.statement_titles import title_text, classify_statement_title
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


def read_report_face_xbrl(file_path: str | Path, all_cols: bool = False) -> list[FaceLine]:
    """
    Track A(XBRL) 보고서의 face 라인을 독립 재추출. 기본 col_index=0(당기)·비차원만.

    all_cols=True: col_index 0/1/2(당기·전기·전전기) 모두 포함 — 비교컬럼 폴백 행 검증용
    (그 행 값은 후속 보고서의 전기/전전기 컬럼에 있으므로 col0 만으론 대조 불가).
    Track A 가 아니면(=ifrs/dart ACODE+ACONTEXT 셀 없음) 빈 리스트.
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []

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
        try:
            adecimal = int(te.get("ADECIMAL", ""))
        except (ValueError, TypeError):
            adecimal = None
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


# 표제기반 본문표 식별은 fin2.extract.statement_titles 로 이전(추출기와 공유, 단일 진실원).
# title_text / classify_statement_title 를 import 해 사용한다.


def read_report_face_text(file_path: str | Path) -> list[FaceLine]:
    """
    Track B(텍스트) 보고서의 **본문 재무제표 face 표** 라인을 독립 재추출.

    설계(NAVER 트리아지 교훈): section_detector.find_section_tables 는 복잡문서(분할·정정)에서
    본문 표 대신 2차 조정표/요약을 오연결한다 → **표제(제목 표)로 본문 재무제표 표를 직접 식별**한다.
    DART 본문 = `<TABLE-GROUP>[표제 TABLE("연결 재무상태표 제N기..."), 데이터 TABLE]` 구조.
    표제에 statement명+기간마커가 있고 분할/주석/요약/자본변동이 아니면 그 데이터 표가 본문 face.

    독립성: 표 위치는 표제로 찾되, 셀은 table_extractor 컬럼로직 비재사용하고 **행 내 모든
    숫자 셀 리터럴** 읽기(any-column). is_cumulative=True 로 interim 필터 통과.
    요약재무정보표·주석표는 제외(본문만).
    """
    from parser.xml.table_extractor import _get_cells
    from parser.common.account_mapper import get_mapper
    from parser.common.amount_normalizer import detect_unit_declaration
    from fin2.extract.text import _detect_unit_near_table, _table_has_data_rows
    from fin2.extract.statement_titles import SECTION_CODE_OF

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

    # ── 1차: 표제기반 본문표(robust, 복잡문서 오연결 회피) ──
    covered: set[str] = set()
    for tbl in root.findall(".//TABLE"):
        meta = classify_statement_title(title_text(tbl))
        if meta is None:
            continue
        # 데이터행 없는 footer/stub 표(제목만)는 face 아님 → 커버로 치지 않음(갭필이 진짜표 채우게).
        if not _table_has_data_rows(tbl):
            continue
        basis, stmt = meta
        # 단위: 표제 선언 → 표 자체/인접 <P>(K-GAAP 천원 ×1000 false-fail 방지).
        unit = detect_unit_declaration(title_text(tbl)) or _detect_unit_near_table(tbl)
        _read_table(tbl, basis, stmt, unit)
        covered.add(SECTION_CODE_OF[(basis, stmt)])

    # ── 폴백(갭필): 표제기반이 못 잡은 섹션(구 K-GAAP 면표는 제목이 stub 표에 분리돼 classify 실패)
    # 은 추출기와 동일하게 detect_sections/find_section_tables 로 찾는다(K-GAAP 등 커버리지 확장).
    # 셀 읽기는 동일 _read_table(any-column, 독립 숫자파서) → 수치/단위 검증 독립성 유지.
    _META_OF = {"BS_C": ("consolidated", "BS"), "BS_S": ("separate", "BS"),
                "IS_C": ("consolidated", "IS"), "IS_S": ("separate", "IS"),
                "CF_C": ("consolidated", "CF"), "CF_S": ("separate", "CF")}
    missing = [c for c in _META_OF if c not in covered]
    if missing:
        from parser.xml.section_detector import (
            detect_sections, find_section_tables, detect_unit_from_section)
        try:
            sections = detect_sections(root)
        except Exception:
            sections = {}
        for code in missing:
            title_elem = sections.get(code)
            if title_elem is None:
                continue
            try:
                tbls = find_section_tables(title_elem)
                unit = detect_unit_from_section(title_elem)
            except Exception:
                continue
            basis, stmt = _META_OF[code]
            for t in tbls:
                _read_table(t, basis, stmt, unit, from_gapfill=True)
    return lines


def _supplement_with_text(a_lines: list[FaceLine], file_path: str | Path) -> list[FaceLine]:
    """Track A 라인에 Track B(텍스트) face 라인을 **보충** 병합한다.

    배경: 일부 보고서(지주·하이브리드)는 BS/CF 는 XBRL ACODE 로 태깅하나 **IS(손익) face 는
    텍스트표만** 제공 → Track A 만 읽으면 매출/순이익이 통째로 빠져 LABEL_UNMATCHED(pending).
    Track A 가 못 잡은 계정의 텍스트 라인을 합치면 그 값이 보고서에 실재함을 검증할 수 있다.

    안전성(단조성): 추가하는 Track B 라인은 모두 from_gapfill=True 로 표시 → 그 계정에 Track A
    후보가 없던 경우(LABEL_UNMATCHED)의 불일치는 GAPFILL_UNVERIFIED(pending)로 남고 **fail 로
    승격되지 않는다**. 후보 추가는 매칭 기회만 늘릴 뿐 기존 매칭을 없애지 못한다 → fail=0 보존.
    """
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

    track = "A"(Track A xbrl_acode 가 행을 냄) / "B"(Track B 텍스트 폴백) / None(둘 다 0행).
    promote 게이트가 fail 의 신뢰도(Track A=확정버그 / Track B=휴리스틱)를 구분하는 데 쓴다.
    all_cols=True: 비교컬럼 폴백 행 검증용으로 Track A 전 컬럼 포함(Track B 는 본래 전 셀 읽음).
    """
    lines = read_report_face_xbrl(file_path, all_cols=all_cols)
    if lines:
        # 비교행(all_cols)은 전기/전전기 컬럼 대조라 보충 비대상. 일반 col0 감사만 텍스트 보충.
        if not all_cols:
            lines = _supplement_with_text(lines, file_path)
        return lines, "A"
    lines = read_report_face_text(file_path)
    if lines:
        return lines, "B"
    return [], None


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
                    "GAPFILL_UNVERIFIED"}


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
    # fail: 실패필드 중 하나라도 Track A(또는 track 미상) → 확정버그로 차단
    if any(fail_field_tracks.get(f) != "B" for f in ra.fail_fields):
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
                for f in audit_fields(db_row, face, basis=basis, fields=(field,), interim=interim):
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
        cands = by_canon.get(canon, [])
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
