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

# strip leading numbering (Ⅰ. / 1. / (1) / I．…) — half AND full-width dots·digits·parens.
# 교보 등은 전각 마침표 '．'(U+FF0E)·전각괄호 '（）' 를 쓴다.
_NUM_PREFIX = re.compile(r"^[\sⅠ-Ⅹⅰ-ⅹIVXivx0-9０-９\.．\(\)（）]+")
# trailing 주석 refs. 정상형 '(주27)' 는 '(' 로 잘리지만, 추출이 괄호를 잃어 '순수수료손익 27,41,44>'
# 처럼 남는 케이스(NH 등)를 위해 끝의 [숫자/콤마/공백] + 선택적 '>' 도 제거한다.
_NOTE_SUFFIX = re.compile(r"[\s\d,]+>?$")


def norm(label: str | None) -> str:
    if not label:
        return ""
    s = _NUM_PREFIX.sub("", label)
    s = re.sub(r"\s+", "", s).split("(")[0].split("（")[0]
    return _NOTE_SUFFIX.sub("", s)


def _max_abs(is_lines: list[dict], labels: frozenset):
    """max-abs value among is_lines whose normalized label ∈ labels (signed). None if none."""
    vals = [c["value_won"] for c in is_lines
            if norm(c["label_raw"]) in labels and c["value_won"] is not None]
    return max(vals, key=abs) if vals else None


# 영업이익 / 판매관리비 라벨(순영업수익 공식용). norm 이 '(손실)'·번호·공백을 제거하므로
# '영업이익(손실)'→'영업이익', '판매 및 일반관리비'→'판매및일반관리비' 로 수렴한다.
_OP_INCOME_LABELS = frozenset({"영업이익", "영업손익", "영업이익손실"})
_OP_REVENUE_TOTAL = frozenset({"영업수익"})   # net 공식 실패 시 gross 폴백용 총계
_SGA_LABELS = frozenset({
    "판매관리비", "판매비와관리비", "판매비및관리비", "판매및일반관리비",
    "판매및관리비", "판매관리비용", "판관비",
    "판매와관리비",   # DART 원문 오타 변형('비' 누락, NH 2024 등)
})


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
    # data-driven signature: the profile applies only if AT LEAST ONE of these labels is
    # present in the IS. Distinguishes an industry structure WITHIN a shared induty (bank
    # HOLDINGS share KSIC 64992 with general holdings; 순이자손익 marks the bank ones).
    # Empty = no signature gate (induty alone).
    signature_labels: frozenset = frozenset()
    # CLAIM the filed grand total as revenue instead of deferring to the general mapper.
    # Securities: the general DIRECT_MAP mis-picks a component (수수료수익) for some firms
    # (유안타/유진/LS) whose 영업수익 label variant it does not recognize, so the profile
    # owns the total. Insurers/banks leave this False (their filed total is mapped fine).
    claim_total: bool = False
    # 순영업수익(NET) 공식: revenue = 영업이익 + 판매관리비. 증권처럼 gross '영업수익'(트레이딩
    # 총액 포함)과 net 표기가 회사·연도별로 섞여 시계열·회사간 비교가 깨지는 업종에 쓴다.
    # 항등식: 영업비용 = 직접원가(수수료·이자비용, 트레이딩손실 등) + 판관비 이므로
    #   순영업수익 = 영업수익 − 직접원가 = 영업이익 + 판관비 (gross/net 표기 무관 성립).
    net_op_formula: bool = False

    def applies_to(self, induty: str | None) -> bool:
        return bool(induty) and induty.startswith(self.induty_prefixes)

    def compose(self, is_lines: list[dict]) -> tuple[int, dict] | None:
        """is_lines = merged col0 IS cells of ONE basis. Returns (revenue, components)
        or None (not this industry / defer to the filed total)."""
        # 순영업수익 공식(증권): 영업이익 + 판매관리비. gross '영업수익' 총계·트레이딩 총액에
        # 흔들리지 않아 표기전환 회사(NH 등)의 시계열 절벽을 제거한다.
        if self.net_op_formula:
            op = _max_abs(is_lines, _OP_INCOME_LABELS)     # 영업이익 (부호 유지 — 손실 가능)
            sga = _max_abs(is_lines, _SGA_LABELS)          # 판매관리비 (클린 — 영업비용 아님)
            if op is not None and sga is not None:
                return op + abs(sga), {"operating_income": op, "sga": abs(sga)}
            # 판관비 총계가 없는 회사(대신/한화 — SG&A 항목화 + 부동산 겸영)는 순영업수익을
            # 신뢰 추출 불가 → 공시 영업수익 총계로 폴백하되 gross_fallback 로 표시(basis 불일치
            # 가시화, 사용자 결정 2026-07-24). 총계도 없으면 None(일반매퍼).
            totals = [c["value_won"] for c in is_lines
                      if norm(c["label_raw"]) in _OP_REVENUE_TOTAL and c["value_won"]]
            if totals:
                t = max(totals, key=abs)
                return t, {"op_revenue_total": t, "revenue_basis": "gross_fallback"}
            return None
        # filed grand total: with claim_total, the total IS the revenue (as-filed gross);
        # otherwise defer (insurers/banks — the general mapper already uses it). A 0-valued
        # total is an IFRS17 empty header → not authoritative, keep going.
        totals = [c["value_won"] for c in is_lines
                  if norm(c["label_raw"]) in self.total_labels and c["value_won"]]
        if totals:
            if self.claim_total:
                t = max(totals, key=abs)
                return t, {"op_revenue_total": t}
            return None
        # no filed total (net-basis presentation) → compose from named subtotals.
        # signature gate: within a shared induty, require the industry's marker line.
        if self.signature_labels and not any(
                norm(c["label_raw"]) in self.signature_labels for c in is_lines):
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
        ("interest_revenue", frozenset({"이자수익"})),       # gross
        ("fee_revenue", frozenset({"수수료수익"})),
        ("insurance_revenue", frozenset({"보험수익", "보험영업수익", "보험서비스수익"})),  # 지주 보험 세그먼트
        ("other_op_revenue", frozenset({"기타영업수익"})),
    ),
    # 순수 은행(64121) + 은행/금융 지주(64992, 일반지주와 혼재). signature_labels 로 일반지주 제외.
    induty_prefixes=("64121", "64992"),
    # ★signature: 순이자손익/순이자이익 = 은행 IS 구조 표지. 일반지주(롯데지주 등)엔 없어 배제.
    signature_labels=frozenset({"순이자손익", "순이자이익"}),
    total_labels=frozenset({"영업수익"}),  # 영업수익 총계 있으면 그것 우선(Tier-1과 동)
)

