"""Phase 0 investigation (read-only) for
docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md.

No DB writes, no source changes. Reads report_lines (layer2, already extracted) for the
structural check, and re-parses the raw XML face table directly via
`fin2.audit.face_audit.read_report_face_xbrl()` for the XBRL cross-check — this mirrors
exactly what Gate B (`face_audit.py`) itself reads for report_won, which is NOT `fact_v2`
(that table is a separate XBRL-instance-parser pipeline with its own coverage gaps; verified
empirically that all 3 known corps have ZERO fact_v2 rows for the filings in question).
Direct XML read here is the verification exception to [[architecture-report-read-layer2-only]]
(same precedent as scripts/probe_revenue_bugb_note_ref_2026-08-14.py).

v2 (2026-08-15): tightened candidate matching from substring LIKE '%영업비용%' (which pulled in
~1108 corps incl. unrelated industries — insurers' '기타영업비용'/'투자영업비용'/'보험영업비용'
sub-lines, none of which are the §1 COGS+SGA-total pattern) to:
  - exact `normalize_account_name(label) == '영업비용'` for the PARENT (총계) line
  - children must include at least one COGS-like label (매출원가/상품매출원가/제품매출원가 등)
    AND one SGA-like label (판매비와관리비/판매비및관리비) — this is what actually
    distinguishes the target pattern from unrelated '영업비용' totals (insurance cos etc.)

Sub-tasks (plan §6 Phase 0):
  1. Narrow the candidate pool with the structural+label check above; for confirmed rows,
     re-parse the raw XML face table to check whether the total is literally tagged
     ifrs-full_CostOfSales.
  2. Check whether dart_TotalSellingGeneralAdministrativeExpenses (concept_map.py's is.sga
     XBRL concept) is ALSO tagged in the same filing.
  3. Enumerate "상품 및 제품매출원가" unmapped-label corps, check AccountMapper result.
  4. (범위 밖 확정만 — 세니젠류 기재정정 체인은 이 스크립트에서 다루지 않는다.)

Usage: python scripts/probe_sga_cogs_holdco_phase0_2026-08-15.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from parser.common.account_mapper import AccountMapper
from parser.common.amount_normalizer import normalize_account_name
from fin2.audit.face_audit import read_report_face_xbrl

COGS_MARKERS = ("매출원가", "원가")   # child label markers (substring)
SGA_MARKERS = ("판매비와관리비", "판매비및관리비", "판매비와 관리비", "판매비 및 관리비")
UNMAPPED_LABEL = "상품 및 제품매출원가"


# ── Step 1: precise candidate rows (parent '영업비용' P-lines) ─────────
def find_parent_rows(session) -> list:
    """All IS report_lines rows where normalize(label)=='영업비용' and node_role='P'
    (candidates for the §1 총계 pattern). Broad LIKE first (cheap index-friendly prefilter),
    exact normalize check in Python."""
    rows = session.execute(text("""
        SELECT id, corp_code, rcept_no, basis, table_seq, row_order, depth, label_raw, value_won,
               report_fiscal_year, report_fiscal_period
        FROM report_lines
        WHERE statement = 'IS' AND col_index = 0 AND node_role = 'P'
          AND label_raw LIKE '%영업비용%'
    """)).fetchall()
    return [r for r in rows if normalize_account_name(r[7]) == "영업비용"]


def direct_children(session, corp, rcept, basis, tseq, prow, pdepth):
    siblings = session.execute(text("""
        SELECT row_order, depth, label_raw, value_won
        FROM report_lines
        WHERE corp_code = :c AND rcept_no = :r AND basis = :b AND statement = 'IS'
          AND table_seq = :t AND col_index = 0 AND row_order > :ro
        ORDER BY row_order
    """), {"c": corp, "r": rcept, "b": basis, "t": tseq, "ro": prow}).fetchall()
    children = []
    for ro, depth, label, val in siblings:
        if depth is None or pdepth is None or depth <= pdepth:
            break
        if depth == pdepth + 1:
            children.append((label, val))
    return children


def get_file_path(session, rcept: str) -> str | None:
    row = session.execute(text("""
        SELECT file_path FROM download_tasks WHERE rcept_no = :r AND file_path IS NOT NULL
    """), {"r": rcept}).fetchone()
    return row[0] if row else None


def main():
    init_db()
    mapper = AccountMapper()

    with get_session() as s:
        parents = find_parent_rows(s)
        print(f"=== Step 1: precise '영업비용' P-line rows (전체 이력, exact-normalize match) === {len(parents)} rows, "
              f"{len({p[1] for p in parents})} unique corps")

        target_rows = []       # children include both a COGS-like and an SGA-like label
        identity_fail = []
        other_pattern = []     # structurally decomposable but not the COGS+SGA shape
        no_children = 0

        for (pid, corp, rcept, basis, tseq, prow, pdepth, plabel, pval, fy, fp) in parents:
            if pval is None:
                continue
            children = direct_children(s, corp, rcept, basis, tseq, prow, pdepth)
            if not children:
                no_children += 1
                continue
            labels = [c[0] for c in children]
            has_cogs = any(any(m in lbl for m in COGS_MARKERS) for lbl in labels)
            has_sga = any(any(m in lbl for m in SGA_MARKERS) for lbl in labels)
            child_sum = sum(v for _, v in children if v is not None)
            n_missing = sum(1 for _, v in children if v is None)
            identity_ok = (n_missing == 0 and child_sum == pval)

            row = {
                "corp": corp, "rcept": rcept, "basis": basis, "fy": fy, "fp": fp,
                "label": plabel, "value_won": pval, "children": children,
                "identity_ok": identity_ok,
            }
            if has_cogs and has_sga:
                if identity_ok:
                    target_rows.append(row)
                else:
                    identity_fail.append(row)
            else:
                other_pattern.append(row)

        print(f"\n=== Step 1 classification ===")
        print(f"target_rows(COGS+SGA 자식, 항등식 성립) = {len(target_rows)} rows, "
              f"{len({r['corp'] for r in target_rows})} unique corps")
        print(f"identity_fail(COGS+SGA 자식 있으나 합 불일치) = {len(identity_fail)} rows, "
              f"{len({r['corp'] for r in identity_fail})} unique corps")
        print(f"other_pattern(§1과 무관한 다른 '영업비용' — 보험/투자 등) = {len(other_pattern)} rows, "
              f"{len({r['corp'] for r in other_pattern})} unique corps")
        print(f"no_children = {no_children}")

        target_corps = sorted({r["corp"] for r in target_rows})
        print(f"\ntarget corps: {target_corps}")

        print("\n=== target_rows sample (child structure) ===")
        for r in target_rows[:20]:
            print(f"  {r['corp']} {r['rcept']} {r['basis']} {r['fy']}{r['fp']} "
                  f"value={r['value_won']} children={r['children']}")

        if identity_fail:
            print("\n=== identity_fail rows (investigate individually) ===")
            for r in identity_fail[:15]:
                print(f"  {r['corp']} {r['rcept']} {r['basis']} value={r['value_won']} children={r['children']}")

        # ── Step 2: XBRL cross-check via raw XML (Gate B's actual code path) ──
        print(f"\n=== Step 2: raw XML face XBRL cross-check ({len(target_rows)} target rows) ===")
        acode_confirmed = []
        sga_concept_present = []
        no_track_a = []
        file_missing = []
        checked_files: dict[str, list] = {}

        for r in target_rows:
            rcept = r["rcept"]
            if rcept not in checked_files:
                fp = get_file_path(s, rcept)
                if fp is None or not Path(fp).exists():
                    checked_files[rcept] = None
                else:
                    try:
                        checked_files[rcept] = read_report_face_xbrl(fp)
                    except Exception as e:
                        checked_files[rcept] = None
                        print(f"  WARN parse failed {rcept}: {e}")
            face_lines = checked_files[rcept]
            if face_lines is None:
                file_missing.append(r)
                continue
            if not face_lines:
                no_track_a.append(r)
                continue
            cogs_hits = [fl for fl in face_lines if fl.acode == "ifrs-full_CostOfSales"
                         and fl.basis == r["basis"] and fl.amount_won == r["value_won"]]
            sga_hits = [fl for fl in face_lines if fl.acode == "dart_TotalSellingGeneralAdministrativeExpenses"
                        and fl.basis == r["basis"]]
            if cogs_hits:
                acode_confirmed.append((r, cogs_hits))
            if sga_hits:
                sga_concept_present.append((r, sga_hits))
            if not cogs_hits and not sga_hits and not any(
                    fl.basis == r["basis"] for fl in face_lines):
                no_track_a.append(r)

        print(f"acode_confirmed(총계가 실제 ifrs-full_CostOfSales로 태깅됨) = {len(acode_confirmed)}")
        for r, hits in acode_confirmed[:15]:
            print(f"  {r['corp']} {r['rcept']} {r['basis']} value={r['value_won']} acode_hits={[(h.acode, h.amount_won) for h in hits]}")

        print(f"\nsga_concept_present(같은 필링에 dart_TotalSellingGeneralAdministrativeExpenses 태깅됨) = {len(sga_concept_present)}")
        for r, hits in sga_concept_present[:15]:
            print(f"  {r['corp']} {r['rcept']} {r['basis']} sga_hits={[(h.acode, h.amount_won) for h in hits]}")

        print(f"\nfile_missing(원문 파일 없음/파싱실패) = {len(file_missing)}")
        print(f"no_track_a(XBRL 없음 — Track A 비교 불가, '침묵 오염' 후보) = {len(no_track_a)} rows, "
              f"{len({r['corp'] for r in no_track_a})} unique corps")
        print(f"  fy distribution of no_track_a: {Counter(r['fy'] for r in no_track_a)}")

        fy_dist_confirmed = Counter(r["fy"] for r, _ in acode_confirmed)
        print(f"\nfy distribution of acode_confirmed: {dict(fy_dist_confirmed)}")

        # ── Step 3: 상품 및 제품매출원가 ──
        print(f"\n=== Step 3: '{UNMAPPED_LABEL}' 라벨 전수 ===")
        unmapped_rows = s.execute(text("""
            SELECT DISTINCT corp_code, label_raw
            FROM report_lines WHERE statement = 'IS' AND label_raw LIKE :l
        """), {"l": f"%{UNMAPPED_LABEL}%"}).fetchall()
        unmapped_corps = sorted({c for c, _ in unmapped_rows})
        print(f"corps={len(unmapped_corps)}: {unmapped_corps}")
        overlap_with_target = sorted(set(unmapped_corps) & set(target_corps))
        print(f"overlap with target_corps (Phase 1/2 대상과 겹침): {overlap_with_target}")
        for lbl, n in Counter(lbl for _, lbl in unmapped_rows).most_common():
            mres = mapper.map(lbl, fs_section="is")
            print(f"  {lbl!r} x{n} → mapper: {mres.account_code} (stage={mres.stage}, conf={mres.confidence})")

    print("\n=== DONE (read-only, no writes) ===")


if __name__ == "__main__":
    main()
