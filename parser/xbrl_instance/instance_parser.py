"""
XBRL instance (.xbrl) structural parser.

Parses a DART standard XBRL instance file (entity{CIK}_{period_end}.xbrl, one of
the 7 files inside the zip returned by ``LegacyDartScraper.fetch_xbrl_zip()``)
into plain structured data: contexts, units, facts. No interpretation happens
here — basis (consolidated/separate) resolution, col_index/period_kind
judgement, presentation-tree walking and label resolution are the
responsibility of later modules (taxonomy_linkbase.py, role_map.py,
fin2/extract/report_lines_xbrl.py).

Verified against real filings (see docs/plans/xbrl_instance_parser_todo_2026-08-05.md,
"Phase 0 결과" section, for the full investigation):
- `sanitize_dart_xml()` is unnecessary — unlike document.xml, standard XBRL
  instance files parse cleanly with plain `lxml.etree.parse()` (Phase 0 §12).
- basis (consolidated/separate) is a context dimension member
  (`ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis`), not a separate
  instance file (Phase 0 §4).
- a context's segment may carry more than one dimension (e.g. SCE breakdown
  rows also carry `ifrs-full:ComponentsOfEquityAxis`) — this module preserves
  all of them in document order, it does not single out "the basis dimension".
- fact values are stored exactly as displayed (negative sign included where
  applicable); no calculation-linkbase weight reversal is needed (Phase 0 §11).
- `decimals` is preserved verbatim ("0", "INF", negative strings, …) — numeric
  interpretation is the caller's responsibility.

Phase 5-A addition (docs/plans/xbrl_instance_parser_todo_2026-08-05.md, 웰킵스하이텍
2019Q3, taxonomy vintage 2019-10-01): dimensional members aren't always inside
`<xbrli:entity><xbrli:segment>` — the XBRL 2.1 spec also allows them directly
under `<xbrli:context><xbrli:scenario>` (a sibling of `<entity>`, not a child of
it), and DART's older filer packages actually use that placement (67 contexts
observed, 0 with segment, 66 with scenario — vs. the two Phase 0 samples,
which used segment exclusively and had 0 scenario). Both are read here and
merged in document order (segment first, then scenario) — no filing observed
so far uses both on the same context, but nothing stops one from doing so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from loguru import logger

_XBRLI_NS = "http://www.xbrl.org/2003/instance"
_XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_XML_NS = "http://www.w3.org/XML/1998/namespace"


@dataclass(frozen=True)
class QName:
    """A namespace URI + local name pair. Every XBRL tag/axis/member is identified this way."""
    ns: str
    local: str

    def __str__(self) -> str:
        return f"{{{self.ns}}}{self.local}"


@dataclass(frozen=True)
class Dimension:
    """One <xbrldi:explicitMember> inside a context's segment: (axis, member)."""
    axis: QName
    member: QName


@dataclass
class XbrlContext:
    """A parsed <xbrli:context>. Judgement (basis/col_index/…) is deliberately not
    done here — only the raw values needed to make that judgement are kept."""
    id: str
    entity_cik: str | None
    period_kind: str  # "instant" | "duration"
    instant: str | None = None       # "YYYY-MM-DD", set when period_kind == "instant"
    start_date: str | None = None    # "YYYY-MM-DD", set when period_kind == "duration"
    end_date: str | None = None      # "YYYY-MM-DD", set when period_kind == "duration"
    dims: list[Dimension] = field(default_factory=list)  # document order, may be empty


@dataclass
class XbrlUnit:
    """A parsed <xbrli:unit>. Observed forms: simple measure (KRW/PURE) or a
    divide unit (KRWEPS = KRW / shares)."""
    id: str
    measure: QName | None = None      # simple unit
    numerator: QName | None = None    # divide unit
    denominator: QName | None = None  # divide unit


@dataclass
class XbrlFact:
    """One top-level fact element (numeric or non-numeric). `qname` alone is not a
    unique key — the same tag can be repeated in both the face statements and
    notes; disambiguating that is the presentation-tree walker's job, not this
    module's."""
    qname: QName
    context_ref: str
    value_raw: str                # exact element text, sign included; "" if nil
    unit_ref: str | None = None   # None for non-numeric facts (doc metadata, etc.)
    decimals: str | None = None   # preserved verbatim, not interpreted here
    is_nil: bool = False
    lang: str | None = None       # xml:lang, common on string facts


