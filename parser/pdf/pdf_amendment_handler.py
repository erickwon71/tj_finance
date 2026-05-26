"""
DART PDF Amendment Handler — parse original + amendment PDF pairs.

Strategy:
  1. Classify the amendment PDF into one of three types:
       FULL_REPORT   – cover (정정신고 page) + full financial report
                       → parse financial sections of the amendment directly
       PARTIAL_COVER – only correction notice with 정정 전/후 table, no full financials
                       → parse original, extract corrections, override matching facts
       NON_FINANCIAL – non-financial notice (제출기한 연장, 감사보고서 등)
                       → use original as-is
  2. Return a single ParseResult using the best available data.

Usage:
    from parser.pdf.pdf_amendment_handler import parse_pdf_with_amendment

    result = parse_pdf_with_amendment(
        orig_path    = Path(".../20170515000000.pdf"),   # original filing PDF
        amend_path   = Path(".../20170515005040.pdf"),   # amendment PDF
        rcept_no     = "20170515005040",                 # amendment rcept_no (used in DB)
        corp_code    = "00163673",
        fiscal_year  = 2017,
        fiscal_period= "Q1",
        report_type  = "quarter",
    )
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

from parser.xml.dart_xml_parser import ParseResult, FactRow
from parser.pdf.dart_pdf_parser import parse_dart_pdf
from parser.pdf.pdf_table_extractor import parse_amount_cell, clean_account_name


# ── Amendment type ─────────────────────────────────────────────────────────────

class AmendmentType(Enum):
    FULL_REPORT   = "full_report"    # Cover + complete financial report (use amendment)
    PARTIAL_COVER = "partial_cover"  # Short correction notice; apply corrections to original
    NON_FINANCIAL = "non_financial"  # No financial content; use original as-is


# ── Correction entry extracted from 정정 전/후 table ──────────────────────────

@dataclass
class CorrectionEntry:
    account_name_raw: str           # Raw text from "정정 후" column
    account_name: str               # Cleaned account name
    after_value: Optional[int]      # Corrected value (None if parsing fails)
    period_label: str               # e.g. "제56기 1분기" (best-effort)
    source_row: int = 0             # Row index in the correction table


# ── Regex helpers ─────────────────────────────────────────────────────────────

# Headers that mark the correction table
_CORRECTION_TABLE_HEADERS = {'항 목', '항목', '정정사유', '정 정 전', '정 정 후', '정정 전', '정정 후'}

# Period label patterns: "제56기 1분기", "제56기", "당기", etc.
_PERIOD_LABEL_RE = re.compile(r'제\s*\d+\s*기|당기|전기|제\d+기')

# Sign correction patterns: "(2,521)" or "△3,690" etc.
_AMOUNT_RE = re.compile(
    r'[\(（]?([\d,]+)[\)）]?|[△▲]([\d,]+)|-[\d,]+'
)


# ── Classification ────────────────────────────────────────────────────────────

def classify_amendment_pdf(pdf) -> AmendmentType:
    """
    Determine the type of an amendment PDF.

    Decision logic:
      1. Check first 4 pages for "정정신고" keyword.
         If absent → NON_FINANCIAL (or it's not really an amendment PDF).
      2. If present, check page count and whether financial tables exist:
         - Many pages (>10) AND financial tables found → FULL_REPORT
         - Few pages OR no financial tables → PARTIAL_COVER
    """
    from parser.pdf.pdf_section_detector import find_financial_pages

    page_count = len(pdf.pages)

    # -- Check for 정정신고 keyword in first 4 pages --------------------------
    correction_notice_found = False
    for page in pdf.pages[:4]:
        text = page.extract_text() or ""
        if "정정" in text and ("신고" in text or "공시" in text or "보고" in text):
            correction_notice_found = True
            break

    if not correction_notice_found:
        return AmendmentType.NON_FINANCIAL

    # -- If very short document, it can only be a cover ----------------------
    if page_count <= 6:
        return AmendmentType.PARTIAL_COVER

    # -- Longer document: check if financial tables are present --------------
    fin_pages = find_financial_pages(pdf)
    has_financial_tables = len(fin_pages) >= 2

    if has_financial_tables:
        return AmendmentType.FULL_REPORT
    else:
        return AmendmentType.PARTIAL_COVER


# ── Correction table extractor ────────────────────────────────────────────────

def extract_correction_table(pdf) -> list[CorrectionEntry]:
    """
    Extract correction entries from the "정정 전/후" table in an amendment PDF.

    The table is typically on page 2 and has columns:
      [항 목] [정정사유] [정 정 전] [정 정 후]

    Returns a list of CorrectionEntry (one per corrected account).
    An empty list is returned if the table cannot be found or parsed.
    """
    corrections: list[CorrectionEntry] = []

    for page in pdf.pages[:6]:      # Correction table is always in the first few pages
        tables = page.extract_tables()
        for table in tables:
            if not table or len(table) < 2:
                continue

            # Detect correction table by header row
            header = [str(c or "").strip() for c in table[0]]
            if not _is_correction_header(header):
                continue

            # Find column indices
            col_before, col_after = _find_correction_columns(header)
            if col_after is None:
                continue

            logger.debug(f"Correction table found: {len(table)-1} data rows, "
                         f"col_after={col_after}")

            # Parse data rows
            for row_idx, row in enumerate(table[1:], start=1):
                if not row or len(row) <= col_after:
                    continue

                after_cell = str(row[col_after] or "").strip()
                if not after_cell:
                    continue

                entries = _parse_correction_cell(after_cell, row_idx)
                corrections.extend(entries)

    return corrections


def _is_correction_header(header: list[str]) -> bool:
    """Check if a table header row matches the correction table format."""
    header_set = set(header)
    # Must have both "정정 후" variants and at least one of the others
    has_after  = any(c in {"정 정 후", "정정 후"} for c in header_set)
    has_before = any(c in {"정 정 전", "정정 전"} for c in header_set)
    return has_after and has_before


def _find_correction_columns(header: list[str]) -> tuple[Optional[int], Optional[int]]:
    """Return (col_before_idx, col_after_idx) from header."""
    col_before = col_after = None
    for i, h in enumerate(header):
        h = h.strip()
        if h in {"정 정 전", "정정 전"}:
            col_before = i
        elif h in {"정 정 후", "정정 후"}:
            col_after = i
    return col_before, col_after


def _parse_correction_cell(cell_text: str, row_idx: int) -> list[CorrectionEntry]:
    """
    Parse the "정정 후" cell which may contain multiple lines like:
        "제56기 1분기\n법인세비용 (2,521)"
        "이익잉여금, 자본합계 (12)"

    Returns one CorrectionEntry per account line found.
    """
    entries: list[CorrectionEntry] = []
    lines = [ln.strip() for ln in cell_text.replace("\r", "\n").split("\n") if ln.strip()]

    period_label = ""
    for line in lines:
        # Detect period label line (e.g. "제56기 1분기")
        if _PERIOD_LABEL_RE.search(line) and len(line) < 30:
            period_label = line
            continue

        # Try to extract account_name + value from the line
        # Patterns: "계정명 1,234"  "계정명 (1,234)"  "계정명 △1,234"
        # Split on last amount-like token
        match = re.search(
            r'^(.+?)\s+([\(\（\-△▲]?[\d,]+[\)\）]?)$',
            line
        )
        if not match:
            # Might be just an account name with no value on same line — skip
            continue

        account_raw = match.group(1).strip()
        value_str   = match.group(2).strip()

        account_clean = clean_account_name(account_raw)
        after_value   = parse_amount_cell(value_str, multiplier=1)  # Raw value; caller applies unit

        entries.append(CorrectionEntry(
            account_name_raw = account_raw,
            account_name     = account_clean,
            after_value      = after_value,
            period_label     = period_label,
            source_row       = row_idx,
        ))

    return entries


# ── Fact merger ───────────────────────────────────────────────────────────────

def apply_corrections(
    base_facts: list[FactRow],
    corrections: list[CorrectionEntry],
    unit_multiplier: int = 1_000_000,
) -> tuple[list[FactRow], int]:
    """
    Override matching facts in base_facts with corrected values.

    Matching strategy (best-effort):
      - Normalize both account names (lowercase, strip spaces)
      - Match on account_code if already mapped, otherwise raw name

    Returns:
        (updated_facts, override_count)
    """
    if not corrections:
        return base_facts, 0

    # Build a lookup: normalized_name → list[FactRow]
    name_index: dict[str, list[FactRow]] = {}
    for fact in base_facts:
        key = _normalize_name(fact.account_name_raw)
        name_index.setdefault(key, []).append(fact)

    override_count = 0
    for corr in corrections:
        if corr.after_value is None:
            continue

        key = _normalize_name(corr.account_name)
        matches = name_index.get(key, [])

        if not matches:
            # Try partial match on account_code prefix
            matches = [
                f for f in base_facts
                if corr.account_name in f.account_name_raw
                   or f.account_name_raw in corr.account_name
            ]

        if not matches:
            logger.debug(f"No match for correction: '{corr.account_name}' — skipping")
            continue

        # Scale correction value with the unit used in the original facts
        corrected_amount = corr.after_value * unit_multiplier

        for fact in matches:
            # Only override col_index=0 (current period) for safety
            if fact.col_index == 0:
                old_val = fact.amount
                fact.amount = corrected_amount
                logger.debug(
                    f"Corrected '{corr.account_name}': {old_val:,} → {corrected_amount:,}"
                )
                override_count += 1

    return base_facts, override_count


def _normalize_name(name: str) -> str:
    """Normalize account name for fuzzy matching."""
    return re.sub(r'[\s\.,·,]', '', name).lower()


# ── Main orchestrator ─────────────────────────────────────────────────────────

def parse_pdf_with_amendment(
    orig_path: Optional[Path],
    amend_path: Path,
    rcept_no:      str,
    corp_code:     str,
    fiscal_year:   int,
    fiscal_period: str,
    report_type:   str,
    rcept_no_orig: Optional[str] = None,
) -> ParseResult:
    """
    Parse a DART PDF filing that has an amendment, choosing the best data source.

    Args:
        orig_path:     Path to original (1st uploaded) PDF; None if not yet downloaded.
        amend_path:    Path to amendment PDF.
        rcept_no:      Amendment rcept_no (stored in DB as the final filing).
        rcept_no_orig: Original rcept_no (used for logging only).
        Other args:    Same as parse_dart_pdf().

    Returns:
        ParseResult tagged with parser_track='PDF_AMEND'.
    """
    try:
        import pdfplumber
    except ImportError:
        result = ParseResult(
            rcept_no=rcept_no, corp_code=corp_code,
            fiscal_year=fiscal_year, fiscal_period=fiscal_period,
            report_type=report_type, fin_type='B', is_ifrs=True,
            unit_multiplier=1, parser_track='PDF_AMEND',
        )
        result.parse_status = 'failed'
        result.errors.append('pdfplumber not installed')
        return result

    # -- Classify the amendment PDF -----------------------------------------
    with pdfplumber.open(str(amend_path)) as pdf_amend:
        amend_type = classify_amendment_pdf(pdf_amend)
        logger.info(
            f"Amendment PDF [{rcept_no}]: {amend_type.value} "
            f"({len(pdf_amend.pages)}pp)"
        )

        if amend_type == AmendmentType.FULL_REPORT:
            return _parse_full_report_amendment(
                pdf_amend, amend_path, rcept_no,
                corp_code, fiscal_year, fiscal_period, report_type,
            )

        elif amend_type == AmendmentType.PARTIAL_COVER:
            corrections = extract_correction_table(pdf_amend)
            logger.info(
                f"Partial cover [{rcept_no}]: "
                f"{len(corrections)} corrections extracted"
            )
        else:
            corrections = []

    # -- NON_FINANCIAL or PARTIAL_COVER: use original as base ---------------
    if orig_path is None or not orig_path.exists():
        logger.warning(
            f"Amendment [{rcept_no}] is {amend_type.value} "
            f"but original PDF is missing — falling back to amendment parse"
        )
        return parse_dart_pdf(
            amend_path, rcept_no, corp_code,
            fiscal_year, fiscal_period, report_type,
        )

    result = parse_dart_pdf(
        orig_path, rcept_no, corp_code,
        fiscal_year, fiscal_period, report_type,
    )
    result.parser_track = 'PDF_AMEND'

    if amend_type == AmendmentType.NON_FINANCIAL or not corrections:
        logger.debug(
            f"No corrections to apply for [{rcept_no}] "
            f"(type={amend_type.value}, n_corr={len(corrections)})"
        )
        return result

    # -- Apply corrections from PARTIAL_COVER to original facts -------------
    if result.parse_status in ('success', 'partial') and result.facts:
        unit = result.unit_multiplier if result.unit_multiplier else 1_000_000
        updated_facts, n_overrides = apply_corrections(
            result.facts, corrections, unit_multiplier=unit
        )
        result.facts = updated_facts
        if n_overrides > 0:
            result.errors.append(
                f"PDF amendment: {n_overrides} accounts overridden from 정정 전/후 table"
            )
            logger.info(
                f"Applied {n_overrides} corrections to [{rcept_no_orig or 'orig'}] "
                f"from amendment [{rcept_no}]"
            )

    return result


def _parse_full_report_amendment(
    pdf,
    amend_path: Path,
    rcept_no:      str,
    corp_code:     str,
    fiscal_year:   int,
    fiscal_period: str,
    report_type:   str,
) -> ParseResult:
    """
    Parse a FULL_REPORT amendment by calling the standard PDF parser on the
    amendment file.  The financial sections (skip cover pages) are parsed
    exactly like an original — find_financial_pages() naturally skips the
    short 정정신고 cover because it has no financial keywords.
    """
    result = parse_dart_pdf(
        amend_path, rcept_no, corp_code,
        fiscal_year, fiscal_period, report_type,
    )
    result.parser_track = 'PDF_AMEND'
    logger.info(
        f"Full-report amendment [{rcept_no}]: "
        f"facts={len(result.facts)}, status={result.parse_status}"
    )
    return result
