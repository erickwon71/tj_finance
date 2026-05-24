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

    # ── 임직원 ────────────────────────────────────────────────────────
    "note.employee_count": [
        "직원수", "종업원수",
        "임직원수",
    ],
    "note.salary_total": [
        "급여합계", "인건비합계",
    ],
}