@dataclass
class XbrlInstance:
    contexts: dict[str, XbrlContext]
    units: dict[str, XbrlUnit]
    facts: list[XbrlFact]
    nsmap: dict[str, str] = field(default_factory=dict)  # prefix -> namespace URI, from the root element


def _resolve_qname_str(value: str, nsmap: dict[str, str]) -> QName:
    """Resolve an in-content QName string (e.g. "ifrs-full:SeparateMember") using
    the element's visible prefix->URI map. Raises if the prefix isn't declared —
    silently falling back to an empty namespace would corrupt axis/member identity.

    Phase 5-A: a bare (unprefixed) value is not automatically an error — per
    XML QName-content resolution, an unprefixed name falls back to whatever
    default namespace (`xmlns="..."`, lxml key `None`) is in scope. Observed
    in a 2019-vintage filing whose root declares `xmlns="...instance"` (xbrli
    as the *default* namespace, no explicit `xbrli:` prefix at all) with
    `<measure>pure</measure>`/`<measure>shares</measure>` written bare — those
    are exactly `xbrli:pure`/`xbrli:shares`, not "no namespace"."""
    prefix, sep, local = value.strip().partition(":")
    if not sep:
        ns = nsmap.get(None)
        if ns is None:
            raise ValueError(f"expected a prefixed QName or a default namespace in scope, got {value!r} (no ':')")
        return QName(ns=ns, local=prefix)
    ns = nsmap.get(prefix)
    if ns is None:
        raise ValueError(f"namespace prefix {prefix!r} not declared (value={value!r})")
    return QName(ns=ns, local=local)


def _parse_context(el: etree._Element) -> XbrlContext:
    ctx_id = el.get("id")
    if not ctx_id:
        raise ValueError("<xbrli:context> missing id attribute")

    cik: str | None = None
    dims: list[Dimension] = []
    entity_el = el.find(f"{{{_XBRLI_NS}}}entity")
    if entity_el is not None:
        ident_el = entity_el.find(f"{{{_XBRLI_NS}}}identifier")
        if ident_el is not None and ident_el.text:
            cik = ident_el.text.strip()

    # Dimensional members live in <entity><segment> (Phase 0 samples) or
    # directly in <context><scenario> (Phase 5-A, older vintage) — both are
    # legal per XBRL 2.1, see module docstring. Read whichever is present.
    segment_el = entity_el.find(f"{{{_XBRLI_NS}}}segment") if entity_el is not None else None
    scenario_el = el.find(f"{{{_XBRLI_NS}}}scenario")
    for container in (segment_el, scenario_el):
        if container is None:
            continue
        for member_el in container.findall(f"{{{_XBRLDI_NS}}}explicitMember"):
            dim_attr = member_el.get("dimension")
            member_text = (member_el.text or "").strip()
            if not dim_attr or not member_text:
                logger.warning(f"context {ctx_id}: explicitMember missing dimension/text, skipped")
                continue
            nsmap = member_el.nsmap
            dims.append(Dimension(
                axis=_resolve_qname_str(dim_attr, nsmap),
                member=_resolve_qname_str(member_text, nsmap),
            ))

    period_el = el.find(f"{{{_XBRLI_NS}}}period")
    if period_el is None:
        raise ValueError(f"context {ctx_id} missing <xbrli:period>")

    instant_el = period_el.find(f"{{{_XBRLI_NS}}}instant")
    if instant_el is not None and instant_el.text:
        return XbrlContext(
            id=ctx_id, entity_cik=cik, period_kind="instant",
            instant=instant_el.text.strip(), dims=dims,
        )

    start_el = period_el.find(f"{{{_XBRLI_NS}}}startDate")
    end_el = period_el.find(f"{{{_XBRLI_NS}}}endDate")
    if start_el is None or end_el is None or not start_el.text or not end_el.text:
        raise ValueError(f"context {ctx_id} period has neither instant nor startDate/endDate")
    return XbrlContext(
        id=ctx_id, entity_cik=cik, period_kind="duration",
        start_date=start_el.text.strip(), end_date=end_el.text.strip(), dims=dims,
    )


