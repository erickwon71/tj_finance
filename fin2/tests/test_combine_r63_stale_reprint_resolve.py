"""R63 (2026-09-02, docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_
reprint_design_2026-09-02.md §1/§3, CF extension §8) — `_resolve()`'s stale-reprint
pre-pass.

K-GAAP era (~2010 이전) interim(Q1/H1/Q3) 연결 IS/CF 필링에는 진짜 당해분기 데이터가
아니라 직전 확정 연차 재무제표를 재게재한 table_seq가 섞여 있다(원문대조로 확정 —
IS: 현대차 00164742/KG스틸 00115676. CF: KG스틸 00115676 2006, §8). `_stale_annual_
reprint_table_seqs()`가 cross-period DB 조회로 (statement별로 따로) 그 table_seq
집합을 찾아주면, `_resolve()`는 그 table_seq의 후보를 해당 prefix(is./cf.)
캐노니컬 풀에서만 제거한다 — 남는 후보가 없으면(이 시대엔 흔함, 대체 소스가
없으므로) 그 캐노니컬은 아예 confirmed/conflicts 어디에도 안 나타나야 한다(=NULL).

Pure/DB-independent: `stale_reprint_table_seqs`는 `_resolve()`의 파라미터라 합성
{prefix: set}으로 직접 주입해 테스트한다(DB round-trip이 필요한 `_stale_annual_
reprint_table_seqs()` 자체의 SQL 로직은 별도 DB-backed 테스트
`test_combine_r63_stale_reprint_db.py`에서 검증)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _resolve


def _row(value, stage, label_raw, table_seq):
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": "IS", "table_seq": table_seq}


def test_stale_table_seq_empties_canonical_to_null_when_sole_source():
    # KG스틸 2006 재현 형태: is.revenue의 유일한 후보가 table_seq=0(연결손익계산서,
    # 직전연차 재게재)인 경우 — 대체 소스가 없으므로 NULL(=confirmed/conflicts에
    # 아예 안 나타남)이 맞다.
    cands = {"is.revenue": [_row(3_606_209_791_554, "exact", "매출액", 0)]}
    confirmed, conflicts = _resolve(cands, stale_reprint_table_seqs={"is": {0}})
    assert "is.revenue" not in confirmed
    assert "is.revenue" not in conflicts


def test_stale_table_seq_leaves_other_table_seq_candidate_intact():
    # 같은 canonical에 진짜 당해분기 소스로 보이는 다른 table_seq 후보가 있으면
    # (이론상 케이스 — 이번 조사 표본엔 없었지만 안전장치로 검증) 그건 살아남는다.
    cands = {"is.revenue": [
        _row(3_606_209_791_554, "exact", "매출액", 0),   # stale, table_seq=0
        _row(19_930_722_000, "exact", "매출액", 5),        # genuine, table_seq=5
    ]}
    confirmed, conflicts = _resolve(cands, stale_reprint_table_seqs={"is": {0}})
    assert confirmed.get("is.revenue") == 19_930_722_000


def test_non_matching_prefix_canonicals_untouched_by_stale_filter():
    # stale_reprint_table_seqs["is"]는 is.* 캐노니컬에만 적용 — bs./cf.는 손대지
    # 않는다.
    cands = {
        "is.revenue": [_row(100, "exact", "매출액", 0)],
        "bs.total_assets": [_row(200, "exact", "자산총계", 0)],
    }
    confirmed, conflicts = _resolve(cands, stale_reprint_table_seqs={"is": {0}})
    assert "is.revenue" not in confirmed
    assert confirmed.get("bs.total_assets") == 200


def test_cf_prefix_filters_cf_canonicals_only():
    # §8 (2026-09-02 후속): CF도 같은 메커니즘으로 배제 — table_seq는 statement별
    # 독립 카운터라 is.* 캐노니컬의 table_seq=0과 cf.* 캐노니컬의 table_seq=0은
    # 서로 무관한 표 — "is" 키의 stale set이 cf.*를 건드리면 안 되고 그 역도 안 된다.
    cands = {
        "cf.operating_cash_flow": [_row(54_870_597_628, "exact", "영업활동으로 인한 현금흐름", 0)],
        "is.revenue": [_row(100, "exact", "매출액", 0)],
    }
    confirmed, conflicts = _resolve(
        cands, stale_reprint_table_seqs={"cf": {0}})
    assert "cf.operating_cash_flow" not in confirmed
    assert confirmed.get("is.revenue") == 100  # is.* untouched by the "cf" set


def test_is_and_cf_stale_seqs_do_not_cross_contaminate_same_table_seq_number():
    # 핵심 안전장치: is.*의 table_seq=0이 stale이어도 cf.*의 table_seq=0(다른 표)은
    # stale로 취급되면 안 된다 — 두 prefix의 set을 절대 합치지 않는다.
    cands = {
        "is.revenue": [_row(100, "exact", "매출액", 0)],       # is table_seq=0: stale
        "cf.operating_cash_flow": [_row(200, "exact", "영업활동으로 인한 현금흐름", 0)],  # cf table_seq=0: genuine
    }
    confirmed, conflicts = _resolve(
        cands, stale_reprint_table_seqs={"is": {0}, "cf": set()})
    assert "is.revenue" not in confirmed
    assert confirmed.get("cf.operating_cash_flow") == 200


def test_empty_stale_set_is_a_no_op():
    cands = {"is.revenue": [_row(100, "exact", "매출액", 0)]}
    confirmed, conflicts = _resolve(cands, stale_reprint_table_seqs={"is": set()})
    assert confirmed.get("is.revenue") == 100


def test_default_param_is_a_no_op_backward_compatible():
    # 기존 호출부(_resolve(cands) 등, 이 파라미터 없이 호출)는 동작이 그대로여야 함.
    cands = {"is.revenue": [_row(100, "exact", "매출액", 0)]}
    confirmed, conflicts = _resolve(cands)
    assert confirmed.get("is.revenue") == 100
