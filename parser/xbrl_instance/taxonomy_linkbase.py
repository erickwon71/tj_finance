"""
XBRL taxonomy linkbase parser: presentation (`_pre.xml`), label (`_lab-ko.xml` /
`_lab-en.xml`) and calculation (`_cal.xml`) linkbases — the 3 of the 7 zip
files (besides the `.xbrl` instance itself) needed to turn raw facts into a
statement structure. `_def.xml` (dimensional definitions) is not parsed here —
basis/segment interpretation is done from context dimensions directly in
`instance_parser.py` (Phase 0 §4).

Verified against real filings (see docs/plans/xbrl_instance_parser_todo_2026-08-05.md,
"Phase 0 결과" §8-11, and the follow-up structural survey done for Phase 3-3):
- A concept's locator href fragment (e.g. "...xsd#ifrs-full_CurrentAssets") is
  "{prefix}_{LocalName}"; the prefix never itself contains "_" (observed:
  ifrs-full, dart, dart-gcd, entity{CIK}) so splitting on the first "_" is
  reliable, including for entity-extension names that contain further
  underscores (e.g. "entity01335851_udf_CF_..."). The linkbase files never
  declare these namespaces themselves — only the instance document's root does
  (Phase 0 §3) — so callers must supply that nsmap.
- roleURI -> statement (BS/IS/CF/SCE/note) mapping is NOT done here: the
  human-readable `link:definition` text lives in the `.xsd`, not in these
  linkbase files (role_map.py, Phase 3-4, reads the `.xsd` separately). This
  module just exposes each presentation/calculation tree keyed by its roleURI.
- within one presentationLink/calculationLink, `xlink:label` locator ids are
  unique (verified: 0 duplicates across both Phase 0 samples), but the SAME
  concept can appear at more than one tree position under DIFFERENT locator
  ids (observed in note rollforward tables: opening/closing balance rows reuse
  one element with distinct `_periodStartLabel`/`_periodEndLabel` locators) —
  so tree nodes are keyed by locator id, never by concept alone.
- every role observed in both samples (36 roles total) has exactly 1 root
  (a locator that is never an arc's `to`) — typically a `...Abstract` element.
  The 4 core statement roles (BS/IS/CF/SCE, `D210`/`D431`/`D520`/`D610`) are
  always clean single-parent trees in both samples. Note/dimensional roles
  (`D8xxxxx`/`U8xxxxx`, out of scope for now — see role_map.py) can have a
  node reachable via more than one parent arc (e.g. a shared Axis referenced
  from multiple Table locators) — `_build_tree_shape()` keeps the first arc
  and logs a warning for those; this is expected noise on those roles, not a
  parse error, and does not occur on the 4 core roles.
- `order` is a float, not an int (values like "1.5", "12.8" observed);
  `priority` was uniformly "0" and no `use="prohibited"` arcs were observed in
  either sample, so arc-suppression handling is not implemented.
- `preferredLabel` (on a presentationArc) names the label *role* URI to prefer
  when rendering that tree position — read verbatim here, resolved against the
  label catalog by the caller.
- label linkbases carry exactly one `<link:labelLink>` covering the whole
  taxonomy (not one per role like presentation/calculation), with locator ids
  unique per file; `_lab-ko.xml` and `_lab-en.xml` share this same schema and
  differ only in which `xml:lang` their `<link:label>` resources use — parse
  both and merge with `merge_label_catalogs()`.
- calculation-linkbase `weight` is parsed here but, per Phase 0 §11, is not
  needed to interpret stored fact values (they're already sign-correct as
  displayed) — its purpose is downstream identity-equation validation
  (Phase 6), not value transformation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from loguru import logger

from .instance_parser import QName

_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_XML_NS = "http://www.w3.org/XML/1998/namespace"


def _q(local: str) -> str:
    return f"{{{_LINK_NS}}}{local}"


def _xlink(el: etree._Element, attr: str) -> str | None:
    return el.get(f"{{{_XLINK_NS}}}{attr}")


def resolve_href_fragment(href: str, nsmap: dict[str, str]) -> QName:
    """Resolve a linkbase locator's href (e.g.
    "http://.../full_ifrs-cor_2021-03-24.xsd#ifrs-full_CurrentAssets") into a
    QName, using the DART/IFRS taxonomy convention that the URL fragment is
    "{prefix}_{LocalName}" (Phase 0 §3/§8). `nsmap` must map that prefix to its
    namespace URI — pass the instance document's `XbrlInstance.nsmap`, which
    always declares all prefixes seen in practice (ifrs-full, dart, dart-gcd,
    entity{CIK})."""
    fragment = href.rpartition("#")[2]
    if not fragment:
        raise ValueError(f"href has no '#fragment': {href!r}")
    prefix, sep, local = fragment.partition("_")
    if not sep:
        raise ValueError(f"fragment isn't '{{prefix}}_{{local}}' shaped: {fragment!r}")
    ns = nsmap.get(prefix)
    if ns is None:
        raise ValueError(f"namespace prefix {prefix!r} not declared in nsmap (fragment={fragment!r})")
    return QName(ns=ns, local=local)


def _parse_locs(link_el: etree._Element, nsmap: dict[str, str], source: str) -> dict[str, QName]:
    """Parse all <link:loc> children of one extended link into locator id -> concept."""
    locs: dict[str, QName] = {}
    for loc_el in link_el.findall(_q("loc")):
        label = _xlink(loc_el, "label")
        href = _xlink(loc_el, "href")
        if not label or not href:
            raise ValueError(f"{source}: <link:loc> missing xlink:label/href")
        if label in locs:
            logger.warning(f"{source}: duplicate loc id {label!r} in one extended link, overwriting")
        locs[label] = resolve_href_fragment(href, nsmap)
    return locs


def _build_tree_shape(
    arcs: list[tuple[str, str, float]], locs: dict[str, QName], source: str
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, float]]:
    """Shared parent/child-with-order logic for presentation and calculation
    trees (both are plain loc/arc/order extended links). Returns
    (parent_of, children_of, order_of), all keyed by locator id; children_of
    values are order-sorted."""
    parent_of: dict[str, str] = {}
    order_of: dict[str, float] = {}
    pending_children: dict[str, list[tuple[str, float]]] = {}
    for frm, to, order in arcs:
        if frm not in locs or to not in locs:
            logger.warning(f"{source}: arc references undeclared loc ({frm!r} -> {to!r}), skipped")
            continue
        if to in parent_of:
            logger.warning(f"{source}: {to!r} has more than one parent arc in this role, keeping the first")
            continue
        parent_of[to] = frm
        order_of[to] = order
        pending_children.setdefault(frm, []).append((to, order))
    children_of = {
        frm: [label for label, _ in sorted(pairs, key=lambda pair: pair[1])]
        for frm, pairs in pending_children.items()
    }
    return parent_of, children_of, order_of


def _compute_depths(roots: list[str], children_of: dict[str, list[str]]) -> dict[str, int]:
    """0-based depth via DFS from the tree's roots. Real DART presentation/
    calculation trees are acyclic (parent_of is single-valued per node), so
    the `already visited` guard is defensive only."""
    depths: dict[str, int] = {}
    stack: list[tuple[str, int]] = [(root, 0) for root in roots]
    while stack:
        label, depth = stack.pop()
        if label in depths:
            continue
        depths[label] = depth
        for child in children_of.get(label, []):
            stack.append((child, depth + 1))
    return depths


@dataclass
class PresentationNode:
    """One position in a presentation (`_pre.xml`) role's tree. A concept can
    occupy more than one position within the same role (Phase 3-3 survey:
    note rollforward tables reuse one element for opening/closing balance rows
    with distinct locators) — nodes are therefore keyed by the linkbase's own
    `xlink:label` wiring id (`loc_label`), never by `element` alone."""
    loc_label: str
    element: QName
    order: float                  # arc order among this node's siblings; 0.0 for roots (no parent arc)
    preferred_label: str | None   # xlink:role URI from the parent arc's `preferredLabel` attr, if any
    parent_loc_label: str | None
    depth: int
    children: list[str] = field(default_factory=list)  # loc_labels, order-sorted


@dataclass
class PresentationTree:
    role_uri: str
    nodes: dict[str, PresentationNode]
    roots: list[str]  # loc_labels with no parent arc in this tree (every role observed so far has exactly 1)


@dataclass
class CalculationNode:
    """Mirrors PresentationNode's shape (Phase 0 §11: weight doesn't transform
    stored values, so this tree is for Phase 6 identity-equation validation,
    not extraction)."""
    loc_label: str
    element: QName
    order: float
    weight: float                 # +1 / -1 observed; from the summation-item arc pointing at this node
    parent_loc_label: str | None
    depth: int
    children: list[str] = field(default_factory=list)


@dataclass
class CalculationTree:
    role_uri: str
    nodes: dict[str, CalculationNode]
    roots: list[str]


def _parse_presentation_link(link_el: etree._Element, nsmap: dict[str, str], source: str) -> PresentationTree:
    role_uri = _xlink(link_el, "role")
    if not role_uri:
        raise ValueError(f"{source}: <link:presentationLink> missing xlink:role")
    locs = _parse_locs(link_el, nsmap, source)

    arcs: list[tuple[str, str, float]] = []
    preferred_of: dict[str, str] = {}  # to_label -> preferredLabel role URI
    for arc_el in link_el.findall(_q("presentationArc")):
        frm, to = _xlink(arc_el, "from"), _xlink(arc_el, "to")
        order_raw = arc_el.get("order")
        if not frm or not to or order_raw is None:
            raise ValueError(f"{source}: <link:presentationArc> missing from/to/order")
        arcs.append((frm, to, float(order_raw)))
        preferred = arc_el.get("preferredLabel")
        if preferred:
            preferred_of[to] = preferred

    parent_of, children_of, order_of = _build_tree_shape(arcs, locs, source)
    roots = [label for label in locs if label not in parent_of]
    depths = _compute_depths(roots, children_of)

    nodes = {
        label: PresentationNode(
            loc_label=label,
            element=element,
            order=order_of.get(label, 0.0),
            preferred_label=preferred_of.get(label),
            parent_loc_label=parent_of.get(label),
            depth=depths.get(label, 0),
            children=children_of.get(label, []),
        )
        for label, element in locs.items()
    }
    return PresentationTree(role_uri=role_uri, nodes=nodes, roots=roots)


def parse_presentation(path: Path, nsmap: dict[str, str]) -> dict[str, PresentationTree]:
    """Parse a `_pre.xml` presentation linkbase into role URI -> tree."""
    tree = etree.parse(str(path))
    source = str(path)
    trees: dict[str, PresentationTree] = {}
    for link_el in tree.getroot().findall(_q("presentationLink")):
        ptree = _parse_presentation_link(link_el, nsmap, source)
        if ptree.role_uri in trees:
            logger.warning(f"{source}: duplicate presentationLink role {ptree.role_uri!r}, overwriting")
        trees[ptree.role_uri] = ptree
    return trees


def _parse_calculation_link(link_el: etree._Element, nsmap: dict[str, str], source: str) -> CalculationTree:
    role_uri = _xlink(link_el, "role")
    if not role_uri:
        raise ValueError(f"{source}: <link:calculationLink> missing xlink:role")
    locs = _parse_locs(link_el, nsmap, source)

    arcs: list[tuple[str, str, float]] = []
    weight_of: dict[str, float] = {}
    for arc_el in link_el.findall(_q("calculationArc")):
        frm, to = _xlink(arc_el, "from"), _xlink(arc_el, "to")
        order_raw, weight_raw = arc_el.get("order"), arc_el.get("weight")
        if not frm or not to or order_raw is None or weight_raw is None:
            raise ValueError(f"{source}: <link:calculationArc> missing from/to/order/weight")
        arcs.append((frm, to, float(order_raw)))
        weight_of[to] = float(weight_raw)

    parent_of, children_of, order_of = _build_tree_shape(arcs, locs, source)
    roots = [label for label in locs if label not in parent_of]
    depths = _compute_depths(roots, children_of)

    nodes = {
        label: CalculationNode(
            loc_label=label,
            element=element,
            order=order_of.get(label, 0.0),
            weight=weight_of.get(label, 1.0),  # roots have no incoming summation arc; 1.0 is a neutral default
            parent_loc_label=parent_of.get(label),
            depth=depths.get(label, 0),
            children=children_of.get(label, []),
        )
        for label, element in locs.items()
    }
    return CalculationTree(role_uri=role_uri, nodes=nodes, roots=roots)


def parse_calculation(path: Path, nsmap: dict[str, str]) -> dict[str, CalculationTree]:
    """Parse a `_cal.xml` calculation linkbase into role URI -> tree."""
    tree = etree.parse(str(path))
    source = str(path)
    trees: dict[str, CalculationTree] = {}
    for link_el in tree.getroot().findall(_q("calculationLink")):
        ctree = _parse_calculation_link(link_el, nsmap, source)
        if ctree.role_uri in trees:
            logger.warning(f"{source}: duplicate calculationLink role {ctree.role_uri!r}, overwriting")
        trees[ctree.role_uri] = ctree
    return trees


@dataclass(frozen=True)
class Label:
    role: str   # xlink:role URI, e.g. ".../role/label", ".../role/terseLabel", DART's ".../dart_label"
    lang: str   # xml:lang, e.g. "ko" / "en"
    text: str


def parse_labels(path: Path, nsmap: dict[str, str]) -> dict[QName, list[Label]]:
    """Parse a label linkbase (`_lab-ko.xml` or `_lab-en.xml` — identical
    schema, they differ only in which `xml:lang` their resources carry) into
    concept -> [Label, ...]. Callers needing both languages should parse both
    files and combine with `merge_label_catalogs()`."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    source = str(path)
    result: dict[QName, list[Label]] = {}
    for link_el in root.findall(_q("labelLink")):
        locs = _parse_locs(link_el, nsmap, source)

        resources: dict[str, Label] = {}
        for label_el in link_el.findall(_q("label")):
            label_id = _xlink(label_el, "label")
            if not label_id:
                raise ValueError(f"{source}: <link:label> missing xlink:label")
            role = _xlink(label_el, "role") or "http://www.xbrl.org/2003/role/label"
            lang = label_el.get(f"{{{_XML_NS}}}lang") or ""
            resources[label_id] = Label(role=role, lang=lang, text=(label_el.text or "").strip())

        for arc_el in link_el.findall(_q("labelArc")):
            frm, to = _xlink(arc_el, "from"), _xlink(arc_el, "to")
            if frm not in locs or to not in resources:
                logger.warning(f"{source}: labelArc references undeclared loc/label ({frm!r} -> {to!r}), skipped")
                continue
            result.setdefault(locs[frm], []).append(resources[to])
    return result


