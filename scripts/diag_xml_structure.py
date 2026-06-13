"""
item 4 진단 — 단일 XML 의 TE[@ACODE]/ACONTEXT 태깅 구조 분석.

추출 0행 보고서가 왜 Track A 에 안 잡히는지 규명:
  - TE[@ACODE] 셀이 아예 없는가? (Track A 비대상)
  - 있으나 prefix 가 ifrs-full_/dart_ 가 아닌가? (금융업 taxonomy?)
  - 있으나 ACONTEXT 가 없는가?
  - 섹션 제목/표 구조는?

    PYTHONPATH=. .venv_tj_finance/bin/python scripts/diag_xml_structure.py <xml_path>
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.xml.dart_xml_parser import _parse_xml_file


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: diag_xml_structure.py <xml_path>")
        return
    path = Path(sys.argv[1])
    root = _parse_xml_file(path)
    if root is None:
        print("XML 루트 없음/파싱 실패")
        return

    all_te = root.findall(".//TE")
    te_acode = root.findall(".//TE[@ACODE]")
    print(f"파일: {path.name}  크기={path.stat().st_size:,} bytes")
    print(f"TE 총: {len(all_te):,}  /  TE[@ACODE]: {len(te_acode):,}")

    prefix = Counter()
    has_ctx = 0
    sample_acodes = []
    for te in te_acode:
        ac = te.get("ACODE", "")
        head = ac.split("_", 1)[0] + "_" if "_" in ac else ac[:12]
        prefix[head] += 1
        if te.get("ACONTEXT"):
            has_ctx += 1
        if len(sample_acodes) < 20:
            sample_acodes.append((ac, te.get("ACONTEXT", "")[:40], te.get("ADECIMAL", "")))

    print(f"\nACODE prefix 분포:")
    for p, n in prefix.most_common(20):
        print(f"  {p:28} {n}")
    print(f"\nACONTEXT 보유 TE[@ACODE]: {has_ctx:,} / {len(te_acode):,}")

    print(f"\nACODE 샘플 20:")
    for ac, ctx, dec in sample_acodes:
        print(f"  ACODE={ac:45} ADEC={dec:4} ACONTEXT={ctx}")

    # 섹션 제목(TITLE/표제) 일부
    titles = []
    for tag in ("TITLE", "SECTION-1", "SECTION-2"):
        for el in root.findall(f".//{tag}"):
            t = "".join(el.itertext()).strip()[:50]
            if t:
                titles.append(f"{tag}: {t}")
    print(f"\n섹션/제목 샘플 15:")
    for t in titles[:15]:
        print(f"  {t}")


if __name__ == "__main__":
    main()
