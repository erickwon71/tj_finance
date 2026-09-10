"""R90 — `fin2/extract/shares.py` "단위 : 천주" 미인식 ×1000 축소 회귀 테스트.

발견 경위(2026-09-09): 계층2 검토 캠페인 중 사용자가 "시총 오류 확인해봐" 지시 →
stock_prices.market_cap 전종목 정체(9/1~) 조사 과정에서, 일부 회사(현대로템·크린앤사이언스
등)의 원문 "주식의 총수 현황" 표가 "(단위 : 천주, %)"로 선언돼 있는데 파서가 이를 무시해
발행주식수가 정확히 1000배 축소 저장됨을 발견. DART 라이브 API(`get_shares_from_dart`)
대조로 실측 확인(문서: docs/plans — 이 세션 핸드오프 참고).

실행: pytest fin2/tests/test_shares_unit_multiplier_r86.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.shares import extract_issued_common_shares_detailed  # noqa: E402

# 현대로템 20260814002977 실측 축약본(원문 표 구조 그대로, 컬럼만 보존).
_THOUSAND_SHARES_XML = """<XML>
<TABLE-GROUP>
4. 주식의 총수 등
가. 주식의 총수 현황
<TABLE>
<TR><TD>(기준일 : 2026.06.30 )</TD><TD>(단위 : 천주, %)</TD></TR>
</TABLE>
<TABLE>
<TR><TD>구 분</TD><TD>보통주</TD><TD>우선주</TD><TD>합계</TD><TD>비고</TD></TR>
<TR><TD>Ⅰ. 발행할 주식의 총수</TD><TD>200,000</TD><TD>-</TD><TD>200,000</TD>
    <TD>정관상 발행 가능한 주식 총수 : 2억주</TD></TR>
<TR><TD>Ⅱ. 현재까지 발행한 주식의 총수</TD><TD>115,742</TD><TD>-</TD><TD>115,742</TD><TD></TD></TR>
<TR><TD>Ⅲ. 현재까지 감소한 주식의 총수</TD><TD>6,600</TD><TD>-</TD><TD>6,600</TD><TD></TD></TR>
<TR><TD>Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)</TD><TD>109,142</TD><TD>-</TD><TD>109,142</TD><TD></TD></TR>
</TABLE>
</TABLE-GROUP>
</XML>"""

# 대다수 정상 서식 — 단위 선언 없이 "주" 그대로(네오팜류).
_PLAIN_SHARES_XML = """<XML>
<TABLE-GROUP>
4. 주식의 총수 등
가. 주식의 총수 현황
<TABLE>
<TR><TD>(기준일 : 2026.06.30 )</TD></TR>
</TABLE>
<TABLE>
<TR><TD>구 분</TD><TD>보통주</TD><TD>우선주</TD><TD>합계</TD><TD>비고</TD></TR>
<TR><TD>Ⅰ. 발행할 주식의 총수</TD><TD>40,000,000</TD><TD>-</TD><TD>40,000,000</TD><TD></TD></TR>
<TR><TD>Ⅱ. 현재까지 발행한 주식의 총수</TD><TD>16,027,989</TD><TD>-</TD><TD>16,027,989</TD><TD></TD></TR>
<TR><TD>Ⅲ. 현재까지 감소한 주식의 총수</TD><TD>-</TD><TD>-</TD><TD>-</TD><TD></TD></TR>
<TR><TD>Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)</TD><TD>16,027,989</TD><TD>-</TD><TD>16,027,989</TD><TD></TD></TR>
</TABLE>
</TABLE-GROUP>
</XML>"""

# "단위 : 주" 명시(천주 아님, 비고도 액면 그대로 정합) — 배수 1 그대로 유지돼야 한다.
# ★_THOUSAND_SHARES_XML 에서 "천주"만 "주"로 바꾸면 비고 "2억주"가 (지금은 액면
#   그대로인) 200,000 과 모순돼(200,000주 ≠ 2억주) 교차검증이 오히려 ×1000 을 정답으로
#   가리키는 자기모순 픽스처가 된다 — 비고도 액면에 맞게 새로 쓴다.
_EXPLICIT_WON_UNIT_XML = """<XML>
<TABLE-GROUP>
4. 주식의 총수 등
가. 주식의 총수 현황
<TABLE>
<TR><TD>(기준일 : 2026.06.30 )</TD><TD>(단위 : 주, %)</TD></TR>
</TABLE>
<TABLE>
<TR><TD>구 분</TD><TD>보통주</TD><TD>우선주</TD><TD>합계</TD><TD>비고</TD></TR>
<TR><TD>Ⅰ. 발행할 주식의 총수</TD><TD>200,000</TD><TD>-</TD><TD>200,000</TD>
    <TD>정관상 발행 가능한 주식 총수 : 200,000주</TD></TR>