def merge_label_catalogs(*catalogs: dict[QName, list[Label]]) -> dict[QName, list[Label]]:
    """Concatenate label lists across catalogs (e.g. ko + en) per concept."""
    merged: dict[QName, list[Label]] = {}
    for catalog in catalogs:
        for element, labels in catalog.items():
            merged.setdefault(element, []).extend(labels)
    return merged


# Phase 5-A: a handful of xsd:import hops to find the shared entry point that
# declares the shared label linkbases — not a big BFS like role_map.py's
# (that one hunts for a specific roleURI across many candidate files).
# ★ Phase 2 (pdf_only_parser_phase2_design_2026-08-12 §A-6, §A-8 item 2):
# 8 -> 15. Was 8 back when this stopped at the FIRST file with any
# labelLinkbaseRef ("a taxonomy vintage only has one shared entry point" —
# that assumption is what broke, see resolve_external_labels()'s docstring
# update below); now that it accumulates across the whole reachable chain,
# a little more headroom keeps the same margin the old code had relative to
# the graphs actually observed (2-3 hops for the vintages checked so far).
_EXTERNAL_LABEL_FETCH_BUDGET = 15


def resolve_external_labels(xsd_path: Path, nsmap: dict[str, str]) -> dict[QName, list[Label]]:
    """Phase 5-A fallback (docs/plans/xbrl_instance_parser_todo_2026-08-05.md
    — 웰킵스하이텍 2019Q3, taxonomy vintage 2019-10-01): the same older DART
    taxonomy vintages that don't bundle `<link:roleType>` locally at all
    (role_map.py) also don't bundle a Korean/English label for *standard*
    `ifrs-full:`/`dart:` concepts — a filer's own `_lab-ko.xml`/`_lab-en.xml`
    only carries labels for that filer's own entity-specific extensions
    (verified: 웰킵스하이텍's local label file has "매입채무"/"장기기타채권" for
    its `dart:`/`entity{CIK}:` concepts, but nothing at all for standard ones
    like `ifrs-full:CurrentAssets` — those come back as the bare English local
    name from `_resolve_label()`'s fallback, which the Korean-keyword-driven
    layer3 mapper can't recognize, silently leaving std_v3 totals NULL).

    Standard concepts' labels live in DART's shared taxonomy package,
    reached the same way role_map.py reaches shared roleType definitions:
    follow the local xsd's `xsd:import` chain out to the shared
    `dart_entry_point_{vintage}.xsd`, then follow `<link:linkbaseRef
    role=".../labelLinkbaseRef">` entries — a different mechanism from
    `xsd:import`/`xsd:include` (those wire in other *schemas*; a
    linkbaseRef is how a schema declares which *linkbase files* belong to
    it, the same way a filer's own `.xsd` declares its own
    `_lab-ko.xml`/`_lab-en.xml`). Verified directly against the DART server
    for vintage 2019-10-01: the shared entry point declares 6 label
    linkbases (`lab_ifrs-ko`/`lab_ifrs-en`/`lab_dart-ko`/`lab_dart-en`/
    `lab_dart-gcd-ko`/`lab_dart-gcd-en`) right there, no further hops needed.

    ★ Phase 2 (pdf_only_parser_phase2_design_2026-08-12 §A-6, root-caused in
    §A-8 item 2): the original version stopped at the FIRST file that
    declared ANY labelLinkbaseRef, reasoning "a taxonomy vintage only has
    one shared entry point" — **that assumption is false for the
    2013-03-31 vintage** (verified by direct fetch): its shared entry point
    `dart_entry_point_2013-03-31.xsd` declares its OWN labelLinkbaseRef
    (`dart_entry_point_2013-03-31-label.xml`) — but that file is a narrow
    supplemental catalog (18 concepts, IS "총계" labels like CostOfSales/
    Revenue only, role=totalLabel) that does NOT carry standard concepts
    like `NoncurrentAssets`/`Assets`/`Liabilities`/`Equity` at all. The real
    comprehensive catalog (`dart_2013-03-31.xsd`'s declared
    `lab_ifrs-ko_2010-04-30.xml`/`lab_ifrs-en_2010-04-30.xml`, confirmed by
    direct fetch to contain all 6 previously-missing concepts) sits one
    `xsd:import` hop further out, on a *sibling* schema the old code never
    reached because it had already stopped. So this now keeps walking the
    whole reachable import graph (within budget) and **merges**
    labelLinkbaseRef declarations from every file visited, instead of
    latching onto the first one — this still resolves 2019-10-01 in a
    single hop (nothing else in its chain declares more), and now also
    resolves 2013-03-31 correctly by continuing past its entry point's own
    (real but incomplete) declaration."""
    from parser.xbrl_instance import external_taxonomy as ext

    source = str(xsd_path)
    seen: set[str] = set()
    queue = ext.dart_first(ext.local_import_urls(xsd_path))

    label_urls: list[str] = []
    fetches = 0
    while queue and fetches < _EXTERNAL_LABEL_FETCH_BUDGET:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        fetches += 1
        root = ext.parse(url)
        if root is None:
            continue
        for found_url in ext.linkbase_ref_urls(root, url, "labelLinkbaseRef"):
            if found_url not in label_urls:
                label_urls.append(found_url)
        queue = ext.dart_first(queue + [u for u in ext.import_urls(root, url) if u not in seen])

    if not label_urls:
        logger.warning(f"{source}: 외부 taxonomy에서도 label linkbase 못 찾음({fetches}건 fetch)")
        return {}

    catalogs: list[dict[QName, list[Label]]] = []
    for label_url in label_urls:
        label_path = ext.fetch(label_url)
        if label_path is None:
            continue
        try:
            catalogs.append(parse_labels(label_path, nsmap))
        except Exception as e:  # noqa: BLE001 — one bad label file shouldn't drop the rest
            logger.warning(f"{source}: 외부 label linkbase 파싱 실패({label_url}): {type(e).__name__}: {e}")
    merged = merge_label_catalogs(*catalogs)
    logger.info(f"{source}: 외부 label linkbase {len(catalogs)}/{len(label_urls)}개에서 "
                f"concept {len(merged)}개 라벨 확보({fetches}건 fetch로 entry point 발견)")
    return merged
