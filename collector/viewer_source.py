"""Web-viewer source for filings whose DART package has no main XML
(docs/plans/viewer_xml_source_policy_2026-10-10.md, user decisions 2026-10-10).

A "viewer-source filing" has `download_tasks.viewer_xml_path` and no completed main XML; layer 2
reads the viewer XML (the printed document) instead of XBRL / PDF. The downloader builds it when
the package has no XML and retries the package for 180 days; `layer2_reload_pending` marks a
filing whose layer-2 source changed (viewer rebuilt, or the main XML finally arrived).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

# Rows whose layer 2 comes from the viewer XML (no completed main XML).
VIEWER_SOURCE_SQL = ("dt.viewer_xml_path IS NOT NULL "
                     "AND NOT (dt.status = 'completed' AND dt.file_type = 'xml')")
RETRY_DAYS = 180          # document.xml retries stop after 6 months (user decision)


def statement_nodes(scraper, rcept_no: str):
    """[(title to use, toc node)] of the statement / notes sections (viewer_xml.select_sections)."""
    from fin2.extract.html_viewer import parse_toc_tree
    from fin2.extract.viewer_xml import select_sections
    return select_sections(parse_toc_tree(scraper.fetch_toc_page(rcept_no) or ""))


def signature(nodes) -> Optional[str]:
    """Title + length of every statement section — changes when DART re-renders the document."""
    if not nodes:
        return None
    key = "|".join(f"{n.text}:{n.length}" for _, n in nodes)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def build_viewer_xml(scraper, rcept_no: str, near_path: str, nodes=None) -> Optional[tuple[str, str]]:
    """Fetch the statement sections and write <folder of near_path>/<rcept>.xml.
    Returns (path, signature), or None when the document has no statement section."""
    from fin2.extract.viewer_xml import build_document
    nodes = nodes if nodes is not None else statement_nodes(scraper, rcept_no)
    if not nodes:
        return None
    sections = [(title, scraper.fetch_viewer_section(rcept_no, dcm_no=n.dcm_no, ele_id=n.ele_id,
                                                     offset=n.offset, length=n.length, dtd=n.dtd) or b"")
                for title, n in nodes]
    # <rcept>.viewer.xml: the package's own XML, when it arrives, is saved as <rcept>.xml
    out = Path(near_path).with_name(f"{rcept_no}.viewer.xml")
    out.write_bytes(build_document(sections))
    return str(out), signature(nodes)


def refresh_viewer(session, scraper, rcept_no: str, near_path: str) -> str:
    """Build the viewer XML if missing, or rebuild it when the document's statement sections
    changed; flags the filing for a layer-2 reload when it did. Returns 'built' / 'rebuilt' /
    'unchanged' / 'no_statement'. Never raises for a fetch problem (the caller keeps retrying)."""
    from sqlalchemy import text
    row = session.execute(text("SELECT viewer_xml_path, viewer_sig FROM download_tasks WHERE rcept_no = :r"),
                          {"r": rcept_no}).fetchone()
    nodes = statement_nodes(scraper, rcept_no)
    sig = signature(nodes)
    if sig is None:
        return "no_statement"
    if row and row.viewer_xml_path and row.viewer_sig == sig and Path(row.viewer_xml_path).exists():
        return "unchanged"
    built = build_viewer_xml(scraper, rcept_no, near_path, nodes)
    if built is None:
        return "no_statement"
    path, sig = built
    session.execute(text("""
        UPDATE download_tasks SET viewer_xml_path = :p, viewer_sig = :s, viewer_built_at = :t,
               layer2_reload_pending = TRUE
        WHERE rcept_no = :r"""), {"p": path, "s": sig, "t": datetime.now(), "r": rcept_no})
    return "rebuilt" if row and row.viewer_xml_path else "built"
