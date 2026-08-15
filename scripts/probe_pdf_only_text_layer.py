"""Phase 1 probe (§1-3) — PDF-only 전수(3,509건) 텍스트 레이어 사전 스캔.

이미지 스캔 PDF(텍스트 레이어 없음) 비율을 전수 확정해 OCR 조사(§1-8) 표본 규모를 정한다.
§3-1 `pdf_section_detector.is_text_based_pdf()`와 동일 판정(첫 5페이지 평균 텍스트 길이
50자 미만 → 이미지 스캔으로 간주)을 재사용, 전 3,509건에 적용.

읽기 전용: DB에 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

REPORT_TYPES = ["annual", "half", "quarter"]


def era_of(fy) -> str:
    if fy is None:
        return "unknown"
    if fy < 2015:
        return "pre2015"
    if fy <= 2019:
        return "2015-2019"
    return "2020+"


def all_pdf_only(session) -> list[dict]:
    q = text("""
        WITH filing_types AS (
          SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at,
                 f.report_type,
                 bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml
          FROM filings f
          JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
          JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
          GROUP BY f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at, f.report_type
        )
        SELECT ft.rcept_no, ft.corp_code, ft.corp_name, ft.fiscal_year, ft.filed_at,
               ft.report_type, dt.file_path
        FROM filing_types ft
        JOIN download_tasks dt ON dt.rcept_no = ft.rcept_no
            AND dt.file_type = 'pdf' AND dt.status = 'completed'
        WHERE NOT ft.has_xml
    """)
    return [dict(r) for r in session.execute(q).mappings().all()]


def is_text_based(pdf, sample_pages: int = 5) -> tuple[bool, float, int]:
    total, checked = 0, 0
    npages = len(pdf.pages)
    for page in list(pdf.pages)[:sample_pages]:
        try:
            t = page.extract_text() or ""
            total += len(t)
            checked += 1
        except Exception:
            continue
    if checked == 0:
        return False, 0.0, npages
    avg = total / checked
    return avg >= 50, avg, npages


def main() -> None:
    import pdfplumber

    with get_session() as session:
        rows = all_pdf_only(session)
    print(f"total PDF-only filings: {len(rows)}")

    results = []
    for i, r in enumerate(rows):
        path = Path(r["file_path"])
        rec = {**r, "era": era_of(r["fiscal_year"])}
        if not path.exists():
            rec["status"] = "file_missing"
        else:
            try:
                with pdfplumber.open(path) as pdf:
                    tb, avg, npages = is_text_based(pdf)
                    rec["status"] = "text" if tb else "image_scan"
                    rec["avg_chars"] = round(avg, 1)
                    rec["page_count"] = npages
            except Exception as e:
                rec["status"] = f"error:{type(e).__name__}"
        results.append(rec)
        if (i + 1) % 200 == 0:
            print(f"  scanned {i + 1}/{len(rows)}")

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pdf_only_text_layer_probe_2026-08-11.md")
    lines = []
    lines.append("# Phase 1-3 — PDF-only 전수 텍스트 레이어 스캔 결과 (2026-08-11)")
    lines.append("")
    lines.append(
        "> 계획서 §1-3(이미지 스캔 PDF 비율 전수 실측). 스크립트 = "
        "`scripts/probe_pdf_only_text_layer.py`(읽기 전용). "
        f"전체 {len(results)}건 스캔."
    )
    lines.append("")

    n = len(results)
    text_n = sum(1 for r in results if r["status"] == "text")
    image_n = sum(1 for r in results if r["status"] == "image_scan")
    missing_n = sum(1 for r in results if r["status"] == "file_missing")
    error_n = sum(1 for r in results if r["status"].startswith("error"))
    lines.append(
        f"**텍스트기반 {text_n}({text_n/n*100:.1f}%) · 이미지스캔추정 {image_n}"
        f"({image_n/n*100:.1f}%) · 파일소실 {missing_n} · 오류 {error_n}**"
    )
    lines.append("")

    lines.append("## era × report_type 별 이미지 스캔 비율")
    lines.append("")
    lines.append("| era | report_type | 표본 | 이미지스캔 | 비율 |")
    lines.append("|---|---|---|---|---|")
    grid = defaultdict(list)
    for r in results:
        grid[(r["era"], r["report_type"])].append(r)
    for era in ("pre2015", "2015-2019", "2020+"):
        for rt in REPORT_TYPES:
            rs = grid.get((era, rt), [])
            if not rs:
                continue
            img = sum(1 for r in rs if r["status"] == "image_scan")
            lines.append(f"| {era} | {rt} | {len(rs)} | {img} | {img/len(rs)*100:.1f}% |")
    lines.append("")

    if image_n:
        lines.append("## 이미지 스캔 표본 목록(최대 40건)")
        lines.append("")
        lines.append("| rcept_no | corp_name | FY | report_type | avg_chars | page_count |")
        lines.append("|---|---|---|---|---|---|")
        for r in [r for r in results if r["status"] == "image_scan"][:40]:
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{r['report_type']} | {r.get('avg_chars')} | {r.get('page_count')} |"
            )
        lines.append("")

    if missing_n or error_n:
        lines.append("## 파일소실/오류 표본")
        lines.append("")
        lines.append("| rcept_no | corp_name | FY | report_type | status |")
        lines.append("|---|---|---|---|---|")
        for r in results:
            if r["status"] == "file_missing" or r["status"].startswith("error"):
                lines.append(
                    f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                    f"{r['report_type']} | {r['status']} |"
                )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
