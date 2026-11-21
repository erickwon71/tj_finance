"""R370 - foreign-currency amounts of the note tables (layer 2, printed facts only).

note_lines keeps WON amounts only (user decision 2026-10-30). The foreign amounts printed beside
them (a 'USD 2,364,000' tail, an '외화금액(USD)' column) were dropped or left in value_raw. This module
reads them into a child table `note_fx_amounts`; note_lines is not touched.

Scope (user decision 2026-11-21): the four major currencies USD / EUR / JPY / CNY (RMB is the same
code printed another way), foreign columns and paired cells, 2015+ first.

Layer 2 rules (R0-2): the number is the PRINTED number (`amount_printed`, never multiplied, never
converted to won). The table's declared scale for that currency, if the declaration names one, is
kept apart in `declared_scale` (NULL = the table does not say). The currency is a printed fact too;
`evidence` says where it was read:

  cell_code      the cell prints the code ('USD 2,364,000', '67,293,600USD 2,364,000', 'US$2,000,000')
  cell_symbol    the cell prints a symbol that names one currency ('$' -> USD, '€' -> EUR)
  header_foreign the column header says foreign amount AND names the code ('외화금액(USD)')
  row_code       the column header says foreign amount, the row label ends in the code ('JPY')
  row_foreign    the column header is the bare code, the row label says foreign amount ('외화금액')
  header_code_only  the column header is the bare code and nothing else says foreign. The cell may
                 still be a won equivalent printed under that header - a consumer decides.

Nothing is guessed: no currency resolved -> no row; header and row label naming different codes ->
no row; a row or column marked '환산'/'원화'/'환율'/'민감도' -> no row; yen/yuan signs (the same glyph prints both)
and unsupported codes are read past but not stored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

MAJOR_CODES = ("USD", "EUR", "JPY", "CNY")
_CODE_ALIAS = {"USD": "USD", "EUR": "EUR", "JPY": "JPY", "CNY": "CNY", "RMB": "CNY"}

# a printed number: grouped or plain, at most 2 decimals; '125.605' (3 decimals) is unresolved
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\d,]|\.\d)"
_ITEM_RE = re.compile(
    r"(?P<open>\()?\s*(?P<neg1>[-－])?\s*"
    r"(?P<cur>(?<![A-Za-z])US[$＄]|(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])|[$＄€￥¥£])"
    r"\s*(?P<neg2>[-－]|\()?\s*(?P<amt>" + _NUM + r")\s*(?P<close>\))?")
# what may stay in a cell besides the items: one won first line and symbol junk
_LEFTOVER_RE = re.compile(r"[\s()\-－=,.]*(?:\(?-?\d{1,3}(?:,\d{3})+\)?)?[\s()\-－=,.]*")
_PURE_NUM_RE = re.compile(r"^\(?\s*(-)?\s*(" + _NUM + r")\s*\)?$")
_NOT_AMOUNT_WORDS = ("환산", "원화", "환율", "민감도")
_CODE_IN_HEADER_RE = re.compile(r"(?<![A-Za-z])(USD|EUR|JPY|CNY|RMB)(?![A-Za-z])")

# declaration tokens with a currency: '천USD' '백만달러' '천엔' ... (scale word optional)
_FX_NAMES = {"USD": "USD", "EUR": "EUR", "JPY": "JPY", "CNY": "CNY", "RMB": "CNY",
             "달러": "USD", "유로": "EUR", "엔": "JPY", "위안": "CNY"}
_SCALE_WORDS = {"천": 1_000, "만": 10_000, "백만": 1_000_000, "억": 100_000_000}
_DECL_TOKEN_RE = re.compile(r"^(천|만|백만|억)?(USD|EUR|JPY|CNY|RMB|달러|유로|엔|위안)(천|만|백만|억)?$", re.I)


@dataclass(frozen=True)
class FxAmount:
    seq: int                     # order inside the cell
    currency: str                # USD / EUR / JPY / CNY
    amount_printed: Decimal      # as printed, never scaled
    evidence: str                # see module docstring
    declared_scale: int | None   # the table's declared multiplier for that currency, else None
    printed: str                 # the printed fragment (<= 64 chars)


@dataclass(frozen=True)
class NoteFxRow:
    """One foreign amount with the cell position it was read from (keys the DB child row)."""
    corp_code: str
    rcept_no: str
    report_fiscal_year: int
    report_fiscal_period: str
    basis: str | None
    table_seq: int | None
    row_order: int | None
    col_index: int | None
    fx: FxAmount


class ReportLineList(list):
    """The list `extract_report_lines` returns. A plain list plus the foreign amounts read from the
    same notes (`note_fx`, NoteFxRow). They live beside the lines, not in them: a cell that prints
    only 'USD 2,364,000' has no note_lines row, and the other consumers of the list must not see
    a new kind of row."""

    def __init__(self, *a):
        super().__init__(*a)
        self.note_fx: list[NoteFxRow] = []


def _norm(raw: str | None) -> str:
    t = (raw or "").replace("&cr;", " ").replace("", " ").replace("　", " ")
    return " ".join(t.split())


def _to_decimal(num: str) -> Decimal:
    return Decimal(num.replace(",", ""))


def _classify_cur(cur: str) -> tuple[str | None, str]:
    """printed currency token -> (supported ISO code or None, evidence)."""
    if cur.startswith("US"):
        return "USD", "cell_code"
    if cur in ("$", "＄"):
        return "USD", "cell_symbol"
    if cur == "€":
        return "EUR", "cell_symbol"
    if cur in _CODE_ALIAS:
        return _CODE_ALIAS[cur], "cell_code"
    return None, "cell_code"        # ￥ ¥ £ and any other code: read past, not stored


def declared_scale_for(currency: str, declaration: str | None) -> int | None:
    """The scale the table's own declaration prints for `currency` ('천USD' -> 1000, 'USD' -> 1,
    '천달러' -> 1000, '천, USD' -> 1000). None when the declaration does not name the currency."""
    if not declaration:
        return None
    t = re.sub(r"[()（）]", " ", declaration)
    t = re.sub(r"(?:외화|원화)?\s*단위\s*[:：]", " ", t)
    toks = [x for x in re.split(r"[\s,，/／]+", t) if x]
    for i, tok in enumerate(toks):
        m = _DECL_TOKEN_RE.match(tok)
        if m and _FX_NAMES.get(m.group(2).upper() if m.group(2).isascii() else m.group(2)) == currency:
            pre, post = m.group(1), m.group(3)
            if pre:
                return _SCALE_WORDS[pre]
            if post:
                return _SCALE_WORDS[post]
            if i > 0 and toks[i - 1] in _SCALE_WORDS:             # '천 USD'
                return _SCALE_WORDS[toks[i - 1]]
            if i + 1 < len(toks) and toks[i + 1] in _SCALE_WORDS:  # 'USD 천'
                return _SCALE_WORDS[toks[i + 1]]
            return 1
    return None


def _cell_items(text: str):
    """('none', []) no currency token; ('invalid', []) text beside the items; ('ok', [(cur, neg, num, span)])"""
    found = []
    for m in _ITEM_RE.finditer(text):
        neg = bool(m.group("neg1")) or (m.group("neg2") in ("-", "－")) or (
            m.group("neg2") == "(" and m.group("close") == ")")
        found.append((m.group("cur"), neg, m.group("amt"), m.span(), m.group(0)))
    if not found:
        return "none", []
    rest, pos = [], 0
    for *_, span, _g in found:
        rest.append(text[pos:span[0]])
        pos = span[1]
    rest.append(text[pos:])
    if not _LEFTOVER_RE.fullmatch(" ".join(rest).strip() or " "):
        return "invalid", []
    return "ok", found


def _header_segments(col_label: str | None) -> list[str]:
    """Header path segments without the table's unit declaration ('(단위: 천USD, 천원)')."""
    out = []
    for seg in (col_label or "").split(">"):
        s = seg.strip()
        if s.startswith("(") and "단위" in s:
            continue
        out.append(s)
    return out


