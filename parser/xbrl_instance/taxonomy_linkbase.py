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


def _drop_prohibited_only_locs(
    locs: dict[str, QName], prohibited_targets: set[str], optional_targets: set[str],
) -> dict[str, QName]:
    """★R129(2026-09-15, 코아스템켐온 20151126000316 XBRL CF 별도 실측 발견) —
    DART 표준 taxonomy 는 회사가 안 쓰는 표준 계정과목도 전부 `<link:loc>`+arc 로
    깔아두고, 그 arc를 `use="prohibited"` 로 명시해 "이 문서에선 안 쓴다"고
    선언한다(실측: `dart_ProceedsFromSalesOfShortTermFinancialInstruments` arc
    는 order=50 use="prohibited", 회사 확장 태그 `...201592152536382`(같은
    element, 다른 loc)의 arc가 order=4 use="optional" — 회사는 표준 계정 대신
    자기 확장 태그를 쓴다는 뜻). 이 모듈은 `use` 속성 자체를 읽지 않아
    prohibited 표시된 loc 도 그대로 트리에 남았다 — 문제는 표준 계정에도 우연히
    fact 가 존재하면(같은 값을 표준+확장 태그 둘 다에 제출한 경우) 두 loc 가 트리
    양쪽에 다 남아 `_emit_statement_lines`가 같은 계정을 두 번 방출한다(실측:
    "단기금융상품의 처분" 등 3개 계정이 report_lines 에 정확히 2번씩 중복 저장).

    완전한 XBRL arc-prohibition/override 스펙(우선순위 비교 등)은 구현하지
    않는다 — 관찰된 패턴(같은 element 를 가리키는 to-loc 이 여러 개고, 그중
    prohibited 로만 도달되는 것)만 좁게 처리한다: 어떤 loc 이 **오직**
    prohibited arc 로만 도달되고 정상(optional) arc 로는 전혀 도달되지 않으면
    최종 트리에서 완전히 제외한다(`_build_tree_shape`의 "미선언 loc 참조"
    방어 로직이 이후 정리를 안전하게 흡수한다)."""
    dead = prohibited_targets - optional_targets
    if not dead:
        return locs
    return {label: el for label, el in locs.items() if label not in dead}


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
    prohibited_targets: set[str] = set()
    optional_targets: set[str] = set()
    for arc_el in link_el.findall(_q("presentationArc")):
        frm, to = _xlink(arc_el, "from"), _xlink(arc_el, "to")
        order_raw = arc_el.get("order")
        if not frm or not to or order_raw is None:
            raise ValueError(f"{source}: <link:presentationArc> missing from/to/order")
        if arc_el.get("use") == "prohibited":  # R129 — see _drop_prohibited_only_locs
            prohibited_targets.add(to)
            continue
        optional_targets.add(to)
        arcs.append((frm, to, float(order_raw)))
        preferred = arc_el.get("preferredLabel")
        if preferred:
            preferred_of[to] = preferred
    locs = _drop_prohibited_only_locs(locs, prohibited_targets, optional_targets)

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


def parse_presentation(
    path: Path, nsmap: dict[str, str], base_links: dict[str, list[Path]] | None = None,
    denegate_base_roles: frozenset[str] = frozenset(),
) -> dict[str, PresentationTree]:
    """Parse a `_pre.xml` presentation linkbase into role URI -> tree.

    `base_links` (R170): role URI -> DART's shared *base* presentation
    linkbase files for that role (`resolve_external_base_presentation()`).
    When a role has one, the filer's link is only a delta on top of it and
    the tree is built from the merged relationship network
    (`_build_merged_presentation_tree`); every other role keeps the
    filer-file-only builder unchanged. `denegate_base_roles`: roles whose
    base-template `negated*` preferredLabels are dropped (`_denegate_role`)."""
    tree = etree.parse(str(path))
    source = str(path)
    base_links = base_links or {}
    trees: dict[str, PresentationTree] = {}
    for link_el in tree.getroot().findall(_q("presentationLink")):
        role_uri = _xlink(link_el, "role")
        base_paths = base_links.get(role_uri or "")
        if base_paths:
            ptree = _build_merged_presentation_tree(
                link_el, base_paths, nsmap, source, denegate_base=role_uri in denegate_base_roles,
            )
        else:
            ptree = _parse_presentation_link(link_el, nsmap, source)
        if ptree.role_uri in trees:
            logger.warning(f"{source}: duplicate presentationLink role {ptree.role_uri!r}, overwriting")
        trees[ptree.role_uri] = ptree
    return trees


