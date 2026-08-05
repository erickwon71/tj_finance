"""
roleURI -> statement (BS/IS/CF/SCE) + basis (consolidated/separate) mapping.

Reads the `.xsd` schema file (the 7th zip member alongside `.xbrl`/`_pre.xml`/
`_cal.xml`/`_def.xml`/`_lab-ko.xml`/`_lab-en.xml`) — not `_pre.xml`/`_cal.xml`
themselves, which only carry the bare roleURI on their `xlink:role` attribute.
The human-readable role text lives in the `.xsd`'s
`<link:roleType roleURI="..."><link:definition>` (Phase 0 §8, Phase 3 design
note 4 in docs/plans/xbrl_instance_parser_todo_2026-08-05.md).

Verified against both Phase 0 samples:
- every `<link:roleType>` observed is unique per roleURI (0 duplicates, both
  samples) and carries exactly one `<link:definition>`, shaped
  "[{role_id}] {definition_ko} | {definition_en}" — e.g.
  "[D210000] 재무상태표, 유동/비유동법 - 연결 | Statement of financial
  position, current/non-current - Consolidated financial statements".
- the roleURI's numeric suffix (`dart_..._role-D210000`) is a **taxonomy-version-
  scoped id**, not a stable statement code — it changes across filings/years,
  so classification here is deliberately keyword-driven off `definition_ko`,
  never off the roleURI string or the `[D...]` bracket code (Phase 0 §8).
- the "- 연결"/"- 별도" suffix on `definition_ko` is what actually
  distinguishes a **core statement role** (BS/IS/CF/SCE face financial
  statements) from a **note role** that happens to mention the same statement
  word — e.g. hanwha's "[D851100] 42. 현금흐름표" (a cash-flow-related note
  chapter) contains "현금흐름표" but has no "- 연결"/"- 별도" suffix, so it is
  correctly excluded here. Classification therefore requires BOTH a statement
  keyword AND that basis suffix; core roles are always "본문 4역할" (BS/IS/CF/
  SCE), each in at most 2 flavors (consolidated/separate) = at most 8 total
  (Phase 0 §8, confirmed in both samples: baxelbio has separate-only 4, hanwha
  has all 8).
- keyword order matters: "포괄손익계산서" (statement of comprehensive income)
  is checked before the plain "손익계산서" (income statement) fallback, since
  the former contains the latter as a substring. The plain-income-statement
  fallback exists for the two-statement IFRS presentation (separate income
  statement + separate statement of comprehensive income) — not observed in
  either Phase 0 sample (both use "단일 포괄손익계산서", single-statement
  approach) but plausible in other filings per the todo's caution against
  hardcoding report-type-specific phrasing (Phase 0 §5's general lesson).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from loguru import logger

_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_ROLE_ID_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
_BASIS_RE = re.compile(r"-\s*(연결|별도)\s*$")

# Order matters — more specific phrase first (see module docstring).
_STATEMENT_KEYWORDS: list[tuple[str, str]] = [
    ("재무상태표", "BS"),
    ("포괄손익계산서", "IS"),
    ("손익계산서", "IS"),
    ("현금흐름표", "CF"),
    ("자본변동표", "SCE"),
]

_BASIS_OF = {"연결": "consolidated", "별도": "separate"}


@dataclass(frozen=True)
class RoleInfo:
    """One classified core-statement role."""
    role_uri: str
    role_id: str          # bracketed code as-is, e.g. "D210000" — logging/debug only, not a stable key
    statement: str         # "BS" | "IS" | "CF" | "SCE"
    basis: str             # "consolidated" | "separate"
    definition_ko: str      # full Korean definition text, basis suffix included
    definition_en: str      # English half, "" if the definition had no " | " split


def _split_definition(text: str) -> tuple[str, str]:
    ko, sep, en = text.partition(" | ")
    return (ko.strip(), en.strip()) if sep else (text.strip(), "")


def classify_role_definition(role_uri: str, definition: str) -> RoleInfo | None:
    """Classify one `<link:definition>` text. Returns None for anything that
    isn't a core BS/IS/CF/SCE statement role (notes, dimensional roles, or
    anything missing a recognized "- 연결"/"- 별도" basis suffix) — those are
    out of Phase 3's scope by design (todo design note 4)."""
    definition_ko, definition_en = _split_definition(definition)

    role_id_match = _ROLE_ID_RE.match(definition_ko)
    role_id = role_id_match.group(1) if role_id_match else ""
    body = role_id_match.group(2) if role_id_match else definition_ko

    basis_match = _BASIS_RE.search(body)
    if basis_match is None:
        return None  # no "- 연결"/"- 별도" suffix -> not a core statement role

    statement = next((code for keyword, code in _STATEMENT_KEYWORDS if keyword in body), None)
    if statement is None:
        return None  # basis suffix present but no recognized statement keyword

    return RoleInfo(
        role_uri=role_uri,
        role_id=role_id,
        statement=statement,
        basis=_BASIS_OF[basis_match.group(1)],
        definition_ko=definition_ko,
        definition_en=definition_en,
    )


def build_role_map(xsd_path: Path) -> dict[str, RoleInfo]:
    """Parse a filing's `.xsd` schema into roleURI -> RoleInfo, keeping only
    core BS/IS/CF/SCE statement roles. Non-core roles (notes, dimensional
    definitions) are silently dropped — they're out of Phase 3 scope, not an
    error (todo design note 4)."""
    tree = etree.parse(str(xsd_path))
    source = str(xsd_path)
    role_map: dict[str, RoleInfo] = {}
    n_role_types = 0
    for role_type_el in tree.getroot().findall(f".//{{{_LINK_NS}}}roleType"):
        n_role_types += 1
        role_uri = role_type_el.get("roleURI")
        definition_el = role_type_el.find(f"{{{_LINK_NS}}}definition")
        if not role_uri or definition_el is None or not definition_el.text:
            continue
        info = classify_role_definition(role_uri, definition_el.text)
        if info is None:
            continue
        if role_uri in role_map:
            logger.warning(f"{source}: duplicate roleType roleURI={role_uri!r}, overwriting")
        role_map[role_uri] = info
    logger.debug(f"{source}: {n_role_types} roleType(s) total, {len(role_map)} classified as core statement roles")
    return role_map


def index_core_roles(role_map: dict[str, RoleInfo]) -> dict[tuple[str, str], RoleInfo]:
    """(statement, basis) -> RoleInfo, for callers that look up "the BS/
    separate role" directly. Phase 0 observed at most one role per
    (statement, basis) pair (at most 8 total: 4 statements x 2 basis) in both
    samples — a filing that violates this should surface via the warning
    below, not silently pick one."""
    index: dict[tuple[str, str], RoleInfo] = {}
    for info in role_map.values():
        key = (info.statement, info.basis)
        if key in index:
            logger.warning(
                f"role_map: more than one core role for statement={info.statement!r} basis={info.basis!r}: "
                f"{index[key].role_uri!r} vs {info.role_uri!r}, keeping the first"
            )
            continue
        index[key] = info
    return index
