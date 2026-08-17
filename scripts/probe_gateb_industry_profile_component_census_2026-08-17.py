"""
Gate B ① 업종 파생 revenue — Phase 0 성분 face 존재율 census (읽기전용, 2026-08-17).

design: docs/plans/gateb_industry_derived_revenue_design_2026-08-17.md §4 Phase 0.

securities(operating_income+sga)는 미래에셋증권 표본으로 이미 실측됐지만(설계 §2-B),
bank/insurance/credit_finance 의 성분(interest_revenue/fee_revenue/other_op_revenue/
insurance_revenue/investment_revenue)이 face 에 독립 재추출 가능한지는 **미확인**이었다.
이 스크립트는 46개사 industry_lines 보유 std_v3 행 전수에 대해, 계층3이 기록한 성분값이
그 행의 IS rcept 원문(Track A+B face, `read_report_face_tracked`)에 **값으로 실재**하는지
측정한다(canonical 매핑 여부와 무관 — 미매핑 XBRL fact 도 값 매칭 대상).

읽기전용: DB/코드 무변경. 결과만 stdout + docs/qa/industry_profile_component_census_2026-08-17.md.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import read_report_face_tracked

# industry_lines 의 성분 키(profile/revenue_basis 는 값 대조 대상 아님).
_SKIP_KEYS = {"profile", "revenue_basis"}


def file_path_map(session, rcepts):
    if not rcepts:
        return {}
    rows = session.execute(text("""
        SELECT rcept_no, file_path, file_type FROM download_tasks
        WHERE rcept_no = ANY(:rs) AND file_type IN ('xml','pdf') AND status='completed'
          AND file_path IS NOT NULL
    """), {"rs": list(rcepts)}).fetchall()
    fmap: dict[str, str] = {}
    for r in rows:
        if r.file_type == "xml" or r.rcept_no not in fmap:
            fmap[r.rcept_no] = r.file_path
    return fmap


def main():
    with get_session() as session:
        rows = session.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period, statement_type AS basis,
                   industry_lines, source_rcepts
            FROM std_financials_v3
            WHERE industry_lines->>'profile' IS NOT NULL
            ORDER BY industry_lines->>'profile', corp_code, fiscal_year, fiscal_period
        """)).fetchall()
        print(f"census population: {len(rows)} rows "
              f"({len(set(r.corp_code for r in rows))} corps)")

        rcepts = {r.source_rcepts.get("IS") for r in rows if r.source_rcepts and r.source_rcepts.get("IS")}
        fpmap = file_path_map(session, rcepts)

    face_cache: dict[str, list] = {}

    def face_of(rc):
        if not rc:
            return []
        if rc not in face_cache:
            fp = fpmap.get(rc)
            try:
                lines, _track = read_report_face_tracked(fp) if fp else ([], None)
            except (FileNotFoundError, OSError):
                lines = []
            face_cache[rc] = lines
        return face_cache[rc]

    # profile -> component_key -> Counter({matched, unmatched, no_rcept, no_file})
    stats: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    # profile -> gross_fallback row count (revenue_basis present — 별도 카운트만, 검증 대상 아님)
    gross_fallback: Counter = Counter()
    # 원문대조 표본용: 매칭 실패 사례 몇 건씩 보존
    unmatched_samples: dict[tuple[str, str], list] = defaultdict(list)

    n = 0
    for r in rows:
        n += 1
        if n % 200 == 0:
            print(f"  ...{n}/{len(rows)}", file=sys.stderr)
        profile = r.industry_lines.get("profile")
        if r.industry_lines.get("revenue_basis"):
            gross_fallback[profile] += 1
            continue  # gross_fallback: 일반경로로 이미 통과, 성분검증 대상 아님(설계 §3-D)
        rc = (r.source_rcepts or {}).get("IS")
        components = {k: v for k, v in r.industry_lines.items() if k not in _SKIP_KEYS}
        if not components:
            continue
        if not rc:
            for k in components:
                stats[profile][k]["no_rcept"] += 1
            continue
        if rc not in fpmap:
            for k in components:
                stats[profile][k]["no_file"] += 1
            continue
        lines = face_of(rc)
        if not lines:
            # face 재추출 자체가 0행(구형 포맷 등 리더 실패) — 성분 부재가 아니라 정보공백.
            # 값 대조는 무의미하므로 read_failed 로 별도 집계(unmatched 에 섞지 않음).
            for k in components:
                stats[profile][k]["read_failed"] += 1
            continue
        won_vals = {ln.amount_won for ln in lines
                    if ln.amount_won is not None and ln.statement in ("IS", None)
                    and ln.basis in (r.basis, None)}
        for k, v in components.items():
            if v is None:
                continue
            if v in won_vals or -v in won_vals:
                stats[profile][k]["matched"] += 1
            else:
                stats[profile][k]["unmatched"] += 1
                key = (profile, k)
                if len(unmatched_samples[key]) < 5:
                    unmatched_samples[key].append(
                        (r.corp_code, r.fiscal_year, r.fiscal_period, r.basis, v))

    # ── 출력 ──
    lines_out = []
    lines_out.append("# 업종 프로파일 파생 revenue — Phase 0 성분 face 존재율 census (2026-08-17)\n")
    lines_out.append("읽기전용 census. design: `gateb_industry_derived_revenue_design_2026-08-17.md` §4 Phase 0.\n")
    lines_out.append(f"모집단: {len(rows)}행 / {len(set(r.corp_code for r in rows))}개사\n")
    for profile in sorted(stats):
        lines_out.append(f"\n## {profile}\n")
        if gross_fallback[profile]:
            lines_out.append(f"- gross_fallback(검증대상 아님, 일반경로 통과): {gross_fallback[profile]}행\n")
        lines_out.append("| component | matched | unmatched | read_failed | no_rcept | no_file | 매칭률(matched/검증가능) |")
        lines_out.append("|---|---|---|---|---|---|---|")
        for k in sorted(stats[profile]):
            c = stats[profile][k]
            verifiable = c["matched"] + c["unmatched"]
            rate = c["matched"] / verifiable * 100 if verifiable else 0.0
            lines_out.append(f"| {k} | {c['matched']} | {c['unmatched']} | {c['read_failed']} | "
                              f"{c['no_rcept']} | {c['no_file']} | {rate:.1f}% |")
    lines_out.append("\n## 미매칭 표본 (component 별 최대 5건)\n")
    for (profile, k), samples in unmatched_samples.items():
        lines_out.append(f"\n### {profile}.{k}\n")
        lines_out.append("| corp_code | fy | fp | basis | value_won |")
        lines_out.append("|---|---|---|---|---|")
        for corp, fy, fp, basis, v in samples:
            lines_out.append(f"| {corp} | {fy} | {fp} | {basis} | {v:,} |")

    out_path = Path(__file__).resolve().parent.parent / "docs" / "qa" / \
        "industry_profile_component_census_2026-08-17.md"
    out_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    print("\n".join(lines_out))


if __name__ == "__main__":
    main()
