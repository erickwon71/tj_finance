"""R161(2026-09-22) 회귀 테스트 — 각주 문장이 **표제 앞에** 붙어 분류를 밀어내던 결함.

## 무엇이 문제였나

하나의 `<P>` 가 **[직전 표의 각주] + [다음 표의 제목]** 을 함께 담는 서식이 있다.
분류기가 그 텍스트를 읽으면 각주에 언급된 **앞 재무제표명**이 먼저 걸려 제목 판정이
한 칸씩 밀린다.

실측(캠페인 이슈#26) — 삼성화재해상보험 `20190515002191` 별도 섹션:

    <P> '註) 당분기 자본변동표는 … 아니하였습니다. 분 기 현 금 흐 름 표'

이 `<P>` 가 현금흐름표 데이터표(82행)의 직전 형제다. 분류가 'SCE' 가 되어 **별도
현금흐름표가 자본변동표로 오분류**됐다 — 별도 CF 0행, 별도 SCE 는 398행으로 부풀었다.

★**자간 공백은 원인이 아니다.** `'분 기 현 금 흐 름 표'` 는 공백이 그대로 있어도
'CF' 로 정확히 분류된다(분류기가 이미 처리한다). 걸리는 건 앞에 붙은 각주뿐이다.

★**두 경로 모두 고쳐야 한다** — `title_text_for_classify` 에만 넣었더니 각주표(5행)가
`title_text_owned` 경로로 여전히 'SCE' 로 분류돼 '제목표/데이터표 분리' 분기가 CF
데이터를 SCE 로 끌어왔다(별도 SCE 에 CF 라벨 28행 잔존). R144/R153 의 교훈.

★`title_text` 자체는 고치지 않는다 — `declared_unit` 이 단위줄 원문을 필요로 한다.

실행: pytest fin2/tests/test_r161_note_before_title.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                      # noqa: E402

from fin2.extract.statement_titles import (                        # noqa: E402
    strip_leading_note_sentences as strip,
)
from fin2.extract.text import classify_statement_in_body_section   # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_SF = (_ROOT / "raw_report/KOSPI/00139214_삼성화재해상보험"
               "/quarter/2019/20190515002191.xml")

_NOTE_CF = ("註) 당분기 자본변동표는 기업회계기준서 제1116호를 적용하여 작성되었으며, "
            "비교표시된 자본변동표는 이와 관련하여 소급재작성되지 아니하였습니다. "
            "분 기 현 금 흐 름 표")


# ───────────────────── 각주 제거 자체 ─────────────────────

def test_strips_leading_note_and_keeps_the_title():
    assert strip(_NOTE_CF) == "분 기 현 금 흐 름 표"


def test_strips_hangul_note_marker():
    text = ("주) 비교표시된 재무상태표는 소급재작성되지 아니하였습니다. "
            "분 기 손 익 계 산 서")
    assert strip(text) == "분 기 손 익 계 산 서"


def test_company_name_paren_ju_is_not_a_note():
    """★`(주)삼성…` 의 '주)' 를 각주로 오인하면 실제 텍스트를 먹는다.

    맨 앞에서만 각주를 인정하므로, 앞에 '(' 가 붙은 회사명은 걸리지 않는다.
    """
    text = "(주)삼성화재해상보험 재무상태표 제70기"
    assert strip(text) == text


def test_text_without_note_is_unchanged():
    assert strip("분 기 현 금 흐 름 표") == "분 기 현 금 흐 름 표"
    assert strip("") == ""


def test_note_only_text_becomes_empty():
    """각주뿐인 형제는 빈 문자열이 되어 메타줄처럼 건너뛰어진다."""
    assert strip("註) 각주만 있습니다.") == ""


# ──────────────── 분류가 실제로 바로잡히는지 ────────────────

def test_classification_flips_from_sce_to_cf():
    """★이 테스트가 결함 자체를 재현한다 — 각주가 붙어 있으면 SCE 로 잘못 간다."""
    assert classify_statement_in_body_section(
        _NOTE_CF, include_sce=True) == "SCE"          # 결함 재현
    assert classify_statement_in_body_section(
        strip(_NOTE_CF), include_sce=True) == "CF"    # 수정 후


def test_letter_spacing_alone_is_not_the_problem():
    """자간 공백은 원인이 아님을 못박는다(오진 방지)."""
    assert classify_statement_in_body_section(
        "분 기 현 금 흐 름 표", include_sce=True) == "CF"


# ──────────────── 두 경로 배선 ────────────────

def test_both_title_paths_strip_notes():
    src = (_ROOT / "fin2/extract/statement_titles.py").read_text(encoding="utf-8")
    owned = src.split("def title_text_owned", 1)[1].split("\ndef ", 1)[0]
    forcls = src.split("def title_text_for_classify", 1)[1].split("\ndef ", 1)[0]
    assert "strip_leading_note_sentences" in owned
    assert "strip_leading_note_sentences" in forcls
    # ★`title_text` 는 건드리지 않는다(declared_unit 이 단위줄 원문을 쓴다)
    plain = src.split("def title_text(", 1)[1].split("\ndef ", 1)[0]
    assert "strip_leading_note_sentences" not in plain


# ──────────────── 실제 필링 원문 대조 ────────────────

@pytest.mark.skipif(not _SF.exists(), reason="원문 XML 없음")
def test_samsung_fire_separate_cf_is_recovered():
    """별도 CF 가 제 라벨로 오고, 별도 SCE 에서 CF 언어가 사라지는지."""
    from fin2.extract.report_lines import extract_report_lines, _is_loadable
    lines = extract_report_lines(
        str(_SF), rcept_no="20190515002191", corp_code="00139214",
        report_fiscal_year=2019, report_fiscal_period="Q1")
    loadable = [l for l in lines if _is_loadable(l)]
    cf_sep = [l for l in loadable
              if l.statement == "CF" and l.basis == "separate"]
    assert len(cf_sep) > 50, len(cf_sep)
    assert any("영업활동으로 인한 현금흐름" in (l.label_raw or "") for l in cf_sep)
    # SCE 에 CF 언어가 남아 있으면 안 된다
    sce_sep = [l for l in loadable
               if l.statement == "SCE" and l.basis == "separate"]
    assert not [l for l in sce_sep if "활동으로" in (l.label_raw or "")]
    # 나머지 scope 는 불변이어야 한다(가산적 수정)
    def n(stmt, basis):
        return sum(1 for l in loadable
                   if l.statement == stmt and l.basis == basis)
    assert n("BS", "consolidated") == 38
    assert n("BS", "separate") == 35
    assert n("IS", "consolidated") == 58
    assert n("IS", "separate") == 54
    assert n("CF", "consolidated") == 83
    assert n("SCE", "consolidated") == 143
