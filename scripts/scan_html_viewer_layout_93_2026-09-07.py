"""검토 후보(docs/plans/html_viewer_extractor_design_2026-09-07.md §8 step 1) —
잔여 93건(fail 19 + missing 74) 전수로 웹뷰어 HTML 레이아웃 분포를 확인한다.

DB 적재 없음, 순수 조사용 프로브(scripts/probe_html_viewer_layout_sample_2026-09-07.py의
5건 표본을 93건 전체로 확대 + 그 표본에서 발견된 두 가지 보강 반영):
  1. TOC 노드 매칭에 "감사의견" 제외 패턴 추가(한솔홈데코 오탐 사례).
  2. 표 하나하나를 <P class='table-group'>제목</P> 로 식별해 실제 대차대조표/
     재무상태표 표만 레이아웃 분류(이전엔 앞쪽 표 3개를 무조건 찍었음 — 노트류
     표까지 섞여 분류가 부정확할 수 있었음).

목록 출처: 검증대장(https://claude.ai/code/artifact/7080b708-5ba0-4f75-85c9-3491c35e69e0)
DATA.fail(19) + DATA.missing(74) 를 rcept_no 단위로 그대로 옮김(고유 필링 93건).
"""
import csv
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from collector.legacy_downloader import LegacyDartScraper, DART_WEB_BASE

_BS_NAMES = ("재무상태표", "대차대조표")

# (corp_code, name, rcept_no, category) — 검증대장 93건 전수, 고유 필링 단위.
SAMPLES = [
    ("00111218", "KD", "20010814000291", "fail"),
    ("00111218", "KD", "20010514000707", "fail"),
    ("00115694", "DB증권", "20010214000346", "fail"),
    ("00121534", "MH에탄올", "20000330000442", "fail"),
    ("00139685", "양지사", "20010514000316", "fail"),
    ("00146232", "일성건설", "20000330000664", "fail"),
    ("00148276", "제일기획", "20010330001205", "fail"),
    ("00148276", "제일기획", "20010814000859", "fail"),
    ("00148276", "제일기획", "20010515000208", "fail"),
    ("00148276", "제일기획", "20011114000932", "fail"),
    ("00148832", "제주은행", "20021114000206", "fail"),
    ("00148832", "제주은행", "20021113000715", "fail"),
    ("00150244", "하이트진로", "20010515000723", "fail"),
    ("00154462", "아모레퍼시픽홀딩스", "20000814000463", "fail"),
    ("00154462", "아모레퍼시픽홀딩스", "20000515000058", "fail"),
    ("00158501", "에스원", "20010514000378", "fail"),
    ("00160047", "한국앤컴퍼니", "20021114000299", "fail"),
    ("00190321", "케이티", "20011114000557", "fail"),
    ("00198697", "일진디스플", "20010331000458", "fail"),
    ("00111218", "KD", "20011112000002", "missing"),
    ("00120562", "롯데지주", "20010814000538", "missing"),
    ("00121288", "모나미", "20010814000169", "missing"),
    ("00121288", "모나미", "20011114001175", "missing"),
    ("00122056", "미창석유공업", "20010810000339", "missing"),
    ("00123772", "부국증권", "20011113000485", "missing"),
    ("00124197", "세아제강지주", "20010814000250", "missing"),
    ("00127158", "씨아이테크", "20000124000002", "missing"),
    ("00127857", "삼익악기", "20010330001105", "missing"),
    ("00127857", "삼익악기", "20010813000313", "missing"),
    ("00127857", "삼익악기", "20010514000655", "missing"),
    ("00127857", "삼익악기", "20011113000655", "missing"),
    ("00128546", "삼천당제약", "20010331000162", "missing"),
    ("00128546", "삼천당제약", "20010514000217", "missing"),
    ("00128546", "삼천당제약", "20011112000095", "missing"),
    ("00128546", "삼천당제약", "20020814001084", "missing"),
    ("00128546", "삼천당제약", "20020515000121", "missing"),
    ("00128546", "삼천당제약", "20021114000391", "missing"),
    ("00129387", "SP삼화", "20000811000096", "missing"),
    ("00129387", "SP삼화", "20010813000039", "missing"),
    ("00129642", "상신브레이크", "20021113000177", "missing"),
    ("00138279", "S-Oil", "20010629000270", "missing"),
    ("00138279", "S-Oil", "20010515000775", "missing"),
    ("00139719", "와이지-원", "20000515000133", "missing"),
    ("00140946", "한솔로지스틱스", "20010814000915", "missing"),
    ("00140946", "한솔로지스틱스", "20011114000972", "missing"),
    ("00140946", "한솔로지스틱스", "20020813000679", "missing"),
    ("00140946", "한솔로지스틱스", "20021111000163", "missing"),
    ("00146861", "자화전자", "20010328000289", "missing"),
    ("00146861", "자화전자", "20021114000177", "missing"),
    ("00159740", "KISCO홀딩스", "20010813000054", "missing"),
    ("00159740", "KISCO홀딩스", "20011113000516", "missing"),
    ("00160047", "한국앤컴퍼니", "20011114000801", "missing"),
    ("00163691", "유수홀딩스", "20010814000185", "missing"),
    ("00163691", "유수홀딩스", "20010515000229", "missing"),
    ("00163691", "유수홀딩스", "20011114000009", "missing"),
    ("00164636", "HDC", "20010814000283", "missing"),
    ("00165103", "푸드웰", "20020514000280", "missing"),
    ("00166175", "대호특수강", "20010813000085", "missing"),
    ("00166175", "대호특수강", "20011114001245", "missing"),
    ("00166175", "대호특수강", "20021113000004", "missing"),
    ("00170026", "시공테크", "20010330000057", "missing"),
    ("00170877", "진로발효", "20010813000386", "missing"),
    ("00173698", "신일전자", "20000629000089", "missing"),
    ("00173698", "신일전자", "20000629000140", "missing"),
    ("00173698", "신일전자", "20000811000116", "missing"),
    ("00173698", "신일전자", "20010214000008", "missing"),
    ("00199252", "HLB", "20010331000331", "missing"),
    ("00199252", "HLB", "20010816000213", "missing"),
    ("00199252", "HLB", "20010814000793", "missing"),
    ("00199252", "HLB", "20010515000939", "missing"),
    ("00199252", "HLB", "20010515000776", "missing"),
    ("00199252", "HLB", "20010516000056", "missing"),
    ("00199252", "HLB", "20011114000515", "missing"),
    ("00199252", "HLB", "20011114000947", "missing"),
    ("00203582", "한솔홈데코", "20000329000320", "missing"),
    ("00203582", "한솔홈데코", "20010331000623", "missing"),
    ("00203582", "한솔홈데코", "20000814000140", "missing"),
    ("00203582", "한솔홈데코", "20000515000269", "missing"),
    ("00203582", "한솔홈데코", "20020401000165", "missing"),
    ("00203582", "한솔홈데코", "20010814000358", "missing"),
    ("00203582", "한솔홈데코", "20010515000415", "missing"),
    ("00203582", "한솔홈데코", "20011114000657", "missing"),
    ("00203582", "한솔홈데코", "20020820000124", "missing"),
    ("00203582", "한솔홈데코", "20020814000471", "missing"),
    ("00203582", "한솔홈데코", "20020514000885", "missing"),
    ("00203582", "한솔홈데코", "20021114000443", "missing"),
    ("00205687", "더라미", "20020514000517", "missing"),
    ("00267881", "보성파워텍", "20010820000006", "missing"),
    ("00267881", "보성파워텍", "20010814000217", "missing"),
    ("00267881", "보성파워텍", "20010829000027", "missing"),
    ("00295547", "디지아이", "20021106000076", "missing"),
    ("00307222", "YBM넷", "20020814000872", "missing"),
    ("00307222", "YBM넷", "20020515000468", "missing"),
]

