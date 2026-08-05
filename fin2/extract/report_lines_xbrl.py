"""
Layer-2 extraction entry point for DART's standard XBRL instance zip
(``file_type='xbrl_zip'``, ``parser_track='XBRL_INSTANCE'`` — see
docs/plans/xbrl_instance_parser_2026-08-05.md, Phase 3-5). Unlike
fin2/extract/report_lines.py (HTML/XML `document.xml`), the source here is a
formal, unambiguous XBRL instance — no cell-splitting, no unit-declaration
guessing. This module reuses parser/xbrl_instance/{instance_parser,
taxonomy_linkbase,role_map}.py (Phase 3-1~3-4) and produces the exact same
``ReportLineRow`` shape as report_lines.py so the two sources can share
storage (`store_report_lines`/`store_report_tables`).

★ Scope: BS/IS/CF (Phase 3-5) + SCE (자본변동표, Phase 3-7, added 2026-08-06 —
option A from docs/plans/xbrl_instance_parser_todo_2026-08-05.md's Phase 3-6
survey). SCE's column axis is NOT the fiscal-period axis used by BS/IS/CF
(col_index=당기/전기/전전기) but `ifrs-full:ComponentsOfEquityAxis`, whose
members form a hierarchy (지배지분귀속/비지배지분 subtotals nested under leaf
components — confirmed by walking hanwha's SCE presentation subtree). So SCE
reuses the existing HTML-parser convention instead of inventing a new one:
col_index = position among 자본 구성요소 columns (NOT a period), col_label =
the ">"-joined component ancestor chain, context_fiscal_year/period_kind =
NULL, and period (당기/전기/전전기) is instead encoded by (a) `row_order`
block-stacking per period and (b) a date suffix synthesized into `label_raw`
for the two instant-typed "boundary" concepts (기초/기말) — this is what lets
the existing `fin2/audit/line_anomaly.py::detect_sce_anomalies()` (which
greps `label_raw` for "기말" + a date) keep working unmodified against
XBRL-sourced SCE rows. See `_emit_sce_lines()` below for the full design, and
the Phase 3-6 section of the todo doc for the empirical survey this is built
on. Unlike BS/IS/CF, `_is_loadable()` does NOT restrict SCE rows to
col_index=0 — every SCE row emitted here is stored, so `_emit_sce_lines()`
also runs a self-consistency check (`_check_sce_column_rollup`) that logs
(never raises/drops) when a parent component column's value doesn't equal
the sum of its child columns for the same row+period — a parser-bug signal,
distinct from `detect_sce_anomalies()`'s post-storage SCE↔BS cross-check of
real filing anomalies. A *row*-rollup check (기초+포괄손익+자본거래=기말) is
NOT implemented here — it would need calculation-linkbase weights for the
SCE role, which haven't been verified to exist (Phase 0 §11 only confirmed
this for BS/CF); left as a follow-up rather than guessed at (R9).

Design decisions (all empirically verified against the two Phase 0 samples —
박셀바이오 20250828000534 / 한화에어로스페이스 20260513000860 — re-fetched and
re-walked for this phase, 2026-08-06):

- **basis (연결/별도)**: a context's `dims` must be *exactly one* dimension —
  `ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis` with the
  matching member — with no other axis. This is what actually isolates a
  statement's face total from the same concept re-tagged inside a note
  breakdown (Phase 0 §7: `ifrs-full:Assets` tagged 40+ times in hanwha's
  instance, of which exactly 1 per basis is the single-dim BS total).
  Verified again here: filtering hanwha's BS tree this way yields exactly
  one Assets/Liabilities/Equity fact per basis, and Assets = Liabilities +
  Equity in both (matches Phase 0 §7's recorded 56,659,594,923,000).

- **col_index (당기/전기)**: NOT derived from the `CFY`/`PFY`/`BPFY` context-ID
  prefix (that string is filing-generator convention, not a schema
  guarantee — see instance_parser.py's caution). Instead, col0 (당기) is the
  candidate context whose actual date value matches
  `Filing.period_end_date` exactly:
    - instant (BS): `ctx.instant == period_end_date`.
    - duration (IS/CF): `ctx.end_date == period_end_date`, and when more than
      one duration context shares that end_date (e.g. hanwha Q1's `FQA`
      6-month-equivalent cumulative vs `FQQ` single-quarter — confirmed both
      exist and, for Q1, hold identical values since Q1 has no prior quarter
      this FY), the one with the **earliest start_date** (= longest, i.e.
      cumulative) wins — this generalizes the `HYA`/`FQA` "누적" convention
      without hardcoding those literal suffixes (Phase 0 §5's caution: future
      report types may invent new codes).
  col1 (전기) is filled best-effort from the next most recent distinct date
  found on that same element/basis (not globally reconciled across the
  statement) — acceptable because `report_lines._is_loadable()` only stores
  col_index==0 for BS/IS/CF; col1 here is for line-shape completeness and
  ad-hoc cross-checks, not storage-critical. col_index 2+ (전전기) is not
  attempted — the only 3rd-period contexts observed in the samples
  (`BPFY...`, 2 facts in hanwha's BS role) were noise from unrelated note
  comparatives leaking onto the role, not a real 3-period column.

- **presentation tree walk**: `row_order` = DFS pre-order index over the
  role's tree (roots first, children in `order`-sorted sequence — same
  ordering `taxonomy_linkbase.py` already computed). `depth` = the tree's own
  computed depth. `node_role` (P/S/F) uses the exact same "compare this row's
  depth to the NEXT row in document order" rule as
  `report_lines.py::_classify_positions` (same structural meaning, applied to
  a tree-derived row sequence instead of an HTML row sequence — the source is
  different, the rule is not). `section_path` = resolved labels of the
  ancestor chain (`parent_loc_label` walk to the root), joined with ">" —
  the tree equivalent of report_lines.py's indent-stack.

- **label**: `preferredLabel` (from the presentation arc) is tried first —
  ko then en — then the standard `label` role — ko then en — then any
  label in either language, then (only if the concept has no label at all)
  the bare local name as a last resort so `label_raw` is never empty
  (Phase 0 §10).

- **value/unit**: XBRL facts are stored as base-unit numeric text already
  (Phase 0 §11/§12) — there is no multiplier to apply, so `adecimal` is
  always 0 (unit=1, same convention as `fin2/extract/text.py::
  _adecimal_from_unit`). Only `KRW`-measure and `KRWEPS`-divide-unit
  (주당이익, 원/주 — same base-unit story) facts are accepted; anything else
  (`PURE`, foreign-currency measures — Phase 0's follow-up finding of 10
  units in hanwha, mostly subsidiary-disclosure FX in notes) is out of scope
  for this pass and simply skipped. `unit_source='xbrl'` — a new value
  distinct from the text-pipeline's declared/inherited/fx_declared/
  doc_default family, since the provenance here (a formal unit declaration,
  not a Korean-text unit label) is categorically different.
"""
from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from loguru import logger

