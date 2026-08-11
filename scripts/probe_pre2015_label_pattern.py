"""Phase 1 follow-up (round 2) — characterize the tag-less plain-text heading
pattern found in the FY2011-2014 "NEITHER" majority
(`docs/qa/pre2015_span_boundary_probe_2026-08-10.md` §4-2/4-4).

Strategy switch: instead of searching forward for heading-like text and hoping
it's near a table, search BACKWARD from statement DATA (anchor cells with
universal K-GAAP/IFRS line-item labels: 자산총계/당기순이익/영업활동으로 인한
현금흐름) to whatever heading text actually precedes it, regardless of tag.
This finds the real heading text even when it carries no distinguishing markup.

Read-only: does not touch report_lines/note_lines or any production table.
Output: docs/qa/pre2015_label_pattern_probe_2026-08-10.md
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file

YEARS = [2011, 2012, 2013, 2014]
SAMPLES_PER_YEAR = 12

ANCHOR_LABELS = {
    "BS": ["자산총계"],
    "IS": ["당기순이익", "반기순이익", "분기순이익"],
    "CF": ["영업활동으로 인한 현금흐름", "영업활동현금흐름"],
}
STATEMENT_KW = {
    "BS": ["재무상태표", "대차대조표"],
    "IS": ["손익계산서"],
    "CF": ["현금흐름표"],
}
MAX_BACK_HOPS = 80
HEADING_LEN_GUARD = 40


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
            ORDER BY md5(f.rcept_no || 'label-pattern-2026-08-10')
            LIMIT :n
        """)
        res = session.execute(q, {"year": year, "n": SAMPLES_PER_YEAR}).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def find_anchor_tables(root: etree._Element, label_kw: list[str]) -> list[etree._Element]:
    """TABLE elements containing a cell whose full text equals (stripped) one
    of the anchor labels — a reliable, tag-agnostic way to locate the real
    statement table regardless of how its heading is marked up."""
    out = []
    for table in root.iter("TABLE"):
        for cell in table.iter():
            if cell.tag in ("TD", "TU"):
                txt = "".join(cell.itertext()).strip()
                if txt in label_kw:
                    out.append(table)
                    break
    return out


def doc_text_stream(root: etree._Element) -> list[tuple[etree._Element, str]]:
    """Flatten the whole tree into (source_elem, text_chunk) pairs in true
    document order — .text before children, each child's subtree, then that
    child's .tail. Plain sibling.getprevious()+.text walks (the first attempt
    here) silently skip .tail text, which is exactly where DART XML puts most
    inline heading text (right after a <SPAN> closes) — hence this rewrite."""
    out: list[tuple[etree._Element, str]] = []

    def walk(e: etree._Element) -> None:
        if e.text:
            out.append((e, e.text))
        for child in e:
            walk(child)
            if child.tail:
                out.append((child, child.tail))

    walk(root)
    return out


def nearest_heading(
    table: etree._Element, kws: list[str], stream: list[tuple[etree._Element, str]]
) -> dict | None:
    table_descendants = {id(x) for x in table.iter()}
    start = next(
        (i for i, (elem, _) in enumerate(stream) if id(elem) in table_descendants),
        None,
    )
    if start is None:
        return None
    hops = 0
    for i in range(start - 1, -1, -1):
        if hops >= MAX_BACK_HOPS:
            break
        elem, txt = stream[i]
        txt = txt.strip()
        if not txt:
            continue
        hops += 1
        if len(txt) <= HEADING_LEN_GUARD and any(k in txt for k in kws):
            return {"hops": hops, "tag": elem.tag, "text": txt}
    return None


_PREFIX_RE = re.compile(
    r"^(?P<num>[가-힣]\.|\(\d+\)|\d+\)|\d+\.)?\s*(?P<consol>연결|별도)?\s*(?P<rest>.*)$"
)


def classify_prefix(text_: str) -> str:
    m = _PREFIX_RE.match(text_)
    if not m:
        return "미분류"
    num = "번호" if m.group("num") else "번호없음"
    consol = m.group("consol") or "표기없음"
    return f"{num}/{consol}"


