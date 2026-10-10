"""DART web-viewer HTML -> DART-style XML document (layer 2 source for filings without a main XML).

Some filings' original package on DART holds XBRL only (no document XML); 1,639 FY2015+ filings
were loaded from XBRL. XBRL is not the print: contra accounts / cash outflows carry the opposite
sign and the labels are taxonomy labels (R0-2, 2026-10-10). The web viewer (`report/viewer.do`)
serves the printed document section by section as HTML rendered from the same DART XML
(TABLE/THEAD/TR/TH/TD, full-width-space indents, unit lines in title tables). Wrapping those
sections in the DART XML skeleton (SECTION-1 > SECTION-2 > TITLE) lets the main extractor
(`fin2.extract.report_lines.extract_report_lines`) read them like any other filing.

Probe (20150827000474 피노 2015 H1): 277 BS/IS/CF cells — 246 equal to the XBRL load, 30 differ
in sign only (the printed convention), 0 other differences.
"""
from __future__ import annotations

import re

from lxml import etree, html

SECTION1_TITLE = "III. 재무에 관한 사항"


def _convert(el):
    """lxml.html element -> DART-style XML element (upper-case tags, same attributes and text)."""
    if not isinstance(el.tag, str):
        return None
    out = etree.Element(el.tag.upper())
    for k, v in el.attrib.items():
        out.set(k.upper(), v)
    out.text = el.text
    for ch in el:
        c = _convert(ch)
        if c is not None:
            out.append(c)
            c.tail = ch.tail
    return out


def is_statement_section(toc_text: str) -> bool:
    """TOC nodes to fetch: (연결)재무제표 and their notes."""
    t = toc_text.replace(" ", "")
    return "재무제표" in t and "요약" not in t and "기타" not in t and "보고서" not in t


def select_sections(nodes) -> list[tuple[str, object]]:
    """[(title to use, toc node)] — the standard report layout as is; an audit/review-report
    layout ([첨부정정]: '(첨부)반 기 연 결 재 무 제 표' followed by a bare '주석' node) mapped to
    the standard titles the main extractor knows (2./4. 재무제표, 3./5. 주석)."""
    out, last_std = [], None
    for n in nodes:
        t = n.text.replace(" ", "")
        if is_statement_section(n.text):
            if re.match(r"^\d+\.", t):           # standard layout: keep the title
                out.append((n.text, n))
                last_std = None
            else:                                   # attached statements
                last_std = "2. 연결재무제표" if "연결" in t else "4. 재무제표"
                out.append((last_std, n))
        elif t == "주석" and last_std:
            out.append(("3. 연결재무제표 주석" if last_std.startswith("2.") else "5. 재무제표 주석", n))
            last_std = None
    return out


def build_document(sections: list[tuple[str, bytes]]) -> bytes:
    """[(toc title, section html bytes)] -> DART-style XML document bytes (utf-8)."""
    doc = etree.Element("DOCUMENT")
    body = etree.SubElement(doc, "BODY")
    s1 = etree.SubElement(body, "SECTION-1")
    etree.SubElement(s1, "TITLE", ATOC="Y").text = SECTION1_TITLE
    for toc_title, raw in sections:
        root = html.fromstring(raw.decode("utf-8", errors="replace")) if raw else None
        b = root.find("body") if root is not None else None
        s2 = etree.SubElement(s1, "SECTION-2")
        etree.SubElement(s2, "TITLE", ATOC="Y").text = toc_title
        if b is None:
            continue
        for ch in b:
            if ch.tag == "p" and "section-2" in (ch.get("class") or ""):
                continue      # the section heading, already the TITLE
            c = _convert(ch)
            if c is not None:
                s2.append(c)
                c.tail = ch.tail
    return etree.tostring(doc, encoding="utf-8", xml_declaration=True)
