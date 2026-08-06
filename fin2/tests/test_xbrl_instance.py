"""
XBRL 원문 instance 파서(Phase 3-1~3-7) 회귀 테스트 — 실측 파일 기반, DB 비의존.

실측: 박셀바이오(01335851) 2024H1 반기보고서 XBRL instance zip
(rcept_no=20250828000534, `file_type='xbrl_zip'`). 하드코딩된 기대값은 전부
`docs/plans/xbrl_instance_parser_todo_2026-08-05.md`의 Phase 0(§1~§12)·3-1·3-5·
3-6·3-7 기록에서 실측 재확인된 값 그대로 옮겨온 것이다(짐작 없음, R9).

핵심 검증:
  - 구조: context/unit/fact 개수, basis(연결/별도) 판정 — 이 필링은 별도만
    존재(연결 context 0개)하는 것이 정상 케이스임을 확인(Phase 0 §4).
  - 값: BS/IS/CF/SCE 주요 계정 하드코딩 대조 + 항등식(자산=부채+자본,
    영업활동현금흐름=영업창출현금흐름+이자수취+법인세환급, SCE 기말자본=BS
    자본총계 등) — 값 자체가 아니라 파서 배선이 맞는지를 항등식으로 교차검증.
  - 라벨: label_raw 가 한글로 채워짐(영문 QName 로컬명으로 새지 않음).
  - instant/duration: BS는 instant, IS는 duration, CF는 흐름=duration/
    현금잔액(기초·기말)=instant.
  - 구조(P/S/F, depth, section_path, SCE col_label 계층)가 사람이 읽어도
    말이 되는 형태로 나오는지.

파일이 없으면 스킵(다른 환경에서 안전, test_xbrl.py와 동일한 관례).

실행: python -m fin2.tests.test_xbrl_instance
"""
from __future__ import annotations

import sys
import zipfile
import tempfile
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xbrl_instance.instance_parser import parse_instance  # noqa: E402
from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl, _extract_zip_members  # noqa: E402

_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/01335851_박셀바이오/half/2024/20250828000534.zip"
)
_RCEPT = "20250828000534"
_CORP = "01335851"
_FY = 2024
_PERIOD = "H1"
_PERIOD_END = date(2024, 6, 30)

# 기대 zip 크기(bytes) — Phase 0 §2 실측 기록. 다른 파일이 잘못 심링크된 채로
# 재검증되는 사고를 조기에 잡기 위한 가드(값 자체보다 "같은 파일인가"가 목적).
_EXPECTED_ZIP_SIZE = 44_076


def _extract():
    return extract_report_lines_xbrl(
        _SAMPLE, rcept_no=_RCEPT, corp_code=_CORP,
        report_fiscal_year=_FY, report_fiscal_period=_PERIOD,
        period_end_date=_PERIOD_END,
    )


def _parsed_instance():
    with tempfile.TemporaryDirectory(prefix="test_xbrl_instance_") as tmp:
        tmp_dir = Path(tmp)
        members = _extract_zip_members(_SAMPLE, tmp_dir)
        return parse_instance(members.xbrl)


def test_zip_size_matches_phase0_record():
    assert _SAMPLE.stat().st_size == _EXPECTED_ZIP_SIZE


def test_instance_structure_counts():
    # Phase 3-1 실측: 32 contexts / 3 units / 289 facts.
    inst = _parsed_instance()
    assert len(inst.contexts) == 32
    assert len(inst.units) == 3
    assert len(inst.facts) == 289


def test_basis_separate_only_no_consolidated():
    # Phase 0 §4: 자회사 없는 소형 바이오는 SeparateMember 만 존재하고
    # ConsolidatedMember context 는 0개 — 에러가 아니라 정상 케이스여야 한다.
    inst = _parsed_instance()
    basis_axis_ns = inst.nsmap.get("ifrs-full")
    members = set()
    for ctx in inst.contexts.values():
        for d in ctx.dims:
            if d.axis.local == "ConsolidatedAndSeparateFinancialStatementsAxis":
                assert d.axis.ns == basis_axis_ns
                members.add(d.member.local)
    assert members == {"SeparateMember"}

    lines = _extract()
    assert lines  # 뭔가는 나와야 함
    assert {l.basis for l in lines} == {"separate"}


