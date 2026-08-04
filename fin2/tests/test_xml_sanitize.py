"""원문 XML 이스케이프 복구(`sanitize_dart_xml`) 회귀 테스트 — DB 비의존.

DART 원문은 제출사가 손으로 쓴 부분에서 이스케이프가 자주 깨진다. 그 손상이 **본문 텍스트에서
끝나면** 추출에 영향이 없지만, **태그 구조를 무너뜨리면 그 뒤가 통째로 사라진다.**
오류 없이 조용히 없어지므로 눈에 띄지 않는다 — 이 파일은 그 형태들을 고정한다.

★ 2026-08-05에 잡은 것: 본문의 `<?…` 가 **처리명령(PI)** 으로 해석돼 문서 끝까지 삼킨 사고.
   웅진 20190401004194 는 책 제목 '<?틴 블레이크의 걸작선>'(제출사가 이 하나만 이스케이프를
   빠뜨렸다) 때문에 문서의 5.9% 에서 파싱이 죽어 원문 929표 중 101표만 남았다.
   `?>` 가 없으니 PI 가 끝나지 않는데, lxml 은 recover 로도 못 살린다.

실행: python -m pytest fin2/tests/test_xml_sanitize.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from parser.xml.dart_xml_parser import sanitize_dart_xml  # noqa: E402


def _parse(raw: bytes):
    return etree.fromstring(sanitize_dart_xml(raw), etree.XMLParser(recover=True))


def test_xml_declaration_is_preserved():
    """`<?xml …?>` 는 진짜 PI 다 — 이스케이프하면 안 된다."""
    raw = b'<?xml version="1.0" encoding="utf-8"?><DOCUMENT><P>x</P></DOCUMENT>'
    out = sanitize_dart_xml(raw)
    assert out.startswith(b'<?xml version="1.0"'), out[:40]
    assert _parse(raw) is not None


def test_bogus_pi_in_body_does_not_swallow_document():
    """★핵심 회귀 — 본문의 '<?…' 가 PI 로 해석돼 뒤를 삼키면 안 된다.

    실측 웅진 20190401004194: '<?틴 블레이크의 걸작선>' 이후 문서 전체가 사라졌다.
    """
    raw = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<DOCUMENT><BODY>"
        "<P>해외 우수 출판사의 <?틴 블레이크의 걸작선>을 출시하며</P>"
        "<TABLE><TR><TD><P>자산총계</P></TD><TD><P>1,234,567</P></TD></TR></TABLE>"
        "<TABLE><TR><TD><P>부채총계</P></TD><TD><P>7,654,321</P></TD></TR></TABLE>"
        "</BODY></DOCUMENT>"
    ).encode()
    root = _parse(raw)
    assert root is not None
    # PI 로 삼켜졌다면 표가 0개가 된다.
    assert len(root.findall(".//TABLE")) == 2
    text = "".join(root.itertext())
    assert "자산총계" in text and "부채총계" in text
    assert "틴 블레이크의 걸작선" in text      # 텍스트로 살아남아야 한다(무손실)


def test_bogus_bang_in_body_does_not_break_structure():
    """'<!' 로 시작하는 본문도 같은 계열 — 마크업 선언으로 오인되면 안 된다."""
    raw = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<DOCUMENT><BODY><P>주의 <!중요 공지>를 참고</P>"
        "<TABLE><TR><TD><P>매출액</P></TD><TD><P>9,999,999</P></TD></TR></TABLE>"
        "</BODY></DOCUMENT>"
    ).encode()
    root = _parse(raw)
    assert len(root.findall(".//TABLE")) == 1
    assert "매출액" in "".join(root.itertext())


def test_plain_text_angle_brackets_still_escaped():
    """기존 동작 유지 — 화이트리스트 밖 '<당기말>' 류는 텍스트로 살린다."""
    raw = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<DOCUMENT><BODY><P><당기말> 기준</P>"
        "<TABLE><TR><TD><P>현금</P></TD><TD><P>1,000,000</P></TD></TR></TABLE>"
        "</BODY></DOCUMENT>"
    ).encode()
    root = _parse(raw)
    assert len(root.findall(".//TABLE")) == 1
    assert "당기말" in "".join(root.itertext())


def test_real_dart_tags_survive():
    """진짜 DART 태그는 이스케이프되지 않는다(대소문자 무관)."""
    raw = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>"
        "<TABLE-GROUP><TABLE><TR><TD><P>자산</P></TD><TD><P>2,000,000</P></TD></TR></TABLE>"
        "</TABLE-GROUP></SECTION-1></BODY></DOCUMENT>"
    ).encode()
    root = _parse(raw)
    assert root.find(".//SECTION-1") is not None
    assert root.find(".//TABLE-GROUP") is not None
    assert len(root.findall(".//TABLE")) == 1
