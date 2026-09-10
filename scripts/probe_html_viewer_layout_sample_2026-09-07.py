"""검토 후보(docs/plans/html_viewer_extractor_design_2026-09-07.md §8 step 1) —
잔여 93건 중 3~5건 표본으로 웹뷰어 HTML 레이아웃 분포를 먼저 확인한다.

DB 적재 없음, 순수 조사용 프로브. `collector/legacy_downloader.py::
LegacyDartScraper`의 기존 요청 흐름(_get()/_fetch_html())만 재사용하고,
`dsaf001/main.do`의 TOC 트리(node1/node2 JS 객체) 파싱은 이 스크립트 안에서
1회용으로 구현한다(설계 문서 §4-1의 실제 검증 — 프로덕션 코드 아님).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from collector.legacy_downloader import LegacyDartScraper, DART_WEB_BASE

# (corp_code, name, rcept_no, category) — 93건 검증대장에서 뽑은 5건 표본.
# fail 3 + missing 2, 업종/연도 다양성 확보(금융/통신/건설/제조/소비재).
SAMPLES = [
    ("00115694", "DB증권",   "20010214000346", "fail"),     # 증권사, fy2001 Q3
    ("00190321", "케이티",    "20011114000557", "fail"),     # 통신, fy2001 Q3
    ("00203582", "한솔홈데코", "20000329000320", "missing"),  # 완전 결측, fy1999 FY
    ("00121534", "MH에탄올",  "20000330000442", "fail"),     # fy1999 FY, 값 이상(단위 의심)
    ("00148276", "제일기획",  "20010330001205", "fail"),     # 광고, fy2000 FY
]


def parse_toc_nodes(main_do_text: str) -> list[dict]:
    """node1/node2 JS 객체 블록에서 text/eleId/offset/length/dtd/dcmNo 추출."""
    nodes = []
    # 각 노드 블록은 "var node[12] = {};" 로 시작해 다음 node 선언 전까지 이어짐.
    for block in re.split(r"var\s+node[12]\s*=\s*\{\};", main_do_text)[1:]:
        block = block[:2000]  # 다음 필드들이 이 안에 다 있음(여유있게 자름)
        def field(name):
            m = re.search(rf"\['{name}'\]\s*=\s*\"([^\"]*)\"", block)
            return m.group(1) if m else None
        text = field("text")
        if text is None:
            continue
        nodes.append({
            "text": text,
            "eleId": field("eleId"),
            "offset": field("offset"),
            "length": field("length"),
            "dtd": field("dtd"),
            "dcmNo": field("dcmNo"),
        })
    return nodes


def find_statement_nodes(nodes: list[dict]) -> list[dict]:
    """'재무제표'/'연결재무제표' 노드만(이용상의 유의점·합병전후는 제외)."""
    out = []
    for n in nodes:
        t = n["text"]
        if "재무제표" not in t:
            continue
        if "유의점" in t or "합병전" in t:
            continue
        out.append(n)
    return out


def classify_table_layout(table) -> str:
    """표 하나가 레이아웃 A(거대-셀형)/B(행별-TR형)/기타 중 어디인지 대략 판정."""
    tbody = table.find("tbody")
    if not tbody:
        return "no-tbody"
    trs = tbody.find_all("tr", recursive=False)
    if not trs:
        return "empty"
    first_row_tds = trs[0].find_all("td", recursive=False)
    if len(trs) <= 2 and first_row_tds:
        # 행이 1~2개뿐인데 첫 TD 안에 <br>이 여러 개면 A류(거대-셀).
        br_count = len(first_row_tds[0].find_all("br"))
        if br_count >= 5:
            return f"A(giant-cell, rows={len(trs)}, brs={br_count})"
    if len(trs) >= 5:
        return f"B(per-row-tr, rows={len(trs)})"
    return f"unknown(rows={len(trs)})"


def probe_one(scraper: LegacyDartScraper, corp: str, name: str, rcept: str, category: str):
    print(f"\n{'='*70}\n{corp} {name} rcept={rcept} ({category})\n{'='*70}")
    resp = scraper._get(f"{DART_WEB_BASE}/dsaf001/main.do", {"rcpNo": rcept})
    if resp is None:
        print("  main.do 요청 실패")
        return
    nodes = parse_toc_nodes(resp.text)
    print(f"  TOC 노드 수: {len(nodes)}")
    fs_nodes = find_statement_nodes(nodes)
    if not fs_nodes:
        print("  ⚠ '재무제표' 노드를 못 찾음 — TOC 구조 자체가 다르거나 목차명이 다를 가능성")
        # 참고용으로 상위 목차 텍스트 몇 개 출력(디버깅 단서)
        sample_texts = [n["text"] for n in nodes if n["text"].strip()][:15]
        print(f"  (참고) 상위 TOC 텍스트 샘플: {sample_texts}")
        return

    for node in fs_nodes:
        print(f"  --- 노드: {node['text']!r} (eleId={node['eleId']}, "
              f"length={node['length']}, dtd={node['dtd']}) ---")
        params = {
            "dcmNo": node["dcmNo"], "eleId": node["eleId"],
            "offset": node["offset"], "length": node["length"], "dtd": node["dtd"],
        }
        html_bytes = scraper._fetch_html(rcept, params)
        if not html_bytes:
            print("    HTML fetch 실패")
            continue
        soup = BeautifulSoup(html_bytes, "lxml")
        bordered_tables = soup.find_all("table", attrs={"border": "1"})
        print(f"    받은 크기: {len(html_bytes):,}B, border=1 표 개수: {len(bordered_tables)}")
        # 대차대조표/재무상태표로 보이는 첫 표만 분류(전체 재무제표군 중 BS 하나만 표본 확인)
        for i, tbl in enumerate(bordered_tables[:3]):
            layout = classify_table_layout(tbl)
            print(f"    표[{i}]: {layout}")


if __name__ == "__main__":
    scraper = LegacyDartScraper()
    try:
        for corp, name, rcept, category in SAMPLES:
            probe_one(scraper, corp, name, rcept, category)
    finally:
        scraper.close()
