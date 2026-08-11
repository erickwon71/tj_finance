"""Phase 1 probe — pre-2015 XML structural census (read-only, no DB writes).

Stratified sample across fiscal_year(1999..2014) x report_type(annual/half/quarter),
4 filings per stratum (~192 total), drawn from the active-universe XML backlog.
For each sample, records: encoding, TITLE hierarchy, whether BS/IS/CF/consolidated
statements are located and at what nesting depth, K-GAAP-only statement presence,
table cell structure hints (ROWSPAN/COLSPAN/TU usage), unit-declaration phrasing.

Output: docs/qa/pre2015_structure_probe_2026-08-10.md

Companion to docs/plans/pre2015_layer2_backfill_plan_2026-08-10.md Phase 1.
Read-only: does not touch report_lines/note_lines or any production table.
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
from parser.xml.dart_xml_parser import _parse_xml_file, _detect_xml_encoding

REPORT_TYPES = ["annual", "half", "quarter"]
YEARS = list(range(1999, 2015))
SAMPLES_PER_STRATUM = 4

# Keywords of interest in <TITLE> text.
BS_KW = [("BS", ["재무상태표"]), ("BS_KGAAP", ["대차대조표"])]
IS_KW = [("IS", ["손익계산서"])]
CF_KW = [("CF", ["현금흐름표"])]
SCE_KW = [("SCE", ["자본변동표"])]
KGAAP_ONLY_KW = [("RETAINED_APPROP", ["이익잉여금처분계산서", "결손금처리계산서"])]
CONSOL_HEADING_KW = ["연결재무제표"]
NOTE_KW = ["주석"]

UNIT_DECL_RE = re.compile(r"단위\s*[:：]\s*[^\s<]{0,10}원")


def sample_stratified(session) -> list[dict]:
    rows = []
    for year in YEARS:
        for rtype in REPORT_TYPES:
            q = text("""
                SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year,
                       f.report_type, c.market, dt.file_path
                FROM filings f
                JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
                JOIN corporations c ON c.corp_code = f.corp_code
                WHERE f.fiscal_year = :year
                  AND f.report_type = :rtype
                  AND dt.status = 'completed'
                  AND dt.file_type = 'xml'
                  AND c.is_active = true
                ORDER BY md5(f.rcept_no || '2026-08-10')
                LIMIT :n
            """)
            res = session.execute(
                q, {"year": year, "rtype": rtype, "n": SAMPLES_PER_STRATUM}
            ).mappings().all()
            rows.extend(dict(r) for r in res)
    return rows


def title_records(root: etree._Element) -> list[dict]:
    """Every TITLE element with text, nesting depth (# ancestor SECTION-2), and
    ancestor TITLE chain (for context like '4. 연결재무제표' parent)."""
    out = []
    for title_el in root.iter("TITLE"):
        text_ = "".join(title_el.itertext()).strip()
        depth = 0
        ancestor_titles = []
        node = title_el.getparent()
        while node is not None:
            if node.tag == "SECTION-2":
                depth += 1
                # sibling TITLE immediately inside this SECTION-2, if not the current one
                for child in node:
                    if child.tag == "TITLE" and child is not title_el:
                        t = "".join(child.itertext()).strip()
                        if t:
                            ancestor_titles.append(t)
                        break
            node = node.getparent()
        out.append({
            "text": text_,
            "depth": depth,
            "ancestors": list(reversed(ancestor_titles)),
            "elem": title_el,
        })
    return out


def nearest_section2(title_el: etree._Element) -> etree._Element | None:
    node = title_el.getparent()
    while node is not None and node.tag != "SECTION-2":
        node = node.getparent()
    return node


def table_stats(section_el: etree._Element) -> dict:
    if section_el is None:
        return {"tables": 0, "rowspan": 0, "colspan": 0, "tu_cells": 0, "td_cells": 0}
    tables = section_el.findall(".//TABLE")
    rowspan = colspan = tu = td = 0
    for t in tables:
        for cell in t.iter():
            if cell.tag in ("TD", "TU"):
                if cell.tag == "TU":
                    tu += 1
                else:
                    td += 1
                if cell.get("ROWSPAN") not in (None, "1"):
                    rowspan += 1
                if cell.get("COLSPAN") not in (None, "1"):
                    colspan += 1
    return {"tables": len(tables), "rowspan": rowspan, "colspan": colspan,
            "tu_cells": tu, "td_cells": td}


def unit_decl_near(section_el: etree._Element) -> list[str]:
    if section_el is None:
        return []
    found = []
    for node in section_el.iter():
        if node.text:
            for m in UNIT_DECL_RE.finditer(node.text):
                found.append(m.group(0))
    return found[:3]


def probe_file(sample: dict) -> dict:
    path = Path(sample["file_path"])
    result = {**sample, "error": None}
    if not path.exists():
        result["error"] = "file_missing"
        return result

    raw = path.read_bytes()
    result["encoding"] = _detect_xml_encoding(raw)
    root = _parse_xml_file(path)
    if root is None:
        result["error"] = "parse_failed"
        return result

    titles = title_records(root)
    result["title_count"] = len(titles)

    found = defaultdict(list)
    for tr in titles:
        for group in [BS_KW, IS_KW, CF_KW, SCE_KW, KGAAP_ONLY_KW]:
            for label, kws in group:
                if all(k in tr["text"] for k in kws):
                    is_consol = ("연결" in tr["text"]) or any(
                        "연결" in a for a in tr["ancestors"]
                    ) or any(kw in a for a in tr["ancestors"] for kw in CONSOL_HEADING_KW)
                    consol_source = (
                        "leaf" if "연결" in tr["text"]
                        else ("ancestor" if is_consol else "none")
                    )
                    found[label].append({
                        "text": tr["text"], "depth": tr["depth"],
                        "ancestors": tr["ancestors"],
                        "is_consolidated": is_consol,
                        "consol_source": consol_source,
                        "elem": tr["elem"],
                    })

    result["found"] = {k: v for k, v in found.items()}

    # table structure for the first BS-ish hit (any flavor), separate + consolidated if present
    stats_by_label = {}
    unit_decls = []
    for label, hits in found.items():
        if label in ("BS", "BS_KGAAP") and hits:
            for h in hits[:2]:
                sec = nearest_section2(h["elem"])
                stats_by_label.setdefault(label, []).append(table_stats(sec))
                unit_decls.extend(unit_decl_near(sec))
    result["table_stats"] = stats_by_label
    result["unit_decls"] = unit_decls[:3]

    return result


def main() -> None:
    with get_session() as session:
        samples = sample_stratified(session)

    print(f"sampled {len(samples)} filings")
    results = []
    for i, s in enumerate(samples):
        r = probe_file(s)
        results.append(r)
        if (i + 1) % 20 == 0:
            print(f"  probed {i + 1}/{len(samples)}")

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pre2015_structure_probe_2026-08-10.md")

    n = len(results)
    errors = [r for r in results if r["error"]]
    ok = [r for r in results if not r["error"]]

    enc_counts = Counter(r["encoding"] for r in ok)

    # per-year aggregation
    by_year = defaultdict(list)
    for r in ok:
        by_year[r["fiscal_year"]].append(r)

    lines = []
    lines.append("# Phase 1 — pre-2015 구조 정밀 실측 결과 (2026-08-10)")
    lines.append("")
    lines.append(
        "> 계획서 = [`pre2015_layer2_backfill_plan_2026-08-10.md`](../plans/"
        "pre2015_layer2_backfill_plan_2026-08-10.md) Phase 1. 실행 스크립트 = "
        "`scripts/probe_pre2015_structure.py`(읽기 전용, DB/report_lines 미변경). "
        "층화표본 1999~2014 × report_type(annual/half/quarter) × 4건/스트라텀."
    )
    lines.append("")
    lines.append(f"**표본 {n}건 · 파싱 성공 {len(ok)}건 · 실패 {len(errors)}건**")
    lines.append("")
    lines.append("## 0. 인코딩 분포")
    lines.append("")
    lines.append("| 인코딩 | 건수 | 비율 |")
    lines.append("|---|---|---|")
    for enc, cnt in enc_counts.most_common():
        lines.append(f"| {enc} | {cnt} | {cnt/len(ok)*100:.1f}% |")
    lines.append("")
    if errors:
        lines.append("### 파싱 실패 표본")
        lines.append("")
        lines.append("| rcept_no | corp_name | fiscal_year | report_type | error |")
        lines.append("|---|---|---|---|---|")
        for r in errors:
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{r['report_type']} | {r['error']} |"
            )
        lines.append("")

    lines.append("## 1. 연도별 요약")
    lines.append("")
    lines.append(
        "| FY | 표본 | BS리프연결 | BS조상연결 | BS별도만 | BS미검출 | K-GAAP전용표 | "
        "avg TITLE수 | ROWSPAN>1 표본비율 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for year in YEARS:
        yr_results = by_year.get(year, [])
        if not yr_results:
            lines.append(f"| {year} | 0 | - | - | - | - | - | - | - |")
            continue
        bs_leaf = bs_ancestor = bs_separate_only = bs_missing = 0
        kgaap = 0
        title_counts = []
        rowspan_flags = []
        for r in yr_results:
            title_counts.append(r["title_count"])
            found = r["found"]
            bs_hits = found.get("BS", []) + found.get("BS_KGAAP", [])
            if not bs_hits:
                # genuinely no BS/대차대조표 TITLE found anywhere in the document
                bs_missing += 1
            else:
                sources = {h["consol_source"] for h in bs_hits}
                if "leaf" in sources:
                    bs_leaf += 1
                elif "ancestor" in sources:
                    bs_ancestor += 1
                else:
                    # found, but every hit is separate/individual (consol_source="none")
                    # — expected for years/filers without a consolidated statement, not a miss
                    bs_separate_only += 1
            if found.get("RETAINED_APPROP"):
                kgaap += 1
            any_rowspan = any(
                stats["rowspan"] > 0
                for stat_list in r["table_stats"].values()
                for stats in stat_list
            )
            rowspan_flags.append(any_rowspan)
        avg_titles = sum(title_counts) / len(title_counts) if title_counts else 0
        rowspan_pct = (
            sum(rowspan_flags) / len(rowspan_flags) * 100 if rowspan_flags else 0
        )
        lines.append(
            f"| {year} | {len(yr_results)} | {bs_leaf} | {bs_ancestor} | {bs_separate_only} | "
            f"{bs_missing} | {kgaap} | {avg_titles:.0f} | {rowspan_pct:.0f}% |"
        )
    lines.append("")
    lines.append(
        "- **BS리프연결**: TITLE 텍스트 자체에 '연결'이 포함된 BS/대차대조표 표본 수"
        "(현재 `section_detector.py` 패턴매칭으로 바로 잡힘)."
    )
    lines.append(
        "- **BS별도만**: BS/대차대조표는 찾았으나 전부 개별(별도) 기준이고 연결 표기가"
        " 리프·상위헤딩 어디에도 없는 표본 수(연결재무제표 의무 대상이 아니었거나 해당"
        " report_type엔 연결이 없는 정상 케이스일 수 있음 — §2에서 개별 확인 필요)."
    )
    lines.append(
        "- **BS미검출**: 표본에서 BS/대차대조표 TITLE 자체를 전혀 못 찾은 진짜 결측 건수."
    )
    lines.append(
        "- **BS조상연결**: '연결' 표기가 리프 TITLE엔 없고 상위 헤딩(예: '4. 연결재무제표')"
        "에만 있는 표본 수(현재 로직이 놓치는 케이스 — 확장 필요 근거)."
    )
    lines.append("")

    lines.append("## 2. 개별 사례 — 조상연결(ancestor-only) 표본")
    lines.append("")
    ancestor_examples = []
    for r in ok:
        bs_hits = r["found"].get("BS", []) + r["found"].get("BS_KGAAP", [])
        for h in bs_hits:
            if h["consol_source"] == "ancestor":
                ancestor_examples.append((r, h))
    if ancestor_examples:
        lines.append("| rcept_no | corp_name | FY | 리프 TITLE | 상위 헤딩 체인 |")
        lines.append("|---|---|---|---|---|")
        for r, h in ancestor_examples[:15]:
            anc = " > ".join(h["ancestors"]) if h["ancestors"] else "(없음)"
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{h['text']} | {anc} |"
            )
    else:
        lines.append("(표본에서 발견되지 않음)")
    lines.append("")

    lines.append("## 2b. 개별 사례 — 별도만 검출(연결 표기 전혀 없음) 표본")
    lines.append("")
    separate_only_examples = []
    for r in ok:
        bs_hits = r["found"].get("BS", []) + r["found"].get("BS_KGAAP", [])
        if bs_hits and all(h["consol_source"] == "none" for h in bs_hits):
            separate_only_examples.append(r)
    if separate_only_examples:
        lines.append(
            f"**{len(separate_only_examples)}/{len(ok)}건**"
            f"({len(separate_only_examples)/len(ok)*100:.1f}%) — report_type/연도 분포 확인용."
        )
        lines.append("")
        lines.append("| rcept_no | corp_name | FY | report_type |")
        lines.append("|---|---|---|---|")
        for r in separate_only_examples[:15]:
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{r['report_type']} |"
            )
    else:
        lines.append("(표본에서 발견되지 않음)")
    lines.append("")

    lines.append("## 3. K-GAAP 전용 표(이익잉여금처분계산서/결손금처리계산서) 출현 사례")
    lines.append("")
    kgaap_examples = [r for r in ok if r["found"].get("RETAINED_APPROP")]
    if kgaap_examples:
        lines.append("| rcept_no | corp_name | FY | report_type | 표제 |")
        lines.append("|---|---|---|---|---|")
        for r in kgaap_examples[:15]:
            titles_txt = "; ".join(
                h["text"] for h in r["found"]["RETAINED_APPROP"]
            )
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{r['report_type']} | {titles_txt} |"
            )
        lines.append("")
        lines.append(
            f"**{len(kgaap_examples)}/{len(ok)}건({len(kgaap_examples)/len(ok)*100:.1f}%)에서 "
            "K-GAAP 전용 표 발견.**"
        )
    else:
        lines.append("(표본에서 발견되지 않음)")
    lines.append("")

    lines.append("## 4. 단위 선언 표기 표본")
    lines.append("")
    unit_samples = []
    for r in ok:
        if r.get("unit_decls"):
            unit_samples.append((r, r["unit_decls"]))
    if unit_samples:
        lines.append("| rcept_no | FY | 발견된 단위 선언 문구 |")
        lines.append("|---|---|---|")
        for r, decls in unit_samples[:15]:
            lines.append(f"| {r['rcept_no']} | {r['fiscal_year']} | {', '.join(decls)} |")
    else:
        lines.append("(정규식 `단위\\s*[:：]\\s*...원` 패턴 표본에서 미검출 — 표기 방식이 "
                      "다르거나 정규식 보강 필요, 개별 확인 요함)")
    lines.append("")

    lines.append("## 5. 표 구조(ROWSPAN/COLSPAN/TU) 표본")
    lines.append("")
    lines.append("| rcept_no | FY | label | tables | rowspan>1 | colspan>1 | TU cells | TD cells |")
    lines.append("|---|---|---|---|---|---|---|---|")
    shown = 0
    for r in ok:
        for label, stat_list in r["table_stats"].items():
            for st in stat_list:
                if shown >= 20:
                    break
                lines.append(
                    f"| {r['rcept_no']} | {r['fiscal_year']} | {label} | {st['tables']} | "
                    f"{st['rowspan']} | {st['colspan']} | {st['tu_cells']} | {st['td_cells']} |"
                )
                shown += 1
    lines.append("")

    lines.append("## 6. 결론 (초안 — 사용자 검토 후 Phase 2 착수)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다. 스크립트는 원자료만 만든다._")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
