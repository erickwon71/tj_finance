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


# ── 3) 표제 인식 완화(2026-08-05) — 거짓 부재 회수 ──────────────────────────
# `_is_metadata_only` 가 표제를 '건너뛸 메타줄' 로 오판해 표가 통째로 유실되던 두 형태.
# 둘 다 **앞단 필터가 뒷단 분류기보다 엄격해서** 생긴 것이다.

def test_spaced_statement_name_is_a_title_not_metadata():
    """★자간 벌림 — DART 가 흔히 쓴다. 종전에는 기간마커만 보고 메타줄로 판정해 건너뛰었다.

    실측: 롯데렌탈 20151113000605(BS/IS/CF 전부 유실) · 세화피앤씨 20171114002715(BS·SCE).
    """
    from fin2.extract.statement_titles import _is_metadata_only, has_statement_name
    for t in ("분 기 연 결 재 무 상 태 표 제 11 기 3 분 기 : 2015년 9월 30일 현재",
              "재 무 상 태 표 제 2기 2017년 9월 30일 현재 (단위 : 원)",
              "자 본변동표 제2(당)기 반기 2015년 1월 1일 부터",
              "현 금 흐름표 제2(당)기 반기 2015년 1월 1일 부터"):
        assert has_statement_name(t), t
        assert _is_metadata_only(t) is False, t


def test_company_prefixed_unit_line_is_metadata():
    """★회사명이 앞에 붙은 단위줄 — '(단위' 로 시작하지 않아 메타로 인식되지 못했다.

    실측: 다올투자증권 20150817000725 — 제목표와 데이터표 사이에 이 줄이 끼어 있어
    back-scan 이 여기서 멈추고 진짜 표제에 닿지 못했다(연결 BS/IS 등 전부 유실).
    """
    from fin2.extract.statement_titles import _is_metadata_only
    assert _is_metadata_only("케이티비투자증권주식회사와 그 종속기업 (단위 : 원)") is True
    assert _is_metadata_only("동부제2호기업인수목적(주) (단위:원)") is True


def test_plain_sentence_is_not_metadata():
    """단위·기간·재무제표명이 없는 평범한 문장은 메타가 아니다(경계로 남아야 한다)."""
    from fin2.extract.statement_titles import _is_metadata_only
    assert _is_metadata_only("상기 재무정보는 내부거래 제거 전 기준으로 작성되었습니다.") is False
    assert _is_metadata_only("2. 연결재무제표") is False
