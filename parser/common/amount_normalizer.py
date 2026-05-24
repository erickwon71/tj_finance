"""
금액 문자열 → int 정규화 + 단위(원/천원/백만원 등) 탐지

사용 예:
    parse_amount("132,020,219,269")      → 132020219269
    parse_amount("(53,508,694,647)")     → -53508694647  (괄호=음수)
    parse_amount("5,123", multiplier=1000) → 5123000    (천원 단위)
    parse_amount("-")                    → None
    parse_amount("　")                   → None          (전각공백)
"""
import re
from typing import Optional

# ── 단위 키워드 → 배수 ───────────────────────────────────────────────
UNIT_MULTIPLIERS: dict[str, int] = {
    "억원":   100_000_000,
    "백만원": 1_000_000,
    "만원":   10_000,
    "천원":   1_000,
    "원":     1,
}

# 공란으로 취급할 문자열
_BLANK_PATTERNS = frozenset(["", "-", "─", "—", "―", "　", " ", "·", ".", "...", "N/A", "n/a"])


def detect_unit_multiplier(section_text: str) -> int:
    """
    테이블 상단 텍스트에서 단위를 탐지해 배수(multiplier)를 반환한다.

    예) "(단위 : 천원)"  → 1_000
        "(단위: 백만원)" → 1_000_000
        "(단위 : 원)"    → 1
        탐지 실패        → 1  (원 단위로 간주)
    """
    # 전각/반각 콜론, 공백 통일
    normalized = section_text.replace('：', ':').replace('　', ' ')
    for keyword, multiplier in UNIT_MULTIPLIERS.items():
        if keyword in normalized:
            return multiplier
    return 1


def parse_amount(cell_text: str, multiplier: int = 1) -> Optional[int]:
    """
    셀 텍스트를 원(KRW) 단위 정수로 변환한다.

    Args:
        cell_text:  DART XML/PDF에서 추출한 셀 원문
        multiplier: 단위 배수 (detect_unit_multiplier() 결과)

    Returns:
        int  : 정규화된 원 단위 금액
        None : 공란 / 파싱 불가
    """
    if cell_text is None:
        return None

    s = (cell_text
         .strip()
         .replace(',', '')          # 천 단위 구분자 제거
         .replace(' ', '')          # 반각공백
         .replace('　', '')         # 전각공백
         .replace('​', '')     # zero-width space
         .replace('\xa0', ''))      # non-breaking space

    # 공란 체크
    if not s or s in _BLANK_PATTERNS:
        return None

    # 괄호 음수 표기: (1,234) → -1234
    negative = s.startswith('(') and s.endswith(')')
    if negative:
        s = s[1:-1]

    # 앞에 붙은 음수 부호
    if s.startswith('-') or s.startswith('△') or s.startswith('▲'):
        negative = True
        s = s.lstrip('-△▲')

    # 다시 공란 체크
    if not s or s in _BLANK_PATTERNS:
        return None

    # PostgreSQL BIGINT 한도: ±9,223,372,036,854,775,807 ≈ 9.2 × 10^18
    # 한국 최대 기업(삼성전자) 총자산 ≈ 5 × 10^14 원 → BIGINT 범위 내
    # 이상값(개발노이즈, 인코딩 오류)은 잘라냄
    _BIGINT_MAX = 9_000_000_000_000_000_000  # 9 × 10^18 (safe margin)

    try:
        # 소수점 허용 (예: "1.5억원" 아닌 표 데이터상 "1.0" 등)
        val = int(float(s))
        val *= multiplier
        if abs(val) > _BIGINT_MAX:
            return None   # 비정상 값 (인코딩 오류, 잘못된 셀 등) 무시
        return -val if negative else val
    except (ValueError, OverflowError):
        return None


def normalize_account_name(raw: str) -> str:
    """
    계정과목명 전처리: 퍼지매핑·표준화 전 항상 적용.

    제거 대상:
      - 전각공백(　) → 반각공백
      - 로마숫자 접두어: Ⅰ., Ⅱ., ⅰ., ①, ② 등
      - 주석 참조: (주14), (주5,6), (Note 1) 등
      - 반복 공백 정리
    """
    if not raw:
        return ""

    s = raw.strip()

    # 전각공백 → 반각
    s = s.replace('　', ' ')

    # 대괄호 제거: [유동자산] → 유동자산
    s = re.sub(r'[\[\]]', '', s)

    # 글머리 기호 제거: ㆍ현금 → 현금, •매출 → 매출, ·자본 → 자본
    s = re.sub(r'^[ㆍ•·→▶◆■□●○△▷]\s*', '', s)

    # 아랍숫자 접두어 (연번+점): 1. 2. 3. → 제거 (위쪽 처리와 중복이지만 안전망)
    # (더 이른 단계에서 처리하므로 여기서는 생략)

    # 로마숫자 접두어 제거 (유니코드: Ⅰ~Ⅹ, ⅰ~ⅹ)
    s = re.sub(r'^[Ⅰ-Ⅹⅰ-ⅹ]+\.?\s*', '', s)
    # 로마숫자 접두어 제거 (ASCII: I, II, III, IV ... XV, XVI 등)
    s = re.sub(r'^M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\.?\s*', '', s)
    # 원숫자 접두어 제거 (①~⑳)
    s = re.sub(r'^[①-⑳]+\.?\s*', '', s)
    # 숫자+점 접두어 제거 (1. 2. 가. 나. 등)
    s = re.sub(r'^[\d가-힣]+\.\s*', '', s)
    # 괄호 숫자 접두어 제거: (1), (2), (3) — 주석 번호가 앞에 붙는 경우
    s = re.sub(r'^\(\d+\)\s*', '', s)
    # 알파벳 괄호 접두어 제거: (A), (B) 등
    s = re.sub(r'^\([A-Za-z]\)\s*', '', s)

    # 주석 참조 제거: (주14,28), (주5), (Note 1) 등
    s = re.sub(r'\(주\s*\d[\d,\s]*\)', '', s)
    s = re.sub(r'\(Note\s*\d+\)', '', s, flags=re.IGNORECASE)
    # 주석 참조 — 후방 제거: "계정과목 (주5)" 형태
    s = re.sub(r'\s*\(주\s*\d[\d,\s]*\)\s*$', '', s)

    # 영문 약어 괄호 제거: (net), (gross) 등 — 계정명은 유지
    # 단, 음수 표기 (1,234)는 건드리지 않음

    # 한글 글자 사이 공백 제거: "매  출  액" → "매출액" (구형 DART 포맷)
    s = re.sub(r'(?<=[가-힣])\s+(?=[가-힣])', '', s)

    # 반복 공백 정리
    s = re.sub(r'\s+', ' ', s).strip()

    return s
