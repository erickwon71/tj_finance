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

Phase 5-A addition (docs/plans/xbrl_instance_parser_todo_2026-08-05.md, 웰킵스하이텍
2019Q3, taxonomy vintage 2019-10-01): some older DART taxonomy vintages don't
bundle `<link:roleType>` in the filer's own `.xsd` **at all** — the package
only carries entity-specific extensions, and the 8 core BS/IS/CF/SCE role
definitions live in DART's *shared* taxonomy package, reached by following
`xsd:import`/`xsd:include` chains out to `dart.fss.or.kr` (verified 2-hop for
2019-10-01: `entry_point.xsd` -> `dart_entry_point_2019-10-01.xsd` ->
`rol_dart_2019-10-01.xsd`, walked generically here — see `_resolve_external_roles`
— rather than hardcoding that specific path, since a different vintage would
have a different chain). That shared file's `<link:definition>` text is
**English-only** (no " | " ko/en split at all — confirmed by direct fetch,
not assumed) but otherwise the same shape: "[D210000] Statement of financial
position, current/non-current - Consolidated financial statements". So
`classify_role_definition()` tries the Korean pattern first (unchanged
behaviour for every filing that has one) and falls back to an English
keyword+suffix pattern only when the Korean one doesn't match — this is
deliberately NOT keyed off the roleURI's `[D210000]`-style bracket code
(Phase 0 §8's caution against relying on that number applies here just as
much: only 2 taxonomy vintages have been checked so far, matching by
chance is not ruled out, so classification stays keyword-driven).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from loguru import logger

from parser.xbrl_instance import external_taxonomy as ext

_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_ROLE_ID_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
_BASIS_RE = re.compile(r"-\s*(연결|별도)\s*$")
_BASIS_RE_EN = re.compile(r"-\s*(Consolidated|Separate)\s+financial statements\s*$", re.IGNORECASE)

# Order matters — more specific phrase first (see module docstring).
_STATEMENT_KEYWORDS: list[tuple[str, str]] = [
    ("재무상태표", "BS"),
    ("포괄손익계산서", "IS"),
    ("손익계산서", "IS"),
    ("현금흐름표", "CF"),
    ("자본변동표", "SCE"),
]
_STATEMENT_KEYWORDS_EN: list[tuple[str, str]] = [
    ("Statement of financial position", "BS"),
    ("Statement of comprehensive income", "IS"),
    ("Income statement", "IS"),
    ("Statement of cash flows", "CF"),
    ("Statement of changes in equity", "SCE"),
]

_BASIS_OF = {"연결": "consolidated", "별도": "separate"}
_BASIS_OF_EN = {"consolidated": "consolidated", "separate": "separate"}

