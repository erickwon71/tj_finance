"""L3-1b cell-key normalization probe (READ-ONLY, measure-first).

Question: should the delta-patch cell key normalize label_raw (strip note refs /
roman prefixes / full-width space via normalize_account_name) NOW, to keep a
기재정정 that changes only a label from misaligning (ONLY_ORIG + ONLY_AMEND →
should be CHANGED)?

Two risks to weigh:
  BENEFIT — how many ONLY_ORIG/ONLY_AMEND pairs are pure label drift (same
            statement/basis/col/section_path, labels differ but normalize equal)?
            These become clean CHANGED (patchable) under a normalized key.
  COST    — collisions: within ONE filing, do two DIFFERENT genuine cells with
            DIFFERENT values collapse to the same normalized key? That would
            wrongly merge them.

Reports both over amendment pairs. Writes nothing.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from parser.common.amount_normalizer import normalize_account_name
from scripts.layer3_amendment_delta_probe import find_amendment_pairs


def cells(session, rcept):
    """{raw_key: value}, {norm_key: [(value, raw_label)]} for one filing (col_index=0)."""
    rows = session.execute(text("""
        SELECT statement, basis, col_index, section_path, label_raw, value_won
        FROM report_lines WHERE rcept_no=:r AND col_index=0 AND value_won IS NOT NULL
    """), {"r": rcept}).fetchall()
    raw = {}
    norm = defaultdict(list)
    for statement, basis, col, path, label, val in rows:
        raw[(statement, basis, col, path, label)] = val
        nkey = (statement, basis, col, path, normalize_account_name(label))
        norm[nkey].append((val, label))
    return raw, norm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--pairs", type=int, default=60)
    ap.add_argument("--year-min", type=int, default=2015)
    ap.add_argument("--examples", type=int, default=8)
    args = ap.parse_args()

    drift_pairs = 0            # ONLY_ORIG cell that finds a normalized match in amendment
    genuine_only = 0          # ONLY_* with no normalized counterpart
    collisions = 0            # within a filing: same norm key, >1 distinct value
    collision_ex = []
    drift_ex = []

    with get_session() as s:
        pairs = find_amendment_pairs(s, args.pairs, args.year_min)
        print(f"amendment pairs: {len(pairs)}\n")
        for corp, fy, period, orig, amend in pairs:
            oraw, onorm = cells(s, orig)
            araw, anorm = cells(s, amend)

            # collision check: within EACH filing, norm key mapping >1 distinct value
            for f_norm, tag in ((onorm, "orig"), (anorm, "amend")):
                for nkey, lst in f_norm.items():
                    vals = {v for v, _ in lst}
                    if len(vals) > 1:
                        collisions += 1
                        if len(collision_ex) < args.examples:
                            collision_ex.append((corp, fy, tag, nkey, lst))

            # drift: raw ONLY_ORIG / ONLY_AMEND that align under normalized key
            okeys, akeys = set(oraw), set(araw)
            only_o = okeys - akeys
            only_a = akeys - oraw.keys()
            # normalized keys present on each side
            o_normkeys = set(onorm)
            a_normkeys = set(anorm)
            for k in only_o:
                stmt, basis, col, path, label = k
                nk = (stmt, basis, col, path, normalize_account_name(label))
                if nk in a_normkeys and nk not in {(kk[0],kk[1],kk[2],kk[3],normalize_account_name(kk[4])) for kk in (okeys & akeys)}:
                    # this orig-only raw label aligns to something in amendment via normalization
                    if nk in a_normkeys:
                        drift_pairs += 1
                        if len(drift_ex) < args.examples:
                            drift_ex.append((corp, fy, label, [l for _, l in anorm[nk]]))
                    else:
                        genuine_only += 1
                else:
                    genuine_only += 1

    print("=== ONLY_ORIG 정렬 개선 여지 ===")
    print(f"  label-drift (정규화하면 정정본과 정렬됨) : {drift_pairs}")
    print(f"  genuine only_orig (진짜 추가/삭제)      : {genuine_only}")
    print(f"\n=== 정규화 키 충돌 위험(같은 filing 내 같은 norm키·다른 값) ===")
    print(f"  collisions: {collisions}")

    if drift_ex:
        print("\n--- label-drift 예시 (원본 라벨 → 정정본 동일정규화 라벨) ---")
        for corp, fy, olabel, alabels in drift_ex:
            print(f"  {corp} {fy}: {olabel!r} → {alabels}")
    if collision_ex:
        print("\n--- 충돌 예시 (같은 norm키에 값 여러 개) ---")
        for corp, fy, tag, nkey, lst in collision_ex:
            print(f"  {corp} {fy} [{tag}] norm={nkey[4]!r} path={nkey[3]}")
            for v, l in lst:
                print(f"      {v:,}  ({l!r})")


if __name__ == "__main__":
    main()
