"""열별 단위 귀속 — 표가 선언한 단위를 **열 단위로** 배분한다(계층2 F1, 2026-07-31).

왜 필요한가 — 실측된 오염
-------------------------
종전에는 표의 첫 금액 배수를 **표의 전 열**에 적용했다. 그래서 비금액 열이 금액으로 둔갑했다.
DB 실측(`scripts/audit_unit_declarations.py --contamination-only`, 2026-07-30):

    비금액 열 표지인데 value_won 이 채워진 행 : 6,130,738 / 93,059 filing
      이자율(%)   185,770 행  최대 2,228,163,141,000,000 원  ← 이자율 5% 가 2,228조원
      지분율(%)   172,943 행  최대   114,869,004,913,000 원

유실은 '없는 것'이지만 오염은 **틀린 값이 들어 있는 것**이라 계층3 이 그대로 소비하면 산출이
틀어진다. 그래서 단위 판정을 표 단위에서 **열 단위**로 내린다.

무엇을 근거로 판정하는가 — 셀 값을 보지 않는다
----------------------------------------------
근거는 **원문이 적어 둔 두 가지**뿐이다:
  ① 표의 단위 선언 토큰 (`amount_normalizer.detect_unit_tokens`)  예 ['천원', 'USD']
  ② 열 헤더 원문 (`report_lines._build_col_labels`)                예 '당분기말>이자율(%)'

셀 값의 크기·소수점으로 "이건 비율 같다"고 추론하지 **않는다**. 그건 계층2 가 금지한 추측이고,
같은 판정을 원문 없이 재현할 수 없다. 열 헤더가 말해주지 않으면 **확정 못 함(NULL)** 으로 둔다.

미확정을 NULL 로 두는 것이 정보 손실이 아닌 이유
------------------------------------------------
같은 커밋에서 `value_raw`(셀 원문 문자열)를 함께 적재한다. value_won 이 NULL 이어도 원문
숫자는 그대로 남으므로, 계층3 이 나중에 표제·주석 문맥을 보고 해석할 수 있다. 즉 이 모듈의
NULL 은 "값이 없다"가 아니라 **"계층2 가 단위를 확정하지 못했다"**는 정직한 표시다.
"""
from __future__ import annotations

import re

from parser.common.amount_normalizer import _money_multiplier, detect_unit_tokens

# ── 열 헤더 표지 ───────────────────────────────────────────────────────
# 비금액 표지. **여기에 걸리면 어떤 선언이든 value_won 을 채우지 않는다** — 금액단독 선언
# 표 안에 비율 열이 섞인 경우(census §2-2 의 후자 6.13M 행)가 이 규칙으로 잡힌다.
#
# ★ 오염 실측(2026-07-30)에 쓰인 패턴을 **그대로** 접두로 둔다. 감사 도구와 정의가 갈리면
#   "오염 = 0" 을 같은 잣대로 확인할 수 없다(`audit_unit_declarations` 가 이 상수를 import).
CONTAMINATION_MARKERS = r"%|비율|이자율|할인율|지분율|주당|수량|주수|배수|USD|EUR|JPY|외화"

# ★그러나 로더는 '%' 를 그대로 쓰지 않는다 — 원문 대조에서 **거짓양성**이 나왔다:
#   '당반기말>10%상승' (환위험 민감도 표의 시나리오 열)은 **천원 금액** 열인데 '%' 가 있다.
#   즉 오염 실측 6,130,738 행에는 이런 거짓양성이 섞여 있다(그만큼 실제 오염은 더 적다).
#   그래서 '%' 는 **단위 표기로 쓰인 경우만** 비금액으로 본다: '(%)' · 라벨 끝의 '%' · 율/률.
_PCT_AS_UNIT = r"\(\s*%\s*\)|%\s*$|율|률"