# Phase 5-A external fallback — bounded so a pathological/unreachable import
# graph can't turn one filing's extraction into a long hang or a fetch storm.
# Network/cache/retry plumbing itself lives in external_taxonomy.py (shared
# with taxonomy_linkbase.py::resolve_external_labels — same fallback shape).
# ★ Phase 2 (pdf_only_parser_phase2_design_2026-08-12 §A-4): 12 -> 20, modest
# headroom alongside external_taxonomy.py::dart_first()'s new filename-level
# priority sort — the sort does the real work (reaches `rol_dart_{vintage}`
# in 2-3 hops instead of ~46), this bump is just a safety margin for an
# unseen vintage whose chain is deeper than the 3 vintages checked so far.
_EXTERNAL_FETCH_BUDGET = 20


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
    anything missing a recognized basis suffix) — those are out of Phase 3's
    scope by design (todo design note 4)."""
    definition_ko, definition_en = _split_definition(definition)

    role_id_match = _ROLE_ID_RE.match(definition_ko)
    role_id = role_id_match.group(1) if role_id_match else ""
    body = role_id_match.group(2) if role_id_match else definition_ko

    basis_match = _BASIS_RE.search(body)
    if basis_match is not None:
        statement = next((code for keyword, code in _STATEMENT_KEYWORDS if keyword in body), None)
        if statement is None:
            return None  # "- 연결"/"- 별도" suffix present but no recognized statement keyword
        return RoleInfo(
            role_uri=role_uri, role_id=role_id, statement=statement,
            basis=_BASIS_OF[basis_match.group(1)],
            definition_ko=definition_ko, definition_en=definition_en,
        )

    # Phase 5-A fallback: definitions with no Korean text at all (see module
    # docstring — DART's shared external role schema for older vintages).
    # `body` still holds the (English) text in this branch since
    # `_split_definition` only assigns definition_en when a " | " was found.
    basis_match_en = _BASIS_RE_EN.search(body)
    if basis_match_en is None:
        return None  # no recognized basis suffix in either language -> not a core statement role
    statement = next((code for keyword, code in _STATEMENT_KEYWORDS_EN if keyword in body), None)
    if statement is None:
        return None
    return RoleInfo(
        role_uri=role_uri, role_id=role_id, statement=statement,
        basis=_BASIS_OF_EN[basis_match_en.group(1).lower()],
        definition_ko=definition_ko, definition_en=definition_en,
    )


def _role_types_in(root: etree._Element, source: str) -> dict[str, RoleInfo]:
    """Shared by build_role_map() (local file) and _resolve_external_roles()
    (fetched file) — classify every `<link:roleType>` under `root`."""
    role_map: dict[str, RoleInfo] = {}
    n_role_types = 0
    for role_type_el in root.findall(f".//{{{_LINK_NS}}}roleType"):
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


def _resolve_external_roles(xsd_path: Path, needed_role_uris: set[str]) -> dict[str, RoleInfo]:
    """Phase 5-A fallback — BFS the local `.xsd`'s `xsd:import`/`xsd:include`
    graph out to `dart.fss.or.kr` (via external_taxonomy.py), fetching
    (cached) external schemas until every `needed_role_uris` is resolved or
    the fetch budget runs out. Walked generically (not hardcoded to a
    specific vintage's import path) so a future taxonomy vintage with a
    different chain length still works."""
    source = str(xsd_path)
    seen: set[str] = set()
    queue: list[str] = ext.dart_first(ext.local_import_urls(xsd_path))

    found: dict[str, RoleInfo] = {}
    fetches = 0
    while queue and fetches < _EXTERNAL_FETCH_BUDGET and not needed_role_uris.issubset(found.keys()):
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        fetches += 1
        root = ext.parse(url)
        if root is None:
            continue
        # ★ filter to needed_role_uris here — DART's shared taxonomy defines
        # every *possible* presentation style (e.g. BS "current/non-current"
        # AND BS "order of liquidity" both classify as statement=BS), not
        # just the ones this filing actually uses. The local-xsd path never
        # has this problem (Phase 0: a filer's own package only ever
        # declares the handful of roles its own _pre.xml references), but
        # the shared external file is the full library — passing all of it
        # through would break index_core_roles()'s "≤1 role per (statement,
        # basis)" invariant with roles this filing doesn't even reference.
        for role_uri, info in _role_types_in(root, url).items():
            if role_uri in needed_role_uris:
                found.setdefault(role_uri, info)
        new_urls = [u for u in ext.import_urls(root, url) if u not in seen]
        queue = ext.dart_first(queue + new_urls)

    missing = needed_role_uris - found.keys()
    if missing:
        logger.warning(f"{source}: 외부 taxonomy 조회({fetches}건 fetch)로도 roleURI {len(missing)}개 "
                        f"못 찾음: {sorted(missing)}")
    else:
        logger.info(f"{source}: 외부 taxonomy 조회({fetches}건 fetch)로 필요한 roleURI {len(found)}개 전부 확인")
    return found


def has_local_role_types(xsd_path: Path) -> bool:
    """Cheap probe: does this filing's own `.xsd` carry any `<link:roleType>`
    at all? Used by report_lines_xbrl.py to decide whether label resolution
    also needs the Phase 5-A external fallback — the same taxonomy vintages
    that lack local roleType also lack local labels for standard concepts
    (see taxonomy_linkbase.py::resolve_external_labels)."""
    root = etree.parse(str(xsd_path)).getroot()
    return root.find(f".//{{{_LINK_NS}}}roleType") is not None


def build_role_map(xsd_path: Path, needed_role_uris: set[str] | None = None) -> dict[str, RoleInfo]:
    """Parse a filing's `.xsd` schema into roleURI -> RoleInfo, keeping only
    core BS/IS/CF/SCE statement roles. Non-core roles (notes, dimensional
    definitions) are silently dropped — they're out of Phase 3 scope, not an
    error (todo design note 4).

    `needed_role_uris` (Phase 5-A): if the local file yields nothing, and the
    caller tells us which roleURIs the filing's `_pre.xml` actually
    references, fall back to DART's external shared taxonomy (see
    `_resolve_external_roles`) instead of returning an empty map outright.
    Omit it (or pass an empty set) to keep pre-Phase-5-A behaviour exactly —
    every filing that already worked keeps working unchanged."""
    source = str(xsd_path)
    role_map = _role_types_in(etree.parse(source).getroot(), source)
    if not role_map and needed_role_uris:
        logger.info(f"{source}: 로컬 roleType 0건 — 외부 taxonomy 참조 시도(Phase 5-A)")
        role_map = _resolve_external_roles(xsd_path, needed_role_uris)
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
