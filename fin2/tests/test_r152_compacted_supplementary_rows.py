"""R152(2026-09-20) 회귀 테스트 — 금융업 보충표기(대손준비금·비상위험준비금)가 본항목과
**같은 칸**에 압축돼 본항목 행이 통째로 유실되던 결함.

원문이 3개 논리행을 물리적 `<TR>` 1개에 담는다(HEIGHT=76~99 = 3줄). 라벨 3개와 금액
3개가 각각 한 칸에 병합돼 오고, `parse_amount` 의 R1 가드("한 셀에 온전한 숫자 둘 이상
→ 어느 것이 이 셀 값인지 원문이 말하지 않으므로 결측")가 그 칸을 받아 **자본/손익
본항목이 사라졌다**. 이 서식에서는 원문이 순서로 말해준다 — [본항목, 보충1, 보충2].

실측 3사 · 전부 독립 산술로 검증:
 · 대신증권 20150515002053 [연결] BS 연결이익잉여금 581,929,430(천원)
   → 지배기업지분 − 나머지 구성요소 = 정확히 일치(차이 0)
 · 코리안리 20150515002691 [연결]/[별도] IS 분기순이익 60,042,793,551 / 59,994,353,039
   → 세전 − 법인세비용 = 정확히 일치
 · 미래에셋증권 20150515001242 [연결] BS 이익잉여금 1,828,134(백만원)
   → 지배기업소유주지분 항등식 차이 0

실행: pytest fin2/tests/test_r152_compacted_supplementary_rows.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines             # noqa: E402
from parser.xml.table_extractor import (                                # noqa: E402
    _first_of_compacted_supplementary_cell as first_of)

_ROOT = Path(__file__).resolve().parents[2]
_DAISHIN = _ROOT / "raw_report/KOSPI/00110893_대신증권/quarter/2015/20150515002053.xml"
_KOREANRE = _ROOT / "raw_report/KOSPI/00113191_코리안리/quarter/2015/20150515002691.xml"
_MIRAE = _ROOT / "raw_report/KOSPI/00111722_미래에셋증권/quarter/2015/20150515001242.xml"


def test_space_separated_compaction_takes_the_primary_value():
    """'본항목 보충1 보충2' 공백 구분 — 첫 값이 본항목이다."""
    assert first_of("60,042,793,551 54,525,604,742 40,084,010,260") == "60,042,793,551"
    assert first_of("13,715,502,018 9,273,310,432 (5,019,119,448)") == "13,715,502,018"
    # 뒤 토큰의 콤마 묶음이 깨져 있어도 첫 토큰만 보면 된다(버릴 값이므로).
    assert first_of("581,929,430 5,320,412647,720") == "581,929,430"


def test_paren_glued_compaction_takes_the_primary_value():
    """'본항목(보충1)(보충2)' 공백 없는 변형 — 선행 금액이 본항목이다."""
    assert first_of("1,828,134(13,701)(2,886)") == "1,828,134"
    assert first_of("1,801,174 (13,213)(488)") == "1,801,174"


def test_note_reference_lists_are_not_turned_into_amounts():
    """★가장 위험한 오작동 — 주석번호를 금액으로 날조하면 안 된다.

    실측: 미래에셋증권 20150515001242 의 이익잉여금 행은 주석칸이 `'26, 27'`(주석
    26·27번)이다. 라벨이 '대손준비금' 을 포함하므로 게이트에는 걸리는데, 금액다움
    가드가 없으면 26 이 값으로 채택된다.
    """
    assert first_of("26, 27") == "26, 27"
    assert first_of("15, 30") == "15, 30"
    assert first_of("4, 27, 30") == "4, 27, 30"


def test_untouched_when_there_is_nothing_to_split():
    """단일 값·구분자 없이 이어붙은 칸은 손대지 않는다(후자는 자릿수 경계가 원문에
    없어 복원하면 날조)."""
    assert first_of("1,234") == "1,234"
    assert first_of("576,044,2464,652,625667,787") == "576,044,2464,652,625667,787"
    assert first_of("(13,701)(2,886)") == "(13,701)(2,886)"
    assert first_of("") == ""


def test_daishin_consolidated_equity_identity_closes():
    """대신증권 — 복원된 연결이익잉여금으로 지배기업지분 항등식이 정확히 닫힌다."""
    if not _DAISHIN.exists():
        return
    lines = extract_report_lines(_DAISHIN, rcept_no="20150515002053",
                                 corp_code="00110893", report_fiscal_year=2015,
                                 report_fiscal_period="Q1")
    bs = {l.label_raw: l.value_won for l in lines
          if l.statement == "BS" and l.basis == "consolidated" and l.col_index == 0}
    retained = next((v for k, v in bs.items() if "연결이익잉여금" in k), None)
    assert retained == 581_929_430_000, retained
    owner = next(v for k, v in bs.items() if "지배기업의 소유주지분" in k)
    parts = [v for k, v in bs.items()
             if any(x in k for x in ("자본금", "연결자본잉여금",
                                     "연결기타포괄손익누계액", "자본조정",
                                     "연결이익잉여금"))]
    assert sum(parts) == owner, (sum(parts), owner)


def test_koreanre_net_income_matches_pretax_minus_tax():
    """코리안리 — 복원된 분기순이익이 세전 − 법인세비용과 일치(연결·별도)."""
    if not _KOREANRE.exists():
        return
    lines = extract_report_lines(_KOREANRE, rcept_no="20150515002691",
                                 corp_code="00113191", report_fiscal_year=2015,
                                 report_fiscal_period="Q1")
    for basis in ("consolidated", "separate"):
        rows = {l.label_raw: l.value_won for l in lines
                if l.statement == "IS" and l.basis == basis and l.col_index == 0}
        pre = next(v for k, v in rows.items() if "법인세비용차감전순이익" in k)
        tax = next(v for k, v in rows.items()
                   if k.strip().endswith("법인세비용") and "차감전" not in k)
        ni = next(v for k, v in rows.items() if "순이익 대손준비금" in k)
        assert pre - tax == ni, (basis, pre, tax, ni)


def test_mirae_consolidated_equity_identity_closes():
    """미래에셋증권 — 괄호 결합 변형에서도 항등식이 닫힌다."""
    if not _MIRAE.exists():
        return
    lines = extract_report_lines(_MIRAE, rcept_no="20150515001242",
                                 corp_code="00111722", report_fiscal_year=2015,
                                 report_fiscal_period="Q1")
    bs = {l.label_raw: l.value_won for l in lines
          if l.statement == "BS" and l.basis == "consolidated" and l.col_index == 0}
    retained = next((v for k, v in bs.items() if "이익잉여금" in k), None)
    assert retained == 1_828_134_000_000, retained
    owner = next(v for k, v in bs.items() if "지배기업소유주지분" in k)
    parts = [v for k, v in bs.items()
             if any(x in k for x in ("자본금", "자본잉여금", "자본조정",
                                     "기타포괄손익누계액", "이익잉여금"))]
    assert sum(parts) == owner, (sum(parts), owner)


# ───────────────────── R152-b: 0 을 붙임표로 찍는 변형 ─────────────────────
# 보충표기 3개 중 첫째의 값이 0 이면 원문이 그것을 `-` 로 찍는다. 그러면 본항목 바로
# 뒤가 `(` 가 아니라 `-` 라서 `_COMPACTED_PAREN_HEAD_RE` 가 빗나가고, 칸이 결측이 되어
# **이익잉여금 행이 통째로 유실**된다.
#
# 실측: 우리금융지주 20200330004490 [별도] BS
#   라벨 '5. 이익잉여금 (대손준비금 적립액) (대손준비금 전입필요액) (대손준비금 전입예정액)'
#   금액칸 '623,930- (692)(692)'      (적립액 = 0 → '-')
# 캠페인 이슈#32(camp_run 발견). 붙임표/전각 대시는 한국 재무제표에서 0(해당없음)의
# 관용 표기다.

_WOORI = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/01350869_우리금융지주/annual/2019/20200330004490.xml"
)


def test_dash_zero_placeholder_between_head_and_parens():
    """★핵심 — 본항목과 괄호 보충표기 사이의 `-`(=0) 를 건너뛴다."""
    from parser.xml.table_extractor import _first_of_compacted_supplementary_cell
    f = _first_of_compacted_supplementary_cell
    assert f("623,930- (692)(692)") == "623,930"
    assert f("623,930-(692)(692)") == "623,930"
    # 종전 변형은 그대로 동작한다(가산적 수정 확인)
    assert f("1,828,134(13,701)(2,886)") == "1,828,134"
    assert f("623,930 - (692) (692)") == "623,930"


def test_dash_variant_does_not_open_a_fabrication_path():
    """★가드가 살아 있는지 — 주석번호와 괄호 없는 칸은 여전히 손대지 않는다."""
    from parser.common.amount_normalizer import parse_amount
    from parser.xml.table_extractor import _first_of_compacted_supplementary_cell
    f = _first_of_compacted_supplementary_cell
    # 주석번호 칸(미래에셋증권 실측) — 금액다움 게이트에 걸려 그대로 결측
    assert parse_amount(f("26, 27")) is None
    # 괄호가 없으면 이 경로 자체가 아니다 — 두 숫자 중 무엇이 값인지 원문이 말하지 않는다
    assert parse_amount(f("1,234-5,678")) is None


def test_woori_2019fy_separate_equity_identity_closes():
    """실측 필링 — 이익잉여금 행이 복구되고 자본총계 항등식이 정확히 닫힌다.

    앵커는 같은 표의 자본총계다(행 자신이 아니라 독립 합계).
    """
    if not _WOORI.exists():
        return
    lines = extract_report_lines(_WOORI, rcept_no="20200330004490",
                                 corp_code="01350869", report_fiscal_year=2019,
                                 report_fiscal_period="FY")
    bs = [l for l in lines if l.statement == "BS" and l.basis == "separate"
          and (l.col_index or 0) == 0]

    def find(pred):
        return next((l.value_won for l in bs
                     if pred((l.label_raw or "").replace(" ", "").replace("\n", ""))),
                    None)

    retained = find(lambda k: k.startswith("5.이익잉여금"))
    assert retained == 623_930_000_000, retained

    total = find(lambda k: k == "자본총계")
    parts = [find(lambda k: k.startswith(p)) for p in
             ("1.자본금", "2.신종자본증권", "3.자본잉여금", "4.기타자본")]
    assert all(p is not None for p in parts), parts
    assert sum(parts) + retained == total, (sum(parts) + retained, total)
