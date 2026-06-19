"""읽기전용: classify_statement_title 구(舊) vs 신(新, 명칭뒤 기간마커 요구) 비교.
신 규칙이 **현재 채택되는 실제 face 표제**를 떨구는지(데이터손실) 확인.
샘플 corp 의 최신 사업보고서 1건씩 스캔, 불일치(구 채택→신 거부) 표제를 덤프.
usage: python scripts/gateb_scan_title_regression.py [N]
"""
import re, sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from fin2.extract.statement_titles import (
    title_text, _PERIOD_MARK, _TITLE_EXCLUDE, _STMT_NAME, _CONSOL_TITLE, _FACE_TITLE_START as NEW,
)

# 구(舊) 규칙 = 명칭뒤 기간마커 요구 전(이전 commit). 회귀 비교 기준.
OLD = re.compile(r"^[\sⅠⅡⅢⅣⅤ\d.\)\(]{0,8}(?:연결|별도|개별)?\s*"
                 r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표)(?![가-힣])")

def cls(title, pat):
    if not title or not _PERIOD_MARK.search(title): return None
    if _TITLE_EXCLUDE.search(title[:45]): return None
    m = pat.match(title)
    if not m: return None
    basis = "C" if _CONSOL_TITLE.search(title) else "S"
    return f"{_STMT_NAME[m.group(1)]}_{basis}"

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
with get_session() as s:
    rows = s.execute(text("""
        SELECT f.corp_code, dt.file_path FROM download_tasks dt JOIN filings f ON f.rcept_no=dt.rcept_no
        WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
          AND f.report_type='annual'
        ORDER BY f.corp_code, f.fiscal_year DESC""")).fetchall()
# one recent annual per corp
seen, files = set(), []
for corp, fp in rows:
    if corp in seen: continue
    seen.add(corp); files.append(fp)
random.seed(7); random.shuffle(files)

dropped = []  # (file, title) old accepted but new rejects
nfiles = 0
for fp in files:
    if nfiles >= N:
        break
    if not Path(fp).exists():
        continue
    try:
        root = _parse_xml_file(Path(fp))
    except Exception:
        continue
    if root is None: continue
    nfiles += 1
    for tbl in root.findall(".//TABLE"):
        t = title_text(tbl)
        o, n = cls(t, OLD), cls(t, NEW)
        if o is not None and n is None:
            dropped.append((Path(fp).name, o, t[:110]))

print(f"스캔 {nfiles} 파일, 구 채택→신 거부 표제: {len(dropped)}건\n")
for fn, o, t in dropped[:80]:
    print(f"  [{o}] {fn}  {t!r}")