from parser.xbrl_instance.instance_parser import (
    Dimension, QName, XbrlContext, XbrlFact, XbrlUnit, parse_instance,
)
from parser.xbrl_instance.taxonomy_linkbase import (
    Label, PresentationTree, merge_label_catalogs, parse_labels, parse_presentation,
)
from parser.xbrl_instance.role_map import build_role_map, index_core_roles

from fin2.extract.report_lines import ReportLineRow

_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
_BASIS_AXIS_LOCAL = "ConsolidatedAndSeparateFinancialStatementsAxis"
_BASIS_MEMBER_LOCAL = {"consolidated": "ConsolidatedMember", "separate": "SeparateMember"}

# report_lines.unit_source is varchar(14) (collector/models.py:ReportLine) — fits easily.
UNIT_SOURCE_XBRL = "xbrl"

# Statements handled by the period-axis path (_emit_statement_lines). SCE has
# its own emitter (_emit_sce_lines) — see module docstring.
_SUPPORTED_STATEMENTS = ("BS", "IS", "CF")
_SUPPORTED_SCE_STATEMENT = "SCE"

# col_index we attempt to resolve. Only col0 is stored for BS/IS/CF
# (report_lines.py::_is_loadable) — col1 is best-effort extra context.
_MAX_COL_INDEX = 1

# SCE-specific concept/axis names (Phase 3-6 survey, both in the ifrs-full
# namespace like the basis axis — Phase 0 §4/§7).
_CE_AXIS_LOCAL = "ComponentsOfEquityAxis"
_SCE_LINEITEMS_LOCAL = "StatementOfChangesInEquityLineItems"
# The two instant-typed "boundary" concepts whose label gets a synthesized
# date suffix so detect_sce_anomalies() (which greps label_raw for "기말" +
# a date, fin2/audit/line_anomaly.py) keeps working — see _sce_row_label().
_SCE_ENDING_LOCAL = "Equity"                    # 기말자본 — the only one detect_sce_anomalies checks
_SCE_BEGINNING_LOCAL = "EquityAtBeginningOfPeriod"  # 기초자본 — dated too, for symmetry/fidelity, not required for compat

# Relative tolerance for the column-rollup self-check (_check_sce_column_rollup) —
# same magnitude as fin2/audit/line_anomaly.py::_TOL (rounding, not real drift).
_SCE_ROLLUP_TOL = 0.001


