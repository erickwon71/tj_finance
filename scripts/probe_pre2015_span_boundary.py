"""Phase 1 follow-up probe — pin down the TITLE-hierarchy vs SPAN-inline-heading
boundary discovered in `docs/qa/pre2015_structure_probe_2026-08-10.md` §6-3.

Denser per-year sample (2004..2014, ~15 filings/year, mixed report_type) than the
first probe. For each sample, checks BOTH detection paths:
  - TITLE-based (reuse title_records from the first probe)
  - SPAN-based: bold <SPAN USERMARK="..."> elements whose text contains a
    statement keyword, plus whether a TABLE with real amount cells follows nearby
    (crude proximity heuristic — same subtree, within N following elements)

Classifies each sample as TITLE / SPAN / BOTH / NEITHER per statement family
(BS/IS/CF), so the year boundary and reliability of the SPAN heuristic can be
read off directly.

Read-only: does not touch report_lines/note_lines or any production table.
Output: docs/qa/pre2015_span_boundary_probe_2026-08-10.md
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file, _detect_xml_encoding
from probe_pre2015_structure import title_records

YEARS = list(range(2004, 2015))
SAMPLES_PER_YEAR = 15

STATEMENT_KW = {
    "BS": ["재무상태표", "대차대조표"],
    "IS": ["손익계산서"],
    "CF": ["현금흐름표"],
}
# how DART XML from this era marks bold inline text — collect raw values seen,
# don't assume a single canonical value up front.
_SPAN_LEN_GUARD = 30  # a real statement heading is short; long SPAN = body text


def sample_years(session) -> list[dict]:
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
            ORDER BY md5(f.rcept_no || 'span-boundary-2026-08-10')
            LIMIT :n
        """)
        res = session.execute(q, {"year": year, "n": SAMPLES_PER_YEAR}).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def span_heading_hits(root: etree._Element) -> dict[str, list[dict]]:
    """Bold-ish <SPAN> elements (any USERMARK attr) whose text is short and
    contains a statement keyword. Records the USERMARK raw value and whether a
    TABLE with numeric cells appears within the next few siblings/ancestors."""
    hits = defaultdict(list)
    for span in root.iter("SPAN"):
        usermark = span.get("USERMARK")
        if usermark is None:
            continue
        txt = "".join(span.itertext()).strip()
        if not txt or len(txt) > _SPAN_LEN_GUARD:
            continue
        for label, kws in STATEMENT_KW.items():
            if any(k in txt for k in kws):
                hits[label].append({
                    "text": txt,
                    "usermark": usermark,
                    "is_consolidated": "연결" in txt,
                    "table_nearby": _table_within_reach(span),
                })
    return dict(hits)


def _table_within_reach(span: etree._Element, max_hops: int = 40) -> bool:
    """Crude proximity check: walk forward through document order (following
    siblings, then up+forward) up to max_hops elements looking for a TABLE with
    at least one numeric-looking TD."""
    node = span
    hops = 0
    while node is not None and hops < max_hops:
        nxt = node.getnext()
        while nxt is None and node.getparent() is not None:
            node = node.getparent()
            nxt = node.getnext()
        if nxt is None:
            break
        node = nxt
        hops += 1
        if node.tag == "TABLE":
            for td in node.iter("TD"):
                val = "".join(td.itertext()).strip()
                if re.match(r"^-?[\d,]+$", val):
                    return True
            return False
    return False


def probe_file(sample: dict) -> dict:
    path = Path(sample["file_path"])
    result = {**sample, "error": None}
    if not path.exists():
        result["error"] = "file_missing"
        return result
    root = _parse_xml_file(path)
    if root is None:
        result["error"] = "parse_failed"
        return result

    titles = title_records(root)
    title_hits = defaultdict(list)
    for tr in titles:
        for label, kws in STATEMENT_KW.items():
            if any(k in tr["text"] for k in kws):
                title_hits[label].append(tr["text"])

    result["title_hits"] = dict(title_hits)
    result["span_hits"] = span_heading_hits(root)
    result["title_count"] = len(titles)
    return result


