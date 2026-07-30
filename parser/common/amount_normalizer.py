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

# 합계행 밑줄 장식(숫자 뒤 '=＝_─—―━' 반복). 뒤쪽에 붙은 것만 제거 — 숫자 일부 아님.
# ★'~∼' 는 여기서 뺐다(2026-07-30) — 밑줄 장식이 아니라 **기간 범위 표기**다.
#   장식으로 지우면 '2006.02~'(임원 재직기간)가 2,006 원이라는 금액으로 들어간다(실측 319건).
_TRAIL_DECOR_RE = re.compile(r"[=＝_─—―━]+$")

# ── R4: 범위 표기(물결)는 금액이 아니다. '2006.02~' · '1,000~2,000' 모두 거부한다.
_RANGE_MARK_RE = re.compile(r"[~∼]")

# 순수 정수 문자열(부호·콤마 제거 후). float 를 우회해 정확히 파싱하기 위한 판정.
_PLAIN_INT_RE = re.compile(r"\d+")

# 정상 금액 표기: 콤마는 3자리 그룹 경계에만 온다. 소수부 허용('1,106.52' 환율·주가).
_WELL_FORMED_RE = re.compile(r"\d{1,3}(,\d{3})+(\.\d+)?")
_DECIMAL_RE = re.compile(r"\d+\.\d+")

# 금액 타당성 상한(원). 한국 상장사 최대 총자산 ≈ 5×10^14(500조). 넘으면 두 숫자가 붙은
# 것으로 본다 — 단일 셀의 콤마 오배치는 숫자열을 바꾸지 않지만, 두 숫자가 이어붙으면
# 자릿수가 폭발한다('316,305268,96147,344' → 3경 1,630조). 근거·실측은
# docs/qa/layer2_fidelity_full_2026-07-30.md 참고.
_AMOUNT_SANE_MAX = 10_000_000_000_000_000  # 1경원 (실측 최대치의 약 20배 여유)


def _is_complete_number(tok: str) -> bool:
    """토큰 하나가 **온전한 금액 표기**인가 — 부호·괄호를 벗긴 뒤 3자리 그룹 또는 무콤마
    정수/소수. 한 셀 안에 이런 토큰이 둘 이상이면 이어붙이면 안 된다(`parse_amount` R1)."""
    tk = tok.strip()
    if tk.startswith("(") and tk.endswith(")"):
        tk = tk[1:-1]
    tk = tk.lstrip("-△▲+").rstrip(",")
    if not tk:
        return False
    return bool(_WELL_FORMED_RE.fullmatch(tk) or _PLAIN_INT_RE.fullmatch(tk)
                or _DECIMAL_RE.fullmatch(tk))

# ── 단위 선언 토큰화 (2026-07-31, F1) ─────────────────────────────────
# 구 정규식은 `단위` **직후**에 금액 토큰을 요구했다:
#     _UNIT_DECL_RE = r'단위\s*[:：]?\s*\(?\s*(억원|백만원|만원|천원|원)'
# 전수 census(docs/qa/unit_declaration_census_2026-07-30.md) 실측 결과 그 한 줄이 세 가지
# 사고를 냈다:
#   ① '(단위 : 주, 천원)' — 금액을 선언했는데 첫 토큰이 비금액이라 매칭 실패 → **표째 폐기**
#      (187,189 표 / 2,626,779 셀 유실)
#   ② '(단위 : 천 원)'   — 자간 공백 때문에 매칭 실패 → 표째 폐기
#   ③ '(단위 : 천원, USD)' — 첫 금액 배수를 **전 열**에 적용 → USD·이자율 열이 ×1,000 오염
#      (DB 실측 6,130,738 행: '이자율(%)' 열에 2,228조원)
# 그래서 선언을 **토큰 리스트**로 읽는다. ③의 열 귀속은 `fin2/extract/units.py` 가 맡는다.
#
# ★ 왜 "금액 토큰을 아무 위치에서나" 찾지 않는가 — 그러면 서술문이 선언으로 오인된다:
#     '회사는 단위 사업부문별로 백만원 이상의 …'  → 백만원 발견 → ×10⁶ 오염
#   유실보다 오염이 나쁘다는 원칙(결측 > 오염)이 여기서 방향을 정한다. 그래서 선언으로
#   인정하는 조건을 **본문 전체가 단위 토큰 목록일 때**로 좁힌다(아래 `_is_unit_token`).

