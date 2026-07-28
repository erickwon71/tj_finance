"""계층3 ④라벨 정규화 — 주석 표의 행 라벨 → canonical 계정.

첫 라벨군은 D&A(감가상각비·무형자산상각비). 계층2 는 라벨을 원문 그대로 싣기 때문에
(`label_raw`) 표기 변종을 여기서 흡수한다.

실측 변종 (2026-07-28)
---------------------
감가상각:  `감가상각비` · `감가상각비에 대한 조정` · `감가상각비, 유형자산` ·
           `감가상각비, 사용권자산` · `유형자산감가상각비` · `감가상각`
무형상각:  `무형자산상각비` · `무형자산상각` · `무형자산감가상각비`
결합:      **`감가상각,무형자산상각`** — dep+amort 가 한 줄에 합쳐진 형태(GST 등).
           기존 `note_extractor._DA_ACCOUNT_PATTERNS` 는 이걸 amortization 으로 **오분류**한다.

★ 반드시 배제해야 하는 함정 (전부 실측에서 마주친 것)
-----------------------------------------------------
· `감가상각누계액`  — 유형자산 주석의 **잔액**(BS 항목). 비용이 아니다. 그냥 '감가상각' 을
                      매칭하면 그대로 딸려온다.
· `상각후원가`      — 금융자산 측정기준('상각후원가측정금융자산'). 상각비와 무관.
· `대손상각비`      — 채권 손상차손. D&A 아님.
· `감가상각방법/률/내용연수` — 정책 서술.

사용권자산 처리
--------------
`감가상각비, 사용권자산` 은 유형자산 감가상각과 **별도 행으로 분리**되는 경우가 많아
D&A 합계를 낼 때 **합산**해야 한다. 그래서 별도 버킷(DEPRECIATION_ROU)으로 분류하되
`is_depreciation()` 은 True 를 돌려준다.
"""
from __future__ import annotations

import re
from typing import Optional

# ★이름은 기존 표준화 규칙(fin2/standardize/rules.py 의 _DEP_CANON/_AMORT_CANON/
#   _DA_TOTAL_CANON)이 이미 기대하는 canonical 어휘에 맞춘다. 새 이름을 만들면
#   rule_additive_da 가 못 알아본다.
DEPRECIATION = "note.depreciation"          # 유형자산 등 감가상각비
DEPRECIATION_ROU = "note.rou_depreciation"  # 사용권자산 감가상각비(합산 대상)
AMORTIZATION = "note.amortization"          # 무형자산상각비
DA_COMBINED = "note.da_total"               # 감가상각+무형자산상각 결합 = D&A 합계 그 자체

# 라벨에 이 중 하나라도 있으면 D&A 후보에서 제외한다.
_EXCLUDE = (
    "누계액",        # 감가상각누계액 = 잔액
    "상각후원가",    # 금융자산 측정기준
    "대손상각",      # 채권 손상
    "손상차손",
    "방법",
    "내용연수",
    "상각률",
    "충당금",
)


def _norm(label: str) -> str:
    """비교용 정규형 — 공백 제거, 구분자 통일."""
    s = (label or "")
    s = s.replace("ㆍ", ",").replace("·", ",").replace("／", "/")
    return re.sub(r"\s+", "", s)


def classify_da_label(label: str) -> Optional[str]:
    """행 라벨 → D&A canonical 버킷. D&A 가 아니면 None.

    순서가 중요하다: 결합 표기 → 사용권 → 무형 → 유형.
    """
    s = _norm(label)
    if not s or any(x in s for x in _EXCLUDE):
        return None

    has_dep = "감가상각" in s
    has_amort = ("무형자산상각" in s) or ("무형자산감가상각" in s)
    # ★'감가' 없이 '<자산종류>상각비' 로만 쓰는 기업이 많다(실측: 사용권자산상각비 ·
    #   투자부동산상각비). '감가상각' 만 찾으면 통째로 누락된다 — 원문 대조로 확인한 결함.
    has_amortize = "상각" in s

    # ① 한 줄에 둘 다 — '감가상각,무형자산상각'
    if has_dep and has_amort and "무형자산감가상각" not in s:
        return DA_COMBINED
    # ② 무형자산 상각 (무형자산감가상각비 포함 — 표기만 '감가상각'일 뿐 무형이다)
    if has_amort:
        return AMORTIZATION
    # ③ 사용권자산 — '감가상각비,사용권자산' / '사용권자산상각비' 양쪽 다. 합산 대상.
    if has_amortize and "사용권" in s:
        return DEPRECIATION_ROU
    # ④ 투자부동산 상각 — 유형자산 성격의 감가상각.
    if has_amortize and "투자부동산" in s:
        return DEPRECIATION
    # ⑤ 그 외 감가상각
    if has_dep:
        return DEPRECIATION
    # ⑥ '무형자산상각비' 없이 '무형…상각' 으로 쓰는 소수 표기
    if "무형" in s and has_amortize:
        return AMORTIZATION
    return None


def is_depreciation(bucket: Optional[str]) -> bool:
    """D&A 합계에서 감가상각 쪽으로 합산할 버킷인가(사용권 포함)."""
    return bucket in (DEPRECIATION, DEPRECIATION_ROU)


def is_amortization(bucket: Optional[str]) -> bool:
    return bucket == AMORTIZATION
