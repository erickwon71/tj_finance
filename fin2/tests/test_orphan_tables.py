"""원문 본문표 미귀속 탐지기(`fin2/audit/orphan_tables.py`) 회귀 테스트.

이 탐지기의 존재 이유는 "캠페인이 구조적으로 못 보는 것을 본다"이므로, 회귀 테스트도
**실제 결함 모양을 다시 만들어** 잡히는지를 본다. R148 규칙(`_looks_like_equity_
changes_header` 기반 SCE 연속표 연결)만 꺼서 수정 전 상태를 재현하고, 그때 잃어버리던
당기 롤포워드 SCE 표가 미귀속으로 적출되는지 확인한다. 이게 깨지면 탐지기는 "아무것도
안 잡는 검산"으로 조용히 퇴화한 것이다.

실행: pytest fin2/tests/test_orphan_tables.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.extract.text as text_mod                      # noqa: E402
from fin2.audit import orphan_tables                      # noqa: E402
from fin2.audit.layer2_selfcheck import FAIL, PASS        # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_SHINHAN_2021FY = _ROOT / "raw_report/KOSPI/00382199_신한지주/annual/2021/20220316000748.xml"
# 은행 신탁계정("(2) 신탁계정") — 은행 자신의 재무제표가 아니라서 파서가 안 붙이는 것이
# 정상. 탐지기가 이걸 결함으로 올리면 은행권 전 필링이 막힌다.
_IBK_2015Q1 = _ROOT / "raw_report/KOSPI/00149646_기업은행/quarter/2015/20150515002437.xml"


def test_shinhan_2021fy_has_no_orphan_with_r148_fix():
    """R148 이 적용된 현재 파서에서는 미귀속 표가 없다."""
    if not _SHINHAN_2021FY.exists():
        return
    result = orphan_tables.check(_SHINHAN_2021FY)
    assert result.verdict == PASS, result.message


def test_detects_the_r148_shape_when_the_rule_is_disabled(monkeypatch):
    """R148 규칙만 끄면(=수정 전 재현) 연결·별도 당기 롤포워드 SCE 표가 적출된다.

    탐지기가 실제 유실 결함을 잡는다는 것의 유일한 직접 증거 — 이 케이스가 없으면
    "한 번도 안 울리는 경보"와 구분되지 않는다.
    """
    if not _SHINHAN_2021FY.exists():
        return
    monkeypatch.setattr(text_mod, "_looks_like_equity_changes_header",
                        lambda tbl: False)
    orphans = orphan_tables.find_orphans(_SHINHAN_2021FY)
    assert len(orphans) == 2, [o.preview[:60] for o in orphans]
    assert {o.basis for o in orphans} == {"consolidated", "separate"}
    # 잃어버리던 것이 자본변동표 데이터라는 것까지 확인(다른 표가 우연히 걸린 게 아님).
    assert all("자본금" in o.preview for o in orphans), [o.preview[:60] for o in orphans]
    assert orphan_tables.check(_SHINHAN_2021FY).verdict == FAIL


def test_bank_trust_account_table_is_not_reported():
    """은행 신탁계정은 재무제표가 아니라 정당한 제외 — 적출하지 않는다."""
    if not _IBK_2015Q1.exists():
        return
    result = orphan_tables.check(_IBK_2015Q1)
    assert result.verdict == PASS, result.message