_DECL_BODY_MAX = 40                       # 실측 최장 선언 '천원, 외화단위: USD' 수준
_DECL_TAIL_MAX = 12                       # 괄호 없이 문자열 끝으로 닫히는 선언('단위:백만원')

# '단위' 뒤의 구분자·여는 괄호. 본문은 여기서부터 **닫는 문자까지**.
_DECL_HEAD_RE = re.compile(r'단위\s*[:：]?\s*[(（]?\s*')
_DECL_END_RE = re.compile(r'[)）\]\n]')
#
# ★한 정규식으로 `단위…본문…닫는문자` 를 통째로 매칭하려다 되돌렸다(2026-07-31):
#   `단위\s*[:：]?\s*[(（]?\s*([^)）\]\n]{0,40})[)）\]\n]` 로 하면 **앞선 서술문의 '단위' 가
#   뒤에 있는 진짜 선언을 삼킨다** — '…현금창출단위의 회수가능액을 … 없습니다. (단위 : 천원)'
#   에서 앞 '단위' 의 본문이 40자를 뻗어 뒤 선언의 ')' 를 먹어치우고, finditer 는 그 뒤부터
#   재개하므로 '(단위 : 천원)' 을 **못 본다**(bench 에서 None 으로 잡혔다).
#   그래서 출현마다 독립적으로 판정한다 — 느린 대신 조용한 유실이 없다.

# '천 원'·'백 만 원' 자간 공백 접합. '주 원'(두 단위)은 건드리지 않는다 — 접두사 목록으로 한정.
_MONEY_GLUE_RE = re.compile(r'(억|백\s*만|만|천)\s+(원)')

# 금액 토큰. '원/주'(주당 금액)도 금액으로 본다 — 배수는 앞의 금액 단위가 정한다.
_MONEY_TOKEN_RE = re.compile(
    r'^[(（]?\s*(억원|백만원|만원|천원|원)\s*(?:[/／]\s*[가-힣A-Za-z]{1,4})?\s*[)）]?[.,]?$')

# 비금액 단위 토큰(주·%·명·톤·USD·천USD…). **짧아야** 한다 — 문장 단어를 선언으로 오인하지
# 않기 위한 방어선이라, 한글 토큰은 4자·비한글 토큰은 8자로 끊는다(실측 최장 '외화단위',
# 'tCO2-eq'). 이 상한이 '사업부문별로'(6자) 같은 문장 단어를 걸러낸다.
# 한글이 섞인 토큰도 허용해야 한다 — '천USD'·'천JPY'·'백만달러'(실측). 종전에는 한글이 하나라도
# 있으면 **한글만** 허용하는 정규식을 걸어 '천USD' 가 탈락했고, 그 토큰 하나 때문에 선언 전체가
# 버려져 금액 표가 통째로 유실됐다(구·신 차분에서 12건 실측).
_UNIT_TOKEN_RE = re.compile(r'^[(（]?\s*[가-힣A-Za-z0-9$%\-㎡㎥㎏㎖ℓ°]{1,8}\s*[)）]?[.,:：]?$')
_HANGUL_MAX = 4                      # 한글 글자 수 상한 — 문장 단어('사업부문별로'=6) 배제

# **알려진** 단위 토큰. 선언으로 인정하려면 본문에 이것이 하나 이상 있어야 한다 —
# 길이 상한만으로는 '단위로 반영' → ['로','반영'] 같은 문장 꼬리가 선언으로 통과한다(실측).
# 반대로 모든 토큰을 화이트리스트로 강제하면 '(단위: 천원, 큐빅미터)' 처럼 낯선 단위가 하나
# 섞인 **금액 표를 통째로 잃는다**. 그래서 "하나 이상 알려진 것 + 나머지는 짧아야"로 나눈다.
_KNOWN_NON_MONEY_RE = re.compile(
    r'^[(（]?\s*(?:%|퍼센트|비율|지분율|백분율'
    r'|(?:천|백만|십억|억|만|백)?(?:주|주식|주수|주식수|톤|달러|USD|EUR|JPY|CNY|GBP|CHF'
    r'|HKD|VND|IDR|엔|위안|유로|원화|외화|배럴|배)'
    # ★'원화단위'·'외화단위' 는 **대상 이름**이지 단위가 아니다 — 여기 넣으면 콜론 왼쪽이
    #   단위로 인정돼 '외화단위:천USD' 가 한 토큰으로 남고, 길이 상한에 걸려 선언 전체가
    #   버려진다(구·신 차분에서 19 표 유실로 실측).
    r'|명|인|건|매|개|대|좌|본|일|시간|분|초|개월|년|월|회|차|평|점|세트|박스'
    r'|리터|ℓ|미터|㎡|㎥|㎏|㎖|kg|g|t|KAU|KOC|KCU|tCO2-eq|CO2'
    r'|\$|US\$|￦|€|¥'
    r')\s*[)）]?[.,:：]?$', re.IGNORECASE)

