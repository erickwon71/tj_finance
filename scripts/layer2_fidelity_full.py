"""계층2 적재 충실성 전수 검증 — 역방향 + 정방향 (READ-ONLY, 샤딩 지원).

report_lines / note_lines 는 **유일한 DB 소스**다. 여기가 원문과 다르면 위 계층 검증은
전부 무의미하므로, 표본이 아니라 전수로 확인할 수 있어야 한다.

세 가지를 함께 본다 (서로 다른 실패 모드다)
--------------------------------------------
  ① 역방향 REVERSE  : DB 값이 원문 셀에 실재하는가.
                      실패 = **없는 값을 만들어냈다**. 0 이어야 한다.
  ② 정방향-A LOAD   : 추출기 출력이 DB 에 그대로 있는가.
                      실패 = **적재 단계에서 잃었다**. 0 이어야 한다.
  ③ 정방향-B DROP   : 추출기가 버린 표의 사유가 전부 의도된 것인가
                      (단위 미선언 / 데이터행 없음). 100% 가 목표가 아니다 —
                      "결측 > 오염" 원칙상 의도적 제외가 많다. 사유별 분포를 남긴다.

Usage
-----
    python scripts/layer2_fidelity_full.py --limit 30            # 표본
    python scripts/layer2_fidelity_full.py --shard 0/6           # 전수(샤드)
    python scripts/layer2_fidelity_full.py --year 2024 --limit 0 # 특정 연도 전수
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (_table_has_data_rows, declared_unit,
                                       extract_report_lines)
from parser.xml.dart_xml_parser import _parse_xml_file, sanitize_dart_xml
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles)

_MULTS = (1, 1_000, 1_000_000, 100_000_000)
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
      {year_clause}
    ORDER BY f.rcept_no
"""

DB_SQL = text(
    """
    SELECT statement, basis, section_path, table_seq, label_raw, row_order,
           col_index, value_won
    FROM {tbl} WHERE rcept_no = :r AND value_won IS NOT NULL
    """
)


