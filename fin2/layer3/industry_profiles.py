"""Industry revenue profiles (L3-4 step2 / P1).

Some industries file a K-IFRS income statement whose structure differs from a general
company's single `매출액` line, so a faithful standardized `revenue` must be COMPOSED
from named subtotal lines rather than read from one cell. This is the general mechanism;
add a `RevenueProfile` per industry whose standard diverges.

Currently implemented:
  insurance — IFRS17 (2023+) splits the IS into 보험손익 / 투자손익 sections with no grand
              영업수익 total. revenue = 보험(영업|서비스)수익 + 투자(영업|서비스)수익.
              (operating_income is unaffected — insurers still file `영업이익` directly,
               which equals 보험손익/서비스결과 + 투자손익, and Layer 3 already reads it.)

Label families (verified 2026-07-24):
  생보(life)    : 보험서비스수익 / 투자서비스수익
  손보(non-life): 보험영업수익   / 투자영업수익

Profiles scan the RAW merged col0 IS lines (not the account-mapper output), so a profile
owns its own label vocabulary and does not perturb general is.revenue mapping. Child
lines (일반보험서비스수익 등) are excluded by exact normalized-label matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# strip leading numbering (Ⅰ. / 1. / (1) …) and spaces, drop trailing 주석 refs
_NUM_PREFIX = re.compile(r"^[\sⅠ-Ⅹⅰ-ⅹIVXivx0-9\.\(\)]+")


def norm(label: str | None) -> str:
    if not label:
        return ""
    s = _NUM_PREFIX.sub("", label)
    return re.sub(r"\s+", "", s).split("(")[0]


@dataclass(frozen=True)
class RevenueProfile:
    """An industry whose standardized revenue = Σ named subtotal lines.

    components: ordered tuple of (output_key, frozenset[accepted normalized labels]).
    The FIRST component is the signature — the profile applies only if it is present,
    so it self-gates to that industry's IS structure.
    """
    name: str
    components: tuple
    # KSIC(induty_code) prefixes this profile's industry standard applies to. Scopes the
    # profile to PRIMARY-business corps (e.g. insurers=65), so a bank/holding (64) that
    # merely consolidates an insurance subsidiary's 보험영업수익 is NOT mis-composed.
    induty_prefixes: tuple = ()
    # grand-total labels (e.g. pre-IFRS17 '영업수익') that, when present as a real
    # non-zero line, are authoritative — DIRECT_MAP already uses them, so DON'T compose.
    # Only when no such total exists (IFRS17 split IS) do we sum the subtotals.
    total_labels: frozenset = frozenset()

    def applies_to(self, induty: str | None) -> bool:
        return bool(induty) and induty.startswith(self.induty_prefixes)

    def compose(self, is_lines: list[dict]) -> tuple[int, dict] | None:
        """is_lines = merged col0 IS cells of ONE basis. Returns (revenue, components)
        if the signature subtotal is present AND no authoritative grand total exists;
        else None (not this industry / defer to the filed total)."""
        # defer to a real grand total when present (pre-IFRS17). A 0-valued total is an
        # IFRS17 empty header → not authoritative, keep composing.
        if any(norm(c["label_raw"]) in self.total_labels and c["value_won"]
               for c in is_lines):
            return None
        found: dict[str, int] = {}
        for key, labels in self.components:
            vals = [c["value_won"] for c in is_lines
                    if norm(c["label_raw"]) in labels and c["value_won"] is not None]
            if vals:
                found[key] = max(vals, key=abs)  # the subtotal (children excluded by exact norm)
        if self.components[0][0] not in found:
            return None
        return sum(found.values()), found


# ── registry: extend per industry that diverges from the general 매출액 standard ──
INSURANCE = RevenueProfile(
    name="insurance",
    components=(
        ("insurance_revenue", frozenset({"보험영업수익", "보험서비스수익"})),
        ("investment_revenue", frozenset({"투자영업수익", "투자서비스수익"})),
    ),
    induty_prefixes=("65",),               # KSIC 65 = 보험 및 연금업 (primary insurers)
    total_labels=frozenset({"영업수익"}),  # pre-IFRS17 grand total → defer to it
)

BANK = RevenueProfile(
    name="bank",
    components=(
        ("interest_revenue", frozenset({"이자수익"})),      # signature (gross)
        ("fee_revenue", frozenset({"수수료수익"})),
        ("other_op_revenue", frozenset({"기타영업수익"})),
    ),
    induty_prefixes=("64121",),            # KSIC 64121 = 일반은행 (pure banks). Bank/financial
                                           # HOLDINGS(64992, mixed segments) & 인터넷은행 추출갭은
                                           # 별도 tail (docs/plans/insurer_revenue_composition_*).
    total_labels=frozenset({"영업수익"}),  # if a bank ever reports 영업수익 total → defer
)

REVENUE_PROFILES: tuple[RevenueProfile, ...] = (INSURANCE, BANK)


def apply_revenue_profile(is_lines: list[dict],
                          induty: str | None) -> tuple[str, int, dict] | None:
    """Try each industry profile (scoped by induty_code) on one basis's merged IS lines.
    Returns (profile_name, revenue, {component_key: value}) or None (general company)."""
    for prof in REVENUE_PROFILES:
        if not prof.applies_to(induty):
            continue
        r = prof.compose(is_lines)
        if r is not None:
            revenue, components = r
            return prof.name, revenue, components
    return None
