"""R21 Phase 3(a) probe — Gate B cogs fail_a 14건의 정확한 키를 확정하고, 각 건이 정말
"report_won(cogs XBRL 태그) = is.cogs(std) + is.sga(std)" 개념 불일치인지 실측 검증한다.

목적(docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md Phase 3 §1):
  1. Gate B v3 재검증(19개사 scope, cogs_phase2_19corps_2026-08-15.txt)에서 cogs 필드가
     fail_a로 잡힌 (corp, fy, period, basis) 키를 전부 뽑는다.
  2. 각 키마다 FieldAudit(db_amount_won=is.cogs std값, report_value_won=Gate B가 찾은
     가장 가까운 보고서 후보값)을 gateb_audit.audit_corp 와 동일 경로(audit_std_row)로 직접
     재현해 얻는다(DB 쓰기 없음, --no-commit 과 동등).
  3. 같은 (corp,fy,period,basis)의 is.sga(std) 값을 std_financials_v3 에서 조회해
     report_won ≈ db_cogs + db_sga 항등식이 성립하는지 확인(허용오차: XBRL ADECIMAL 표시단위
     ±1, face_audit.py::won_match 와 동일 규약은 아니고 단순 절대값 비교로 충분 — 이미
     정수 won 단위라 반올림 차는 미미할 것으로 예상, 실측으로 확인).
  4. 4개사(00108940·00117212·00143527·00163673) 밖에서 cogs fail_a가 나오면 즉시 보고
     (R21 §Gate B 해석의 "전부 예견됨" 전제가 깨진 것 — 가짜양성 없이 정확히 보고, R9 원칙).

읽기전용(DB 미변경). 원문 XML 대조는 이 스크립트가 항등식을 확정한 뒤, 표본 1~2건만
별도로 손으로 확인한다(과대해석 방지 — R9).

Usage: python scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.db import get_session
import scripts.gateb_audit as ga

_KNOWN_CORPS = {"00108940", "00117212", "00143527", "00163673"}


def main():
    args = argparse.Namespace(
        source="v3", corp=None,
        corp_file=str(Path(__file__).resolve().parent / "cogs_phase2_19corps_2026-08-15.txt"),
        corps=None, sample=None, seed=42, fy_min=2010, fy_max=2100,
        recheck=True, no_commit=True, line_audit=False,
    )
    ga.ensure_table()

    found: list[dict] = []
    unexpected_corps: set[str] = set()

    with get_session() as session:
        corps = ga.select_corps(session, args)
        print(f"대상 corp {len(corps)}사(19개사 scope)")

        for corp in corps:
            rows = session.execute(ga.text("""
                SELECT * FROM std_financials_v3
                WHERE corp_code=:c AND fiscal_year >= :fymin AND fiscal_year <= :fymax
                ORDER BY fiscal_year DESC
            """), {"c": corp, "fymin": args.fy_min, "fymax": args.fy_max}).fetchall()
            if not rows:
                continue

            rcepts = set()
            for r in rows:
                for rc in ga._row_rcepts(dict(r._mapping), args.source).values():
                    if rc:
                        rcepts.add(rc)
            fpmap = ga.file_path_map(session, rcepts)
            face_cache: dict[str, list] = {}
            track_of: dict[str, str | None] = {}

            def face_of(rc, _cache=face_cache, _fpmap=fpmap, _track=track_of):
                if not rc:
                    return []
                if rc not in _cache:
                    fp = _fpmap.get(rc)
                    try:
                        lines, track = ga.read_report_face_tracked(fp) if fp else ([], None)
                    except (FileNotFoundError, OSError):
                        lines, track = [], None
                    _cache[rc] = lines
                    _track[rc] = track
                return _cache[rc]

            for r in rows:
                d = dict(r._mapping)
                rc = ga._row_rcepts(d, args.source)
                basis = d["statement_type"]
                ra = ga.audit_std_row(
                    d, basis=basis,
                    bs_face=face_of(rc.get("BS")),
                    is_face=face_of(rc.get("IS")),
                    cf_face=face_of(rc.get("CF")),
                    is_comparative=False,
                )
                if "cogs" not in ra.fail_fields:
                    continue
                # gate_status_for_row 와 동일 로직으로 fail_a/fail_b 판정 — Track B(fail_b)는
                # R21에서 이미 "감사기 자체 한계, 비차단 REVIEW"로 별도 분류된 것이라 Phase 3(a)의
                # pending 예외처리 대상이 아니다(fail_a만).
                fail_tracks = {f: ga._field_track(f, rc, track_of) for f in ra.fail_fields}
                gate = ga.gate_status_for_row(ra, fail_tracks)
                if gate != "fail_a":
                    continue
                for f in ra.fields:
                    if f.field != "cogs" or f.reason != "VALUE_DIFF":
                        continue
                    if corp not in _KNOWN_CORPS:
                        unexpected_corps.add(corp)
                    db_sga = d.get("sga")
                    total = (f.db_amount_won or 0) + (db_sga or 0) if db_sga is not None else None
                    match = total is not None and f.report_value_won is not None \
                        and abs(total - f.report_value_won) <= 1
                    found.append({
                        "corp": corp, "fy": d["fiscal_year"], "fp": d["fiscal_period"],
                        "basis": basis, "db_cogs": f.db_amount_won,
                        "report_won": f.report_value_won, "db_sga": db_sga,
                        "sum": total, "identity_holds": match,
                    })

    print(f"\ncogs VALUE_DIFF 건수 = {len(found)}")
    for row in found:
        flag = "OK" if row["identity_holds"] else "**MISMATCH**"
        print(f"  {row['corp']} {row['fy']} {row['fp']} {row['basis']}: "
              f"cogs={row['db_cogs']} + sga={row['db_sga']} = {row['sum']} "
              f"vs report_won={row['report_won']}  [{flag}]")

    n_hold = sum(1 for r in found if r["identity_holds"])
    print(f"\n항등식(cogs+sga==report_won, ±1) 성립 = {n_hold}/{len(found)}")

    if unexpected_corps:
        print(f"\n★ 4개사 밖 예상외 corp = {sorted(unexpected_corps)} (R9: 재조사 필요)")
    else:
        print("\n4개사(00108940/00117212/00143527/00163673) 밖 예상외 corp 없음(전제 확인).")

    by_corp = Counter(r["corp"] for r in found)
    print(f"\ncorp별 건수: {dict(by_corp)}")


if __name__ == "__main__":
    main()
