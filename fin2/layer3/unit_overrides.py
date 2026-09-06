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