def classify(result: dict, label: str) -> str:
    has_title = bool(result["title_hits"].get(label))
    has_span = bool(result["span_hits"].get(label))
    if has_title and has_span:
        return "BOTH"
    if has_title:
        return "TITLE"
    if has_span:
        return "SPAN"
    return "NEITHER"


def main() -> None:
    with get_session() as session:
        samples = sample_years(session)
    print(f"sampled {len(samples)} filings")

    results = []
    for i, s in enumerate(samples):
        results.append(probe_file(s))
        if (i + 1) % 20 == 0:
            print(f"  probed {i + 1}/{len(samples)}")

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pre2015_span_boundary_probe_2026-08-10.md")
    ok = [r for r in results if not r["error"]]
    errors = [r for r in results if r["error"]]

    by_year = defaultdict(list)
    for r in ok:
        by_year[r["fiscal_year"]].append(r)

    lines = []
    lines.append("# Phase 1 후속 — SPAN 인라인 표제 경계 실측 (2026-08-10)")
    lines.append("")
    lines.append(
        "> 1차 확률표본([`pre2015_structure_probe_2026-08-10.md`](pre2015_structure_probe_2026-08-10.md) "
        "§6-3)에서 발견한 '2012~2014년은 TITLE 대신 굵은 SPAN 인라인 표제'를 확인하기 위해 "
        "2004~2014년을 연도당 15건(report_type 무관, 읽기 전용)으로 밀도를 높여 재표본."
    )
    lines.append("")
    lines.append(f"**표본 {len(results)}건 · 파싱 성공 {len(ok)}건 · 실패 {len(errors)}건**")
    lines.append("")

    lines.append("## 1. 연도별 BS/IS/CF 검출 경로")
    lines.append("")
    for label in ["BS", "IS", "CF"]:
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| FY | 표본 | TITLE만 | SPAN만 | 둘다 | 둘다없음 |")
        lines.append("|---|---|---|---|---|---|")
        for year in YEARS:
            yr = by_year.get(year, [])
            if not yr:
                lines.append(f"| {year} | 0 | - | - | - | - |")
                continue
            counts = Counter(classify(r, label) for r in yr)
            lines.append(
                f"| {year} | {len(yr)} | {counts['TITLE']} | {counts['SPAN']} | "
                f"{counts['BOTH']} | {counts['NEITHER']} |"
            )
        lines.append("")

    lines.append("## 2. SPAN 표제 발견 사례 (USERMARK 값 · 표 근접 여부)")
    lines.append("")
    span_examples = []
    for r in ok:
        for label, hits in r["span_hits"].items():
            for h in hits:
                span_examples.append((r, label, h))
    if span_examples:
        lines.append("| rcept_no | FY | label | 텍스트 | USERMARK | 연결 | 표 근접 |")
        lines.append("|---|---|---|---|---|---|---|")
        for r, label, h in span_examples[:40]:
            lines.append(
                f"| {r['rcept_no']} | {r['fiscal_year']} | {label} | {h['text']} | "
                f"`{h['usermark']}` | {'Y' if h['is_consolidated'] else 'N'} | "
                f"{'Y' if h['table_nearby'] else 'N'} |"
            )
        lines.append("")
        usermark_dist = Counter(h["usermark"] for _, _, h in span_examples)
        lines.append(f"USERMARK 값 분포: {dict(usermark_dist)}")
        table_nearby_rate = sum(1 for _, _, h in span_examples if h["table_nearby"]) / len(span_examples)
        lines.append(f"표 근접 비율(휴리스틱, 40홉 이내 TABLE+숫자셀): {table_nearby_rate*100:.1f}%")
    else:
        lines.append("(발견되지 않음)")
    lines.append("")

    if errors:
        lines.append("## 3. 파싱 실패")
        lines.append("")
        for r in errors:
            lines.append(f"- {r['rcept_no']} ({r['fiscal_year']}): {r['error']}")
        lines.append("")

    lines.append("## 4. 결론 (사람이 채움)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다._")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