_TOK_SPLIT_RE = re.compile(r'[,，·|;、\s]+')
_PUNCT_ONLY_RE = re.compile(r'^[:：/／.,\-]+$')


def _is_unit_token(tok: str) -> bool:
    """토큰이 **단위 표기**로 볼 만한가(금액이든 아니든) — 길이 게이트."""
    if _MONEY_TOKEN_RE.match(tok):
        return True
    if sum(1 for ch in tok if '가' <= ch <= '힣') > _HANGUL_MAX:
        return False
    return bool(_UNIT_TOKEN_RE.match(tok))


def _is_known_unit_token(tok: str) -> bool:
    """**알려진** 단위인가(금액 또는 위 목록). 선언 인정의 필수 조건 — 문장 꼬리 차단용."""
    return bool(_MONEY_TOKEN_RE.match(tok) or _KNOWN_NON_MONEY_RE.match(tok))


def _money_multiplier(tok: str) -> Optional[int]:
    m = _MONEY_TOKEN_RE.match(tok)
    if not m:
        return None
    return UNIT_MULTIPLIERS[m.group(1)]


_DECL_SCAN_MAX = 2_000                    # 한 텍스트에서 검사할 '단위' 출현 수 상한(아래 ★)


def _iter_declarations(text: str):
    """텍스트 안의 **단위 선언마다** 토큰 목록을 yield 한다(원문 표기·순서 보존).

    선언으로 인정하는 조건 — 넷 다 만족해야 한다:
      · 본문이 **닫는 괄호·줄끝으로 닫힌다**. 괄호로 닫히면 40자까지, 문자열 끝으로 닫히면
        12자까지 — 후자를 짧게 잡는 이유는 '단위: 백만원 기준으로 산정' 같은 서술 꼬리가
        문자열 끝까지 통째로 본문이 되는 것을 막기 위해서다(실측 오염 방향).
      · 토큰이 1~12개(통화 나열 '천원, USD, 천JPY, EUR, NZD, CNY, AUD' 이 7개다)
      · **모든** 토큰이 짧다(`_is_unit_token`) — 문장 단어 배제
      · **하나 이상**이 알려진 단위다(`_is_known_unit_token`) — '단위로 반영' 배제

    ★ 지연 평가인 이유: 깨진 XML(`</TABLE>` 누락)에서는 한 형제의 itertext 가 문서 전체가 되어
      '단위' 가 수천 번 나온다. 구 정규식은 첫 매칭에서 멈췄지만 이 함수는 선언을 전부 만들 수
      있으므로, 호출부가 **첫 금액 선언에서 멈출 수 있게** generator 로 둔다.
      실측(`scripts/bench_unit_declaration.py`): 정상 표제 2.9 µs · '단위' 400 회 서술문
      236 µs(출현당 ~590 ns). 실제 전수 스윕 처리량은 0.14 s/filing 으로 F1 전과 같다.
    """
    if not text or "단위" not in text:
        return
    s = text.replace('：', ':').replace('　', ' ')
    pos = 0
    for _ in range(_DECL_SCAN_MAX):
        i = s.find('단위', pos)              # C 레벨 탐색(정규식 search 보다 싸다)
        if i < 0:
            return
        m = _DECL_HEAD_RE.match(s, i)
        pos = m.end()
        rest = s[pos: pos + _DECL_BODY_MAX + 1]
        end = _DECL_END_RE.search(rest)
        if end:
            body = rest[: end.start()]       # 괄호/줄바꿈으로 닫힌 선언
        elif len(s) - pos <= _DECL_TAIL_MAX:
            body = rest                      # 문자열 끝에서 닫힌 짧은 선언('단위:천원')
        else:
            continue                         # 닫히지 않았다 → 서술문
        toks = _body_tokens(body)
        if toks:
            yield toks