def probe_file(sample: dict) -> dict:
    path = Path(sample["file_path"])
    result = {**sample, "error": None, "anchors": {}}
    if not path.exists():
        result["error"] = "file_missing"
        return result
    root = _parse_xml_file(path)
    if root is None:
        result["error"] = "parse_failed"
        return result

    stream = doc_text_stream(root)
    for label, anchor_kw in ANCHOR_LABELS.items():
        tables = find_anchor_tables(root, anchor_kw)
        found_headings = []
        for t in tables[:3]:  # cap per label to keep runtime sane
            h = nearest_heading(t, STATEMENT_KW[label], stream)
            found_headings.append(h)
        result["anchors"][label] = {
            "table_count": len(tables),
            "headings": found_headings,
        }
    return result


def main() -> None:
    with get_session() as session:
        samples = sample_years(session)
    print(f"sampled {len(samples)} filings")

    results = []
    for i, s in enumerate(samples):
        results.append(probe_file(s))
        if (i + 1) % 10 == 0:
            print(f"  probed {i + 1}/{len(samples)}")

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pre2015_label_pattern_probe_2026-08-10.md")
    ok = [r for r in results if not r["error"]]
    errors = [r for r in results if r["error"]]

    lines = []
    lines.append("# Phase 1 후속(2회차) — 2011~2014 평문 인라인 라벨 패턴 실측 (2026-08-10)")
    lines.append("")
    lines.append(
        "> [`pre2015_span_boundary_probe_2026-08-10.md`](pre2015_span_boundary_probe_2026-08-10.md) "
        "§4-2에서 발견한 '태그 없는 평문 라벨' 다수 사례의 실제 텍스트 규칙을 찾기 위해, "
        "**태그가 아니라 데이터를 앵커로** 삼는 방식으로 전환했다: `자산총계`/`당기순이익`/"
        "`영업활동으로 인한 현금흐름` 같은 보편적 계정 라벨 셀을 가진 TABLE을 원문에서 먼저 "
        "찾고, 거기서 역방향으로 가장 가까운 표제 텍스트를 추적한다(태그 무관, 읽기 전용)."
    )
    lines.append("")
    lines.append(
        f"**표본 {len(results)}건({'/'.join(str(y) for y in YEARS)}, 연도당 {SAMPLES_PER_YEAR}건) "
        f"· 파싱 성공 {len(ok)}건 · 실패 {len(errors)}건**"
    )
    lines.append("")

    for label in ["BS", "IS", "CF"]:
        lines.append(f"## {label} 앵커 결과")
        lines.append("")
        total_tables = sum(r["anchors"][label]["table_count"] for r in ok)
        with_heading = sum(
            1 for r in ok for h in r["anchors"][label]["headings"] if h
        )
        without_heading = sum(
            1 for r in ok for h in r["anchors"][label]["headings"] if h is None
        )
        lines.append(
            f"앵커 테이블 총 {total_tables}개(표본 {len(ok)}건) · 표제 발견 {with_heading}개 · "
            f"미발견(80홉 이내 없음) {without_heading}개"
        )
        lines.append("")
        lines.append("| rcept_no | FY | hops | tag | 원문 표제 텍스트 | 접두 분류 |")
        lines.append("|---|---|---|---|---|---|")
        shown = 0
        prefix_counter = Counter()
        hop_dist = []
        for r in ok:
            for h in r["anchors"][label]["headings"]:
                if h is None:
                    continue
                prefix_counter[classify_prefix(h["text"])] += 1
                hop_dist.append(h["hops"])
                if shown < 25:
                    lines.append(
                        f"| {r['rcept_no']} | {r['fiscal_year']} | {h['hops']} | {h['tag']} | "
                        f"{h['text']} | {classify_prefix(h['text'])} |"
                    )
                    shown += 1
        lines.append("")
        if prefix_counter:
            lines.append(f"접두 패턴 분포: {dict(prefix_counter)}")
            lines.append("")
        if hop_dist:
            lines.append(
                f"hop 거리 분포: min={min(hop_dist)} · median={sorted(hop_dist)[len(hop_dist)//2]} · "
                f"max={max(hop_dist)}"
            )
        lines.append("")

    if errors:
        lines.append("## 파싱 실패")
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
