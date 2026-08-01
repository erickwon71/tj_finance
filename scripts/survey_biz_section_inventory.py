"""Inventory census of the 'II. 사업의 내용' tables — starts from the source documents (READ-ONLY).

Why
---
Only three extractors read this section today (biz_section = capacity/output/utilization,
sales_section = segment and export/domestic sales, order_backlog = orders). Choosing the
items to load by looking at Samsung Electronics alone would miss the core tables of other
industries entirely (financial-sector managed assets, pharma pipelines, construction backlog,
regional game revenue, ...). This tool inverts the direction: it **starts from the document**,
counts every table in the section per subsection, and aggregates what actually exists by
industry.

What this proves / does not prove
---------------------------------
  proven     : measured frequency (in the sample) of subsections, table captions and table
               shapes (rows/cols/numeric cells)
  proven     : whether a caption matches the keywords of the three existing extractors
               (decided with keywords read out of their code)
  NOT proven : whether a matching caption actually resulted in DB rows — that belongs to
               audit_document_census.py

Usage
-----
    python scripts/survey_biz_section_inventory.py --per-industry 3 --limit 60
    python scripts/survey_biz_section_inventory.py --per-industry 8 --limit 500 \
        --out docs/qa/biz_section_inventory.md --json scratchpad/biz_inv.json
    python scripts/survey_biz_section_inventory.py --rcept 20250311001085   # single-filing drill
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import _load_root, _tag, _text, _direct_trs
from parser.xml.section_detector import normalize_dart_section_title
from parser.xml.table_extractor import _get_cells

# Top-level TOC entries (Roman-numeral prefix) mark the end of the section.
_ROMAN_PREFIX_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|[IVX]{1,5})\s*[.．)]\s*")
_SEC_BIZ = "사업의내용"

# Subsection headings of the section (the 7 from the 2022 form revision plus legacy and
# financial-sector variants). Only a fallback signal for continuing the section in documents
# without Roman-numeral prefixes — never used as a classification key.
_BIZ_SUBSECTIONS = frozenset({
    "사업의개요", "주요제품및서비스", "원재료및생산설비", "매출및수주상황",
    "위험관리및파생거래", "주요계약및연구개발활동", "기타참고사항",
    "영업의현황", "영업설비", "재무건전성등기타참고사항",
    "생산설비(연구설비)에관한사항(상세)", "지적재산권현황(상세)",
})

# Caption normalization — strip leading numbering (가. / 1) / (1) / ① / 나-1.) and trailing extras.
_CAP_NUM_RE = re.compile(
    r"^\s*(?:[\(（]?\s*(?:\d+|[가-힣]|[ⅰ-ⅹ]+|[a-zA-Z])\s*[-–]?\s*\d*\s*[\)）.．]|[①-⑳㉠-㉿▶◆■○●※-])\s*")
_CAP_TAIL_RE = re.compile(r"[\(（]\s*(?:단위|기준일?|연결|별도)[^)）]*[\)）]\s*$")
_NUMERIC_CELL_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?%?$")

_CAPTION_MAX = 42       # max caption-candidate length (to tell it from a narrative paragraph)
_CAPTION_LOOKBACK = 4   # how many preceding paragraphs stay eligible as a caption

# Heading keywords the three existing extractors actually use (read from their code, not guessed).
_CONSUMED_KW = {
    "biz_section(생산)":  ("생산능력", "생산실적", "가동률", "생산및설비"),
    "sales_section(매출)": ("매출실적", "판매실적", "매출현황"),
    "order_backlog(수주)": ("수주상황", "수주잔고", "수주총액"),
    "rd_note(연구개발)":   ("연구개발비용", "연구개발실적", "연구개발활동"),
}

TARGETS_SQL = """
    SELECT DISTINCT ON (f.corp_code)
           f.corp_code, c.corp_name, c.market, c.induty_code,
           f.fiscal_year, f.rcept_no, d.file_path
    FROM filings f
    JOIN download_tasks d USING (rcept_no)
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE d.status = 'completed' AND d.file_type = 'xml' AND d.file_path IS NOT NULL
      AND f.fiscal_period = 'FY' AND c.is_active AND c.stock_code IS NOT NULL
      AND f.fiscal_year >= :min_year
    ORDER BY f.corp_code, f.fiscal_year DESC