# 로더가 추가로 비금액으로 보는 표지(오염 실측 정의는 위 상수로 고정하고, 여기서 넓힌다).
#
# ★ 넓힐 때의 함정 — **기간 표지를 비금액으로 넣으면 안 된다.** 유동성위험 만기분석 표는
#   열이 '6개월이내 / 6-12개월 / 1-2년' 인데 그 칸의 값은 **천원 금액**이다(실측: 성일하이텍
#   34번 주석). 초안에 `개월|년|기간` 을 넣었다가 이 표들의 금액을 전부 NULL 로 만들 참이었다.
#   그래서 여기에는 **그 자체로 비금액인 표지만** 둔다(비율·주식수·외화·수량).
_EXTRA_NON_MONEY = (
    r"주식수|소유주식|보유주식|발행주식|의결권|주식총수"
    r"|일수|적수|CNY|HKD|GBP|CHF|VND|IDR|천주|백만주|인원|건수|톤"
    # ★외화 표기 — 원문 대조에서 잡은 오염: '계약금액($)' 열(USD 1,000,000)에 천원 배수가
    #   적용돼 10억원으로 들어갔다(에쎈테크 20150817000851 18.파생상품). '금액' 이라는 단어가
    #   있어도 통화가 원이 아니면 원 단위 금액이 아니다.
    r"|\$|달러|USD|EUR|JPY|위안|엔화"
)
# '%' 만 위 `_PCT_AS_UNIT` 로 좁히고 나머지 표지는 그대로 쓴다.
NON_MONEY_COL_RE = re.compile(
    _PCT_AS_UNIT + "|" + r"비율|이자율|할인율|지분율|주당|수량|주수|배수|USD|EUR|JPY|외화"
    + "|" + _EXTRA_NON_MONEY)

# 금액 표지 — **혼합 선언에서 양의 근거가 필요할 때만** 쓴다.
#
# ★기간 표지(당기·전기·기초·기말·제N기)는 여기에 넣지 않는다. 그건 "이 열이 언제인가"만
#  말해주고 "금액인가"는 말해주지 않는다 — '(단위: 주, 원)' 주식선택권 표의 기초/기말 열은
#  **주식수**다. 혼합 선언에서 요구하는 것은 시점이 아니라 **금액이라는 명시적 어휘**다.
_MONEY_COL_RE = re.compile(
    r"금액|장부금액|공정가치|취득원가|잔액|평가액|환산액|원화|외화금액"
    r"|매출|수익|비용|원가|손익|이익|손실|배당금|보상원가"
    r"|자산|부채|자본|차입금|사채|대출|보증|충당금|현금|채권|채무|리스"
    r"|\(원\)|\(천원\)|\(백만원\)|\(억원\)"
    # 한글 열 이름이 '…금'·'…액' 으로 끝나면 금액이다(실측: 출자약정금·주식발행초과금·
    # 누적출자금액·미실행잔액). 이 규칙이 없으면 혼합 선언 표에서 이런 열이 전부
    # undetermined 로 비워졌다(F1 초판 표본에서 확인).
    r"|[가-힣]금$|[가-힣]액$"
)

# ── 외화 표시 재무제표 ─────────────────────────────────────────────────
# 국내 기업이 **표시통화를 외화로** 쓰는 경우가 있다(실측 아남전자 008700: 2019 사업연도부터
# 본문 8표 전부 '(단위 : USD)'). 종전에는 'USD' 에 원화 배수가 없어 `NON_MONEY_ONLY` 로
# 분류돼 표 전체가 보류됐다 — 즉 **숫자를 못 읽은 게 아니라 통화를 표현할 방법이 없어서**
# 버린 것이다(2019~2026 정기보고서 30건이 report_lines 0 행).
#
# 사용자 결정 2026-08-05 — 환산하지 않고 **표시통화 금액 그대로** value_won 에 담고,
# 그 사실을 행에서 바로 알 수 있게 `unit_source='fx_declared'` 로 표시한다. 통화 코드는
# 표 단위 사실이므로 `report_tables.currency` 에 적는다(행마다 반복하지 않는다 — F3 원칙).
#
# ⚠ 적용 범위를 **외화 단독 선언으로만** 좁힌다. '1USD, 천원' 처럼 원화와 섞인 선언
#   (주석표 대부분, 실측 137,680표 중 다수)은 **건드리지 않는다** — 그런 표는 원화 열만
#   적재되고 USD 셀은 원문이 'USD 12,000,000' 처럼 통화 접두를 달고 있어 금액 정규식에
#   걸리지 않는다. 이미 올바르게 동작하므로 손대면 오히려 위험하다.
FX_CODES = ("USD", "EUR", "JPY", "CNY", "HKD", "GBP", "CHF", "VND", "IDR", "SGD", "AUD")
# 토큰 형태: 'USD' · '천USD' · '백만USD' · '천/USD'(스케일 접두 또는 슬래시 표기).
_FX_TOKEN_RE = re.compile(
    r"^[(（]?\s*(천|만|백만|억)?\s*[/／]?\s*(" + "|".join(FX_CODES) + r")\s*[)）]?[.,]?$",
    re.I)
_FX_SCALE = {None: 1, "천": 1_000, "만": 10_000, "백만": 1_000_000, "억": 100_000_000}


