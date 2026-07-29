"""XML 정규화(이스케이프 복구)의 추출 영향 측정 (READ-ONLY, DB 미변경).

배경
----
DART 원문 XML 은 특수문자를 이스케이프하지 않는다:
    <대표이사 등의 확인>   → 파서가 '대표이사' 를 태그 시작으로 오인
    <당기말                → 태그 mismatch
    A&B                    → EntityRef 오류
실측: FY2024 표본 200/200(100%) 에 태그 깨짐이 있고, 150 중 70(46.7%) 에서 실제 구조 손상
(고아 TR — TABLE 밖에 떠 있는 표 행)이 발생한다. 성일하이텍은 이 손상으로 주석 22번 이후가
트리에서 통째로 사라졌다.

이 스크립트는 **파이프라인을 바꾸지 않고** 정규화 전/후 추출 결과를 비교해
"고치면 무엇이 달라지는가"를 수치로 보여준다. 전량 재적재 여부를 판단하기 위한 것.

비교 지표
--------
  · 파싱 오류 수 / 고아 TR 수
  · 추출 행 수 (본문 report_lines / 주석 note_lines)
  · **셀 단위 diff**: (statement, basis, section_path, label_raw, col_index, value) 집합의
    추가/삭제/변경. 값이 바뀌는지가 핵심 — 늘기만 하면 순수 복구, 바뀌면 검증 필요.

Usage
-----
    python scripts/layer2_xml_sanitize_impact.py --limit 40
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

# 엔티티가 아닌 '&' → &amp;   (&amp; &#123; &#x1F; 는 보존)
_BAD_AMP = re.compile(
    rb"&(?!(?:[a-zA-Z][a-zA-Z0-9]{1,7}|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});)"
)
# ★'<' 뒤 ASCII 여부로는 부족하다 — '<Recycling Park>' 같은 영문 텍스트도 태그로 오인된다.
#   실측: 60개 파일에서 lxml 이 만들어낸 '태그' 282종 중 실제 DART 태그는 40여 종뿐이고
#   나머지는 '<당기말>' '<파묘>' '<범죄도시2>' 같은 본문 텍스트였다.
#   그래서 **관측된 DART 태그 화이트리스트**에 없으면 전부 이스케이프한다.
#   (실제 태그를 잘못 이스케이프하는 쪽이 더 위험하므로 관측된 ASCII 태그는 모두 포함)
_DART_TAGS = (
    "DOCUMENT DOCUMENT-NAME COMPANY-NAME FORMULA-VERSION COVER COVER-TITLE BODY "
    "LIBRARY SUMMARY SECTION-1 SECTION-2 SECTION-3 TITLE P SPAN TABLE TABLE-GROUP "
    "THEAD TBODY TR TD TH TE TU COL COLGROUP IMAGE IMG IMG-CAPTION PGBRK CORRECTION "
    "EXTRACTION A BIG E FLY KNIGHTS MPN SHU THE WESTERN"
).split()
_BAD_LT = re.compile(
    rb"<(?!/?(?:" + b"|".join(t.encode() for t in sorted(_DART_TAGS, key=len, reverse=True))
    + rb")(?![A-Za-z0-9-])|[!?])",
    re.IGNORECASE,
)


# 속성값 안의 이스케이프 안 된 큰따옴표.
#   <TE ENG=""KB Kookmin Bank" VALIGN="MIDDLE" …>
#            ^^ 값이 따옴표로 시작하는데 이스케이프가 없어 속성 파싱이 깨지고,
#               그 지점부터 태그 중첩이 무너진다(성일하이텍 주석 22번 이후 소실 원인).
# ★정상적인 빈 속성(ENG="" VALIGN="…")을 망가뜨리면 안 되므로 조건을 좁힌다:
#   따옴표 사이에 '=' '<' '>' 가 없고(다음 속성 시작이 아님), 닫는 따옴표 뒤가 공백/'>' 일 때만.
_BAD_ATTR_QUOTE = re.compile(rb'=""([^"=<>]{1,120})"(?=[\s>])')


def sanitize(raw: bytes) -> bytes:
    out = _BAD_AMP.sub(b"&amp;", raw)
    out = _BAD_ATTR_QUOTE.sub(rb'="&quot;\1&quot;"', out)
    return _BAD_LT.sub(b"&lt;", out)


def orphan_trs(root) -> int:
    n = 0
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.upper() == "TR":
            p = el.getparent()
            if p is not None and p.tag.upper() not in ("TABLE", "TBODY", "THEAD", "TFOOT"):
                n += 1
    return n


def cells(path: str, rcept: str, corp: str, fy: int, per: str):
    """추출 결과를 셀 집합으로. (키) -> 값"""
    out = {}
    for r in extract_report_lines(path, rcept_no=rcept, corp_code=corp,
                                  report_fiscal_year=fy, report_fiscal_period=per,
                                  include_notes=True):
        key = (r.statement, r.basis, r.section_path, r.label_raw, r.col_index)
        out[key] = r.value_won
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20260729)
    args = ap.parse_args()

    t: Counter[str] = Counter()
    err_before = err_after = orph_before = orph_after = 0
    rows_before = rows_after = 0
    changed_examples: list[str] = []

    with get_session() as session:
        rows = list(session.execute(text("""
            SELECT f.corp_code, f.rcept_no, f.fiscal_period, d.file_path
            FROM filings f JOIN download_tasks d USING (rcept_no)
            WHERE f.fiscal_year = :y AND f.fiscal_period='FY' AND f.report_type='annual'
              AND f.is_final AND d.file_type='xml' AND d.status='completed'
              AND d.file_path IS NOT NULL
        """), {"y": args.year}).fetchall())
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing", flush=True)

        for i, f in enumerate(rows, 1):
            if i % 10 == 0:
                print(f"  … {i}/{len(rows)}", flush=True)
            raw = Path(f.file_path).read_bytes()
            fixed = sanitize(raw)
            if fixed == raw:
                t["정규화 불필요"] += 1

            p1 = etree.XMLParser(recover=True)
            r1 = etree.fromstring(raw, p1)
            p2 = etree.XMLParser(recover=True)
            try:
                r2 = etree.fromstring(fixed, p2)
            except Exception:  # noqa: BLE001
                t["정규화 후 파싱실패"] += 1
                continue

            err_before += len(list(p1.error_log))
            err_after += len(list(p2.error_log))
            orph_before += orphan_trs(r1)
            orph_after += orphan_trs(r2)

            with tempfile.NamedTemporaryFile(suffix=".xml", delete=True) as tmp:
                tmp.write(fixed)
                tmp.flush()
                try:
                    a = cells(f.file_path, f.rcept_no, f.corp_code, args.year, "FY")
                    b = cells(tmp.name, f.rcept_no, f.corp_code, args.year, "FY")
                except Exception:  # noqa: BLE001
                    t["추출 실패"] += 1
                    continue

            t["비교"] += 1
            rows_before += len(a)
            rows_after += len(b)
            added = set(b) - set(a)
            removed = set(a) - set(b)
            common = set(a) & set(b)
            changed = {k for k in common if a[k] != b[k]}
            if added:
                t["행 증가한 filing"] += 1
            if removed:
                t["행 감소한 filing"] += 1
            if changed:
                t["★값이 바뀐 filing"] += 1
                if len(changed_examples) < 6:
                    k = next(iter(changed))
                    changed_examples.append(
                        f"{f.corp_code} {str(k)[:60]} {a[k]:,} -> {b[k]:,}")
            t["추가 셀"] += len(added)
            t["삭제 셀"] += len(removed)
            t["변경 셀"] += len(changed)

    n = max(t["비교"], 1)
    print(f"\n=== XML 정규화 영향 · FY{args.year} (비교 {n} filing) ===")
    print(f"  파싱오류  {err_before:>7} -> {err_after:>7}")
    print(f"  고아 TR   {orph_before:>7} -> {orph_after:>7}")
    print(f"  추출 셀   {rows_before:>7} -> {rows_after:>7} "
          f"({(rows_after-rows_before)/max(rows_before,1)*100:+.2f}%)")
    print()
    for k, v in t.most_common():
        print(f"  {k:<20} {v:>7}")
    if changed_examples:
        print("\n--- 값이 바뀐 예 (★검증 필요) ---")
        for e in changed_examples:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
