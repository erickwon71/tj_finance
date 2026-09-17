"""SCE 저조행수 후보 1차 자동 스크리닝 — DB report_lines 기반 회계항등식 검증.

BS/IS/CF 스캔과 같은 순서: (1) 임계값 이하 후보 추출 (scan_sce_2015plus 스크립트)
(2) 자동 검증으로 1차 스크리닝 (3) 실패/미확인 건만 원문 대조.

SCE 검증식 — 열=자본구성요소이므로 BS/CF와 다르다:
  [A] 행 내부: 총계열 == 구성요소열들의 합 (열 라벨 분류는 verify_sce.py 재사용)
  [B] 시계열: 기초자본 + Σ(중간 변동행) == 기말자본  (같은 열 안에서)

DB report_lines 에서 직접 읽는다(원문 재파싱 아님 — 이미 적재된 값의 내부정합만 본다).

사용:
    python scripts/scan_sce_identity_check_2026-09-16.py --threshold-consolidated 30 --threshold-separate 14
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# ★"기초" 텍스트가 없는 시작행 라벨 변형(2026-09-16, 원문대조로 확인) — 신설법인
#   첫 SCE는 "기초" 대신 "설립일"을 쓰고(러셀 20160330000145), 일부 회사는 당기 블록의
#   시작을 "당기초" 대신 전년도 종가를 재인용하는 "전기말"/"전분기말"/"전반기말"로 쓴다
#   (애니플러스 20191104000164 — "2018.12.31(전기말)"이 사실상 당기 블록의 기초잔액).
#   둘 다 데이터 자체는 정상이고 이 스크립트의 라벨 정규식만 못 알아봤던 것.
_OPEN = re.compile(r"기초|설립일|전기말|전분기말|전반기말")
_CLOSE = re.compile(r"기말")
_DATE_ROW = re.compile(r"^\d{4}[.\-]\d{1,2}[.\-]\d{1,2}$")
_TOTAL_COL = re.compile(r"자본\s*합계|자본총계|총\s*계")
_OWNERS_SUBTOTAL_COL = re.compile(r"지배기업.*합계|지배지분\s*합계|소유주.*합계")
_NCI_COL = re.compile(r"비지배")
_TOL = 0.005  # SCE는 반올림누적이 BS/CF보다 커서 0.5%로 완화

_UNIVERSE_FILTER = """
    c.is_active
    AND c.stock_code IS NOT NULL
    AND c.stock_code NOT LIKE '9%'
    AND c.coverage_class = 'periodic'
"""
_FILING_FILTER = """
    f.report_type IN ('annual','half','quarter')
    AND f.fiscal_year >= 2015
    AND f.is_final = TRUE
    AND f.report_nm NOT LIKE '%제출기한연장%'
