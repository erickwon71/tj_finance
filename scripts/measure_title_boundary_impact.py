"""`title_text_for_classify` 데이터표 경계 추가의 **영향 범위**를 수정 전/후로 비교한다.

이 함수는 현대 서식 전 문서가 타는 공용 경로다. 그래서 "처분계산서가 빠졌다" 만으로는
부족하고, **정당한 재무제표까지 같이 빠지지 않았는지**를 적재분에서 확인해야 한다.

방법 — 수정 전 구현을 그대로 되살려(monkeypatch) 같은 문서에 두 번 돌리고,
선택된 표 집합의 차이를 낸다. 사라진 표/새로 생긴 표를 모두 표본과 함께 보고한다.

사용:
    python scripts/measure_title_boundary_impact.py --sample 600
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
from parser.xml.section_detector import table_direct_rows
import fin2.extract.text as T


SQL = """
SELECT f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no, d.file_path
  FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
 WHERE f.fiscal_year >= 2015
   AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
 ORDER BY md5(f.rcept_no) LIMIT :n
"""


import fin2.extract.statement_titles as _ST
_NEW_CLASSIFY = _ST.classify_statement_in_body_section


def old_classify(title, include_sce=False):
    """수정 **이전** 분류기 — 처분계산서 배제가 없던 상태."""
    import re as _re
    if not title:
        return None
    t = _re.sub(r"\s+", "", title)
    if _ST._SCE_RE.search(t):
        return "SCE" if include_sce else None
    for name, code in _ST._BODY_STMT_ORDER:
        if name in t:
            return code
    return None


def snapshot(root):
    """{(섹션코드, 문서내 XPath): (단위, 행수, 앞머리)}.

    ★ 키에 `id(element)` 를 쓰면 안 된다 — lxml 요소는 접근할 때마다 새 프록시가 만들어져
      `id()` 가 달라진다(같은 표가 제거·추가 양쪽에 잡히는 가짜 diff 를 실제로 만들었다).
      문서 내 XPath 는 같은 트리에서 안정적이다.
    """
    tree = root.getroottree()
    g = T._detect_body_statement_tables(root, T._detect_fin_type(root), include_sce=True)
    out = {}
    for code, v in g.items():
        for tbl, unit, _k in v:
            head = " ".join("".join(tbl.itertext()).split())[:60]
            out[(code, tree.getpath(tbl))] = (unit, len(table_direct_rows(tbl)), head)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=600)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(SQL), {"n": args.sample}).fetchall()

    new_impl = _NEW_CLASSIFY
    docs = changed = 0
    removed_n = added_n = 0
    removed_rows = 0
    removed_kind: Counter = Counter()
    samples: list = []
    other_removed: list = []

    for corp_name, fy, fp, rcept, fpth in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        docs += 1

        T.classify_statement_in_body_section = old_classify
        before = snapshot(root)
        T.classify_statement_in_body_section = new_impl
        after = snapshot(root)

        removed = {k: v for k, v in before.items() if k not in after}
        added = {k: v for k, v in after.items() if k not in before}
        if not removed and not added:
            continue
        changed += 1
        removed_n += len(removed)
        added_n += len(added)
        for (code, _p), (unit, nrows, head) in removed.items():
            removed_rows += nrows
            t = re.sub(r"\s+", "", head)
            # 이익잉여금처분계산서/결손금처리계산서의 실제 표기 변형(실측):
            # '미처분이익잉여금' · '미처리결손금' · '처분예정일/처분확정일' 헤더
            if re.search(r"미처분이익잉여금|미처리결손금|이익잉여금처분|결손금처리|처분예정일|처분확정일", t):
                removed_kind["이익잉여금처분계산서/결손금처리계산서"] += 1
            else:
                removed_kind["★기타 — 정당한 재무제표일 수 있음(확인 필요)"] += 1
                if len(other_removed) < 15:
                    other_removed.append((corp_name, fy, fp, rcept, code, unit, nrows, head))
            if len(samples) < 20:
                samples.append(("제거", corp_name, fy, fp, rcept, code, unit, nrows, head))
        for (code, _p), (unit, nrows, head) in added.items():
            if len(samples) < 20:
                samples.append(("추가", corp_name, fy, fp, rcept, code, unit, nrows, head))

    print(f"=== 적재분 표본 {docs}건 ===")
    print(f"  선택이 바뀐 문서 : {changed} ({changed / max(docs,1) * 100:.1f}%)")
    print(f"  제거된 표        : {removed_n}  (직접 데이터행 {removed_rows:,}행)")
    print(f"  추가된 표        : {added_n}   ← 0 이어야 안전(가산 없음)")
    print("\n  제거된 표의 정체:")
    for k, v in removed_kind.most_common():
        print(f"    {v:5d}  {k}")
    if other_removed:
        print("\n  ★기타로 분류된 제거 표(전수):")
        for e in other_removed:
            print(f"    {e[0]} {e[1]}{e[2]} {e[3]} {e[4]} unit={e[5]} rows={e[6]}")
            print(f"       {e[7]!r}")

    print("\n  사례:")
    for kind, corp_name, fy, fp, rcept, code, unit, nrows, head in samples:
        print(f"    [{kind}] {corp_name} {fy}{fp} {rcept} {code} unit={unit} rows={nrows}")
        print(f"           {head!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
