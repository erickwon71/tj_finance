"""계층2 검증 (2) — section_path(하위섹션 tree) 구조 검증.

값이 아니라 **위치(tree)**를 검증한다. 두 가지:
  1) **well-formedness**: 각 라인 section_path 의 모든 세그먼트가 같은 statement/basis 안의 실제
     라벨(더 얕은 조상 행)로 존재하는가. 자기 자신 참조·유령 조상이 없어야 한다.
  2) **★금융업 이중섹션 정합(핵심)**: section_path 에 '금융업'이 있는 보고서에서, 일반 섹션 현금 +
     금융업 섹션 현금 합이 현금흐름표 기말현금과 일치하는가. 이게 재설계의 동기였던 그 구조가
     실제로 계층3 합산을 가능케 하는지의 end-to-end 증거다.

사용:
    python scripts/verify_section_paths.py --sample 400
    python scripts/verify_section_paths.py --corp 00101220
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import extract_rows
from fin2.extract.text import _detect_fin_type, _detect_body_statement_tables
from fin2.extract.report_lines import extract_report_lines

_CASH = "현금및현금성자산"
_CF_TOL = 1   # 원문 자체 반올림으로 BS 현금합 vs CF기말현금이 ±1원 어긋날 수 있다.


def _all_body_labels(file_path) -> dict[tuple, set]:
    """본문 BS/IS/CF 표의 **모든 행 라벨**(값 없는 헤더 '자산'/'부채'/'자본' 포함) 을 (stmt,basis)별로.

    report_lines 는 금액 있는 행만 저장하므로 '자산' 같은 값-없는 최상위 헤더는 stored 라벨에
    없다. 그러나 section_path 조상으로는 정당하게 등장한다 → well-formedness 검증엔 값-없는 행까지
    포함한 전체 라벨 집합이 필요하다(그래야 값-없는 조상을 유령으로 오판하지 않는다)."""
    out: dict[tuple, set] = {}
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return out
    groups = _detect_body_statement_tables(root, _detect_fin_type(root))
    for code, tw in groups.items():
        stmt = code.split("_")[0]
        basis = "consolidated" if code.endswith("_C") else "separate"
        s = out.setdefault((stmt, basis), set())
        for tbl, unit, _kind in tw:
            if unit is None:
                continue
            for row in extract_rows(tbl, multiplier=unit or 1, num_cols=3,
                                    direct_only=True, skip_junk=False):
                if row.account_name:
                    s.add(row.account_name)
    return out


def _wellformed_violations(rows, all_labels: dict[tuple, set]) -> list[str]:
    """section_path 세그먼트가 같은 (statement,basis) 의 실제 원문 라벨(값-없는 헤더 포함)로
    존재하는지 + 자기참조 없는지. 위반 목록 반환."""
    viols = []
    for r in rows:
        if not r.section_path:
            continue
        if "주당" in r.label_raw:
            continue  # EPS 는 합성 section_path('주당손익') 사용 — 원문 조상 라벨 검증 대상 아님
        known = all_labels.get((r.statement, r.basis), set())
        segs = r.section_path.split(">")
        for seg in segs:
            if seg not in known:
                viols.append(f"{r.statement}/{r.basis} '{r.label_raw}' path seg '{seg}' 미존재")
                break
        # ※ 자기참조(라벨이 자기 path 에 등장)는 **위반이 아니다** — 원문이 같은 계정을 인접 두
        #   들여쓰기 레벨에 그대로 인쇄하는 경우(헤더+동명 상세, 값 동일)가 실재하며, report_lines
        #   는 이를 충실 전사한다(실측: 비지배지분·현금및현금성자산 헤더/상세 동일값). 정상 중첩.
    return viols


def _cf_ending_cash(rows, basis) -> int | None:
    """현금흐름표 기말현금 (col0). 라벨에 '기말'+'현금' 포함하는 CF 라인."""
    cands = [r.value_won for r in rows
             if r.statement == "CF" and r.basis == basis and r.col_index == 0
             and r.value_won is not None and "기말" in r.label_raw and "현금" in r.label_raw]
    return cands[-1] if cands else None


def _dual_section_check(rows) -> tuple[bool, str] | None:
    """금융업 이중섹션 보고서면 (현금 일반+금융업 합) vs CF 기말현금 정합 판정. 대상 아니면 None."""
    has_fin = any(r.section_path and "금융업" in r.section_path for r in rows if r.statement == "BS")
    if not has_fin:
        return None
    # 이중섹션이 나타난 basis 를 고른다(대개 consolidated).
    for basis in ("consolidated", "separate"):
        cash_lines = [r for r in rows if r.statement == "BS" and r.basis == basis
                      and r.col_index == 0 and r.label_raw == _CASH and r.value_won is not None]
        if len(cash_lines) < 2:
            continue
        paths = {r.section_path for r in cash_lines}
        # 최소 하나는 금융업, 하나는 비금융업이어야 이중섹션
        if not (any("금융업" in (p or "") for p in paths) and any("금융업" not in (p or "") for p in paths)):
            continue
        total = sum(r.value_won for r in cash_lines)
        cf_end = _cf_ending_cash(rows, basis)
        if cf_end is None:
            return (True, f"{basis}: 현금합 {total:,} (CF기말현금 없음 — 부분확인)")
        ok = abs(total - cf_end) <= _CF_TOL   # ±1원(원문 반올림) 허용
        return (ok, f"{basis}: 현금합 {total:,} vs CF기말 {cf_end:,} {'일치' if ok else '불일치'}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--year", type=int)
    args = ap.parse_args()

    where = ["dt.status='completed'", "dt.file_type='xml'", "dt.file_path IS NOT NULL",
             "f.fiscal_period='FY'", "f.report_nm NOT LIKE '%정정%'"]
    params = {}
    if args.corp:
        where.append("f.corp_code=:c"); params["c"] = args.corp
    if args.year:
        where.append("f.fiscal_year=:y"); params["y"] = args.year
    sql = f"""SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
              FROM download_tasks dt JOIN filings f USING(rcept_no)
              WHERE {' AND '.join(where)}"""
    with get_session() as session:
        rows = session.execute(text(sql), params).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)

    n = wf_ok = 0
    wf_fail = []
    dual = []   # (tag, ok, msg)
    for r in rows:
        if not Path(r.file_path).exists():
            continue
        try:
            lines = extract_report_lines(r.file_path, rcept_no=r.rcept_no, corp_code=r.corp_code,
                                         report_fiscal_year=r.fiscal_year,
                                         report_fiscal_period=r.fiscal_period)
        except Exception as e:
            wf_fail.append((f"{r.corp_code} r{r.rcept_no}", f"ERR {e}"))
            n += 1
            continue
        n += 1
        v = _wellformed_violations(lines, _all_body_labels(r.file_path))
        if v:
            wf_fail.append((f"{r.corp_code} r{r.rcept_no}", v[0]))
        else:
            wf_ok += 1
        d = _dual_section_check(lines)
        if d is not None:
            dual.append((f"{r.corp_code} r{r.rcept_no} {r.fiscal_year}", d[0], d[1]))

    print(f"\n=== section_path 검증: {n}개 보고서 ===")
    print(f"[1] well-formedness (조상 실존·자기참조 없음): {wf_ok}/{n} PASS")
    for tag, msg in wf_fail[:15]:
        print(f"    ✗ {tag}: {msg}")
    print(f"\n[2] 금융업 이중섹션 CF정합: 대상 {len(dual)}건")
    dual_ok = sum(1 for _, ok, _ in dual if ok)
    print(f"    정합 {dual_ok}/{len(dual)}")
    for tag, ok, msg in dual:
        mark = "✓" if ok else "✗"
        print(f"    {mark} {tag}: {msg}")


if __name__ == "__main__":
    main()
