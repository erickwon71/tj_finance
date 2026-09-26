"""R162-d — SCE 행 내부 열 항등식 + 이중증거 회귀 테스트.

실측 근거(2026-09-25 표본 원문대조, `docs/qa/r162d_row_identity_handoff_2026-09-25.md`):
  - 흥국(`20230814000814`) 자본조정 — 교차-basis 증거로 참(true positive) 확인.
  - 이니텍(`20171114002176`) 확정급여채무의재측정요소 — 처음엔 SCE 원문표만 보고
    별도·연결이 다른 부호로 정상 인쇄된 오탐이라 의심했으나, IS 문(별도 basis 자체)에
    같은 개념이 이미 음수로 있어(같은-basis 앵커) 사실은 참으로 판명됐다(스크립트
    `verify_r162d_live_extraction.py` 참고). 다만 "손익결과 항목은 basis 간 부호가
    실제로 달라질 수 있으니 교차-basis SCE 증거만으로는 뒤집지 않는다"는 방어 원칙은
    이 케이스와 무관하게 유효해서(같은-basis 증거가 없는 가상 사례로) 아래
    `test_oci_remeasurement_cross_basis_only_rejected` 로 별도 검증한다.
  - 제이씨현시스템(`20210517000597`) 배당금지급 — 같은 행의 다른 항등식(중첩계층) 이미
    확정된 형제 칸이 유효한 증거(참).
  - 코아스템켐온(`20170515004679`) 당기순이익(손실) — 2칸짜리 단일 항등식은 서로가
    서로의 유일한 "증거"라 순환참조(증거 없음으로 스킵)여야 함.
"""
from __future__ import annotations

from fin2.extract.sce_sign_repair import repair_sce_row_identity


class _Line:
    """ReportLineRow 의 최소 대역 — 이 모듈이 읽는 속성만 갖는다."""

    def __init__(self, statement, basis, label_raw, value_won, *,
                 col_index=0, col_label=None, row_order=0, table_seq=0):
        self.statement = statement
        self.basis = basis
        self.label_raw = label_raw
        self.value_won = value_won
        self.col_index = col_index
        self.col_label = col_label
        self.row_order = row_order
        self.table_seq = table_seq


def _sce(lines, basis, row_order, col_label):
    (found,) = [l for l in lines if l.statement == "SCE" and l.basis == basis
                and l.row_order == row_order and l.col_label == col_label]
    return found


def test_treasury_stock_cross_basis_true_positive():
    """자본조정(자기주식) 잔액행 — 교차-basis SCE 증거만 있어도 자본거래/이월잔액이라 채택."""
    lines = [
        _Line("SCE", "consolidated", "2022.06.30 (기말자본)", 100, col_index=0,
              col_label="자본>자본금", row_order=5),
        _Line("SCE", "consolidated", "2022.06.30 (기말자본)", 50, col_index=1,
              col_label="자본>자본잉여금", row_order=5),
        _Line("SCE", "consolidated", "2022.06.30 (기말자본)", 30, col_index=2,
              col_label="자본>자본조정", row_order=5),                       # 원문 괄호 유실
        _Line("SCE", "consolidated", "2022.06.30 (기말자본)", 200, col_index=3,
              col_label="자본>이익잉여금", row_order=5),
        _Line("SCE", "consolidated", "2022.06.30 (기말자본)", 320, col_index=4,
              col_label="자본>자본 합계", row_order=5),
        # 별도 basis — 같은 자기주식/자본조정이 이미 음수로 확정(교차-basis 증거)
        _Line("SCE", "separate", "2022.06.30 (기말자본)", -30, col_index=2,
              col_label="자본>자본조정", row_order=5),
        _Line("SCE", "separate", "2022.06.30 (기말자본)", 320, col_index=4,
              col_label="자본>자본 합계", row_order=5),
    ]
    fixes = repair_sce_row_identity(lines)
    assert _sce(lines, "consolidated", 5, "자본>자본조정").value_won == -30
    assert any(f.col_label == "자본>자본조정" and f.basis == "consolidated" for f in fixes)


def test_oci_remeasurement_cross_basis_only_rejected():
    """손익결과(재측정요소) 행 — 교차-basis SCE 증거뿐이면 뒤집지 않는다(방어적 원칙;
    가상 사례 — 실측 이니텍 케이스는 같은-basis IS 앵커가 따로 있어 참으로 확정됨)."""
    lines = [
        # 별도: 이익잉여금은 이전 규칙이 이미(잘못) 음수로 뒤집어 둔 상태, 합계는 원문 그대로 양수.
        _Line("SCE", "separate", "확정급여채무의재측정요소", -942, col_index=0,
              col_label="자본>이익잉여금", row_order=2),
        _Line("SCE", "separate", "확정급여채무의재측정요소", 942, col_index=1,
              col_label="자본>자본 합계", row_order=2),
        # 연결: 같은 금액이 음수(교차-basis 증거) — 그러나 손익결과 항목이라 인정하지 않는다.
        _Line("SCE", "consolidated", "확정급여제도의 재측정요소", -942, col_index=0,
              col_label="자본>이익잉여금", row_order=3),
        _Line("SCE", "consolidated", "확정급여제도의 재측정요소", -942, col_index=1,
              col_label="자본>자본 합계", row_order=3),
    ]
    fixes = repair_sce_row_identity(lines)
    assert _sce(lines, "separate", 2, "자본>자본 합계").value_won == 942   # 그대로(미수정)
    assert not any(f.basis == "separate" and f.row_order == 2 for f in fixes)


