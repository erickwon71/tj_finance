"""Report source selection — the single place that decides WHICH filings a parser reads.

docs/PARSING_RULES.md R0 / R2-0 / R2.

The rule
--------
A period (corp, report_type, fiscal_year, fiscal_period) can have several filings: the
original plus amendments. **All of them are sources.** They are returned oldest-first so a
caller can parse each with the SAME parser and let later items override earlier ones.

`is_final` must NEVER be used to filter parsing sources. It only marks "the newest filing in
the group" and says nothing about completeness — an `[첨부정정]` carries no report body at all
yet still takes the flag (measured 2026-07-31: 547 is_final annual reports have no XML body,
447 companies; 505 of them have a sibling filing whose body IS on disk).

Measured scope of each amendment kind (2026-08-01, 260 amendment filings):

    [기재정정]  249건 — 본문 포함 99.6%   ← the periodic-report body correction we care about
    [첨부추가]    7건 — 본문 포함 100%
    [첨부정정]    4건 — 본문 포함   0%    ← audit report / opinions / articles only

Callers must not special-case those labels: just parse whatever a filing actually contains and
skip what it does not (R0). The labels above are documentation, not control flow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text


@dataclass(frozen=True)
class SourceFiling:
    """One filing that a parser should read."""
    rcept_no: str
    file_path: str
    fiscal_year: int
    fiscal_period: str
    report_nm: str
    is_final: bool          # informational only — never a filter


_SQL = """
    SELECT f.rcept_no, dt.file_path, f.fiscal_year, f.fiscal_period,
           COALESCE(f.report_nm, '') AS report_nm, COALESCE(f.is_final, FALSE) AS is_final
    FROM filings f
    JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    WHERE f.corp_code = :corp
      AND f.report_type = :rtype
      AND dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
      {year_clause}
    ORDER BY f.fiscal_year DESC, f.fiscal_period,
             f.filed_at ASC NULLS FIRST, f.rcept_no ASC
"""


def period_groups(session, corp_code: str, report_type: str = "annual",
                  year: Optional[int] = None,
                  latest_only: bool = False) -> list[list[SourceFiling]]:
    """Filings grouped by reporting period, each group **oldest-first**.

    Returns [[original, amendment1, amendment2, ...], ...] — newest period first.
    A group with a single element is simply a period that was never amended.

    `latest_only` keeps only the most recent period (used by the daily pipeline, which only
    needs to refresh what just arrived) — it still returns that period's FULL chain.
    """
    sql = _SQL.format(year_clause="AND f.fiscal_year = :year" if year is not None else "")
    params: dict = {"corp": corp_code, "rtype": report_type}
    if year is not None:
        params["year"] = year

    groups: dict[tuple[int, str], list[SourceFiling]] = {}
    order: list[tuple[int, str]] = []
    for r in session.execute(text(sql), params).fetchall():
        key = (r.fiscal_year, r.fiscal_period)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(SourceFiling(
            rcept_no=r.rcept_no, file_path=r.file_path, fiscal_year=r.fiscal_year,
            fiscal_period=r.fiscal_period, report_nm=r.report_nm, is_final=bool(r.is_final)))

    out = [groups[k] for k in order]
    return out[:1] if (latest_only and out) else out