<TR><TD>Ⅱ. 현재까지 발행한 주식의 총수</TD><TD>115,742</TD><TD>-</TD><TD>115,742</TD><TD></TD></TR>
<TR><TD>Ⅲ. 현재까지 감소한 주식의 총수</TD><TD>6,600</TD><TD>-</TD><TD>6,600</TD><TD></TD></TR>
<TR><TD>Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)</TD><TD>109,142</TD><TD>-</TD><TD>109,142</TD><TD></TD></TR>
</TABLE>
</TABLE-GROUP>
</XML>"""

# 일승 01396676 20260814000008 실측 축약본 — 캡션은 "천주"인데 실제 인쇄된 숫자는
# "주" 단위(원문 자체의 오탈자 캡션). 프로즈·Ⅰ행 둘 다 배수 1 을 가리킨다.
_MISLABELED_CAPTION_XML = """<XML>
<TABLE-GROUP>
4. 주식의 총수 등
가. 주식의 총수 현황
2026년 6월 30일 현재 당사의 발행가능한 주식의 총수는 500,000,000주이며,
발행한 주식의 총수는 보통주 30,726,747주입니다.
<TABLE>
<TR><TD>(기준일 : 2026년 06월 30일 )</TD><TD>(단위 : 천주, %)</TD></TR>
</TABLE>
<TABLE>
<TR><TD>구 분</TD><TD>보통주</TD><TD>우선주</TD><TD>합계</TD><TD>비고</TD></TR>
<TR><TD>Ⅰ. 발행할 주식의 총수</TD><TD>500,000,000</TD><TD>-</TD><TD>500,000,000</TD><TD></TD></TR>
<TR><TD>Ⅱ. 현재까지 발행한 주식의 총수</TD><TD>30,726,747</TD><TD>-</TD><TD>30,726,747</TD><TD></TD></TR>
<TR><TD>Ⅲ. 현재까지 감소한 주식의 총수</TD><TD>-</TD><TD>-</TD><TD>-</TD><TD></TD></TR>
<TR><TD>Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)</TD><TD>30,726,747</TD><TD>-</TD><TD>30,726,747</TD><TD></TD></TR>
</TABLE>
</TABLE-GROUP>
</XML>"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "doc.xml"
    p.write_text(content, encoding="utf-8")
    return p


def test_thousand_shares_unit_is_multiplied_by_1000(tmp_path):
    """R90 핵심 — "(단위 : 천주, %)" 표는 인쇄된 숫자에 ×1000 해야 실제 주식수가 된다
    (현대로템 실측: 200,000천주 = 2억주, 비고란과 일치 검증됨)."""
    path = _write(tmp_path, _THOUSAND_SHARES_XML)
    shares, label = extract_issued_common_shares_detailed(path)
    assert shares == 109_142_000
    assert label == "발행주식의 총수"


def test_plain_shares_unit_is_not_multiplied(tmp_path):
    """단위 선언이 없는(다수) 서식은 기존 그대로 배수 1 — 회귀 방지."""
    path = _write(tmp_path, _PLAIN_SHARES_XML)
    shares, label = extract_issued_common_shares_detailed(path)
    assert shares == 16_027_989
    assert label == "발행주식의 총수"


