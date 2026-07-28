"""계층3 ②주제 정규화 — 주석 제목 → canonical topic.

역할
----
계층2 `note_lines.section_path` 는 원문 주석 제목('30. 비용의 성격별 분류 (연결)')이다.
계층3 의 주석 파생 항목(D&A·R&D·리스·부문…)은 "어느 주석을 볼 것인가"를 **이 모듈의
canonical topic 으로 지목**한다. 항목별로 제목 문자열을 하드코딩하면 항목 수만큼
전용 추출기가 생기므로(흡수 대상인 파편 추출기의 재생산) 여기 한 곳에 모은다.

근거
----
실측(2026-07-28, FY2024 · corp 289사 주석 보유):
  · 원문 제목 인스턴스 15,591 → 번호/기준표기/띄어쓰기 정규화 후 고유 2,239
  · 같은 주석이 번호만 달라 수십 종으로 갈린다(판매비와관리비 65종, 현금흐름표 43종)
  · 띄어쓰기 변종 실재: `판매비와관리비`(30.0%) vs `판매비와 관리비`(13.3%)
  · 접속사 변종 실재: `기타수익및기타비용`(37.0%) vs `기타수익과기타비용`(22.8%)
                      `금융수익및금융비용`(37.0%) vs `금융수익과금융비용`(22.1%)
  · 동의 제목 실재:   `주당이익`(31.8%) vs `주당손익`(23.2%)
                      `법인세비용`(54.3%) vs `법인세`(17.6%)
  · 롱테일 2,239 중 1,707 은 1개 corp 에만 등장 → 전수 카탈로그화는 무의미.
    **계층3 가 실제로 쓰는 topic 만** 다루고 나머지는 None(미분류)로 둔다.

설계 원칙
--------
· 정규화는 되돌릴 수 있는 것만(번호·기준표기·공백·구분자). 의미를 바꾸지 않는다.
· 매칭은 **정규화된 문자열에 대한 부분일치**. 회사마다 수식어가 붙기 때문
  ('유형자산및투자부동산', '리스(사용권자산)').
· 더 구체적인 topic 을 먼저 검사한다(사용권자산 → LEASE 가 유형자산보다 앞).
"""
from __future__ import annotations

import re
from typing import Optional

# ── canonical topics ────────────────────────────────────────────────────────
EXPENSE_BY_NATURE = "note.expense_by_nature"   # 비용의 성격별 분류
CASH_FLOW = "note.cash_flow"                   # 현금흐름표 / 영업으로부터 창출된 현금
PPE = "note.ppe"                               # 유형자산
INTANGIBLES = "note.intangibles"               # 무형자산
INVESTMENT_PROPERTY = "note.investment_property"
LEASE = "note.lease"                           # 리스 / 사용권자산
SGA = "note.sga"                               # 판매비와관리비
SEGMENT = "note.segment"                       # 영업부문 / 부문정보
INCOME_TAX = "note.income_tax"
EMPLOYEE_BENEFITS = "note.employee_benefits"
BORROWINGS = "note.borrowings"
REVENUE = "note.revenue"                       # 고객과의 계약에서 생기는 수익
INVENTORY = "note.inventory"
EPS = "note.eps"
# ⚠ RND 는 topic 으로는 거의 잡히지 않는다(실측 corp 커버리지 0.7% = 2사).
#   연구개발비는 **독립 주석이 아니라** 판관비/비용의성격별 분류 표 **안의 라벨**이기 때문.
#   즉 R&D 는 ②주제가 아니라 ④라벨 단계에서 다뤄야 한다. topic 은 폴백으로만 남겨둔다.
RND = "note.rnd"

# 문서 수준 일반 제목 — 개별 주석이 아니다(실측 잔여 4.9%: 첫 헤딩 이전 표).
GENERIC = "note.__generic__"

_NUM_PREFIX = re.compile(r"^\s*\d{1,2}\s*[.．]\s*")
_BASIS_TAIL = re.compile(r"(\s*[-–]\s*(연결|별도)\s*$)|([(（]\s*(연결|별도)\s*[)）]\s*$)")
_PAREN_TAIL = re.compile(r"\s*[(（][^)）]{0,20}[)）]\s*$")
_GENERIC_RE = re.compile(r"^(연결)?재무제표(에대한)?주석$")