assert len(SAMPLES) == 93, f"expected 93, got {len(SAMPLES)}"


def parse_toc_nodes(main_do_text: str) -> list[dict]:
    nodes = []
    for block in re.split(r"var\s+node[12]\s*=\s*\{\};", main_do_text)[1:]:
        block = block[:2000]
        def field(name):
            m = re.search(rf"\['{name}'\]\s*=\s*\"([^\"]*)\"", block)
            return m.group(1) if m else None
        text = field("text")
        if text is None:
            continue
        nodes.append({
            "text": text, "eleId": field("eleId"), "offset": field("offset"),
            "length": field("length"), "dtd": field("dtd"), "dcmNo": field("dcmNo"),
        })
    return nodes


def find_statement_nodes(nodes: list[dict]) -> list[dict]:
    """'재무제표'/'연결재무제표' 노드만 — 유의점/합병전/★감사의견(신규)★ 제외."""
    out = []
    for n in nodes:
        t = n["text"]
        if "재무제표" not in t:
            continue
        if "유의점" in t or "합병전" in t or "감사의견" in t or "감사인" in t:
            continue
        out.append(n)
    return out


def classify_table_layout(table) -> str:
    tbody = table.find("tbody")
    if not tbody:
        return "no-tbody"
    trs = tbody.find_all("tr", recursive=False)
    if not trs:
        return "empty"
    first_row_tds = trs[0].find_all("td", recursive=False)
    if len(trs) <= 2 and first_row_tds:
        br_count = len(first_row_tds[0].find_all("br"))
        if br_count >= 5:
            return f"A(rows={len(trs)},brs={br_count})"
    if len(trs) >= 5:
        return f"B(rows={len(trs)})"
    return f"unknown(rows={len(trs)})"


