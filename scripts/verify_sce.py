"""계층2 검증 (3) — 자본변동표(SCE) 전용.

SCE 는 BS/IS/CF 와 컬럼 규약이 달라(열=자본 구성요소) 기존 검증기가 커버하지 못한다.
값·구조가 맞는지 **독립 근거 두 축**으로 확인한다:

  [A] 행 내부 정합 — 총계 열 == 구성요소 열들의 합
      각 변동사유 행에서 '자본 합계' 열이 자본금/자본잉여금/기타자본/이익잉여금(연결이면
      +비지배지분) 의 합이어야 한다. **col_label 복원이 맞았는지**를 동시에 검증한다
      (열 라벨이 어긋나면 이 합이 깨진다).

  [B] BS 교차검증 — 최종 기말자본 총계 == 같은 보고서 BS 의 자본총계
      계층2 안에서 서로 다른 재무제표를 대조하는 것이라 가장 강한 증거다.

추가로 커버리지(기초/기말 행 존재·col_label 채움률)를 센다 — 기초/기말 행은
`_is_header_cell` 의 날짜 규칙에 걸려 통째로 유실됐던 이력이 있다(date_labels_ok 로 해소).

사용:
    python scripts/verify_sce.py --corp 00101220
    python scripts/verify_sce.py --sample 300
    python scripts/verify_sce.py --sample 300 --show 20
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

_OPEN = re.compile(r"기초")
_CLOSE = re.compile(r"기말")
# 열 라벨 분류. '지배기업…지분 합계' 는 **중간소계 열**이라 합산에서 빼야 이중계산이 없다.
_TOTAL_COL = re.compile(r"자본\s*합계|자본총계|총\s*계")
_OWNERS_SUBTOTAL_COL = re.compile(r"지배기업.*합계|지배지분\s*합계|소유주.*합계")
_NCI_COL = re.compile(r"비지배")
_TOL = 0.001            # 상대오차 0.1% — 단위 반올림 흡수


def _norm(s: str | None) -> str:
    return (s or "").replace(" ", "").replace("　", "")


def _classify_cols(col_labels: dict[int, str]) -> tuple[int | None, int | None, list[int]]:
    """반환 (총계열, 지배지분소계열, 구성요소열들)."""
    total = subtotal = None
    for c, lbl in col_labels.items():
        n = _norm(lbl)
        if _TOTAL_COL.search(n) and not _OWNERS_SUBTOTAL_COL.search(n):
            total = c if total is None else max(total, c)   # 가장 오른쪽을 총계로
        elif _OWNERS_SUBTOTAL_COL.search(n):
            subtotal = c
    comps = [c for c in col_labels if c not in (total, subtotal)]
    return total, subtotal, comps


def _check_one(lines, basis: str):
    """한 (보고서, basis) 의 SCE 를 검사 → (결과 dict)."""
    sce = [l for l in lines if l.statement == "SCE" and l.basis == basis]
    if not sce:
        return None

    col_labels = {}
    for l in sce:
        if l.col_label and l.col_index not in col_labels:
            col_labels[l.col_index] = l.col_label
    n_cols_seen = len({l.col_index for l in sce})

    by_row: dict[tuple, dict[int, int]] = defaultdict(dict)
    for l in sce:
        by_row[(l.table_seq, l.row_order, l.label_raw)][l.col_index] = l.value_won

    total_c, sub_c, comps = _classify_cols(col_labels)

    # [A] 행 내부 정합
    a_ok = a_bad = 0
    a_examples = []
    if total_c is not None and comps:
        for (tseq, ro, lbl), vals in by_row.items():
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
                    a_examples.append((lbl, expect, got))

    # 커버리지 — 기초/기말 행
    labels = [lbl for (_, _, lbl) in by_row]
    has_open = any(_OPEN.search(_norm(l)) for l in labels)
    has_close = any(_CLOSE.search(_norm(l)) for l in labels)

    # [B] BS 교차검증 — 마지막 기말자본 총계 vs BS 자본총계(당기)
    b_status, b_detail = "SKIP", None
    close_rows = [(k, v) for k, v in by_row.items() if _CLOSE.search(_norm(k[2]))]
    if close_rows and total_c is not None:
        (_, _, lbl), vals = max(close_rows, key=lambda kv: (kv[0][0], kv[0][1]))
        sce_close = vals.get(total_c)
        bs_total = None
        for l in lines:
            if (l.statement == "BS" and l.basis == basis and l.col_index == 0
                    and _norm(l.label_raw) in ("자본총계", "자본총계(결손금)", "총자본")):
                bs_total = l.value_won
                break
        if sce_close is not None and bs_total is not None:
            if sce_close == bs_total or abs(sce_close - bs_total) <= abs(bs_total) * _TOL:
                b_status = "PASS"
            else:
                b_status = "FAIL"
            b_detail = (lbl, sce_close, bs_total)

    return {
        "n_rows": len(sce), "n_cols": n_cols_seen,
        "n_labeled": len(col_labels),
        "has_open": has_open, "has_close": has_close,
        "a_ok": a_ok, "a_bad": a_bad, "a_examples": a_examples,
        "b_status": b_status, "b_detail": b_detail,
    }


def _fetch(session, args):
    where = ["dt.status='completed'", "dt.file_type='xml'", "dt.file_path IS NOT NULL",
             "f.fiscal_period='FY'", "f.report_nm NOT LIKE '%정정%'", "f.fiscal_year >= 2015"]
    params = {}
    if args.corp:
        where.append("f.corp_code=:c"); params["c"] = args.corp
    sql = f"""SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
              FROM download_tasks dt JOIN filings f USING(rcept_no)
              WHERE {' AND '.join(where)}"""
    rows = session.execute(text(sql), params).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    with get_session() as session:
        targets = _fetch(session, args)
    if not targets:
        print("대상 없음"); return

    n_rep = n_sec = 0
    cov = Counter()
    a_ok = a_bad = 0
    b = Counter()
    fails = []

    for t in targets:
        if not Path(t.file_path).exists():
            continue
        try:
            lines = extract_report_lines(
                t.file_path, rcept_no=t.rcept_no, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period)
        except Exception as e:
            fails.append((t, f"ERR {type(e).__name__}: {e}"))
            continue
        n_rep += 1
        for basis in ("consolidated", "separate"):
            res = _check_one(lines, basis)
            if res is None:
                continue
            n_sec += 1
            cov["기초행 보유"] += res["has_open"]
            cov["기말행 보유"] += res["has_close"]
            cov["col_label 전열 채움"] += (res["n_labeled"] >= res["n_cols"])
            a_ok += res["a_ok"]; a_bad += res["a_bad"]
            b[res["b_status"]] += 1
            if res["b_status"] == "FAIL" or res["a_bad"]:
                fails.append((t, f"{basis} A불일치 {res['a_bad']} B={res['b_status']} "
                                 f"{res['b_detail']} ex={res['a_examples'][:2]}"))

    print(f"\n=== SCE 검증: 보고서 {n_rep}건 · SCE 섹션 {n_sec}개 ===\n")
    print("[커버리지]")
    for k in ("기초행 보유", "기말행 보유", "col_label 전열 채움"):
        print(f"    {k:22s} {cov[k]:5,} / {n_sec:5,}  ({100*cov[k]/max(n_sec,1):5.1f}%)")
    tot_a = a_ok + a_bad
    print(f"\n[A] 행 내부 정합(총계열 = 구성요소 합)  {a_ok:,} / {tot_a:,} "
          f"({100*a_ok/max(tot_a,1):.1f}%)")
    print(f"[B] BS 교차검증(기말자본 = BS 자본총계)  PASS {b['PASS']:,} · "
          f"FAIL {b['FAIL']:,} · SKIP {b['SKIP']:,}")

    if fails:
        print(f"\n[불일치 상위 {min(len(fails), args.show)} / 총 {len(fails)}]")
        for t, msg in fails[: args.show]:
            print(f"  ✗ {t.corp_code} r{t.rcept_no} {t.fiscal_year}: {msg}")


if __name__ == "__main__":
    main()