def source_numbers(root) -> set[str]:
    out: set[str] = set()
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.upper() not in ("TD", "TE", "TH", "TU"):
            continue
        s = "".join(el.itertext()).strip()
        if not s:
            continue
        s = s.replace(",", "").replace(" ", "").replace(" ", "")
        s = s.strip("()△▲-−+원%")
        if s and _NUM_RE.fullmatch(s):
            out.add(s)
            if "." in s:                     # '(208.00)' → '208'
                out.add(s.split(".")[0])
                out.add(s.rstrip("0").rstrip("."))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--limit", type=int, default=30, help="0 = 전수")
    ap.add_argument("--shard", help="a/n")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--show", type=int, default=6)
    args = ap.parse_args()

    t: Counter[str] = Counter()
    bad: list[str] = []
    t0 = time.time()

    with get_session() as session:
        yc = "AND f.fiscal_year = :y" if args.year else ""
        rows = list(session.execute(
            text(TARGETS_SQL.format(year_clause=yc)),
            {"y": args.year} if args.year else {},
        ).fetchall())
        if args.shard:
            a, n = (int(x) for x in args.shard.split("/"))
            rows = [r for i, r in enumerate(rows) if i % n == a]
        elif args.limit:
            random.Random(args.seed).shuffle(rows)
            rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing", flush=True)

        for i, f in enumerate(rows, 1):
            if i % 200 == 0:
                el = time.time() - t0
                print(f"  … {i}/{len(rows)} ({el/i:.2f}s/filing)", flush=True)
            p = Path(f.file_path)
            if not p.exists():
                t["파일없음"] += 1
                continue
            try:
                # ★추출기와 **같은 경로**로 파싱해야 한다. 직접 fromstring 하면 구형
                #   EUC-KR 보고서에서 텍스트가 깨져 원문 숫자를 못 찾고 허위 불일치가 난다
                #   (초판이 이래서 2018 사업보고서 1건에서 15건 허위 실패).
                root = _parse_xml_file(p)
                if root is None:
                    t["파싱실패"] += 1
                    continue
            except Exception:  # noqa: BLE001
                t["파싱실패"] += 1
                continue
            t["filing"] += 1

            # ── ③ DROP: 추출기가 본 주석 표와 폐기 사유
            for sec in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
                for tbl_el, _title in assign_note_tables_with_titles(root).get(sec, []):
                    t["표:총계"] += 1
                    if declared_unit(tbl_el) is None:
                        t["표:폐기(단위 미선언)"] += 1
                    elif not _table_has_data_rows(tbl_el):
                        t["표:폐기(데이터행 없음)"] += 1
                    else:
                        t["표:적재대상"] += 1

            # ── 추출기 출력
            try:
                emitted = list(extract_report_lines(
                    str(p), rcept_no=f.rcept_no, corp_code=f.corp_code,
                    report_fiscal_year=f.fiscal_year,
                    report_fiscal_period=f.fiscal_period, include_notes=True))
            except Exception:  # noqa: BLE001
                t["추출실패"] += 1
                continue

            src = source_numbers(root)
            key = lambda x: (x.statement, x.basis, str(x.section_path), x.table_seq,
                             x.label_raw, x.row_order, x.col_index)
            ex_map = {key(x): x.value_won for x in emitted if x.value_won is not None}

            for tbl, want_stmt in (("report_lines", False), ("note_lines", True)):
                db = session.execute(
                    text(str(DB_SQL).format(tbl=tbl)), {"r": f.rcept_no}).fetchall()
                db_map = {key(r): r.value_won for r in db}
                exp = {k: v for k, v in ex_map.items()
                       if (k[0] == "note") == want_stmt}

                # ② LOAD: 추출기 출력이 DB 에 있는가
                t[f"{tbl}:추출"] += len(exp)
                t[f"{tbl}:DB"] += len(db_map)
                lost = [k for k in exp if k not in db_map]
                t[f"{tbl}:적재누락"] += len(lost)
                diff = [k for k in exp if k in db_map and exp[k] != db_map[k]]
                t[f"{tbl}:값불일치"] += len(diff)
                if (lost or diff) and len(bad) < args.show:
                    k = (lost or diff)[0]
                    bad.append(f"LOAD {tbl} {f.rcept_no} {str(k)[:70]}")

                # ① REVERSE: DB 값이 원문에 실재하는가
                for k, v in db_map.items():
                    if v == 0:
                        continue
                    t[f"{tbl}:역검사"] += 1
                    av = abs(v)
                    if any((av % m == 0) and str(av // m) in src for m in _MULTS):
                        t[f"{tbl}:역일치"] += 1
                    else:
                        t[f"{tbl}:역실패"] += 1
                        if len(bad) < args.show:
                            bad.append(f"REV {tbl} {f.rcept_no} {str(k)[:60]} = {v:,}")

    el = time.time() - t0
    n = max(t["filing"], 1)
    print(f"\n=== 계층2 충실성 (filing {n}, {el:.0f}s, {el/n:.2f}s/filing) ===")
    for tbl in ("report_lines", "note_lines"):
        if not t[f"{tbl}:DB"]:
            continue
        rv, ro = t[f"{tbl}:역검사"], t[f"{tbl}:역일치"]
        print(f"  {tbl}")
        print(f"    ① 역방향  {ro:>9,}/{rv:<9,} ({ro/max(rv,1)*100:7.3f}%) · 실패 {t[f'{tbl}:역실패']:,}")
        print(f"    ② 적재    추출 {t[f'{tbl}:추출']:>9,} → DB {t[f'{tbl}:DB']:>9,} · "
              f"누락 {t[f'{tbl}:적재누락']:,} · 값불일치 {t[f'{tbl}:값불일치']:,}")
    tt = max(t["표:총계"], 1)
    print(f"\n  ③ 주석 표 {tt:,} — 적재대상 {t['표:적재대상']:,} ({t['표:적재대상']/tt*100:.1f}%) · "
          f"단위미선언 {t['표:폐기(단위 미선언)']:,} · 데이터행없음 {t['표:폐기(데이터행 없음)']:,}")
    for k in ("파일없음", "파싱실패", "추출실패"):
        if t[k]:
            print(f"  {k}: {t[k]}")
    if bad:
        print("\n--- 이상 사례 ---")
        for b in bad:
            print(f"  {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