def _row_code(label: str | None) -> str | None:
    last = (label or "").split(">")[-1].strip()
    m = re.fullmatch(r"[(\[]?(USD|EUR|JPY|CNY|RMB)[)\]]?", last)
    return _CODE_ALIAS[m.group(1)] if m else None


def extract_fx_cell(raw: str | None, *, label: str | None, col_label: str | None,
                    declaration: str | None = None) -> list[FxAmount]:
    """The major-currency amounts printed in one note cell. [] when the cell has none or its
    currency is not certain."""
    text = _norm(raw)
    if not text or len(text) > 200:
        return []
    decl = declaration or next((s for s in (col_label or "").split(">")
                                if s.strip().startswith("(") and "단위" in s), None)
    kind, found = _cell_items(text)
    if kind == "invalid":
        return []
    if kind == "ok":
        out = []
        for cur, neg, num, _span, whole in found:
            code, ev = _classify_cur(cur)
            if code is None:
                continue
            amt = _to_decimal(num)
            out.append(FxAmount(len(out), code, -amt if neg else amt, ev,
                                declared_scale_for(code, decl), whole.strip()[:64]))
        return out
    return _header_based(text, label, col_label, decl)


def _header_based(text: str, label: str | None, col_label: str | None, decl: str | None):
    m = _PURE_NUM_RE.match(text)
    if not m:
        return []
    segs = _header_segments(col_label)
    row_segs = [s.strip() for s in (label or "").split(">")]
    # won-equivalent rows/columns and exchange-rate / sensitivity tables are no foreign amounts
    if any(w in s for s in segs + row_segs for w in _NOT_AMOUNT_WORDS):
        return []
    codes = {_CODE_ALIAS[c] for s in segs for c in _CODE_IN_HEADER_RE.findall(s)}
    if len(codes) > 1:
        return []
    hdr = next(iter(codes)) if codes else None
    row = _row_code(label)
    if hdr and row and hdr != row:
        return []
    marked = any("외화" in s for s in segs)
    row_marked = any("외화" in s for s in row_segs)
    if hdr and marked:
        ev = "header_foreign"
    elif row and marked and not hdr:
        ev = "row_code"
    elif hdr and row_marked:
        ev = "row_foreign"
    elif hdr:
        ev = "header_code_only"
    else:
        return []
    code = hdr or row
    amt = _to_decimal(m.group(2))
    neg = bool(m.group(1)) or (text.startswith("(") and text.endswith(")"))
    return [FxAmount(0, code, -amt if neg else amt, ev, declared_scale_for(code, decl), text[:64])]