def presentation_role_uris(path: Path) -> set[str]:
    """Role URIs of every presentationLink in a `_pre.xml` (no tree building)."""
    root = etree.parse(str(path)).getroot()
    return {r for r in (_xlink(el, "role") for el in root.findall(_q("presentationLink"))) if r}


@dataclass(frozen=True)
class _PresArc:
    frm: str                # loc label (base labels carry a "base:" prefix, never collide with filer ones)
    to: str
    frm_el: QName
    to_el: QName
    order: float
    preferred: str | None
    priority: int
    prohibited: bool
    from_base: bool


_BASE_LABEL_PREFIX = "base:"

_XBRL_2003_ROLE = "http://www.xbrl.org/2003/role/"
_XBRL_2009_ROLE = "http://www.xbrl.org/2009/role/"


def _denegate_role(role: str | None) -> str | None:
    """R170-b — the *income statement* base template negates deductions
    (IncomeTaxExpense, DistributionCosts, AdministrativeExpense ... carry
    `negatedTerseLabel`), i.e. it renders them as subtractions. Korean
    손익계산서 print expenses as positive amounts, so the XBRL fact sign
    (expense +, 법인세수익 −) already equals the 원문 (measured on batch #4:
    법인세비용 9/9 matched raw, 9/9 flipped once negated). The *cash-flow*
    base template's negation of outflows (이자지급·법인세납부·차입금상환·리스부채
    상환, 8/8) does match the 원문's parentheses, so callers apply this to IS
    roles only. Keeps the label role (terse/total/...), drops only the
    negation. A filer's own negated arcs are never touched (R10)."""
    if not role:
        return role
    local = role.rsplit("/", 1)[-1]
    if not local.startswith("negated"):
        return role
    plain = local[len("negated"):]
    plain = plain[:1].lower() + plain[1:]
    if plain == "netLabel":
        return _XBRL_2009_ROLE + plain
    return _XBRL_2003_ROLE + plain


def _collect_presentation_arcs(
    link_el: etree._Element, nsmap: dict[str, str], source: str, from_base: bool,
) -> tuple[dict[str, QName], list[_PresArc]]:
    """Locs + arcs of one presentationLink, tolerant of locators whose prefix
    the instance never declares (a base-template concept this filer never
    tagged — it can't carry a fact, so dropping its loc loses nothing)."""
    prefix = _BASE_LABEL_PREFIX if from_base else ""
    locs: dict[str, QName] = {}
    for loc_el in link_el.findall(_q("loc")):
        label, href = _xlink(loc_el, "label"), _xlink(loc_el, "href")
        if not label or not href:
            continue
        try:
            locs[prefix + label] = resolve_href_fragment(href, nsmap)
        except ValueError:
            continue
    arcs: list[_PresArc] = []
    for arc_el in link_el.findall(_q("presentationArc")):
        frm, to, order_raw = _xlink(arc_el, "from"), _xlink(arc_el, "to"), arc_el.get("order")
        if not frm or not to:
            continue
        frm, to = prefix + frm, prefix + to
        if frm not in locs or to not in locs:
            continue
        arcs.append(_PresArc(
            frm=frm, to=to, frm_el=locs[frm], to_el=locs[to],
            order=float(order_raw) if order_raw is not None else 1.0,
            preferred=arc_el.get("preferredLabel"),
            priority=int(arc_el.get("priority") or 0),
            prohibited=arc_el.get("use") == "prohibited",
            from_base=from_base,
        ))
    return locs, arcs


