"""`_is_metadata_only` 완화(자간 공백 · 회사명+단위줄)의 **영향 범위**를 수정 전/후로 비교한다.

이 술어는 현대 서식 전 문서가 타는 공용 경로다(`title_text_for_classify` 안). 표제를
"건너뛸 메타줄"로 볼지 결정하므로, 완화하면 **없던 표가 새로 잡히는** 방향으로 움직인다.
그게 의도한 회수인지, 아니면 남의 표를 주워오는 것인지는 실측으로만 갈린다.

방법 — 수정 전 구현을 되살려(monkeypatch) 같은 문서에 두 번 돌리고 선택 차이를 낸다.
`title_text_for_classify` 안에서 모듈 전역으로 참조되므로 모듈 속성 교체가 그대로 먹는다.

사용:
    python scripts/measure_metadata_only_impact.py --sample 400
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
import fin2.extract.statement_titles as ST
import fin2.extract.text as T

SQL = """
SELECT f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no, d.file_path
  FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
 WHERE f.fiscal_year >= 2015
   AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
 ORDER BY md5(f.rcept_no) LIMIT :n
"""

_OLD_STMT_TITLE = [re.compile(r"재무상태표|대차대조표"),
                   re.compile(r"포괄손익계산서|손익계산서"),
                   re.compile(r"현금흐름표")]


def old_is_metadata_only(txt: str) -> bool:
    """수정 **이전** 구현 그대로. 비교 기준선."""
    if not txt:
        return True
    if any(p.search(txt) for p in _OLD_STMT_TITLE):
        return False
    return bool(ST._UNIT_ONLY_RE.match(txt)) or bool(ST._PERIOD_MARK.search(txt))


def snapshot(root):
    tree = root.getroottree()
    g = T._detect_body_statement_tables(root, T._detect_fin_type(root), include_sce=True)
    return {(code, tree.getpath(tbl)): (unit, len(table_direct_rows(tbl)),
                                        " ".join("".join(tbl.itertext()).split())[:60])
            for code, v in g.items() for tbl, unit, _k in v}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(SQL), {"n": args.sample}).fetchall()

    new_impl = ST._is_metadata_only
    docs = changed = added_n = removed_n = added_rows = 0
    added_by_code: Counter = Counter()
    samples: list = []
    removed_all: list = []

    for corp_name, fy, fp, rcept, fpth in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        docs += 1

        ST._is_metadata_only = old_is_metadata_only
        before = snapshot(root)
        ST._is_metadata_only = new_impl
        after = snapshot(root)

        added = {k: v for k, v in after.items() if k not in before}
        removed = {k: v for k, v in before.items() if k not in after}
        if not added and not removed:
            continue
        changed += 1
        added_n += len(added)
        removed_n += len(removed)
        for (code, _p), (unit, nrows, head) in added.items():
            added_by_code[code] += 1
            added_rows += nrows
            if len(samples) < 12:
                samples.append(("추가", corp_name, fy, fp, rcept, code, unit, nrows, head))
        for (code, _p), (unit, nrows, head) in removed.items():
            removed_all.append((corp_name, fy, fp, rcept, code, unit, nrows, head))

    print(f"=== 적재분 표본 {docs}건 ===")
    print(f"  선택이 바뀐 문서 : {changed} ({changed / max(docs,1) * 100:.1f}%)")
    print(f"  추가된 표        : {added_n}  (직접 데이터행 {added_rows:,}행)  ← 회수")
    print(f"  제거된 표        : {removed_n}  ← 0 이어야 안전(기존 것을 잃지 않음)")
    print("\n  추가된 표의 섹션코드:")
    for k, v in added_by_code.most_common():
        print(f"    {k:6s} {v}")
    if removed_all:
        print("\n  ★제거된 표(전수) — 확인 필요:")
        for e in removed_all[:20]:
            print(f"    {e[0]} {e[1]}{e[2]} {e[3]} {e[4]} unit={e[5]} rows={e[6]}")
            print(f"       {e[7]!r}")
    print("\n  추가 사례:")
    for kind, corp_name, fy, fp, rcept, code, unit, nrows, head in samples:
        print(f"    {corp_name} {fy}{fp} {rcept} {code} unit={unit} rows={nrows}")
        print(f"       {head!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
