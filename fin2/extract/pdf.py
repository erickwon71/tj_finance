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
_PERIOD_MARK_RE = re.compile(r"제\s*\d+\s*기")
_UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만원|천원|원)")
# 'label  숫자 숫자 …' 데이터 라인: 선두 한글 라벨 + 1개 이상 숫자 토큰.
_HANGUL_RE = re.compile(r"[가-힣]")
_NUM_TOKEN_RE = re.compile(r"\(?-?[△▲]?\s?[0-9][0-9,]*\)?")

_UNIT_FACTOR = {"원": 1, "천원": 1000, "백만원": 1_000_000}

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
    anchors: list[_Anchor] = []
    for m in _TITLE_RE.finditer(text):
        name = re.sub(r"\s+", "", m.group("name"))   # '손 익 계 산 서' → '손익계산서'
        stmt = _TITLE_TOKENS[name]
        # 제목 직후(공백/개행 포함 ~50자) 에 '제 N 기' 기간마커가 와야 본문 statement
        # (목차 점선·주석 속 언급은 기간마커 부재 → 배제).
        if not _PERIOD_MARK_RE.search(text[m.end():m.end() + 50]):
            continue
        basis = "consolidated" if m.group("conso") else "separate"
        # 단위: 앵커 직후 ~200자 내 '(단위 : X)'.
        um = _UNIT_RE.search(text, m.end(), m.end() + 200)
        unit = _UNIT_FACTOR.get(um.group(1), 1) if um else 1
        anchors.append(_Anchor(stmt, basis, m.start(), unit))
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
        nums_iter = list(_NUM_TOKEN_RE.finditer(line))
        if not nums_iter:
            continue
        first_num = nums_iter[0].start()
        label = line[:first_num].strip()
        if not label or not _HANGUL_RE.search(label):
            continue
        nums = [parse_number(mm.group(0)) for mm in nums_iter]
        nums = [n for n in nums if n is not None]
        if nums:
            yield label, nums


def extract_pdf_facts(
    file_path,
    *,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """PDF-only 보고서 → fact_v2 호환 ExtractedFact 리스트(BS/IS/CF, 연결+별도)."""
    text = _read_pdf_text(file_path)
    if not text:
        return []
    return facts_from_text(
        text, corp_code=corp_code, rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
    )


def facts_from_text(
    text: str,
    *,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """PDF 본문 텍스트 → ExtractedFact 리스트(PDF I/O 와 분리, 테스트 가능)."""
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
            continue
        adecimal = _adecimal_from_unit(anc.unit)
        fs_section = anc.statement.lower()
        period_kind = "instant" if anc.statement == "BS" else "duration"
        # interim IS/CF: '3개월 누적' 2단 → 당기 누적(2번째) 컬럼 채택. 그 외 col0.
        cum_idx = 1 if (interim and anc.statement in ("IS", "CF")
                        and _is_interim_cumulative(region)) else 0

        for label, nums in _iter_data_lines(region):
            idx = cum_idx if len(nums) > cum_idx else 0
            amount = nums[idx]
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
    return facts