def _body_tokens(body: str) -> list[str]:
    """선언 본문 → 토큰. 단위 목록으로 보이지 않으면 [](=선언 아님).

    본문은 단위의 나열이고, 항목은 `대상 : 단위` 짝일 수 있다 —
    '(단위 : 천원, 주당순이익 : 원)' · '(원화단위:천원 외화단위:천USD,천JPY)'.
    콜론 주변 공백을 먼저 지워 짝을 **한 토큰**으로 만든 뒤(그래야 '천원 외화단위:천USD' 처럼
    쉼표 없이 이어진 것도 갈린다), 토큰마다 왼쪽이 알려진 단위인지 보고 버릴지 정한다.
    이 처리가 없으면 '주당순이익'(5자)·'외화단위:천USD'(9자) 때문에 토큰 검사가 실패해
    **선언 전체가 버려진다**(구·신 차분에서 표 19 개 유실로 실측).
    """
    body = _MONEY_GLUE_RE.sub(lambda mm: mm.group(1).replace(' ', '') + mm.group(2), body)
    body = re.sub(r'\s*:\s*', ':', body)     # '주당순이익 : 원' → '주당순이익:원' (짝을 한 토큰으로)
    toks: list[str] = []
    for raw in _TOK_SPLIT_RE.split(body.strip(' .:')):
        if not raw or _PUNCT_ONLY_RE.match(raw):
            continue
        if ':' in raw:
            left, right = raw.rsplit(':', 1)
            # 콜론 왼쪽이 **대상 이름**이면(알려진 단위가 아니다) 버리고 오른쪽만 취한다.
            # 왼쪽이 단위면 둘 다 살린다 — '(단위: 천원/USD : $)' 에서 왼쪽을 버리면 금액
            # 단위 '천원' 이 사라져 금액 표가 통째로 유실된다(구·신 차분 실측).
            for t in ((left, right) if _is_known_unit_token(left) else (right,)):
                if t and not _PUNCT_ONLY_RE.match(t):
                    toks.append(t)
        else:
            toks.append(raw)
    # 상한은 통화 나열을 담을 만큼 넉넉해야 한다 — 실측 '(단위: 천원, USD, 천JPY, EUR, NZD,
    # CNY, AUD)' 는 7 토큰이라 종전 상한 6 에서 **선언 자체가 무시됐다**.
    if not toks or len(toks) > 12:
        return []
    if all(_is_unit_token(t) for t in toks) and any(_is_known_unit_token(t) for t in toks):
        return toks
    return []


def detect_unit_tokens(text: str) -> list[str]:
    """단위 선언의 토큰 전부를 **원문 표기 그대로·선언 순서대로** 반환. 선언이 없으면 [].

        '(단위 : 주, 천원)'      → ['주', '천원']
        '(단위 : 천원, 천USD)'   → ['천원', '천USD']
        '(단위 : %)'             → ['%']
        '단위 사업부문별 매출은'  → []            (서술문 — 선언 아님)

    여러 선언이 있으면 **금액 토큰을 가진 첫 선언**을, 그것이 없으면 첫 선언을 돌려준다.
    열별 단위 귀속은 이 토큰을 받아 `fin2/extract/units.py` 가 결정한다.
    """
    first: list[str] = []
    for toks in _iter_declarations(text):
        if any(_money_multiplier(t) is not None for t in toks):
            return toks                      # 금액 선언 발견 → 즉시 종료(긴 텍스트 방어)
        if not first:
            first = toks
    return first


