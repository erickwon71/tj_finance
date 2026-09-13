"""연결비대상 확정 근거(2026-09-13, Track 1) 회귀 테스트 (순수 텍스트 판정만, DB 비의존).

docs/plans/consolidation_scope_confirmation_design_2026-09-13.md §2-1 era 분산 표본
원문대조(300+300건 실측, 오탐 0건/재현율 ~99%)에서 확정한 규칙과 실제로 발견된 문구
변형들을 회귀로 고정한다. 각 케이스의 본문 텍스트는 실제 필링에서 그대로 인용했다
(rcept 번호는 §2-1 표 참고).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.consolidation_evidence import (  # noqa: E402
    EVIDENCE_NO_CONSOLIDATED_FS, compute_text_evidence, detect_no_consolidated_fs,
    resolve_filing_evidence,
)


def _wrap(body: str) -> str:
    """실제 필링 구조를 흉내낸 최소 SECTION-2 래퍼."""
    return (
        '<SECTION-2 ACLASS="MANDATORY">'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-3-2-0">2. 연결재무제표</TITLE>'
        f'{body}'
        '</SECTION-2>'
        '<SECTION-2 ACLASS="MANDATORY">'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-3-3-0">3. 연결재무제표 주석</TITLE>'
        '<P></P></SECTION-2>'
    )


def test_no_title_section_returns_false():
    """이 TITLE 자체가 문서에 없으면(pre-2015 전환기 등, §2-1-B) False — 짐작 금지."""
    assert not detect_no_consolidated_fs("<P>연결재무제표 이용상의 유의점...</P>")


def test_real_consolidated_data_is_not_flagged():
    """실제 표(연결 데이터)가 있으면 False — 오탐 금지(대조군 300건 실측 0건 확인)."""
    body = ('<TABLE-GROUP ACLASS="{XBRL}BS_C"><TITLE>2-1. 연결 재무상태표</TITLE>'
            '<TABLE><TBODY><TR><TE>자산총계</TE><TE>1,000,000</TE></TR></TBODY></TABLE>'
            '</TABLE-GROUP>')
    assert not detect_no_consolidated_fs(_wrap(body))


def test_nested_title_inside_table_group_is_not_a_boundary():
    """§2-1 구현 중 발견한 버그 회귀 가드: TABLE-GROUP 안의 하위 TITLE("2-1. 연결
    재무상태표")을 섹션 경계로 오인하면 본문이 표 시작 직후에서 잘려 텅 빈 것처럼 보인다
    (대조군 60건 중 16건 오탐 원인, 수정 후 300건 재검증 0건)."""
    body = ('<TABLE-GROUP ACLASS="{XBRL}BS_C"><TITLE>2-1. 연결 재무상태표</TITLE>'
            '<TABLE><TBODY><TR><TE>자산총계</TE><TE>999</TE></TR></TBODY></TABLE>'
            '</TABLE-GROUP>')
    text = _wrap(body)
    assert not detect_no_consolidated_fs(text)
    code, _ = compute_text_evidence(text)
    assert code is None


def test_empty_section_body_is_confirmed_absent():
    """표/문구 전부 없이 <P></P>만 있으면 확정(세우글로벌/동화약품/파세코 실측 패턴)."""
    assert detect_no_consolidated_fs(_wrap("<P></P>"))


def test_standard_phrase_variants():
    """실측 6개 변형(§2-1-A) — 전부 확정돼야 한다."""
    variants = [
        "<P>해당사항없음.</P>",
        "<P>해당사항 없음.&cr;</P>",
        "<P>당사는 보고서 작성기준일 현재 해당사항이 없습니다.</P>",
        "<P>보고서 제출일 현재 해당사항이 없습니다.</P>",
        "<P>※ 해당사항 없습니다.</P>",
        "<P>본 보고서 제출 기준일 현재 해당사항 없습니다. </P>",
        "<P>- 해당사항 없음</P>",
    ]
    for body in variants:
        assert detect_no_consolidated_fs(_wrap(body)), body


def test_additional_variants_found_during_broader_sampling():
    """60건→300건 확대 검증 중 원문대조로 추가 확인된 변형들(§2-1 구현 로그)."""
    variants = [
        "<P>연결대상에 해당하는 자회사가 없으므로 한국채택국제회계기준에 의한 연결재무제표 작성의무가 없음.</P>",
        "<P>당사는 당기 중 종속회사인 SV Leisure Co., Ltd.를 청산하여 당반기말부터 당사는 "
        "연결재무제표작성대상 종속기업을 보유하고 있지 않습니다.</P>",
        "<P>당사는 본 보고서 제출기준일 현재 연결재무제표 작성 대상에 해당되지 않습니다.</P>",
        "<P>당사는 당분기말과 전기말 현재 연결재무제표 작성대상에 해당하지 않습니다.</P>",
        "<P>당사는 연결재무제표 작성 대상 법인에 해당하지 않습니다.</P>",
        "<P>- 당사는 분기보고서 제출일 현재  연결재무제표와 관련된 사항이 없습니다.&cr;</P>",
        '<P>- 해 당 사 항 없 음&cr;</P>',   # 글자당 공백 강조체(문배철강 실측)
        "<P>- 해당 없음.</P>",              # "사항" 생략형(큐렉소 실측)
        '<P>"당사는 개별재무제표 작성 기준입니다.</P>',  # 긍정형 선언(THE CUBE& 실측)
    ]
    for body in variants:
        assert detect_no_consolidated_fs(_wrap(body)), body


def test_compute_text_evidence_returns_code_and_detail():
    code, detail = compute_text_evidence(_wrap("<P>해당사항 없음.</P>"))
    assert code == EVIDENCE_NO_CONSOLIDATED_FS
    assert "reason" in detail


def test_r106_ifrs_transition_non_restatement_note_is_not_confused_with_no_consolidated_fs():
    """R106(2026-09-13, 사용자 질문으로 발견) — 웅진씽크빅(00628189) 20190401005063 실측:
    "전기 및 전전기 실적은 이를 소급적용하여 재작성하지 않았습니다"(IFRS1109/1115 도입시
    소급재작성 안 함을 알리는 흔한 각주, 연결 존재여부와 무관)가 옛 `작성\\s*(?:하지|치)
    \\s*않` 패턴에 걸려 52건 오탐(report_lines에 실제 연결 BS/IS/CF 수백행 있는데도
    "확정"으로 잘못 판정). "재무제표"가 바로 앞(≤15자)에 붙어야만 매칭하도록 좁힘."""
    body = ('<P>당기실적은 2018년 1월 1일부터 시행되는 한국채택국제회계기준(K-IFRS) '
            '제1109호 및 제1115호를 적용한 결산기준이며, 전기 및 전전기 실적은 이를 '
            '소급적용하여 재작성하지 않았습니다.</P>'
            '<TABLE-GROUP ACLASS="{XBRL}BS"><TABLE><TBODY><TR><TE>연결 재무상태표</TE>'
            '<TE>자산총계</TE><TE>1,000</TE></TR></TBODY></TABLE></TABLE-GROUP>')
    assert not detect_no_consolidated_fs(_wrap(body))


def test_r107_ifrs_transition_restatement_note_adjacent_to_financial_statements_word():
    """R107(2026-09-13, R106 잔여 41건 원문대조 중 발견) — 인텍플러스(00479787)
    20190401003585 실측: "전기 및 전전기 재무제표를 재작성하지 않았습니다"(같은
    IFRS1109/1115 각주지만 "재무제표"가 "재작성" 바로 앞이라 R106의 ≤15자 조건을 그대로
    통과해 28건 오탐, report_lines에 당기 연결 BS 실측 존재). "작성" 바로 앞 1글자가
    "재"(=고정 복합어 "재작성")인 경우만 배제하도록 `(?<!재)` 추가."""
    body = ('<TABLE><TBODY><TR><TD>본 연결재무제표는 한국채택국제회계기준(K-IFRS)에 따라 '
            '작성되었습니다. 제24기, 제23기, 제22기 연결재무제표는 외부감사인의 감사(검토)를 '
            '받은 재무제표입니다.※당사는 2018년 1월 1일 최초적용일로 하여 기업회계기준서 '
            '제1115호 "고객과의 계약에서 생기는 수익" 과 제1109호 "금융상품"을 최초 '
            '적용하였고, 경과규정에 따라 전기 및 전전기 재무제표를 재작성하지 않았습니다. '
            '제23기(전기)는 종전 기준서인 K-IFRS 제1018호 및 K-IFRS 제1039호에 따라 '
            '작성되었습니다.</TD></TR></TBODY></TABLE>'
            '<TABLE-GROUP ACLASS="{XBRL}BS"><TABLE><TBODY><TR><TE>연결 재무상태표</TE>'
            '<TE>자산총계</TE><TE>1,000</TE></TR></TBODY></TABLE></TABLE-GROUP>')
    assert not detect_no_consolidated_fs(_wrap(body))


def test_r108_spac_merger_shell_company_na_declaration_is_not_applied_to_target_company():
    """R108(2026-09-13, 잔여 13건 원문대조 중 발견) — 밸로프(01398151) 20221114002664
    실측: SPAC 껍데기 법인("[교보9호기업인수목적 주식회사]" + "해당사항 없습니다")과
    실제 합병대상 법인("[주식회사 밸로프]")이 같은 섹션에 나란히 서술됨. 밸로프는
    report_lines에 진짜 연결 BS(237.6억, 별도 87.0억과 다른 값) 보유 — SPAC 쪽 결측
    선언이 밸로프에 잘못 적용되면 안 된다."""
    body = ('<P></P><P><SPAN>[교보9호기업인수목적 주식회사]</SPAN></P>'
            '<P>해당사항 없습니다.<SPAN>[주식회사 밸로프]</SPAN></P><P></P>'
            '<TABLE-GROUP ACLASS="{XBRL}BS"><TABLE><TBODY><TR><TE>연 결 재 무 상 태 표</TE>'
            '<TE>자산총계</TE><TE>23,760,531,108</TE></TR></TBODY></TABLE></TABLE-GROUP>')
    assert not detect_no_consolidated_fs(_wrap(body))


def test_r109_na_declaration_scoped_to_comparative_year_only_is_not_confused_with_current_year():
    """R109(2026-09-13, 같은 조사) — YBM넷(00307222) 20220323000611 실측: "1. 당사의
    제22(당)기...연결재무제표는...작성되었으며...2. 비교표시되는 제21(전)기 재무제표는
    연결대상 종속기업이 없는 회사의 재무제표입니다"에서 당기(제22기)는 진짜 연결
    재무제표가 있는데(실측: 연결 831.5억 vs 별도 832.3억, 서로 다른 값) "종속기업이
    없는" 매칭이 전기(제21기) 서술에 걸려 오탐."""
    body = ('<P>1. 당사의 제22(당)기, 제21(전)기 및 제20(전전)기 연결재무제표는 한국채택'
            '국제회계기준(K-IFRS)에따라 작성되었으며, 외부감사인의 감사를 받았습니다. '
            '2. 비교표시되는 제21(전)기 재무제표는 연결대상 종속기업이 없는 회사의 '
            '재무제표입니다.</P>'
            '<TABLE-GROUP ACLASS="{XBRL}BS"><TABLE><TBODY><TR><TE>연결 재무상태표</TE>'
            '<TE>자산총계</TE><TE>8,315,143,3507</TE></TR></TBODY></TABLE></TABLE-GROUP>')
    assert not detect_no_consolidated_fs(_wrap(body))


def test_r110_manual_override_rcepts_skip_text_classification_entirely():
    """R110(2026-09-13, C유형 SGA솔루션즈 00988364 사용자 원문대조 확정) — "제1기만
    연결없음" 패턴은 순번↔실제 회계연도 매핑이 없어 일반 규칙화가 불가능해서, 사용자가
    직접 DART 원문의 당기 자산총계를 확인해 "당기에 연결·별도 실데이터가 둘 다 존재"를
    확정했다. 이 2건은 본문 텍스트와 무관하게(재현해도 다시 오탐될 것이므로) 영구
    예외로 evidence=None을 강제해야 한다 — file_path 없이 호출해도(텍스트 판정 자체를
    건너뛰므로) 결과가 바뀌면 안 된다."""
    for rcept_no in ("20151113001023", "20160329000826"):
        code, detail = resolve_filing_evidence(None, rcept_no)
        assert code is None, (rcept_no, code)
        assert "R110" in detail["reason"]


def test_unrelated_na_phrase_elsewhere_in_document_is_ignored():
    """문서 다른 부분(예: 소송/후발사건)의 흔한 "해당사항 없음"은 이 섹션과 무관하면
    잡히면 안 된다(§2-1-B에서 확인된 함정 — 앵커 없이 문서 전체를 grep하면 오탐)."""
    text = ('<P>중요한 소송사건: 해당사항 없음</P>' + _wrap(
        '<TABLE-GROUP ACLASS="{XBRL}BS_C"><TABLE><TBODY><TR><TE>자산총계</TE>'
        '<TE>1</TE></TR></TBODY></TABLE></TABLE-GROUP>'))
    assert not detect_no_consolidated_fs(text)
