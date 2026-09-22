"""R163 — CF 현금 조정 구간의 원문 부호 누락 복원 회귀 테스트.

실측 근거는 한화오션 `20180330001629`(2017FY, [별도] CF). 캠페인 이슈#29.
`docs/PARSING_RULES.md` R163.
"""
from __future__ import annotations

from fin2.extract.cf_cash_sign_repair import repair_cf_cash_sign_loss


class _Line:
    def __init__(self, statement, basis, label_raw, value_won, *,
                 col_index=0, row_order=0, table_seq=0):
        self.statement = statement
        self.basis = basis
        self.label_raw = label_raw
        self.value_won = value_won
        self.col_index = col_index
        self.row_order = row_order
        self.table_seq = table_seq


def _cf(rows, *, basis="separate", col_index=0):
    return [_Line("CF", basis, label, value,
                  col_index=col_index, row_order=order)
            for order, label, value in rows]


def _hanwha():
    """한화오션 별도 CF 당기 열 — 환율변동효과만 부호를 잃었다."""
    return _cf([
        (57, "현금및현금성자산의 증가(감소)", 16_367_553_617),
        (58, "기초의 현금및현금성자산", 144_292_901_261),
        (59, "외화표시 현금및현금성자산의 환율변동효과", 521_074_352),
        (60, "기말의 현금및현금성자산", 160_139_380_526),
    ])


def test_restores_fx_effect_cell():
    lines = _hanwha()
    fixes = repair_cf_cash_sign_loss(lines)
    assert len(fixes) == 1
    assert fixes[0].old_value == 521_074_352
    assert fixes[0].new_value == -521_074_352
    assert lines[2].value_won == -521_074_352


def test_identity_closes_after_repair():
    lines = _hanwha()
    repair_cf_cash_sign_loss(lines)
    net, opening, fx, closing = (l.value_won for l in lines)
    assert opening + net + fx == closing


def test_correction_records_the_identity():
    """교정 내역에 항등식 문자열을 담는다 — 사람이 그대로 검산할 수 있게."""
    fixes = repair_cf_cash_sign_loss(_hanwha())
    assert "160,139,380,526" in fixes[0].identity


def test_repair_is_idempotent():
    lines = _hanwha()
    assert len(repair_cf_cash_sign_loss(lines)) == 1
    assert repair_cf_cash_sign_loss(lines) == []


# --------------------------------------------------------------------------
# 손대지 않는 경우
# --------------------------------------------------------------------------

def test_positive_fx_effect_is_normal_and_untouched():
    """★환율변동효과는 **양수가 정상인 경우가 더 많다**(2015+ 양수 114,412셀).

    부호만 보고 뒤집으면 멀쩡한 데이터를 대량으로 망친다 — 항등식이 닫히면 손대지
    않는다는 것을 고정한다. 한화오션 비교연도 열이 실제로 이 경우다.
    """
    lines = _cf([
        (57, "현금및현금성자산의 증가(감소)", -930_201_067_779),
        (58, "기초의 현금및현금성자산", 1_072_187_331_380),
        (59, "외화표시 현금및현금성자산의 환율변동효과", 2_306_637_660),
        (60, "기말의 현금및현금성자산", 144_292_901_261),
    ])
    assert repair_cf_cash_sign_loss(lines) == []
    assert lines[2].value_won == 2_306_637_660


def test_missing_row_means_no_repair():
    """4행을 다 못 찾으면 손대지 않는다(순증감 행 없음)."""
    lines = _cf([
        (58, "기초의 현금및현금성자산", 100),
        (59, "현금및현금성자산의 환율변동효과", 30),
        (60, "기말의 현금및현금성자산", 70),
    ])
    assert repair_cf_cash_sign_loss(lines) == []


def test_ambiguous_single_flip_is_rejected():
    """단일 셀 뒤집기로 닫히는 후보가 둘이면 판정불가 — 손대지 않는다."""
    # 순증감과 환율효과가 같은 값이면 어느 쪽을 뒤집어도 같은 결과가 된다.
    lines = _cf([
        (57, "현금및현금성자산의 증가(감소)", 50),
        (58, "기초의 현금및현금성자산", 100),
        (59, "현금및현금성자산의 환율변동효과", 50),
        (60, "기말의 현금및현금성자산", 100),
    ])
    assert repair_cf_cash_sign_loss(lines) == []


def test_unclosable_identity_is_left_alone():
    """뒤집어도 안 닫히면 다른 원인이다 — 추측하지 않는다."""
    lines = _cf([
        (57, "현금및현금성자산의 증가(감소)", 7),
        (58, "기초의 현금및현금성자산", 100),
        (59, "현금및현금성자산의 환율변동효과", 3),
        (60, "기말의 현금및현금성자산", 999),
    ])
    assert repair_cf_cash_sign_loss(lines) == []


def test_negative_cash_balance_is_refused():
    """현금 잔액이 음수인 표는 우리가 이해한 구조가 아니다 — 손대지 않는다."""
    lines = _cf([
        (57, "현금및현금성자산의 증가(감소)", 10),
        (58, "기초의 현금및현금성자산", -100),
        (59, "현금및현금성자산의 환율변동효과", 5),
        (60, "기말의 현금및현금성자산", -95),
    ])
    assert repair_cf_cash_sign_loss(lines) == []


def test_pre_fx_net_change_is_not_mistaken_for_fx_row():
    """'환율변동효과 **반영전** … 순증가(감소)' 는 순증감 행이고 환율효과 행이 아니다.

    두 행이 다 '환율변동' 을 포함하므로 배제 규칙이 없으면 환율효과 행 식별이
    중복되어(_pick 이 2건 → None) 아무것도 못 고친다. 실측 에이루트 20190814001339.
    """
    lines = _cf([
        (37, "환율변동효과 반영전 현금및현금성자산의 순증가(감소)", 29_687_530_915),
        (38, "현금및현금성자산에 대한 환율변동효과", 108_087_203),
        (39, "기초현금및현금성자산", 9_250_555_514),
        (40, "기말현금및현금성자산", 38_829_999_226),
    ])
    fixes = repair_cf_cash_sign_loss(lines)
    assert len(fixes) == 1
    assert fixes[0].label_raw == "현금및현금성자산에 대한 환율변동효과"
    assert lines[1].value_won == -108_087_203


def test_only_cf_is_modified():
    """BS/IS/SCE 는 건드리지 않는다."""
    lines = _hanwha() + [
        _Line("SCE", "separate", "기초의 현금및현금성자산", 144_292_901_261),
        _Line("BS", "separate", "현금및현금성자산", 160_139_380_526),
    ]
    repair_cf_cash_sign_loss(lines)
    assert lines[-1].value_won == 160_139_380_526
    assert lines[-2].value_won == 144_292_901_261


def test_columns_are_independent():
    """열마다 따로 판정한다 — 당기가 깨졌어도 비교연도 열은 그대로 둔다."""
    lines = _hanwha() + _cf([
        (57, "현금및현금성자산의 증가(감소)", -930_201_067_779),
        (58, "기초의 현금및현금성자산", 1_072_187_331_380),
        (59, "외화표시 현금및현금성자산의 환율변동효과", 2_306_637_660),
        (60, "기말의 현금및현금성자산", 144_292_901_261),
    ], col_index=1)
    fixes = repair_cf_cash_sign_loss(lines)
    assert [f.col_index for f in fixes] == [0]
