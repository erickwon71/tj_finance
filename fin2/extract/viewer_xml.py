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


def _append_text(out, text):
    """Append text after the last child of `out` (or to its text when it has none)."""
    if not text:
        return
    if len(out):
        out[-1].tail = (out[-1].tail or "") + text
    else:
        out.text = (out.text or "") + text


def _convert(el):
    """lxml.html element -> DART-style XML element (upper-case tags, same attributes and text).

    <BR> is dropped, its tail kept: the viewer renders DART's in-cell line break `&cr;` as <BR>,
    and the DART XML reader deletes `&cr;` (parser/xml/dart_xml_parser.py). BR is not a DART tag,
    so a kept <BR/> was read as the text '<BR/>' — labels like 'Ⅴ. 이익잉여금<BR/>' (176 filings)
    and statement titles hidden behind an empty '<P><BR/></P>' (2026-10-10)."""
    if not isinstance(el.tag, str):
        return None
    out = etree.Element(el.tag.upper())
    for k, v in el.attrib.items():
        out.set(k.upper(), v)
    out.text = el.text
    for ch in el:
        if isinstance(ch.tag, str) and ch.tag.upper() == "BR":
            _append_text(out, ch.tail)
            continue
        c = _convert(ch)
        if c is not None:
            out.append(c)
            c.tail = ch.tail
    return out


def strip_line_breaks(root) -> int:
    """Drop <BR> elements (keeping their tail text) from an already built viewer XML tree —
    the same rule as _convert, for prints built before it. Returns the number removed."""
    n = 0
    for br in list(root.iter("BR")):
        parent = br.getparent()
        prev = br.getprevious()
        if br.tail:
            if prev is not None:
                prev.tail = (prev.tail or "") + br.tail
            else:
                parent.text = (parent.text or "") + br.tail
        parent.remove(br)
        n += 1
    return n


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
        if "주석" in t and not re.match(r"^\d+\.", t):
            # '반기재무제표에 대한 주석' (review-report layout) is the notes of the statements
            # just before it, not a statement section itself (R381).
            if last_std:
                out.append(("3. 연결재무제표 주석" if last_std.startswith("2.") else "5. 재무제표 주석", n))
                last_std = None
        elif is_statement_section(n.text):
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
    fix_basis_titles(doc)
    return etree.tostring(doc, encoding="utf-8", xml_declaration=True)


# A statement heading table: '[반기|분기]연결재무상태표 제60(당)기 반기 2014년 06월 30일 현재 ...'.
_STMT_HEAD = re.compile(
    r"^(?:\(첨부\))?(?:제\d+(?:\(당\))?기)?(?:반기|분기|[1-4]분기)?(연결)?"
    r"(?:재무상태표|대차대조표|포괄손익계산서|손익계산서|자본변동표|현금흐름표)")
_CONS_TITLE, _SEP_TITLE = "2. 연결재무제표", "4. 재무제표"


def _heading_basis(el) -> str | None:
    """'c' / 's' when `el` is a short statement heading table (it carries a period phrase:
    '현재' / '부터' / '까지'), else None. Note text such as '재무상태표상 순재산액' is not one."""
    if not isinstance(el.tag, str) or el.tag not in ("TABLE", "P"):
        return None
    t = re.sub(r"\s+", "", "".join(el.itertext()))
    if el.tag == "P":
        # a title-only paragraph ('분기연결재무상태표', the period line is the next table); the review
        # phrase '"검토를받은분기재무제표"' may share the paragraph
        t = re.sub(r'^"검토를받은[^"]*"', "", t)
        m = _STMT_HEAD.match(t)
        return "c" if m and m.group(1) and m.end() == len(t) else ("s" if m and m.end() == len(t) else None)
    if len(t) > 450 or not re.search(r"현재|부터|까지", t):
        return None
    m = _STMT_HEAD.match(t)
    return None if m is None else ("c" if m.group(1) else "s")


def fix_basis_titles(doc) -> int:
    """Name each statement SECTION-2 by what its body prints, not by the TOC node text (R381).

    The generator maps a TOC node to '2. 연결재무제표' only when the node text says 연결. Review-report
    layouts ('반 기 재 무 제 표') and 'XI. 재무제표 등' nodes print 연결 statements under a plain
    title, so layer 2 stored them as basis=separate (BYC 20140829001554, 대신증권 20141121000333,
    한성크린텍 20150730000147). Only titles that do not already say 연결 are touched: a body whose
    headings are all 연결 gets '2. 연결재무제표'; a body with both is split at the first heading of the
    other basis; the notes section right after a consolidated-only statement section gets
    '3. 연결재무제표 주석'. Returns the number of sections retitled or split."""
    changed, prev_basis, prev_title = 0, None, None
    for s2 in doc.iter("SECTION-2"):          # the print already names its consolidated statements
        tn = (s2.findtext("TITLE") or "").replace(" ", "")
        if "연결" in tn and "주석" not in tn:
            return 0
    for s2 in list(doc.iter("SECTION-2")):
        title_el = s2.find("TITLE")
        title = (title_el.text or "") if title_el is not None else ""
        tn = title.replace(" ", "")
        body = [c for c in s2 if c is not title_el]
        marks = [(i, b) for i, c in enumerate(body) if (b := _heading_basis(c))]
        if "주석" in tn:
            if prev_basis == "c" and tn.startswith("5.") and title_el is not None:
                title_el.text, changed = "3. 연결재무제표 주석", changed + 1
            continue
        if not marks:
            if prev_basis == "c" and title == prev_title and title_el is not None:   # the notes node
                title_el.text = "3. 연결재무제표 주석"
                changed += 1
            prev_basis = None
            continue
        prev_title = title
        bases = {b for _, b in marks}
        # prev_basis is 'c' only for a section THIS function made consolidated: older prints whose
        # titles were right (or merely duplicated) are left as they are.
        if "연결" in tn or bases == {"s"}:
            prev_basis = None
        elif bases == {"c"}:
            title_el.text, prev_basis, changed = _CONS_TITLE, "c", changed + 1
        else:                                                    # both printed: split the section
            cuts, cur = [], None
            for i, b in marks:
                if b != cur:
                    cuts.append((i, b))
                    cur = b
            parent, pos = s2.getparent(), s2.getparent().index(s2)
            cuts[0] = (0, cuts[0][1])                            # the preamble stays in segment 1
            for k, (start, b) in enumerate(cuts):
                end = cuts[k + 1][0] if k + 1 < len(cuts) else len(body)
                seg = etree.Element("SECTION-2")
                etree.SubElement(seg, "TITLE", ATOC="Y").text = _CONS_TITLE if b == "c" else _SEP_TITLE
                for c in body[start:end]:
                    seg.append(c)
                parent.insert(pos + 1 + k, seg)
            parent.remove(s2)
            prev_basis, changed = ("c" if cuts[-1][1] == "c" else None), changed + 1
    return changed
