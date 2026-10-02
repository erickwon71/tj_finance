"""R213(2026-10-03) 회귀 테스트 — 계층3 EPS 라벨 매핑 공백.

계층3 은 일반 매퍼(AccountMapper)로 EPS 를 찾았는데, 매퍼는 '주당' 라벨을 퍼지에서 의도적으로
막고(원 단위 손익 오염 방지) 정확 일치 alias 는 '기본주당이익'·'희석주당이익' 류만 알았다.
그래서 2015+ HTML EPS 행 363,756건 중 3.5% 만 is.eps_* 로 올라갔다
('기본주당이익(손실) (단위 : 원)' 96,904건 등이 전부 unknown).

수정: 적재기의 EPS 경로가 방출한 행(source_ref 'eps/…')은 `_eps_canonicals` 로 분류한다.

실행: pytest fin2/tests/test_r213_layer3_eps_mapping.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _STAGE_RANK, _eps_canonicals, _map_rows  # noqa: E402

B, D = "is.eps_basic", "is.eps_diluted"


def test_label_forms_seen_in_the_unmapped_census():
    assert _eps_canonicals("기본주당이익(손실) (단위 : 원)", "주당손익") == (B,)
    assert _eps_canonicals("희석주당이익(손실) (단위 : 원)", "주당손익") == (D,)
    assert _eps_canonicals("기본주당순손익 (단위 : 원)", None) == (B,)
    assert _eps_canonicals("희석주당손실", None) == (D,)
    assert _eps_canonicals("보통주기본주당이익(손실) (단위 : 원)", None) == (B,)
    assert _eps_canonicals("주당이익", None) == (B,)


def test_combined_basic_and_diluted_line_is_both():
    assert _eps_canonicals("기본및희석주당이익(손실) (단위 : 원)", None) == (B, D)
    assert _eps_canonicals("기본/희석주당순이익 (단위 : 원)", "주당이익(단위 : 원)>계속영업과 중단영업") == (B, D)


def test_components_and_preferred_shares_are_not_headline():
    assert _eps_canonicals("계속영업기본주당이익(손실) (단위 : 원)", None) == ()
    assert _eps_canonicals("중단영업희석주당이익(손실)", None) == ()
    assert _eps_canonicals("우선주기본주당이익 (단위 : 원)", None) == ()
    # the component is named by the nearest ancestor
    assert _eps_canonicals("기본주당손익 (단위 : 원)", "계속영업") == ()
    assert _eps_canonicals("기본주당순이익", "주당이익>중단영업") == ()
    assert _eps_canonicals("계속영업", "주당이익(단위 : 원)") == ()


def test_child_line_without_jootang_is_named_by_its_section():
    assert _eps_canonicals("1. 보통주", "(1) 기본주당이익") == (B,)
    assert _eps_canonicals("1. 보통주", "(2) 희석주당이익") == (D,)


def _row(label, won, *, eps_row=True, section=None, cum=False, exact=None):
    return {"statement": "IS", "basis": "consolidated", "label_raw": label, "value_won": won,
            "value_exact": exact, "eps_row": eps_row, "node_role": None,
            "section_path": section, "table_seq": 0, "is_cumulative": cum}


def test_map_rows_routes_loader_eps_rows_through_the_eps_rule():
    cands = _map_rows([
        _row("기본주당이익(손실) (단위 : 원)", -110, exact=Decimal("-109.89"), section="주당손익"),
        _row("희석주당이익(손실) (단위 : 원)", -110, section="주당손익"),
        _row("계속영업기본주당이익(손실) (단위 : 원)", -95, section="주당손익"),
        _row("매출액", 1_000, eps_row=False),
    ], "FY", "consolidated", ("IS",))
    assert [(c["value"], c["exact"], c["stage"]) for c in cands[B]] == [(-110, Decimal("-109.89"), "eps")]
    assert [c["value"] for c in cands[D]] == [-110]
    assert "is.revenue" in cands                       # non-EPS rows still use the mapper


def test_loss_label_keeps_the_printed_sign():
    # stored EPS sign agrees with the controlling-NI sign ~99% whatever the label says
    cands = _map_rows([_row("기본주당손실 (단위 : 원)", -2)], "FY", "consolidated", ("IS",))
    assert cands[B][0]["value"] == -2
    cands = _map_rows([_row("기본주당손실 (단위 : 원)", 2)], "FY", "consolidated", ("IS",))
    assert cands[B][0]["value"] == 2


def test_interim_keeps_cumulative_eps_only():
    cands = _map_rows([_row("기본주당이익 (단위 : 원)", 100, cum=False),
                       _row("기본주당이익 (단위 : 원)", 300, cum=True)], "H1", "consolidated", ("IS",))
    assert [c["value"] for c in cands[B]] == [300]


def test_eps_stage_ranks_with_exact():
    assert _STAGE_RANK["eps"] == _STAGE_RANK["exact"]
