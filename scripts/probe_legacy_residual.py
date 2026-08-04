"""구형 레이아웃 후보 109건 중 **앵커 선택이 0인 문서**의 실제 구조를 규명한다.

`probe_legacy_face_selection.py` 결과:
  · `재무제표등` 섹션 보유 87건 → 73건은 face 3~8표 선택(주석 오염 0), **14건은 0표**
  · 나머지 22건은 `재무제표등` 섹션 자체가 없음

이 두 잔여군이 무엇인지 원문으로 본다(추측 금지 — R9).

사용:
    python scripts/probe_legacy_residual.py
    python scripts/probe_legacy_residual.py --dump 20150302000123
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import normalize_dart_section_title, table_direct_rows
from fin2.extract.statement_titles import classify_statement_title, title_text
from fin2.extract.text import _table_has_data_rows

from scripts.probe_legacy_layout_gap import SQL_GAP

LEGACY_SECTION = "재무제표등"


def _walk(root, section: str | None):
    """section=None 이면 문서 전체, 아니면 그 섹션 구간의 (tag, el) 을 문서순으로 낸다."""
    inside = section is None
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            t = el.find("TITLE")
            if t is not None and section is not None:
                norm = normalize_dart_section_title(" ".join("".join(t.itertext()).split()))
                if inside and norm != section:
                    return
                inside = norm == section
            continue
        if not inside:
            continue
        anc, in_table = el.getparent(), False
        while anc is not None:
            if isinstance(anc.tag, str) and anc.tag.upper() == "TABLE":
                in_table = True
                break
            anc = anc.getparent()
        if not in_table:
            yield tag, el


def analyze(root) -> dict:
    titles = []
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            t = el.find("TITLE")
            if t is not None:
                titles.append(normalize_dart_section_title(
                    " ".join("".join(t.itertext()).split())))
    has_legacy = LEGACY_SECTION in titles

    sec = LEGACY_SECTION if has_legacy else None
    n_tables = n_data = n_pick = 0
    data_titles = []
    for tag, el in _walk(root, sec):
        if tag != "TABLE":
            continue
        n_tables += 1
        has_data = bool(_table_has_data_rows(el))
        if has_data:
            n_data += 1
        if classify_statement_title(title_text(el)):
            n_pick += 1
        elif has_data and len(data_titles) < 8:
            data_titles.append(title_text(el)[:110])
    return {"has_legacy": has_legacy, "titles": titles, "n_tables": n_tables,
            "n_data": n_data, "n_pick": n_pick, "data_titles": data_titles}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", help="단건 rcept_no 정밀 덤프")
    args = ap.parse_args()

    with get_session() as s:
        tasks = {r[0]: r[1] for r in s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks")).fetchall()}
        rows = s.execute(text(SQL_GAP)).fetchall()

    if args.dump:
        root = _parse_xml_file(Path(tasks[args.dump]))
        a = analyze(root)
        print(f"has_legacy={a['has_legacy']} 표={a['n_tables']} 데이터표={a['n_data']} "
              f"선택={a['n_pick']}")
        print("섹션 TITLE:")
        for t in a["titles"]:
            print(f"   {t[:80]}")
        print("\n선택 안 된 데이터표의 표제:")
        for t in a["data_titles"]:
            print(f"   {t!r}")
        return 0

    buckets: Counter = Counter()
    samples: dict[str, list] = {}

    for corp_code, corp_name, fy, fp, rt, rcept, filed in rows:
        fpth = tasks.get(rcept)
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        a = analyze(root)
        # 현대 서식(본문섹션 보유)은 이 트랙 대상이 아니다 — 제외
        if any(t in ("연결재무제표", "재무제표") for t in a["titles"]):
            continue

        if a["n_pick"] > 0:
            b = "★앵커가 face 선택함(복구 가능)"
        elif not a["has_legacy"]:
            b = "재무제표등 섹션 없음"
        elif a["n_data"] == 0:
            b = "재무제표등에 데이터표 없음"
        else:
            b = "재무제표등에 데이터표는 있으나 선택 0"
        buckets[b] += 1
        samples.setdefault(b, []).append((corp_name, fy, fp, rcept, a))

    print("=== 구형 레이아웃 후보 잔여 분류 ===")
    for k, v in buckets.most_common():
        print(f"  {v:4d}  {k}")

    for k in ("재무제표등 섹션 없음", "재무제표등에 데이터표 없음",
              "재무제표등에 데이터표는 있으나 선택 0"):
        for corp_name, fy, fp, rcept, a in samples.get(k, [])[:3]:
            print(f"\n── [{k}] {corp_name} {fy}{fp} {rcept} "
                  f"표={a['n_tables']} 데이터표={a['n_data']}")
            print(f"   섹션: {[t[:24] for t in a['titles'][:14]]}")
            for t in a["data_titles"][:5]:
                print(f"   미선택 표제: {t!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
