"""Build fin2/taxonomy/ko_label_index.json (R229) from the DART taxonomy Korean label linkbases
in taxonomy_cache/ (lab_ifrs-ko_*, lab_dart-ko_*; the general-corporate-data gcd files are
skipped). Roles used: standard label, terseLabel, totalLabel — not period start/end labels
(SCE context), negated labels (opposite sign) or the DART 'dart_label' role (contextual
captions such as '기말 장부금액').

Usage (cwd = repo root):
  python scripts/build_ko_label_index.py
Fetch a missing vintage first with curl -L (https) into taxonomy_cache/ under the same
naming as parser/xbrl_instance/external_taxonomy._cache_path.
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.getcwd())

from lxml import etree  # noqa: E402

from collector.config import TAXONOMY_CACHE_DIR  # noqa: E402
from fin2.taxonomy.ko_labels import INDEX_PATH, label_key  # noqa: E402

LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
ROLES = {"http://www.xbrl.org/2003/role/label", "http://www.xbrl.org/2003/role/terseLabel",
         "http://www.xbrl.org/2003/role/totalLabel"}


def read_linkbase(path):
    """[(concept id, label text)] of one label linkbase."""
    root = etree.parse(str(path)).getroot()
    out = []
    for link in root.iter(f"{{{LINK}}}labelLink"):
        locs, labels = {}, defaultdict(list)
        for el in link:
            kind = el.get(f"{{{XLINK}}}type")
            key = el.get(f"{{{XLINK}}}label")
            if kind == "locator":
                concept = (el.get(f"{{{XLINK}}}href") or "").split("#")[-1]
                # pre-2019 vintages use the 'ifrs_' prefix for the same IFRS concepts
                locs[key] = "ifrs-full_" + concept[5:] if concept.startswith("ifrs_") else concept
            elif kind == "resource" and el.get(f"{{{XLINK}}}role") in ROLES and el.text:
                labels[key].append(el.text.strip())
        for el in link.iter(f"{{{LINK}}}labelArc"):
            concept = locs.get(el.get(f"{{{XLINK}}}from"))
            for text in labels.get(el.get(f"{{{XLINK}}}to"), ()):
                if concept and not text.endswith(("[abstract]", "[text block]", "[axis]", "[member]",
                                                  "[table]", "[line items]")):
                    out.append((concept, text))
    return out


def main():
    files = sorted(p for p in TAXONOMY_CACHE_DIR.iterdir()
                   if "labels_lab_" in p.name and "-ko_" in p.name and "gcd" not in p.name)
    index = defaultdict(set)
    for p in files:
        pairs = read_linkbase(p)
        for concept, text in pairs:
            k = label_key(text)
            if k:
                index[k].add(concept)
        print(f"{len(pairs):6d}  {p.name}")
    data = {k: sorted(v) for k, v in sorted(index.items())}
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print("labels", len(data), "->", INDEX_PATH)


if __name__ == "__main__":
    main()