def find_bs_tables(soup: BeautifulSoup) -> list[tuple[str, object]]:
    """BS류(대차대조표/재무상태표) 표만 식별.

    ★설계 변경(2026-09-07, 삼익악기 00127857·제주은행 00148832 원인조사) — 원래는
    <P class='table-group'>제목</P>(자간띄움 텍스트, 예: "대 차 대 조 표")을
    앵커로 썼으나, 실측 결과 그 제목의 **위치 관례가 최소 3가지**였다:
      ① table-group P 안에 제목 직접 포함(KD·케이티·동성제약 등 다수)
      ② table-group P는 비어있고 제목은 바로 다음 형제 plain <P>(삼익악기 FY2000,
         제주은행 두 필링 — 은행은 "은행계정"류 하위 표제까지 낌)
      ③ table-group P 자체가 아예 없고 제목이 section-3 바로 다음 plain <P>
         (삼익악기 H1/Q1/Q3 2001)
    세 경우 모두에서 안정적으로 존재하는 건 **<P class='section-3'>가. 대차대조표
    </P>류의 소제목**뿐이었다(이 텍스트는 지금까지 본 모든 표본에서 자간띄움 없이
    정상 표기됨). 그래서 앵커를 table-group에서 section-3로 바꿨다 — 제목 위치가
    몇 번째 관례든 상관없이 "이 섹션 바로 다음에 오는 첫 border=1 표"만 있으면
    되므로 더 단순하고 강건하다.
    """
    out = []
    for p in soup.find_all("p", attrs={"class": "section-3"}):
        heading = re.sub(r"\s+", "", p.get_text().strip())
        if not any(name in heading for name in _BS_NAMES):
            continue
        tbl = p.find_next("table", attrs={"border": "1"})
        if tbl is not None:
            out.append((heading, tbl))
    return out


def probe_one(scraper: LegacyDartScraper, corp: str, name: str, rcept: str, category: str) -> list[dict]:
    rows = []
    resp = scraper._get(f"{DART_WEB_BASE}/dsaf001/main.do", {"rcpNo": rcept})
    if resp is None:
        rows.append({"corp": corp, "name": name, "rcept": rcept, "category": category,
                      "basis_node": "", "bs_title": "", "layout": "main.do 실패"})
        return rows
    nodes = parse_toc_nodes(resp.text)
    fs_nodes = find_statement_nodes(nodes)
    if not fs_nodes:
        rows.append({"corp": corp, "name": name, "rcept": rcept, "category": category,
                      "basis_node": "", "bs_title": "", "layout": "TOC 노드 없음"})
        return rows

    for node in fs_nodes:
        params = {"dcmNo": node["dcmNo"], "eleId": node["eleId"],
                  "offset": node["offset"], "length": node["length"], "dtd": node["dtd"]}
        html_bytes = scraper._fetch_html(rcept, params)
        if not html_bytes:
            rows.append({"corp": corp, "name": name, "rcept": rcept, "category": category,
                          "basis_node": node["text"], "bs_title": "", "layout": "viewer.do 실패"})
            continue
        soup = BeautifulSoup(html_bytes, "lxml")
        bs_tables = find_bs_tables(soup)
        if not bs_tables:
            rows.append({"corp": corp, "name": name, "rcept": rcept, "category": category,
                          "basis_node": node["text"], "bs_title": "", "layout": "BS표 없음"})
            continue
        for title, tbl in bs_tables:
            layout = classify_table_layout(tbl)
            rows.append({"corp": corp, "name": name, "rcept": rcept, "category": category,
                          "basis_node": node["text"], "bs_title": title, "layout": layout})
    return rows


if __name__ == "__main__":
    out_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scan_html_layout_93_result.csv")
    scraper = LegacyDartScraper()
    all_rows = []
    t0 = time.monotonic()
    try:
        for i, (corp, name, rcept, category) in enumerate(SAMPLES, 1):
            rows = probe_one(scraper, corp, name, rcept, category)
            all_rows.extend(rows)
            elapsed = time.monotonic() - t0
            print(f"[{i}/93] {corp} {name} {rcept} ({category}) -> "
                  f"{[r['layout'] for r in rows]}  (elapsed {elapsed:.0f}s)", flush=True)
    finally:
        scraper.close()

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["corp", "name", "rcept", "category", "basis_node", "bs_title", "layout"])
        w.writeheader()
        w.writerows(all_rows)
    print(f"\n저장: {out_csv} ({len(all_rows)}행)")
