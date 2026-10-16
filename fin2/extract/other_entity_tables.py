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
_ABSORBED = re.compile(r"흡수합병된\s*([^\s의]{1,30}(?:\s*주식회사)?)의[^.]{0,40}재무제표")
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
            m = _ABSORBED.search(re.sub(r"\s+", " ", text.replace("&cr;", " ")))
            if m:
                return normalize_entity(m.group(1))
    return None


def drop_other_entity_tables(root, groups: dict) -> tuple[dict, list[tuple[str, str, str]]]:
    """Remove later tables of a section code that follow a marker for a different entity.

    ``groups`` is ``{section_code: [(table, unit, section_kind), ...]}``. Returns the filtered
    dict (same order) and ``[(section_code, kept_entity, dropped_entity), ...]``.
    """
    wanted = {id(t) for tws in groups.values() for t, _, _ in tws}
    if not wanted:
        return groups, []
    entity_at: dict[int, str | None] = {}
    pos_of: dict[int, int] = {}
    current: str | None = None
    seen = 0
    for el in root.iter():
        if id(el) in wanted:
            entity_at[id(el)] = current
            pos_of[id(el)] = seen
            seen += 1
            if seen == len(wanted):
                break
            continue
        name = _marker_of(el)
        if name:
            current = name
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