def _build_merged_presentation_tree(
    link_el: etree._Element, base_paths: list[Path], nsmap: dict[str, str], source: str,
    denegate_base: bool = False,
) -> PresentationTree:
    """★R170 — DART delta presentation linkbases (2013-03-31/2017-10-01/
    2018-07-01 vintages): the filer's `_pre.xml` is NOT the statement tree,
    it is a delta over DART's shared base presentation linkbase for the same
    role (`pre_dart_{vintage}_role-D310005.xml` etc., declared by
    `dart_{vintage}.xsd` and therefore part of the filing's DTS). Measured on
    한화엔진 20150515002710: 1,301 of 1,488 filer arcs are `use="prohibited"`
    cancellations of base arcs, and GrossProfit/IncomeTaxExpense exist only
    in the base — reading the filer file alone silently drops them.

    XBRL relationship semantics, applied to the merged base+filer network:
      1. Arcs are relationships between *concepts*; locator labels are
         file-local pointers. Equivalent relationships (same from/to concept,
         order, preferredLabel) are resolved by priority: the highest wins,
         and a prohibited arc at that priority removes the relationship.
      2. A filer placement of a concept beats any base placement of the same
         concept with the same preferredLabel (the filer re-parents by
         prohibiting the base arc and adding its own; if it only adds, the
         base placement would otherwise duplicate the row).
      3. An arc's parent is resolved by concept: when its `from` locator is
         not itself a placed node (e.g. R129 dropped it because its own
         parent arc was prohibited and re-added under a new locator — 엘앤에프
         20151104000116: 단기차입금/유동성장기차입금 hung off the orphaned
         `Loc_label_ifrs_CurrentLiabilities`), it attaches to the node that
         placed the same concept."""
    role_uri = _xlink(link_el, "role")
    if not role_uri:
        raise ValueError(f"{source}: <link:presentationLink> missing xlink:role")
    locs, arcs = _collect_presentation_arcs(link_el, nsmap, source, from_base=False)
    filer_locs = dict(locs)
    for base_path in base_paths:
        try:
            base_root = etree.parse(str(base_path)).getroot()
        except Exception as e:  # noqa: BLE001 — a corrupt cache entry degrades to filer-only
            logger.warning(f"{source}: base presentation 파싱 실패({base_path}): {type(e).__name__}: {e}")
            continue
        for base_link in base_root.findall(_q("presentationLink")):
            if _xlink(base_link, "role") != role_uri:
                continue
            b_locs, b_arcs = _collect_presentation_arcs(base_link, nsmap, source, from_base=True)
            locs.update(b_locs)
            arcs.extend(b_arcs)

    # 1. priority / prohibition over equivalent relationships
    groups: dict[tuple, list[_PresArc]] = {}
    for a in arcs:
        groups.setdefault((a.frm_el, a.to_el, a.order, a.preferred), []).append(a)
    surviving: list[_PresArc] = []
    for group in groups.values():
        top = max(a.priority for a in group)
        winners = [a for a in group if a.priority == top]
        if any(a.prohibited for a in winners):
            continue
        winners.sort(key=lambda a: a.from_base)  # filer arc first among equals
        surviving.append(winners[0])

    # 2. filer placement beats base placement of the same concept+label role
    filer_placed = {(a.to_el, a.preferred) for a in surviving if not a.from_base}
    surviving = [a for a in surviving
                 if not a.from_base or (a.to_el, a.preferred) not in filer_placed]
    # arcs keep document order: filer first, then base
    surviving.sort(key=lambda a: a.from_base)

    # 3. nodes = arc targets; parents resolved by concept when the locator isn't placed
    target_labels: list[str] = []
    for a in surviving:
        if a.to not in target_labels:
            target_labels.append(a.to)
    nodes_of_el: dict[QName, list[str]] = {}
    for label in target_labels:
        nodes_of_el.setdefault(locs[label], []).append(label)

    parent_of: dict[str, str] = {}
    order_of: dict[str, float] = {}
    preferred_of: dict[str, str] = {}
    pending_children: dict[str, list[tuple[str, float]]] = {}
    root_labels: list[str] = []
    root_of_el: dict[QName, str] = {}
    for a in surviving:
        if a.to in parent_of:
            continue
        if a.frm in nodes_of_el.get(a.frm_el, []):
            parent = a.frm
        elif nodes_of_el.get(a.frm_el):
            parent = nodes_of_el[a.frm_el][0]
        else:
            parent = root_of_el.setdefault(a.frm_el, a.frm)
            if parent not in root_labels:
                root_labels.append(parent)
        if parent == a.to:
            continue
        parent_of[a.to] = parent
        order_of[a.to] = a.order
        preferred = _denegate_role(a.preferred) if (a.from_base and denegate_base) else a.preferred
        if preferred:
            preferred_of[a.to] = preferred
        pending_children.setdefault(parent, []).append((a.to, a.order))
    # a filer loc that takes part in no arc at all stays a standalone root, as
    # the filer-only builder keeps it (unless its concept is already placed)
    in_any_arc = {lbl for a in arcs for lbl in (a.frm, a.to)}
    for label, element in filer_locs.items():
        if label in in_any_arc or element in nodes_of_el or element in root_of_el:
            continue
        root_of_el[element] = label
        root_labels.append(label)

    children_of = {
        frm: [label for label, _ in sorted(pairs, key=lambda pair: pair[1])]
        for frm, pairs in pending_children.items()
    }
    node_labels = root_labels + [lbl for lbl in target_labels if lbl in parent_of]
    roots = [lbl for lbl in node_labels if lbl not in parent_of]
    depths = _compute_depths(roots, children_of)
    nodes = {
        label: PresentationNode(
            loc_label=label,
            element=locs[label],
            order=order_of.get(label, 0.0),
            preferred_label=preferred_of.get(label),
            parent_loc_label=parent_of.get(label),
            depth=depths.get(label, 0),
            children=children_of.get(label, []),
        )
        for label in node_labels
    }
    return PresentationTree(role_uri=role_uri, nodes=nodes, roots=roots)