def fx_token(tok: str) -> tuple[str, int] | None:
    """외화 단위 토큰 → (통화코드, 스케일). 외화가 아니면 None.

    '(단위 : USD)' → ('USD', 1) · '천USD' → ('USD', 1000) · '천/USD' → ('USD', 1000)
    """
    m = _FX_TOKEN_RE.match(tok.strip())
    if not m:
        return None
    return m.group(2).upper(), _FX_SCALE[m.group(1)]


# 선언 분류
MONEY_ONLY = "money_only"
NON_MONEY_ONLY = "non_money"
MIXED = "mixed"
UNDECLARED = "undeclared"
# 외화 **단독** 선언 — 원화 토큰이 없고 외화 토큰만 있는 표(위 설명 참고).
FX_ONLY = "fx_only"

# unit_source 값(DB 에 그대로 들어간다) — 그 행의 value_won 이 어떤 근거로 채워졌는가/왜 비었나.
SRC_DECLARED = "declared"        # 표 선언 배수 적용(금액단독)
SRC_INHERITED = "inherited"      # 앞선 **선언 전용 표**의 단위를 상속(D1) — 표 자신의 선언 아님
SRC_COL_MONEY = "col_money"      # 혼합 선언 + 열 헤더가 금액이라고 말함
SRC_NON_MONEY = "non_monetary"   # 비금액 열/표 — value_won 없음(원문은 value_raw)
SRC_UNDET = "undetermined"       # 단위 확정 못 함 — value_won 없음(원문은 value_raw)
SRC_UNDECLARED = "undeclared"    # 표에 단위 선언 자체가 없음 — value_won 없음
# ★외화 표시 — value_won 에 **표시통화 금액 그대로** 들어간다(원화 환산 아님).
#   통화 코드는 report_tables.currency. 계층3 소비자는 기본적으로 이 행을 걸러야 한다.
SRC_FX = "fx_declared"


def classify_tokens(tokens: list[str]) -> str:
    """선언 토큰 목록 → 분류(MONEY_ONLY / FX_ONLY / NON_MONEY_ONLY / MIXED / UNDECLARED).

    ★ FX_ONLY 는 **원화 토큰이 하나도 없고** 외화 토큰이 있을 때만이다. 원화가 섞이면
      (예 '1USD, 천원') 종전대로 MIXED — 그 표는 열 헤더로 원화 열만 골라 적재한다.
    """
    if not tokens:
        return UNDECLARED
    money = [t for t in tokens if _money_multiplier(t) is not None]
    if money and len(money) == len(tokens):
        return MONEY_ONLY
    if money:
        return MIXED
    if any(fx_token(t) for t in tokens):
        return FX_ONLY
    return NON_MONEY_ONLY


def first_fx(tokens: list[str]) -> tuple[str, int] | None:
    """선언의 첫 외화 토큰 → (통화코드, 스케일). 없으면 None."""
    for t in tokens:
        fx = fx_token(t)
        if fx:
            return fx
    return None


def first_money_multiplier(tokens: list[str]) -> int | None:
    for t in tokens:
        m = _money_multiplier(t)
        if m is not None:
            return m
    return None


# DART 서식은 한글 자간에 공백을 넣는다 — 실측 열 헤더 '금 액' · '지 분 율' · '당 반 기 말'.
# 정규화 없이 매칭하면 '지 분 율' 이 비금액 표지에 걸리지 않아 **오염이 그대로 통과**한다
# (원문 대조에서 실제로 잡혔다: 에쎈테크 20150817000851 주주현황 표).
_HANGUL_GAP_RE = re.compile(r"(?<=[가-힣])\s+(?=[가-힣])")


def normalize_col_label(col_label: str | None) -> str:
    """열 헤더를 표지 매칭용으로 정규화 — 한글 자간 공백만 제거(원문은 보존, 판단 아님)."""
    if not col_label:
        return ""
    return _HANGUL_GAP_RE.sub("", col_label)


def label_segments(col_label: str | None) -> list[str]:
    """다단 헤더('당기말>지분율(%)')를 단별로 쪼갠다. **단위 선언 단은 버린다.**

    ★ 왜 버리는가: `_build_col_labels` 는 헤더 행을 위→아래로 이어 붙이므로 표의 단위 선언
      줄이 열 라벨의 접두가 되는 일이 흔하다 — '(원화단위: 백만원, 외화단위: 백만단위)>당기
      출자약정금'. 여기서 '외화' 는 **열의 성격이 아니라 표의 선언**이라, 그대로 매칭하면
      원화 금액 열이 외화로 오판돼 value_won 이 비었다(F1 초판 표본 실측 71 행).
    """
    s = normalize_col_label(col_label)
    if not s:
        return []
    return [seg for seg in s.split(">") if seg and "단위" not in seg]