def normalize_title(section_path: Optional[str]) -> str:
    """주석 제목 → 비교용 정규형(번호·기준표기·공백·구분자 제거).

    의미를 바꾸지 않는 변환만 한다. '판매비와 관리비' → '판매비와관리비'.
    """
    s = (section_path or "").strip()
    s = _NUM_PREFIX.sub("", s)
    s = _BASIS_TAIL.sub("", s)
    s = _PAREN_TAIL.sub("", s)
    s = s.replace("ㆍ", ",").replace("·", ",").replace("，", ",")
    # ★ '및'/'과' 를 구분자로 치환하지 않는다. '과' 는 단어 내부 음절로 흔해서
    #   ('성과급'→'성,급', '과세'→',세') 전역 치환하면 제목이 망가진다.
    #   접속사 변종(기타수익'및'기타비용 / 기타수익'과'기타비용)은 규칙 쪽에서
    #   접속사를 걸치지 않는 단일 개념 키워드로 매칭해 흡수한다.
    s = re.sub(r"\s+", "", s)
    return s.strip(" .,-—")


# (topic, 부분일치 키워드들, 제외 키워드들) — 구체적인 것이 먼저.
_TOPIC_RULES: list[tuple[str, list[str], list[str]]] = [
    (LEASE,               ["사용권자산"],           []),
    (LEASE,               ["리스"],                 ["리스크"]),
    (EXPENSE_BY_NATURE,   ["성격별"],               []),
    (CASH_FLOW,           ["현금흐름"],             []),
    (CASH_FLOW,           ["창출된현금"],           []),   # '영업으로부터 창출된 현금'
    (SGA,                 ["판매비"],               []),
    (RND,                 ["연구개발"],             []),
    (SEGMENT,             ["부문"],                 []),
    (INVESTMENT_PROPERTY, ["투자부동산"],           []),
    (INTANGIBLES,         ["무형자산"],             []),
    (PPE,                 ["유형자산"],             []),
    (EMPLOYEE_BENEFITS,   ["종업원급여"],           []),
    (EMPLOYEE_BENEFITS,   ["퇴직급여"],             []),
    (EMPLOYEE_BENEFITS,   ["확정급여"],             []),
    (INCOME_TAX,          ["법인세"],               []),
    (BORROWINGS,          ["차입금"],               []),
    (BORROWINGS,          ["사채"],                 ["사채권"]),
    (REVENUE,             ["고객과의계약"],         []),
    (REVENUE,             ["수익인식"],             []),
    (INVENTORY,           ["재고자산"],             []),
    (EPS,                 ["주당이익"],             []),
    (EPS,                 ["주당손익"],             []),
    (EPS,                 ["주당순이익"],           []),
]


def map_topic(section_path: Optional[str]) -> Optional[str]:
    """주석 제목 → canonical topic. 해당 없으면 None(미분류).

    GENERIC 은 '연결재무제표 주석' 같은 문서 수준 제목 — 개별 주석이 아님을 뜻하며,
    계층3 는 이걸 소스로 삼으면 안 된다(어느 주석인지 모른다는 의미이므로).
    """
    norm = normalize_title(section_path)
    if not norm:
        return None
    if _GENERIC_RE.match(norm):
        return GENERIC
    for topic, incl, excl in _TOPIC_RULES:
        if all(k in norm for k in incl) and not any(k in norm for k in excl):
            return topic
    return None


# 계층3 D&A 가 볼 주석의 우선순위(2026-07-28 실측 커버리지 근거).
# 단일 1차 소스는 존재하지 않는다 — 비용의성격별 66.1% · 유형자산 86.2% 등으로 분산.
DA_SOURCE_PRIORITY: list[str] = [
    EXPENSE_BY_NATURE,   # dep/amort 가 한 표에 나란히 — 가장 해석이 쉽다
    CASH_FLOW,           # 조정항목의 감가상각비/무형자산상각비
    SGA,                 # 판관비 내역의 감가상각비
    PPE,                 # 유형자산 증감표의 감가상각 행
    INTANGIBLES,
    INVESTMENT_PROPERTY,
    LEASE,
]
