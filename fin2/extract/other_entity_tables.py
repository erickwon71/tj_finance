"""R245 — body statement tables that belong to another legal entity are not the filer's.

A merger report (SPAC merger, absorbed company) can print the statements of two legal
entities in the same body section. The extractor files both under the filer's basis, so the
second entity's statement loads as extra ``table_seq`` rows of the filer.

The reporting entity is the one the FIRST table of each section code (basis + statement)
belongs to. A later table of the same code is dropped only when an entity marker printed
between the two names a different entity. A table with no marker before it is the filer's.

Entity markers (printed text, in document order; the latest one before a table applies):
  * a bracket-only heading naming a company: ``[주식회사 밸로프]``, ``[합병법인 X]``,
    ``[피합병법인 Y]``
  * the sentence ``…에 흡수합병된 X의 … 재무제표입니다`` (the absorbed company's statements)
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_ROLE = r"(?:합병법인|피합병법인|합병회사|피합병회사|분할법인|분할신설법인|존속법인|소멸법인)"
_COMPANY_HINT = re.compile(r"주식회사|\(주\)|㈜|기업인수목적|스팩|SPAC")
_BRACKET = re.compile(rf"^\[\s*(?:({_ROLE})\s+)?([^\[\]]{{2,60}}?)\s*\]$")
_R272_ABSORBED_WITH_SUBSIDIARIES = True   # `…삼양제넥스와 그 종속기업의 … 연결재무제표`
_ABSORBED = re.compile(r"흡수합병된\s*([^\s의]{1,30}(?:\s*주식회사)?)의[^.]{0,40}재무제표")
_ABSORBED_GROUP = re.compile(r"흡수합병된\s*([^\s의와과]{1,30})[와과]\s*그\s*종속기업의[^.]{0,40}재무제표")
_NOISE = re.compile(r"주식회사|\(주\)|㈜|\s+")


def normalize_entity(name: str) -> str:
    return _NOISE.sub("", name).strip()


def _marker_of(el) -> str | None:
    """Entity name this element announces, or None."""
    if el.tag in ("P", "SPAN", "TD", "TU", "TITLE"):
        text = (el.text or "").strip()
        if text and len(text) <= 80:
            m = _BRACKET.match(text)
            if m and (m.group(1) or _COMPANY_HINT.search(m.group(2))):
                return normalize_entity(m.group(2))
    if el.tag == "P":
        text = "".join(el.itertext())
        if "흡수합병된" in text and len(text) <= 200:
            flat = re.sub(r"\s+", " ", text.replace("&cr;", " "))
            m = _ABSORBED.search(flat)
            if not m and _R272_ABSORBED_WITH_SUBSIDIARIES:
                m = _ABSORBED_GROUP.search(flat)
            if m:
                return normalize_entity(m.group(1))
    return None


def _is_group_marker(el) -> bool:
    """True for the `…와 그 종속기업의 … 재무제표` sentence (R272), which scopes to one basis."""
    if el.tag != "P":
        return False
    flat = re.sub(r"\s+", " ", "".join(el.itertext()).replace("&cr;", " "))
    return bool(_ABSORBED_GROUP.search(flat)) and not _ABSORBED.search(flat)


def drop_other_entity_tables(root, groups: dict) -> tuple[dict, list[tuple[str, str, str]]]:
    """Remove later tables of a section code that follow a marker for a different entity.

    ``groups`` is ``{section_code: [(table, unit, section_kind), ...]}``. Returns the filtered
    dict (same order) and ``[(section_code, kept_entity, dropped_entity), ...]``.
    """
    wanted = {id(t) for tws in groups.values() for t, _, _ in tws}
    if not wanted:
        return groups, []
    basis_of = {id(t): code.rsplit("_", 1)[-1] for code, tws in groups.items() for t, _, _ in tws}
    last_basis: str | None = None
    scoped = False
    entity_at: dict[int, str | None] = {}
    pos_of: dict[int, int] = {}
    current: str | None = None
    seen = 0
    for el in root.iter():
        if id(el) in wanted:
            basis = basis_of.get(id(el))
            if _R272_ABSORBED_WITH_SUBSIDIARIES and scoped and basis in ("C", "S"):
                # a marker scopes to its own consolidated/separate run of tables; the filer's
                # other-basis statements that follow carry no marker of their own
                if last_basis is not None and basis != last_basis:
                    current = None
                    scoped = False
                last_basis = basis
            entity_at[id(el)] = current
            pos_of[id(el)] = seen
            seen += 1
            if seen == len(wanted):
                break
            continue
        name = _marker_of(el)
        if name:
            current = name
            scoped = _R272_ABSORBED_WITH_SUBSIDIARIES and _is_group_marker(el)
            last_basis = None
    out: dict[str, list] = {}
    dropped: list[tuple[str, str, str]] = []
    for code, tws in groups.items():
        # document order of tables is the order they were collected in
        ordered = sorted(tws, key=lambda x: pos_of.get(id(x[0]), 0))
        first = entity_at.get(id(ordered[0][0])) if ordered else None
        kept = []
        for tw in tws:
            ent = entity_at.get(id(tw[0]))
            if ent is not None and first is not None and ent != first:
                dropped.append((code, first, ent))
                continue
            if ent is not None and first is None and tw is not ordered[0]:
                # first table carries no marker (the filer's own); a named later table is another entity
                dropped.append((code, "", ent))
                continue
            kept.append(tw)
        if kept:
            out[code] = kept
    return out, dropped