"""

# KSIC 2-digit -> display name (readability only; unknown codes are shown as the raw code).
_IND2: dict[str, str] = {
    "10": "식료품", "11": "음료", "13": "섬유", "14": "의복", "17": "펄프·종이",
    "18": "인쇄", "19": "석유정제", "20": "화학", "21": "의약품", "22": "고무·플라스틱",
    "23": "비금속광물", "24": "1차금속", "25": "금속가공", "26": "전자·반도체·부품",
    "27": "의료·정밀·광학", "28": "전기장비", "29": "기계·장비", "30": "자동차·운송장비",
    "31": "기타운송장비", "32": "가구·기타제조", "33": "기타제품", "35": "전기·가스",
    "41": "종합건설", "42": "전문건설", "45": "자동차판매", "46": "도매·중개",
    "47": "소매", "49": "육상운송", "50": "수상운송", "51": "항공운송", "52": "창고·운송지원",
    "55": "숙박", "56": "음식점", "58": "출판(SW 포함)", "59": "영상·음악",
    "61": "통신", "62": "컴퓨터프로그래밍·SI", "63": "정보서비스", "64": "금융업",
    "65": "보험업", "66": "금융지원서비스(증권 등)", "68": "부동산", "70": "연구개발",
    "71": "전문서비스", "72": "건축기술·엔지니어링", "73": "기타 과학기술",
    "74": "사업지원", "85": "교육", "86": "보건업", "90": "예술·스포츠",
}


def ind_label(code: str | None) -> str:
    if not code:
        return "(업종미상)"
    k = code[:2]
    return f"{k} {_IND2.get(k, '기타')}"


def normalize_caption(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:                      # nested numbering such as '가. (1) 주요 제품'
        prev = s
        s = _CAP_NUM_RE.sub("", s).strip()
    s = _CAP_TAIL_RE.sub("", s).strip()
    return re.sub(r"\s+", "", s)[:40]


def table_shape(tbl) -> tuple[int, int, int]:
    """(rows, max cols, numeric cells). Rows of nested TABLEs are excluded (broken-source defense)."""
    rows = _direct_trs(tbl)
    ncol = 0
    nnum = 0
    for tr in rows:
        cells = _get_cells(tr)
        ncol = max(ncol, len(cells))
        for c in cells:
            t = c.strip().replace(" ", "").replace("　", "")
            if t and _NUMERIC_CELL_RE.match(t) and any(ch.isdigit() for ch in t):
                nnum += 1
    return len(rows), ncol, nnum


def is_text_block(nrow: int, ncol: int, nnum: int) -> bool:
    """Is this a layout table wrapping a narrative paragraph (not a real data table)?"""
    return nnum == 0 and nrow <= 2 and ncol <= 2


def consumed_by(caption: str) -> str | None:
    flat = caption.replace(" ", "")
    for owner, kws in _CONSUMED_KW.items():
        if any(k in flat for k in kws):
            return owner
    return None


def scan_biz_section(root) -> tuple[list[dict], dict[str, int]]:
    """Table inventory of the section plus prose length per subsection.

    Section boundaries are decided by **document order** — DART's SECTION-2 elements are
    cascaded rather than siblings, so containment (`.//`) cannot delimit them (same measured
    rationale as section_detector). A TITLE with a Roman-numeral prefix is treated as a
    top-level TOC entry: the section opens at '사업의내용' and closes at the next top-level
    TITLE. Legacy forms without Roman numerals are continued via the known subsection headings.
    """
    tables: list[dict] = []
    prose: dict[str, int] = defaultdict(int)
    in_biz = False
    subsection = "(소제목없음)"
    recent: list[str] = []          # buffer of paragraphs preceding a table (caption candidates)
    leaf_stack: list[bool] = []     # whether each currently open TABLE is a leaf (data table)
    leaf_depth = 0

    for ev, el in etree.iterwalk(root, events=("start", "end")):
        tag = _tag(el)
        if ev == "end":
            if tag == "TABLE" and leaf_stack:
                leaf_depth -= 1 if leaf_stack.pop() else 0
            continue

        if tag == "TABLE":
            # Do NOT decide 'top-level table' by TABLE nesting depth — a missing </TABLE>
            # is common in DART sources and can put the **entire** document inside one table
            # (measured, KT&G 20260318001422: the 'II. 사업의 내용' TITLE itself sits at
            # depth=1). So only tables with no descendant TABLE (leaves) count as data
            # tables; wrappers pass through uncounted so their <P> can serve as captions.
            it = el.iter("TABLE")
            next(it, None)                        # itself
            is_leaf = next(it, None) is None
            leaf_stack.append(is_leaf)
            if not is_leaf:
                continue
            leaf_depth += 1
            if in_biz and leaf_depth == 1:
                nrow, ncol, nnum = table_shape(el)
                if is_text_block(nrow, ncol, nnum):
                    # DART commonly wraps narrative paragraphs in 1x1 TABLEs (measured,
                    # Samsung Electronics 2024: half of the 85 apparent tables are such text
                    # wrappers). Counting them inflates the inventory and, worse, **steals the
                    # caption of the real table that follows**. Push the wrapper's <P> text
                    # into the caption-candidate buffer instead.
                    for p in el.iter("P"):
                        t = re.sub(r"\s+", " ", _text(p)).strip()
                        if t:
                            prose[subsection] += len(t)
                            recent.append(t)
                    del recent[:-_CAPTION_LOOKBACK]
                    continue
                cap = ""
                for cand in reversed(recent):    # 가장 가까운 '짧은' 문단을 캡션으로
                    if len(cand) <= _CAPTION_MAX:
                        cap = cand
                        break
                if not cap and recent:
                    cap = recent[-1][:_CAPTION_MAX]
                tables.append({"subsection": subsection, "caption_raw": cap,
                               "caption": normalize_caption(cap),
                               "rows": nrow, "cols": ncol, "num_cells": nnum})
                recent.clear()
            continue

        if leaf_depth:                           # 데이터 표 안쪽 텍스트는 캡션 후보가 아니다
            continue

        if tag == "TITLE":
            raw = re.sub(r"\s+", " ", _text(el)).strip()
            norm = normalize_dart_section_title(raw)
            is_top = bool(_ROMAN_PREFIX_RE.match(raw))
            if norm == _SEC_BIZ:
                in_biz, subsection = True, "(소제목없음)"
            elif in_biz and is_top:
                in_biz = False                   # 다음 최상위 목차 → 구간 종료
            elif in_biz:
                subsection = norm or subsection
            recent.clear()
        elif tag == "P" and in_biz:
            t = re.sub(r"\s+", " ", _text(el)).strip()
            if t:
                prose[subsection] += len(t)
                recent.append(t)
                del recent[:-_CAPTION_LOOKBACK]

    return tables, dict(prose)


def pick_targets(session, args) -> list[dict]:
    rows = [dict(r._mapping) for r in session.execute(
        text(TARGETS_SQL), {"min_year": args.min_year}).fetchall()]
    by_ind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ind[(r["induty_code"] or "??")[:2]].append(r)
    rnd = random.Random(args.seed)
    picked: list[dict] = []
    for ind in sorted(by_ind):
        pool = by_ind[ind]
        rnd.shuffle(pool)
        picked += pool[: args.per_industry]
    rnd.shuffle(picked)
    return picked[: args.limit] if args.limit else picked


def drill(session, rcept_no: str) -> int:
    row = session.execute(text(
        "SELECT d.file_path FROM download_tasks d WHERE d.rcept_no=:r "
        "AND d.file_type='xml' AND d.file_path IS NOT NULL LIMIT 1"), {"r": rcept_no}).fetchone()
    if not row:
        print(f"{rcept_no}: 원본 없음")
        return 1
    root = _load_root(Path(row.file_path))
    if root is None:
        print(f"{rcept_no}: 파싱 실패")
        return 1
    tables, prose = scan_biz_section(root)
    print(f"=== {rcept_no} · 사업의 내용 표 {len(tables)}개 ===")
    cur = None
    for t in tables:
        if t["subsection"] != cur:
            cur = t["subsection"]
            print(f"\n[{cur}]  본문 {prose.get(cur, 0):,}자")
        owner = consumed_by(t["caption"]) or "—"
        print(f"  {t['caption_raw'][:46]:<48} {t['rows']:>3}x{t['cols']:<3} "
              f"숫자{t['num_cells']:>5}  {owner}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-industry", type=int, default=3, help="업종(KSIC 2자리)당 표본 수")
    ap.add_argument("--limit", type=int, default=0, help="전체 상한(0=제한없음)")
    ap.add_argument("--min-year", type=int, default=2023)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rcept", help="단건 드릴")
    ap.add_argument("--out", help="마크다운 리포트 경로")
    ap.add_argument("--json", help="원자료 JSON 경로(후속 드릴용)")
    args = ap.parse_args()

    with get_session() as s:
        if args.rcept:
            return drill(s, args.rcept)
        targets = pick_targets(s, args)

    print(f"표본 {len(targets)}사 스캔 시작…", flush=True)
    t0 = time.time()
    records: list[dict] = []
    failed: list[str] = []
    no_biz: list[str] = []
    for i, tgt in enumerate(targets, 1):
        p = Path(tgt["file_path"])
        if not p.exists():
            failed.append(f"{tgt['corp_name']}(파일없음)")
            continue
        try:
            root = _load_root(p)
        except Exception as e:                                    # noqa: BLE001
            failed.append(f"{tgt['corp_name']}({type(e).__name__})")
            continue
        if root is None:
            failed.append(f"{tgt['corp_name']}(파싱실패)")
            continue
        tables, prose = scan_biz_section(root)
        if not tables:
            no_biz.append(f"{tgt['corp_name']}/{tgt['rcept_no']}")
        records.append({**{k: tgt[k] for k in
                           ("corp_code", "corp_name", "market", "induty_code",
                            "fiscal_year", "rcept_no")},
                        "tables": tables, "prose": prose})
        if i % 20 == 0:
            print(f"  {i}/{len(targets)} ({time.time()-t0:.0f}s)", flush=True)

    report = build_report(records, failed, no_biz, time.time() - t0)
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n[report] {args.out}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        print(f"[json]   {args.json}")
    return 0


def build_report(records: list[dict], failed: list[str], no_biz: list[str],
                 elapsed: float) -> str:
    L: list[str] = []
    n = len(records)
    L.append("# '사업의 내용' 표 인벤토리 (원문 census, READ-ONLY)\n")
    L.append(f"- 표본 {n}사 · 소요 {elapsed/60:.1f}분 · 파싱실패 {len(failed)}건 "
             f"· 사업의내용 구간 미검출 {len(no_biz)}사\n")
    total_tables = sum(len(r["tables"]) for r in records)
    L.append(f"- 사업의 내용 표 총 {total_tables:,}개 (기업당 평균 {total_tables/max(n,1):.1f}개)\n")

    # (1) By subsection
    sub_tbl: Counter = Counter()
    sub_corp: dict[str, set] = defaultdict(set)
    sub_prose: Counter = Counter()
    for r in records:
        for t in r["tables"]:
            sub_tbl[t["subsection"]] += 1
            sub_corp[t["subsection"]].add(r["corp_code"])
        for k, v in r["prose"].items():
            sub_prose[k] += v
    L.append("\n## ① 소제목별 표/본문 분포\n")
    L.append("| 소제목 | 표 | 기업수 | 커버율 | 본문 글자수(합) |")
    L.append("|---|---:|---:|---:|---:|")
    for sub, cnt in sub_tbl.most_common(25):
        L.append(f"| {sub} | {cnt:,} | {len(sub_corp[sub])} | "
                 f"{len(sub_corp[sub])/max(n,1)*100:.0f}% | {sub_prose[sub]:,} |")

    # (2) Caption clusters (overall)
    cap_corp: dict[str, set] = defaultdict(set)
    cap_cnt: Counter = Counter()
    cap_num: Counter = Counter()
    cap_example: dict[str, str] = {}
    for r in records:
        for t in r["tables"]:
            c = t["caption"] or "(캡션없음)"
            cap_cnt[c] += 1
            cap_num[c] += t["num_cells"]
            cap_corp[c].add(r["corp_code"])
            cap_example.setdefault(c, f"{r['corp_name']} {t['caption_raw'][:36]}")
    L.append("\n## ② 표 캡션 상위 80 (기업 커버리지 순)\n")
    L.append("| 캡션(정규화) | 기업수 | 커버율 | 표 | 숫자셀 | 기존추출기 | 예시 |")
    L.append("|---|---:|---:|---:|---:|---|---|")
    for c, corps in sorted(cap_corp.items(), key=lambda x: -len(x[1]))[:80]:
        L.append(f"| {c} | {len(corps)} | {len(corps)/max(n,1)*100:.0f}% | {cap_cnt[c]:,} | "
                 f"{cap_num[c]:,} | {consumed_by(c) or '—'} | {cap_example[c]} |")

    # (3) Captions with no consumer (no extractor), ordered by numeric-cell count
    L.append("\n## ③ 추출기 없는 캡션 TOP 60 (숫자셀 기준)\n")
    L.append("| 캡션 | 기업수 | 표 | 숫자셀 | 예시 |")
    L.append("|---|---:|---:|---:|---|")
    unc = [(c, v) for c, v in cap_num.items() if not consumed_by(c) and c != "(캡션없음)"]
    for c, v in sorted(unc, key=lambda x: -x[1])[:60]:
        L.append(f"| {c} | {len(cap_corp[c])} | {cap_cnt[c]:,} | {v:,} | {cap_example[c]} |")

    # (4) Industry-characteristic captions — coverage in that industry well above overall
    L.append("\n## ④ 업종별 특징 캡션 (해당 업종 커버율 ≥40% & 전체 대비 2배↑)\n")
    by_ind: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_ind[ind_label(r["induty_code"])].append(r)
    overall = {c: len(v) / max(n, 1) for c, v in cap_corp.items()}
    for ind in sorted(by_ind, key=lambda k: -len(by_ind[k])):
        grp = by_ind[ind]
        if len(grp) < 3:
            continue
        icap: dict[str, set] = defaultdict(set)
        for r in grp:
            for t in r["tables"]:
                icap[t["caption"] or "(캡션없음)"].add(r["corp_code"])
        hits = [(c, len(v) / len(grp)) for c, v in icap.items()
                if c != "(캡션없음)" and len(v) / len(grp) >= 0.4
                and len(v) / len(grp) >= 2 * overall.get(c, 0)]
        if not hits:
            continue
        L.append(f"\n**{ind}** (n={len(grp)}: "
                 f"{', '.join(r['corp_name'] for r in grp[:6])}{'…' if len(grp) > 6 else ''})\n")
        L.append("| 캡션 | 업종 커버율 | 전체 커버율 |")
        L.append("|---|---:|---:|")
        for c, rate in sorted(hits, key=lambda x: -x[1])[:12]:
            L.append(f"| {c} | {rate*100:.0f}% | {overall.get(c,0)*100:.0f}% |")

    if failed:
        L.append(f"\n## 파싱 실패 {len(failed)}건\n\n" + ", ".join(failed[:40]))
    if no_biz:
        L.append(f"\n## 사업의내용 구간 미검출 {len(no_biz)}사\n\n" + ", ".join(no_biz[:40]))
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
