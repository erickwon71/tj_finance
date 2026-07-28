"""
Inspect how per-note headings are marked up in a DART XML (READ-ONLY, no DB).

Used to design the <P>-heading branch of
parser.xml.section_detector.assign_note_tables_with_titles: for ~57.5% of corps
the note headings are plain <P> text rather than <TITLE>, so we need to know
whether the heading sits in its own <P> or is glued to the following sentence.

Usage
-----
    python scripts/inspect_note_heading_markup.py <xml_path> [--needle 비용의 성격별]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from lxml import etree

_NUM_HEAD = re.compile(r"^\s*\d{1,2}\s*[.．]\s*(?!\d)\S")


def text_of(el) -> str:
    return " ".join("".join(el.itertext()).split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xml_path")
    ap.add_argument("--needle", default="비용의 성격별")
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    root = etree.parse(str(Path(args.xml_path)), etree.XMLParser(recover=True)).getroot()

    print("=== elements whose text starts with a note number ===")
    tally: dict[str, int] = {}
    shown = 0
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag not in ("P", "TITLE", "SPAN"):
            continue
        txt = text_of(el)
        if not txt or not _NUM_HEAD.match(txt):
            continue
        tally[tag] = tally.get(tag, 0) + 1
        if shown < args.limit:
            shown += 1
            print(f"  <{tag}> len={len(txt):>4}  {txt[:88]!r}")

    print(f"\n  tag tally: {tally}")

    print(f"\n=== context around needle {args.needle!r} ===")
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag not in ("P", "TITLE"):
            continue
        txt = text_of(el)
        if args.needle in txt:
            parent = el.getparent()
            sibs = list(parent) if parent is not None else []
            idx = sibs.index(el) if el in sibs else -1
            print(f"\n  hit <{tag}> idx={idx} in <{parent.tag if parent is not None else '?'}>")
            for j in range(max(0, idx - 1), min(len(sibs), idx + 4)):
                s = sibs[j]
                stag = s.tag.upper() if isinstance(s.tag, str) else "?"
                body = text_of(s)[:80]
                mark = " <<<" if j == idx else ""
                print(f"    [{j}] <{stag}> {body!r}{mark}")
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