def column_is_non_money(col_label: str | None) -> bool:
    """열 헤더 원문이 **비금액이라고 말하는가**. 헤더가 없으면 말해주는 것이 없다 → False.

    어느 단에서든 비금액 표지가 나오면 비금액으로 본다 — '전기말>지분율(%)' 처럼 상위 단이
    기간이고 하위 단이 비율인 경우를 잡아야 한다.
    """
    return any(NON_MONEY_COL_RE.search(seg) for seg in label_segments(col_label))


def column_is_money(col_label: str | None) -> bool:
    return any(_MONEY_COL_RE.search(seg) for seg in label_segments(col_label))


class ColumnUnits:
    """표 하나의 열별 단위 계획. `multiplier(col_idx)` 가 None 이면 value_won 을 비운다.

    사용 측 계약:
        cu = ColumnUnits.from_declaration(decl_text, col_labels)
        if not cu.table_loadable: return            # 데이터행 없는 표 등은 호출측 판단
        mult = cu.multiplier(col_idx)
        value_won = parse_amount(raw, mult) if mult is not None else None
        unit_source = cu.source(col_idx)
    """

    def __init__(self, tokens: list[str], col_labels: dict[int, str] | None,
                 inherited: bool = False):
        self.tokens = tokens
        self.raw_decl: str | None = None
        self.col_labels = col_labels or {}
        self.kind = classify_tokens(tokens)
        self.money_mult = first_money_multiplier(tokens)
        # 외화 단독 선언이면 (통화코드, 스케일). 그 외에는 None — 혼합 선언은 여기 안 온다.
        fx = first_fx(tokens) if self.kind == FX_ONLY else None
        self.currency: str | None = fx[0] if fx else None
        self.fx_mult: int | None = fx[1] if fx else None
        # 표 자신의 선언이 아니라 **앞선 선언 전용 표**에서 받아온 것인가(D1).
        # 값 판정 규칙은 같고, `unit_source` 만 'inherited' 로 표시해 계층3 이 구분하게 한다.
        self.inherited = inherited

    @classmethod
    def from_declaration(cls, decl_text: str | None,
                         col_labels: dict[int, str] | None = None,
                         inherited: bool = False) -> "ColumnUnits":
        tokens = detect_unit_tokens(decl_text) if decl_text else []
        obj = cls(tokens, col_labels, inherited=inherited)
        obj.raw_decl = (decl_text or "").strip()[:120] or None
        return obj

    @classmethod
    def from_tokens(cls, tokens: list[str],
                    col_labels: dict[int, str] | None = None) -> "ColumnUnits":
        return cls(tokens, col_labels)

    # ── 판정 ────────────────────────────────────────────────────────────
    def multiplier(self, col_idx: int) -> int | None:
        """그 열의 금액 배수. None = 금액 열이 아니거나 단위를 확정하지 못했다.

        ★ FX_ONLY 표에서 이 배수는 **표시통화 스케일**이다(USD=1, 천USD=1000). 원화 환산이
          아니므로 곱한 결과도 USD 금액이다 — 그 사실은 `source()` 가 'fx_declared' 로 알린다.
        """
        label = self.col_labels.get(col_idx)
        if self.kind in (NON_MONEY_ONLY, UNDECLARED):
            return None
        if column_is_non_money(label):
            return None                      # ★오염 차단 — 선언이 금액단독이어도 여기서 막는다
        if self.kind == FX_ONLY:
            return self.fx_mult
        if self.kind == MONEY_ONLY:
            return self.money_mult
        # 혼합 — 양의 근거(열 헤더가 금액)를 요구한다. 헤더가 침묵하면 확정 불가.
        return self.money_mult if column_is_money(label) else None

    def source(self, col_idx: int) -> str:
        label = self.col_labels.get(col_idx)
        if self.kind == UNDECLARED:
            return SRC_UNDECLARED
        if self.kind == NON_MONEY_ONLY:
            return SRC_NON_MONEY
        if column_is_non_money(label):
            return SRC_NON_MONEY
        if self.kind == FX_ONLY:
            return SRC_FX
        if self.kind == MONEY_ONLY:
            return SRC_INHERITED if self.inherited else SRC_DECLARED
        if not column_is_money(label):
            return SRC_UNDET
        return SRC_INHERITED if self.inherited else SRC_COL_MONEY

    @property
    def has_money_column(self) -> bool:
        """열 계획에 금액 열이 하나라도 있는가(열 헤더가 없으면 금액단독 선언 기준으로 판단)."""
        if self.kind in (MONEY_ONLY, FX_ONLY):
            return True
        if self.kind == MIXED:
            return any(self.multiplier(i) is not None for i in self.col_labels)
        return False
