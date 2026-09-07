"""account_mapper 전체 어휘 스캔(형태소 반의어 갭)으로 찾은 것들의 회귀 테스트.

배경(2026-09-07, DB증권 155행 원문대조 후속 — 사용자 지시 "전체 어휘 스캔을
별도 진행해봐" → "yes" → "커밋하고 처분 부분 추가하는것 진행해"): 등록된
818개 alias 전체에 회계 반의어 쌍(채권/채무, 취득/처분 등)을 적용해 미등록
변형이 fuzzy 로 어디에 붙는지 전수 확인(R80).

1) "비유동기타채무"(부채) — 어순만 뒤집힌 "기타비유동채무"는 이미 등록돼
   있는데 이 변형은 없어서 자산쪽 "비유동기타채권"에 오매핑되던 갭 → exact
   alias 추가로 해결.
2) CF/NOTE 의 "취득"(canonical 있음) ↔ "처분"(canonical 자체가 없음) 반의어
   6종 — 처음엔 `_FUZZY_BLOCK`으로 방어만 했다가(R80), 후속(R81, 사용자 지시
   "처분 부분 추가")으로 8개 라벨은 신규 canonical 신설해 정확히 매핑:
     - cf.disposal_of_subsidiaries / cf.disposal_of_associates (M&A, 신규)
     - cf.investment_property_acquisition (신규, ★_CAPEX_CANON 미포함 — FCF
       정의를 조용히 넓히는 셈이라 별도 결정 필요, 의도적 보류)
     - cf.treasury_stock_proceeds / note.treasury_stock_proceeds (신규,
       ★app/data/shareholder_return.py 는 아직 이 신규 canonical 을 안 읽음
       — "순취득금액" 넷팅은 별도 후속 작업)
     - "산업재산권의처분"은 신규 canonical 없이 기존 cf.ppe_proceeds 에 등록
       (같은 문서에 있던 "무형자산의처분"이 이미 그렇게 매핑되는 것과 동일 패턴)
   나머지 2개("기계장치의취득"/"차량운반구의취득")는 `_FUZZY_BLOCK`에 **의도적
   으로 계속 유지** — 대응 처분쪽(cf.ppe_proceeds_detail)은 이미 등록돼 있지만,
   취득쪽은 보통 총계 라인(유형자산의취득→cf.capex)과 같이 찍혀 세부항목까지
   따로 잡으면 총계와 중복계상 위험이 커 임시방편이 아니라 영구 방어로 남겨둠.

실행: python fin2/tests/test_account_mapper_full_vocab_scan_2026-09-07.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_reordered_other_noncurrent_payables_maps_to_liability_not_asset():
    m = get_mapper()
    r = m.map("비유동기타채무", fs_section="bs")
    assert r.account_code == "bs.other_noncurrent_liabilities", r.account_code


def test_original_word_order_still_correct_unaffected():
    m = get_mapper()
    r = m.map("기타비유동채무", fs_section="bs")
    assert r.account_code == "bs.other_noncurrent_liabilities", r.account_code


def test_disposal_side_labels_now_map_to_dedicated_disposal_canonicals():
    """R81 — 8개 라벨은 신규 canonical 로 정확히 매핑돼야 한다(더 이상 무매핑도,
    부호반대 취득 계정도 아님)."""
    m = get_mapper()
    cases = [
        ("종속기업의처분", "cf", "cf.disposal_of_subsidiaries"),
        ("관계기업의처분", "cf", "cf.disposal_of_associates"),
        ("공동기업투자의처분", "cf", "cf.disposal_of_associates"),
        ("공동기업의처분", "cf", "cf.disposal_of_associates"),
        ("투자부동산의취득", "cf", "cf.investment_property_acquisition"),
        ("산업재산권의처분", "cf", "cf.ppe_proceeds"),
        ("자기주식의처분", "cf", "cf.treasury_stock_proceeds"),
        ("자기주식처분금액", "note", "note.treasury_stock_proceeds"),
    ]
    for lbl, sec, expect in cases:
        r = m.map(lbl, fs_section=sec)
        assert r.account_code == expect, f"{lbl} -> {r.account_code} (기대: {expect})"


def test_ppe_acquisition_detail_labels_stay_intentionally_blocked():
    """"기계장치의취득"/"차량운반구의취득"은 총계(cf.capex)와 중복계상 위험
    때문에 R81 이후에도 의도적으로 무매핑 유지."""
    m = get_mapper()
    for lbl in ("기계장치의취득", "차량운반구의취득"):
        r = m.map(lbl, fs_section="cf")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_acquisition_side_labels_still_correctly_mapped_unaffected():
    m = get_mapper()
    assert m.map("종속기업의취득", fs_section="cf").account_code == "cf.acquisition_of_subsidiaries"
    assert m.map("관계기업의취득", fs_section="cf").account_code == "cf.acquisition_of_associates"
    assert m.map("자기주식의취득", fs_section="cf").account_code == "cf.treasury_stock_purchase"
    assert m.map("자기주식취득금액", fs_section="note").account_code == "note.treasury_stock_purchase"
    assert m.map("투자부동산의처분", fs_section="cf").account_code == "cf.investment_property_proceeds"
    assert m.map("무형자산의처분", fs_section="cf").account_code == "cf.ppe_proceeds"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
