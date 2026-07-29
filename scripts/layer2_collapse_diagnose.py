"""주석 섹션 붕괴/절단 개별 진단 — '적재 결함인가 원문 특성인가' (READ-ONLY).

판정 기준
--------
붕괴한 filing 에 대해 **원문에 주석 헤딩이 실제로 있는지**를 본다.
  · 있는데 못 잡았다  → 계층2 적재(헤딩 검출) 결함  ← 우리가 고칠 것
  · 원문에 없다        → 원문 특성(구조 없는 보고서). 고칠 대상이 아님

헤딩 후보는 **주석 섹션 안의 <P>/<TITLE>** 에서만 찾는다. 문서 전체를 훑으면
본문 재무제표 제목('4. 현금흐름표')이나 날짜 조각('2024.12.31. 현재')이 섞인다
— 앞선 측정들이 전부 이걸로 실패했다.

Usage
-----
    python scripts/layer2_collapse_diagnose.py --rcept 20250328001069 20250320001351
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from parser.xml.section_detector import (DART_NOTE_SECTIONS, SEC_CONSOL_NOTE,
                                         SEC_SEP_NOTE, _extract_note_heading,
                                         assign_note_tables_with_titles,
                                         classify_dart_section)

PATH_SQL = text(
    "SELECT d.file_path, f.corp_code FROM download_tasks d JOIN filings f USING (rcept_no) "
    "WHERE d.rcept_no = :r AND d.file_type='xml' LIMIT 1"
)


def scan_note_region(root):
    """주석 섹션 안의 <P>/<TITLE> 만 순회하며 헤딩 후보를 뽑는다."""
    current = None
    titles, paras = [], []
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            t = el.find("TITLE")
            if t is not None:
                current = classify_dart_section("".join(t.itertext()))
        elif tag in ("TITLE", "P") and current in DART_NOTE_SECTIONS:
            txt = " ".join("".join(el.itertext()).split())
            head = _extract_note_heading(txt)
            if head:
                (titles if tag == "TITLE" else paras).append(head)
    return titles, paras


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rcept", nargs="+", required=True)
    args = ap.parse_args()

    with get_session() as session:
        for rcept in args.rcept:
            row = session.execute(PATH_SQL, {"r": rcept}).fetchone()
            if not row:
                print(f"{rcept}: 경로 없음\n")
                continue
            try:
                root = etree.parse(row.file_path,
                                   etree.XMLParser(recover=True)).getroot()
            except Exception as e:  # noqa: BLE001
                print(f"{rcept}: 파싱 실패 {e}\n")
                continue

            sec_tables = assign_note_tables_with_titles(root)
            got = {
                k: sorted({t for _tbl, t in v if t})
                for k, v in sec_tables.items()
            }
            n_tables = sum(len(v) for v in sec_tables.values())
            titles, paras = scan_note_region(root)

            print(f"=== {rcept} (corp {row.corp_code}) ===")
            print(f"  추출기가 붙인 주석제목 종류: "
                  f"연결 {len(got.get(SEC_CONSOL_NOTE, []))} · "
                  f"별도 {len(got.get(SEC_SEP_NOTE, []))} · 표 {n_tables}개")
            print(f"  원문 주석영역 헤딩 후보: <TITLE> {len(titles)} · <P> {len(paras)}")
            uniq = sorted({f"{n}. {t}" for n, t in (titles + paras)},
                          key=lambda s: int(s.split(".")[0]))
            print(f"  후보 고유 {len(uniq)}: {uniq[:6]}{' …' if len(uniq) > 6 else ''}")

            if len(uniq) > 2 and len(got.get(SEC_CONSOL_NOTE, [])) <= 1:
                print("  판정: ★적재 결함 — 원문에 헤딩이 있는데 추출기가 못 붙였다")
            elif len(uniq) <= 2:
                print("  판정: 원문 특성 — 주석영역에 번호 헤딩 자체가 거의 없다")
            else:
                print("  판정: 부분 검출 — 원문 헤딩 일부만 붙었다")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
