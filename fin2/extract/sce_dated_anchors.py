"""R187 — dated sign anchors for SCE balance rows (2026-09-27, fix batch #35).

Design: `docs/plans/sce_opening_prior_period_anchor_design_2026-09-27.md`.

A SCE balance row carries its date in the label ("2013.01.01 (기초자본)", "2013.12.31
(기말자본)"). An opening balance on D equals the balance at D − 1 day, and a closing
balance on D equals the balance at D. The balance sheet prints those balances with their
signs. So a BS value at the matching date proves the sign of a SCE balance cell.

The existing anchors (`build_sign_anchors`) use only BS col 0, the current period end,
matched by magnitude. This module adds anchors keyed by `(basis, concept label, date)`:

- Stage 1, same filing: BS col 1 (and col 2 in an annual report) are the prior period
  ends. Their dates come from the SCE's own opening dates. Col 1 is the day before the
  latest block's opening, and col 2 is the day before the next older block's opening.
- Stage 2, other filings: `prior_balances`, which the loader reads from the prior periodic
  reports' BS col 0 — annual, half and quarter (R190) — (`load_prior_balances`). The
  extractor itself stays DB-free.

Guard: a date's anchors are used only when that BS's 자본총계 equals the SCE total
column at the same date. That rules out restated periods and wrong column/date mapping.
Anchors are evidence only. R162 still requires every identity to close exactly.
"""
from __future__ import annotations

import datetime
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_DATE_RE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_OPEN_RE = re.compile(r"기\s*초")
_CLOSE_RE = re.compile(r"기\s*말")
_TOTAL_COL_RE = re.compile(r"합\s*계|총\s*계")
# Note reference in a BS label: '(주20)', '(주석 21,31)' (same shape as pdf.py).
_NOTE_REF_RE = re.compile(r"\(\s*주석?\s*\d[\d,\s와과및]*\)")

# Prior-period BS balances handed in by the loader: date → [(basis, label, value)].
PriorBalances = Dict[datetime.date, List[Tuple[str, str, int]]]


