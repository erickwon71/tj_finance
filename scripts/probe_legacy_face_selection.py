"""구형 레이아웃(`XI. 재무제표 등`)에서 **앵커 분류기가 무엇을 집는지** 전수 계측한다.

왜 이 계측이 먼저인가 — 2023년 DB손해보험 사고(이익잉여금 8.5경원)는 본문 섹션 분류가
실패했을 때 **앵커 없는 폴백**(`_detect_sections_from_tables` 의 느슨한 키워드 매칭)이
주석표를 본문으로 집어서 났다. 구형 레이아웃은 재무제표와 **주석이 같은 섹션**에 있으므로
(실측 20141128001023: 연결BS/IS/SCE/CF → `연결재무제표에 대한 주석` → 별도 4표 → 별도 주석),
섹션이 본문을 보장해주지 못한다. 따라서 표제 앵커(`classify_statement_title`)가 유일한
방어선이고, 그것이 실제로 충분한지 원문으로 확인해야 한다(R9).

측정 내용 — `재무제표등` 섹션의 **모든** 표에 앵커 분류기를 걸어:
  · 선택된 표의 (basis, stmt) 시퀀스와 직접 데이터행 수
  · **주석 마커 이후에 선택된 표**(= 오염 후보)를 별도 표시
  · 문서당 선택 수 분포(정상 기대치 = 연결 4 + 별도 4 = 최대 8)

사용:
    python scripts/probe_legacy_face_selection.py
    python scripts/probe_legacy_face_selection.py --detail 5
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    classify_dart_section, normalize_dart_section_title, table_direct_rows,
)
from fin2.extract.statement_titles import classify_statement_title, title_text
from fin2.extract.text import _table_has_data_rows, declared_unit

from scripts.probe_legacy_layout_gap import SQL_GAP  # 같은 공백 정의를 공유한다

LEGACY_SECTION = "재무제표등"

# 주석 구간 시작 마커(실측). '연결재무제표에 대한 주석' / '별도재무제표에 대한 주석' 및
# 번호 주석 헤딩. 이 마커 이후 선택은 오염 후보로 본다.
_NOTE_MARK_RE = re.compile(r"재무제표에?\s*대한\s*주석|^주석$")


def probe(rcept_no: str, file_path: str | None) -> dict | None:
    if not file_path or not Path(file_path).exists():
        return None
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return None

    inside = False
    in_note = False
    picks: list[tuple] = []
    n_tables = 0

    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            t = el.find("TITLE")
            if t is not None:
                norm = normalize_dart_section_title(" ".join("".join(t.itertext()).split()))
                if inside and norm != LEGACY_SECTION:
                    break
                inside = norm == LEGACY_SECTION
            continue
        if not inside:
            continue

        # 표 안쪽 요소는 구조가 아니다.
        anc, in_table = el.getparent(), False
        while anc is not None:
            if isinstance(anc.tag, str) and anc.tag.upper() == "TABLE":
                in_table = True
                break
            anc = anc.getparent()
        if in_table:
            continue

        txt = " ".join("".join(el.itertext()).split())
        if tag == "P" and _NOTE_MARK_RE.search(txt):
            in_note = True
            continue
        if tag != "TABLE":
            continue
        n_tables += 1
        cls = classify_statement_title(title_text(el))
        if cls is None:
            continue
        # note_seen = 직전 선택 이후 주석 마커를 지나왔는가. 연결 4표 뒤 '연결재무제표에 대한
        # 주석' 을 지나 별도 4표로 넘어가는 정상 전이도 여기 걸리므로, 판단은 시퀀스로 한다.
        picks.append((cls[0], cls[1], len(table_direct_rows(el)),
                      bool(_table_has_data_rows(el)), declared_unit(el), in_note))
        in_note = False

    return {"rcept_no": rcept_no, "n_tables": n_tables, "picks": picks}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", type=int, default=0)
    args = ap.parse_args()

    with get_session() as s:
        tasks = {r[0]: r[1] for r in s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks")).fetchall()}
        rows = s.execute(text(SQL_GAP)).fetchall()

    n_pick_dist: Counter = Counter()
    seq_dist: Counter = Counter()
    tainted = []
    no_data_picks = 0
    total_docs = 0
    shown = 0

    for corp_code, corp_name, fy, fp, rt, rcept, filed in rows:
        r = probe(rcept, tasks.get(rcept))
        if r is None or r["n_tables"] == 0:
            continue
        # 구형 레이아웃만 대상 — 현대 서식은 이 섹션이 없어 n_tables=0 으로 걸러진다
        total_docs += 1
        picks = r["picks"]
        n_pick_dist[len(picks)] += 1
        seq_dist[tuple(f"{b[:3]}.{s}" for b, s, *_ in picks)] += 1
        for b, st, nrows, has_data, unit, note_side in picks:
            if note_side:
                tainted.append((corp_name, fy, fp, rcept, b, st, nrows))
            if not has_data:
                no_data_picks += 1

        if args.detail and shown < args.detail:
            shown += 1
            print(f"── {corp_name} {fy}{fp} {rcept}  섹션표={r['n_tables']} 선택={len(picks)}")
            for b, st, nrows, has_data, unit, note_side in picks:
                flag = " ⚠주석이후" if note_side else ""
                print(f"     {b:12s} {st:3s} rows={nrows:4d} data={has_data} unit={unit}{flag}")
            print()

    print(f"=== 구형 레이아웃 문서 {total_docs}건 ===")
    print("\n문서당 선택 표 수 분포:")
    for k, v in sorted(n_pick_dist.items()):
        print(f"  {k:3d}개 선택 → {v:4d}건")
    print(f"\n데이터행 없는 선택(제목표): {no_data_picks}")
    print(f"주석 마커 이후 선택(오염 후보): {len(tainted)}")
    for t in tainted[:20]:
        print(f"   {t}")
    print("\n선택 시퀀스 상위 12:")
    for k, v in seq_dist.most_common(12):
        print(f"  {v:4d}  {' → '.join(k) if k else '(없음)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
