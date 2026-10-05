"""API→문서 전환 — 계층3 원문판 10개 테이블 동기화 (docs/plans/api_to_document_migration_plan_2026-10-05.md).

계층2 `doc_section_tables` → 계층3 매퍼(`fin2/layer3/doc_*.py`) → 기존 테이블(이름·컬럼 유지, 앱 무변경):
  dividend_facts · major_shareholders · shareholder_changes · retail_ownership · executives ·
  employee_stats · exec_pay_summary · exec_pay_individual · other_investments · treasury_activity

회사 단위로 fiscal_year >= fy_min 행을 지우고 원문판을 넣는다(delete-then-insert, 멱등). 원문에
표가 없는 (회사, 연도)는 행을 만들지 않는다 — API 판에만 있던 행은 이 동기화 후 사라진다
(검증 단계에서 건수·원인 보고, PDF-only 필링 등).

`executives.compensation` 은 같은 연도 '이사·감사 개인별 보수현황'(SUB_CMPK)에서 이름으로 붙인다
(API 판의 hmvAuditIndvdlBySttus 조인과 같은 의미).
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.layer3 import (doc_dividend, doc_investments, doc_pay, doc_people, doc_shareholders,
                         doc_treasury)
from fin2.layer3.doc_common import norm

# Unique keys of the target tables (pg_constraint). A source roster can list the same person
# twice (00101220 2015 '전석규 상무이사'); keep the first row like the API path effectively did.
# Rows whose key has a NULL are never duplicates (PostgreSQL semantics).
_UNIQUE_KEYS = {
    "executives": ("corp_code", "fiscal_year", "name", "position"),
    "major_shareholders": ("corp_code", "fiscal_year", "name", "relation", "stock_kind"),
    "retail_ownership": ("corp_code", "fiscal_year"),
    "dividend_facts": ("corp_code", "fiscal_year"),
    "exec_pay_summary": ("corp_code", "fiscal_year"),
}


def _dedup(table: str, rows: list[dict]) -> tuple[list[dict], int]:
    key = _UNIQUE_KEYS.get(table)
    if not key:
        return rows, 0
    seen, out = set(), []
    for r in rows:
        k = tuple(r.get(c) for c in key)
        if None not in k:
            if k in seen:
                continue
            seen.add(k)
        out.append(r)
    return out, len(rows) - len(out)


TABLES = ("dividend_facts", "major_shareholders", "shareholder_changes", "retail_ownership",
          "executives", "employee_stats", "exec_pay_summary", "exec_pay_individual",
          "other_investments", "treasury_activity")


def build_all(session, corps: list[str], fy_min: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {t: [] for t in TABLES}
    out["dividend_facts"] = doc_dividend.build_dividend_rows(session, corps, fy_min)
    out.update(doc_shareholders.build_rows(session, corps, fy_min))
    people = doc_people.build_rows(session, corps, fy_min)
    pay = doc_pay.build_rows(session, corps, fy_min)
    comp = pay.pop("compensation")
    for r in people["executives"]:
        r["compensation"] = comp.get((r["corp_code"], r["fiscal_year"], norm(r["name"])))
    out.update(people)
    out.update(pay)
    out["other_investments"] = doc_investments.build_rows(session, corps, fy_min)
    out["treasury_activity"] = doc_treasury.build_rows(session, corps, fy_min)
    return out


def _executives_rcepts(session, corps: list[str], fy_min: int) -> dict[tuple[str, int], str]:
    from fin2.layer3.doc_common import pick_filing_grids
    return {k: v[0] for k, v in pick_filing_grids(session, corps, "SH5_DRCT_STT", fy_min).items()}


def store_all(session, corps: list[str], rows: dict[str, list[dict]], fy_min: int) -> dict:
    now = datetime.utcnow()
    ex_rcepts = _executives_rcepts(session, corps, fy_min)
    for r in rows["executives"]:
        r.setdefault("rcept_no", ex_rcepts.get((r["corp_code"], r["fiscal_year"])))
    counts = {}
    for table in TABLES:
        session.execute(text(f"DELETE FROM {table} WHERE corp_code = ANY(:c) "
                             f"AND fiscal_year >= :y"), {"c": corps, "y": fy_min})
        batch, dropped = _dedup(table, rows.get(table) or [])
        if dropped:
            logger.debug(f"[doc_sections] {table}: {dropped} duplicate-key row(s) skipped")
        if batch:
            cols = sorted({k for r in batch for k in r} | {"fetched_at"})
            stmt = text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                        f"({', '.join(':' + c for c in cols)})")
            if any(c in ("raw", "pay_detail") for c in cols):
                from sqlalchemy.dialects.postgresql import JSONB
                from sqlalchemy import bindparam
                stmt = stmt.bindparams(*[bindparam(c, type_=JSONB) for c in cols
                                         if c in ("raw", "pay_detail")])
            session.execute(stmt, [{**{c: None for c in cols}, **r, "fetched_at": now}
                                   for r in batch])
        counts[table] = len(batch)
    return counts


def sync_doc_sections(corps: list[str], fy_min: int = 2015, chunk: int = 100) -> dict:
    """Rebuild the 10 tables for `corps` (fiscal_year >= fy_min) from layer-2 tables."""
    total = {t: 0 for t in TABLES}
    if not corps:
        return total
    corps = sorted(set(corps))
    with get_session() as s:
        for i in range(0, len(corps), chunk):
            part = corps[i:i + chunk]
            counts = store_all(s, part, build_all(s, part, fy_min), fy_min)
            s.commit()
            for t, n in counts.items():
                total[t] += n
            if (i // chunk) % 5 == 0:
                logger.info(f"[doc_sections] {min(i + chunk, len(corps)):,}/{len(corps):,} corps")
    return total