def test_bs_values_and_identity():
    lines = _extract()
    bs0 = {l.label_raw: l.value_won for l in lines if l.statement == "BS" and l.col_index == 0}

    assert bs0["자산총계"] == 83_142_583_571
    assert bs0["부채총계"] == 4_867_937_672
    assert bs0["자본총계"] == 78_274_645_899
    assert bs0["현금및현금성자산"] == 4_603_655_980
    assert bs0["유동자산"] == 52_067_184_236
    assert bs0["비유동자산"] == 31_075_399_335

    # 항등식: 자산 = 부채 + 자본 (Phase 0 §7 교차검증과 동일)
    assert bs0["자산총계"] == bs0["부채총계"] + bs0["자본총계"]
    assert bs0["자산총계"] == bs0["유동자산"] + bs0["비유동자산"]
    assert bs0["부채및자본총계"] == bs0["자산총계"]


def test_is_values_and_rollup():
    lines = _extract()
    is0 = {l.label_raw: l.value_won for l in lines if l.statement == "IS" and l.col_index == 0}

    assert is0["매출액"] == 55_876_193
    assert is0["매출총이익"] == is0["매출액"] - is0["매출원가"]
    assert is0["영업이익(손실)"] == is0["매출총이익"] - is0["판매관리비"]
    assert is0["당기순이익(손실)"] == -4_895_467_478
    # 당기순이익 + 기타포괄손익 = 총포괄손익
    assert is0["당기순이익(손실)"] + is0["기타포괄손익"] == is0["총포괄손익"]


def test_cf_values_and_weighted_identity():
    lines = _extract()
    cf0 = {l.label_raw: l.value_won for l in lines if l.statement == "CF" and l.col_index == 0}

    assert cf0["영업활동현금흐름"] == -5_586_995_010
    assert cf0["영업으로부터창출된현금흐름"] == -5_931_095_417
    assert cf0["이자수취"] == 249_435_527
    # ★2026-08-06 정정(Phase 6-2 DART 웹뷰어 수동 대조로 발견): 이 계정의
    # presentationArc가 preferredLabel="...negatedTerseLabel"이라 raw XBRL
    # fact(-94,664,880)를 그대로 저장하면 DART 화면 표시(+94,664,880)와
    # 부호가 어긋난다 — `report_lines_xbrl.py::_value_sign()`이 이 경우 -1을
    # 곱해 저장하도록 수정됐고, 이 값이 그 수정 결과다. 옛 기대값
    # (-94,664,880)과 "weight 반영해야 항등식이 맞는다"는 이전 결론(Phase 0
    # §11/3-5)은 BS만으로 일반화한 것이었고 CF의 negated-label 케이스에선
    # 틀렸음이 이번에 드러났다 — 이제는 단순합만으로 항등식이 맞아야 한다.
    assert cf0["법인세환급(납부)"] == 94_664_880
    assert (
        cf0["영업으로부터창출된현금흐름"] + cf0["이자수취"] + cf0["법인세환급(납부)"]
        == cf0["영업활동현금흐름"]
    )

    # CF 현금잔액(기말)이 BS 현금및현금성자산과 정확히 일치해야 함(교차검증).
    bs0 = {l.label_raw: l.value_won for l in lines if l.statement == "BS" and l.col_index == 0}
    assert cf0["기말의 현금"] == bs0["현금및현금성자산"]

    # ★두 번째 negated-label 케이스(같은 Phase 6-2 발견): "2. 재무활동으로
    # 인한 현금 유출액"도 preferredLabel="...negatedTerseLabel" — raw fact는
    # +347,076,273(entity 확장 개념의 자식 "리스부채의 상환"은 이미
    # -347,076,273로 부호가 맞음)인데 DART 화면은 (347,076,273)으로 음수
    # 표시한다. `_value_sign()` 수정 후 이 값도 음수로 저장돼야 하고, 재무
    # 활동 항등식(유입액+유출액=재무활동현금흐름)도 단순합으로 맞아야 한다.
    assert cf0["2. 재무활동으로 인한 현금 유출액"] == -347_076_273
    assert cf0["리스부채의 상환"] == -347_076_273
    assert (
        cf0["1. 재무활동으로 인한 현금유입액"] + cf0["2. 재무활동으로 인한 현금 유출액"]
        == cf0["재무활동현금흐름"]
    )


