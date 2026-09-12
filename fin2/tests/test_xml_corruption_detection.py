"""원문 손상(리터럴 '?' 치환) 감지 회귀 테스트 — DB 비의존.

배경: `docs/plans/parser_source_fallback_cascade_design_2026-09-12.md` §3. 솔트웨어
20220802000208 실측 — DART OpenDART `document.xml` archive 자체가 한글을 리터럴
'?'(0x3F)로 치환한 채 손상돼 있었다(재다운로드해도 바이트까지 동일 — DART 서버측
archive 손상, 저희 인코딩 처리 문제 아님). `_parse_xml_file()`이 이걸 파싱 시도 전에
걸러 `None`을 반환해야 호출부(`extract_report_lines()` 등)가 "0행"이 아니라 다른
소스(PDF/HTML) 전환을 검토할 신호로 구분할 수 있다.

임계치 검증(2026-09-12, DB 표본 200건, 2000~2025년 분포): 정상 파일 비율 최대
0.0001(0.01%), 손상 파일(솔트웨어) 0.1098(11%) — 1000배 격차. 1%를 임계치로 잡는다.

실행: python -m pytest fin2/tests/test_xml_corruption_detection.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xml.dart_xml_parser import (  # noqa: E402
    _CORRUPTION_QMARK_THRESHOLD, _corruption_ratio, _parse_xml_file,
)


# ── _corruption_ratio() 순수 로직 ────────────────────────────────────────────

def test_corruption_ratio_empty_bytes_is_zero():
    assert _corruption_ratio(b"") == 0.0


def test_corruption_ratio_normal_text_negligible():
    """정상 문서 — 진짜 물음표 몇 개는 있어도 전체 대비 미미하다."""
    raw = ("<DOCUMENT><P>회사의 목적은 무엇인가?</P>" + "정상텍스트" * 500 + "</DOCUMENT>").encode("utf-8")
    assert _corruption_ratio(raw) < _CORRUPTION_QMARK_THRESHOLD


def test_corruption_ratio_saltware_style_corruption_exceeds_threshold():
    """실측 패턴 재현 — 한글 자리가 전부 리터럴 '?'로 치환된 문서."""
    raw = b'<COMPANY-NAME>?? ??? ?? ????</COMPANY-NAME>' * 200
    assert _corruption_ratio(raw) > _CORRUPTION_QMARK_THRESHOLD


# ── _parse_xml_file() 배선 — 손상 감지 시 파싱 시도 없이 None ────────────────

def test_parse_xml_file_returns_none_for_corrupted_content(tmp_path):
    """손상된 파일은 구조적으로 valid XML이어도(파싱 자체는 가능해도) None을 반환한다
    — 태그는 살아있어도 라벨(한글)이 전부 파괴돼 추출이 무의미하기 때문."""
    corrupted = tmp_path / "corrupted.xml"
    body = '<COMPANY-NAME>?? ??? ?? ????</COMPANY-NAME>' * 200
    corrupted.write_text(f'<?xml version="1.0" encoding="utf-8"?><DOCUMENT>{body}</DOCUMENT>',
                         encoding="utf-8")
    assert _parse_xml_file(corrupted) is None


def test_parse_xml_file_parses_normal_content_unaffected(tmp_path):
    """정상 문서는 기존과 동일하게 정상 파싱된다 — 회귀 방지.

    ★본문을 충분히 채워야 한다 — `<?xml …?>` 선언 자체가 이미 진짜 '?' 2개를
    포함하므로, 파일이 너무 작으면(실제 원문은 수백KB~수MB) 그 2개만으로도
    비율이 튀어 거짓양성이 난다(실측으로 발견 — 현실적인 크기가 아니면 이
    임계치 검사 자체가 무의미하다는 방증이기도 하다)."""
    normal = tmp_path / "normal.xml"
    body = "<P>회사의 목적은 소프트웨어 개발이다.</P>" * 200
    normal.write_text(f'<?xml version="1.0" encoding="utf-8"?><DOCUMENT>{body}</DOCUMENT>',
                      encoding="utf-8")
    root = _parse_xml_file(normal)
    assert root is not None
    assert root.find("P").text == "회사의 목적은 소프트웨어 개발이다."


def test_saltware_real_file_detected_as_corrupted():
    """실제 사고 파일로 종단 검증(파일 없으면 스킵 — 환경 차이 대응)."""
    path = (Path(__file__).resolve().parents[2]
            / "raw_report/KOSDAQ/01390399_솔트웨어/half/2022/20220802000208.xml")
    if not path.exists():
        return
    assert _parse_xml_file(path) is None