_EXTERNAL_BASE_PRE_FETCH_BUDGET = 15


def resolve_external_base_presentation(xsd_path: Path, role_uris: set[str],
                                       kind: str = "presentation") -> dict[str, list[Path]]:
    """R170 — DART's shared base presentation linkbase(s) for `role_uris`,
    found the same way `resolve_external_labels()` finds shared label
    linkbases: walk the filing xsd's `xsd:import` chain out to
    `dart_{vintage}.xsd` and collect its `presentationLinkbaseRef`s. Only
    files named after one of the wanted roles' ids (`..._role-D310005.xml`)
    are fetched, and each is kept only if it really carries that role URI.
    Vintages whose shared schema declares no base presentation (2019-10-01+,
    where filers bundle the full tree) return {} — callers then keep the
    filer-file-only tree.

    `kind="calculation"` (R175) walks the same chain for `calculationLinkbaseRef`
    (`cal_dart_{vintage}_role-D520000.xml` …) instead."""
    from parser.xbrl_instance import external_taxonomy as ext

    ref_role = f"{kind}LinkbaseRef"
    link_tag = f"{kind}Link"
    wanted = {uri.rsplit("role-", 1)[-1]: uri for uri in role_uris if "role-" in uri}
    if not wanted:
        return {}
    seen: set[str] = set()
    queue = ext.dart_first(ext.local_import_urls(xsd_path))
    pre_urls: list[str] = []
    fetches = 0
    while queue and fetches < _EXTERNAL_BASE_PRE_FETCH_BUDGET:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        fetches += 1
        root = ext.parse(url)
        if root is None:
            continue
        for found in ext.linkbase_ref_urls(root, url, ref_role):
            if found not in pre_urls:
                pre_urls.append(found)
        queue = ext.dart_first(queue + [u for u in ext.import_urls(root, url) if u not in seen])

    out: dict[str, list[Path]] = {}
    for url in pre_urls:
        stem = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        role_id = stem.rsplit("role-", 1)[-1] if "role-" in stem else None
        role_uri = wanted.get(role_id or "")
        if role_uri is None:
            continue
        path = ext.fetch(url)
        if path is None:
            continue
        try:
            root = etree.parse(str(path)).getroot()
            roles = {_xlink(el, "role") for el in root.findall(_q(link_tag))}
        except Exception:  # noqa: BLE001 — corrupt cache / HTML error page
            continue
        if role_uri in roles:
            out.setdefault(role_uri, []).append(path)
    return out