def detect_unit_declaration(text: str) -> Optional[int]:
    """
    '단위 : 천원' 같은 **명시적 단위 선언**의 금액 배수. 금액 선언이 없으면 None.

    detect_unit_multiplier()와 달리 '원' 선언(배수 1)도 None이 아니라 1로 구분 반환한다.
    → 호출부가 "가장 가까운 단위 선언"을 (원 포함) 채택할 수 있게 한다.
    '단위적립방식', '단위의 회수가능액' 처럼 단위 키워드가 없는 경우 None.

    ★ 반환값은 **표의 첫 금액 토큰 배수**다. 혼합 선언('천원, USD')에서 이 값을 전 열에
      적용하면 오염이 된다 — 호출부는 `detect_unit_tokens` + `units.resolve_column_units`
      를 써야 한다. 이 함수는 "금액 표인가"의 판정과 단일 단위 표의 배수용으로 남긴다.
    """
    for toks in _iter_declarations(text):
        for t in toks:
            mult = _money_multiplier(t)
            if mult is not None:
                return mult
    return None


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

    # ── R1: 한 셀에 **온전한 숫자가 공백으로 둘 이상** 나열된 경우(2026-07-30).
    #   제출인이 두 논리행을 한 행에 접어 넣은 표에서 나온다 — 원문 실측:
    #     <TD>723,570,750 723,570,750 </TD>  · 라벨도 '3.배당금   현금배당' · 다른 셀은 '- -'
    #   아래에서 공백을 지우고 이어붙이면 원문에 없는 값이 된다. XML 이 깨진 게 아니라
    #   원문 구조 자체가 그렇다(중첩 없는 단일 TD).
    toks = cell_text.split()
    if len(toks) >= 2 and all(_is_complete_number(tk) for tk in toks):
        if len({tk.strip() for tk in toks}) > 1:
            return None            # 어느 값이 이 셀 것인지 원문이 말하지 않는다 → 결측
        cell_text = toks[0]        # 같은 값이 반복된 셀 → 하나로 취한다

    s = (cell_text
         .strip()
         .replace(' ', '')          # 반각공백
         .replace('　', '')         # 전각공백
         .replace('​', '')     # zero-width space
         .replace('\xa0', ''))      # non-breaking space

    # 합계행 밑줄 장식 제거: 일부 보고서(보험·구형)는 합계 셀에 숫자 뒤로 '====' / '────'
    # 이중선을 붙여 렌더한다(예 '264653801=========='). 숫자의 일부가 아니므로 뒤쪽 장식만 제거.
    s = _TRAIL_DECOR_RE.sub('', s)

    # 공란 체크
    if not s or s in _BLANK_PATTERNS:
        return None

    # ── R4: 범위 표기가 남아 있으면 금액이 아니다(기간·구간).
    if _RANGE_MARK_RE.search(s):
        return None

    # 괄호 음수 표기: (1,234) → -1234
    negative = s.startswith('(') and s.endswith(')')
    if negative:
        s = s[1:-1]

    # 앞에 붙은 음수 부호
    if s.startswith('-') or s.startswith('△') or s.startswith('▲'):
        negative = True
        s = s.lstrip('-△▲')

    # ── R2: 후행 콤마('135,582,')는 표기 실수다 — 제거하고 판정한다.
    s = s.rstrip(',')

    # 다시 공란 체크
    if not s or s in _BLANK_PATTERNS:
        return None

    # ── R2 (계속): 콤마가 있으면 3자리 그룹이어야 하지만, 그룹이 깨졌다고 값을 버리진
    #   않는다. **단일 셀의 콤마 오배치는 숫자열을 바꾸지 않기 때문**이다:
    #     '92,31386,801'  → 9,231,386,801  (자릿수 10 — 정상. 콤마만 잘못 찍힘)
    #     '1,074,7100'    → 10,747,100     (자릿수 8  — 정상)
    #   숫자열이 실제로 틀리는 건 **두 숫자가 이어붙은 때**이고, 그때는 자릿수가 폭발한다:
    #     '316,305268,96147,344' → 3경 1,630조 (자릿수 17 — 날조)
    #   그래서 콤마 문법은 못 믿어도 자릿수는 믿을 수 있다 → 아래 _AMOUNT_SANE_MAX 로 가린다.
    s = s.replace(',', '')          # 천 단위 구분자 제거

    if not s or s in _BLANK_PATTERNS:
        return None

    try:
        # ★정수 문자열은 float 를 거치지 않는다. float64 는 유효자릿수가 15~17 자리라
        #   2^53(9,007,199,254,740,992) 을 넘는 정수에서 값이 조용히 바뀐다:
        #     int(float('723570750723570750')) = 723570750723570688
        #   깨진 원문에서 셀이 병합돼 18 자리 문자열이 들어오면(예 '723,570,750 723,570,750')
        #   이 경로를 타서 DB 에 원문에도 없는 값이 남았다(전수조사에서 17,771 행 발견).
        #   소수 표기('1.0'·환율 '1,106.52')는 종전대로 float 경유가 필요하다.
        val = int(s) if _PLAIN_INT_RE.fullmatch(s) else int(float(s))
        val *= multiplier
        # ── R3: 금액 타당성 상한. 종전 상한 9×10^18 은 BIGINT 한도라 사실상 무제한이어서
        #   병합으로 날조된 값(1.6×10^17 등)이 전부 통과했다(DB 실측 17,771 행).
        if abs(val) > _AMOUNT_SANE_MAX:
            return None   # 두 숫자 이어붙음·인코딩 오류 — 오염보다 결측을 택한다
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

    # 주석 참조 제거: (주14,28), (주5), (주석 9,37), (Note 1) 등
    # ★ '주석' 표기도 포함(2026-07-17): 구 정규식은 `\(주\s*\d` 라 '(주5)' 만 잡고
    #    '(주석 9,37)' 은 놓쳤다('주' 뒤가 숫자가 아니라 '석') → 퍼지 매핑에 의존하게 만들었다.
    s = re.sub(r'\(주석?\s*\d[\d,\s]*\)', '', s)
    s = re.sub(r'\(Note\s*\d+\)', '', s, flags=re.IGNORECASE)
    # 주석 참조 — 후방 제거: "계정과목 (주5)" 형태
    s = re.sub(r'\s*\(주석?\s*\d[\d,\s]*\)\s*$', '', s)

    # ★ literal '<주석N,...>' 제거(2026-07-30, 8.5경 카나리아 회귀로 발견):
    # `sanitize_dart_xml()`(2026-07-29) 이후 이 표기가 **텍스트로 그대로 남는다** — 종전에는
    # lxml 이 '<주석19/>' 를 엘리먼트로 만들어 꼬리 ',39>' 만 남았고 아래 규칙이 그걸 뗐다.
    # 이제는 '<주석5,42>' 전체가 텍스트라 아래 규칙이 ',42>' 만 떼고 '<주석5' 를 남긴다:
    #   '5. 이익잉여금<주석5,39>' → (구) '이익잉여금'  →  (신) '이익잉여금<주석5'  ← canonical 유실
    # 실측: DB손해보험 별도 이익잉여금이 exact → fuzzy 로 떨어져 canonical 을 잃었다.
    s = re.sub(r'<\s*주석?\s*\d[\d,\s]*>?', '', s)

    # ★ <주석N/> 엘리먼트 잔재 제거(2026-07-17, 실측 원문 대조로 발견):
    # DART 편집기는 작성자가 쓴 '<주석19,22,32,42,44>' 를 **엘리먼트 <주석19/> + 남은 텍스트
    # ',22,32,42,44>'** 로 저장한다. itertext() 는 그 꼬리를 계정명에 붙여버린다:
    #   원문 XML : <TD>4. 기타포괄손익-공정가치측정금융자산<주석19/>,22,32,42,44&gt;</TD>
    #   추출 결과: '기타포괄손익-공정가치측정금융자산,22,32,42,44>'
    #   DB손해보험: '이익잉여금,39>'  ← 8.5경 사고의 그 계정
    # 이건 '비슷한 이름'이 아니라 **정제 실패**다. 꼬리를 떼면 정확일치가 되므로 퍼지가 불필요.
    # (실측: 본문 라벨행의 0.39%, 6/300 파일 — 보험·금융사에 집중.)
    s = re.sub(r',[\d,\s]*>\s*$', '', s)

    # 영문 약어 괄호 제거: (net), (gross) 등 — 계정명은 유지
    # 단, 음수 표기 (1,234)는 건드리지 않음

    # 한글 글자 사이 공백 제거: "매  출  액" → "매출액" (구형 DART 포맷)
    s = re.sub(r'(?<=[가-힣])\s+(?=[가-힣])', '', s)

    # 반복 공백 정리
    s = re.sub(r'\s+', ' ', s).strip()

    return s
