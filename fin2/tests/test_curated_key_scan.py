"""fin2/audit/curated_key_scan.py 순수 로직 단위 테스트.

★ 이 테스트는 **의도적으로 DB 를 건드리지 않는다** — `_operating_expense_parents()`/
`scan_*()` 자체는 `report_lines`/`face_audit` 전수(수십만 행)를 훑는 수 분짜리 작업이라
(design `docs/plans/gateb_curated_key_regenerator_design_2026-08-18.md` §5-A) pytest
정기 스위트에 넣기엔 너무 느리다 — [[feedback-pytest-scope-raw-report-symlink]] 류
교훈과 같은 이유. 4-family 스캔의 **①일치(동치성 증명)** 자체는 최초 구현 시 1회
`python -m fin2.audit.curated_key_scan` 수동 실행으로 확인하고 결과를 문서/메모리에
남긴다(전수 재감사와 동일 원칙 — [[gateb-full-reaudit-is-required-to-close]]).

여기서 고정하는 건 분류/직렬화 헬퍼(`_classify_full`/`_classify_residual`/`_jsonable`)의
순수 로직뿐이다.
"""
from __future__ import annotations

from fin2.audit.curated_key_scan import _classify_full, _classify_residual, _jsonable


def test_classify_full_matched_and_vanished():
    # 등재된 3키 중 2개는 스캔에서도 재현(①일치), 1개는 스캔에 안 잡힘(④소멸).
    registered = {("00100001", 2024, "FY"), ("00100001", 2025, "FY"), ("00200002", 2023, "FY")}
    scan = {("00100001", 2024, "FY"), ("00100001", 2025, "FY")}
    matched, vanished, forward, lateral = _classify_full(scan, registered)
    assert matched == {("00100001", 2024, "FY"), ("00100001", 2025, "FY")}
    assert vanished == {("00200002", 2023, "FY")}
    assert forward == set()
    assert lateral == set()


def test_classify_full_forward_vs_lateral():
    # 등재 corp(00100001)의 새 기간 = forward. 미등재 corp(00999999) = lateral.
    registered = {("00100001", 2024, "FY")}
    scan = {("00100001", 2024, "FY"), ("00100001", 2026, "Q1"), ("00999999", 2025, "FY")}
    matched, vanished, forward, lateral = _classify_full(scan, registered)
    assert matched == {("00100001", 2024, "FY")}
    assert vanished == set()
    assert forward == {("00100001", 2026, "Q1")}
    assert lateral == {("00999999", 2025, "FY")}


def test_classify_residual_no_matched_or_vanished_output():
    # T1(residual) 은 matched/vanished 개념이 없다 — forward/lateral 만 반환.
    registered = {("00100001", 2024, "FY")}
    scan = {("00100001", 2026, "Q1"), ("00999999", 2025, "FY")}
    forward, lateral = _classify_residual(scan, registered)
    assert forward == {("00100001", 2026, "Q1")}
    assert lateral == {("00999999", 2025, "FY")}


def test_classify_residual_ignores_own_registered_period():
    # scan 모집단이 구조적으로 등재분을 이미 제외하므로, 등재된 바로 그 키가 스캔에
    # 다시 나타나는 일은 실전에선 없지만, 방어적으로 나타나도 forward 로만 분류되고
    # 크래시하지 않아야 한다(matched 슬롯 자체가 없음).
    registered = {("00100001", 2024, "FY")}
    scan = {("00100001", 2024, "FY")}
    forward, lateral = _classify_residual(scan, registered)
    assert forward == {("00100001", 2024, "FY")}
    assert lateral == set()


def test_jsonable_converts_tuples_and_nested_structures():
    src = {"labels": ("매입채무", "기타채무"), "values": [1, 2], "nested": {"k": ("a", "b")}}
    out = _jsonable(src)
    assert out == {"labels": ["매입채무", "기타채무"], "values": [1, 2], "nested": {"k": ["a", "b"]}}
    assert isinstance(out["labels"], list)
