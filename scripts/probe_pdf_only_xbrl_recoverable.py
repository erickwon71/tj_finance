"""Phase 1 probe (§1-2 최우선 조사) — PDF-only 필링이 ifrs.do 경로로 XBRL 회수 가능한지 실측.

배경: 12건 소표본에서 document.xml 이 전부 014(파일없음)를 반환하는 걸 확인했고,
LegacyDartScraper.fetch_xbrl_zip() (ifrs.do)를 같은 12건에 시험 적용했더니 **2015+ 표본
5/5건 전부 XBRL 회수 성공**, pre-2015 표본 7/7건 전부 실패했다 — "2015-2019 몰림"이
DART가 원래 XML을 안 준 게 아니라, **현재 다운로더가 최근에 추가된 ifrs.do 폴백을
당시엔 없었던 탓에 시도하지 않았을 가능성**을 시사한다. 이 스크립트는 더 큰 표본으로
그 패턴을 확정한다.

읽기 전용: DB에 아무것도 쓰지 않는다(document_zip/legacy fetch만 호출, 저장 안 함).
호출량: 표본당 opendart document.xml 1회(1초 간격) + dart.fss.or.kr 웹 스크래핑 2회
(2초 간격) — N=80이면 약 7분 소요.

Output: docs/qa/pdf_only_xbrl_recoverable_probe_2026-08-11.md
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.dart_client import DartClient
from collector.legacy_downloader import LegacyDartScraper

SEED = "xbrl-recoverable-2026-08-11"
N_PER_ERA = 40


def sample(session, era_filter: str) -> list[dict]:
    if era_filter == "pre2015":
        cond = "f.filed_at < '2015-01-01'"
    else:
        cond = "f.filed_at >= '2015-01-01'"
    q = text(f"""
        WITH filing_types AS (
          SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at,
                 f.report_type,
                 bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml
          FROM filings f
          JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
          JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
          WHERE {cond}
          GROUP BY f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at, f.report_type
        )
        SELECT ft.rcept_no, ft.corp_code, ft.corp_name, ft.fiscal_year, ft.filed_at, ft.report_type
        FROM filing_types ft
        WHERE NOT ft.has_xml
          AND EXISTS (
            SELECT 1 FROM download_tasks dt2
            WHERE dt2.rcept_no = ft.rcept_no AND dt2.file_type = 'pdf' AND dt2.status = 'completed'
          )
        ORDER BY md5(ft.rcept_no || :seed)
        LIMIT :n
    """)
    res = session.execute(q, {"seed": SEED, "n": N_PER_ERA}).mappings().all()
    return [dict(r) for r in res]


def probe_one(dart_client: DartClient, scraper: LegacyDartScraper, s: dict) -> dict:
    result = {**s}
    # step 1: confirm document.xml behavior (should be 014 per prior finding)
    try:
        raw = dart_client.get_document_zip(s["rcept_no"])
        if raw[:2] == b"PK":
            zf = zipfile.ZipFile(io.BytesIO(raw))
            exts = sorted({n.rsplit(".", 1)[-1].lower() for n in zf.namelist()})
            result["document_xml"] = f"ZIP:{exts}"
        else:
            # parse minimal status code out of the error XML
            txt = raw.decode("utf-8", errors="replace")
            import re
            m = re.search(r"<status>(\d+)</status>", txt)
            result["document_xml"] = f"error_{m.group(1)}" if m else "error_unknown"
    except Exception as e:
        result["document_xml"] = f"exc:{type(e).__name__}"

    # step 2: try ifrs.do XBRL fallback regardless of step 1 outcome
    try:
        zip_bytes, dcm_no = scraper.fetch_xbrl_zip(s["rcept_no"])
        result["xbrl_recoverable"] = zip_bytes is not None
        result["xbrl_size"] = len(zip_bytes) if zip_bytes else 0
        result["dcm_no"] = dcm_no
    except Exception as e:
        result["xbrl_recoverable"] = None
        result["xbrl_error"] = f"exc:{type(e).__name__}:{e}"

    return result


def main() -> None:
    with get_session() as session:
        pre2015 = sample(session, "pre2015")
        post2015 = sample(session, "post2015")

    print(f"sampled pre2015={len(pre2015)} post2015={len(post2015)}")

    dart_client = DartClient()
    scraper = LegacyDartScraper()
    results = []
    all_samples = [("pre2015", s) for s in pre2015] + [("2015+", s) for s in post2015]
    for i, (era, s) in enumerate(all_samples):
        r = probe_one(dart_client, scraper, s)
        r["era"] = era
        results.append(r)
        print(f"  [{i+1}/{len(all_samples)}] {era} {s['rcept_no']} {s['fiscal_year']} "
              f"{s['report_type']} -> document_xml={r.get('document_xml')} "
              f"xbrl_recoverable={r.get('xbrl_recoverable')}")
    dart_client.close()
    scraper.close()

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pdf_only_xbrl_recoverable_probe_2026-08-11.md")
    lines = []
    lines.append("# Phase 1-2 — PDF-only ifrs.do XBRL 회수가능성 실측 (2026-08-11)")
    lines.append("")
    lines.append(
        "> 계획서 §1-2(2015-2019 몰림 원인 최우선 조사) 실행 결과. 스크립트 = "
        "`scripts/probe_pdf_only_xbrl_recoverable.py`(읽기 전용, DB 미기록)."
    )
    lines.append("")

    for era in ("pre2015", "2015+"):
        rs = [r for r in results if r["era"] == era]
        recoverable = sum(1 for r in rs if r.get("xbrl_recoverable") is True)
        errs = sum(1 for r in rs if r.get("xbrl_recoverable") is None)
        lines.append(f"## {era} (표본 {len(rs)}건)")
        lines.append("")
        lines.append(f"**XBRL 회수가능 {recoverable}/{len(rs)}건"
                      f"({recoverable/len(rs)*100:.1f}%), 조사오류 {errs}건**")
        lines.append("")
        lines.append("| rcept_no | corp_name | FY | report_type | document.xml | xbrl_recoverable | size |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in rs:
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | {r['report_type']} | "
                f"{r.get('document_xml')} | {r.get('xbrl_recoverable')} | {r.get('xbrl_size', 0)} |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