# 증권(KSIC 66121). 표준 = 순영업수익(NET) = 영업이익 + 판매관리비 (사용자 결정 2026-07-24).
# 이유: 증권사는 gross '영업수익'(트레이딩 총액 포함)과 net 표기가 회사·연도별로 섞여, gross-as-filed
# 는 표기전환 회사(NH 2019 11.5조→2022 net 2.2조)에서 가짜 시계열 절벽을 만든다. 순영업수익 공식은
# 영업이익·판관비(전 회사 공시)만 쓰므로 표기 무관하게 시계열·회사간 일관된다.
SECURITIES = RevenueProfile(
    name="securities",
    components=(),                         # net_op_formula 사용 — 성분합산 안 함
    induty_prefixes=("66121",),            # KSIC 66121 = 증권 중개
    net_op_formula=True,
)

# 여신전문·저축은행(KSIC 64913 카드·64911 캐피탈/할부·64132 저축은행). 은행형 gross 표준
# (사용자 결정 2026-07-24): 영업수익 총계 있으면 그것, 없으면 이자수익+수수료수익+기타영업수익.
# 여신전문사는 은행처럼 이자·수수료가 본업 매출인데, 총계 미공시 시 일반매퍼가 수수료수익 성분만
# 오선택 → 대폭 과소(삼성카드 1.81조=수수료만·이자 2.03조 누락 / 한국캐피탈 0.04조 vs 이자 0.47조 /
# 푸른저축 0.0019조 vs 이자 0.08조). 은행 프로파일과 동일 패턴(총계 우선·없으면 gross 합산).
CREDIT_FINANCE = RevenueProfile(
    name="credit_finance",
    components=(
        ("interest_revenue", frozenset({"이자수익"})),        # gross, 신호(여신업 항상 존재)
        ("fee_revenue", frozenset({"수수료수익"})),
        ("other_op_revenue", frozenset({"기타영업수익"})),
    ),
    induty_prefixes=("64913", "64911", "64132"),
    total_labels=frozenset({"영업수익"}),  # 총계 있으면 그것 우선(메이슨캐피탈 등)
)

REVENUE_PROFILES: tuple[RevenueProfile, ...] = (INSURANCE, BANK, SECURITIES, CREDIT_FINANCE)

# corp 단위 induty 오버라이드: KSIC 오분류로 업종 프로파일이 빗나가는 개별사(curated).
# 다올투자증권은 실질 증권사인데 661(금융지원서비스)로 코딩돼 66121 증권 프로파일이 적용 안 됨
# → 증권 표준(순영업수익) 강제 적용(사용자 결정 2026-07-24). 661 의 결제/핀테크사(NHN KCP·헥토
# ·카카오페이 등)는 실제 비증권이므로 오버라이드 대상 아님.
CORP_INDUTY_OVERRIDE: dict = {
    "00156859": "66121",   # 다올투자증권 (661 오분류 → 증권 표준)
}

# ★증권성 금융지주(매출액/영업수익 총계 없음 → revenue 는 사실상 없음, 사용자 결정 2026-07-24).
# 영업이익~당기순이익 은 정확 적재되므로 revenue 만 NULL 로 둔다(억지 gross 합산·성분 오선택 방지).
# 은행지주(신한/KB/하나/우리/BNK/iM/JB)와 IS 마커가 동일해 자동구분 불가 → curated 세트.
# 확장: 순수 증권지주/투자지주(64992)가 추가되면 여기에 corp_code 를 넣는다.
NO_REVENUE_CORPS: frozenset = frozenset({
    "00432102",   # 한국금융지주 (한국투자금융지주 — 증권 주력, 매출액 개념 없음)
})


def apply_revenue_profile(is_lines: list[dict],
                          induty: str | None,
                          corp: str | None = None) -> tuple[str, int, dict] | None:
    """Try each industry profile (scoped by induty_code) on one basis's merged IS lines.
    Returns (profile_name, revenue, {component_key: value}) or None (general company).
    A curated CORP_INDUTY_OVERRIDE remaps mis-coded corps (e.g. 다올투자증권 661→66121)."""
    if corp is not None and corp in CORP_INDUTY_OVERRIDE:
        induty = CORP_INDUTY_OVERRIDE[corp]
    for prof in REVENUE_PROFILES:
        if not prof.applies_to(induty):
            continue
        r = prof.compose(is_lines)
        if r is not None:
            revenue, components = r
            return prof.name, revenue, components
    return None
