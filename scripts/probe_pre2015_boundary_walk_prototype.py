"""Phase 2 design validation — prototype the proposed fix for the root cause
found in `docs/qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md`:

    `assign_tables_to_dart_sections` / `iter_section_elements` both RESET
    (deactivate) section tracking the instant they see ANY nested SECTION-N
    with an unrecognized TITLE — including pre-2015 K-GAAP's Korean-ordinal
    statement sub-headings ("가. 대차대조표", "나. 손익계산서", …). Since every
    1999-2010 statement sits behind one of these, the walk dies before ever
    reaching a TABLE, and both the primary path and the existing 2026-08-04
    "legacy" fallback (keyed to a DIFFERENT, merged "재무제표등" section) come
    back with zero results.

This script is a THROWAWAY prototype (does not modify production code): it
implements a depth-aware boundary walk that only resets on a SIBLING-OR-
SHALLOWER section change, not on a nested sub-heading, and reuses
`classify_legacy_statement_heading` extended with a Korean-ordinal prefix
strip + the two K-GAAP-only statement names (Q1 decision: include them).
Read-only. Output: docs/qa/pre2015_boundary_walk_prototype_probe_2026-08-10.md
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, normalize_dart_section_title, table_has_amount_rows,
)
from fin2.extract.statement_titles import is_legacy_note_marker, _LEGACY_EXCLUDE

YEARS = list(range(1999, 2011))
SAMPLES_PER_YEAR = 8

# ── prototype-only extension of classify_legacy_statement_heading ──────────
_ORDINAL_PREFIX = re.compile(r"^[가-힣]\s*[.．)）]\s*")
_ENUM_PREFIX = re.compile(r"^[\dⅠ-Ⅻ]+\s*[.．)）]")
_HEAD = re.compile(
    r"^(?:연결|별도|개별|반기|분기|중간|당|전)*"
    r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|"
    r"이익잉여금처분계산서|결손금처리계산서)"
)
_PERIOD_AFTER = re.compile(
    r"^(?:제\d+(?:\([^)]*\))?기|\d{4}[.\-년]|[당전]?(?:반기말|분기말|기말)|"
    r"[(（]?단위|[당전]기(?=[\d(（]))"
)
_NAME_TO_CODE = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS",
    "현금흐름표": "CF",
    "이익잉여금처분계산서": "APPR", "결손금처리계산서": "APPR",
}


def classify_heading_ext(text_: str) -> tuple[str, str] | None:
    """Prototype extension: strip a leading Korean-ordinal ("가.", "나.", …)
    BEFORE the enum-prefix/exclude/head checks, then otherwise identical to
    `classify_legacy_statement_heading` (incl. K-GAAP appropriation names)."""
    if not text_:
        return None
    t = re.sub(r"\s+", "", text_)
    t = _ORDINAL_PREFIX.sub("", t) if _ORDINAL_PREFIX.match(t) else t
    if not t or _ENUM_PREFIX.match(t):
        return None
    if _LEGACY_EXCLUDE.search(t[:45]):
        return None
    m = _HEAD.match(t)
    if m is None:
        return None
    stmt = _NAME_TO_CODE[m.group(1)]
    rest = t[m.end():].lstrip("：:·-—")
    if rest and not _PERIOD_AFTER.match(rest):
        return None
    basis = "consolidated" if "연결" in t[:m.start(1)] else "separate"
    return (basis, stmt)


def iter_section_span_depth_aware(root: etree._Element, normalized_title: str):
    """Like `iter_section_elements` but only ends the span on a SIBLING-OR-
    SHALLOWER SECTION-N title change (tracked by counting SECTION ancestors),
    not on any nested sub-heading. TABLE-internal elements excluded."""
    out = []
    inside = False
    entry_depth = None
    depth = 0
    for event, el in etree.iterwalk(root, events=("start", "end")):
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        is_section = tag.startswith("SECTION")
        if event == "start":
            if is_section:
                depth += 1
                title_elem = el.find("TITLE")
                norm = normalize_dart_section_title("".join(title_elem.itertext())) if title_elem is not None else None
                if inside and norm is not None and depth <= entry_depth and norm != normalized_title:
                    inside = False
                    entry_depth = None
                elif not inside and norm == normalized_title:
                    inside = True
                    entry_depth = depth
                    continue
            if inside and tag not in ("TITLE",):
                anc = el.getparent()
                is_table_inner = False
                while anc is not None:
                    if isinstance(anc.tag, str) and anc.tag.upper() == "TABLE":
                        is_table_inner = True
                        break
                    anc = anc.getparent()
                if not is_table_inner:
                    out.append((tag, el))
        else:  # end
            if is_section:
                depth -= 1
    return out


def probe_file(sample: dict) -> dict:
    result = {**sample, "error": None, "hits": defaultdict(int), "appr_hits": 0}
    path = Path(sample["file_path"])
    if not path.exists():
        result["error"] = "file_missing"
        return result
    root = _parse_xml_file(path)
    if root is None:
        result["error"] = "parse_failed"
        return result

    for sec_title, basis_expect in ((SEC_SEP_FS, "separate"), (SEC_CONSOL_FS, "consolidated")):
        elements = iter_section_span_depth_aware(root, sec_title)
        pending = None
        pending_age = 0
        for tag, el in elements:
            text_ = " ".join("".join(el.itertext()).split())
            if pending is not None:
                pending_age += 1
                if pending_age > 4:
                    pending = None
            if tag == "TABLE" and table_has_amount_rows(el):
                if pending is not None:
                    _, stmt = pending
                    if stmt == "APPR":
                        result["appr_hits"] += 1
                    else:
                        result["hits"][stmt] += 1
                    pending = None
                continue
            if is_legacy_note_marker(text_):
                pending = None
                continue
            head = classify_heading_ext(text_)
            if head is not None:
                pending = head
                pending_age = 0
    return result


def sample_filings(session) -> list[dict]:
    rows = []
    for year in YEARS:
        q = text("""
            SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year,
                   f.report_type, dt.file_path
            FROM filings f
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            JOIN corporations c ON c.corp_code = f.corp_code
            WHERE f.fiscal_year = :year
              AND dt.status = 'completed'
              AND dt.file_type = 'xml'
              AND c.is_active = true
            ORDER BY md5(f.rcept_no || 'boundary-walk-2026-08-10')
            LIMIT :n
        """)
        res = session.execute(q, {"year": year, "n": SAMPLES_PER_YEAR}).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def main() -> None:
    with get_session() as session:
        samples = sample_filings(session)
    print(f"sampled {len(samples)} filings")
    results = [probe_file(s) for s in samples]
    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pre2015_boundary_walk_prototype_probe_2026-08-10.md")
    lines = []
    lines.append("# Phase 2 설계 검증 — 깊이인식 경계walk 프로토타입 실측 (2026-08-10)")
    lines.append("")
    lines.append(
        "> **프로덕션 코드 무변경.** `pre2015_existing_pipeline_reuse_probe_2026-08-10.md`에서 찾은 "
        "근본원인(중첩 SECTION-N 하위표제를 만나면 즉시 리셋)에 대한 제안 수정을 스크립트 내부에서만 "
        "구현해 검증한다: ①SECTION 깊이를 추적해 **형제-이하 레벨 표제 변경에서만** 구간을 끝내고 "
        "②`classify_legacy_statement_heading`을 한글서수 접두('가.'/'나.'/…) 제거 + K-GAAP 전용 "
        "표(이익잉여금처분계산서/결손금처리계산서) 포함으로 확장."
    )
    lines.append("")
    ok = [r for r in results if not r["error"]]
    errors = [r for r in results if r["error"]]
    lines.append(f"**표본 {len(results)}건(1999~2010, 연도당 {SAMPLES_PER_YEAR}건) · 정상 {len(ok)}건 · 오류 {len(errors)}건**")
    lines.append("")
    lines.append("## 연도별 BS/IS/CF/APPR 검출 성공률 (문서 단위, 연결+별도 중 하나라도 hit)")
    lines.append("")
    lines.append("| FY | 표본 | BS | IS | CF | APPR(K-GAAP) | 전부0 |")
    lines.append("|---|---|---|---|---|---|---|")
    by_year = defaultdict(list)
    for r in results:
        by_year[r["fiscal_year"]].append(r)
    for year in YEARS:
        rs = [r for r in by_year.get(year, []) if not r["error"]]
        n = len(rs)
        bs = sum(1 for r in rs if r["hits"].get("BS", 0) > 0)
        is_ = sum(1 for r in rs if r["hits"].get("IS", 0) > 0)
        cf = sum(1 for r in rs if r["hits"].get("CF", 0) > 0)
        appr = sum(1 for r in rs if r["appr_hits"] > 0)
        zero = sum(1 for r in rs if not r["hits"] and r["appr_hits"] == 0)
        lines.append(f"| {year} | {n} | {bs} | {is_} | {cf} | {appr} | {zero} |")
    lines.append("")
    lines.append("## 전부 0건 사례")
    lines.append("")
    lines.append("| rcept_no | corp_name | FY | report_type |")
    lines.append("|---|---|---|---|")
    for r in ok:
        if not r["hits"] and r["appr_hits"] == 0:
            lines.append(f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | {r['report_type']} |")
    lines.append("")
    if errors:
        lines.append("## 오류")
        lines.append("")
        for r in errors:
            lines.append(f"- {r['rcept_no']} ({r['fiscal_year']}): {r['error']}")
        lines.append("")
    lines.append("## 결론 (사람이 채움)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다._")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
