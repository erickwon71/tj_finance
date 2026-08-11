"""Phase 3 (구현) 검증 — 실제 프로덕션 함수(`extract_report_lines`) canary 실측.

todo 3-2: Phase 1(188+165+48건) + Phase2 설계문서 신규표본(96건) 표본을 canary 로 재사용,
production 코드 경로(`fin2.extract.report_lines.extract_report_lines` — 실제 데일리
파이프라인 진입점)로 **DB 미기록** read-only 재실행한다. 잔여항목④(설계문서 §3)에 따라
1999~2003 구간은 연도당 20건으로 두텁게 표본을 넓힌다.

읽기 전용 — report_lines/note_lines 테이블에 아무것도 쓰지 않는다(extract_report_lines를
직접 호출만 하고 반환된 리스트를 집계할 뿐, INSERT 는 없음).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

YEARS = list(range(1999, 2015))  # 1999~2014 — 신규 경로(≤2010) + 무변경 구간(2011~2014) 둘 다 확인
SAMPLES_PER_YEAR = {y: (20 if y <= 2003 else 8) for y in YEARS}


def sample_filings(session) -> list[dict]:
    rows = []
    for year in YEARS:
        n = SAMPLES_PER_YEAR[year]
        q = text("""
            SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year,
                   f.report_type, f.fiscal_period, dt.file_path
            FROM filings f
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            JOIN corporations c ON c.corp_code = f.corp_code
            WHERE f.fiscal_year = :year
              AND dt.status = 'completed'
              AND dt.file_type = 'xml'
              AND c.is_active = true
            ORDER BY md5(f.rcept_no || 'phase3-canary-2026-08-10')
            LIMIT :n
        """)
        res = session.execute(q, {"year": year, "n": n}).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def probe_file(sample: dict) -> dict:
    result = {**sample, "error": None, "counts": defaultdict(int)}
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
    except Exception as e:  # noqa: BLE001 — canary run, capture and report, don't crash the sweep
        result["error"] = f"exception:{type(e).__name__}:{e}"
        return result
    for ln in lines:
        result["counts"][ln.statement] += 1
    return result


def main() -> None:
    with get_session() as session:
        samples = sample_filings(session)
    print(f"sampled {len(samples)} filings")
    results = [probe_file(s) for s in samples]
    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pre2015_phase3_canary_verify_2026-08-10.md")
    lines = []
    lines.append("# Phase 3 구현 검증 — 프로덕션 함수 canary 실측 (2026-08-10)")
    lines.append("")
    lines.append(
        "> `extract_report_lines()`(계층2 실제 진입점, `fin2/extract/report_lines.py`)를 "
        "**읽기 전용**으로 직접 호출(DB 미기록)한 결과. 새 pre-2015 라우팅(`report_fiscal_year"
        " <= 2010`)이 적용된 상태 — todo 3-2."
    )
    lines.append("")
    ok = [r for r in results if not r["error"]]
    errors = [r for r in results if r["error"]]
    lines.append(f"**표본 {len(results)}건(1999~2014) · 정상 {len(ok)}건 · 오류 {len(errors)}건**")
    lines.append("")
    lines.append("## 연도별 BS/IS/CF/APPR/SCE 검출 성공률 (문서 단위, 연결+별도 중 하나라도 hit)")
    lines.append("")
    lines.append("| FY | 표본 | BS | IS | CF | APPR | SCE | 전부0 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    by_year = defaultdict(list)
    for r in results:
        by_year[r["fiscal_year"]].append(r)
    for year in YEARS:
        rs = [r for r in by_year.get(year, []) if not r["error"]]
        n = len(rs)
        def hit(stmt_prefix):
            return sum(1 for r in rs
                       if any(k.startswith(stmt_prefix) for k in r["counts"]))
        bs, is_, cf, appr, sce = (hit("BS"), hit("IS"), hit("CF"), hit("APPR"), hit("SCE"))
        zero = sum(1 for r in rs if not r["counts"])
        lines.append(f"| {year} | {n} | {bs} | {is_} | {cf} | {appr} | {sce} | {zero} |")
    lines.append("")
    lines.append("## 전부 0건 사례")
    lines.append("")
    lines.append("| rcept_no | corp_name | FY | report_type |")
    lines.append("|---|---|---|---|")
    for r in ok:
        if not r["counts"]:
            lines.append(f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | {r['report_type']} |")
    lines.append("")
    if errors:
        lines.append("## 오류")
        lines.append("")
        for r in errors:
            lines.append(f"- {r['rcept_no']} ({r['fiscal_year']} {r['report_type']}, {r['corp_name']}): {r['error']}")
        lines.append("")
    lines.append("## 결론 (사람이 채움)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다._")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
