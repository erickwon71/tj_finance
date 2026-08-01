"""B5 - Caption catalog extractor for the '사업의 내용' section (Tier1/Tier2/industry-specific).

Why a separate module
---------------------
The existing three extractors (biz_section=production, sales_section=sales,
order_backlog=orders) each *hunt for their own keyword heading and read the tables that
follow*. Growing that to 20+ items would clone the heading-search logic 20 times over.
This module inverts the direction: it walks **every table in the document once and
classifies it by caption** (same traversal as the census tool
`scripts/survey_biz_section_inventory.py`).

Evidence (2026-07-31 source census, 782 companies / 22,698 tables — see
docs/qa/biz_section_items_shortlist_2026-07-31.md):
  - The section holds ~29 tables per company and the caption almost fully determines the item.
  - Industry-specific tables (insurance solvency, securities fund operations, construction
    contract work) are unreachable by the manufacturing-format parsers -> only a caption
    catalog gets to them.

Two source-document traps the traversal MUST handle (measured and fixed during the census)
------------------------------------------------------------------------------------------
1. **DART wraps narrative paragraphs in 1x1 TABLE elements.** Counting them doubles the
   inventory and, worse, **steals the caption of the real table that follows**
   (Samsung Electronics 2024: looks like 85 tables, actually 37).
2. **A missing `</TABLE>` can nest the whole document inside one table** (KT&G
   20260318001422: the `II. 사업의 내용` TITLE itself sits at nesting depth 1). Deciding
   "top-level table" by nesting depth therefore finds **zero** tables -> only tables with
   no descendant TABLE (leaf tables) count as data tables.

Double-capture prevention
-------------------------
Caption keyword exclusion alone is not enough (the same physical table can also fall inside
the heading window of the production/sales parsers). So tables already captured are excluded
by **grid content hash** (`seen_grids`) — duplicate loading becomes impossible no matter how
the caption rules change.

Destination
-----------
No new table. Rows are appended, with continuing table_ord, to the two lists returned by
`parse_biz_metrics` (biz_section_tables, biz_metrics) -> this rides the existing sync
(rcept-scoped delete-then-insert, idempotent) and the daily pipeline wiring
(`collect_new.py`, both call sites) **unchanged**.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

from fin2.extract.biz_section import (
    _FINANCIAL_STMT_KW,
    _PERIOD_GI_RE,
    _PERIOD_YEAR_RE,
    _is_clean_number,
    _is_period_header_cell,
    is_merged_column_table,
    _narrative_unit,
    _parse_value,
    _tag,
    _text,
    expand_table_grid,
)
from parser.xml.section_detector import normalize_dart_section_title

# ─────────────────────────────────────────────────────────────────────────────
# 1) Section traversal — collect captioned leaf tables
# ─────────────────────────────────────────────────────────────────────────────
_SEC_BIZ = "사업의내용"
# Top-level TOC entries (Roman-numeral prefix) close the section:
# 'II. 사업의 내용' -> 'III. 재무에 관한 사항'.
_ROMAN_PREFIX_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|[IVX]{1,5})\s*[.．)]\s*")
# Strip leading caption numbering (가. / 1) / (1) / ① / ■).
_CAP_NUM_RE = re.compile(
    r"^\s*(?:[\(（]?\s*(?:\d+|[가-힣]|[ⅰ-ⅹ]+|[a-zA-Z])\s*[-–]?\s*\d*\s*[\)）.．]|[①-⑳㉠-㉿▶◆■○●※-])\s*")
_CAP_TAIL_RE = re.compile(r"[\(（]\s*(?:단위|기준일?|연결|별도)[^)）]*[\)）]\s*$")

_CAPTION_MAX = 42        # max length of a caption candidate (to tell it from a narrative paragraph)
_CAPTION_LOOKBACK = 4    # how many preceding paragraphs stay eligible as a caption
_NARRATIVE_KEEP = 3      # preceding paragraphs kept for unit extraction

# Unit token — also recovers the common "(단위: 백만원, %)" form where % follows a comma
# (the first monetary unit wins).
_UNIT_TOKEN_RE = re.compile(r"단위\s*[:：]?\s*[\(（]?\s*(백만원|십억원|억원|천만원|천원|만원|조원|원)")


@dataclass
class CaptionedTable:
    """One data table from the section plus the context that describes it."""
    subsection: str                       # subsection heading (주요제품및서비스 etc.)
    caption: str                          # normalized caption (classification key)
    caption_raw: str                      # caption as written
    narrative: str                        # preceding paragraphs (for unit extraction)
    grid: list[list[str]] = field(default_factory=list)
    inherited: bool = False               # continuation table that inherited the previous caption


def normalize_caption(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:                      # nested numbering such as '가. (1) 주요 제품'
        prev = s
        s = _CAP_NUM_RE.sub("", s).strip()
    s = _CAP_TAIL_RE.sub("", s).strip()
    return re.sub(r"\s+", "", s)[:40]


def _is_text_block(grid: list[list[str]]) -> bool:
    """Is this a layout table wrapping a narrative paragraph (not a real data table)? — trap 1."""
    if not grid:
        return True
    nrow = len(grid)
    ncol = max(len(r) for r in grid)
    if nrow > 2 or ncol > 2:
        return False
    return not any(_is_clean_number(c) for r in grid for c in r)


def walk_captioned_tables(root: etree._Element) -> list[CaptionedTable]:
    """Collect the data tables of the 'II. 사업의 내용' section in document order.

    Section boundaries are decided by **document order**, not containment — DART's SECTION-2
    elements are cascaded rather than siblings, so `.//` cannot delimit them (same measured
    rationale as `section_detector.assign_tables_to_dart_sections`).
    """
    out: list[CaptionedTable] = []
    in_biz = False
    subsection = "(소제목없음)"
    recent: list[str] = []
    leaf_stack: list[bool] = []
    leaf_depth = 0
    last_caption = ("", "")               # (normalized, raw) — for continuation-table inheritance

    for ev, el in etree.iterwalk(root, events=("start", "end")):
        tag = _tag(el)
        if ev == "end":
            if tag == "TABLE" and leaf_stack:
                leaf_depth -= 1 if leaf_stack.pop() else 0
            continue

        if tag == "TABLE":
            # Trap 2 — identify data tables by 'has no descendant TABLE (leaf)', not by depth.
            it = el.iter("TABLE")
            next(it, None)                # itself
            is_leaf = next(it, None) is None
            leaf_stack.append(is_leaf)
            if not is_leaf:
                continue                  # let wrappers through so their <P> can serve as captions
            leaf_depth += 1
            if not (in_biz and leaf_depth == 1):
                continue

            grid = expand_table_grid(el)
            if _is_text_block(grid):      # trap 1 — absorb paragraph wrappers as caption candidates
                for p in el.iter("P"):
                    t = re.sub(r"\s+", " ", _text(p)).strip()
                    if t:
                        recent.append(t)
                del recent[:-_CAPTION_LOOKBACK]
                continue

            cap_raw = ""
            for cand in reversed(recent):          # nearest 'short' paragraph becomes the caption
                if len(cand) <= _CAPTION_MAX:
                    cap_raw = cand
                    break
            if not cap_raw and recent:
                cap_raw = recent[-1][:_CAPTION_MAX]
            cap = normalize_caption(cap_raw)
            inherited = False
            if not cap:
                # Continuation table (2nd and later in a caption -> table -> table run). The census
                # measured 10.6% of tables here — dropping them for lack of a caption would lose
                # that whole slice, so inherit the previous table's caption.
                cap, cap_raw = last_caption
                inherited = bool(cap)
            else:
                last_caption = (cap, cap_raw)
            out.append(CaptionedTable(
                subsection=subsection, caption=cap, caption_raw=cap_raw,
                narrative=" ".join(recent[-_NARRATIVE_KEEP:]), grid=grid, inherited=inherited))
            recent.clear()
            continue

        if leaf_depth:                    # text inside a data table is not a caption candidate
            continue

        if tag == "TITLE":
            raw = re.sub(r"\s+", " ", _text(el)).strip()
            norm = normalize_dart_section_title(raw)
            if norm == _SEC_BIZ:
                in_biz, subsection = True, "(소제목없음)"
                last_caption = ("", "")
            elif in_biz and _ROMAN_PREFIX_RE.match(raw):
                in_biz = False            # next top-level TOC entry -> section ends
            elif in_biz:
                subsection = norm or subsection
                last_caption = ("", "")   # a new subsection breaks caption inheritance
            recent.clear()
        elif tag == "P" and in_biz:
            t = re.sub(r"\s+", " ", _text(el)).strip()
            if t:
                recent.append(t)
                del recent[:-_CAPTION_LOOKBACK]

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2) Caption catalog — caption -> metric
# ─────────────────────────────────────────────────────────────────────────────
# Rules are an **ordered** list of (metric, include keywords, required keywords).
# First match wins. Metric names respect biz_metrics.metric VARCHAR(20) (all <= 20 chars).
#
# Captions owned by the existing parsers (production / sales / R&D expense) are not matched
# here. The physical guarantee against double capture is the grid hash (`seen_grids`), not
# these keywords — the rules below only declare *what is newly read*.
CatalogRule = tuple[str, tuple[str, ...], tuple[str, ...]]

# Order IS priority. **More specific rules must come first** — substring collisions cause
# silent misclassification otherwise (measured: '파생상품 및 풋백옵션 등 거래 현황' matched
# product_status via the substring '상품' and was filed as a product listing). Hence
# industry-specific and dedicated rules first, broad product/material rules last.
CATALOG: list[CatalogRule] = [
    # ── Industry-specific: insurance ──────────────────────────────────────────
    ("ins_solvency",    ("지급여력", "RBC", "K-ICS", "킥스"), ()),
    ("ins_premium",     ("수입보험료", "보험료수익", "원수보험료"), ()),
    ("ins_claim",       ("보험금내역", "보험금지급", "지급보험금", "손해율"), ()),
    ("ins_reserve",     ("준비금", "보험계약부채", "책임준비금"), ()),
    ("branch",          ("점포현황", "지점등설치", "지점현황", "영업점현황"), ()),
    # ── Industry-specific: securities / banking ───────────────────────────────
    # Fund raising and fund use frequently share one caption (신한지주 '자금조달ㆍ운용현황',
    # 카카오뱅크 '자금 조달 및 운용 현황'), so the combined rule goes first.
    ("fund_flow",       ("자금조달및운용", "자금조달ㆍ운용", "자금조달·운용", "조달및운용",
                         "자금조달과운용"), ()),
    ("fund_raise",      ("자금조달",), ()),
    ("fund_use",        ("자금운용", "운용실적", "운용내역", "운용현황", "자산운용률",
                         "유가증권운용", "대출금운용"), ()),
    ("brokerage",       ("위탁매매", "증권거래현황", "환매조건부", "매매거래실적"), ()),
    ("underwriting",    ("인수업무", "인수실적", "유가증권인수"), ()),
    # Derivatives/trusts overlap broad tokens like '상품'/'재산', so they must precede
    # the product rules.
    ("derivative",      ("파생상품", "파생결합", "풋백옵션"), ()),
    ("trust_aum",       ("투자일임", "신탁별수탁", "수탁현황", "금전신탁"), ()),
    # ── Industry-specific: construction ───────────────────────────────────────
    ("construction",    ("도급건축", "도급토목", "도급공사", "자체공사", "주요공사",
                         "공사현황", "분양현황"), ()),
    ("inventory",       ("재고자산",), ()),
    # ── Industry-specific: pharma / R&D staffing ──────────────────────────────
    ("rd_staff",        ("핵심연구인력", "연구개발인력", "연구개발담당조직", "연구개발조직",
                         "연구인력"), ()),
    ("license",         ("라이센스", "라이선스", "license"), ()),
    # ── Tier 2 ────────────────────────────────────────────────────────────────
    ("market_share",    ("점유율",), ()),
    ("customer",        ("매출처", "판매처", "주요거래처", "주요고객"), ()),
    ("capex_plan",      ("진행중인투자", "향후투자", "투자계획", "설비의신설", "신설ㆍ매입",
                         "신설·매입", "시설투자", "설치계획", "증설"), ()),
    ("ip_right",        ("지적재산권", "지식재산권", "특허", "상표등록", "실용신안"), ()),
    ("order_status",    ("수주",), ()),
    # ── Tier 1 ────────────────────────────────────────────────────────────────
    # 매출 계열 보강(2026-08-01 실측): sales_section 은 '매출실적/판매실적/매출현황' 헤딩만
    # 잡는데, 같은 내용을 '매출개요'·'매출유형별 실적'·'매출형태별 실적'·'매출유형별 매출액'
    # 으로 적는 기업이 있어 통째로 누락됐다(나무에이엑스는 이것 때문에 0행이었다).
    # metric 은 sales_section 과 같은 'sales' 로 통일한다 — 개념이 같고, 같은 물리 표를 둘 다
    # 가져가는 일은 grid 해시가 막는다.
    ("sales",           ("매출개요", "매출유형별", "매출형태별", "매출비중",
                         "매출에관한사항", "부문별매출", "품목별매출", "지역별매출"), ()),
    ("segment_fin",     ("부문별요약재무", "부문별주요재무", "부문별재무", "부문별영업",
                         "부문별손익"), ()),
    ("facility",        ("생산설비", "영업설비", "주요설비", "설비의현황", "설비현황",
                         "사업장현황", "주요시설"), ()),
    # Price-trend rules must precede the product/material status rules ('주요 제품 등의
    # 가격변동추이' also matches the product status rule) — more specific rule first.
    ("material_price",  ("원재료", "원자재", "주요매입"), ("가격변동", "가격추이", "단가추이")),
    ("product_price",   ("제품", "판가", "품목"), ("가격변동", "가격추이", "평균판가", "판가추이")),
    ("material_status", ("원재료", "원자재"), ()),
    ("material_status", ("매입현황", "매입처", "매입에관한"), ()),
    # '상품' is not used as a standalone token: it collides with 파생상품/금융상품
    # (see the misclassification noted above).
    ("product_status",  ("제품", "품목", "주요상품", "서비스현황", "제품및서비스"), ()),
]

# Captions containing these belong to the existing parsers, so the catalog skips them (this is
# for performance and intent; the physical guarantee is the grid hash). '수주' is exempt:
# order_backlog only accepts tables that have a backlog column and drops the rest by design,
# so the catalog preserves those separately in long format.
_OWNED_BY_EXISTING = ("생산능력", "생산실적", "가동률", "가동율", "매출실적", "판매실적",
                      "매출현황", "연구개발비용", "연구개발실적", "연구개발비")

# Captions the catalog must never read — re-postings of financial-statement notes (census F2).
# The same content already lives in note_lines.
_RISK_NOTE_KW = ("이자율위험", "이자율변동위험", "유동성위험", "신용위험", "외환위험",
                 "환위험", "환율변동위험", "시장위험", "가격위험", "자본위험", "민감도분석",
                 "공정가치", "손실충당금", "만기분석", "범주별금융", "금융상품의종류별",
                 # 채권 잔액표도 주석 재게시다(실측 2026-08-01: '매출채권'·'매출채권및기타채권'
                 # 이 사업의 내용에 다시 실린다). '매출' 이 들어 있어 위 sales 규칙에 걸리므로
                 # 여기서 먼저 막는다.
                 "매출채권", "기타채권", "위험관리", "자본관리", "신용위험에대한노출")


def classify_caption(caption: str) -> Optional[str]:
    """Normalized caption -> metric, or None when nothing applies."""
    if not caption:
        return None
    flat = caption.replace(" ", "")
    if any(k in flat for k in _RISK_NOTE_KW):
        return None
    if any(k in flat for k in _OWNED_BY_EXISTING):
        return None
    for metric, includes, requires in CATALOG:
        if not any(k in flat for k in includes):
            continue
        if requires and not any(k in flat for k in requires):
            continue
        return metric
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 3) Generic mapper — grid -> long-format metric rows
# ─────────────────────────────────────────────────────────────────────────────
# The production-specific guards (filtering value columns by _PRODUCTION_COL_KW etc.) are
# dropped here: the caption has already fixed the subject, so only 'dimension x value
# columns' needs interpreting.
_MAX_DATA_ROWS = 400     # guard against row explosion in pathologically large (broken) tables
_MAX_COLS = 40
_UNIT_HEADER_KW = ("단위",)
# Missing-value markers — treated exactly like empty cells during column classification
# (they are not labels).
_PLACEHOLDERS = frozenset({"-", "－", "—", "–", "N/A", "n/a", "해당없음", "해당사항없음", "."})
# Segment financial tables legitimately carry financial-statement line items
# (total assets / operating profit) — exempt them from that guard.
_ALLOW_FINANCIAL_LABELS = frozenset({"segment_fin", "inventory", "fund_flow", "fund_raise",
                                     "fund_use", "ins_reserve", "construction"})


@dataclass
class CatalogRow:
    metric: str
    segment: Optional[str]
    item: Optional[str]
    period_label: Optional[str]
    period_year: Optional[int]
    value: float
    unit: Optional[str]
    is_ratio: bool


def _catalog_unit(narrative: str, caption: str, grid: list[list[str]]) -> Optional[str]:
    """Unit extraction: narrative (strict) -> narrative/caption (lenient) -> table cells.

    Same strategy as sales_section.
    """
    u = _narrative_unit(narrative)
    if u:
        return u
    for src in (narrative, caption):
        m = _UNIT_TOKEN_RE.search(src or "")
        if m:
            return m.group(1)
    head = " ".join(" ".join(r) for r in grid[:3])
    m = _UNIT_TOKEN_RE.search(head)
    return m.group(1) if m else None


def map_catalog_table(ct: CaptionedTable, metric: str,
                      fiscal_year: int) -> list[CatalogRow]:
    """Lossless grid -> structured metric rows.

    Column headers that cannot be resolved to a period are preserved in period_label
    (lossless).
    """
    grid = [list(r) for r in ct.grid if r]
    if len(grid) < 2:
        return []
    ncols = max(len(r) for r in grid)
    if ncols > _MAX_COLS:
        return []
    # 열 전체가 한 셀에 병합된 표는 값을 만들지 않는다(사용자 결정 2026-08-01). 행 구조가 원문에
    # 기록돼 있지 않아 복원이 불가능하고, 파싱하면 여러 값이 이어붙은 날조된 수치가 나온다.
    # 원본 grid 는 biz_section_tables 에 무손실 보존되므로 나중에 재처리할 수 있다.
    if is_merged_column_table(grid):
        return []
    grid = [r + [""] * (ncols - len(r)) for r in grid]

    # 1) Header/data split — data starts at the first row holding a 'clean number'.
    #    Period header cells ("2023", "2025(E)", "제34기") must NOT count as numbers. A header
    #    row of bare years would otherwise be judged a data row, making first_data=0 and
    #    discarding the whole table (measured: 21 insurer tables such as 한화생명's
    #    보험종목별 수입보험료 and 흥국화재's 원수보험료 전망 produced zero rows because their
    #    first header row reads '구분|2025|2025|2024…').
    first_data = next((i for i, r in enumerate(grid)
                       if any(_is_clean_number(c) and not _is_period_header_cell(c) for c in r)),
                      None)
    if not first_data:                     # None (no numbers) or 0 (no header)
        return []
    header_rows, data_rows = grid[:first_data], grid[first_data:_MAX_DATA_ROWS + first_data]

    # 2) Column classification — a column is a value column when most of its data cells are
    #    clean numbers, otherwise a dimension column.
    #    Missing-value markers ('-', 'N/A', …) must count as **blank**. Counting them as labels
    #    flips a sparse value column into a dimension column, and that column's numbers end up
    #    as item labels (measured: 한국컴퓨터 20260316000809 material price trend produced
    #    item='5.32').
    dim_cols, val_cols = [], []
    for c in range(ncols):
        col = [row[c].strip() for row in data_rows]
        nonempty = [v for v in col if v and v not in _PLACEHOLDERS]
        clean = sum(1 for v in nonempty if _is_clean_number(v))
        (val_cols if nonempty and clean >= len(nonempty) / 2 else dim_cols).append(c)
    if not val_cols:
        return []

    # A table-wide unit declaration row ("(단위 : 백만원)" replicated across every column by
    # COLSPAN) must be excluded from per-column header text. Otherwise **every column header
    # contains '단위' and the leftmost label column is mistaken for the unit column**: segment
    # becomes entirely NULL and the labels (목재 / 열병합발전 …) leak into unit
    # (measured: 한솔홈데코 20260311003988 segment financial summary).
    wide_unit_rows = {
        r for r in range(len(header_rows))
        if sum(1 for c in range(ncols) if "단위" in header_rows[r][c]) >= max(2, ncols / 2)
    }

    def col_header(c: int) -> str:
        return " ".join(header_rows[r][c] for r in range(len(header_rows))
                        if r not in wide_unit_rows)

    unit_col = None
    for c in dim_cols:
        if any(k in col_header(c) for k in _UNIT_HEADER_KW):
            unit_col = c
            break
    label_cols = [c for c in dim_cols if c != unit_col]

    # 3) Financial-statement line-item guard — reject statements/notes re-posted inside the
    #    section. Segment financials, inventory and the banking fund tables carry those items
    #    legitimately, so they are exempt.
    if metric not in _ALLOW_FINANCIAL_LABELS:
        for drow in data_rows:
            row_label_text = " ".join(drow[c] for c in label_cols)
            if any(k in row_label_text for k in _FINANCIAL_STMT_KW):
                return []

    # Map the largest '제N기' to fiscal_year and derive the rest relatively
    # (same convention as biz_section).
    max_gi = None
    for r in header_rows:
        for c in val_cols:
            gm = _PERIOD_GI_RE.search(r[c])
            if gm:
                max_gi = max(max_gi or 0, int(gm.group(1)))

    def col_sublabel(c: int) -> Optional[str]:
        """Join every non-period axis in a value column's header (product group, measure, …).

        This prevents two distinct failures:
          - When measures split into several columns under one period (제34기 -> 부문매출 |
            영업이익), omitting the measure collapses (segment, item, period) into one key and
            **makes revenue indistinguishable from profit** (measured: 한솔홈데코 segment
            financial summary).
          - When a product group repeats across the top header (OLED | 산업용 | QD-OLED x
            제32/31/30기), taking only the 'first short header cell' drops long group names on
            the length limit, so the same period column of different groups **collides on one
            key** (measured: 한국컴퓨터).
        """
        parts: list[str] = []
        for r in range(len(header_rows)):
            if r in wide_unit_rows:
                continue
            t = re.sub(r"\s+", " ", header_rows[r][c]).strip()
            if not t or "단위" in t or _is_period_header_cell(t):
                continue
            if _PERIOD_GI_RE.search(t) or _PERIOD_YEAR_RE.search(t):
                continue
            parts.append(t)
        return " ".join(dict.fromkeys(parts))[:40] or None

    def col_period(c: int) -> tuple[Optional[str], Optional[int]]:
        label = year = None
        for r in header_rows:
            cell = r[c]
            gm = _PERIOD_GI_RE.search(cell)
            ym = _PERIOD_YEAR_RE.search(cell)
            if gm and label is None:
                label = f"제{gm.group(1)}기"
                if ym:
                    year = int(ym.group(0))
                elif max_gi is not None:
                    year = fiscal_year - (max_gi - int(gm.group(1)))
            elif ym and year is None:
                year = int(ym.group(0))
                if label is None:
                    label = f"{ym.group(0)}년"
        if label is not None:
            sub = col_sublabel(c)
            if sub:
                label = f"{label} {sub}"[:60]
        if label is None:
            # Non-period value column (asset item, country, fund category …) -> keep the header
            # text as the label (lossless).
            label = col_sublabel(c)
        return label, year

    nar_unit = _catalog_unit(ct.narrative, ct.caption_raw, grid)
    rows: list[CatalogRow] = []
    for drow in data_rows:
        labels: list[str] = []
        for c in label_cols:
            # Source cells contain embedded newlines (measured, Samsung Electronics:
            # '디스플레이 패널\nTV\nㆍ\n모니터용…'). Left as-is they break the dimension key,
            # so fold whitespace.
            v = re.sub(r"\s+", " ", drow[c]).strip()
            # Missing-value markers are not dimension labels — when an all-'-' column is
            # classified as a label column, segment/item would be filled with '-'.
            if v and v not in _PLACEHOLDERS and (not labels or labels[-1] != v):
                labels.append(v)
        # segment/item are **grouping keys**. Concatenating three or more label columns
        # (descriptive ones such as usage or supplier) makes the key differ on every row and
        # kills aggregation — keep the first two axes and leave the rest to the lossless grid
        # in biz_section_tables (same convention as biz_section).
        segment = labels[0] if labels else None
        item = labels[1] if len(labels) > 1 else None
        row_unit = drow[unit_col].strip() if unit_col is not None else None
        for c in val_cols:
            val, is_ratio, inline_unit = _parse_value(drow[c])
            if val is None:
                continue
            plabel, pyear = col_period(c)
            unit = "%" if is_ratio else (row_unit or inline_unit or nar_unit)
            rows.append(CatalogRow(
                metric=metric, segment=segment, item=item,
                period_label=plabel, period_year=pyear,
                value=val, unit=unit, is_ratio=is_ratio))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 4) Entry point — called by parse_biz_metrics
# ─────────────────────────────────────────────────────────────────────────────
def grid_key(grid: list[list[str]]) -> str:
    """Content fingerprint of a table, used to block double capture (whitespace-insensitive)."""
    return "\x1f".join("\x1e".join(c.strip() for c in row) for row in grid)


def _clip(v: Optional[str], n: int) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v[:n] if v else None


def extract_catalog_from_root(root: etree._Element, corp_code: str, fiscal_year: int,
                              start_ord: int = 0,
                              seen_grids: Optional[set[str]] = None,
                              ) -> tuple[list[dict], list[dict]]:
    """Root -> (biz_section_tables rows, biz_metrics rows).

    Pass the grid_key of **every table already captured by another parser** in `seen_grids`
    to block double loading.
    """
    seen = set(seen_grids or ())
    section_rows: list[dict] = []
    metric_rows: list[dict] = []
    ord_ = start_ord
    for ct in walk_captioned_tables(root):
        metric = classify_caption(ct.caption)
        if metric is None:
            continue
        key = grid_key(ct.grid)
        if key in seen:
            continue                       # physical table already taken by production/sales
        seen.add(key)
        mrows = map_catalog_table(ct, metric, fiscal_year)
        if not mrows:
            # Keep the raw grid even when no numbers could be interpreted (pure text tables) —
            # lossless. Continuation tables dragged in by caption inheritance are dropped
            # instead, since keeping them adds more noise than signal.
            if ct.inherited:
                continue
        section_rows.append({
            "corp_code": corp_code, "fiscal_year": fiscal_year, "table_ord": ord_,
            "metric": _clip(metric, 40),
            "narrative": (f"[{ct.subsection}] {ct.caption_raw}"
                          f"{' (연속표)' if ct.inherited else ''} :: {ct.narrative}")[:4000],
            "grid": ct.grid, "n_metric_rows": len(mrows),
        })
        for m in mrows:
            metric_rows.append({
                "corp_code": corp_code, "fiscal_year": fiscal_year, "table_ord": ord_,
                "metric": _clip(m.metric, 20), "channel": None,
                "segment": _clip(m.segment, 120), "item": _clip(m.item, 150),
                "period_label": _clip(m.period_label, 60), "period_year": m.period_year,
                "value": m.value, "unit": _clip(m.unit, 30), "is_ratio": m.is_ratio,
            })
        ord_ += 1
    return section_rows, metric_rows
