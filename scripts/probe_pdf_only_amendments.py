"""Phase 1 probe (§1-9) — PDF-only 정정 필링 비율 실측 + 기존 3분류 유효성 확인.

핵심 발견(2026-08-11 사전조사): `filings.superseded_by`는 **프로젝트 전체에서 0% 채워져
있음**(사용되지 않는 컬럼) — 정정 계보는 그 컬럼이 아니라 (corp_code, report_type,
fiscal_year, fiscal_period, is_final=True) 그룹키로 "같은 기간의 최종본"을 찾아 재구성해야
한다(§4에서 계획한 `amended_by` 계보는 XML 파이프라인에도 아직 없는 **신규 개념** — Phase 2
설계 항목).

이 스크립트는: is_final=False PDF-only 필링(2015+ 297건 + pre-2015분 포함, 그룹조인 결과
506건 실측) 각각에 대해 같은 기간 최종본을 그룹키로 찾고,
  (a) 최종본이 XML 보유 → 이 정정 계보는 최종 데이터엔 이미 반영됨(계보만 추가 과제)
  (b) 최종본도 PDF-only → 진짜 "PDF 정정 쌍" — §3-1 3분류(FULL_REPORT/PARTIAL_COVER/
      NON_FINANCIAL) classify_amendment_pdf()를 표본에 실제 적용해 유효성 확인
  (c) 최종본을 못 찾음(orphan) — 있으면 원인 조사 필요

읽기 전용: DB에 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.pdf.pdf_amendment_handler import classify_amendment_pdf

SEED = "amendments-2026-08-11"
SAMPLE_N = 30


def gather(session) -> list[dict]:
    q = text("""
        WITH filing_types AS (
          SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, f.filed_at,
                 f.report_type, f.is_final, f.report_nm,
                 bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml,
                 bool_or(dt.file_type='pdf' AND dt.status='completed') AS has_pdf
          FROM filings f
          JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
          JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
          GROUP BY f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, f.filed_at,
                   f.report_type, f.is_final, f.report_nm
        ),
        pdf_only_nonfinal AS (
          SELECT * FROM filing_types WHERE NOT has_xml AND has_pdf AND is_final = false
        )
        SELECT
          p.rcept_no AS orig_rcept, p.filed_at AS orig_filed_at, p.report_nm AS orig_report_nm,
          p.corp_code, p.fiscal_year, p.fiscal_period, p.report_type,
          s.rcept_no AS final_rcept, s.filed_at AS final_filed_at, s.has_xml AS final_has_xml,
          s.has_pdf AS final_has_pdf, s.report_nm AS final_report_nm
        FROM pdf_only_nonfinal p
        LEFT JOIN filing_types s
          ON s.corp_code = p.corp_code AND s.report_type = p.report_type
         AND s.fiscal_year = p.fiscal_year AND s.fiscal_period = p.fiscal_period
         AND s.is_final = true AND s.rcept_no <> p.rcept_no
    """)
    return [dict(r) for r in session.execute(q).mappings().all()]


def file_path_for(session, rcept_no: str) -> str | None:
    q = text("""
        SELECT file_path FROM download_tasks
        WHERE rcept_no = :r AND file_type = 'pdf' AND status = 'completed'
        LIMIT 1
    """)
    row = session.execute(q, {"r": rcept_no}).first()
    return row[0] if row else None


def main() -> None:
    import pdfplumber

    with get_session() as session:
        rows = gather(session)
        print(f"total is_final=False pdf-only rows (grouped): {len(rows)}")

        no_sibling = [r for r in rows if r["final_rcept"] is None]
        sib_xml = [r for r in rows if r["final_rcept"] and r["final_has_xml"]]
        sib_pdf = [r for r in rows if r["final_rcept"] and not r["final_has_xml"] and r["final_has_pdf"]]

        print(f"no final sibling found (orphan): {len(no_sibling)}")
        print(f"final sibling has XML (already covered): {len(sib_xml)}")
        print(f"final sibling also PDF-only (true PDF amendment pair): {len(sib_pdf)}")

        # sample true PDF amendment pairs and run classify_amendment_pdf on both members
        import random
        random.seed(SEED)
        sample_pairs = random.sample(sib_pdf, min(SAMPLE_N, len(sib_pdf)))

        classified = []
        for r in sample_pairs:
            orig_path = file_path_for(session, r["orig_rcept"])
            final_path = file_path_for(session, r["final_rcept"])
            rec = {**r, "orig_path": orig_path, "final_path": final_path}
            for label, rcept, path in [
                ("orig", r["orig_rcept"], orig_path),
                ("final", r["final_rcept"], final_path),
            ]:
                if not path or not Path(path).exists():
                    rec[f"{label}_class"] = "file_missing"
                    continue
                try:
                    with pdfplumber.open(path) as pdf:
                        cls = classify_amendment_pdf(pdf)
                        rec[f"{label}_class"] = cls.value
                        rec[f"{label}_pages"] = len(pdf.pages)
                except Exception as e:
                    rec[f"{label}_class"] = f"error:{type(e).__name__}"
            classified.append(rec)
            print(f"  {r['orig_rcept']} -> {r['final_rcept']}: "
                  f"orig={rec.get('orig_class')} final={rec.get('final_class')}")

    write_report(rows, no_sibling, sib_xml, sib_pdf, classified)


def write_report(rows, no_sibling, sib_xml, sib_pdf, classified) -> None:
    out_path = Path("docs/qa/pdf_only_amendments_probe_2026-08-11.md")
    lines = []
    lines.append("# Phase 1-9 — PDF-only 정정 필링 실측 (2026-08-11)")
    lines.append("")
    lines.append(
        "> 계획서 §1-9(정정 PDF 쌍 비율 실측, is_final=False 297건 포함 스코프). 스크립트 = "
        "`scripts/probe_pdf_only_amendments.py`(읽기 전용)."
    )
    lines.append("")
    lines.append(
        "**★사전 발견**: `filings.superseded_by`는 프로젝트 전체(188,296건) 중 0건 채워짐 — "
        "정정 계보 추적에 쓸 수 없는 죽은 컬럼. 대신 (corp_code, report_type, fiscal_year, "
        "fiscal_period, is_final=True) 그룹키로 같은 기간 최종본을 찾아 재구성했다(아래 결과는 "
        "이 방식 기준). §4에서 언급한 `amended_by` 계보는 XML 파이프라인에도 없는 **신규 "
        "스키마 개념** — Phase 2 설계 시 반영 필요."
    )
    lines.append("")
    lines.append(f"**is_final=False PDF-only 필링(그룹조인 기준) 총 {len(rows)}건**")
    lines.append("")
    lines.append("| 분류 | 건수 | 비율 |")
    lines.append("|---|---|---|")
    lines.append(f"| 최종본을 못 찾음(orphan) | {len(no_sibling)} | {len(no_sibling)/len(rows)*100:.1f}% |")
    lines.append(f"| 최종본이 XML 보유(이미 커버됨) | {len(sib_xml)} | {len(sib_xml)/len(rows)*100:.1f}% |")
    lines.append(f"| 최종본도 PDF-only(진짜 정정쌍) | {len(sib_pdf)} | {len(sib_pdf)/len(rows)*100:.1f}% |")
    lines.append("")

    if no_sibling:
        lines.append("## orphan 표본(최종본 못 찾음)")
        lines.append("")
        lines.append("| rcept_no | corp_code | FY | period | report_type | report_nm |")
        lines.append("|---|---|---|---|---|---|")
        for r in no_sibling[:15]:
            lines.append(
                f"| {r['orig_rcept']} | {r['corp_code']} | {r['fiscal_year']} | "
                f"{r['fiscal_period']} | {r['report_type']} | {r['orig_report_nm']} |"
            )
        lines.append("")

    lines.append("## 3분류(FULL_REPORT/PARTIAL_COVER/NON_FINANCIAL) 실측 적용 결과")
    lines.append("")
    lines.append(f"표본 {len(classified)}쌍(orig=is_final=False 필링, final=같은 기간 최종본)")
    lines.append("")
    lines.append("| orig_rcept | final_rcept | FY | period | orig_class | final_class | orig_report_nm |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in classified:
        lines.append(
            f"| {r['orig_rcept']} | {r['final_rcept']} | {r['fiscal_year']} | "
            f"{r['fiscal_period']} | {r.get('orig_class')} | {r.get('final_class')} | "
            f"{r['orig_report_nm']} |"
        )
    lines.append("")

    from collections import Counter
    orig_dist = Counter(r.get("orig_class") for r in classified)
    final_dist = Counter(r.get("final_class") for r in classified)
    lines.append(f"**orig 분류 분포**: {dict(orig_dist)}")
    lines.append("")
    lines.append(f"**final 분류 분포**: {dict(final_dist)}")
    lines.append("")

    lines.append("## 결론 (초안 — 사용자 검토 후 Phase 2 착수)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다._")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
