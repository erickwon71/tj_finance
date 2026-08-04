"""단위 상속(앞선 표의 단위를 물려쓰기)의 **안전성과 이득**을 실측한다 (2026-08-04).

사용자 제안 — "개별 표에 단위가 없으면 앞선 표의 단위를 쓰면 되지 않나.
같은 페이지든, 보고서에서 한 번이라도 확인된 단위든."
사용자 단서 — "단, 이 가정은 단위 찾는 것이 100% 완벽해야 가능하다."

그 단서 외에 **또 하나의 위험**이 있다: 탐지가 완벽해도 **원문이 인접 표끼리 단위를
다르게 쓰면** 상속은 틀린다. 그래서 두 가지를 나눠 잰다.

── 측정 방법 (핵심) ────────────────────────────────────────────────────────
'단위가 없는 표' 는 정답을 모르니 직접 검증할 수 없다. 그래서 **단위를 실제로 선언한
표**만 골라 그 선언을 가린 뒤, 상속 규칙이 뭐라고 답하는지를 **실제 선언값과 대조**한다
(leave-one-out). 이러면 상속 오류율을 정답 기반으로 직접 얻는다.

3가지 상속 범위를 비교한다:
  scope=face_section : 같은 본문 섹션의 **직전 face 표**(BS/IS/CF/SCE) 단위
  scope=face_doc     : 문서 전체의 직전 face 표 단위(연결→별도 넘나듦)
  scope=any_doc      : 문서 순서상 직전 **아무 표**의 단위(주석표 포함) = 가장 넓은 해석

이득도 함께 잰다 — 지금 보류(unit=None)인 face 표 중 몇 개가 각 범위에서 채워지는가.

사용:
    python scripts/measure_unit_inheritance_safety.py --sample 400
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
from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, classify_dart_section, table_direct_rows,
)
from fin2.extract.text import (
    _detect_body_statement_tables, _detect_fin_type, _table_has_data_rows, declared_unit,
)

SQL_LOADED = """
SELECT f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no, d.file_path
  FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
 WHERE f.fiscal_year >= 2015
   AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
 ORDER BY md5(f.rcept_no)
 LIMIT :n
"""


def walk(root):
    """문서 순서로 (섹션종류, TABLE) 를 낸다 — 데이터표만."""
    current = None
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            t = el.find("TITLE")
            if t is not None:
                current = classify_dart_section("".join(t.itertext()))
        elif tag == "TABLE" and _table_has_data_rows(el):
            yield current, el


def analyze(root, stats):
    fin_type = _detect_fin_type(root)
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    face = {}
    for code, v in groups.items():
        for tbl, unit, _k in v:
            face[id(tbl)] = code

    prev_any = None                      # 직전 아무 표의 단위
    prev_face_doc = None                 # 직전 face 표의 단위
    prev_face_sec: dict[str, int] = {}   # 섹션별 직전 face 표의 단위

    for sec, tbl in walk(root):
        u = declared_unit(tbl)
        code = face.get(id(tbl))

        if code is not None:
            sec_key = sec or "?"
            cands = {
                "face_section": prev_face_sec.get(sec_key),
                "face_doc": prev_face_doc,
                "any_doc": prev_any,
            }
            if u is None:
                # 이득 측정 — 지금 보류 중인 표
                stats["held"] += 1
                for k, p in cands.items():
                    if p is not None:
                        stats[f"fill_{k}"] += 1
            else:
                # 위험 측정 — 정답(u)을 알고 있으니 상속 규칙을 채점한다
                for k, p in cands.items():
                    if p is None:
                        continue
                    stats[f"eval_{k}"] += 1
                    if p == u:
                        stats[f"ok_{k}"] += 1
                    else:
                        stats[f"bad_{k}"] += 1
                        stats.setdefault(f"badratio_{k}", Counter())[
                            f"{p}→{u}"] += 1
                        if k == "face_section" and len(stats["bad_examples"]) < 12:
                            stats["bad_examples"].append(
                                (stats["cur"], code, p, u, len(table_direct_rows(tbl))))
            if u is not None:
                prev_face_doc = u
                prev_face_sec[sec or "?"] = u
        if u is not None:
            prev_any = u


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(SQL_LOADED), {"n": args.sample}).fetchall()

    stats: dict = Counter()
    stats["bad_examples"] = []
    docs = 0
    for corp_name, fy, fp, rcept, fpth in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        docs += 1
        stats["cur"] = f"{corp_name} {fy}{fp} {rcept}"
        analyze(root, stats)

    print(f"=== 적재분 표본 {docs}건 ===\n")
    print("【위험】 단위를 선언한 face 표에서, 그 선언을 가리고 상속시켰을 때의 정확도")
    print("        (정답 = 그 표가 실제로 선언한 단위)\n")
    print(f"  {'상속 범위':14s} {'평가':>7s} {'일치':>7s} {'불일치':>7s} {'오류율':>8s}")
    for k in ("face_section", "face_doc", "any_doc"):
        ev, ok, bad = stats[f"eval_{k}"], stats[f"ok_{k}"], stats[f"bad_{k}"]
        rate = bad / ev * 100 if ev else 0.0
        print(f"  {k:14s} {ev:7d} {ok:7d} {bad:7d} {rate:7.2f}%")

    for k in ("face_section", "face_doc", "any_doc"):
        c = stats.get(f"badratio_{k}")
        if c:
            print(f"\n  [{k}] 틀린 상속의 배수 조합(상위 8) — '상속값→실제값'")
            for kk, vv in c.most_common(8):
                p, u = kk.split("→")
                factor = int(u) / int(p) if int(p) else 0
                print(f"     {vv:5d}  {kk:22s} (실제가 {factor:g}배)")

    print("\n【이득】 지금 단위 미확정으로 보류 중인 face 표")
    print(f"  보류 표 총계 : {stats['held']}")
    for k in ("face_section", "face_doc", "any_doc"):
        f = stats[f"fill_{k}"]
        print(f"    {k:14s} 로 채울 수 있는 표: {f} "
              f"({f / max(stats['held'],1) * 100:.1f}%)")

    if stats["bad_examples"]:
        print("\n  face_section 오류 사례:")
        for cur, code, p, u, nrows in stats["bad_examples"]:
            print(f"     {cur} [{code}] 상속={p} 실제={u} rows={nrows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
