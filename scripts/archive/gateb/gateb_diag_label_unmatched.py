"""
LABEL_UNMATCHED 진단 — pending 행을 재감사해 어떤 std 필드가 미매칭이고,
그 값(won)을 보유한 face 라인의 라벨이 무엇인지 식별한다(=추가할 account_maps alias 후보).

usage:
  python scripts/gateb_diag_label_unmatched.py [--limit N] [--reason LABEL_UNMATCHED]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import (
    read_report_face_tracked, read_report_face_text, audit_std_row,
    STD_FIELD_CANONICAL, _statement_face,
)

_RCEPT_COL = {"BS": "bs_rcept", "IS": "is_rcept", "CF": "cf_rcept"}
_STMT_OF = lambda c: ("BS" if c.startswith("bs.") else "IS" if c.startswith("is.") else "CF")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", default="LABEL_UNMATCHED")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--fy-min", type=int, default=2015)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period, statement_type
            FROM face_audit
            WHERE gate_status='pending'
              AND pending_detail ? :reason
              AND fiscal_year >= :fymin
            ORDER BY fiscal_year DESC
            LIMIT :lim
        """), {"reason": args.reason, "fymin": args.fy_min, "lim": args.limit}).fetchall()
        print(f"진단 대상 {len(rows)}행 (reason={args.reason}, fy>={args.fy_min})")

        # canonical_field -> Counter(label -> n)  (값 일치하는 face 라벨)
        match_label: dict[str, Counter] = {}
        # canonical_field -> n  (값 보유 face 라인 자체가 없음 = 진짜 미커버)
        no_value = Counter()
        field_total = Counter()
        examples: dict[str, list] = {}
        # 근본원인: trackA 선택됐는데 trackB(read_report_face_text)면 매칭됐을 케이스
        rootcause = Counter()   # field -> Counter? use dict
        rc_by_field: dict[str, Counter] = {}

        # corp 단위 face 캐시
        for (corp, fy, fp, stmt_type) in rows:
            d = s.execute(text("""
                SELECT * FROM std_financials_v2
                WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
                  AND statement_type=:st AND version=1 AND NOT COALESCE(is_stub,false)
            """), {"c": corp, "y": fy, "p": fp, "st": stmt_type}).fetchone()
            if d is None:
                continue
            dm = dict(d._mapping)
            rcepts = {k: dm.get(k) for k in ("bs_rcept", "is_rcept", "cf_rcept")}
            fp_map = {}
            for rc in set(v for v in rcepts.values() if v):
                fr = s.execute(text("""
                    SELECT file_path FROM download_tasks
                    WHERE rcept_no=:rc AND file_type='xml' AND status='completed'
                      AND file_path IS NOT NULL LIMIT 1
                """), {"rc": rc}).fetchone()
                fp_map[rc] = fr[0] if fr else None
            face_cache = {}
            track_cache = {}
            textface_cache = {}
            def face_of(rc):
                if not rc:
                    return []
                if rc not in face_cache:
                    fpath = fp_map.get(rc)
                    try:
                        ls, tr = read_report_face_tracked(fpath) if fpath else ([], None)
                    except (FileNotFoundError, OSError):
                        ls, tr = [], None
                    face_cache[rc] = ls
                    track_cache[rc] = tr
                return face_cache[rc]
            def textface_of(rc):
                if not rc:
                    return []
                if rc not in textface_cache:
                    fpath = fp_map.get(rc)
                    try:
                        textface_cache[rc] = read_report_face_text(fpath) if fpath else []
                    except (FileNotFoundError, OSError):
                        textface_cache[rc] = []
                return textface_cache[rc]

            bs_face = face_of(rcepts["bs_rcept"])
            is_face = face_of(rcepts["is_rcept"])
            cf_face = face_of(rcepts["cf_rcept"])
            basis = stmt_type
            interim = fp in ("H1", "Q3")
            ra = audit_std_row(dm, basis=basis, bs_face=bs_face, is_face=is_face,
                               cf_face=cf_face, is_comparative=False)
            for fa in ra.fields:
                if fa.reason != "LABEL_UNMATCHED":
                    continue
                field = fa.field
                canon = fa.canonical
                field_total[field] += 1
                val = fa.db_amount_won
                # 이 statement face 에서 값(won)이 일치하는 라인의 라벨 찾기
                face = _statement_face(field, bs_face, is_face, cf_face)
                hit_labels = []
                for ln in face:
                    if ln.basis is not None and ln.basis != basis:
                        continue
                    if interim and (canon.startswith("is.") or canon.startswith("cf.")) \
                            and not ln.is_cumulative:
                        continue
                    aw = ln.amount_won
                    if aw == val or aw == -val:
                        hit_labels.append((ln.label, ln.canonical))
                if hit_labels:
                    mc = match_label.setdefault(field, Counter())
                    for lbl, lc in hit_labels:
                        mc[(lbl, lc)] += 1
                    examples.setdefault(field, [])
                    if len(examples[field]) < 5:
                        examples[field].append((corp, fy, fp, basis, val, hit_labels[:2]))
                else:
                    no_value[field] += 1

                # ── 근본원인 분류 ──
                rcc = rc_by_field.setdefault(field, Counter())
                rc_col = _RCEPT_COL[canon[:2].upper().replace("IS","IS").replace("CF","CF").replace("BS","BS")] \
                    if False else _RCEPT_COL.get(("BS" if canon.startswith("bs.") else "IS" if canon.startswith("is.") else "CF"))
                rc = rcepts.get(rc_col)
                tr = track_cache.get(rc)
                # Track B 텍스트 reader 가 이 값을 그 canonical 로 보유하는가?
                tb_match = False
                for ln in textface_of(rc):
                    if ln.canonical != canon:
                        continue
                    if ln.basis is not None and ln.basis != basis:
                        continue
                    if interim and (canon.startswith("is.") or canon.startswith("cf.")) and not ln.is_cumulative:
                        continue
                    if ln.amount_won == val or ln.amount_won == -val:
                        tb_match = True
                        break
                if tr == "A" and tb_match:
                    rcc["A_used_but_B_matches"] += 1
                elif tr == "A":
                    rcc["A_used_B_nomatch"] += 1
                elif tr == "B" and hit_labels:
                    rcc["B_used_label_alias"] += 1
                elif tr == "B":
                    rcc["B_used_nomatch"] += 1
                else:
                    rcc["no_track"] += 1

    print("\n=== 필드별 LABEL_UNMATCHED 합계 ===")
    for f, n in field_total.most_common():
        nv = no_value[f]
        matched = n - nv
        print(f"  {f:22} total {n:5}  값보유라벨발견 {matched:5}  진짜미발견 {nv:5}")

    print("\n=== 근본원인 분류 (field별) ===")
    for f in field_total:
        rcc = rc_by_field.get(f, Counter())
        print(f"  [{f}] " + "  ".join(f"{k}={v}" for k, v in rcc.most_common()))

    print("\n=== 값 일치 face 라벨 (alias 후보, 상위) ===")
    for f in field_total:
        mc = match_label.get(f)
        if not mc:
            continue
        print(f"\n[{f}] -> {STD_FIELD_CANONICAL[f]}")
        for (lbl, lc), n in mc.most_common(8):
            print(f"   {n:4}x  label={lbl!r:50} (reader_canon={lc})")
        for ex in examples.get(f, [])[:3]:
            print(f"     ex: {ex[0]} {ex[1]} {ex[2]} {ex[3]} val={ex[4]}")


if __name__ == "__main__":
    main()