def test_sce_matches_bs_equity():
    lines = _extract()
    sce = [l for l in lines if l.statement == "SCE"]
    assert len(sce) == 37  # Phase 3-7 실측(별도 37행)

    bs0 = {l.label_raw: l.value_won for l in lines if l.statement == "BS" and l.col_index == 0}
    ending = {
        l.value_won for l in sce
        if l.col_index == 0 and l.label_raw is not None
        and "기말" in l.label_raw and "2024-06-30" in l.label_raw
    }
    assert ending == {bs0["자본총계"]}  # SCE 기말자본(총계열) == BS 자본총계

    # 열 계층: col_index=0 은 "자본 [구성요소]"(총계), col_index=1 은 그 자식인
    # "자본금 [구성요소]" — Phase 3-6/3-7 실측대로 5열 평평한 구조(박셀바이오
    # 는 지배지분/비지배지분 분기가 없는 자회사 없는 소형사).
    col_labels = {l.col_index: l.col_label for l in sce}
    assert col_labels[0] == "자본 [구성요소]"
    assert col_labels[1] == "자본 [구성요소]>자본금 [구성요소]"


def test_period_kind_instant_vs_duration():
    lines = _extract()
    by_stmt = {}
    for l in lines:
        by_stmt.setdefault(l.statement, set()).add(l.period_kind)

    assert by_stmt["BS"] == {"instant"}
    assert by_stmt["IS"] == {"duration"}
    # CF: 흐름 항목은 duration, 기초/기말 현금잔액 행만 instant.
    assert by_stmt["CF"] == {"instant", "duration"}
    cf_instant_labels = {
        l.label_raw for l in lines if l.statement == "CF" and l.period_kind == "instant"
    }
    assert cf_instant_labels == {"기초의 현금", "기말의 현금"}
    # SCE는 열축이 기간이 아니므로 period_kind 를 아예 안 채운다(module docstring).
    assert by_stmt["SCE"] == {None}


def test_labels_are_korean_not_bare_qname():
    # _resolve_label() 이 라벨 카탈로그를 못 찾으면 QName 로컬명(영문)으로
    # 폴백한다(예: "Assets") — 정상 케이스라면 전부 한글이어야 한다.
    lines = _extract()
    bs0 = [l for l in lines if l.statement == "BS" and l.col_index == 0]
    assert bs0
    for l in bs0:
        assert any("가" <= ch <= "힣" for ch in l.label_raw), f"non-Korean label: {l.label_raw!r}"


def test_row_structure_sane():
    lines = _extract()
    bs0 = {l.label_raw: l for l in lines if l.statement == "BS" and l.col_index == 0}

    # 소계/합계 행은 S, 잎(leaf) 계정은 F, 중간 헤더는 P — report_lines.py의
    # 들여쓰기 규칙과 개념적으로 같은 구조 신호(module docstring).
    assert bs0["자산총계"].node_role == "S"
    assert bs0["부채총계"].node_role == "S"
    assert bs0["자본총계"].node_role == "S"
    assert bs0["현금및현금성자산"].node_role == "F"
    assert bs0["유동자산"].node_role == "P"

    # section_path: 조상 라벨 체인이 ">"로 이어져야 함.
    assert bs0["현금및현금성자산"].section_path == "재무상태표 [개요]>자산 [개요]>유동자산"

    # 최상위 행(부채및자본총계)의 depth 가 가장 얕아야 함.
    assert bs0["부채및자본총계"].depth < bs0["자산총계"].depth < bs0["현금및현금성자산"].depth


def _run():
    if not _SAMPLE.exists():
        print(f"  - SKIP: 실측 파일 없음 {_SAMPLE}")
        return 0
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