def test_dividend_nested_hierarchy_same_row_evidence():
    """배당금지급 — 중첩계층에서 안쪽(지배기업 소유주 귀속분)이 이미 확정돼 있으면
    바깥(전체 자본 합계)의 유효한 증거가 된다(같은 행이라도 다른 항등식이면 순환이 아니다)."""
    lines = [
        _Line("SCE", "consolidated", "배당금지급", -500, col_index=0,
              col_label="자본>지배기업의 소유주에게 귀속되는 자본>이익잉여금", row_order=11),
        _Line("SCE", "consolidated", "배당금지급", -500, col_index=1,
              col_label="자본>지배기업의 소유주에게 귀속되는 자본>지배기업의 소유주에게 귀속되는 자본 합계",
              row_order=11),
        _Line("SCE", "consolidated", "배당금지급", 0, col_index=2,
              col_label="자본>비지배지분", row_order=11),
        _Line("SCE", "consolidated", "배당금지급", 500, col_index=3,
              col_label="자본>자본 합계", row_order=11),                     # 원문 괄호 유실
    ]
    fixes = repair_sce_row_identity(lines)
    assert _sce(lines, "consolidated", 11, "자본>자본 합계").value_won == -500
    assert any(f.col_label == "자본>자본 합계" for f in fixes)


def test_two_column_identity_is_circular_no_external_evidence():
    """당기순이익(손실) — 2칸(이익잉여금/합계)짜리 단일 항등식은 서로가 서로의 유일한
    "증거"라 순환참조다. 이 행 밖에 독립 증거가 없으면 손대지 않는다."""
    lines = [
        _Line("SCE", "separate", "당기순이익(손실)", 2_690_748_354, col_index=0,
              col_label="자본>이익잉여금", row_order=11),
        _Line("SCE", "separate", "당기순이익(손실)", -2_690_748_354, col_index=1,
              col_label="자본>자본 합계", row_order=11),
    ]
    fixes = repair_sce_row_identity(lines)
    assert _sce(lines, "separate", 11, "자본>이익잉여금").value_won == 2_690_748_354  # 미수정
    assert fixes == []


def test_note_lines_evidence_gated_by_capital_transaction_too():
    """주석뿐인 증거도 교차-basis 증거와 동일하게 자본거래/이월잔액 행에만 인정한다."""
    lines = [
        _Line("SCE", "separate", "지분법자본변동", 942, col_index=0,
              col_label="자본>이익잉여금", row_order=25),
        _Line("SCE", "separate", "지분법자본변동", -942, col_index=1,
              col_label="자본>자본 합계", row_order=25),
        # 이 행 밖 주석에 같은 금액이 음수로 존재 — 그러나 '지분법자본변동'은
        # 손익결과라 주석 증거만으로는 인정하지 않는다.
        _Line("note", "separate", "지분법이익", -942, col_index=0, row_order=99),
    ]
    fixes = repair_sce_row_identity(lines)
    assert fixes == []


# ── R185: column-consistency guard (도이치모터스 `20110516003437` shape) ──────────
_COLS = {0: "자본>자본금", 1: "자본>자본조정", 2: "자본>이익잉여금", 3: "자본>자본 합계"}


def _row(ro, label, vals):
    return [_Line("SCE", "separate", label, v, col_index=ci, col_label=_COLS[ci], row_order=ro)
            for ci, v in vals.items()]


def _partial_evidence_table(movement=10, opening=40, closing=50):
    total = lambda cap, adj, re_: cap - adj + re_          # noqa: E731 — true (negative) 자본조정
    return (
        _row(0, "2010.01.01 (기초자본)", {0: 100, 1: opening, 2: 50, 3: total(100, opening, 50)})
        + _row(1, "합병으로 인한 증가", {0: 10, 1: movement})
        + _row(2, "당기순이익", {2: 20, 3: 20})
        + _row(3, "2010.12.31 (기말자본)", {0: 110, 1: closing, 2: 70, 3: total(110, closing, 70)})
        + _row(4, "2011.01.01 (기초자본)", {0: 110, 1: closing, 2: 70, 3: total(110, closing, 70)})
        + _row(5, "2011.03.31 (기말자본)", {0: 110, 1: closing, 2: 70, 3: total(110, closing, 70)})
        # BS prints the closing balance in parentheses — evidence for `closing` only.
        + [_Line("BS", "separate", "자본조정", -closing)]
    )


def test_r185_extends_partial_flip_to_the_whole_column():
    lines = _partial_evidence_table()
    fixes = repair_sce_row_identity(lines)
    col = {ro: _sce(lines, "separate", ro, "자본>자본조정").value_won for ro in (0, 1, 3, 4, 5)}
    assert col == {0: -40, 1: -10, 3: -50, 4: -50, 5: -50}
    assert sum(f.anchor_label == "R185 열일관성 확장" for f in fixes) == 2


def test_r185_keeps_proven_flips_when_the_whole_column_does_not_close():
    # A real negative movement: flipping every positive cell can no longer close the block.
    # R162-d's flips are each proven on their own, so they stay; nothing is extended.
    lines = _partial_evidence_table(movement=-10, opening=40, closing=30)
    fixes = repair_sce_row_identity(lines)
    col = {ro: _sce(lines, "separate", ro, "자본>자본조정").value_won for ro in (0, 1, 3, 4, 5)}
    assert col == {0: 40, 1: -10, 3: -30, 4: -30, 5: -30}
    assert not [f for f in fixes if f.anchor_label == "R185 열일관성 확장"]


def test_r185_leaves_flips_alone_when_no_closed_block_breaks():
    # Evidence for every balance, no movement: R162-d flips them all, blocks stay closed.
    lines = _partial_evidence_table(movement=0, opening=50, closing=50)
    repair_sce_row_identity(lines)
    col = {ro: _sce(lines, "separate", ro, "자본>자본조정").value_won for ro in (0, 3, 4, 5)}
    assert col == {0: -50, 3: -50, 4: -50, 5: -50}