def test_explicit_share_unit_is_not_multiplied(tmp_path):
    """"단위 : 주"(천주 아님)로 명시된 경우는 배수 1 — "천주"만 특별 취급한다."""
    path = _write(tmp_path, _EXPLICIT_WON_UNIT_XML)
    shares, _ = extract_issued_common_shares_detailed(path)
    assert shares == 109_142


def test_mislabeled_thousand_caption_is_overridden_by_prose_corroboration(tmp_path):
    """★핵심 회귀 — 캡션이 "천주"라도 프로즈/표 안 Ⅰ행이 배수 1 을 가리키면 캡션을
    무시한다(일승 01396676 실측: 캡션만 믿었다면 30,726,747,000 이라는 새 불가값을
    만들 뻔했다, 2026-09-09 이 수정 검증 중 발견)."""
    path = _write(tmp_path, _MISLABELED_CAPTION_XML)
    shares, label = extract_issued_common_shares_detailed(path)
    assert shares == 30_726_747
    assert label == "발행주식의 총수"


def test_mislabeled_caption_confirmed_via_row2_when_row4_is_arithmetic(tmp_path):
    """★핵심 회귀 — 한일철강 00163196 실측: Ⅳ(발행주식의 총수=Ⅱ−Ⅲ)는 산술값이라 프로즈에
    거의 안 나온다. 프로즈는 Ⅰ/Ⅱ/Ⅲ 만 restate 하므로, Ⅳ 자체를 프로즈와 직접 대조하면
    (Ⅳ=26,697,460 은 어디에도 평문으로 안 나옴) 교차검증에 실패해 캡션("천주")을 그대로
    믿어 26,697,460,000 이라는 새 불가값을 만들 뻔했다(2026-09-09 발견). Ⅱ 로 표 전체
    배수를 확정하고 그걸 Ⅳ 에도 적용해야 한다."""
    content = """<XML>
<TABLE-GROUP>
4. 주식의 총수 등
액면분할 이후 발행할 주식의 총수는 60,000,000주이며 현재까지 발행한 주식의 총수는
보통주 39,061,040주, 현재까지 감소한주식의 총수는 12,363,580주(회사분할)입니다.
<TABLE>
<TR><TD>(기준일 : 2026.03.31 )</TD><TD>(단위 : 천주, %)</TD></TR>
</TABLE>
<TABLE>
<TR><TD>구 분</TD><TD>보통주</TD><TD>우선주</TD><TD>합계</TD><TD>비고</TD></TR>
<TR><TD>Ⅰ. 발행할 주식의 총수</TD><TD>60,000,000</TD><TD>-</TD><TD>60,000,000</TD><TD></TD></TR>
<TR><TD>Ⅱ. 현재까지 발행한 주식의 총수</TD><TD>39,061,040</TD><TD>-</TD><TD>39,061,040</TD><TD></TD></TR>
<TR><TD>Ⅲ. 현재까지 감소한 주식의 총수</TD><TD>12,363,580</TD><TD>-</TD><TD>12,363,580</TD><TD></TD></TR>
<TR><TD>Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)</TD><TD>26,697,460</TD><TD>-</TD><TD>26,697,460</TD><TD></TD></TR>
</TABLE>
</TABLE-GROUP>
</XML>"""
    path = _write(tmp_path, content)
    shares, label = extract_issued_common_shares_detailed(path)
    assert shares == 26_697_460
    assert label == "발행주식의 총수"


def test_distant_unrelated_unit_declaration_does_not_leak_in(tmp_path):
    """훨씬 앞선(창 밖) 무관한 표의 "천주" 선언은 물지 않는다 — 표에 직결된 캡션만 본다."""
    far_away = "(단위 : 천주)" + " " * 500  # _UNIT_WINDOW(400)보다 멀리 떨어뜨림
    content = _PLAIN_SHARES_XML.replace(
        "4. 주식의 총수 등", far_away + "\n4. 주식의 총수 등")
    path = _write(tmp_path, content)
    shares, _ = extract_issued_common_shares_detailed(path)
    assert shares == 16_027_989, "창 밖의 무관한 단위선언에 오염되면 안 된다"
