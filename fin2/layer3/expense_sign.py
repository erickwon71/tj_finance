"""R221 — 계층3 손익 비용 컬럼 부호 정규화 (std_financials_v3 = 비용 양수 관례).

국내 손익계산서는 대개 비용을 양수로 인쇄하지만, 비용을 괄호(음수)로 인쇄하는 회사가 늘고
있다(FY cogs 음수: 2022 14개사 → 2025 372개사. 삼양식품 2024 사업보고서 원문
`매출원가 (1,004,797,694,924)`). 계층2(report_lines)는 원문 부호 그대로가 원칙이므로,
std 컬럼의 의미("비용 = 양수, 법인세 환급 = 음수")를 맞추는 일은 계층3 이 한다.

판정은 같은 기간·같은 basis 의 std 값 사이 **항등식**으로만 한다(추측 금지):
    cogs        : gross_profit = revenue ∓ cogs
    sga         : operating_income = gross_profit ∓ sga
    tax_expense : net_income = ebt ∓ tax_expense
`+` 쪽만 성립하면 그 컬럼은 음수 표기 관례로 증명된 것이라 부호를 뒤집는다.
`−` 쪽만 성립하면 양수 관례로 증명된 것이라 그대로 둔다.

cogs·sga·interest_expense 는 **성질상 음수가 될 수 없는 비용**이라, 자기 항등식으로 증명이 안
되더라도 음수면 표기 관례로 보고 뒤집는다. 같은 표 안에서도 관례가 섞인다(실측 00145260 FY2018:
매출원가 양수 · 판관비/금융비용 음수) — "기간 관례"로 추론하면 이자비용(자기 항등식이 없음)을
놓쳐서(시뮬레이션 잔여 11,954행) 이 방식을 택했다. 단, 자기 항등식이 **양수 관례**를 증명하면
(음수값이 그대로 맞는 경우, cogs 142행) 그대로 둔다.
법인세는 환급(음수)이 정상값이라 자기 증명 없이는 건드리지 않는다.
rd_expense 는 주석 소스가 섞여(rules.py 가 이미 abs 처리) 대상이 아니다.

측정(2026-10-05, 정규화 전 std_v3 전체): cogs<0 4,222행 중 음수관례 증명 3,538 · 양수관례 142,
tax 의 음수관례 증명 15,025행(그중 5,992행은 환급이 양수로 적재돼 있던 것 — 부호만 보고
abs 를 하면 안 되는 이유).
"""
from __future__ import annotations

# column -> (total, base, sign) where: total == base + sign * value under the positive convention
_IDENTITIES = {
    "cogs": ("gross_profit", "revenue"),
    "sga": ("operating_income", "gross_profit"),
    "tax_expense": ("net_income", "ebt"),
}
# expense columns that are never negative by nature (a negative value is presentation)
_NONNEG_EXPENSES = ("cogs", "sga", "interest_expense")


def _close(a: int, b: int) -> bool:
    """Exact-won identity with room for the source's own rounding (천원/백만원 tables)."""
    return abs(a - b) <= max(1_000, abs(b) // 100_000)


def _proof(col: dict, c: str) -> str | None:
    """'neg' / 'pos' if the column's identity proves its sign convention, else None."""
    v = col.get(c)
    total_k, base_k = _IDENTITIES[c]
    total, base = col.get(total_k), col.get(base_k)
    if not v or total is None or base is None:
        return None
    neg = _close(total, base + v)       # expense printed negative
    pos = _close(total, base - v)       # expense printed positive
    if neg and not pos:
        return "neg"
    if pos and not neg:
        return "pos"
    return None


def normalize_expense_signs(col: dict) -> list[str]:
    """Flip expense columns of `col` (in place) to the positive-expense convention.

    Returns the flipped column names (empty when nothing changed).
    """
    proofs = {c: _proof(col, c) for c in _IDENTITIES}
    flipped: list[str] = []
    for c in ("cogs", "sga", "interest_expense", "tax_expense"):
        v = col.get(c)
        if not v:
            continue
        p = proofs.get(c)
        if p == "neg":
            flip = True
        elif p == "pos":
            flip = False
        else:
            flip = c in _NONNEG_EXPENSES and v < 0
        if flip:
            col[c] = -v
            flipped.append(c)
    return flipped
