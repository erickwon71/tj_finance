"""Phase 1 probe — PDF-only 3차 패스 구조 정밀 실측 (read-only, no DB/report_lines writes).

Stratified sample across fiscal_year x report_type, drawn from the 3,509-filing
PDF-only (no xml/xbrl_zip) active-universe backlog. For each sample, measures:
  - text layer presence (image-scan PDF detection, §1-3 companion for full-population)
  - face section anchor detection (§1-4), reusing fin2/extract/pdf.py's anchor regex
    (title + period-marker) — read-only reuse, no fact_v2 writes.
  - table/number formatting (§1-5): parentheses/hyphen negative notation, column count
  - indentation preservation (§1-6): leading-whitespace / pdfplumber char x0 distribution
    of account-label lines within each detected statement region
  - alternative structure signals (§1-7): font size/bold, numbering-prefix glyphs,
    table-cell bbox padding, line-spacing gaps — candidate depth signals for
    generations where indentation is lost

Output: docs/qa/pdf_only_structure_probe_2026-08-XX.md (raw tables; conclusions
section left for human review, per pre-2015 probe convention).

Companion scripts: probe_pdf_only_text_layer.py (§1-3, full 3,509 population),
probe_pdf_only_amendments.py (§1-9, amendment pair classification).

Read-only: does not touch report_lines/fact_v2 or any production table.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.pdf import (
    _find_anchors, _region_has_anchor_labels, _iter_data_lines,
    _TITLE_RE, _PERIOD_MARK_RE, parse_number,
)

REPORT_TYPES = ["annual", "half", "quarter"]
SAMPLES_PER_STRATUM = 4
SEED = "pdf-only-2026-08-11"

# Numbering-prefix glyphs that might carry depth information (§1-7 candidate b).
_NUMBERING_PREFIX_RE = re.compile(
    r"^\s*(가|나|다|라|마|바|사|아|자|차)\.|"
    r"^\s*[Ⅰ-Ⅹ]\s*[.\)]?|"
    r"^\s*\d+\)|"
    r"^\s*\(\d+\)|"
    r"^\s*[①-⑳]"
)

# Keywords suggesting a subtotal/total row (used for line-spacing signal, §1-7d).
_SUBTOTAL_KW = ["총계", "소계", "합계", "계"]


def sample_stratified(session) -> list[dict]:
    """Distinct (fiscal_year, report_type) strata present in the PDF-only population,
    min(SAMPLES_PER_STRATUM, available) sampled from each via deterministic md5 seed."""
    strata_q = text("""
        WITH filing_types AS (
          SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.filed_at, f.report_type,
                 f.is_final, f.superseded_by,
                 bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml
          FROM filings f
          JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
          JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
          GROUP BY f.rcept_no, f.corp_code, f.fiscal_year, f.filed_at, f.report_type,
                   f.is_final, f.superseded_by
        )
        SELECT DISTINCT fiscal_year, report_type
        FROM filing_types
        WHERE NOT has_xml
          AND EXISTS (
            SELECT 1 FROM download_tasks dt2
            WHERE dt2.rcept_no = filing_types.rcept_no
              AND dt2.file_type = 'pdf' AND dt2.status = 'completed'
          )
        ORDER BY fiscal_year, report_type
    """)
    strata = session.execute(strata_q).all()

    rows = []
    for fy, rtype in strata:
        q = text("""
            WITH filing_types AS (
              SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at,
                     f.report_type, f.is_final, f.superseded_by,
                     bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml
              FROM filings f
              JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
              JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
              WHERE f.fiscal_year = :fy AND f.report_type = :rtype
              GROUP BY f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at,
                       f.report_type, f.is_final, f.superseded_by
            )
            SELECT ft.rcept_no, ft.corp_code, ft.corp_name, ft.fiscal_year, ft.filed_at,
                   ft.report_type, ft.is_final, ft.superseded_by, dt.file_path
            FROM filing_types ft
            JOIN download_tasks dt ON dt.rcept_no = ft.rcept_no
                AND dt.file_type = 'pdf' AND dt.status = 'completed'
            WHERE NOT ft.has_xml
            ORDER BY md5(ft.rcept_no || :seed)
            LIMIT :n
        """)
        res = session.execute(
            q, {"fy": fy, "rtype": rtype, "seed": SEED, "n": SAMPLES_PER_STRATUM}
        ).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def era_of(fy: int) -> str:
    if fy is None:
        return "unknown"
    if fy < 2015:
        return "pre2015"
    if fy <= 2019:
        return "2015-2019"
    return "2020+"


def is_text_based(pdf, sample_pages: int = 5) -> tuple[bool, float]:
    total, checked = 0, 0
    for page in list(pdf.pages)[:sample_pages]:
        try:
            t = page.extract_text() or ""
            total += len(t)
            checked += 1
        except Exception:
            continue
    if checked == 0:
        return False, 0.0
    avg = total / checked
    return avg >= 50, avg


def build_line_records(pdf, region_start_page: int, region_end_page: int) -> list[dict]:
    """Char-level line reconstruction (x0/top/font) for pages spanning a statement
    region, used for indentation (§1-6) and font/spacing signals (§1-7)."""
    lines = []
    for pi in range(region_start_page, min(region_end_page + 1, len(pdf.pages))):
        page = pdf.pages[pi]
        try:
            chars = page.chars
        except Exception:
            continue
        if not chars:
            continue
        # group chars into lines by rounded 'top'
        by_top = defaultdict(list)
        for ch in chars:
            by_top[round(ch["top"])].append(ch)
        for top, chs in sorted(by_top.items()):
            chs.sort(key=lambda c: c["x0"])
            txt = "".join(c["text"] for c in chs)
            if not txt.strip():
                continue
            lines.append({
                "page": pi, "top": top, "x0": chs[0]["x0"], "text": txt,
                "size": chs[0].get("size"), "fontname": chs[0].get("fontname", ""),
            })
    return lines


def probe_file(sample: dict) -> dict:
    path = Path(sample["file_path"])
    result = {**sample, "era": era_of(sample["fiscal_year"]), "error": None}
    if not path.exists():
        result["error"] = "file_missing"
        return result

    try:
        import pdfplumber
    except ImportError:
        result["error"] = "pdfplumber_missing"
        return result

    try:
        with pdfplumber.open(path) as pdf:
            text_based, avg_chars = is_text_based(pdf)
            result["text_based"] = text_based
            result["avg_chars_first5"] = round(avg_chars, 1)
            result["page_count"] = len(pdf.pages)
            if not text_based:
                result["image_scan"] = True
                return result
            result["image_scan"] = False

            # full text (page-joined) for anchor detection
            page_texts = []
            for pg in pdf.pages:
                try:
                    page_texts.append(pg.extract_text() or "")
                except Exception:
                    page_texts.append("")
            full_text = "\f".join(page_texts)

            # candidate title occurrences (with/without period marker) — §1-4 failure catalog
            title_hits = list(_TITLE_RE.finditer(full_text))
            result["title_hits_total"] = len(title_hits)
            anchors = _find_anchors(full_text)
            result["anchors_total"] = len(anchors)
            result["anchors_no_period_marker"] = len(title_hits) - len(anchors)

            found_stmts = {}
            region_page_ranges = {}
            for i, anc in enumerate(anchors):
                if anc.statement == "SCE":
                    continue
                end = anchors[i + 1].start if i + 1 < len(anchors) else len(full_text)
                region = full_text[anc.start:end]
                has_labels = _region_has_anchor_labels(region, anc.statement)
                key = f"{anc.statement}_{anc.basis[:3]}"
                found_stmts.setdefault(key, []).append(has_labels)
                if has_labels:
                    # map char offsets back to page indices via \f boundaries
                    start_page = full_text.count("\f", 0, anc.start)
                    end_page = full_text.count("\f", 0, end)
                    region_page_ranges.setdefault(key, []).append(
                        (start_page, end_page, region)
                    )
            result["found_stmts"] = {
                k: {"count": len(v), "labeled": sum(v)} for k, v in found_stmts.items()
            }

            # number formatting (§1-5): parentheses vs hyphen vs minus for negatives
            neg_paren = len(re.findall(r"\([\d,]+\)", full_text))
            neg_triangle = len(re.findall(r"[△▲][\d,]+", full_text))
            neg_minus = len(re.findall(r"(?<![0-9])-[\d,]+", full_text))
            blank_hyphen = len(re.findall(r"(?<=\s)-(?=\s|$)", full_text[:20000]))
            result["numfmt"] = {
                "paren_neg": neg_paren, "triangle_neg": neg_triangle,
                "minus_neg": neg_minus, "blank_hyphen_sample": blank_hyphen,
            }

            # indentation / alt-signal probe on the first labeled BS-ish region found
            probe_key = None
            for k in ("BS_con", "BS_sep"):
                if k in region_page_ranges:
                    probe_key = k
                    break
            if probe_key is None and region_page_ranges:
                probe_key = next(iter(region_page_ranges))

            indent_info = {"probed": False}
            if probe_key:
                sp, ep, region_text = region_page_ranges[probe_key][0]
                lines = build_line_records(pdf, sp, ep)
                label_lines = []
                for ln in lines:
                    t = ln["text"].strip()
                    if not t or not re.search(r"[가-힣]", t):
                        continue
                    if not re.search(r"[0-9]", t):
                        continue
                    label_lines.append(ln)
                if label_lines:
                    x0s = [round(ln["x0"], 1) for ln in label_lines]
                    # cluster x0 to nearest 3pt bucket as a depth-level proxy
                    clusters = sorted({round(x / 3) * 3 for x in x0s})
                    sizes = Counter(round(ln["size"], 1) for ln in label_lines if ln["size"])
                    bold_flags = [
                        ("bold" in ln["fontname"].lower() or "Bold" in ln["fontname"])
                        for ln in label_lines
                    ]
                    prefix_hits = sum(
                        1 for ln in label_lines if _NUMBERING_PREFIX_RE.match(ln["text"])
                    )
                    tops = sorted(ln["top"] for ln in label_lines)
                    gaps = [round(b - a, 1) for a, b in zip(tops, tops[1:])]
                    subtotal_lines = [
                        ln for ln in label_lines
                        if any(kw in ln["text"] for kw in _SUBTOTAL_KW)
                    ]
                    indent_info = {
                        "probed": True,
                        "n_label_lines": len(label_lines),
                        "x0_distinct_clusters": len(clusters),
                        "x0_clusters": clusters[:10],
                        "font_sizes": dict(sizes.most_common(5)),
                        "bold_ratio": round(sum(bold_flags) / len(bold_flags), 2) if bold_flags else 0,
                        "numbering_prefix_hits": prefix_hits,
                        "n_subtotal_lines": len(subtotal_lines),
                        "gap_median": sorted(gaps)[len(gaps) // 2] if gaps else None,
                        "sample_lines": [ln["text"][:40] for ln in label_lines[:8]],
                    }
            result["indent_probe_key"] = probe_key
            result["indent"] = indent_info

    except Exception as e:
        result["error"] = f"exception:{type(e).__name__}:{e}"

    return result


def main() -> None:
    with get_session() as session:
        samples = sample_stratified(session)

    print(f"sampled {len(samples)} filings across strata")
    results = []
    for i, s in enumerate(samples):
        r = probe_file(s)
        results.append(r)
        if (i + 1) % 25 == 0:
            print(f"  probed {i + 1}/{len(samples)}")

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pdf_only_structure_probe_2026-08-11.md")
    n = len(results)
    errors = [r for r in results if r.get("error")]
    image_scan = [r for r in results if r.get("image_scan")]
    ok = [r for r in results if not r.get("error") and not r.get("image_scan")]

    lines = []
    lines.append("# Phase 1 — PDF-only 구조 정밀 실측 결과 (2026-08-11)")
    lines.append("")
    lines.append(
        "> 계획서 = [`pdf_only_parser_plan_2026-08-11.md`](../plans/"
        "pdf_only_parser_plan_2026-08-11.md) Phase 1. 체크리스트 = "
        "[`pdf_only_parser_todo_2026-08-11.md`](../plans/pdf_only_parser_todo_2026-08-11.md). "
        "실행 스크립트 = `scripts/probe_pdf_only_structure.py`(읽기 전용, DB/report_lines 미변경). "
        "층화표본 = (fiscal_year × report_type) 조합별 최대 4건."
    )
    lines.append("")
    lines.append(
        f"**표본 {n}건 · 텍스트 기반(측정 대상) {len(ok)}건 · 이미지 스캔(추정) "
        f"{len(image_scan)}건 · 오류 {len(errors)}건**"
    )
    lines.append("")

    if errors:
        lines.append("## 0. 오류 표본")
        lines.append("")
        lines.append("| rcept_no | corp_name | FY | report_type | error |")
        lines.append("|---|---|---|---|---|")
        for r in errors:
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{r['report_type']} | {r['error']} |"
            )
        lines.append("")

    # §1-3 mini (sample-level only — full population covered by companion script)
    lines.append("## 1. 텍스트 레이어(표본 수준 — 전수는 별도 스크립트) ")
    lines.append("")
    lines.append("| era | 표본 | 텍스트기반 | 이미지스캔추정 | avg_chars(첫5p) 중앙값 |")
    lines.append("|---|---|---|---|---|")
    by_era = defaultdict(list)
    for r in results:
        if not r.get("error"):
            by_era[r["era"]].append(r)
    for era in ("pre2015", "2015-2019", "2020+"):
        rs = by_era.get(era, [])
        if not rs:
            continue
        tb = [r for r in rs if r.get("text_based")]
        isc = [r for r in rs if r.get("image_scan")]
        avgs = sorted(r["avg_chars_first5"] for r in rs if "avg_chars_first5" in r)
        med = avgs[len(avgs) // 2] if avgs else "-"
        lines.append(f"| {era} | {len(rs)} | {len(tb)} | {len(isc)} | {med} |")
    lines.append("")

    # §1-4 anchor detection
    lines.append("## 2. Face 섹션 앵커 탐지 (§1-4)")
    lines.append("")
    lines.append("| era | 표본 | title_hits합 | anchor채택합 | 기간마커없어제외 | BS라벨확인 | IS라벨확인 | CF라벨확인 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for era in ("pre2015", "2015-2019", "2020+"):
        rs = [r for r in by_era.get(era, []) if not r.get("image_scan")]
        if not rs:
            continue
        th = sum(r.get("title_hits_total", 0) for r in rs)
        at = sum(r.get("anchors_total", 0) for r in rs)
        npm = sum(r.get("anchors_no_period_marker", 0) for r in rs)
        def labeled_count(stmt_prefix):
            c = 0
            for r in rs:
                fs = r.get("found_stmts", {})
                if any(fs[k]["labeled"] > 0 for k in fs if k.startswith(stmt_prefix)):
                    c += 1
            return c
        bs = labeled_count("BS")
        is_ = labeled_count("IS")
        cf = labeled_count("CF")
        lines.append(f"| {era} | {len(rs)} | {th} | {at} | {npm} | {bs} | {is_} | {cf} |")
    lines.append("")
    lines.append(
        "- **anchor채택합**: 제목+기간마커(`제 N 기`) 조합으로 채택된 앵커 수(합계). "
        "**기간마커없어제외**: 제목 텍스트는 매치됐으나 직후 50자 내 기간마커가 없어 "
        "목차/주석 언급으로 배제된 건수 — 이 값이 크면 목차 오인식 위험 큼."
    )
    lines.append(
        "- BS/IS/CF 라벨확인 = 앵커 채택 + 해당 statement 앵커 라벨(자산총계 등 2개 이상)"
        "까지 확인된 **표본 파일 수**(건수 아님)."
    )
    lines.append("")

    lines.append("### 2b. 표본 전체 없이 표(라벨 미확인) — 실패 사례")
    lines.append("")
    no_bs = [
        r for r in ok
        if not any(k.startswith("BS") and r["found_stmts"][k]["labeled"] > 0
                    for k in r.get("found_stmts", {}))
    ]
    if no_bs:
        lines.append(
            f"**{len(no_bs)}/{len(ok)}건({len(no_bs)/len(ok)*100:.1f}%)**에서 BS 라벨 미확인."
        )
        lines.append("")
        lines.append("| rcept_no | corp_name | FY | report_type | title_hits | anchors | found_stmts |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in no_bs[:20]:
            lines.append(
                f"| {r['rcept_no']} | {r['corp_name']} | {r['fiscal_year']} | "
                f"{r['report_type']} | {r.get('title_hits_total')} | {r.get('anchors_total')} | "
                f"{r.get('found_stmts')} |"
            )
    else:
        lines.append("(표본에서 발견되지 않음 — 전 표본 BS 라벨 확인됨)")
    lines.append("")

    # §1-5 number formatting
    lines.append("## 3. 표(계정명+금액) 텍스트/숫자 표기 실측 (§1-5)")
    lines.append("")
    lines.append("| era | 표본 | 괄호음수 합 | △▲음수 합 | 마이너스음수 합 |")
    lines.append("|---|---|---|---|---|")
    for era in ("pre2015", "2015-2019", "2020+"):
        rs = [r for r in by_era.get(era, []) if not r.get("image_scan") and r.get("numfmt")]
        if not rs:
            continue
        p = sum(r["numfmt"]["paren_neg"] for r in rs)
        t = sum(r["numfmt"]["triangle_neg"] for r in rs)
        m = sum(r["numfmt"]["minus_neg"] for r in rs)
        lines.append(f"| {era} | {len(rs)} | {p} | {t} | {m} |")
    lines.append("")

    # §1-6/1-7 indentation + alt signals
    lines.append("## 4. 들여쓰기/구조 보존 실측 (§1-6) + 대체 신호 (§1-7)")
    lines.append("")
    probed = [r for r in ok if r.get("indent", {}).get("probed")]
    lines.append(f"**들여쓰기 probe 성공 {len(probed)}/{len(ok)}건**")
    lines.append("")
    lines.append(
        "| rcept_no | FY | era | probe대상 | 라벨행수 | x0클러스터수 | bold비율 | "
        "번호매김prefix건수 | 소계행수 | gap중앙값 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in probed:
        ind = r["indent"]
        lines.append(
            f"| {r['rcept_no']} | {r['fiscal_year']} | {r['era']} | {r['indent_probe_key']} | "
            f"{ind['n_label_lines']} | {ind['x0_distinct_clusters']} | {ind['bold_ratio']} | "
            f"{ind['numbering_prefix_hits']} | {ind['n_subtotal_lines']} | {ind['gap_median']} |"
        )
    lines.append("")
    lines.append(
        "- **x0클러스터수**: 라벨 라인 선행 x0 좌표를 3pt 단위로 클러스터링한 서로 다른 "
        "값 개수 — 1이면 들여쓰기 신호 없음(전부 동일 좌표), 2 이상이면 계층 구분 후보."
    )
    lines.append(
        "- **번호매김prefix건수**: 라벨이 '가./나.', '1)/2)', 'Ⅰ./Ⅱ.' 등으로 시작하는 행 수 "
        "— 대체 신호(§1-7b) 후보 검출."
    )
    lines.append("")

    lines.append("### 4b. era별 x0 클러스터 분포 요약")
    lines.append("")
    lines.append("| era | probe건수 | 클러스터수=1(들여쓰기없음) | 클러스터수>=2 | 평균 클러스터수 |")
    lines.append("|---|---|---|---|---|")
    for era in ("pre2015", "2015-2019", "2020+"):
        rs = [r for r in probed if r["era"] == era]
        if not rs:
            continue
        cl = [r["indent"]["x0_distinct_clusters"] for r in rs]
        one = sum(1 for c in cl if c <= 1)
        multi = sum(1 for c in cl if c >= 2)
        avg = sum(cl) / len(cl) if cl else 0
        lines.append(f"| {era} | {len(rs)} | {one} | {multi} | {avg:.1f} |")
    lines.append("")

    lines.append("## 5. 정정(is_final) 표본 분포")
    lines.append("")
    amend = [r for r in results if r.get("is_final") is False]
    lines.append(f"층화표본 중 is_final=False(정정 전 원본): {len(amend)}/{n}건 "
                  "— 전수 실측은 별도 스크립트(§1-9) 참고.")
    lines.append("")

    lines.append("## 6. 결론 (초안 — 사용자 검토 후 Phase 2 착수)")
    lines.append("")
    lines.append("_이 절은 위 표 결과를 보고 사람이 채운다. 스크립트는 원자료만 만든다._")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