def merged_calculation_weights(
    path: Path, nsmap: dict[str, str], role_uri: str, base_paths: list[Path] | None = None,
) -> dict[QName, float]:
    """★R175 — concept -> display sign (+1/-1) = product of summation-item weights up to
    its CF section total (see `cumulative` below),
    from the filer's `_cal.xml` merged with DART's shared base calculation linkbase for
    `role_uri` (same delta structure and XBRL prohibition/priority semantics as
    `_build_merged_presentation_tree`; equivalence also keys on `weight`). A concept
    with more than one surviving calculation parent is left out (ambiguous — R6).
    The section totals themselves get no entry (their own sign stays R10)."""
    def collect(link_el, prefix: str) -> list[tuple]:
        locs: dict[str, QName] = {}
        for loc_el in link_el.findall(_q("loc")):
            label, href = _xlink(loc_el, "label"), _xlink(loc_el, "href")
            if not label or not href:
                continue
            try:
                locs[prefix + label] = resolve_href_fragment(href, nsmap)
            except ValueError:
                continue
        arcs = []
        for arc_el in link_el.findall(_q("calculationArc")):
            frm, to, w = _xlink(arc_el, "from"), _xlink(arc_el, "to"), arc_el.get("weight")
            if not frm or not to or w is None:
                continue
            frm, to = prefix + frm, prefix + to
            if frm not in locs or to not in locs:
                continue
            arcs.append((locs[frm], locs[to], float(arc_el.get("order") or 1.0), float(w),
                         int(arc_el.get("priority") or 0), arc_el.get("use") == "prohibited",
                         bool(prefix)))
        return arcs

    arcs: list[tuple] = []
    for p_, prefix in [(path, "")] + [(b, _BASE_LABEL_PREFIX) for b in (base_paths or [])]:
        try:
            root = etree.parse(str(p_)).getroot()
        except Exception:  # noqa: BLE001
            continue
        for link_el in root.findall(_q("calculationLink")):
            if _xlink(link_el, "role") == role_uri:
                arcs.extend(collect(link_el, prefix))
    groups: dict[tuple, list[tuple]] = {}
    for a in arcs:
        groups.setdefault((a[0], a[1], a[2], a[3]), []).append(a)
    surviving = []
    for group in groups.values():
        top = max(a[4] for a in group)
        winners = [a for a in group if a[4] == top]
        if any(a[5] for a in winners):
            continue
        surviving.append(winners[0])
    # a filer placement of a concept beats the base template's (as in presentation)
    filer_to = {a[1] for a in surviving if not a[6]}
    surviving = [a for a in surviving if not a[6] or a[1] not in filer_to]
    edges: dict[QName, set[tuple[QName, float]]] = {}
    for a in surviving:
        edges.setdefault(a[1], set()).add((a[0], a[3]))
    parent_of = {c: next(iter(e)) for c, e in edges.items() if len(e) == 1}

    # Korean CF prints every line as its contribution to the **section total**
    # (영업/투자/재무활동현금흐름), not to its immediate group: an outflow group
    # modelled as [group −1, children +1] (20180801000294) and one modelled as
    # [group +1, children −1] (엘앤에프 20151104000116) both print the children in
    # parentheses. So the display sign is the product of weights up the chain, stopping
    # at a section total (CashFlowsFromUsedIn*Activities) or the chain's top.
    def cumulative(c: QName) -> float | None:
        sign, seen = 1.0, set()
        while c in parent_of and c not in seen:
            if c.local.startswith("CashFlowsFromUsedIn") and c.local.endswith("Activities"):
                break
            seen.add(c)
            parent, w = parent_of[c]
            sign *= w
            c = parent
        return sign if seen else None
    out: dict[QName, float] = {}
    for c in parent_of:
        v = cumulative(c)
        if v is not None:
            out[c] = v
    return out


def _parse_calculation_link(link_el: etree._Element, nsmap: dict[str, str], source: str) -> CalculationTree:
    role_uri = _xlink(link_el, "role")
    if not role_uri:
        raise ValueError(f"{source}: <link:calculationLink> missing xlink:role")
    locs = _parse_locs(link_el, nsmap, source)

    arcs: list[tuple[str, str, float]] = []
    weight_of: dict[str, float] = {}
    prohibited_targets: set[str] = set()
    optional_targets: set[str] = set()
    for arc_el in link_el.findall(_q("calculationArc")):
        frm, to = _xlink(arc_el, "from"), _xlink(arc_el, "to")
        order_raw, weight_raw = arc_el.get("order"), arc_el.get("weight")
        if not frm or not to or order_raw is None or weight_raw is None:
            raise ValueError(f"{source}: <link:calculationArc> missing from/to/order/weight")
        if arc_el.get("use") == "prohibited":  # R129 — see _drop_prohibited_only_locs
            prohibited_targets.add(to)
            continue
        optional_targets.add(to)
        arcs.append((frm, to, float(order_raw)))
        weight_of[to] = float(weight_raw)
    locs = _drop_prohibited_only_locs(locs, prohibited_targets, optional_targets)

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
