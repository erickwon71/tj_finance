"""Phase 2 design input — run the REAL, unmodified production extractor
(`fin2.extract.report_lines.extract_report_lines`) against a fresh pre-2015
stratified sample and measure how much already works with zero code changes.

Rationale: `docs/plans/pre2015_layer2_backfill_plan_2026-08-10.md` Phase 1
probes found that pre-2015 top-level SECTION-2 titles ("3. 재무제표" /
"4. 연결재무제표") normalize to the exact same keys
(`SEC_SEP_FS`="재무제표" / `SEC_CONSOL_FS`="연결재무제표") that
`assign_tables_to_dart_sections` already recognizes for 2015+. If that holds
across years/report_types, `_detect_body_statement_tables` may already route
most pre-2015 tables into the same per-table classifier
(`classify_statement_in_body_section` + `title_text_owned`/`title_text_for_classify`)
used for 2015+ — meaning Phase 2 may be an EXTENSION of that classifier's
regex coverage (headless SPAN/plain-text titles), not a new module.

This script calls the actual entry point with zero modification and reports,
per fiscal year, the hit rate for BS/IS/CF rows. Read-only — does not touch
report_lines/note_lines or any production table.

Output: docs/qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

YEARS = list(range(1999, 2015))
SAMPLES_PER_YEAR = 10


def sample_filings(session) -> list[dict]:
    rows = []
    for year in YEARS:
        q = text("""
            SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year,
                   f.fiscal_period, f.report_type, dt.file_path
            FROM filings f
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            JOIN corporations c ON c.corp_code = f.corp_code
            WHERE f.fiscal_year = :year
              AND dt.status = 'completed'
              AND dt.file_type = 'xml'
              AND c.is_active = true
            ORDER BY md5(f.rcept_no || 'pipeline-reuse-2026-08-10')
            LIMIT :n
        """)
        res = session.execute(q, {"year": year, "n": SAMPLES_PER_YEAR}).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def probe_file(sample: dict) -> dict:
    result = {**sample, "error": None, "counts": defaultdict(int), "total_rows": 0}
    path = Path(sample["file_path"])
    if not path.exists():
        result["error"] = "file_missing"
        return result
    try:
        lines = extract_report_lines(
            path,
            rcept_no=sample["rcept_no"],
            corp_code=sample["corp_code"],
            report_fiscal_year=sample["fiscal_year"],
            report_fiscal_period=sample["fiscal_period"],
            include_notes=False,
        )
    except Exception as e:  # noqa: BLE001 — probe must not die on one bad file
        result["error"] = f"{type(e).__name__}: {e}"
        return result
    result["total_rows"] = len(lines)
    for ln in lines:
        result["counts"][ln.statement] += 1
    return result


def main() -> None:
    with get_session() as session:
        samples = sample_filings(session)
    print(f"sampled {len(samples)} filings")

    results = []
    for i, s in enumerate(samples):
        results.append(probe_file(s))
        if (i + 1) % 20 == 0:
            print(f"  probed {i + 1}/{len(samples)}")

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md")
    lines = []
    lines.append("# Phase 2 설계 입력 — 기존 파이프라인 무변경 재사용률 실측 (2026-08-10)")
    lines.append("")
    lines.append(
        "> `fin2.extract.report_lines.extract_report_lines`(2015+ 운영 진입점, **코드 무변경**)를 "
        "pre-2015 신규 층화표본(1999~2014, 연도당 10건)에 그대로 돌려 BS/IS/CF 검출 성공률을 "
        "실측한다. 목적 = Phase 2가 '신규 모듈'인지 '기존 분류기 확장'인지 결정."
    )
    lines.append("")

    ok = [r for r in results if not r["error"]]
    errors = [r for r in results if r["error"]]
    lines.append(f"**표본 {len(results)}건 · 정상실행 {len(ok)}건 · 예외/파일누락 {len(errors)}건**")
    lines.append("")

    lines.append("## 연도별 BS/IS/CF 검출 성공률")
    lines.append("")
    lines.append("| FY | 표본 | BS 있음 | IS 있음 | CF 있음 | 전체 0행 | avg total_rows |")
    lines.append("|---|---|---|---|---|---|---|")
    by_year = defaultdict(list)
    for r in results:
        by_year[r["fiscal_year"]].append(r)
    for year in YEARS:
        rs = by_year.get(year, [])
        rs_ok = [r for r in rs if not r["error"]]
        n = len(rs)
        bs = sum(1 for r in rs_ok if r["counts"].get("BS", 0) > 0)
        is_ = sum(1 for r in rs_ok if r["counts"].get("IS", 0) > 0)
        cf = sum(1 for r in rs_ok if r["counts"].get("CF", 0) > 0)
        zero = sum(1 for r in rs_ok if r["total_rows"] == 0)
        avg_rows = (sum(r["total_rows"] for r in rs_ok) / len(rs_ok)) if rs_ok else 0
        lines.append(f"| {year} | {n} | {bs} | {is_} | {cf} | {zero} | {avg_rows:.0f} |")
    lines.append("")

    lines.append("## 개별 실패/0행 사례 (최대 40건)")
    lines.append("")
    lines.append("| rcept_no | corp_name | FY | report_type | 사유 |")
    lines.append("|---|---|---|---|---|")
    shown = 0
    for r in results:
        if shown >= 40:
            break
        if r["error"]:
            lines.append(f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | {r['report_type']} | error: {r['error']} |")
            shown += 1
        elif r["total_rows"] == 0:
            lines.append(f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | {r['report_type']} | 0행 |")
            shown += 1
    lines.append("")

    lines.append("## 결론 (사람이 채움)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다._")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
