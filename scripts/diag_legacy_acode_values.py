"""
item 4 진단 — legacy ACODE 재무제표 값이 본문 XML 에 실제로 있는지 확인.

BSS_/BS_/INC_/IS_/CF_ 등 계정 prefix 의 TE[@ACODE] 셀과 표기값을 덤프.
또 재무제표 섹션 제목(재무상태표/손익계산서/현금흐름표)이 본문에 있는지 본다.

    PYTHONPATH=. .venv_tj_finance/bin/python scripts/diag_legacy_acode_values.py <xml_path>
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.xml.dart_xml_parser import _parse_xml_file

FS_PREFIXES = ("BS", "BSS", "INC", "IS", "CF", "CIS", "PL", "AS", "LB", "CA", "TOT", "ASUM", "AJ", "AO", "AK")


def cell_text(te) -> str:
    raw = (te.text or "").strip()
    if not raw:
        p = te.find("P")
        if p is not None:
            raw = (p.text or "").strip()
    if not raw:
        raw = "".join(te.itertext()).strip()
    return raw[:30]


def main() -> None:
    path = Path(sys.argv[1])
    root = _parse_xml_file(path)
    if root is None:
        print("파싱 실패")
        return

    # 계정성 prefix TE 덤프
    numeric_cells = []
    for te in root.findall(".//TE[@ACODE]"):
        ac = te.get("ACODE", "")
        head = ac.split("_", 1)[0]
        if head in FS_PREFIXES:
            txt = cell_text(te)
            # 숫자 포함 셀만(값 추정)
            if any(ch.isdigit() for ch in txt):
                numeric_cells.append((ac, txt))

    print(f"계정성 prefix({'/'.join(FS_PREFIXES)}) 숫자셀: {len(numeric_cells)}")
    for ac, txt in numeric_cells[:40]:
        print(f"  {ac:30} = {txt}")

    # 재무제표 관련 제목 탐색
    print("\n재무제표 섹션 제목 탐색:")
    fs_kw = ("재무상태표", "대차대조표", "손익계산서", "포괄손익", "현금흐름표", "재무제표", "재무에 관한")
    for tag in ("TITLE", "SECTION-1", "SECTION-2", "TABLE"):
        for el in root.findall(f".//{tag}"):
            t = "".join(el.itertext()).strip()
            for kw in fs_kw:
                if kw in t[:60]:
                    print(f"  [{tag}] {t[:55]}")
                    break


if __name__ == "__main__":
    main()
