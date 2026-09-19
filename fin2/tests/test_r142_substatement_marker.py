"""R142(2026-09-19) 회귀 테스트 — 재무제표가 기간대역별 하위표 2개로 쪼개지고, 뒤쪽
하위표의 표제가 재무제표명을 아예 반복하지 않는 서식("(2) 개별재무제표(2015년 및
2016년)")일 때, 직전에 성공적으로 분류된 statement 를 물려받아 데이터를 살린다.

실측: 삼성바이오로직스 20170331005571(2016FY) 별도 자본변동표 — "다.자본변동표
(1)별도재무제표(2013년및2014년)"[데이터19행] "(2)개별재무제표(2015년및2016년)"
[데이터26행, 당기(2016) 데이터 포함] 구조에서 뒤쪽 26행 표 전체가 statement 분류
실패로 유실되던 결함(layer2 review campaign fail #3). `is_substatement_marker()`가
이 표지를 인식하고, `_detect_body_statement_tables()`가 직전 statement 를 물려준다.

실행: pytest fin2/tests/test_r142_substatement_marker.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.statement_titles import is_substatement_marker  # noqa: E402
from fin2.extract.report_lines import extract_report_lines  # noqa: E402

_SAMBIO_2016FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00877059_삼성바이오로직스/annual/2016/20170331005571.xml"
)


# --- §1: is_substatement_marker() 순수 목 테스트 -----------------------------

def test_is_substatement_marker_matches_real_case():
    assert is_substatement_marker("(2) 개별재무제표(2015년 및 2016년)")
    assert is_substatement_marker("(1) 별도재무제표(2013년 및 2014년)")
    assert is_substatement_marker("(1)연결재무제표(2020년)")


def test_is_substatement_marker_rejects_real_statement_titles():
    """진짜 재무제표명이 있는 표제는 (설령 번호가 붙어도) 이 판정에 걸리면 안 된다 —
    그건 `classify_statement_in_body_section` 이 이미 정상 처리한다."""
    assert not is_substatement_marker("다. 자본변동표(1) 별도재무제표(2013년 및 2014년)")
    assert not is_substatement_marker("가. 재무상태표")
    assert not is_substatement_marker("")
    assert not is_substatement_marker("(단위 : 원)")
    assert not is_substatement_marker("2. 연결재무제표")


# --- §2: 실측 파일 재현(삼성바이오로직스 2016FY) ------------------------------

def test_sambio_2016fy_separate_sce_second_block_recovered():
    """별도 자본변동표 "제6기 기말(2016.12.31)" 행(당기 데이터)이 더 이상 유실되지
    않고, "제6기 기초(2016.01.01)" 행과 다른 값(원문 그대로)을 갖는다."""
    if not _SAMBIO_2016FY.exists():
        return
    lines = extract_report_lines(
        _SAMBIO_2016FY, rcept_no="20170331005571", corp_code="00877059",
        report_fiscal_year=2016, report_fiscal_period="FY",
    )
    sce_sep = [l for l in lines if l.statement == "SCE" and l.basis == "separate"]
    ending = {l.col_index: l.value_won for l in sce_sep
              if l.label_raw == "제6기 기말(2016.12.31)"}
    beginning = {l.col_index: l.value_won for l in sce_sep
                 if l.label_raw == "제6기 기초(2016.01.01)"}
    assert ending, "제6기 기말(2016.12.31) 행이 여전히 유실됨(R142 회귀)"
    # DART 원문 실측값(2026-09-19 직접 확인) — 자본금/자본잉여금/기타포괄손익누계액/
    # 이익잉여금/지배기업소유주지분소계/합계.
    assert ending[0] == 165_412_500_000        # 자본금
    assert ending[1] == 2_487_313_082_024      # 자본잉여금
    assert ending[3] == 1_424_706_873_013      # 이익잉여금
    assert ending[6] == 4_082_379_459_573      # 합계
    # 기초/기말이 더 이상 같은 값으로 중복 적재되지 않는다(원 결함 재현 방지).
    assert ending[1] != beginning.get(1)
    assert ending[6] != beginning.get(6)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
