"""Manual unit-scale corrections for self-contradictory filings (2026-09-06).

design: docs/plans/unit_override_self_contradictory_filings_design_2026-09-06.md
context: memory v2-drop-remaining-backlog-2026-09-03.md §2, (가+라) group.

Some filings print a unit label ("(단위:백만원)" etc.) on a table that does not match
the actual magnitude of the numbers underneath it — the source document itself is
wrong, not a parsing bug (report_lines faithfully reflects what was declared;
`_pick_fallback_unit`/`declared_unit()` etc. already read the printed label correctly).
This module lets a human, after checking the original filing (this project's ★원문
대조검증 원칙 — never guess), correct such cells at combine-time.

report_lines stays untouched (it must remain a faithful "as declared" extraction) —
the correction is applied in `combine.py::combine_full()` as the very last step, after
DIRECT_MAP/_resolve()/every other curated override has produced `col`, so it always
wins for the exact (corp, fiscal_year, fiscal_period, statement_type, concept) key
listed here.

Key includes `concept` (the DIRECT_MAP canonical, e.g. "bs.retained_earnings"), not
just the std column name, because a single filing can have some concepts correct and
others self-contradictory (see 나이스디앤비/00606293: revenue was a separate,
already-fixed bug — R72 — while total_assets is this kind of source-label error).

Each entry MUST cite what was checked (rcept_no + a specific printed value) and when.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitOverride:
    # corrected_value = declared_value * multiplier. Typically a power of 10
    # (e.g. 1e-6 to undo an errant "백만원" label, 1e-3 for "천원").
    multiplier: float
    note: str


# Key: (corp_code, fiscal_year, fiscal_period, statement_type, concept)
UNIT_OVERRIDES: dict[tuple[str, int, str, str, str], UnitOverride] = {
    # 00138516 아남전자 FY2006 — v2-drop-remaining-backlog-2026-09-03.md (가+라) 그룹.
    # BS의 "1.처분전이익잉여금(결손금)" 행 라벨 자체가 괄호 안에 "당기순이익(손실):
    # 제34기: 2,146,172,472원"이라고 원 단위로 명시하는데, 같은 표의 단위선언
    # "(단위:백만원)"을 따라 adecimal=-6이 적용돼 report_lines.value_won이
    # 2,146,172,472,000,000으로 저장됨(×10^6 과대). 같은 회사의 같은 rcept 안
    # 이익잉여금처분계산서(APPR)가 독립적으로 2,146,172,472(원 단위, adecimal=0)를
    # 보고해 교차검증됨. std_financials_v3에서도 인접 분기(H1/Q3, 자본총계 ~390억원)
    # 대비 FY 값만 10^6배 튀는 것으로 재확인. 원문: annual/2006/20070330000181.xml.
    # 원문대조: 2026-09-06.
    ("00138516", 2006, "FY", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6,
        note="BS '1.처분전이익잉여금(결손금)' 행 라벨 자체가 '당기순이익(손실): "
             "제34기: 2,146,172,472원'이라 원 단위로 명시하는데, 표 선언 "
             "'(단위:백만원)'을 따라 ×10^6 오적용됨. 같은 rcept의 이익잉여금처분계산서가 "
             "2,146,172,472(원 단위)를 독립적으로 재확인. "
             "원문: annual/2006/20070330000181.xml. 원문대조 2026-09-06.",
    ),
    ("00138516", 2006, "FY", "separate", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6,
        note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 별도=연결).",
    ),

    # 00102858 고려아연 2000H1/Q3 — (가+라) 그룹, 2026-09-06 원문대조(메모리
    # v2-drop-remaining-backlog-2026-09-03.md, 이전 세션에서 LegacyDartScraper.fetch()로
    # 원문 PDF 텍스트까지 직접 재수집·대조 완료: "연결대차대조표"가 "(단위:천원)"라
    # 인쇄돼 있는데 실제 숫자는 이미 원 단위 규모). 이번 세션 DB 재확인:
    # 별도(separate) 기준 자산총계 1,121,648,359,089(H1)/1,161,659,097,379(Q3, 원단위
    # adecimal=0)와 규모가 맞으려면 연결값도 ×10^-3 필요 — 1,607,305,757,650,000×
    # 10^-3=1,607,305,757,650(1.6조원), 별도보다 크고 합리적. H1/Q3 둘 다 같은 rcept류
    # 연결 원본값이 동일(K-GAAP시대 연결 반기/3분기 재작성 의무 없음 — 참고용 재게재).
    ("00102858", 2000, "H1", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="고려아연 연결BS '(단위:천원)' declared가 실제로는 이미 "
        "원단위인 자기모순. 별도기준(adecimal=0, 원문PDF검증됨) 규모와 대조 확인."),
    ("00102858", 2000, "H1", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 total_assets와 동일 표·동일 근거."),
    ("00102858", 2000, "Q3", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="위 H1과 동일 원본값 재게재(연결 인터림 작성의무 없던 시기)."),
    ("00102858", 2000, "Q3", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 H1과 동일 원본값 재게재(연결 인터림 작성의무 없던 시기)."),

    # 00113207 대한전선 2001Q3 — (가+라) 그룹, 이전 세션 LegacyDartScraper.fetch()로
    # 원문 PDF 대조 완료: "연결대차대조표"가 "(단위:백만원)"라 인쇄돼 있는데 실제
    # 숫자는 별도재무제표와 같은 천원 규모(템플릿 복붙 오류로 추정). 이번 세션 재확인:
    # 별도 자산총계 1,324,190,744,000(adecimal=-3, 원문PDF검증됨, 1.32조원) 대비
    # 연결값 1,301,154,371,000,000×10^-3=1,301,154,371,000(1.30조원)로 같은 규모.
    ("00113207", 2001, "Q3", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="대한전선 연결BS '(단위:백만원)' declared가 별도(adecimal=-3, "
        "원문PDF검증됨) 규모와 맞으려면 ×10^-3 필요 — 템플릿 단위 복붙 오류로 추정."),

    # 00117601(2000FY) — 신규 조사(2026-09-06), 은행/금융사(수수료수익·이자수익·
    # 대출채권·예치금·후순위사채 등 계정과목으로 확인). 표 declared adecimal=-3인데
    # BS 항등식(자산=부채+자본)이 raw*10^-3에서만 정확히 성립: 부채총계
    # 1,639,964,273,866,000×10^-3=1,639,964,273,866 + 자본총계
    # 507,124,189,018,000×10^-3=507,124,189,018 = 2,147,088,462,884 = 자산총계
    # 2,147,088,462,884,000×10^-3 (원문: annual/2000/20000629000206.xml). 인접연도
    # (2001FY 자산 1.25조·2002FY 4.4조)와도 규모 일치. basis_fallback으로 별도=연결.
    ("00117601", 2000, "FY", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="BS 항등식(자산=부채+자본)이 raw×10^-3에서 정확히 성립 확인 "
        "(annual/2000/20000629000206.xml). 인접연도 규모(1~5조원대)와도 일치."),
    ("00117601", 2000, "FY", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 total_assets와 동일 표·동일 항등식 근거."),
    ("00117601", 2000, "FY", "separate", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),
    ("00117601", 2000, "FY", "separate", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),

    # 00138701 아세아 2007H1/Q3 — (가+라) 그룹, 2026-09-06 원문 XML 직접대조
    # (half/2007/20070814000868.xml): 연결BS "자 산 총 계" 행의 실제 인쇄값이
    # "1,038,181,374,181"(원문 텍스트 그대로) — declared adecimal=-3("단위:천원")을
    # 적용하면 안 되는 이미 원단위 규모. 항등식 재확인: 부채총계 351,206,722,301,000
    # ×10^-3=351,206,722,301 + 자본총계 686,974,651,880,000×10^-3=686,974,651,880 =
    # 1,038,181,374,181 = 자산총계×10^-3, 정확 일치. H1/Q3 두 rcept가 동일 연결값
    # 재게재(연결 인터림 작성의무 없던 시기, 00102858과 같은 패턴).
    ("00138701", 2007, "H1", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="원문(half/2007/20070814000868.xml) '자산총계' 인쇄값이 이미 "
        "원단위(1,038,181,374,181)로 declared '(단위:천원)'과 자기모순. 항등식 정확 성립 확인."),
    ("00138701", 2007, "H1", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 total_assets와 동일 표·동일 항등식 근거."),
    ("00138701", 2007, "H1", "consolidated", "bs.total_liabilities"): UnitOverride(
        multiplier=1e-3, note="위 total_assets와 동일 표·동일 항등식 근거."),
    ("00138701", 2007, "Q3", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="위 H1과 동일 원본값 재게재(연결 인터림 작성의무 없던 시기)."),
    ("00138701", 2007, "Q3", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 H1과 동일 원본값 재게재(연결 인터림 작성의무 없던 시기)."),
    ("00138701", 2007, "Q3", "consolidated", "bs.total_liabilities"): UnitOverride(
        multiplier=1e-3, note="위 H1과 동일 원본값 재게재(연결 인터림 작성의무 없던 시기)."),

    # 00143226 엠투엔 2004Q3 — (가+라) 그룹, 2026-09-06 원문 XML 직접대조
    # (quarter/2004/20041109000245.xml): IS "Ⅰ. 매출액" 행의 실제 인쇄값이
    # "5,047,789,251"(원문 텍스트 그대로) — declared "(단위:백만원)"를 적용하면 안
    # 되는 이미 원단위 규모(회사 자산 규모 200~300억원대와 일치). 별도재무제표만
    # 존재(basis_fallback으로 연결=별도).
    ("00143226", 2004, "Q3", "consolidated", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="원문(quarter/2004/20041109000245.xml) 'Ⅰ.매출액' 인쇄값이 "
        "이미 원단위(5,047,789,251)로 declared '(단위:백만원)'과 자기모순."),
    ("00143226", 2004, "Q3", "separate", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "연결=별도)."),

    # 00163673(2000H1) — 신규 조사(2026-09-06), PDF 복구 트랙 산출물(unit_source='pdf',
    # 00102858/00113207과 같은 시기·같은 원인 계열). 같은 회사의 2000Q1 행이 이미
    # 정상 규모(adecimal=0, 자산총계 3,564,947,303,755)로 저장돼 있는데, H1의
    # declared adecimal=-3 원본값(3,564,947,303,755,000)을 ×10^-3 하면 Q1과 정확히
    # 동일한 숫자 — 같은 연결 데이터가 재게재된 것으로 확인(연결 인터림 작성의무
    # 없던 시기).
    ("00163673", 2000, "H1", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="같은 회사 2000Q1(adecimal=0)의 자산총계 3,564,947,303,755와 "
        "×10^-3 후 정확히 일치 확인 — 연결 데이터 재게재(인터림 작성의무 없던 시기)."),
    ("00163673", 2000, "H1", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 total_assets와 동일 표·동일 근거."),
    ("00163673", 2000, "H1", "separate", "bs.total_assets"): UnitOverride(
        multiplier=1e-3, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),
    ("00163673", 2000, "H1", "separate", "bs.total_equity"): UnitOverride(
        multiplier=1e-3, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),

    # 00260958 케이티알파 2000H1 — 신규 조사(2026-09-06), PDF 복구 트랙 산출물(R72
    # 전사백필에서 함께 발견, unit_source='pdf'). declared adecimal=-6인데 ×10^-6
    # 하면 인접연도(1999FY 자산 2,733억원·2000FY 자산 2,616억원)와 같은 규모(2000H1
    # 자산 2,737억원)로 수렴 — 00102858/00113207과 같은 시기·같은 계열의 PDF 복구
    # 단위오염으로 판단. 원문 PDF 재수집(LegacyDartScraper)까지는 하지 않았고
    # 인접기간 규모 정합성으로 확인(중간 신뢰도 — 향후 원문 PDF 직접대조 권장).
    ("00260958", 2000, "H1", "consolidated", "bs.total_assets"): UnitOverride(
        multiplier=1e-6, note="인접연도(1999FY 2,733억·2000FY 2,616억)와 같은 규모로 수렴 "
        "확인(2,737억). 원문 PDF 직접대조는 미실시(중간 신뢰도)."),
    ("00260958", 2000, "H1", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-6, note="위 total_assets와 동일 표·동일 근거."),
    ("00260958", 2000, "H1", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="위 total_assets와 동일 표·동일 근거."),
    ("00260958", 2000, "H1", "separate", "bs.total_assets"): UnitOverride(
        multiplier=1e-6, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),
    ("00260958", 2000, "H1", "separate", "bs.total_equity"): UnitOverride(
        multiplier=1e-6, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),
    ("00260958", 2000, "H1", "separate", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),

    # 00366942 미코 2004H1 — (가+라) 그룹, 2026-09-06 원문 XML 직접대조
    # (half/2004/20040813001345.xml): BS "6.처분전이익잉여금" 행 라벨 자체가 괄호
    # 안에 "반기순이익:4,252,326,282원"이라고 원 단위로 명시. 같은 rcept의
    # 이익잉여금처분계산서(APPR) "IV.차기이월이익잉여금"(전기이월,
    # col_index=0)=2,292,974,734와 더하면 2,292,974,734+4,252,326,282=
    # 6,545,301,016 — BS raw×10^-6(6,545,301,016)와 정확 일치. "Ⅲ.이익잉여금"
    # 총계행(9,950,218,965,000,000)도 같은 표·같은 declared 오류로 함께 ×10^-6.
    ("00366942", 2004, "H1", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="BS 행 라벨 자체에 '반기순이익:4,252,326,282원' 명시 + APPR "
        "전기이월(2,292,974,734)과의 합이 raw×10^-6과 정확 일치 확인."),
    ("00366942", 2004, "H1", "separate", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="위 consolidated 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "별도=연결)."),

    # 00400121 유아이디 2020Q1 — (가+라) 그룹, 2026-09-06 원문 XML 직접대조
    # (quarter/2020/20200601000502.xml): "이익잉여금(결손금)" 행 인쇄값이
    # "(2,695,312,230)"(연결)/각주 "18-4 이익잉여금" 표가 명시적으로 "(단위 : 원)"
    # 선언 + "합 계" 행도 동일값 재확인. "매출액" 행도 별도 요약표(천원단위
    # "7,356,347")와 원단위 정밀값(7,356,347,189)이 반올림 일치.
    ("00400121", 2020, "Q1", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="원문 각주 '18-4 이익잉여금' 표가 명시적으로 '(단위 : 원)' "
        "선언 + 본문 인쇄값 (2,695,312,230)과 정확 일치 확인."),
    ("00400121", 2020, "Q1", "separate", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="원문 인쇄값 (2,697,895)천원 요약표와 정밀값 "
        "(2,697,894,422) 반올림 일치 확인."),
    ("00400121", 2020, "Q1", "separate", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="원문 요약표 '매출액' 7,356,347천원과 정밀값 "
        "7,356,347,189 반올림 일치 확인."),

    # 00487546 웰크론한텍 2010H1 — (가+라) 그룹, 2026-09-06 원문 XML 직접대조
    # (half/2010/20100816001285.xml): 손익계산서 "매출액" 행의 실제 인쇄값이
    # "7,206,472,963"(원문 텍스트 그대로, 하위 "제품매출액" 7,150,072,962도 같은
    # 표에서 동일 패턴) — declared "(단위:백만원)"를 적용하면 안 되는 이미 원단위
    # 규모. 별도재무제표만 존재.
    ("00487546", 2010, "H1", "separate", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="원문(half/2010/20100816001285.xml) '매출액' 인쇄값이 이미 "
        "원단위(7,206,472,963)로 declared '(단위:백만원)'과 자기모순."),
    ("00487546", 2010, "H1", "consolidated", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="위 separate 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "연결=별도)."),

    # ── R74 트랙③④⑤ 재분류 후속(2026-09-06) — v2-drop-remaining-backlog-2026-09-03.md
    # (가+라) 그룹 후속 편입분. 원문대조: PARSING_RULES.md R74 절 참고.

    # 00133751 세명전기 2004H1(rcept 20040814000049) — 원래 "declared 경계오판정"(다)
    # 그룹이었으나 R74 사전조사로 (가+라)와 같은 자기모순 단위로 재분류(§(다) 카테고리
    # 소멸). BS는 declared '(단위:원)'·adecimal=0으로 정상(자산총계 26,270,052,307원 등
    # 상식적 규모)인데, IS·CF만 declared '(단위:백만원)'·adecimal=-6가 붙어 자기모순 —
    # 별도재무제표만 존재(연결 없음, basis_fallback). 교차검증 다중: ① IS 자체에 "주당순이익"
    # 두 행이 있는데 하나(처분계산서류, adecimal=0)=27원, 다른 하나(IS 본문,
    # adecimal=-6 raw=26,000,000)를 ×10^-6하면 26원 — 거의 일치. ② CF "Ⅵ.기말의 현금"
    # raw=1,265,326,806,000,000을 ×10^-6하면 1,265,326,806원인데, 이는 BS(정상 원단위)
    # "1.현금및현금등가물"=1,265,326,806원과 숫자가 정확히 일치(같은 날짜 잔액이므로
    # 당연히 같아야 함) — 배수 오류를 자릿수 단위까지 확정. 이 표들이 소비하는 DIRECT_MAP
    # 개념 전부(revenue~dividends_paid)를 함께 보정한다 — 하나만 고치면 다른 개념이
    # 그대로 ×10^6 오염 상태로 남아 std_v3 안에서 서로 스케일이 안 맞는 상태가 된다.
    ("00133751", 2004, "H1", "separate", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="IS·CF declared '(단위:백만원)' 자기모순(BS는 원단위로 정상) "
        "— CF 기말현금(÷10^6)이 BS 현금잔액과 숫자까지 정확 일치해 확정."),
    ("00133751", 2004, "H1", "separate", "is.cogs"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.gross_profit"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.sga"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.operating_income"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.interest_expense"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.ebt"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.tax_expense"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거 — 주당순이익 교차검증(26원)도 "
        "이 값과 정합."),
    ("00133751", 2004, "H1", "separate", "is.controlling_ni"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "cf.operating"): UnitOverride(
        multiplier=1e-6, note="CF declared '(단위:백만원)' 자기모순 — 기말현금(÷10^6)이 BS "
        "현금잔액과 정확 일치해 확정."),
    ("00133751", 2004, "H1", "separate", "cf.investing"): UnitOverride(
        multiplier=1e-6, note="위 cf.operating과 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "cf.financing"): UnitOverride(
        multiplier=1e-6, note="위 cf.operating과 동일 표·동일 근거."),
    ("00133751", 2004, "H1", "separate", "cf.dividends_paid"): UnitOverride(
        multiplier=1e-6, note="위 cf.operating과 동일 표·동일 근거."),
    # consolidated는 이 회사에 연결재무제표가 없어 basis_fallback으로 separate를 그대로
    # 복사한다 — 같은 근거로 전부 반복 등록(00138516 등 기존 관례).
    ("00133751", 2004, "H1", "consolidated", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="위 separate 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "연결=별도)."),
    ("00133751", 2004, "H1", "consolidated", "is.cogs"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.gross_profit"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.sga"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.operating_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.interest_expense"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.ebt"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.tax_expense"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "is.controlling_ni"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback) — 이 회사 consolidated는 controlling_ni "
        "가 NULL이라 실제 적용은 무동작."),
    ("00133751", 2004, "H1", "consolidated", "cf.operating"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "cf.investing"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "cf.financing"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00133751", 2004, "H1", "consolidated", "cf.dividends_paid"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),

    # 01344363 다원넥스뷰 2024H1(rcept 20240813000596) — 원래 "declared 경계오판정"(다)
    # 그룹. R74(else 분기, 00204226와 같은 컬럼압축 메커니즘)로 컬럼밀림 증상은 이미
    # 해소됐지만, 근본원인인 자기모순 단위(선언 백만원·인쇄 원) 자체는 그대로 남아 있어
    # 별도 unit_overrides 등록이 필요(§(다) 카테고리 소멸 시 확정한 재분류). 별도재무제표만
    # 존재(연결 없음). BS·IS·CF 전 표가 같은 자기모순(declared '(단위:백만원)', adecimal=-6,
    # 실제 인쇄값은 이미 원단위) — BS "자본총계" raw=3,783,475,775,000,000를 ×10^-6하면
    # 3,783,475,775원(38억원)으로 소형 상장사 규모에 부합.
    ("01344363", 2024, "H1", "separate", "bs.total_equity"): UnitOverride(
        multiplier=1e-6, note="BS declared '(단위:백만원)' 자기모순(실제 인쇄값 이미 원단위) — "
        "÷10^6하면 소형 상장사 규모(38억원)에 부합."),
    ("01344363", 2024, "H1", "separate", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="위 bs.total_equity와 동일 표군·동일 근거."),
    ("01344363", 2024, "H1", "separate", "is.cogs"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "is.operating_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "is.ebt"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "is.tax_expense"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "cf.operating"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "cf.investing"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "separate", "cf.financing"): UnitOverride(
        multiplier=1e-6, note="위와 동일 근거."),
    ("01344363", 2024, "H1", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-6, note="위 separate 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "연결=별도)."),
    ("01344363", 2024, "H1", "consolidated", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "is.cogs"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "is.operating_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "is.ebt"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "is.tax_expense"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "cf.operating"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "cf.investing"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("01344363", 2024, "H1", "consolidated", "cf.financing"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),

    # 00122825 (2003 Q3, is_final rcept 20031203000256) — 원래 "DART 503 재수집" 분류였으나
    # R74 재조사로 파일 자체는 온전(에러 아님) 확인 — 연결 BS만 자기모순 단위((가+라)
    # 그룹으로 재편입, 별도는 정상). "Ⅲ.연결이익잉여금(주석17)" 라벨 자체에 실측 순손실
    # "당기: -8,129,513,066원"이 원단위로 명시돼 있어 이 표가 원단위임을 뒷받침.
    ("00122825", 2003, "Q3", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="연결BS declared '(단위:백만원)' 자기모순(별도는 정상 원단위 "
        "선언) — 라벨 자체에 실측 순손실 -8,129,513,066원이 원단위로 명시돼 뒷받침."),

    # 00125488 (2003 H1, rcept 20030814000591) — 원래 "DART 503 재수집" 분류였으나 R74
    # 재조사로 파일 온전 확인, (가+라) 그룹으로 재편입. BS는 declared 원단위로 정상
    # (자본총계 19,049,109,619원)인데 IS만 declared '(단위:백만원)' 자기모순(별도=연결
    # basis_fallback). 매출액÷10^6=5,929,790,300원 — 자본총계(19B) 대비 매출 비율이
    # 상식적 규모로 회복됨.
    ("00125488", 2003, "H1", "separate", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="IS declared '(단위:백만원)' 자기모순(BS는 원단위로 정상) — "
        "÷10^6하면 BS 자본총계(19B원) 대비 상식적 매출 규모로 회복."),
    ("00125488", 2003, "H1", "separate", "is.operating_income"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00125488", 2003, "H1", "separate", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="위 is.revenue와 동일 표·동일 근거."),
    ("00125488", 2003, "H1", "consolidated", "is.revenue"): UnitOverride(
        multiplier=1e-6, note="위 separate 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "연결=별도)."),
    ("00125488", 2003, "H1", "consolidated", "is.operating_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),
    ("00125488", 2003, "H1", "consolidated", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),

    # 00133618 (2003 H1, rcept 20030814001940) — 원래 "DART 503 재수집" 분류였으나 R74
    # 재조사로 파일 온전 확인, (가+라) 그룹으로 재편입. 이 필링은 00125488과 반대 패턴 —
    # BS declared '(단위:백만원)' 전체가 자기모순(IS·매출액·영업이익 등은 이미 원단위로
    # 정상, dq_assertions에도 안 걸림). "자본총계" raw=9,199,455,550,000,000 ÷10^6=
    # 9,199,455,550원.
    ("00133618", 2003, "H1", "separate", "bs.total_equity"): UnitOverride(
        multiplier=1e-6, note="BS declared '(단위:백만원)' 전체가 자기모순(IS는 이미 원단위로 "
        "정상이라 손대지 않음) — ÷10^6하면 상식적 자본총계 규모(92억원)."),
    ("00133618", 2003, "H1", "separate", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="위 bs.total_equity와 동일 표·동일 근거."),
    ("00133618", 2003, "H1", "consolidated", "bs.total_equity"): UnitOverride(
        multiplier=1e-6, note="위 separate 항목과 동일 근거(이 회사는 basis_fallback으로 "
        "연결=별도)."),
    ("00133618", 2003, "H1", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="위와 동일(basis_fallback)."),

    # 00124799 사조산업 FY2001(rcept 20020401000221, 연결만 — 별도는 정상이라 미등록) —
    # 원래 "DART 503 재수집" 분류였으나 R74 재조사로 파일 온전 확인. 이 필링의 연결
    # IS/BS는 개념매핑 자체가 틀린 라인(주석. is.revenue가 실제로는 "3.수수료수익"을,
    # is.cogs가 "7.기타매출원가" 한 줄만 잘못 집은 것으로 보임 — 별개의 계정매퍼 버그
    # 후보, 이번 세션 범위 밖이라 그 두 개념은 등록하지 않는다)와 순수 자기모순 단위
    # 라인이 섞여 있어, **원문대조로 매핑이 맞다고 확인된 것만** 등록한다. 당기순이익
    # 계열은 라벨 안에 박힌 "주당 순이익: 당기 3,967원"과 ÷10^6 후 주식수 역산(≈106만주,
    # 소형 상장사 규모에 부합)으로 교차검증.
    ("00124799", 2001, "FY", "consolidated", "bs.retained_earnings"): UnitOverride(
        multiplier=1e-6, note="연결BS declared '(단위:백만원)' 자기모순(별도는 정상) — 같은 "
        "규모대의 다른 항목들과 일관된 ÷10^6."),
    ("00124799", 2001, "FY", "consolidated", "is.ebt"): UnitOverride(
        multiplier=1e-6, note="연결IS 같은 표·동일 자기모순."),
    ("00124799", 2001, "FY", "consolidated", "is.tax_expense"): UnitOverride(
        multiplier=1e-6, note="연결IS 같은 표·동일 자기모순."),
    ("00124799", 2001, "FY", "consolidated", "is.net_income"): UnitOverride(
        multiplier=1e-6, note="라벨에 박힌 '주당 순이익: 당기 3,967원'으로 ÷10^6 후 주식수 "
        "역산(≈106만주, 소형 상장사 규모)해 교차검증. is.revenue/is.cogs는 개념매핑 자체가 "
        "틀린 것으로 보여(주석. 별도 계정매퍼 버그 후보) 이번엔 등록하지 않음."),
}


def apply_unit_overrides(corp: str | None, fy: int | None, period: str, basis: str,
                         direct_map: dict[str, str], col: dict[str, int],
                         overrides: dict | None = None) -> dict:
    """Apply every curated override matching (corp, fy, period, basis), mutating `col`
    in place. Returns {std_col: {...}} for the cells actually touched (empty if none) —
    callers persist this as StdFinancialV3.unit_overrides for traceability.

    direct_map: pass combine.py's DIRECT_MAP (canonical -> std_col) so this module
    doesn't need to import combine.py/rules.py and risk a circular import.
    overrides: defaults to the module-level UNIT_OVERRIDES; tests pass a fixture dict
    instead so they don't depend on (or need to mutate) the curated production list.
    """
    if corp is None or fy is None:
        return {}
    if overrides is None:
        overrides = UNIT_OVERRIDES
    applied: dict[str, dict] = {}
    for (c, y, p, b, concept), ov in overrides.items():
        if (c, y, p, b) != (corp, fy, period, basis):
            continue
        std_col = direct_map.get(concept)
        if std_col is None or col.get(std_col) is None:
            continue
        declared_value = col[std_col]
        corrected_value = round(declared_value * ov.multiplier)
        col[std_col] = corrected_value
        applied[std_col] = {
            "concept": concept,
            "declared_value": declared_value,
            "corrected_value": corrected_value,
            "multiplier": ov.multiplier,
            "note": ov.note,
        }
    return applied