def _parse_unit(el: etree._Element) -> XbrlUnit:
    unit_id = el.get("id")
    if not unit_id:
        raise ValueError("<xbrli:unit> missing id attribute")

    nsmap = el.nsmap
    measure_el = el.find(f"{{{_XBRLI_NS}}}measure")
    if measure_el is not None and measure_el.text:
        return XbrlUnit(id=unit_id, measure=_resolve_qname_str(measure_el.text, nsmap))

    divide_el = el.find(f"{{{_XBRLI_NS}}}divide")
    if divide_el is not None:
        num_container = divide_el.find(f"{{{_XBRLI_NS}}}unitNumerator")
        den_container = divide_el.find(f"{{{_XBRLI_NS}}}unitDenominator")
        num_el = num_container.find(f"{{{_XBRLI_NS}}}measure") if num_container is not None else None
        den_el = den_container.find(f"{{{_XBRLI_NS}}}measure") if den_container is not None else None
        if num_el is None or den_el is None or not num_el.text or not den_el.text:
            raise ValueError(f"unit {unit_id} <divide> missing numerator/denominator measure")
        return XbrlUnit(
            id=unit_id,
            numerator=_resolve_qname_str(num_el.text, nsmap),
            denominator=_resolve_qname_str(den_el.text, nsmap),
        )

    raise ValueError(f"unit {unit_id} has neither <measure> nor <divide>")


def _parse_fact(el: etree._Element) -> XbrlFact:
    tag = etree.QName(el.tag)
    if not tag.namespace:
        raise ValueError(f"fact <{tag.localname}> has no namespace")

    context_ref = el.get("contextRef")
    if not context_ref:
        raise ValueError(f"fact <{tag.localname}> missing contextRef")

    is_nil = el.get(f"{{{_XSI_NS}}}nil") == "true"
    return XbrlFact(
        qname=QName(ns=tag.namespace, local=tag.localname),
        context_ref=context_ref,
        value_raw="" if is_nil else (el.text or "").strip(),
        unit_ref=el.get("unitRef"),
        decimals=el.get("decimals"),
        is_nil=is_nil,
        lang=el.get(f"{{{_XML_NS}}}lang"),
    )


def _validate(instance: XbrlInstance, source: str) -> None:
    """Log (never raise) dangling references — a real integrity problem in the
    filing should be visible, not silently dropped or a hard crash."""
    for f in instance.facts:
        if f.context_ref not in instance.contexts:
            logger.warning(f"{source}: fact {f.qname} references unknown contextRef={f.context_ref!r}")
        if f.unit_ref is not None and f.unit_ref not in instance.units:
            logger.warning(f"{source}: fact {f.qname} references unknown unitRef={f.unit_ref!r}")


def parse_instance(path: Path) -> XbrlInstance:
    """Parse a single .xbrl instance file. No sanitize step (Phase 0 §12) —
    standard XBRL instances don't carry the document.xml-style quoting/PI traps."""
    tree = etree.parse(str(path))
    root = tree.getroot()

    contexts: dict[str, XbrlContext] = {}
    units: dict[str, XbrlUnit] = {}
    facts: list[XbrlFact] = []

    for el in root:
        if not isinstance(el.tag, str):
            continue  # comment / processing instruction
        tag = etree.QName(el.tag)
        if tag.namespace == _XBRLI_NS and tag.localname == "context":
            ctx = _parse_context(el)
            if ctx.id in contexts:
                logger.warning(f"{path}: duplicate context id={ctx.id!r}, overwriting")
            contexts[ctx.id] = ctx
        elif tag.namespace == _XBRLI_NS and tag.localname == "unit":
            unit = _parse_unit(el)
            if unit.id in units:
                logger.warning(f"{path}: duplicate unit id={unit.id!r}, overwriting")
            units[unit.id] = unit
        elif tag.namespace == _LINK_NS:
            continue  # schemaRef / linkbase refs — not a fact, taxonomy files handle these
        else:
            facts.append(_parse_fact(el))

    # Captured for taxonomy_linkbase.py: linkbase locator hrefs (e.g.
    # "...xsd#ifrs-full_CurrentAssets") name concepts by prefix, not by
    # namespace URI, and the linkbase files themselves never declare
    # ifrs-full:/dart:/dart-gcd:/entity{CIK}: — only the instance root does
    # (Phase 0 §3). No interpretation happens here, just recording.
    nsmap = {prefix: uri for prefix, uri in root.nsmap.items() if prefix is not None}

    instance = XbrlInstance(contexts=contexts, units=units, facts=facts, nsmap=nsmap)
    _validate(instance, source=str(path))
    return instance
