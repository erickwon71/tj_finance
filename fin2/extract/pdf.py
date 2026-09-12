"""
Track C — PDF-only 정기보고서에서 재무제표 face 추출.

배경: 일부 보고서(구형 2000년대 + 일부 분기/정정본)는 DART 가 XBRL/XML 없이 **PDF 만** 제공
→ Track A(xbrl) · Track B(xml_text) 모두 0행. 이 모듈은 pdfplumber 로 PDF 본문 텍스트를 읽어
재무제표(재무상태표·손익계산서·포괄손익계산서·현금흐름표)의 face 라인을 추출한다.

설계(텍스트-리전 방식, NAVER/요약표 오연결 교훈 반영):
  - DART PDF 본문은 statement 제목이 `(연결) 재무상태표\n제 N 기 ... 현재\n(단위 : 천원)` 형태로
    렌더된다. **제목 + 직후 '제 N 기' 기간마커**를 statement 시작 앵커로 잡으면 목차/주석 속
    언급(기간마커 없음)·요약재무정보(앵커 앞)와 구분된다.
  - 한 statement 의 데이터 = 그 앵커부터 **다음 앵커 전까지** 의 'label 숫자 숫자…' 라인.
  - 단위는 앵커 직후 '(단위 : 원/천원/백만원)' 선언으로 결정(요약표 백만원 오염 차단).
  - 셀: 행 내 모든 숫자 리터럴을 읽고(any-column 비재사용), BS=col0(당기) / interim IS·CF 는
    '3개월 누적' 2단 헤더면 누적(YTD) 컬럼을 채택(std_v2 가 저장하는 값).

산출: fin2.extract.xbrl.ExtractedFact (source_format='pdf') → store_facts 로 fact_v2 적재 →
reconcile/standardize 가 Track A/B 와 동일하게 소비.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from parser.common.account_mapper import get_mapper
from parser.common.amount_normalizer import normalize_account_name
from fin2.extract.xbrl import ExtractedFact

# ── statement 제목 → 섹션코드 ─────────────────────────────────────────────────
_TITLE_TOKENS = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS",
    "현금흐름표": "CF",
    # 자본변동표(SCE)는 추출 대상 아님 — 앵커로만 인식해 경계로 사용.
    "자본변동표": "SCE",
}
# 우선순위(긴 토큰 먼저: 포괄손익계산서 > 손익계산서). 구형 PDF 는 제목을 자간 띄움
# ('손 익 계 산 서') → 각 글자 사이 \s* 허용하는 space-tolerant 패턴으로 생성.
def _spaced(tok: str) -> str:
    return r"\s*".join(re.escape(ch) for ch in tok)

_TITLE_NAMES = ("포괄손익계산서", "손익계산서", "재무상태표", "대차대조표", "현금흐름표", "자본변동표")
_TITLE_RE = re.compile(
    r"(?P<conso>연\s*결)?\s*"
    r"(?P<name>" + "|".join(_spaced(t) for t in _TITLE_NAMES) + r")"
)
# Allow two things between the period number and "기"/"분기" that the plain form
# ("제 28 기") doesn't have: a hyphenated sub-period suffix ("제 34-1 분기", real
# filing 00102432 rcept 20000512000074) and a short parenthetical current/prior
# remark ("제19(당)기", "제18(전)기", real filing 00115694 rcept 20010214000346).
# Either one used to make `_PERIOD_MARK_RE` miss the period marker entirely, so
# `_find_anchors()` treated the statement title as a false positive (looked like a
# stray TOC/footnote mention with no period marker nearby) and the whole BS/IS
# extraction for that basis came up empty despite the source table being simple
# and well-formed.
_PERIOD_MARK_RE = re.compile(r"제\s*\d+(?:-\d+)?\s*(?:\([^)]{1,4}\)\s*)?(?:기|분기)")
_UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만원|천원|원)")
# 'label  숫자 숫자 …' 데이터 라인: 선두 한글 라벨 + 1개 이상 숫자 토큰.
_HANGUL_RE = re.compile(r"[가-힣]")
_NUM_TOKEN_RE = re.compile(r"\(?-?[△▲]?\s?[0-9][0-9,]*\)?")
# ★2026-09-03 (Category C fy1999~2003 다운로드 복구 세션, 20000329000397 실측) — 1999~2003년대
# 인쇄 관행: BS 로마숫자/괄호번호 상위 항목("Ⅰ. 유동자산 (45,700,051)")은 괄호가 "바로 아래
# 세부항목의 합계 미리보기"일 뿐 음수가 아니다(세부항목이 괄호 없이 그 합으로 풀린다). 이
# 시대 문서에서 진짜 음수는 "-"/"△"/"▲" 접두로만 나타난다(실측: 자기주식 등 contra 계정,
# "1. 자기주식 -2,821,943"). 로마숫자/괄호번호로 시작하는 헤더 라인의 단일 괄호값만 음수
# 판정에서 제외한다 — 그 외 괄호=음수 해석(다른 시대 포맷)은 그대로 유지.
# ★2026-09-06 (R74 트랙② PDF재수집 재조사, 00198697 일진디스플 2000Q1 실측) — 같은 문서
# 안에서도 로마숫자 글리프가 섞여 나온다: "Ⅴ."는 진짜 유니코드 로마숫자(U+2164)인데
# "I."/"II."/"III."/"IV."는 pdfplumber가 라틴 문자 I/V(U+0049/U+0056)로 뽑아낸다(같은
# PDF 폰트의 서브셋 인코딩 차이로 추정). 유니코드 로마숫자만 인식하던 기존 정규식은
# "I. 자본금 (22,083,500,000)"을 헤더로 못 알아보고 괄호=음수로 오판정해, 헤더와 바로
# 아래 유일한 세부항목("보통주자본금")이 크기는 같고 부호만 반대인 쌍으로 저장되는
# 버그를 냈다. 라틴 로마숫자는 (Hangul 라벨 앞이라는 문맥상 오탐 위험이 낮으므로) 마침표
# 필수 조건으로 좁혀 추가.
_SUBTOTAL_HEADER_RE = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]{1,3}\.?\s*|[IVX]{1,4}\.\s*|\(\d{1,2}\)\s*)")

_UNIT_FACTOR = {"원": 1, "천원": 1000, "백만원": 1_000_000}

# ── Track C(PDF-only) "3줄 이중언어" 레이아웃 지원 ──────────────────────────
# 배경: 1999~2002년대 필링(72개사·195건, census: scripts/census_multiline_layout_2026-09-06.py)
# 은 BS/IS 표가 "한 줄=라벨+숫자"가 아니라 "한글 라벨" → "숫자만(기간별 여러 개)" →
# "영문 번역" 의 3줄 1항목 구조라 기존 _iter_data_lines() 가 라벨·숫자를 같은 줄에서
# 찾다 보니 거의 통째로 유실했다(설계: docs/plans/pdf_multiline_bilingual_layout_2026-09-06.md).
# 아래는 그 문서의 "구현 방향" 그대로 — 기존 단일줄 경로(_iter_data_lines/_parse_single_line)는
# 건드리지 않고, 게이트로 판별된 리전에서만 별도 3줄 파싱을 태운다(대다수 정상 필링 무영향).

# 페이지 푸터 잡음("전자공시시스템 dart.fss.or.kr Page 66") — 한글이 있어 라벨로 오인될
# 위험이 있으므로 3줄 모드 처리 전에 통째로 걸러낸다.
_FOOTER_NOISE_RE = re.compile(r"전자공시시스템|dart\.fss\.or\.kr")

# 라벨줄에 흔히 붙는 각주참조("(주석 2, 3)" 등) 안의 작은 숫자(2, 3)를 "이 줄에 진짜
# 데이터 숫자가 있다"고 오판하면 안 된다 — 3줄 게이트/페어링 판별 전용으로 먼저 지운다.
# 정본 각주제거 규칙은 amount_normalizer.normalize_account_name() 쪽(라벨 자체의 최종
# 정규화는 그 함수가 그대로 담당 — 여기서는 "숫자 유무 판별"만 위해 별도로 재사용한다.
_NOTE_REF_STRIP_RE = re.compile(r'\(주석?\s*\d[\d,\s와과및]*\)')

# 기간 열이 결측일 때 원문이 남기는 대시 placeholder(열 위치 보존용 — 왼쪽으로 채우지 않음).
_DASH_TOKEN_RE = re.compile(r"^[-－―–—]+$")


# ★2026-09-12(헤더 우선 파싱 재설계) — 표에 "주석" 열이 따로 있으면(예: "현금및현금성자산
#   4,5,6  2,351,294,869  2,403,931,716" — "4,5,6"이 별도 주석번호 열) `_NUM_TOKEN_RE`가
#   그 주석번호 나열도 그대로 숫자 토큰으로 집어(콤마+숫자 조합이라 형태는 금액과 같다)
#   금액 컬럼이 한 칸씩 밀린다(솔트웨어 20220802000208 실측 — "현금및현금성자산"이
#   456원으로, "단기금융상품"이 45,718원으로 나온 원인 = "4,5,6"/"4,5,7,18" 을 금액으로
#   오인식). 진짜 금액은 **천단위 콤마 그룹**(첫 그룹 1~3자리, 나머지 전부 정확히 3자리)
#   인데, 주석번호 나열은 자릿수가 불규칙(각 자리가 1~2자리인 번호 목록)하다 — 이 차이로
#   구분한다. 콤마가 아예 없으면(예 "45", "9") 그대로 금액으로 본다(1~2자리 순수 금액도
#   흔함, 오탐 방지).
def _looks_like_real_amount(tok: str) -> bool:
    core = tok.strip()
    if core.startswith("(") and core.endswith(")"):
        core = core[1:-1]
    core = core.lstrip("△▲-−").strip()
    if "," not in core:
        return True
    groups = core.split(",")
    if not (1 <= len(groups[0]) <= 3):
        return False
    return all(len(g) == 3 for g in groups[1:])

# 라벨 선두의 항목번호("Ⅰ.", "(1)", "1." 등)에 들어있는 숫자도 "진짜 데이터 숫자"가
# 아니다 — _SUBTOTAL_HEADER_RE(로마숫자/괄호번호)에 평범한 "N." 아라비아 접두어까지
# 더한 버전(amount_normalizer.normalize_account_name() 의 동일 접두어 제거 규칙과 정합).
_LEADING_ITEM_PREFIX_RE = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]{1,3}\.?\s*|[IVX]{1,4}\.\s*|\(\d{1,2}\)\s*|\d{1,2}\.\s*)")


# ★2026-09-06(00101488 rcept 20010814000979 원문 dry-run 실측) — 3줄이 항상 엄격히
# 분리돼 있지는 않다. 영문 번역이 짧으면 한글라벨과 **같은 줄**에 붙어 나온다
# ("자 산 총 계 (Total Assets)") — normalize_account_name() 은 (net)/(gross) 같은 짧은
# 약어 괄호만 지우고 이런 전체 문구 괄호는 남겨서 계정 매핑이 실패했다(자산총계 결측).
# 한글이 없는 trailing 괄호는 (원래 3번째 줄이었을) 영문 대역어이므로 라벨에서 떼어낸다
# — 한글이 든 괄호(예: "(자기주식 등)")는 계정명의 일부일 수 있어 보존.
_TRAILING_ENGLISH_GLOSS_RE = re.compile(r"\s*\([^()가-힣]*\)\s*$")


def _strip_inline_english_gloss(label: str) -> str:
    """라벨 끝에 같은 줄로 붙은 영문 대역어 괄호를 반복 제거(중첩 대비 while)."""
    prev = None
    s = label
    while s != prev:
        prev = s
        s = _TRAILING_ENGLISH_GLOSS_RE.sub("", s)
    return s.strip()


def _has_real_number(line: str) -> bool:
    """각주참조·항목번호 접두어의 작은 숫자를 지운 뒤에도 실제 숫자 토큰이 남는지
    (3줄 게이트/페어링 전용 — 실측: "(1)당좌자산"·"2. 단기금융상품" 처럼 라벨 자체에
    숫자가 섞여 들어있어 이 필터 없이는 라벨줄이 "숫자 있음"으로 오판됐다)."""
    s = _LEADING_ITEM_PREFIX_RE.sub("", line)
    s = _NOTE_REF_STRIP_RE.sub("", s)
    return bool(_NUM_TOKEN_RE.search(s))


def _looks_multiline_bilingual(region: str) -> bool:
    """'한글라벨 / 숫자단독 / 영문' 3줄 레이아웃 리전인지 판별하는 게이트.

    대다수 필링은 지금 단일줄 로직으로 이미 잘 동작한다(오늘 section_def 트랙에서
    "증상이 같다고 정답도 같지 않다"를 반례로 확인한 교훈 — 전면 교체 금지). "한글
    단독행(진짜 숫자 없음) 다음이 숫자단독행(한글 없음)" 비율이 충분히 높을 때만 3줄
    모드로 전환하고, 후보가 적으면(우연 매치 위험) 판정을 보류한다.
    """
    lines = [ln.strip() for ln in region.split("\n")]
    lines = [ln for ln in lines if ln and not _FOOTER_NOISE_RE.search(ln)]
    candidates = 0
    paired = 0
    for i in range(len(lines) - 1):
        ln = lines[i]
        if not _HANGUL_RE.search(ln) or _has_real_number(ln):
            continue
        candidates += 1
        nxt = lines[i + 1]
        if not _HANGUL_RE.search(nxt) and _has_real_number(nxt):
            paired += 1
    if candidates < 3:
        return False
    return paired / candidates >= 0.6


def _parse_single_line(line: str) -> tuple[str, list[int]] | None:
    """한 줄 'label 숫자 숫자 …' → (label, [nums]). 매치 없으면 None.

    _iter_data_lines() 의 기존 단일줄 로직을 그대로 함수로 뽑은 것(동작 무변경) —
    3줄 모드 리전 안에서도 드물게 라벨+숫자가 한 줄에 온 경계행을 같은 방식으로
    처리하기 위해 재사용한다.
    """
    nums_iter = list(_NUM_TOKEN_RE.finditer(line))
    if not nums_iter:
        return None
    first_num = nums_iter[0].start()
    # ★2026-09-06(00101488 실측) — "총계" 류는 라벨+짧은영문+숫자가 전부 한 줄에 온다
    # ("자 산 총 계 (Total Assets) 120,860,966,620 …"). 괄호 안에 한글이 없으면 원래
    # 3줄 레이아웃의 영문줄이 이번엔 라벨에 붙은 것뿐 — 떼지 않으면 account_mapper 가
    # "자산총계 (Total Assets)"를 못 알아보고 unknown 처리해 헤드라인 항목이 결측된다.
    # 한글 없는 trailing 괄호에만 반응하므로(_strip_inline_english_gloss 주석 참고)
    # 기존 정상 필링(그런 접미사가 없는 라벨)엔 영향 없음.
    label = _strip_inline_english_gloss(line[:first_num].strip())
    if not label or not _HANGUL_RE.search(label):
        return None
    # 로마숫자/괄호번호 헤더 + 단일 괄호값 = 소계 미리보기(_SUBTOTAL_HEADER_RE 주석 참고)
    # — 괄호를 벗겨내고 파싱해 음수판정을 우회한다.
    is_subtotal_preview = (
        len(nums_iter) == 1 and _SUBTOTAL_HEADER_RE.match(label) is not None)
    nums = []
    for mm in nums_iter:
        tok = mm.group(0)
        if is_subtotal_preview and tok.startswith("(") and tok.endswith(")"):
            tok = tok[1:-1]
            nums.append(parse_number(tok))
            continue
        # ★2026-09-12 — 주석번호 열("4,5,6")을 금액으로 오인식하지 않는다(위
        #   _looks_like_real_amount 주석 참고). is_subtotal_preview 경로는 위에서
        #   이미 처리했으니 이 필터를 안 거친다(그 경로는 원래도 콤마 없는 단일값이라
        #   서로 안 겹침).
        if not _looks_like_real_amount(tok):
            continue
        nums.append(parse_number(tok))
    nums = [n for n in nums if n is not None]
    return (label, nums) if nums else None


def _parse_numline_tokens(label: str, tokens: list[str]) -> list[int | None]:
    """숫자단독줄 토큰(공백 split, 열위치 보존) → [값 또는 None].

    - 헤더(로마숫자/괄호번호) 행은 그 줄의 **모든** 토큰에서 괄호를 벗겨 파싱한다(단일값
      가정을 버림 — 설계문서 실측: 같은 헤더 행 안에서도 괄호 유무가 값마다 들쭉날쭉하다).
    - 순수 대시는 결측(None)으로 **그 열 위치를 그대로 유지**한다(절대 왼쪽으로 채우지
      않는다 — 오늘 R74 컬럼압축 함정과 동일 원칙). 호출측이 idx로 원하는 열을 그대로
      골라 쓰므로, 리스트 길이·순서가 실제 원문 열과 일치해야 한다.
    - ★2026-09-06(00101488 실측) — 긴 영문 번역은 두 줄로 줄바꿈되는데, 진짜 숫자가
      **그 첫 영문줄 끝에 붙어** 나온다("(Appropriated Retained Earnings 622,000,000 …").
      이때 앞쪽 영문 단어 토큰들은 대시(결측 placeholder)가 아니라 그냥 잡음이므로
      대시와 달리 **자리를 만들지 않고 통째로 버린다**(대시=열 보존 / 잡음=열 없음,
      둘을 같은 None 취급하면 뒤 실측값이 왼쪽으로 밀려 컬럼 인덱스가 틀어진다).
    """
    is_header = _SUBTOTAL_HEADER_RE.match(label) is not None
    out: list[int | None] = []
    for tok in tokens:
        if _DASH_TOKEN_RE.fullmatch(tok):
            out.append(None)
            continue
        if not _NUM_TOKEN_RE.fullmatch(tok):
            continue  # 잡음(줄바꿈된 영문 조각 등) — 열 자리를 만들지 않고 버림
        if is_header and tok.startswith("(") and tok.endswith(")"):
            tok = tok[1:-1]
        # ★2026-09-12 — 주석번호 열("4,5,6") 셀이 그대로 토큰으로 들어오면(격자 폴백
        #   경로에서 특히 흔함 — extract_tables() 가 주석열을 별도 셀로 주지만 이
        #   함수는 셀 내용이 뭔지 모르고 그냥 숫자로 본다) 금액으로 오인식하지 않는다
        #   (위 _looks_like_real_amount 주석 참고). 대시와 달리 자리를 만들지 않고
        #   버린다 — 주석열은 애초에 "기간" 위치가 아니었으므로 열 보존 대상이 아니다.
        if not _looks_like_real_amount(tok):
            continue
        out.append(parse_number(tok))
    return out


def _iter_data_lines_multiline(region: str):
    """'한글라벨 / 숫자단독(열위치 보존) / 영문' 3줄 레이아웃 → (label, [nums]) 산출.

    - 순수 섹션 헤더(라벨 다음이 숫자줄이 아니라 바로 영문줄, 예 "자산\\n(Assets)")는
      숫자줄이 없으므로 라벨만 스킵(데이터 아님).
    - 영문 번역줄은 한글이 없어 별도 처리 불요(자동으로 건너뜀).
    - 라벨+숫자가 한 줄에 온 경계행(순수 3줄 패턴을 안 따르는 소수 예외)은 기존
      _parse_single_line() 로 그대로 처리.
    """
    raw = [ln.strip() for ln in region.split("\n")]
    lines = [ln for ln in raw if ln and not _FOOTER_NOISE_RE.search(ln)]
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not _HANGUL_RE.search(line):
            i += 1
            continue
        if _has_real_number(line):
            parsed = _parse_single_line(line)
            i += 1
            if parsed:
                yield parsed
            continue
        # 짧은 영문 대역어가 라벨과 같은 줄에 붙어온 경우 떼어낸다(위 _strip_inline_
        # english_gloss 주석 참고) — 그래야 "자산총계 (Total Assets)" 같은 라벨이
        # account_mapper 매핑에 실패해 헤드라인 항목이 결측되는 일이 없다.
        label = _strip_inline_english_gloss(line)
        nxt = lines[i + 1] if i + 1 < n else ""
        if nxt and not _HANGUL_RE.search(nxt) and _has_real_number(nxt):
            nums = _parse_numline_tokens(label, nxt.split())
            i += 2
            # ★2026-09-06(00101488 실측) — 순수 섹션 헤더("부채")가 드물게 밑줄/구분선을
            # pdfplumber 가 "0 0" 처럼 숫자로 오독한 가짜 숫자줄을 달고 나온다("부 채\n0
            # 0\n(Liabilities)"). 모든 기간이 문자 그대로 0이면 진짜 재무데이터가 아닐
            # 확률이 높다 — 그런 라벨이 canonical(예: bs.total_liabilities)에 매핑되면
            # 진짜 "부채총계" 값과 경합하는 가짜 0원 후보가 생겨 하류 결합로직(Layer3)에
            # 불필요한 위험을 얹는다. 결측(전부 None)과 마찬가지로 스킵 — 결측이 오염보다 낫다.
            if any(v not in (None, 0) for v in nums):
                yield label, nums
        else:
            # 순수 섹션 헤더 — 숫자줄 없음, 라벨만 스킵.
            i += 1


# ── Track C(PDF-only) 표-격자(pdfplumber extract_tables) 폴백 ──────────────
# 배경(00116268 동성제약, 2026-09-06 원문대조로 발견) — 위 3줄 게이트로도 못 잡는
# 세 번째 변형: 라벨이 좁은 열 폭 때문에 줄바꿈되는데, 줄바꿈 지점이 숫자를 사이에
# 두고 걸친다("자 산 총" → [숫자] → "계", "9.주주임원종업" → "원단기 [숫자]" →
# "대여금"). 텍스트 스트림(`extract_text()`)만 봐서는 라벨 앞/뒤 조각과 숫자가 서로
# 다른 줄로 흩어져 어느 조합도 복원할 수 없다 — `_region_has_anchor_labels()`가
# 이런 리전은 실측상 전부 거부해(자산총계/부채총계/자본총계 문자열이 개행으로
# 끊겨 안 걸림) BS 전체가 통째로 유실됐다(00116268: BS 행 0개, 별도·연결 둘 다).
#
# pdfplumber 의 `extract_tables()`(같은 페이지, 기본 설정)는 이 문서에서 셀 격자를
# 그대로 복원해 라벨 조각을 하나의 셀 문자열로 합쳐준다(`'자 산 총\n계'` 한 셀 +
# 같은 행에 숫자 4개) — 텍스트 스트림에선 안 보이던 라벨-숫자 대응이 표 구조로
# 보면 애초에 멀쩡하다. 그래서 텍스트 게이트가 리전을 거부할 때만(=대다수 정상
# 필링은 절대 이 경로를 안 탐) 그 리전이 걸치는 페이지의 표를 대신 읽는다 — 순수
# 폴백이라 기존 텍스트 경로의 동작은 전혀 안 바뀐다.
def _pages_overlapping(page_bounds: list[tuple[int, int]], start: int, end: int) -> list[int]:
    """앵커 리전 [start,end) 이 걸치는 페이지 인덱스(문서 순서)."""
    return [i for i, (pstart, pend) in enumerate(page_bounds) if pend > start and pstart < end]


def _table_rows_for_span(pdf, page_bounds, start: int, end: int) -> list[list]:
    """리전이 걸치는 페이지들의 표 행을 문서 순서대로 모은다(표 추출 실패 페이지는 스킵)."""
    if pdf is None or not page_bounds:
        return []
    rows: list[list] = []
    for pno in _pages_overlapping(page_bounds, start, end):
        try:
            tables = pdf.pages[pno].extract_tables()
        except Exception:
            continue
        for tbl in tables:
            rows.extend(tbl)
    return rows


def _clean_table_label(cell: str | None) -> str:
    """셀 문자열의 줄바꿈까지 포함한 모든 공백을 지운다(라벨이 여러 줄로 나뉘어도
    하나의 셀이므로 이미 순서가 맞다 — 3줄 게이트처럼 다음 줄을 추측해 이어붙일
    필요가 없다)."""
    return re.sub(r"\s+", "", cell or "")


def _table_has_anchor_labels(rows: list[list], stmt: str) -> bool:
    """표에서 재구성한 라벨이 그 statement 의 앵커 합계를 담고 있는지(요약표·
    엉뚱한 표 오검출 배제) — `_region_has_anchor_labels()`의 표-버전."""
    labels = _ANCHOR_LABELS.get(stmt, ())
    hits = sum(1 for row in rows if row and row[0]
               and any(lab in _clean_table_label(row[0]) for lab in labels))
    return hits >= 2


def _iter_data_lines_from_table_rows(rows: list[list]):
    """표 행(1열=라벨, 나머지=기간별 금액) → (label, [nums]) 산출.

    라벨 셀은 줄바꿈을 공백으로 접어 하나로 합친다(`_strip_inline_english_gloss`
    까지 재사용 — 표 경로에서도 영문 대역어가 라벨과 같은 셀에 올 수 있음). 금액
    셀은 빈 문자열(표 격자가 열을 실제보다 잘게 쪼갠 잡음 — 실측: 값/빈칸 교대로
    나옴)만 걷어내고, 나머지는 `_parse_numline_tokens()`(대시=열 보존 결측, 헤더행
    괄호벗김)로 그대로 재사용한다 — 순수 섹션 헤더(금액 셀이 전부 빈칸)는 스킵.
    """
    for row in rows:
        if not row:
            continue
        label = _strip_inline_english_gloss(re.sub(r"\s+", " ", row[0] or "").strip())
        if not label or not _HANGUL_RE.search(label):
            continue
        cells = [c for c in row[1:] if c is not None and c.strip() != ""]
        if not cells:
            continue
        nums = _parse_numline_tokens(label, cells)
        # 순수 섹션 헤더가 가짜 0으로 오독되는 경우도 있음(_iter_data_lines_multiline
        # 과 동일한 방어 — 모든 기간이 문자 그대로 0이면 결측과 동일 취급).
        if any(v not in (None, 0) for v in nums):
            yield label, nums


# 본문표 식별용 앵커 계정(요약표·주석표 배제). 각 statement 가 반드시 포함하는 합계 라벨.
_ANCHOR_LABELS = {
    "BS": ("자산총계", "부채총계", "자본총계"),
    "IS": ("매출", "영업이익", "당기순이익", "분기순이익", "반기순이익", "영업수익"),
    "CF": ("영업활동", "투자활동", "재무활동"),
}


@dataclass
class _Anchor:
    statement: str        # BS/IS/CF/SCE
    basis: str            # consolidated/separate
    start: int            # 전체 텍스트 내 시작 offset
    unit: int             # 원 환산 배수


# ── 헤더 구조 우선 파싱 (2026-09-12, `docs/plans/pdf_header_aware_table_parsing_
#   redesign_2026-09-12.md`) ───────────────────────────────────────────────
# 배경: 솔트웨어 20220802000208 실측 — `extract_text()`가 인접 두 행("Ⅰ.유동자산"과
# "현금및현금성자산") 사이 줄바꿈을 잃어버려 한 줄로 합쳐졌다. 기존 `_parse_single_line()`
# 은 "그 줄에 있는 숫자를 순서대로 컬럼"으로 간주해(모듈 docstring "any-column 비재사용")
# 이걸 못 잡는다. 표 헤더("과목 [주석] 제N(당/전)기…")를 먼저 읽어 "이 표는 기간 컬럼이
# 몇 개여야 하는가"를 진실로 삼고, 데이터 줄의 숫자 개수가 그와 다르면(=행 병합 등으로
# 텍스트 스트림이 깨졌다는 신호) 격자 폴백(`extract_tables()`)으로 승격한다.
# `parser/xml/table_extractor.py::parse_header_columns()`와 같은 철학(R88/89) — 헤더를
# 못 읽거나 애매하면 `None`으로 돌려 기존 동작을 완전히 그대로 둔다(R6, 추측 안 함).
@dataclass
class PdfTableHeader:
    has_note_col: bool
    n_period_cols: int
    period_labels: list[str]


# ★`_PERIOD_MARK_RE`(위)는 "제 N 기"/"제 N 분기"만 잡는다 — "반기"(半期) 복합어는
#   "반"이 "기" 앞에 끼어들어(예 "제 4(당)반기말"/"제4(당)반기") 못 잡는다. 실측
#   (솔트웨어 20220802000208, 반기보고서): 이 갭이 **두 군데**에서 동시에 문제였다 —
#   ①앵커 탐지(`_find_anchors`)에서 포괄손익계산서·자본변동표·현금흐름표 제목 뒤의
#   "제4(당)반기"가 전혀 안 걸려 앵커 자체가 안 잡히고, 그 결과 BS 리전이 다음 앵커
#   없이 문서 끝까지 뻗어나가 엉뚱한 표까지 섞였다(더 심각한 쪽). ②헤더 컬럼 수를
#   세는 `_parse_pdf_table_header`에서 "제4(당)반기말"이 안 걸려 헤더가 1개 컬럼으로
#   보이는 거짓음성. 두 용도 다 커버하는 정규식으로 통합(긴 것부터: 반기말>분기말>
#   반기>분기>기말>기 — 짧은 대안이 먼저면 "반기말"을 "기"로 조기 매치해버림).
#   `_PERIOD_MARK_RE`의 상위집합이라 교체해도 기존에 잡던 건 그대로 잡는다.
_HEADER_PERIOD_MARK_RE = re.compile(
    r"제\s*\d+(?:-\d+)?\s*(?:\([^)]{1,4}\)\s*)?(?:반기말|분기말|반기|분기|기말|기)")


def _parse_pdf_table_header(region: str) -> "PdfTableHeader | None":
    """리전 선두(~600자, 제목+단위선언 다음에 오는 실제 컬럼헤더 줄)에서 '과목 [주석]
    제N(당/전)기…' 구조를 읽는다.

    ★"제 N 기" 마커가 **한 줄에 2번 이상** 나오는 첫 줄만 헤더로 인정한다 — 앵커
    탐지에 쓰는 statement 제목 직후의 단일 기간마커줄("제 28 기 2020.12.31 현재")은
    보통 마커가 1개뿐이라 자연히 걸러진다(진짜 다기간 헤더만 2개 이상). 못 찾으면
    `None`(호출측이 기존 동작 그대로 유지 — 지어내지 않는다)."""
    head_region = region[:600]
    for raw in head_region.split("\n"):
        line = raw.strip()
        if not line:
            continue
        period_labels = _HEADER_PERIOD_MARK_RE.findall(line)
        if len(period_labels) >= 2:
            has_note = bool(re.search(r"주석|Note", line))
            return PdfTableHeader(has_note_col=has_note, n_period_cols=len(period_labels),
                                  period_labels=period_labels)
    return None


def _lines_disagree_with_header(
    lines: list[tuple[str, list[int]]], header: "PdfTableHeader",
) -> bool:
    """데이터 줄 중 하나라도 숫자 개수가 헤더 선언 기간 수를 **초과**하면 True.
    (부족한 경우는 원래도 흔하다 — 소계행이 일부 기간만 채우는 정상 서식이 있어
    "부족"은 신호로 안 쓴다. "초과"만 병합/오염의 강한 신호다 — 정상 데이터 줄은
    헤더가 선언한 기간 수보다 숫자가 많을 이유가 없다.)"""
    return any(len(nums) > header.n_period_cols for _, nums in lines)


def _adecimal_from_unit(unit: int) -> int:
    import math
    if unit <= 1:
        return 0
    return -int(round(math.log10(unit)))


def parse_number(tok: str) -> int | None:
    """PDF 셀 토큰 → 정수(리터럴). 괄호/△/− 음수, 콤마 제거."""
    t = tok.strip()
    if not t:
        return None
    neg = (t.startswith("(") and t.endswith(")")) or t[:1] in ("△", "▲", "-", "−")
    digits = re.sub(r"[^0-9]", "", t)
    if not digits:
        return None
    try:
        v = int(digits)
    except ValueError:
        return None
    return -v if neg else v


def _read_pdf_text(file_path) -> str | None:
    """PDF 전 페이지 텍스트 결합(페이지 경계 \f). 텍스트 미보유(스캔본) → None."""
    try:
        import pdfplumber
    except ImportError:
        return None
    parts: list[str] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for pg in pdf.pages:
                parts.append(pg.extract_text() or "")
    except Exception:
        return None
    text = "\f".join(parts)
    return text if _HANGUL_RE.search(text) else None


def _find_anchors(text: str) -> list[_Anchor]:
    """제목+직후 '제 N 기' 기간마커를 statement 시작 앵커로 수집(목차·주석 언급 배제)."""
    raw_anchors: list[_Anchor] = []
    for m in _TITLE_RE.finditer(text):
        name = re.sub(r"\s+", "", m.group("name"))   # '손 익 계 산 서' → '손익계산서'
        stmt = _TITLE_TOKENS[name]
        # 제목 직후(공백/개행 포함 ~50자) 에 '제 N 기' 기간마커가 와야 본문 statement
        # (목차 점선·주석 속 언급은 기간마커 부재 → 배제).
        # ★2026-09-12(솔트웨어 20220802000208 실측) — 예전엔 `_PERIOD_MARK_RE`("제 N
        #   기"/"제 N 분기"만 인식)를 썼는데, 반기보고서 제목 뒤엔 "제4(당)반기"("반"이
        #   "기" 앞에 끼어듦)가 오는 경우가 흔해 이 표현을 못 잡았다. 그 결과 이
        #   필링에서 포괄손익계산서·자본변동표·현금흐름표 앵커가 전부 안 잡혀, BS
        #   리전이 다음 앵커 없이 문서 끝까지(다른 statement·주석 전부) 뻗어나가
        #   엉뚱한 표의 합계(현금흐름표 기초/기말현금, 주석 소계 등)까지 "재무상태표"
        #   값으로 섞여 들어갔다. `_HEADER_PERIOD_MARK_RE`(아래, "반기"/"반기말"/
        #   "분기말"까지 인식)로 교체 — 기존 패턴의 상위집합이라 이미 잡던 건 그대로
        #   잡고 놓치던 것만 추가로 잡는다(회귀 위험 없음).
        if not _HEADER_PERIOD_MARK_RE.search(text[m.end():m.end() + 50]):
            continue
        basis = "consolidated" if m.group("conso") else "separate"
        # 단위: 앵커 직후 ~200자 내 '(단위 : X)'.
        um = _UNIT_RE.search(text, m.end(), m.end() + 200)
        unit = _UNIT_FACTOR.get(um.group(1), 1) if um else 1
        raw_anchors.append(_Anchor(stmt, basis, m.start(), unit))
    # ★2026-09-03(PDF 복구 세션, 20000329000397 실측) — 제목이 붙여쓰기+자간띄움 두 표기로
    # 연달아 인쇄되면("대차대조표\n대 차 대 조 표") 같은 statement 앵커가 몇 글자 간격으로
    # 중복 매칭된다(`_spaced()`의 '\s*'가 0칸도 허용해 붙여쓰기 표기도 그대로 통과). 두 앵커
    # 사이 구간이 사실상 비어 하나는 무의미한데, 그 무의미한 앵커가 리전 경계로 쓰이면 바로
    # 앞 앵커의 리전이 몇 글자로 쪼그라들어 본문을 놓친다. 같은 (statement, basis) 앵커가
    # 근접(<30자)하면 뒤쪽만 남긴다(실제 헤더/기간마커에 더 가까워 단위탐색창이 더 정확).
    anchors: list[_Anchor] = []
    for a in raw_anchors:
        if (anchors and anchors[-1].statement == a.statement
                and anchors[-1].basis == a.basis and a.start - anchors[-1].start < 30):
            anchors[-1] = a
        else:
            anchors.append(a)
    return anchors


def _region_has_anchor_labels(region: str, stmt: str) -> bool:
    """리전이 그 statement 의 본문표인지(앵커 합계 라벨 보유) 확인 — 잔여 stub/오검출 배제."""
    labels = _ANCHOR_LABELS.get(stmt, ())
    flat = region.replace(" ", "")
    return sum(1 for lab in labels if lab in flat) >= 2


def _is_interim_cumulative(region: str) -> bool:
    """interim IS/CF 가 '3개월 누적' 2단 헤더(당기 3개월·누적 공존)인지."""
    head = region[:400]
    return "누적" in head and "3개월" in head


def _iter_data_lines(region: str):
    """'label  숫자 숫자 …' 데이터 라인 → (label, [nums]) 산출."""
    for raw in region.split("\n"):
        line = raw.strip()
        if not line or not _HANGUL_RE.search(line):
            continue
        parsed = _parse_single_line(line)
        if parsed:
            yield parsed


def extract_pdf_facts(
    file_path,
    *,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """PDF-only 보고서 → fact_v2 호환 ExtractedFact 리스트(BS/IS/CF, 연결+별도).

    표-격자 폴백(아래 `facts_from_text()`의 `pdf`/`page_bounds`)을 쓰려면 pdfplumber
    페이지 객체가 파싱 내내 열려 있어야 해서, `_read_pdf_text()`(텍스트만 뽑고 파일을
    바로 닫음)는 여기선 안 쓰고 직접 `with pdfplumber.open()` 을 열어둔 채로 처리한다
    (텍스트 조합 방식 자체는 `_read_pdf_text()`와 동일 — `\\f` 페이지 구분).
    """
    try:
        import pdfplumber
    except ImportError:
        return []
    try:
        with pdfplumber.open(file_path) as pdf:
            page_texts = [pg.extract_text() or "" for pg in pdf.pages]
            text = "\f".join(page_texts)
            if not _HANGUL_RE.search(text):
                return []
            page_bounds: list[tuple[int, int]] = []
            pos = 0
            for pt in page_texts:
                page_bounds.append((pos, pos + len(pt)))
                pos += len(pt) + 1  # +1 = 페이지 구분자 "\f" 한 글자
            return facts_from_text(
                text, corp_code=corp_code, rcept_no=rcept_no,
                report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
                pdf=pdf, page_bounds=page_bounds,
            )
    except Exception:
        return []


def facts_from_text(
    text: str,
    *,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
    pdf=None,
    page_bounds: list[tuple[int, int]] | None = None,
) -> list[ExtractedFact]:
    """PDF 본문 텍스트 → ExtractedFact 리스트(PDF I/O 와 분리, 텍스트만으로도 테스트 가능).

    `pdf`/`page_bounds`: 표-격자 폴백용(선택) — 열려 있는 pdfplumber 문서 객체와, `text`
    안에서 각 페이지가 차지하는 [시작,끝) 문자 오프셋. 둘 다 없으면(기본값, 순수 텍스트
    fixture로 부르는 기존 테스트 전부 포함) 폴백을 아예 시도하지 않고 기존 동작 그대로.
    """
    anchors = _find_anchors(text)
    if not anchors:
        return []

    mapper = get_mapper()
    interim = report_fiscal_period in ("H1", "Q3", "Q1")
    facts: list[ExtractedFact] = []
    seen: set[tuple] = set()

    for i, anc in enumerate(anchors):
        if anc.statement == "SCE":
            continue
        end = anchors[i + 1].start if i + 1 < len(anchors) else len(text)
        region = text[anc.start:end]
        if not _region_has_anchor_labels(region, anc.statement):
            # ★2026-09-06(00116268 동성제약 원문대조로 발견) — 텍스트 스트림 게이트가
            # 거부하는 리전 중 일부는 라벨이 숫자를 사이에 두고 줄바꿈돼(3줄 게이트와도
            # 다른 변형 — 위 "표-격자 폴백" 블록 주석 참고) 텍스트만으론 원리적으로
            # 복원이 안 된다. 표 구조로 보면 라벨 조각이 한 셀로 이미 합쳐져 있으므로,
            # 텍스트 게이트가 거부할 때만(=정상 필링은 이 분기 자체를 안 탐) 폴백한다.
            table_rows = _table_rows_for_span(pdf, page_bounds, anc.start, end)
            if not table_rows or not _table_has_anchor_labels(table_rows, anc.statement):
                continue
            lines_iter = list(_iter_data_lines_from_table_rows(table_rows))
        else:
            # ★2026-09-06 — "3줄 이중언어" 레이아웃(1999~2002년대, 설계문서
            # docs/plans/pdf_multiline_bilingual_layout_2026-09-06.md) 지원. CF는 이번
            # 트랙 범위 밖(2단-페이지 레이아웃 별개 — 문서 §CF 참고)이라 BS/IS만 게이트
            # 대상. interim IS 의 '3개월 누적' 2단헤더가 이 3줄 레이아웃과 만나는 조합은
            # 실측 사례가 아직 없어 미검증 — cum_idx 는 열위치를 그대로 쓰므로 동작은
            # 하나, 실제로 그런 필링이 나오면 원문대조로 재확인할 것(문서 "구현 방향" §3).
            use_multiline = anc.statement in ("BS", "IS") and _looks_multiline_bilingual(region)
            text_lines = list(_iter_data_lines_multiline(region) if use_multiline
                              else _iter_data_lines(region))
            # ★2026-09-12(헤더 우선 파싱, 위 PdfTableHeader 참고) — 헤더가 선언한 기간
            #   수보다 숫자가 많은 줄이 하나라도 있으면(행 병합 등으로 텍스트 스트림이
            #   깨졌다는 신호) 격자 폴백을 시도한다. 앵커 라벨 자체는 안 깨져(위
            #   `_region_has_anchor_labels`를 통과했으므로) 이 분기 전엔 폴백 계기가
            #   없었다 — 솔트웨어 20220802000208 실측(라벨은 멀쩡, 숫자만 인접행과
            #   병합)이 정확히 이 경우.
            header = _parse_pdf_table_header(region)
            if header is not None and _lines_disagree_with_header(text_lines, header):
                table_rows = _table_rows_for_span(pdf, page_bounds, anc.start, end)
                if table_rows and _table_has_anchor_labels(table_rows, anc.statement):
                    lines_iter = list(_iter_data_lines_from_table_rows(table_rows))
                else:
                    lines_iter = text_lines
            else:
                lines_iter = text_lines
            # ★격자로 승격했든 안 했든, 헤더 기간수를 넘는 줄은 마지막에 한 번 더
            #   걸러낸다(설계문서 §2-2 — 격자 결과도 무조건 믿지 않는다). 콤마 없는
            #   단독 주석번호("14")처럼 `_looks_like_real_amount`로도 못 잡는 잔여
            #   케이스의 최종 안전망 — 결측이 오염보다 낫다(R6).
            if header is not None:
                lines_iter = [(lab, nums) for lab, nums in lines_iter
                             if len(nums) <= header.n_period_cols]
        adecimal = _adecimal_from_unit(anc.unit)
        fs_section = anc.statement.lower()
        period_kind = "instant" if anc.statement == "BS" else "duration"
        # interim IS/CF: '3개월 누적' 2단 → 당기 누적(2번째) 컬럼 채택. 그 외 col0.
        cum_idx = 1 if (interim and anc.statement in ("IS", "CF")
                        and _is_interim_cumulative(region)) else 0

        for label, nums in lines_iter:
            idx = cum_idx if len(nums) > cum_idx else 0
            # 3줄 모드는 열위치를 보존한 채 결측을 None으로 남긴다 — col0(당기)이 결측이면
            # 다른 열로 대체하지 않고 항목 자체를 결측 처리한다(왼쪽으로 채우지 않음).
            amount = nums[idx] if idx < len(nums) else None
            if amount is None:
                continue
            mapping = mapper.map(label, fs_section=fs_section)
            canon = mapping.account_code
            if not canon or canon.startswith("unknown."):
                continue
            # 섹션 일치(BS 계정만 BS 등) — 라벨 오매핑(CF '당기순이익' 등) 배제.
            if not canon.startswith(anc.statement.lower() + "."):
                continue
            if canon == "is.tax_expense" and "차감전" in label:
                continue  # 세전이익 오매핑 가드(Track B 와 동일)
            amount_won = amount * anc.unit
            # ★2026-09-03(PDF 복구 세션, 20010515000606 실측) — pdfplumber 가 인접 컬럼 숫자를
            # 섞어 붙이는 렌더링 결함으로 자릿수가 튀는 값이 드물게 나온다(실측: 별도기준
            # 995억원인 항목이 연결기준에서 "14조원"으로 나온 사례 — bigint 범위(약 922경)를
            # 넘겨 그 필링 전체 insert 를 실패시킨 바 있음). 복구 불가능한 노이즈라 아예
            # 버린다 — 결측이 낫다(위 PACKED_CELL 등과 같은 원칙, 이 시대 파서 전반의 설계).
            # 코스피 상장사 중 가장 큰 개별 계정도 수백조원(10^14~10^15) 대이므로 여유있게 잡음.
            if abs(amount_won) > 10 ** 16:
                continue
            # ★2026-09-04 — 위 절대상한(10^16)보다 작아도(예: 9,000조원대) 여전히 물리적으로
            # 불가능한 자릿수 튐이 소수 있음(실측: 전수 복구 6,592건 중 6건이
            # `scripts/dq_assertions.py::statement_magnitude_impossible` ERROR 로 잡힘).
            # 그 어서션과 같은 임계값을 핵심 4개 concept 에 그대로 재사용해 std_v3 도달 전에
            # 미리 버린다(같은 원칙 — 결측이 오염보다 낫다).
            magnitude_cap = {
                "bs.total_assets": 1e15, "bs.total_equity": 5e14,
                "bs.retained_earnings": 5e14, "is.revenue": 4e14,
            }.get(canon)
            if magnitude_cap is not None and abs(amount_won) > magnitude_cap:
                continue
            is_cumulative = period_kind == "duration" and report_fiscal_period != "FY"
            acode = (normalize_account_name(label) or label)[:120]
            # dedup 키 = DB uq_fact_v2_cell(rcept, acode, acontext_raw) 와 동일 grain.
            # acontext_raw 가 (stmt,basis,fy) 를 인코딩하므로 (acode, stmt, basis) 로 충분.
            # 같은 라벨이 본문·하위표에 재등장 시 **첫 등장(본문 col0 당기)** 만 채택.
            key = (acode, anc.statement, anc.basis)
            if key in seen:
                continue
            seen.add(key)
            facts.append(ExtractedFact(
                corp_code=corp_code,
                rcept_no=rcept_no,
                report_fiscal_year=report_fiscal_year,
                report_fiscal_period=report_fiscal_period,
                acode=acode,
                basis=anc.basis,
                context_fiscal_year=report_fiscal_year,
                col_index=0,
                period_kind=period_kind,
                period_type="FY" if report_fiscal_period == "FY" else report_fiscal_period,
                is_cumulative=is_cumulative,
                extra_dims=None,
                is_dimensional=False,
                adecimal=adecimal,
                amount_won=amount_won,
                source_format="pdf",
                source_ref=f"{anc.statement}_{anc.basis[:3]}/{label[:60]}"[:180],
                acontext_raw=f"pdf:{anc.statement}:{anc.basis[:3]}:c0:{report_fiscal_year}",
                context_parsed=False,
                canonical_account=canon,
            ))
    _fix_paren_formatted_bs(facts)
    _fix_swapped_grand_total_equity(facts)
    return facts


def _fix_paren_formatted_bs(facts: list[ExtractedFact]) -> None:
    """구 DART PDF 의 **괄호 전체포맷 BS** 보정(in-place).

    일부 2000년대 K-GAAP PDF 는 재무상태표 금액 컬럼 전체를 괄호로 감싼다((6,744,327)=양수
    표기 스타일, 음수 아님) → parse_number 가 전부 음수로 읽어 자산총계<0. (BS, basis) 단위로
    자산/부채/자본 총계가 **모두 음수**이고 회계 항등식 |자산|≈|부채|+|자본|(0.5% 이내)이 성립하면
    그 basis 의 BS 전 계정 부호를 반전(괄호=포맷 확정). 일반 음수(자본조정 등 소수)는 함께 뒤집히나
    헤드라인 정합 우선. 항등식 미성립(진짜 음수/오추출)은 미발동 → 품질게이트가 reject.
    """
    by_basis: dict[str, dict[str, int]] = {}
    for f in facts:
        if (f.canonical_account or "") in (
                "bs.total_assets", "bs.total_liabilities", "bs.total_equity"):
            by_basis.setdefault(f.basis, {})[f.canonical_account] = f.amount_won
    flip = set()
    for basis, d in by_basis.items():
        if len(d) < 3:
            continue
        A, L, E = d["bs.total_assets"], d["bs.total_liabilities"], d["bs.total_equity"]
        if A < 0 and L < 0 and E < 0 and abs(abs(A) - abs(L) - abs(E)) <= abs(A) * 0.005:
            flip.add(basis)
    for f in facts:
        if (f.canonical_account or "").startswith("bs.") and f.basis in flip \
                and f.amount_won is not None:
            f.amount_won = -f.amount_won

    # ★2026-09-06(00113526 rcept 20010814000593 실측, R75 표본 dry-run) — 위와 별개로
    # **부채·자본 섹션만** 괄호 전체포맷이고 자산 섹션은 정상인 변종도 있다(자산총계는
    # 양수, 부채총계·자본총계만 괄호=음수로 오독). 하위 세부계정까지 같은 문제인지는
    # 미검증이라 건드리지 않고, 항등식이 성립하는 헤드라인 두 총계만 반전한다(위 전체
    # 반전과 같은 "항등식으로 게이트" 원칙 — 라벨만 보고 블랭킷 반전하지 않음).
    for basis, d in by_basis.items():
        if len(d) < 3 or basis in flip:
            continue
        A, L, E = d["bs.total_assets"], d["bs.total_liabilities"], d["bs.total_equity"]
        if A > 0 and L < 0 and E < 0 and abs(A - (-L) - (-E)) <= abs(A) * 0.005:
            for f in facts:
                if f.basis == basis and f.canonical_account in (
                        "bs.total_liabilities", "bs.total_equity") \
                        and f.amount_won is not None:
                    f.amount_won = -f.amount_won
        # ★거울상 변종(00160047 rcept 20010814000003 실측) — 반대로 **자산 섹션만**
        # 괄호포맷이고 부채·자본은 정상인 경우. 자산총계 하나만 반전.
        elif A < 0 and L > 0 and E > 0 and abs(-A - L - E) <= abs(L + E) * 0.005:
            for f in facts:
                if f.basis == basis and f.canonical_account == "bs.total_assets" \
                        and f.amount_won is not None:
                    f.amount_won = -f.amount_won


def _fix_swapped_grand_total_equity(facts: list[ExtractedFact]) -> None:
    """"자본총계"↔"부채와자본총계" 값-라벨 도치 보정(in-place) — R75 3줄 레이아웃 전용.

    실측(00134565 rcept 20010331000135, PDF 페이지 이미지 직접 대조로 확정) — 근본원인은
    Korean 라벨이 숫자줄을 사이에 두고 **단어 중간에서 줄바꿈**되는 경우다("1.투자유가
    증권 평가이" → [숫자] → "익"). 이 잔여 조각("익")이 새 라벨 후보로 오인돼 그 다음
    숫자줄(원래 "자본총계"의 값)을 가로채고, 그 여파로 "자본총계"는 "부채와자본총계"의
    값(=자산총계와 같아야 하는 그랜드토탈)을 대신 받고, "부채와자본총계" 자신은 빈손이
    된다 — 결과적으로 bs.total_equity 가 bs.total_assets 와 똑같은 값이 되는 특징적
    증상을 남긴다(부채가 0이 아닌 한 회계상 불가능한 조합). 라벨 파싱을 역추적해 고치는
    대신, 같은 문서에서 이미 올바르게 뽑힌 자산총계·부채총계로 항등식(자본=자산-부채)
    역산해 복원한다 — `_fix_paren_formatted_bs()`와 같은 "항등식으로 게이트" 원칙.
    """
    totals: dict[str, dict[str, ExtractedFact]] = {}
    for f in facts:
        if (f.canonical_account or "") in (
                "bs.total_assets", "bs.total_liabilities", "bs.total_equity"):
            totals.setdefault(f.basis, {})[f.canonical_account] = f
    for basis, d in totals.items():
        if len(d) < 3:
            continue
        fa, fl, fe = d["bs.total_assets"], d["bs.total_liabilities"], d["bs.total_equity"]
        if fa.amount_won is None or fl.amount_won is None or fe.amount_won is None:
            continue
        if fl.amount_won == 0:
            continue  # 부채=0이면 자본=자산이 정상일 수 있어 증상 판별 불가
        if fe.amount_won == fa.amount_won:
            fe.amount_won = fa.amount_won - fl.amount_won
