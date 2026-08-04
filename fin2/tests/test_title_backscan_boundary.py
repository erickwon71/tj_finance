"""표제 back-scan 의 **데이터표 경계** 회귀 테스트 (합성 XML, DB 비의존).

`title_text_for_classify` 는 데이터표의 직전 형제가 단위/기간 줄뿐일 때 그것을 건너뛰고
표제를 찾는다(요약재무정보 서식 대응). 그 docstring 은 "데이터표를 만나면 멈춘다" 고
약속했지만 **구현에 그 검사가 없었다**(2026-08-04 발견).

그래서 기간 헤더로 시작하는 데이터표를 '기간줄' 로 오인해 통째로 건너뛰고, 그 앞
재무제표의 제목을 주워왔다. 결과:

  · 이익잉여금처분계산서가 현금흐름표(CF)로 적재 — 일진홀딩스 20210318000893 외 31표
  · 전기·전전기 열만 있는 **연속 표**가 당기(col_index=0) 로 적재 —
    부국증권 20210517000980: 2020 연간 영업CF 82,603,867,221 이 2021 당기로 들어가 있었다

실측 영향(적재분 597건): 선택 변경 34문서 · 제거 35표(545행) · **추가 0표**.
제거된 35표는 전수 확인 결과 전부 처분계산서/결손금처리계산서이거나 당기 열이 없는 연속표였다.

실행: python -m pytest fin2/tests/test_title_backscan_boundary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.statement_titles import title_text_for_classify  # noqa: E402
from fin2.extract.text import _detect_body_statement_tables  # noqa: E402


def _rows(*pairs: tuple[str, str]) -> str:
    return "".join(
        f"<TR><TD><P>{a}</P></TD><TD><P>{b}</P></TD></TR>" for a, b in pairs
    )


def _title(txt: str) -> str:
    return f"<TABLE><TR><TD><P>{txt}</P></TD></TR></TABLE>"


def _data(*pairs: tuple[str, str]) -> str:
    return f"<TABLE>{_rows(*pairs)}</TABLE>"


CF_DATA = _data(("Ⅰ.영업활동현금흐름", "1,111,111,111"), ("당기순이익", "222,222,222"))
APPROP = _data(("Ⅰ.미처분이익잉여금", "110,890"), ("전기이월미처분이익잉여금", "105,759"))


def _amounts(groups, code):
    out = set()
    for tbl, _u, _k in groups.get(code, []):
        out.update(t.strip() for t in tbl.itertext() if "," in t)
    return out


# ── 1) 단위 함수 ────────────────────────────────────────────────────────────

def test_backscan_stops_at_data_table():
    """데이터표 너머의 제목은 남의 것 — 주워오지 않는다."""
    doc = (f"<SECTION-2>{_title('현금흐름표 제 39 기 2020.01.01 부터')}"
           f"{CF_DATA}<P></P>{_title('이익잉여금처분계산서 제 39 기')}</SECTION-2>")
    root = etree.fromstring(doc.encode())
    approp_title = root.findall("TABLE")[-1]
    assert title_text_for_classify(approp_title) == ""


def test_backscan_stops_at_table_group_wrapping_data():
    """★<TABLE-GROUP> 으로 감싼 데이터표도 경계다.

    DART 는 같은 문서에서 [제목표,데이터표] 를 TABLE-GROUP 으로 묶기도 하고 SECTION-2
    직계 형제로 두기도 한다. 실측 일진홀딩스는 **둘이 섞여** 있어서, TABLE 만 검사하면
    TABLE-GROUP 형제를 그냥 통과했다.
    """
    doc = (f"<SECTION-2><TABLE-GROUP>{_title('현금흐름표 제 39 기 2020.01.01 부터')}"
           f"{CF_DATA}</TABLE-GROUP><P></P>"
           f"{_title('이익잉여금처분계산서 제 39 기')}</SECTION-2>")
    root = etree.fromstring(doc.encode())
    approp_title = root.findall("TABLE")[-1]
    assert title_text_for_classify(approp_title) == ""


def test_backscan_still_skips_metadata_lines():
    """본래 목적(요약재무정보 서식)은 유지 — 단위/기간 <P> 는 계속 건너뛴다."""
    doc = ("<SECTION-2><P>재무상태표</P><P>제 19 기 2023.12.31 현재</P>"
           "<P>(단위 : 천원)</P>"
           + _data(("자산총계", "1,000,000")) + "</SECTION-2>")
    root = etree.fromstring(doc.encode())
    data_tbl = root.findall("TABLE")[-1]
    assert "재무상태표" in title_text_for_classify(data_tbl)


# ── 2) 감지기 통합 ──────────────────────────────────────────────────────────

APPROP_DOC = f"""<DOCUMENT>
 <SECTION-2><TITLE>4. 재무제표</TITLE>
   {_title('재무상태표 제 39 기 2020.12.31 현재 (단위 : 원)')}
   {_data(('자산총계', '9,999,999,999'), ('부채총계', '1,234,567,890'))}
   <TABLE-GROUP>
     {_title('현금흐름표 제 39 기 2020.01.01 부터 2020.12.31 까지 (단위 : 원)')}
     {CF_DATA}
   </TABLE-GROUP>
   <P></P>
   {_title('이익잉여금처분계산서 제 39 기 2020년 1월 1일 부터 (단위 : 백만원)')}
   {APPROP}
 </SECTION-2>
</DOCUMENT>"""


def test_appropriation_statement_not_loaded_as_cashflow():
    """★핵심 회귀 — 이익잉여금처분계산서가 현금흐름표로 적재되면 안 된다."""
    root = etree.fromstring(APPROP_DOC.encode())
    groups = _detect_body_statement_tables(root, fin_type="B", include_sce=True)

    assert "1,111,111,111" in _amounts(groups, "CF_S")      # 진짜 CF 는 그대로
    assert "9,999,999,999" in _amounts(groups, "BS_S")
    picked = {a for code in groups for a in _amounts(groups, code)}
    assert "110,890" not in picked, "이익잉여금처분계산서가 본문으로 샜다"
    assert len(groups.get("CF_S", [])) == 1, "CF 에 표가 둘 붙었다"
