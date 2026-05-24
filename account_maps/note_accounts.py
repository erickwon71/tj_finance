"""
주석(Notes) 구조화 데이터 계정 매핑

현금흐름표에서 직접 추출하거나, 주석 테이블에서 별도 추출하는 항목들.
"""

NOTE_ACCOUNTS: dict[str, list[str]] = {

    # ── 감가상각 (현금흐름표 조정 항목에서 추출) ─────────────────────
    "note.depreciation": [
        "감가상각비",
        "유형자산감가상각비",
        "투자부동산감가상각비",
    ],
    "note.amortization": [
        "무형자산상각비",
        "무형자산감가상각비",
    ],
    # 사용권자산 감가상각비 (Right-Of-Use asset depreciation, IFRS 16)
    "note.rou_depreciation": [
        "사용권자산상각비",
        "리스자산감가상각비",
        "사용권 자산상각비",
        "사용권자산 감가상각비",
    ],
    # legacy typo alias (aggregator handles both)
    "note.roa_depreciation": [],
    "note.da_total": [
        "감가상각비및무형자산상각비합계",
        "상각비합계",
    ],

    # ── CAPEX 세부 (주석 유형자산 테이블에서) ────────────────────────
    "note.capex_land": [
        "토지취득",
    ],
    "note.capex_building": [
        "건물취득",
    ],
    "note.capex_machinery": [
        "기계장치취득",
    ],
    "note.capex_construction_in_progress": [
        "건설중인자산", "건설중인자산취득",
        "진행중인공사",
    ],

    # ── 리스 관련 ─────────────────────────────────────────────────────
    "note.lease_liability_current": [
        "유동리스부채",
    ],
    "note.lease_liability_noncurrent": [
        "비유동리스부채",
    ],

    # ── 주주환원 ──────────────────────────────────────────────────────
    "note.dividend_per_share": [
        "주당배당금", "1주당배당금",
    ],
    "note.dividend_total": [
        "배당금총액", "현금배당금",
    ],
    "note.treasury_stock_purchase": [
        "자기주식취득금액",
    ],

    # ── 주석 테이블 구조 레이블 (고빈도 미매핑 → unknown_accounts 오염 방지) ──
    # 이 항목들은 실제 금융 데이터가 아닌 테이블 헤더/레이블
    # aggregator에서 집계 안 되며, unknown_accounts 노이즈 감소 목적
    "note.table_label": [
        "소계",           # NOTE_C 소계 (648,009건)
        "회사명",         # NOTE 기업명 열 (215,543건)
        "주주명",         # NOTE 주주명 열 (157,102건)
        "성명",           # NOTE 임원/주주 이름 열 (117,616건)
        "미상환잔액",     # NOTE 차입금 잔액 열 (115,621건)
        "합계",           # NOTE 합계 행 (110,096건) — BS에서도 매핑되나 NOTE에선 별도 처리
        "사모",           # NOTE 사모채 (94,407건)
        "잔여만기",       # NOTE 만기 정보 열 (93,777건)
        "계정과목",       # NOTE 계정과목 열헤더 (93,613건)
        "금액",           # NOTE 금액 열헤더
        "구분",           # NOTE 구분 열헤더
        "내역",           # NOTE 내역 열헤더
        "비고",           # NOTE 비고 열헤더
        "기준일",         # NOTE 기준일 열헤더
        "발행일",         # NOTE 발행일
        "만기일",         # NOTE 만기일
        "이자율",         # NOTE 이자율 열헤더
        "보증금액",       # NOTE 보증금액
        "차입금종류",     # NOTE 차입금 종류 열
        "거래처",         # NOTE 거래처
        "관계",           # NOTE 관계 열
    ],

    # ── 임직원 ────────────────────────────────────────────────────────
    "note.employee_count": [
        "직원수", "종업원수",
        "임직원수",
    ],
    "note.salary_total": [
        "급여합계", "인건비합계",
    ],
}