@dataclass
class _ZipMembers:
    xbrl: Path
    xsd: Path
    pre: Path
    lab_ko: Path | None
    lab_en: Path | None


def _find_one(names: list[str], suffix: str, source: str, required: bool = True) -> str | None:
    matches = [n for n in names if n.endswith(suffix)]
    if not matches:
        if required:
            raise ValueError(f"{source}: no member ending with {suffix!r} in zip")
        return None
    if len(matches) > 1:
        logger.warning(f"{source}: {len(matches)} members end with {suffix!r}, using {matches[0]!r}")
    return matches[0]


def _extract_zip_members(zip_path: Path, dest_dir: Path) -> _ZipMembers:
    """Unzip the 7-file DART XBRL bundle and locate the 5 members this pass
    needs by filename suffix (`_def.xml`/`_cal.xml` unused here — Phase 0 §2's
    fixed naming pattern `entity{CIK}_{period_end}.{ext}`)."""
    source = str(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        zf.extractall(dest_dir)
    return _ZipMembers(
        xbrl=dest_dir / _find_one(names, ".xbrl", source),
        xsd=dest_dir / _find_one(names, ".xsd", source),
        pre=dest_dir / _find_one(names, "_pre.xml", source),
        lab_ko=dest_dir / n if (n := _find_one(names, "_lab-ko.xml", source, required=False)) else None,
        lab_en=dest_dir / n if (n := _find_one(names, "_lab-en.xml", source, required=False)) else None,
    )


def _resolve_label(element: QName, preferred_role: str | None, labels: dict[QName, list[Label]]) -> str:
    """★ label_raw is never empty — falls all the way back to the bare local
    name if the concept genuinely has no label (shouldn't happen in practice,
    but report_lines.label_raw is NOT NULL)."""
    candidates = labels.get(element, [])
    if not candidates:
        return element.local

    def pick(role: str) -> str | None:
        ko = next((l.text for l in candidates if l.role == role and l.lang == "ko" and l.text), None)
        if ko:
            return ko
        return next((l.text for l in candidates if l.role == role and l.lang == "en" and l.text), None)

    if preferred_role:
        got = pick(preferred_role)
        if got:
            return got
    got = pick(_STANDARD_LABEL_ROLE)
    if got:
        return got
    any_ko = next((l.text for l in candidates if l.lang == "ko" and l.text), None)
    if any_ko:
        return any_ko
    any_en = next((l.text for l in candidates if l.lang == "en" and l.text), None)
    return any_en or element.local


def _flatten_preorder(tree: PresentationTree) -> list[str]:
    """DFS pre-order over the tree, roots first, children in the `order`-sorted
    sequence taxonomy_linkbase.py already computed. This is the tree
    equivalent of a report_lines.py table's row-document-order."""
    out: list[str] = []

    def visit(loc_label: str) -> None:
        out.append(loc_label)
        for child in tree.nodes[loc_label].children:
            visit(child)

    for root in tree.roots:
        visit(root)
    return out


def _compute_node_roles(flat: list[str], tree: PresentationTree) -> dict[str, str]:
    """P/S/F — identical rule to report_lines.py::_classify_positions (compare
    this row's depth to the NEXT row in document order), applied to the
    tree-derived flat sequence instead of an HTML row sequence."""
    roles: dict[str, str] = {}
    for i, loc_label in enumerate(flat):
        depth = tree.nodes[loc_label].depth
        nxt_depth = tree.nodes[flat[i + 1]].depth if i + 1 < len(flat) else None
        if nxt_depth is None or nxt_depth < depth:
            roles[loc_label] = "S"
        elif nxt_depth > depth:
            roles[loc_label] = "P"
        else:
            roles[loc_label] = "F"
    return roles


def _section_path(loc_label: str, tree: PresentationTree, label_of: dict[str, str]) -> str | None:
    """Ancestor label chain via parent_loc_label — the tree equivalent of
    report_lines.py's indent-stack section_path."""
    chain: list[str] = []
    parent = tree.nodes[loc_label].parent_loc_label
    while parent is not None:
        chain.append(label_of[parent])
        parent = tree.nodes[parent].parent_loc_label
    chain.reverse()
    return ">".join(chain) if chain else None


def _basis_candidates(
    element: QName,
    facts_by_qname: dict[QName, list[XbrlFact]],
    contexts: dict[str, XbrlContext],
    basis_axis: QName,
    basis_member: QName,
) -> list[tuple[XbrlFact, XbrlContext]]:
    """Facts for `element` whose context carries *exactly* the basis dimension
    and nothing else — excludes the same concept re-tagged in note breakdowns
    (Phase 0 §7)."""
    out: list[tuple[XbrlFact, XbrlContext]] = []
    for f in facts_by_qname.get(element, []):
        if f.is_nil or not f.value_raw:
            continue
        ctx = contexts.get(f.context_ref)
        if ctx is None or len(ctx.dims) != 1:
            continue
        d = ctx.dims[0]
        if d.axis == basis_axis and d.member == basis_member:
            out.append((f, ctx))
    return out


def _bucket_by_period(
    candidates: list[tuple[XbrlFact, XbrlContext]], source: str,
) -> dict[date, tuple[XbrlFact, XbrlContext]]:
    """Group candidate (fact, context) pairs by resolved period date, picking
    exactly one representative per date. Duration candidates sharing an
    end_date are disambiguated by earliest start_date (= cumulative, "누적" —
    generalizes HYA/FQA vs HYQ/FQQ without hardcoding those literal suffixes,
    module docstring). Used by `_resolve_columns` (BS/IS/CF, anchored to
    `period_end_date`) and directly by `_emit_sce_lines` (SCE, which ranks by
    recency instead — module docstring's SCE section explains why SCE can't
    anchor to `period_end_date`, and why it resolves periods once per row
    from the total column rather than per column)."""
    kinds = {ctx.period_kind for _, ctx in candidates}
    if not kinds:
        return {}
    if len(kinds) > 1:
        counts = {k: sum(1 for _, c in candidates if c.period_kind == k) for k in kinds}
        majority = max(counts, key=counts.get)
        logger.warning(f"{source}: mixed instant/duration contexts ({counts}), using {majority!r}")
        candidates = [(f, ctx) for f, ctx in candidates if ctx.period_kind == majority]
    if not candidates:
        return {}
    kind = candidates[0][1].period_kind

    buckets: dict[date, tuple[XbrlFact, XbrlContext]] = {}
    if kind == "instant":
        for f, ctx in candidates:
            d = date.fromisoformat(ctx.instant)
            if d not in buckets:
                buckets[d] = (f, ctx)
            elif buckets[d][0].value_raw != f.value_raw:
                logger.warning(f"{source}: {d} has conflicting instant facts, keeping the first")
    else:
        # Group by end_date; within a group, the context with the earliest
        # start_date is the cumulative ("누적") one — generalizes HYA/FQA vs
        # HYQ/FQQ without hardcoding those suffixes (module docstring).
        by_end: dict[date, list[tuple[XbrlFact, XbrlContext]]] = {}
        for f, ctx in candidates:
            d = date.fromisoformat(ctx.end_date)
            by_end.setdefault(d, []).append((f, ctx))
        for d, group in by_end.items():
            group.sort(key=lambda pair: pair[1].start_date)
            buckets[d] = group[0]
    return buckets


def _resolve_columns(
    candidates: list[tuple[XbrlFact, XbrlContext]], period_end_date: date, source: str,
) -> list[tuple[int, XbrlFact, XbrlContext]]:
    """col0 requires an exact date match to `period_end_date` — if none of the
    candidates match, this element contributes nothing (see module docstring
    on why col1+ is best-effort and col0-or-nothing is the right trade-off)."""
    buckets = _bucket_by_period(candidates, source)
    if not buckets:
        return []

    results: list[tuple[int, XbrlFact, XbrlContext]] = []
    if period_end_date in buckets:
        f, ctx = buckets.pop(period_end_date)
        results.append((0, f, ctx))
    else:
        return []  # no col0 -> nothing worth keeping (see docstring)

    for col_idx, d in enumerate(sorted(buckets, reverse=True)[:_MAX_COL_INDEX], start=1):
        f, ctx = buckets[d]
        results.append((col_idx, f, ctx))
    return results


def _numeric_value(fact: XbrlFact, units: dict[str, XbrlUnit]) -> int | None:
    """KRW measure or KRWEPS divide-unit only (module docstring) — both are
    already base-unit values, no multiplier needed."""
    if fact.unit_ref is None:
        return None
    unit = units.get(fact.unit_ref)
    if unit is None:
        return None
    is_krw = unit.measure is not None and unit.measure.local == "KRW"
    is_krweps = unit.numerator is not None and unit.numerator.local == "KRW" and unit.denominator is not None
    if not (is_krw or is_krweps):
        return None
    try:
        num = Decimal(fact.value_raw)
    except (InvalidOperation, ValueError):
        logger.warning(f"non-numeric value_raw for {fact.qname}: {fact.value_raw!r}")
        return None
    return int(num.to_integral_value(rounding=ROUND_HALF_UP))


def _flatten_from(tree: PresentationTree, start: str) -> list[str]:
    """DFS pre-order starting at an arbitrary node (not necessarily a tree
    root) — used to walk the LineItems/Axis *subtrees* of an SCE role rather
    than the whole role tree (module docstring's SCE section)."""
    out: list[str] = []

    def visit(loc_label: str) -> None:
        out.append(loc_label)
        for child in tree.nodes[loc_label].children:
            visit(child)

    visit(start)
    return out


def _find_by_local(tree: PresentationTree, ns: str, local: str, source: str) -> str | None:
    """Locate the (expected-unique) node whose element is `{ns}local` — used
    to find the SCE role's `ComponentsOfEquityAxis` and
    `StatementOfChangesInEquityLineItems` locators by concept identity rather
    than by position (Phase 3-6 §1/§2)."""
    matches = [label for label, node in tree.nodes.items()
               if node.element.ns == ns and node.element.local == local]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(f"{source}: {len(matches)} nodes with element {{{ns}}}{local}, using the first")
    return matches[0]


def _col_label_chain(loc_label: str, tree: PresentationTree, label_of: dict[str, str], stop_before: str) -> str:
    """Ancestor label chain for an SCE column, bounded to the
    `ComponentsOfEquityAxis` subtree (excludes the Axis locator itself and
    everything above it — Table/LineItems-abstract/role-root are not part of
    the *column* hierarchy). ">"-joined, same convention as
    `report_lines.py::_build_col_labels` (whose `detect_sce_anomalies()`
    consumer only reads the LAST segment via `lab.split(">")[-1]`, so an
    extra/short ancestor chain here is harmless either way — this just aims
    to be a faithful rendering of the true XBRL structure)."""
    chain: list[str] = [label_of[loc_label]]
    parent = tree.nodes[loc_label].parent_loc_label
    while parent is not None and parent != stop_before:
        chain.append(label_of[parent])
        parent = tree.nodes[parent].parent_loc_label
    chain.reverse()
    return ">".join(chain)


def _dim_candidates(
    element: QName,
    facts_by_qname: dict[QName, list[XbrlFact]],
    contexts: dict[str, XbrlContext],
    required_dims: frozenset[Dimension],
) -> list[tuple[XbrlFact, XbrlContext]]:
    """Generalizes `_basis_candidates` to an arbitrary exact dimension set —
    SCE non-total columns need basis + `ComponentsOfEquityAxis`=member (2
    dims), not just basis (1 dim). Still an *exact* set match (Phase 0 §7):
    a context carrying any dimension beyond `required_dims` is excluded, same
    reasoning as `_basis_candidates` (note-role reuse of the same axis)."""
    out: list[tuple[XbrlFact, XbrlContext]] = []
    for f in facts_by_qname.get(element, []):
        if f.is_nil or not f.value_raw:
            continue
        ctx = contexts.get(f.context_ref)
        if ctx is None or frozenset(ctx.dims) != required_dims:
            continue
        out.append((f, ctx))
    return out


def _sce_row_label(base_label: str, element: QName, ifrs_full_ns: str, ctx: XbrlContext) -> str:
    """Synthesizes the date (+ 기말/기초 marker) suffix that lets
    `detect_sce_anomalies()` keep working unmodified (module docstring). Only
    instant-typed rows get a suffix — duration rows (flow items: 당기순이익/
    배당/유상증자…) keep the bare concept label, matching the HTML source
    where only 기초/기말 balance rows carry a date in their account-name text
    (report_lines.py::_emit_sce_lines docstring)."""
    if ctx.period_kind != "instant":
        return base_label
    marker = None
    if element.ns == ifrs_full_ns and element.local == _SCE_ENDING_LOCAL:
        marker = "기말"          # the ONLY marker detect_sce_anomalies() greps for
    elif element.ns == ifrs_full_ns and element.local == _SCE_BEGINNING_LOCAL:
        marker = "기초"          # not required for compat, added for fidelity/symmetry
    suffix = f" ({marker})" if marker else ""
    return f"{base_label}{suffix} ({ctx.instant})"


def _check_sce_column_rollup(
    lines: list[ReportLineRow], col_parent_of: dict[int, int | None], source: str,
) -> None:
    """Self-consistency check, NOT a filter — logs only (module docstring).
    For every (row_order) group, verifies each parent column's value equals
    the sum of its *direct* child columns' values, when both are present.
    This can only ever catch OUR OWN column-tree wiring bugs (a real filing
    typo would show up here too, but `detect_sce_anomalies()` is the intended
    place to surface real 원문 anomalies post-storage, with `original_value`/
    `suggested_value` semantics `report_lines` rows don't carry)."""
    children_of: dict[int, list[int]] = {}
    for child, parent in col_parent_of.items():
        if parent is not None:
            children_of.setdefault(parent, []).append(child)
    if not children_of:
        return

    by_row: dict[int, dict[int, int]] = {}
    for l in lines:
        if l.value_won is not None:
            by_row.setdefault(l.row_order, {})[l.col_index] = l.value_won

    for row_order, cells in by_row.items():
        for parent_col, child_cols in children_of.items():
            parent_val = cells.get(parent_col)
            child_vals = [cells[c] for c in child_cols if c in cells]
            if parent_val is None or len(child_vals) != len(child_cols):
                continue  # incomplete row (e.g. 비지배지분 not present in a prior period) — not comparable
            total = sum(child_vals)
            if total != parent_val and abs(total - parent_val) > abs(parent_val or 1) * _SCE_ROLLUP_TOL:
                logger.warning(
                    f"{source}: row_order={row_order} col{parent_col} column-rollup mismatch: "
                    f"parent={parent_val:,} != sum(children {child_cols})={total:,}"
                )


def _emit_statement_lines(
    *, tree: PresentationTree, facts_by_qname: dict[QName, list[XbrlFact]],
    contexts: dict[str, XbrlContext], units: dict[str, XbrlUnit],
    labels: dict[QName, list[Label]], basis_axis: QName, basis_member: QName,
    statement: str, basis: str, corp_code: str, rcept_no: str,
    report_fiscal_year: int, report_fiscal_period: str, period_end_date: date,
) -> list[ReportLineRow]:
    flat = _flatten_preorder(tree)
    row_order_of = {loc_label: i for i, loc_label in enumerate(flat)}
    node_role_of = _compute_node_roles(flat, tree)
    label_of = {
        loc_label: _resolve_label(node.element, node.preferred_label, labels)
        for loc_label, node in tree.nodes.items()
    }
    source = f"{rcept_no}/{statement}/{basis}"

    out: list[ReportLineRow] = []
    for loc_label in flat:
        node = tree.nodes[loc_label]
        candidates = _basis_candidates(node.element, facts_by_qname, contexts, basis_axis, basis_member)
        if not candidates:
            continue
        for col_idx, fact, ctx in _resolve_columns(candidates, period_end_date, source):
            value = _numeric_value(fact, units)
            if value is None:
                continue
            out.append(ReportLineRow(
                corp_code=corp_code,
                rcept_no=rcept_no,
                report_fiscal_year=report_fiscal_year,
                report_fiscal_period=report_fiscal_period,
                statement=statement,
                basis=basis,
                section_path=_section_path(loc_label, tree, label_of),
                label_raw=label_of[loc_label],
                col_index=col_idx,
                context_fiscal_year=report_fiscal_year - col_idx,
                period_kind=ctx.period_kind,
                is_cumulative=(ctx.period_kind == "duration" and report_fiscal_period != "FY"),
                value_won=value,
                adecimal=0,  # XBRL facts are already base-unit values (module docstring)
                unit_source=UNIT_SOURCE_XBRL,
                source_ref=f"{statement}_{basis}/{node.element.local}"[:180],
                context_raw=fact.context_ref[:255],
                row_order=row_order_of[loc_label],
                depth=node.depth,
                node_role=node_role_of[loc_label],
                table_seq=0,  # one role = one coherent statement tree, no multi-table split
                table_title=None,
            ))
    return out


def _emit_sce_lines(
    *, tree: PresentationTree, facts_by_qname: dict[QName, list[XbrlFact]],
    contexts: dict[str, XbrlContext], units: dict[str, XbrlUnit],
    labels: dict[QName, list[Label]], basis_axis: QName, basis_member: QName,
    ifrs_full_ns: str, basis: str, corp_code: str, rcept_no: str,
    report_fiscal_year: int, report_fiscal_period: str,
) -> list[ReportLineRow]:
    """SCE emitter — see module docstring's SCE section for the full design
    (col_index=자본구성요소 위치, period encoded via row_order block-stacking +
    label_raw date suffix, not context_fiscal_year/period_kind)."""
    source = f"{rcept_no}/SCE/{basis}"

    axis_loc = _find_by_local(tree, ifrs_full_ns, _CE_AXIS_LOCAL, source)
    lineitems_loc = _find_by_local(tree, ifrs_full_ns, _SCE_LINEITEMS_LOCAL, source)
    if axis_loc is None or lineitems_loc is None:
        logger.warning(f"{source}: ComponentsOfEquityAxis 또는 LineItems 노드 없음, 스킵")
        return []
    ce_axis = QName(ns=ifrs_full_ns, local=_CE_AXIS_LOCAL)

    # Labels resolved for the WHOLE role tree, not just the column/row
    # subtrees — `_section_path` walks a row's ancestor chain past
    # `lineitems_loc` up to the role's true root (Table/Abstract), so it
    # needs labels for those ancestors too (same reason `_emit_statement_lines`
    # resolves labels over `tree.nodes` wholesale, not just its own flat list).
    label_of = {
        loc_label: _resolve_label(node.element, node.preferred_label, labels)
        for loc_label, node in tree.nodes.items()
    }

    # ── Columns: DFS over the axis's domain subtree(s) (Phase 3-6 §1). ──────
    axis_children = tree.nodes[axis_loc].children
    if not axis_children:
        logger.warning(f"{source}: ComponentsOfEquityAxis 에 domain 자식 없음, 스킵")
        return []
    col_flat: list[str] = []
    for domain_root in axis_children:
        col_flat.extend(_flatten_from(tree, domain_root))
    col_index_of = {loc_label: i for i, loc_label in enumerate(col_flat)}
    col_label_of = {
        loc_label: _col_label_chain(loc_label, tree, label_of, stop_before=axis_loc)
        for loc_label in col_flat
    }
    col_parent_of: dict[int, int | None] = {}
    for loc_label in col_flat:
        parent = tree.nodes[loc_label].parent_loc_label
        col_parent_of[col_index_of[loc_label]] = col_index_of.get(parent)  # None if parent == axis_loc (a root)
    total_col = col_flat[0]  # the axis's first domain member = the "총계" root (Phase 3-6 §1)

    # ── Rows: DFS over the LineItems subtree (Phase 3-6 §2). ────────────────
    row_flat = _flatten_from(tree, lineitems_loc)
    row_index_of = {loc_label: i for i, loc_label in enumerate(row_flat)}
    row_node_role_of = _compute_node_roles(row_flat, tree)
    # Period blocks are stacked at a fixed stride so they never overlap
    # regardless of how many periods a given row actually has (module
    # docstring's SCE section — row_order here is a display/grouping
    # convenience, not a period claim; context_fiscal_year/period_kind stay
    # NULL, matching the HTML-parser SCE convention).
    stride = len(row_flat)

    out: list[ReportLineRow] = []
    for row_loc in row_flat:
        row_node = tree.nodes[row_loc]
        row_depth = row_node.depth
        row_role = row_node_role_of[row_loc]
        row_section_path = _section_path(row_loc, tree, label_of)
        base_label = label_of[row_loc]

        # ★ Canonical period ranking comes from the TOTAL column only, then
        # every other column looks up that *same date* in its own bucket —
        # resolving periods independently per column (rank-by-recency on each
        # column's own candidate set) is wrong whenever a member column is
        # missing a period a sibling has (e.g. 비지배지분 absent in an
        # earlier year): the local rankings then shift out of step and
        # period_idx 1 can mean a different real date in different columns,
        # silently mixing unrelated periods into the same row_order (found
        # empirically — hanwha/baxelbio both tripped `_check_sce_column_rollup`
        # until this was fixed). The total column is the right anchor because
        # a statement's grand-total line exists for every period covered
        # (Phase 3-6 §1: "총계열은 context dims==1"), while member columns can
        # legitimately be sparse.
        total_required = frozenset({Dimension(axis=basis_axis, member=basis_member)})
        total_candidates = _dim_candidates(row_node.element, facts_by_qname, contexts, total_required)
        total_buckets = _bucket_by_period(total_candidates, source)
        canonical_dates = sorted(total_buckets, reverse=True)
        if not canonical_dates:
            continue  # this row concept has no total-column value anywhere — nothing to anchor periods to

        for col_loc in col_flat:
            col_idx = col_index_of[col_loc]
            if col_loc == total_col:
                col_buckets = total_buckets
            else:
                col_element = tree.nodes[col_loc].element
                required = frozenset({
                    Dimension(axis=basis_axis, member=basis_member),
                    Dimension(axis=ce_axis, member=col_element),
                })
                candidates = _dim_candidates(row_node.element, facts_by_qname, contexts, required)
                col_buckets = _bucket_by_period(candidates, source)
            if not col_buckets:
                continue

            for period_idx, d in enumerate(canonical_dates):
                bucket = col_buckets.get(d)
                if bucket is None:
                    continue  # this column has no value for this particular period — sparse, not an error
                fact, ctx = bucket
                value = _numeric_value(fact, units)
                if value is None:
                    continue
                out.append(ReportLineRow(
                    corp_code=corp_code,
                    rcept_no=rcept_no,
                    report_fiscal_year=report_fiscal_year,
                    report_fiscal_period=report_fiscal_period,
                    statement="SCE",
                    basis=basis,
                    section_path=row_section_path,
                    label_raw=_sce_row_label(base_label, row_node.element, ifrs_full_ns, ctx),
                    col_index=col_idx,                       # position (자본 구성요소), NOT a period
                    col_label=col_label_of[col_loc],
                    context_fiscal_year=None,                # ★ no year claim (module docstring)
                    period_kind=None,                        # varies per row/period, same as HTML SCE
                    is_cumulative=False,
                    value_won=value,
                    adecimal=0,
                    unit_source=UNIT_SOURCE_XBRL,
                    source_ref=f"SCE_{basis}/{row_node.element.local}"[:180],
                    context_raw=fact.context_ref[:255],
                    row_order=period_idx * stride + row_index_of[row_loc],
                    depth=row_depth,
                    node_role=row_role,
                    table_seq=0,
                    table_title=None,
                ))

    _check_sce_column_rollup(out, col_parent_of, source)
    return out


def extract_report_lines_xbrl(
    zip_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
    period_end_date: date | None,
) -> list[ReportLineRow]:
    """Layer-2 extraction entry point for a DART XBRL instance zip. Returns
    `ReportLineRow` — same shape `report_lines.py::extract_report_lines`
    returns, so both feed the same `store_report_lines`/`store_report_tables`.

    Never raises — any failure (bad zip, unparseable member, missing
    period_end_date) is logged and yields `[]`, matching
    `extract_report_lines`'s own contract (a missing/malformed source is not
    a pipeline-halting error, see fin2/extract/report_lines.py's XML-root-None
    branch)."""
    zip_path = Path(zip_path)
    if period_end_date is None:
        logger.warning(f"[report_lines_xbrl] {rcept_no}: period_end_date 없음 — col0 판정 불가, 스킵")
        return []

    try:
        with tempfile.TemporaryDirectory(prefix="xbrl_instance_") as tmp:
            tmp_dir = Path(tmp)
            members = _extract_zip_members(zip_path, tmp_dir)

            instance = parse_instance(members.xbrl)
            pre_trees = parse_presentation(members.pre, instance.nsmap)
            labels = merge_label_catalogs(
                parse_labels(members.lab_ko, instance.nsmap) if members.lab_ko else {},
                parse_labels(members.lab_en, instance.nsmap) if members.lab_en else {},
            )
            core_roles = index_core_roles(build_role_map(members.xsd))

            basis_axis_ns = instance.nsmap.get("ifrs-full")
            if basis_axis_ns is None:
                logger.warning(f"[report_lines_xbrl] {rcept_no}: 'ifrs-full' 접두 없음, 스킵")
                return []
            basis_axis = QName(ns=basis_axis_ns, local=_BASIS_AXIS_LOCAL)

            facts_by_qname: dict[QName, list[XbrlFact]] = {}
            for f in instance.facts:
                facts_by_qname.setdefault(f.qname, []).append(f)

            lines: list[ReportLineRow] = []
            for (statement, basis), role_info in core_roles.items():
                if statement not in _SUPPORTED_STATEMENTS and statement != _SUPPORTED_SCE_STATEMENT:
                    continue  # note-adjacent statement kinds, if role_map.py ever adds one
                tree = pre_trees.get(role_info.role_uri)
                if tree is None:
                    logger.warning(f"[report_lines_xbrl] {rcept_no}: role {role_info.role_uri} "
                                    f"_pre.xml 에 없음, 스킵")
                    continue
                basis_member = QName(ns=basis_axis_ns, local=_BASIS_MEMBER_LOCAL[basis])
                # ★ per-(statement, basis) try/except — one bad role (a parser
                # bug, or a malformed/unusual filing) must not zero out the
                # other statements this rcept already extracted cleanly. The
                # outer try/except (bad zip, unparseable member) is a
                # different failure class and stays coarse-grained.
                try:
                    if statement == _SUPPORTED_SCE_STATEMENT:
                        lines.extend(_emit_sce_lines(
                            tree=tree, facts_by_qname=facts_by_qname, contexts=instance.contexts,
                            units=instance.units, labels=labels, basis_axis=basis_axis,
                            basis_member=basis_member, ifrs_full_ns=basis_axis_ns, basis=basis,
                            corp_code=corp_code, rcept_no=rcept_no,
                            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
                        ))
                    else:
                        lines.extend(_emit_statement_lines(
                            tree=tree, facts_by_qname=facts_by_qname, contexts=instance.contexts,
                            units=instance.units, labels=labels, basis_axis=basis_axis,
                            basis_member=basis_member, statement=statement, basis=basis,
                            corp_code=corp_code, rcept_no=rcept_no,
                            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
                            period_end_date=period_end_date,
                        ))
                except Exception as e:
                    logger.warning(f"[report_lines_xbrl] {rcept_no}: {statement}/{basis} 추출 실패 "
                                    f"({type(e).__name__}: {e}), 이 role 만 스킵")

            if not core_roles:
                logger.debug(f"[report_lines_xbrl] {rcept_no}: core statement role 없음 → 빈 결과")
            return lines
    except Exception as e:
        logger.warning(f"[report_lines_xbrl] {rcept_no}: 추출 실패 ({type(e).__name__}: {e})")
        return []
