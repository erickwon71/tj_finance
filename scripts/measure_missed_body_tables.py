"""적재분에서 **본문 표를 얼마나 놓치고 있었는지** 계측한다 (2026-08-04).

배경 — 세화피앤씨 20171114002715 에서 `(단위 : 원)` 을 정상 획득한 **재무상태표가
분류 단계에서 통째로 유실**되는 것이 확인됐다. 원인은 `_is_metadata_only()` 가
표제를 '건너뛸 메타줄' 로 오판하는 것:

  · `_STMT_TITLE` 정규식이 **자간 공백을 허용하지 않음** → '재 무 상 태 표' 미매칭
  · `_STMT_TITLE` 에 **자본변동표 패턴이 없음**       → '자본변동표' 미매칭
  ⟹ 이름 매칭에 실패하면 기간마커만 보고 메타줄로 판정 → **뒷단 분류기가 표제를 보지도 못함**
     (정작 `classify_statement_in_body_section` 은 공백 제거·SCE 인식으로 BS/SCE 를 맞힌다)

이 스크립트는 두 가지를 잰다:
  ① **유실 표** — 문서순서로 관장 표제를 따라가는 '관대한' 선택과 실제 감지기 선택의 차이
  ② **구간 내 단위 일관성** — 한 본문 섹션 안에서 표들이 서로 다른 단위를 선언하는가
     (사용자 제안 "같은 페이지 상단 단위를 그 구간 표에 적용" 의 안전성 판단 근거)

②가 중요한 이유: 과거 사고가 정확히 이 지점에서 났다 — 엘브이엠씨 2019 는 USD 기준 BS 가
4형제 앞 '연결현금흐름표 단위:백만원' 을 주워 **자산총계 586조**가 됐다(`declared_unit` docstring).
그래서 '구간 내 단위가 항상 같은가' 를 원문으로 확인해야 상속 확대를 논할 수 있다.

사용:
    python scripts/measure_missed_body_tables.py --sample 400
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
    SEC_CONSOL_FS, SEC_SEP_FS, assign_tables_to_dart_sections,
    iter_section_elements, table_direct_rows,
)
from fin2.extract.statement_titles import (
    classify_statement_in_body_section, _STMT_TITLE,
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

_SPACED_NAME = re.compile(r"재\s*무\s*상\s*태\s*표|대\s*차\s*대\s*조\s*표|"
                          r"포\s*괄\s*손\s*익\s*계\s*산\s*서|손\s*익\s*계\s*산\s*서|"
                          r"현\s*금\s*흐\s*름\s*표")


def _why_missed(title: str) -> str:
    """표제가 있는데 놓친 이유를 원문 문자열만 보고 분류한다."""
    t = re.sub(r"\s+", "", title)
    if "자본변동표" in t:
        return "자본변동표(_STMT_TITLE 에 패턴 없음)"
    if _SPACED_NAME.search(title) and not any(p.search(title) for p, _ in _STMT_TITLE):
        return "자간 공백(‘재 무 상 태 표’ 류)"
    return "기타"


def analyze(root) -> tuple[list, list]:
    """(유실표 목록, 섹션별 단위집합 목록)."""
    fin_type = _detect_fin_type(root)
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    selected = {id(tbl) for v in groups.values() for (tbl, _u, _k) in v}

    missed: list[tuple] = []
    unit_sets: list[tuple] = []

    for sec_norm in (SEC_CONSOL_FS, SEC_SEP_FS):
        if sec_norm == SEC_CONSOL_FS and fin_type == "B":
            continue
        elements = iter_section_elements(root, sec_norm)
        if not elements:
            continue
        last_title = ""
        units_here: list[int] = []
        for tag, el in elements:
            txt = " ".join("".join(el.itertext()).split())
            if tag == "TABLE" and _table_has_data_rows(el):
                stmt = classify_statement_in_body_section(last_title, include_sce=True)
                u = declared_unit(el)
                if u is not None:
                    units_here.append(u)
                if stmt is not None and id(el) not in selected:
                    missed.append((sec_norm, stmt, len(table_direct_rows(el)), u,
                                   _why_missed(last_title), last_title[:70]))
                continue
            if txt:
                last_title = txt          # 관장 표제 후보(제목표 또는 문단)
        if units_here:
            unit_sets.append((sec_norm, tuple(sorted(set(units_here))), tuple(units_here)))
    return missed, unit_sets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(SQL_LOADED), {"n": args.sample}).fetchall()

    docs = docs_with_miss = 0
    miss_stmt: Counter = Counter()
    miss_why: Counter = Counter()
    miss_rows = 0
    unit_uniform = unit_mixed = 0
    mixed_examples: list = []
    examples: list = []

    for corp_name, fy, fp, rcept, fpth in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        docs += 1
        missed, unit_sets = analyze(root)
        if missed:
            docs_with_miss += 1
            if len(examples) < 12:
                examples.append((corp_name, fy, fp, rcept, missed[:3]))
        for _sec, stmt, nrows, u, why, title in missed:
            miss_stmt[stmt] += 1
            miss_why[why] += 1
            miss_rows += nrows
        for sec, uniq, seq in unit_sets:
            if len(uniq) <= 1:
                unit_uniform += 1
            else:
                unit_mixed += 1
                if len(mixed_examples) < 10:
                    mixed_examples.append((corp_name, fy, fp, rcept, sec, uniq))

    print(f"=== 적재분 표본 {docs}건 ===\n")
    print("① 유실 표(관장 표제는 재무제표인데 감지기가 안 고른 데이터표)")
    print(f"   유실 있는 문서 : {docs_with_miss} / {docs} "
          f"({docs_with_miss / max(docs,1) * 100:.1f}%)")
    print(f"   유실 표 총계   : {sum(miss_stmt.values())}  (직접 데이터행 {miss_rows:,}행)")
    print("   재무제표별:")
    for k, v in miss_stmt.most_common():
        print(f"     {k:4s} {v}")
    print("   원인별:")
    for k, v in miss_why.most_common():
        print(f"     {v:5d}  {k}")

    print("\n   사례:")
    for corp_name, fy, fp, rcept, ms in examples:
        print(f"     {corp_name} {fy}{fp} {rcept}")
        for _sec, stmt, nrows, u, why, title in ms:
            print(f"        {stmt} rows={nrows} unit={u} [{why}] {title!r}")

    tot_sec = unit_uniform + unit_mixed
    print(f"\n② 본문 섹션 내 단위 일관성 (섹션 {tot_sec}개)")
    print(f"   단위 1종만 선언   : {unit_uniform} ({unit_uniform / max(tot_sec,1) * 100:.1f}%)")
    print(f"   ★2종 이상 선언    : {unit_mixed} ({unit_mixed / max(tot_sec,1) * 100:.1f}%)")
    for e in mixed_examples:
        print(f"      {e[0]} {e[1]}{e[2]} {e[3]} [{e[4]}] 단위={e[5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
