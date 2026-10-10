"""Korean taxonomy label -> XBRL concept (R229, 2026-10-10).

Printed statements (DART XML, web-viewer print, PDF) carry no concept: the XML's ACODE
attributes tag form fields (CS_DIV, SH5_* ...), never statement lines. The layer-3 mapper
therefore reads only the printed label, and a label the alias catalog (account_maps) does not
list is lost — e.g. the IFRS standard label '영업권 이외의 무형자산'
(ifrs-full_IntangibleAssetsOtherThanGoodwill): ~30k FY2015+ periods printed it and had
std_financials_v3.intangibles NULL. Filers compose statements in the DART editor from the
taxonomy, so the printed label is very often the taxonomy's own Korean label.

The index (ko_label_index.json, built by scripts/build_ko_label_index.py from the DART
taxonomy Korean label linkbases) maps a whitespace-free normalized label to the concepts that
carry it as a standard / terse / total label. A label is used only when every concept that
carries it resolves to one and the same canonical (fin2/taxonomy/concept_map.py, audit-only
concepts excluded) — a label shared by concepts with different (or no) canonicals is
ambiguous and ignored.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fin2.taxonomy.concept_map import AUDIT_ONLY_CONCEPTS, map_acode

INDEX_PATH = Path(__file__).with_name("ko_label_index.json")
_WS_RE = re.compile(r"\s+")


def label_key(label: str) -> str:
    """Normalized, whitespace-free key shared by the index builder and the lookup."""
    from parser.common.amount_normalizer import normalize_account_name
    return _WS_RE.sub("", normalize_account_name(label or ""))


@lru_cache(maxsize=1)
def _index() -> dict[str, list[str]]:
    if not INDEX_PATH.exists():
        return {}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=65536)
def canonical_for_label(label: str) -> str | None:
    """The single canonical every concept carrying this Korean label maps to, else None."""
    concepts = _index().get(label_key(label))
    if not concepts:
        return None
    canons = {None if c in AUDIT_ONLY_CONCEPTS else map_acode(c) for c in concepts}
    if len(canons) != 1:
        return None
    return canons.pop()
