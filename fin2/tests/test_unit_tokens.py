"""단위 선언 토큰화 + 열별 단위 귀속 회귀 테스트 (F1, 2026-07-31).

고정하는 계약 — 전수 census(`docs/qa/unit_declaration_census_2026-07-30.md`)가 실측한 결함이
다시 들어오지 않게 하는 것이 목적이다:

  ① '(단위 : 주, 천원)' 처럼 **금액 토큰이 선두가 아니어도** 금액 표로 인식한다 (2.63M 셀 유실)
  ② '(단위 : 천 원)' 자간 공백을 인식한다
  ③ 혼합 선언에서 **비금액 열에 value_won 을 채우지 않는다** (DB 실측 6,130,738 행 오염)
  ④ 서술문('… 단위 사업부문별로 백만원 …')을 선언으로 오인하지 않는다 (오염 방지 — 신규 위험)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.units import (ColumnUnits, MIXED, MONEY_ONLY, NON_MONEY_ONLY,  # noqa: E402
                                UNDECLARED, classify_tokens)
from parser.common.amount_normalizer import (detect_unit_declaration,  # noqa: E402
                                             detect_unit_tokens)


# ── ① 금액 토큰의 위치 ──────────────────────────────────────────────────
def test_money_token_not_first():
    assert detect_unit_tokens("(단위 : 주, 천원)") == ["주", "천원"]
    assert detect_unit_declaration("(단위 : 주, 천원)") == 1_000
    assert detect_unit_declaration("(단위 : 건, 백만원)") == 1_000_000
    assert detect_unit_declaration("(단위 : 매, 백만원)") == 1_000_000


def test_money_only_unchanged():
    for text, mult in (("(단위 : 천원)", 1_000), ("단위:백만원", 1_000_000),
                       ("(단위 : 원)", 1), ("(단위: 억원)", 100_000_000),
                       ("(단위 : 만원)", 10_000)):
        assert detect_unit_declaration(text) == mult, text


# ── ② 자간 공백 ─────────────────────────────────────────────────────────
def test_spaced_money_token():
    assert detect_unit_declaration("(단위 : 천 원)") == 1_000
    assert detect_unit_declaration("(단위 : 백 만 원)") == 1_000_000
    # '주 원' 은 두 개의 단위다 — 붙여서 없는 단위를 만들지 않는다.
    assert detect_unit_tokens("(단위 : 주, 원)") == ["주", "원"]


# ── 비금액 단독 ─────────────────────────────────────────────────────────
def test_non_monetary_only():
    for text in ("(단위 : %)", "(단위: 주)", "(단위 : 명)", "(단위 : 톤)"):
        assert detect_unit_declaration(text) is None, text
        assert detect_unit_tokens(text), text            # 선언은 있다(비금액일 뿐)
        assert classify_tokens(detect_unit_tokens(text)) == NON_MONEY_ONLY


def test_per_share_is_money():
    # '원/주' = 주당 금액. 배수는 앞의 금액 단위가 정한다.
    assert detect_unit_declaration("(단위 : 원/주)") == 1
    assert classify_tokens(detect_unit_tokens("(단위 : 원/주)")) == MONEY_ONLY


# ── ④ 서술문을 선언으로 오인하지 않기(신규 위험 — 오염 방향) ────────────
def test_prose_is_not_declaration():
    for text in ("회사는 단위 사업부문별로 백만원 이상의 매출을 인식하고 있습니다.",
                 "단위적립방식에 따라 백만원 단위로 반영",
                 "현금흐름단위의 회수가능액은 천원 단위로 측정되었으며 손상징후는 없습니다."):
        assert detect_unit_declaration(text) is None, text
        assert detect_unit_tokens(text) == [], text


def test_foreign_currency_list_declaration():
    """'(원화단위:천원 외화단위:천USD,천JPY,천EUR)' — 통화 나열 선언.

    실측 유실 3종을 한꺼번에 고정한다(구·신 차분에서 표 19 개 유실로 잡힌 것):
      · '천USD' 처럼 한글+영문이 섞인 토큰      · 토큰 7 개 이상   · '대상:단위' 짝
    """
    toks = detect_unit_tokens("(원화단위:천원 외화단위:천USD,천JPY,천EUR)")
    assert toks == ["천원", "천USD", "천JPY", "천EUR"], toks
    assert detect_unit_declaration("(원화단위:천원 외화단위:천USD,천JPY,천EUR)") == 1_000
    assert detect_unit_declaration("(단위: 천원, USD, 천JPY, EUR, NZD, CNY, AUD)") == 1_000


def test_label_colon_unit_pairs():
    """'대상 : 단위' 에서 대상 이름은 단위가 아니다 — 단, 왼쪽이 단위면 버리지 않는다."""
    assert detect_unit_tokens("(단위 : 천원, 주당순이익 : 원)") == ["천원", "원"]
    assert detect_unit_declaration("(단위: 천원/USD : $)") == 1_000   # 왼쪽 '천원/USD' 보존


def test_foreign_only_table_has_no_won_unit():
    """'(단위: USD)' 표는 원 단위 금액이 아니다 — 옆 표의 '천원' 을 주워오면 오염이다."""
    assert detect_unit_declaration("(단위: USD)") is None
    assert classify_tokens(detect_unit_tokens("(단위: USD)")) == NON_MONEY_ONLY


def test_no_declaration_at_all():
    assert detect_unit_tokens("연결 재무상태표 제33기") == []
    assert detect_unit_declaration("") is None
    assert classify_tokens([]) == UNDECLARED


# ── ③ 열별 귀속 ─────────────────────────────────────────────────────────
def test_mixed_declaration_blocks_non_money_column():
    """'(단위 : 천원, USD)' — USD·이자율 열에 value_won 을 채우지 않는다."""
    cu = ColumnUnits.from_declaration(
        "(단위 : 천원, USD)",
        {0: "당분기말>장부금액", 1: "당분기말>이자율(%)", 2: "USD 금액"})
    assert cu.kind == MIXED
    assert cu.multiplier(0) == 1_000
    assert cu.multiplier(1) is None and cu.source(1) == "non_monetary"
    assert cu.multiplier(2) is None and cu.source(2) == "non_monetary"


def test_money_only_declaration_still_blocks_rate_column():
    """금액단독 선언이어도 열 헤더가 '이자율(%)' 이면 채우지 않는다 — 오염 6.13M 행의 정체."""
    cu = ColumnUnits.from_declaration("(단위: 천원)", {0: "차입금", 1: "이자율(%)", 2: "지분율"})
    assert cu.kind == MONEY_ONLY
    assert cu.multiplier(0) == 1_000 and cu.source(0) == "declared"
    assert cu.multiplier(1) is None and cu.source(1) == "non_monetary"
    assert cu.multiplier(2) is None


def test_money_only_without_headers_keeps_old_behavior():
    """열 헤더를 복원하지 못한 금액단독 표는 종전대로 전 열에 배수를 적용한다(회귀 방지)."""
    cu = ColumnUnits.from_declaration("(단위 : 백만원)", {})
    assert [cu.multiplier(i) for i in range(3)] == [1_000_000] * 3
    assert cu.source(0) == "declared"


def test_mixed_requires_positive_evidence():
    """혼합 선언 + 헤더가 침묵 → 확정 못 함(NULL). value_raw 로 원문을 남기는 전제."""
    cu = ColumnUnits.from_declaration("(단위 : 주, 천원)", {0: "기초", 1: "증가"})
    assert cu.kind == MIXED
    assert cu.multiplier(0) is None and cu.source(0) == "undetermined"
    cu2 = ColumnUnits.from_declaration("(단위 : 주, 천원)", {0: "주식수", 1: "금액"})
    assert cu2.multiplier(0) is None and cu2.source(0) == "non_monetary"
    assert cu2.multiplier(1) == 1_000 and cu2.source(1) == "col_money"


def test_maturity_bucket_columns_are_money():
    """유동성위험 만기분석: '6개월이내'·'1-2년' 칸은 **금액**이다 — 기간 표지를 비금액으로
    보면 이 표들의 금액이 통째로 NULL 이 된다(초안에서 실제로 그랬다)."""
    cu = ColumnUnits.from_declaration(
        "(단위:천원)", {0: "장부금액", 1: "6개월이내", 2: "6-12개월", 3: "1-2년"})
    assert all(cu.multiplier(i) == 1_000 for i in range(4))


def test_col_label_hangul_gaps_are_normalized():
    """DART 는 한글 자간에 공백을 넣는다 — '지 분 율' 을 못 잡으면 오염이 그대로 통과한다."""
    cu = ColumnUnits.from_declaration("(단위 : 주,천원)", {0: "금 액", 1: "지 분 율"})
    assert cu.multiplier(1) is None and cu.source(1) == "non_monetary"
    assert cu.multiplier(0) == 1_000            # '금 액' → 금액


def test_unit_declaration_segment_is_not_a_column_marker():
    """열 라벨 접두의 단위 선언은 **표의 사실**이다 — 그걸 열 성격으로 읽으면 오판한다.

    실측: '(원화단위: 백만원, 외화단위: 백만단위)>당기출자약정금' 의 '외화' 때문에 원화 금액
    열이 비워졌다(71 행). 선언 단을 버리고 나면 '…금' 으로 끝나므로 금액이다.
    """
    cu = ColumnUnits.from_declaration(
        "(원화단위: 백만원, 외화단위: 백만단위)",
        {0: "(원화단위: 백만원, 외화단위: 백만단위)>당기출자약정금"})
    assert cu.kind == MIXED
    assert cu.multiplier(0) == 1_000_000 and cu.source(0) == "col_money"


def test_foreign_currency_amount_column_is_not_won():
    """'계약금액($)' 은 USD 금액이다 — '금액' 이라는 말에 속아 천원 배수를 걸면 오염이다."""
    cu = ColumnUnits.from_declaration("(단위 : 천원)", {0: "당 반 기 말>계약금액($)"})
    assert cu.multiplier(0) is None and cu.source(0) == "non_monetary"


def test_percent_in_scenario_label_is_not_a_rate_column():
    """'10%상승'(환위험 민감도 시나리오)은 **천원 금액** 열이다 — '%' 만으로 비우면 유실."""
    cu = ColumnUnits.from_declaration("(단위 : 천원)", {0: "당반기말>10%상승"})
    assert cu.multiplier(0) == 1_000 and cu.source(0) == "declared"


def test_undeclared_table_yields_no_value():
    cu = ColumnUnits.from_declaration(None, {0: "소유주식수(주)", 1: "지분율(%)"})
    assert cu.kind == UNDECLARED
    assert cu.multiplier(0) is None and cu.source(0) == "undeclared"


def test_non_money_table_yields_no_value():
    cu = ColumnUnits.from_declaration("(단위 : 주)", {0: "기초", 1: "기말"})
    assert cu.kind == NON_MONEY_ONLY
    assert cu.multiplier(1) is None and cu.source(1) == "non_monetary"


if __name__ == "__main__":
    from tests._util import run_tests
    sys.exit(1 if run_tests(globals()) else 0)


# ── D1 · 선언 전용 표에서만 단위를 상속한다 (2026-07-31 사용자 결정) ────────────
def _tbl(xml: str):
    from lxml import etree
    return etree.fromstring(xml)


_DECL_ONLY = "<TABLE><TR><TD>(단위: 천원)</TD></TR></TABLE>"
# ★기간 표기('당기말' 등)를 넣지 않는다 — 그러면 `_is_metadata_only` 가 이 표를 메타로 보고
#   기존 (3) 경로가 이미 건너뛰어, 새 상속 규칙을 시험하지 못한다(초판 테스트가 그랬다).
_DATA = ("<TABLE><TR><TD>구분</TD><TD>금액</TD></TR>"
         "<TR><TD>매입채무및기타채무</TD><TD>3,855,977</TD></TR>"
         "<TR><TD>단기차입금</TD><TD>14,420,000</TD></TR></TABLE>")


def test_inherit_from_declaration_only_table_across_empty_sibling():
    """[선언표][데이터표A][빈 P][데이터표B] — B 가 A 와 같은 선언을 상속한다.

    실측 서식(20230515001080 8.범주별 금융상품)에서 B 가 단위를 잃던 자리다.
    """
    from fin2.extract.text import declaration_text, inherited_declaration_text
    root = _tbl(f"<BODY><P>(1) 내역은 다음과 같습니다.</P>{_DECL_ONLY}{_DATA}<P></P>{_DATA}</BODY>")
    b = root[4]
    assert declaration_text(b) is None            # 자기 선언은 없다
    assert "천원" in (inherited_declaration_text(b) or "")


def test_no_inherit_across_text_paragraph():
    """사이에 **문장이 있는 <P>** 가 있으면 새 소항목이므로 상속하지 않는다.

    실측 반례(20230512001205): '(단위 : 원/주)' 선언표 뒤 데이터표 다음에 설명 <P> 가 오고
    그 뒤가 **주식 적수 표**다. 여기서 상속하면 주식수에 금액 단위가 붙는다.
    """
    from fin2.extract.text import inherited_declaration_text
    root = _tbl(f"<BODY>{_DECL_ONLY}{_DATA}<P>(*) 가중평균유통보통주식수의 산출근거입니다.</P>{_DATA}</BODY>")
    assert inherited_declaration_text(root[3]) is None


def test_no_inherit_from_a_data_table_declaration():
    """앞 표가 **데이터표**면(그 표 자신의 표제에 선언이 있어도) 상속하지 않는다 —
    상속 근거는 '선언 전용 표'라는 원문 구조 사실 하나뿐이다."""
    from fin2.extract.text import inherited_declaration_text
    data_with_decl = ("<TABLE><TR><TD>(단위: 백만원)</TD></TR>"
                      "<TR><TD>가</TD><TD>1,000</TD></TR><TR><TD>나</TD><TD>2,000</TD></TR></TABLE>")
    root = _tbl(f"<BODY>{data_with_decl}<P></P>{_DATA}</BODY>")
    # 데이터표는 건너뛰기만 하고, 그 앞에 선언 전용 표가 없으므로 근거 없음
    assert inherited_declaration_text(root[2]) is None


def test_inherited_unit_still_blocks_non_money_columns():
    """상속한 단위에도 비금액 열 차단은 그대로 적용되고, 근거는 'inherited' 로 표시된다."""
    cu = ColumnUnits.from_declaration("(단위: 천원)", {0: "장부금액", 1: "지분율(%)"},
                                      inherited=True)
    assert cu.multiplier(0) == 1_000 and cu.source(0) == "inherited"
    assert cu.multiplier(1) is None and cu.source(1) == "non_monetary"


def test_inherit_from_declaration_bearing_paragraph():
    """항목 도입 문단이 단위를 선언하면 그 아래 **두 번째 데이터표**도 상속한다(D1 보완).

    항목 내 관장 선언의 94%가 이 모양이다(표본 400 filing: 문단 667표 vs 선언전용표 68표).
    """
    from fin2.extract.text import inherited_declaration_text
    intro = "<P>(2) 담보로 제공된 자산의 내역은 다음과 같습니다. (단위: 천원)</P>"
    root = _tbl(f"<BODY>{intro}{_DATA}<P></P>{_DATA}</BODY>")
    assert "천원" in (inherited_declaration_text(root[3]) or "")


def test_no_inherit_across_statement_title():
    """재무제표명은 예외 — 남의 statement 경계다.

    엘브이엠씨 2019 사고(USD 기준 BS 표가 앞 '연결현금흐름표 단위:백만원' 을 주워 자산총계
    586조)가 이 경계를 넘었을 때 벌어진 일이다.
    """
    from fin2.extract.text import inherited_declaration_text
    title = "<P>연결 현금흐름표 제 33 기 (단위: 백만원)</P>"
    root = _tbl(f"<BODY>{title}{_DATA}<P></P>{_DATA}</BODY>")
    assert inherited_declaration_text(root[3]) is None