def _label_date(label: str) -> Optional[datetime.date]:
    m = _DATE_RE.search(label or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def balance_anchor_date(label: str) -> Optional[datetime.date]:
    """Date whose balance a SCE balance row shows: closing D → D, opening D → D − 1 day."""
    d = _label_date(label)
    if d is None:
        return None
    if _OPEN_RE.search(label):
        return d - datetime.timedelta(days=1)
    if _CLOSE_RE.search(label):
        return d
    return None


def is_bs_equity_total(label: str) -> bool:
    norm = re.sub(r"[\s\d.ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ()]", "", label or "")
    return "부채" not in norm and (norm.endswith("자본총계") or norm.endswith("자본합계")
                                   or norm == "총자본")


def _concept(col_label: Optional[str]) -> str:
    return (col_label or "").split(">")[-1].strip()


def _sce_totals_by_date(lines: Sequence) -> Dict[Tuple[str, datetime.date], Set[int]]:
    """`(basis, date) → {SCE top total values}` from balance rows."""
    top: Dict[str, int] = {}
    for ln in lines:
        if getattr(ln, "statement", None) != "SCE" or not getattr(ln, "col_label", None):
            continue
        if _TOTAL_COL_RE.search(_concept(ln.col_label)):
            depth = ln.col_label.count(">")
            top[ln.basis] = min(depth, top.get(ln.basis, depth))
    out: Dict[Tuple[str, datetime.date], Set[int]] = defaultdict(set)
    for ln in lines:
        if (getattr(ln, "statement", None) != "SCE" or getattr(ln, "value_won", None) is None
                or not getattr(ln, "col_label", None)):
            continue
        if not _TOTAL_COL_RE.search(_concept(ln.col_label)):
            continue
        if ln.col_label.count(">") != top.get(ln.basis):
            continue
        d = balance_anchor_date(ln.label_raw or "")
        if d is not None:
            out[(ln.basis, d)].add(int(ln.value_won))
    return out


def _bs_column_dates(lines: Sequence, basis: str, annual: bool) -> Dict[int, datetime.date]:
    """BS col_index → date, from the SCE's own balance dates (col 0 = latest closing,
    col 1 = day before the latest opening, col 2 = day before the next older opening,
    annual reports only)."""
    closings, openings = set(), set()
    for ln in lines:
        if getattr(ln, "statement", None) != "SCE" or ln.basis != basis:
            continue
        label = ln.label_raw or ""
        d = _label_date(label)
        if d is None:
            continue
        if _OPEN_RE.search(label):
            openings.add(d)
        elif _CLOSE_RE.search(label):
            closings.add(d)
    out: Dict[int, datetime.date] = {}
    if closings:
        out[0] = max(closings)
    opens = sorted(openings, reverse=True)
    if opens:
        out[1] = opens[0] - datetime.timedelta(days=1)
    if annual and len(opens) > 1:
        out[2] = opens[1] - datetime.timedelta(days=1)
    return out


def add_dated_anchors(anchors: Dict, lines: Sequence,
                      prior_balances: Optional[PriorBalances] = None) -> Dict:
    """Add `(basis, label, date) → {values}` keys to `anchors` in place and return it."""
    sce_totals = _sce_totals_by_date(lines)
    if not sce_totals:
        return anchors
    period = next((getattr(ln, "report_fiscal_period", None) for ln in lines
                   if getattr(ln, "report_fiscal_period", None)), None)
    annual = period == "FY"

    def admit(basis: str, date: datetime.date, rows: Iterable[Tuple[str, int]]) -> None:
        rows = list(rows)
        totals = {v for label, v in rows if is_bs_equity_total(label)}
        if not totals or not (totals & sce_totals.get((basis, date), set())):
            return                      # restated / mismatched period — no evidence
        for label, v in rows:
            if label:
                anchors.setdefault((basis, label, date), set()).add(v)
                # R190 — BS labels carry note refs ('자본금 (주20)'); the SCE column concept
                # does not (넵튠 `20210817001798`). Key the stripped label as well.
                bare = _NOTE_REF_RE.sub("", label).strip()
                if bare and bare != label:
                    anchors.setdefault((basis, bare, date), set()).add(v)

    # Stage 1 — this filing's BS prior-period columns (and col 0 under its date).
    by_col: Dict[Tuple[str, int], List[Tuple[str, int]]] = defaultdict(list)
    for ln in lines:
        if getattr(ln, "statement", None) != "BS" or getattr(ln, "value_won", None) is None:
            continue
        ci = getattr(ln, "col_index", None)
        if ci is None or ci > 2:
            continue
        by_col[(ln.basis, ci)].append(((ln.label_raw or "").strip(), int(ln.value_won)))
    for basis in {b for b, _ in by_col}:
        for ci, date in _bs_column_dates(lines, basis, annual).items():
            if (basis, ci) in by_col:
                admit(basis, date, by_col[(basis, ci)])

    # Stage 2 — prior periodic reports (annual + interim, R190) supplied by the loader.
    for date, rows in (prior_balances or {}).items():
        per_basis: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for basis, label, v in rows:
            per_basis[basis].append(((label or "").strip(), int(v)))
        for basis, brows in per_basis.items():
            if (basis, date) in sce_totals:
                admit(basis, date, brows)
    return anchors


def load_prior_balances(session, corp_code: str, rcept_no: str, years: int = 3) -> PriorBalances:
    """Loader-side (DB) helper for stage 2: BS col 0 of this company's periodic reports
    (annual, half, quarter) whose period ends before this filing's, within `years` years.
    For each period end, the latest rcept that has BS lines (amendments included).

    R190 (2026-09-27) — interim reports too. A comparative SCE block ends on a quarter or
    half-year date (씨에스베어링 `20220516002123` 2021.03.31, 넵튠 `20210817001798`
    2020.06.30); with annual BS only, those balances had no anchor and R162-e picked a
    mirror solution."""
    from sqlalchemy import text

    rows = session.execute(text("""
        WITH me AS (SELECT period_end_date FROM filings WHERE rcept_no = :r),
        prior AS (
            SELECT f.period_end_date, max(f.rcept_no) AS rcept_no
            FROM filings f, me
            WHERE f.corp_code = :c
              AND f.period_end_date IS NOT NULL AND f.period_end_date < me.period_end_date
              AND f.period_end_date >= me.period_end_date - (:n * interval '1 year')
              AND f.rcept_no <> :r
              AND EXISTS (SELECT 1 FROM report_lines l WHERE l.rcept_no = f.rcept_no
                          AND l.statement = 'BS')
            GROUP BY f.period_end_date)
        SELECT p.period_end_date, l.basis, l.label_raw, l.value_won
        FROM prior p JOIN report_lines l ON l.rcept_no = p.rcept_no
        WHERE l.statement = 'BS' AND l.col_index = 0 AND l.value_won IS NOT NULL"""),
        {"r": rcept_no, "c": corp_code, "n": years}).fetchall()
    out: PriorBalances = defaultdict(list)
    for date, basis, label, value in rows:
        out[date].append((basis, label, int(value)))
    return dict(out)


# Prior-period income-statement amounts handed in by the loader (R189-b):
# (period start, period end) → [(basis, label, value)].
PriorIncome = Dict[Tuple[datetime.date, datetime.date], List[Tuple[str, str, int]]]


def block_period(lines: Sequence, target) -> Optional[Tuple[datetime.date, datetime.date]]:
    """`(opening date, closing date)` of the SCE block (in `target`'s column) that holds
    `target`'s row, from the block's own balance labels."""
    col = sorted((ln for ln in lines if getattr(ln, "statement", None) == "SCE"
                  and ln.basis == target.basis
                  and getattr(ln, "table_seq", None) == getattr(target, "table_seq", None)
                  and ln.col_index == target.col_index and ln.row_order is not None),
                 key=lambda l: l.row_order)
    open_d = None
    for ln in col:
        label = ln.label_raw or ""
        if _OPEN_RE.search(label):
            open_d = _label_date(label) if ln.row_order <= target.row_order else open_d
        elif _CLOSE_RE.search(label) and ln.row_order >= target.row_order:
            close_d = _label_date(label)
            return (open_d, close_d) if open_d and close_d else None
    return None


def load_prior_income(session, corp_code: str, rcept_no: str, years: int = 3) -> PriorIncome:
    """Loader-side (DB) helper for R189-b: IS amounts of this company's earlier reports
    (annual full year, interim cumulative year-to-date), keyed by their period. The period
    start is the day after the latest annual period end before it (fiscal year start).

    R192 (2026-09-28) — only reports that have IS lines, as `load_prior_balances` does for
    BS: CMG제약 2013 사업보고서 `20140331000231` lost to its later '[첨부정정]'
    `20140407000591` (no IS lines), so the 2013 period had no evidence at all."""
    from sqlalchemy import text

    rows = session.execute(text("""
        WITH me AS (SELECT period_end_date FROM filings WHERE rcept_no = :r),
        prior AS (
            SELECT f.period_end_date, f.report_type, max(f.rcept_no) AS rcept_no
            FROM filings f, me
            WHERE f.corp_code = :c AND f.period_end_date IS NOT NULL
              AND f.period_end_date < me.period_end_date
              AND f.period_end_date >= me.period_end_date - (:n * interval '1 year')
              AND f.rcept_no <> :r
              AND EXISTS (SELECT 1 FROM report_lines l WHERE l.rcept_no = f.rcept_no
                          AND l.statement = 'IS')
            GROUP BY f.period_end_date, f.report_type)
        SELECT p.period_end_date, p.report_type, l.basis, l.label_raw, l.value_won
        FROM prior p JOIN report_lines l ON l.rcept_no = p.rcept_no
        WHERE l.statement = 'IS' AND l.col_index = 0 AND l.value_won IS NOT NULL
          AND (p.report_type = 'annual' OR l.is_cumulative)"""),
        {"r": rcept_no, "c": corp_code, "n": years + 1}).fetchall()
    annual_ends = session.execute(text("""
        SELECT DISTINCT period_end_date FROM filings
        WHERE corp_code = :c AND report_type = 'annual' AND period_end_date IS NOT NULL"""),
        {"c": corp_code}).scalars().all()
    out: PriorIncome = defaultdict(list)
    for end, rtype, basis, label, value in rows:
        before = [d for d in annual_ends if d < end]
        start = (max(before) + datetime.timedelta(days=1)) if before else datetime.date(end.year, 1, 1)
        out[(start, end)].append((basis, label, int(value)))
    return dict(out)


def load_prior_evidence(session, corp_code: str, rcept_no: str) -> Tuple[PriorBalances, PriorIncome]:
    """Both loader-side evidence sets for `extract_report_lines(prior_balances=, prior_income=)`."""
    return (load_prior_balances(session, corp_code, rcept_no),
            load_prior_income(session, corp_code, rcept_no))