"""


def _norm(s):
    return (s or "").replace(" ", "").replace("　", "")


def _classify_cols(col_labels: dict[int, str]):
    total = None
    subtotals = []
    for c, lbl in col_labels.items():
        n = _norm(lbl)
        if _NCI_COL.search(n):
            continue
        if _TOTAL_COL.search(n) and not _OWNERS_SUBTOTAL_COL.search(n):
            total = c if total is None else max(total, c)
        elif _OWNERS_SUBTOTAL_COL.search(n):
            subtotals.append(c)
    comps = [c for c in col_labels if c != total and c not in subtotals]
    return total, subtotals, comps


def _fetch_candidates(session, thr_cons: int, thr_sep: int):
    sql = f"""
        SELECT rl.rcept_no, rl.basis, count(*) AS n_rows,
               f.corp_code, c.corp_name, c.stock_code, f.fiscal_year, f.fiscal_period
        FROM report_lines rl
        JOIN filings f ON f.rcept_no = rl.rcept_no
        JOIN corporations c ON c.corp_code = f.corp_code
        WHERE rl.statement = 'SCE'
          AND {_UNIVERSE_FILTER}
          AND {_FILING_FILTER}
        GROUP BY rl.rcept_no, rl.basis, f.corp_code, c.corp_name, c.stock_code, f.fiscal_year, f.fiscal_period
        HAVING (rl.basis = 'consolidated' AND count(*) <= :thr_cons)
            OR (rl.basis = 'separate' AND count(*) <= :thr_sep)
        ORDER BY count(*)
    """
    return session.execute(text(sql), {"thr_cons": thr_cons, "thr_sep": thr_sep}).fetchall()


def _check(session, rcept_no: str, basis: str):
    sql = """
        SELECT table_seq, row_order, label_raw, col_index, col_label, value_won
        FROM report_lines
        WHERE rcept_no = :r AND basis = :b AND statement = 'SCE'
        ORDER BY table_seq, row_order, col_index
    """
    rows = session.execute(text(sql), {"r": rcept_no, "b": basis}).fetchall()
    if not rows:
        return None

    col_labels: dict[int, str] = {}
    for r in rows:
        if r.col_label and r.col_index not in col_labels:
            col_labels[r.col_index] = r.col_label

    by_row: dict[tuple, dict[int, int]] = defaultdict(dict)
    row_seq_order: list[tuple] = []
    for r in rows:
        key = (r.table_seq, r.row_order, r.label_raw)
        if key not in by_row:
            row_seq_order.append(key)
        if r.value_won is not None:
            by_row[key][r.col_index] = r.value_won

    total_c, sub_cs, comps = _classify_cols(col_labels)

    # [A] 행 내부: 총계 == 구성요소 합
    a_ok = a_bad = 0
    a_examples = []
    if total_c is not None and comps:
        for key, vals in by_row.items():
            if total_c not in vals:
                continue
            parts = [vals[c] for c in comps if c in vals]
            if len(parts) < 2:
                continue
            expect, got = sum(parts), vals[total_c]
            if expect == got or (got and abs(expect - got) <= abs(got) * _TOL):
                a_ok += 1
            else:
                a_bad += 1
                if len(a_examples) < 3:
                    a_examples.append((key[2], expect, got))

    # [B] 시계열: 기초 + Σ중간행 == 기말 (열별)
    # 라벨이 '기초/기말' 텍스트 대신 날짜(YYYY.MM.DD)로만 된 표가 있음 —
    # 그 경우 같은 table_seq 안에서 첫/마지막 날짜행을 기초/기말로 간주.
    # ★당기/전기 블록이 세로로 두 번 쌓이는 표가 있다(report_lines.py 의 _emit_sce_lines
    #   docstring 참고) — "첫 기초 ~ 마지막 기말"로 통짜 스팬을 잡으면 중간 블록 경계의
    #   기말/기초 잔액행 자체가 "변동행"으로 잘못 합산돼 대략 2배 어긋나는 거짓양성이 난다.
    #   그래서 **가장 가까운 기초→기말 쌍**(블록 단위)으로만 검증한다.
    open_positions = [i for i, key in enumerate(row_seq_order) if _OPEN.search(_norm(key[2]))]
    close_positions = [i for i, key in enumerate(row_seq_order) if _CLOSE.search(_norm(key[2]))]
    if not open_positions or not close_positions:
        date_idxs = [i for i, key in enumerate(row_seq_order) if _DATE_ROW.match((key[2] or "").strip())]
        if len(date_idxs) >= 2:
            open_positions, close_positions = date_idxs[:1], date_idxs[-1:]

    blocks: list[tuple[int, int]] = []
    for oi in open_positions:
        candidates = [ci for ci in close_positions if ci > oi]
        if candidates:
            blocks.append((oi, min(candidates)))

    b_ok = b_bad = 0
    b_examples = []
    for open_idx, close_idx in blocks:
        mid_keys = row_seq_order[open_idx + 1: close_idx]
        open_vals = by_row[row_seq_order[open_idx]]
        close_vals = by_row[row_seq_order[close_idx]]
        cols_to_check = comps + ([total_c] if total_c is not None else [])
        for c in cols_to_check:
            if c not in open_vals or c not in close_vals:
                continue
            delta_sum = 0
            n_mid = 0
            for mk in mid_keys:
                v = by_row[mk].get(c)
                if v is not None:
                    delta_sum += v
                    n_mid += 1
            if n_mid == 0:
                continue
            expect = open_vals[c] + delta_sum
            got = close_vals[c]
            if expect == got or (got and abs(expect - got) <= abs(got) * _TOL):
                b_ok += 1
            else:
                b_bad += 1
                if len(b_examples) < 3:
                    b_examples.append((col_labels.get(c, c), expect, got))

    return {
        "n_rows": len(rows), "n_cols": len(col_labels),
        "has_open": bool(open_positions), "has_close": bool(close_positions),
        "n_blocks": len(blocks),
        "a_ok": a_ok, "a_bad": a_bad, "a_examples": a_examples,
        "b_ok": b_ok, "b_bad": b_bad, "b_examples": b_examples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold-consolidated", type=int, required=True)
    ap.add_argument("--threshold-separate", type=int, required=True)
    ap.add_argument("--show-pass", action="store_true")
    args = ap.parse_args()

    with get_session() as session:
        candidates = _fetch_candidates(session, args.threshold_consolidated, args.threshold_separate)
        print(f"후보 {len(candidates)}건\n")

        clean = flagged = no_open_close = 0
        flagged_list = []
        for cand in candidates:
            res = _check(session, cand.rcept_no, cand.basis)
            if res is None:
                continue
            problem = res["a_bad"] > 0 or res["b_bad"] > 0
            missing_oc = not (res["has_open"] and res["has_close"])
            if problem:
                flagged += 1
                flagged_list.append((cand, res))
            elif missing_oc:
                no_open_close += 1
                flagged_list.append((cand, res))
            else:
                clean += 1
                if args.show_pass:
                    print(f"  OK  {cand.corp_name}({cand.stock_code}) {cand.fiscal_year} "
                          f"{cand.fiscal_period} {cand.basis} n={res['n_rows']}")

        print(f"\n=== 요약 ===")
        print(f"항등식 정상(기초/기말 보유+정합):        {clean}")
        print(f"기초/기말 행 자체가 없음(구조 다름):      {no_open_close}")
        print(f"항등식 불일치([A] 또는 [B] fail):         {flagged}")

        if flagged_list:
            print(f"\n=== 원문대조 필요 후보 {len(flagged_list)}건 ===")
            for cand, res in flagged_list:
                print(f"\n  {cand.corp_name}({cand.stock_code}) {cand.fiscal_year} {cand.fiscal_period} "
                      f"{cand.basis} rcept={cand.rcept_no} n_rows={res['n_rows']} n_cols={res['n_cols']} "
                      f"has_open={res['has_open']} has_close={res['has_close']}")
                if res["a_bad"]:
                    print(f"    [A] bad={res['a_bad']} ok={res['a_ok']}  examples={res['a_examples']}")
                if res["b_bad"]:
                    print(f"    [B] bad={res['b_bad']} ok={res['b_ok']}  examples={res['b_examples']}")
                print(f"    https://dart.fss.or.kr/dsaf001/main.do?rcpNo={cand.rcept_no}")


if __name__ == "__main__":
    main()
