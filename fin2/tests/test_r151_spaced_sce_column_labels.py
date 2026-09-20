"""R151(2026-09-20) 회귀 테스트 — SCE 열이름의 **자간 공백** 때문에 R148(표지 없는
물리분할표 이어붙이기)이 발동하지 못해 당기 롤포워드 표가 통째로 유실되던 결함.

DART 는 열이름에 자간을 벌려 넣는 서식을 흔히 쓴다:
    '과 목  자 본 금  자 본잉여금  기타포괄손익누계액  이 익잉여금  자기주식  총 계'
`_looks_like_equity_changes_header()` 가 원문 그대로 매칭해서 `자본금`·`자본잉여금`·
`이익잉여금` 이 전부 빗나가고, 공백 없는 `기타포괄손익누계액` 1개만 걸려 임계값(3)
미달로 False 가 됐다. 그러면 표지 없는 둘째 표(당기 롤포워드)를 SCE 로 물려받지 못한다.

실측: KB금융 20180814002480(2018H1) 별도 자본변동표 — 캠페인 원문전체대조 이슈#18.
R148 이 신한지주에서만 통했던 이유가 이것이다(신한지주 열이름엔 자간 공백이 없다).

실행: pytest fin2/tests/test_r151_spaced_sce_column_labels.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.extract.text as text_mod                          # noqa: E402
from fin2.extract.report_lines import extract_report_lines    # noqa: E402

_KB_2018H1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00688996_KB금융/half/2018/20180814002480.xml"
)


def _synthetic_header_table(header_cells: list[str]):
    """헤더 한 행만 든 최소 <TABLE> — 술어만 단위테스트하기 위한 것."""
    from lxml import etree
    tbl = etree.Element("TABLE")
    tbody = etree.SubElement(tbl, "TBODY")
    tr = etree.SubElement(tbody, "TR")
    for txt in header_cells:
        td = etree.SubElement(tr, "TD")
        td.text = txt
    return tbl


def test_spaced_column_labels_are_recognised():
    """자간이 벌어진 열이름도 SCE 헤더로 인정한다(KB금융 실측 서식)."""
    tbl = _synthetic_header_table(
        ["과 목", "자 본 금", "자 본잉여금", "기타포괄손익누계액", "이 익잉여금",
         "자기주식", "총 계"])
    assert text_mod._looks_like_equity_changes_header(tbl)


def test_unspaced_column_labels_still_recognised():
    """공백 없는 서식(신한지주류)도 그대로 인정한다 — 가산적 수정."""
    tbl = _synthetic_header_table(
        ["과목", "자본금", "신종자본증권", "자본잉여금", "자본조정",
         "기타포괄손익누계액", "이익잉여금", "총계"])
    assert text_mod._looks_like_equity_changes_header(tbl)


def test_non_sce_header_is_not_recognised():
    """자본 항목 열이름이 3개 미달이면 SCE 가 아니다(과잉 흡수 방지)."""
    tbl = _synthetic_header_table(
        ["과 목", "제 11 기 반기", "제 10 기 반기", "제 10 기", "제 9 기"])
    assert not text_mod._looks_like_equity_changes_header(tbl)
    # 자본금 하나만 있는 재무상태표 머리행도 아니다.
    tbl2 = _synthetic_header_table(["과 목", "자 본 금", "금액"])
    assert not text_mod._looks_like_equity_changes_header(tbl2)


def test_kb_2018h1_separate_sce_current_period_recovered():
    """별도 자본변동표의 당기(2018.6.30) 롤포워드 표가 복원되고, 그 마지막 행의 자본
    구성요소가 재무상태표 당기 값과 일치한다."""
    if not _KB_2018H1.exists():
        return
    lines = extract_report_lines(
        _KB_2018H1, rcept_no="20180814002480", corp_code="00688996",
        report_fiscal_year=2018, report_fiscal_period="H1")

    sce_sep = [l for l in lines if l.statement == "SCE" and l.basis == "separate"]
    assert {l.table_seq for l in sce_sep} == {0, 1}, \
        sorted({l.table_seq for l in sce_sep})

    # 둘째 표(당기) 마지막 라벨 = 2018.6.30(당반기말)
    seq1 = [l for l in sce_sep if l.table_seq == 1]
    labels = []
    for l in seq1:
        if l.label_raw not in labels:
            labels.append(l.label_raw)
    assert "2018.6.30" in labels[-1].replace(" ", ""), labels[-1]

    # 그 행의 자본금/자본잉여금이 재무상태표 당기 값과 같다(독립 교차검증).
    last = [l.value_won for l in seq1 if l.label_raw == labels[-1]]
    bs = {l.label_raw: l.value_won for l in lines
          if l.statement == "BS" and l.basis == "separate" and l.col_index == 0}
    assert bs["Ⅰ. 자본금"] in last
    assert bs["Ⅱ. 자본잉여금"] in last

    # 첫째 표(전기 구간)는 그대로 보존 — 가산적 수정.
    assert [l for l in sce_sep if l.table_seq == 0]


def test_the_old_unsquished_predicate_would_have_missed_it(monkeypatch):
    """★결함 재현 가드 — 공백을 제거하지 않으면 그 표를 못 잡는다는 것을 고정한다.
    이게 없으면 "왜 공백 제거가 필요한가"가 코드에서 사라진다."""
    if not _KB_2018H1.exists():
        return

    def _old(tbl):
        from parser.xml.section_detector import table_direct_rows
        rows = table_direct_rows(tbl)
        if not rows:
            return False
        cells = (text_mod._get_cells(rows[0])
                 + (text_mod._get_cells(rows[1]) if len(rows) > 1 else []))
        return len(text_mod._SCE_COLUMN_LABELS_RE.findall("".join(cells))) >= 3

    monkeypatch.setattr(text_mod, "_looks_like_equity_changes_header", _old)
    lines = extract_report_lines(
        _KB_2018H1, rcept_no="20180814002480", corp_code="00688996",
        report_fiscal_year=2018, report_fiscal_period="H1")
    seqs = {l.table_seq for l in lines
            if l.statement == "SCE" and l.basis == "separate"}
    assert seqs == {0}, seqs        # 당기 표가 없다 = 수정 전 결함 모양
