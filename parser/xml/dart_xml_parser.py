"""
DART XML 파서 — 메인 오케스트레이터

파일 포맷 자동 감지:
  - dart4.xsd (FORMULA-VERSION ≥ 5.x) → Track A: ACODE 기반 추출
  - dart3.xsd 이하                     → Track B: TITLE+텍스트 기반

출력: ParseResult (facts 리스트 + 메타데이터)
"""
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from loguru import logger
from lxml import etree

from parser.common.account_mapper import get_mapper, MappingResult
from parser.common.amount_normalizer import (
    parse_amount, normalize_account_name, detect_unit_multiplier
)
from parser.xml.section_detector import (
    detect_sections, find_section_tables,
    detect_unit_from_section, detect_periods_from_header,
    find_summary_tables,
)
from parser.xml.table_extractor import extract_rows, RowData
from parser.xml.note_extractor import extract_da_from_cf_notes, NoteDAFact


# ── 데이터 구조 ───────────────────────────────────────────────────────

@dataclass
class FactRow:
    """파싱된 단일 재무 항목"""
    fs_type: str            # BS_C / IS_C / CF_C / BS_S / IS_S / CF_S / NOTE_C / NOTE_S
    statement_type: str     # 'consolidated' / 'separate'
    period_type: str        # 'annual' / 'cumulative_ytd' / 'point_in_time'
    account_code: str       # 표준 코드 또는 "unknown.xxx"
    account_name_raw: str   # 원문 계정과목명
    period_end: Optional[date]
    fiscal_year: int
    fiscal_period: str      # FY / H1 / Q1 / Q3
    amount: Optional[int]   # 원 단위 (None=공란)
    col_index: int          # 0=당기, 1=전기, 2=전전기
    row_order: int
    is_subtotal: bool
    unit_multiplier: int
    source_format: str      # 'xbrl_acode' / 'xml_text'
    extraction_confidence: float
    parser_track: str       # 'A' / 'B'
    source_ref: Optional[str] = None   # 원본 위치: PDF='p42/t3/r5', XBRL='IS_C/ACODE', XML='BS_S/r12'


@dataclass
class ParseResult:
    """파싱 결과"""
    rcept_no: str
    corp_code: str
    fiscal_year: int
    fiscal_period: str
    report_type: str         # annual / half / quarter
    fin_type: str            # A(연결있음) / B(별도만)
    is_ifrs: bool
    unit_multiplier: int     # 1 또는 1000
    parser_track: str        # 'A' / 'B'
    facts: list[FactRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parse_status: str = "pending"   # success / partial / failed
    # unknown 계정 추적 (financial_facts에는 저장 안 되지만 unknown_accounts에는 기록)
    # {normalized_name: {"fs_type": ..., "count": ...}}
    unknown_accounts_seen: dict = field(default_factory=dict)


# ── 파서 메인 ─────────────────────────────────────────────────────────

def parse_dart_xml(
    file_path: Path,
    rcept_no: str,
    corp_code: str,
    fiscal_year: int,
    fiscal_period: str,
    report_type: str,
) -> ParseResult:
    """
    단일 DART XML 파일을 파싱해 ParseResult를 반환한다.

    Args:
        file_path:    XML 파일 경로
        rcept_no:     DART 접수번호
        corp_code:    DART 기업코드
        fiscal_year:  회계연도
        fiscal_period: FY / H1 / Q1 / Q3
        report_type:  annual / half / quarter
    """
    result = ParseResult(
        rcept_no=rcept_no,
        corp_code=corp_code,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        report_type=report_type,
        fin_type="B",
        is_ifrs=True,
        unit_multiplier=1,
        parser_track="B",
    )

    try:
        # ── XML 파싱 (malformed + 인코딩 자동 감지) ───────────────────
        root = _parse_xml_file(file_path)
        if root is None:
            result.parse_status = "failed"
            result.errors.append("XML 루트 요소 없음")
            return result

        # ── 메타데이터 추출 ───────────────────────────────────────────
        _extract_meta(root, result)

        # ── Track 결정 ────────────────────────────────────────────────
        track = _detect_track(root)
        result.parser_track = track

        if track == "A":
            _parse_track_a(root, result)
            # Track A는 _ACODE_TO_STANDARD에 있는 핵심 항목만 추출.
            # Track B도 함께 실행해 텍스트 기반 한국어 계정 보완 (특히 감가상각 등).
            # 중복 항목은 DB upsert 시 extraction_confidence 높은 쪽(Track A=1.0)이 우선.
            _parse_track_b(root, result, fiscal_year, fiscal_period)
        else:
            _parse_track_b(root, result, fiscal_year, fiscal_period)

        # ── NOTE 추출: 현금흐름표 주석 D&A ───────────────────────────────
        # 연간 보고서에만 적용 (분기/반기 주석은 전기 데이터 중복 위험)
        if fiscal_period == "FY":
            _extract_note_da(root, result, fiscal_year)

        # ── 결과 집계 ──────────────────────────────────────────────────
        # 핵심 재무제표 fact만으로 품질 판정 (NOTE 섹션 제외)
        # NOTE 항목은 복잡한 주석 구조로 unknown 비율이 높아 판정을 왜곡함
        core_mapped = sum(
            1 for f in result.facts
            if not f.fs_type.startswith("NOTE")
               and not f.account_code.startswith("unknown.")
        )
        # unknown.* skip 방식: 미매핑 계정은 result.facts 대신 unknown_accounts_seen에 기록
        # 품질 판정 시 unknown_accounts_seen의 비-NOTE 미매핑 계정도 포함
        core_unknown_from_seen = sum(
            info["count"]
            for info in result.unknown_accounts_seen.values()
            if not info.get("fs_type", "").startswith("NOTE")
        )
        # 레거시 방식(unknown.* 여전히 result.facts에 있는 경우)도 처리
        core_unknown_from_facts = sum(
            1 for f in result.facts
            if not f.fs_type.startswith("NOTE")
               and f.account_code.startswith("unknown.")
        )
        core_unknown = core_unknown_from_seen + core_unknown_from_facts
        core_total   = core_mapped + core_unknown

        if result.facts or core_unknown > 0:
            unknown_ratio = core_unknown / core_total if core_total else 1.0

            # 핵심 재무제표 항목이 아예 없으면 실패/부분
            if core_total == 0:
                result.parse_status = "partial"
                result.errors.append("핵심 재무제표(BS/IS/CF) 항목 없음")
            elif unknown_ratio > 0.5:
                result.parse_status = "partial"
            else:
                result.parse_status = "success"

            logger.debug(
                f"  품질 [{result.rcept_no}]: 핵심facts={core_total} "
                f"unknown={core_unknown} ({unknown_ratio:.0%})"
            )
        else:
            result.parse_status = "failed" if result.errors else "partial"
            result.errors.append("추출된 재무 항목 없음")

    except Exception as e:
        logger.error(f"파싱 오류 [{rcept_no}]: {e}")
        result.parse_status = "failed"
        result.errors.append(str(e))

    return result


# ── 원문 이스케이프 복구 (2026-07-29) ────────────────────────────────────────
# DART XML 은 특수문자를 이스케이프하지 않아 lxml 이 구조를 잘못 복구한다.
# 실측(FY2024, 400 filing):
#     꺾쇠 안 텍스트('<당기말')      99.8%  → 추출 영향 없음
#     미이스케이프 '&'               91.8%  → 추출 영향 없음
#     ★속성값 안 따옴표              2.0%  → **치명적**
# 앞의 둘은 손상이 본문 텍스트에서 끝나지만, 속성 따옴표가 깨지면 태그 중첩이 무너져
# 그 뒤 내용이 통째로 사라진다. 성일하이텍 FY2024 는 이 때문에 추출 셀 1,143 밖에 안 나왔고
# 복구 후 3,407(주석 섹션 17→75)이 됐다. 오류 없이 조용히 손실되던 것이라 지금까지 안 보였다.
#
# 250 filing 검증: 파싱오류 15,720→238 · 고아TR 6,892→57 · 추출 셀 +0.32% ·
#   값이 바뀐 filing 5(2%). 바뀐 것은 전부 **오귀속 교정**이었다
#   (예: '차입금, 기준이자율' 이 '8. 관계기업투자' 밑 → '16. 차입금' 으로 이동).

# 엔티티가 아닌 '&'  (&amp; &#123; &#x1F; 는 보존)
_BAD_AMP = re.compile(
    rb"&(?!(?:[a-zA-Z][a-zA-Z0-9]{1,7}|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});)"
)
# 속성값 안의 이스케이프 안 된 따옴표:  ENG=""KB Kookmin Bank" VALIGN="MIDDLE"
# ★정상적인 빈 속성(ENG="" …)을 깨면 안 되므로, 따옴표 사이에 '=' '<' '>' 가 없고
#   닫는 따옴표 뒤가 공백/'>' 일 때만 적용한다.
_BAD_ATTR_QUOTE = re.compile(rb'=""([^"=<>]{1,120})"(?=[\s>])')
# DART 실제 태그(실측 60 filing 에서 lxml 이 만든 '태그' 282종 중 진짜는 아래 40여 종뿐,
# 나머지는 '<당기말>' '<파묘>' 같은 본문 텍스트였다). 화이트리스트 밖이면 텍스트로 본다.
_DART_TAGS = (
    "DOCUMENT DOCUMENT-NAME COMPANY-NAME FORMULA-VERSION COVER COVER-TITLE BODY "
    "LIBRARY SUMMARY SECTION-1 SECTION-2 SECTION-3 TITLE P SPAN TABLE TABLE-GROUP "
    "THEAD TBODY TR TD TH TE TU COL COLGROUP IMAGE IMG IMG-CAPTION PGBRK CORRECTION "
    "EXTRACTION A BIG E FLY KNIGHTS MPN SHU THE WESTERN"
).split()
_BAD_LT = re.compile(
    rb"<(?!/?(?:" + b"|".join(t.encode() for t in sorted(_DART_TAGS, key=len, reverse=True))
    + rb")(?![A-Za-z0-9-])|[!?])",
    re.IGNORECASE,
)


def sanitize_dart_xml(raw: bytes) -> bytes:
    """파싱 전 원문 이스케이프 복구. 순서 주의 — '&' 를 먼저 고쳐야 뒤에서 넣는
    &quot;/&lt; 가 다시 이스케이프되지 않는다."""
    out = _BAD_AMP.sub(b"&amp;", raw)
    out = _BAD_ATTR_QUOTE.sub(rb'="&quot;\1&quot;"', out)
    return _BAD_LT.sub(b"&lt;", out)


def _parse_xml_file(file_path: Path) -> Optional[etree._Element]:
    """
    DART XML 파일 파싱. 인코딩 자동 감지 (UTF-8 → EUC-KR 폴백).

    구형 DART XML(~2010년대)은 XML 선언이 UTF-8이지만
    실제로는 EUC-KR로 저장된 경우가 많음.
    바이트 분포로 실제 인코딩을 감지 후 파싱.

    파싱 전 sanitize_dart_xml() 로 원문 이스케이프를 복구한다(위 주석 참조).
    """
    with open(file_path, "rb") as f:
        raw = f.read()

    actual_enc = _detect_xml_encoding(raw)
    raw = sanitize_dart_xml(raw)
    xml_parser = etree.XMLParser(recover=True)

    if actual_enc == "utf-8":
        # ── UTF-8: 원본 그대로 파싱 ────────────────────────────────
        try:
            root = etree.fromstring(raw, xml_parser)
            if root is not None:
                return root
        except Exception:
            pass
    else:
        # ── EUC-KR: 디코딩 후 UTF-8로 변환 ────────────────────────
        try:
            text = raw.decode("euc-kr", errors="replace")
            raw_utf8 = text.encode("utf-8")
            # XML 선언의 인코딩 표기를 utf-8로 교체
            raw_utf8 = re.sub(
                rb'encoding\s*=\s*"[^"]*"', b'encoding="utf-8"', raw_utf8, count=1
            )
            root = etree.fromstring(raw_utf8, xml_parser)
            if root is not None:
                return root
        except Exception:
            pass

    # ── 최후 수단: UTF-8 강제 지정 ─────────────────────────────────
    try:
        xml_parser_forced = etree.XMLParser(recover=True, encoding="utf-8")
        root = etree.fromstring(raw, xml_parser_forced)
        return root
    except Exception:
        return None


def _detect_xml_encoding(raw: bytes) -> str:
    """
    DART XML 파일의 실제 인코딩 추정.

    전략:
    1. strict UTF-8 decode 성공 → "utf-8"  (가장 신뢰)
    2. UTF-8 실패 시 EUC-KR 특징 바이트 분포로 판단

    주의: 이전의 0xB0~0xFE 카운팅 방식은 UTF-8 한글 연속 바이트
    (0x80~0xBF)가 0xB0~0xBF 구간과 겹쳐 오탐지가 발생했음.
    """
    # ── 1순위: strict UTF-8 검증 ──────────────────────────────────────
    try:
        raw.decode("utf-8")
        return "utf-8"
    except (UnicodeDecodeError, ValueError):
        pass

    # ── 2순위: EUC-KR 특징 바이트 분포 ───────────────────────────────
    # EUC-KR 한글: 첫 바이트 0xB0~0xC8, 두 번째 바이트 0xA1~0xFE
    # UTF-8에서 0xC0~0xC1, 0xF5~0xFF는 사용하지 않음
    # → 0xC0 이상 바이트가 있으면 EUC-KR 강력 지시
    sample = raw[:5000]
    high_bytes = sum(1 for b in sample if b >= 0xC0)
    if high_bytes > 10:
        return "euc-kr"

    return "utf-8"


def _extract_meta(root: etree._Element, result: ParseResult) -> None:
    """SUMMARY/COVER 블록에서 메타데이터 추출"""
    fin_type_found = False

    for extraction in root.findall(".//EXTRACTION"):
        acode = extraction.get("ACODE", "")
        value = (extraction.text or "").strip()
        if acode == "FIN_TYPE":
            result.fin_type = value  # A=연결있음, B=별도만
            fin_type_found = True
        elif acode == "IFRS_YN":
            result.is_ifrs = (value.upper() == "Y")

    # FIN_TYPE 태그 없는 경우 (분기보고서 일부):
    # TITLE / P 태그에서 연결 여부 자동 탐지
    if not fin_type_found:
        for title in root.findall(".//TITLE"):
            text = ''.join(title.itertext()).strip()
            if "연결재무" in text or "연결 재무" in text or "요약연결" in text:
                result.fin_type = "A"
                fin_type_found = True
                break
        if not fin_type_found:
            for p in root.findall(".//P"):
                text = ''.join(p.itertext()).strip()
                if "요약연결재무정보" in text or "연결재무제표" in text:
                    result.fin_type = "A"
                    break

    # 보고기간 종료일 탐색 (COVER의 TU 태그)
    for tu in root.findall(".//TU"):
        aunit = tu.get("AUNIT", "")
        if aunit == "PERIODTO":
            aunitvalue = tu.get("AUNITVALUE", "")
            if aunitvalue:
                logger.debug(f"보고기간 종료일: {aunitvalue}")
                break


def _detect_track(root: etree._Element) -> str:
    """
    파일이 Track A (진짜 XBRL ACODE 방식) 인지 Track B 인지 결정.

    판단 기준 (엄격): TE 태그의 ACODE 속성이 실제 XBRL 표준 네임스페이스를 사용할 때만 Track A.
    - "ifrs-full_*" 또는 "dart_*" (with ACONTEXT) → Track A
    - DART 독자 코드("LST_BASE", "STK_KND_TOT" 등) → Track B

    주의: dart4.xsd, FORMULA-VERSION ≥ 5.x 라도 현재(2026.05) DART 공시는
    TE 태그에 DART 독자 ACODE를 사용함. 재무제표 데이터는 TABLE/TD 구조로 제공.
    """
    # TE 태그에서 진짜 XBRL ACODE 존재 여부 확인
    # 주의: XBRL 섹션이 문서 앞부분이 아닌 중간에 위치하는 경우가 있으므로
    # 앞 100개만 샘플링하지 않고 전체 탐색 (10개 찾으면 조기 종료)
    te_elements = root.findall(".//TE[@ACODE]")
    xbrl_count = 0
    for te in te_elements:  # 전체 스캔 (10개 찾으면 break)
        acode = te.get("ACODE", "")
        acontext = te.get("ACONTEXT", "")
        if (acode.startswith("ifrs-full_") or acode.startswith("dart_")) and acontext:
            xbrl_count += 1
            if xbrl_count >= 10:
                break  # 충분히 확인됨 → 조기 종료

    # XBRL ACODE가 10개 이상이면 Track A
    if xbrl_count >= 10:
        return "A"

    return "B"


# ── Track A: ACODE 기반 파싱 ─────────────────────────────────────────

# XBRL ACODE → 표준 account_code 매핑 (ifrs-full 주요 항목)
_ACODE_TO_STANDARD: dict[str, str] = {
    # Balance Sheet
    "ifrs-full_Assets":                        "bs.total_assets",
    "ifrs-full_CurrentAssets":                 "bs.current_assets",
    "ifrs-full_CashAndCashEquivalents":        "bs.cash",
    "ifrs-full_CurrentFinancialAssets":        "bs.short_term_investment",
    "ifrs-full_TradeAndOtherCurrentReceivables": "bs.trade_receivables",
    "ifrs-full_Inventories":                   "bs.inventory",
    "ifrs-full_NoncurrentAssets":              "bs.noncurrent_assets",
    "ifrs-full_PropertyPlantAndEquipment":     "bs.ppe",
    "ifrs-full_RightofuseAssets":              "bs.right_of_use_asset",
    "ifrs-full_IntangibleAssetsOtherThanGoodwill": "bs.intangibles",
    "ifrs-full_Goodwill":                      "bs.goodwill",
    "ifrs-full_Liabilities":                   "bs.total_liabilities",
    "ifrs-full_CurrentLiabilities":            "bs.current_liabilities",
    "ifrs-full_CurrentBorrowings":             "bs.short_term_debt",
    "ifrs-full_NoncurrentLiabilities":         "bs.noncurrent_liabilities",
    "ifrs-full_NoncurrentBorrowings":          "bs.long_term_debt",
    "ifrs-full_Equity":                        "bs.total_equity",
    "ifrs-full_RetainedEarnings":              "bs.retained_earnings",
    "ifrs-full_IssuedCapital":                 "bs.paid_in_capital",
    "ifrs-full_TreasuryShares":                "bs.treasury_stock",
    # Income Statement
    "ifrs-full_Revenue":                       "is.revenue",
    "ifrs-full_GrossProfit":                   "is.gross_profit",
    "ifrs-full_ProfitLossFromOperatingActivities": "is.operating_income",
    "ifrs-full_FinanceIncome":                 "is.finance_income",
    "ifrs-full_FinanceCosts":                  "is.finance_cost",
    "ifrs-full_ProfitLossBeforeTax":           "is.ebt",
    "ifrs-full_IncomeTaxExpenseContinuingOperations": "is.tax_expense",
    "ifrs-full_ProfitLoss":                    "is.net_income",
    "ifrs-full_BasicEarningsLossPerShare":     "is.eps_basic",
    # Cash Flow
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "cf.operating",
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": "cf.investing",
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": "cf.financing",
    "ifrs-full_PurchaseOfPropertyPlantAndEquipment": "cf.capex",
    # 배당금 지급: 두 가지 XBRL 분류 모두 매핑
    # ifrs-full_DividendsPaid = 자본변동표 배당 (간혹 CF에서도 사용)
    # ifrs-full_DividendsPaidClassifiedAsFinancingActivities = CF 재무활동 배당 (K-IFRS 주류)
    "ifrs-full_DividendsPaid":                                    "cf.dividends_paid",
    "ifrs-full_DividendsPaidClassifiedAsFinancingActivities":     "cf.dividends_paid",
    "ifrs-full_DividendsPaidClassifiedAsOperatingActivities":     "cf.dividends_paid",
    # 인수합병 관련
    "ifrs-full_CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities": "cf.acquisition_of_subsidiaries",
    # 무형자산 취득
    "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": "cf.capex_intangible",
    "ifrs-full_AcquisitionOfIntangibleAssets": "cf.capex_intangible",
}

# ACONTEXT 파싱: 기간 타입 추출
#
# DART XBRL ACONTEXT 포맷 (두 가지 변형):
#   1. 구형(Plan 문서 기준): CFY2026eFQA → 당기 Q1 누적
#   2. 신형(실측):           CFY2024dFY  → 당기 연간
#                           PFY2023eFY  → 전기 연간 (BS 기준)
#                           BPFY2022dFY → 전전기 연간 (2년 전)
#
# 접두사 의미:
#   C   = 당기 (Current)  → col_index=0
#   P   = 전기 (Prior)    → col_index=1
#   BPF = 전전기 시작      → col_index=2  (BPFY2022dFY 형식)
#
# 기간 구분:
#   [de]FY  = 연간 (annual)
#   [de]FH  = 반기 (half-year)
#   [de]FQ  = 분기 (quarter, 3개월)
#   [de]FQA = Q1~Q3 누적 (cumulative_ytd)
#   [de]FHA = H1 누적 (cumulative_ytd)
#
# BPFY 패턴은 별도 regex로 먼저 처리 (BP+P 충돌 방지)
_ACONTEXT_BP_PATTERN = re.compile(
    r'BPFY\d{4}[de]F(?P<period>[QHYA])(?P<accum>A?)'
)
_ACONTEXT_PERIOD_PATTERN = re.compile(
    r'(?P<rel>[CP])FY\d{4}[de]F(?P<period>[QHYA])(?P<accum>A?)'
)


def _parse_acontext(acontext: str) -> tuple[str, int]:
    """
    ACONTEXT 문자열에서 (period_type, col_index)를 반환.

    Returns:
        period_type: 'annual' / 'cumulative_ytd' / 'point_in_time'
        col_index: 0=당기, 1=전기, 2=전전기
    """
    if not acontext:
        return "annual", 0

    def _period_from_match(m) -> str:
        period = m.group("period")
        accum  = m.group("accum")
        if period in ("Q", "H") and accum == "A":
            return "cumulative_ytd"
        elif period in ("Y", "A"):
            return "annual"
        else:
            return "point_in_time"

    # 1순위: BPFY (전전기) 패턴 먼저 체크 — CP 패턴과 충돌 방지
    bp_m = _ACONTEXT_BP_PATTERN.search(acontext)
    if bp_m:
        return _period_from_match(bp_m), 2

    # 2순위: C/P FY 패턴
    m = _ACONTEXT_PERIOD_PATTERN.search(acontext)
    if not m:
        return "annual", 0

    rel   = m.group("rel")     # C=당기, P=전기
    col_index = 0 if rel == "C" else 1

    return _period_from_match(m), col_index


def _parse_track_a(root: etree._Element, result: ParseResult) -> None:
    """
    Track A: TE 태그의 ACODE/ACONTEXT 속성으로 직접 추출.
    정확도 최고, 퍼지매칭 불필요.
    미등록 ACODE는 skip → Track B hybrid에서 텍스트 기반 보완.
    """
    # 연결/별도 구분: ACONTEXT에 Consolidated/Separate 포함
    te_elements = root.findall(".//TE[@ACODE]")

    for te in te_elements:
        acode = te.get("ACODE", "")
        acontext = te.get("ACONTEXT", "")
        aunit = te.get("AUNIT", "KRW")
        # TE의 텍스트는 직접 te.text 또는 <P> 자식 태그 안에 있을 수 있음
        # 예: <TE ACODE="..."><P>(4,196,698)</P></TE>
        raw_text = (te.text or "").strip()
        if not raw_text:
            # <P> 자식에서 텍스트 추출
            p_child = te.find("P")
            if p_child is not None:
                raw_text = (p_child.text or "").strip()
        # <P> 안에도 없으면 전체 텍스트 노드 결합 시도
        if not raw_text:
            raw_text = "".join(te.itertext()).strip()

        if not acode or not raw_text:
            continue

        # 표준 코드 매핑
        # Track A는 ACODE → _ACODE_TO_STANDARD 직접 매핑만 사용.
        # ACODE가 _ACODE_TO_STANDARD에 없으면 즉시 skip (mapper 호출 불필요).
        # 이유: mapper.map()은 텍스트 기반 퍼지매칭이라 XBRL 태그명에 맞지 않음.
        #       Track B가 동일 파일에서 텍스트 기반 계정을 보완 추출함.
        if acode in _ACODE_TO_STANDARD:
            account_code = _ACODE_TO_STANDARD[acode]
            confidence = 1.0
        else:
            continue  # 미등록 ACODE → skip (Track B에서 보완)

        # 연결/별도 구분
        if "Consolidated" in acontext or "_CON" in acontext.upper():
            statement_type = "consolidated"
            fs_prefix = _fs_prefix_from_code(account_code) + "_C"
        elif "Separate" in acontext or "_SEP" in acontext.upper():
            statement_type = "separate"
            fs_prefix = _fs_prefix_from_code(account_code) + "_S"
        else:
            # 기본값: FIN_TYPE A이면 연결, B이면 별도
            if result.fin_type == "A":
                statement_type = "consolidated"
                fs_prefix = _fs_prefix_from_code(account_code) + "_C"
            else:
                statement_type = "separate"
                fs_prefix = _fs_prefix_from_code(account_code) + "_S"

        # 기간 타입 및 col_index
        period_type, col_index = _parse_acontext(acontext)

        # Track A: ACODE 기반이므로 _ACODE_TO_STANDARD에 없는 항목은 저장하지 않음
        # (알 수 없는 XBRL 표준 태그를 unknown.*로 저장하면 financial_facts 비대화 & unknown_accounts 오염)
        if account_code.startswith("unknown."):
            continue

        # 금액 파싱
        # ADECIMAL 속성으로 단위 결정: ADECIMAL="-6" → 백만원(×10^6), "-3" → 천원(×10^3)
        # unit_multiplier 기본값(1)보다 ADECIMAL이 더 정확하므로 우선 사용
        adecimal_str = te.get("ADECIMAL", "")
        try:
            adecimal = int(adecimal_str)
            # ADECIMAL은 소수점 자릿수(-n = n자리 반올림 → 단위 10^n)
            unit_mult = 10 ** (-adecimal) if adecimal < 0 else 1
        except (ValueError, TypeError):
            unit_mult = result.unit_multiplier

        amount = parse_amount(raw_text, unit_mult)

        result.facts.append(FactRow(
            fs_type=fs_prefix,
            statement_type=statement_type,
            period_type=period_type,
            account_code=account_code,
            account_name_raw=acode,  # ACODE를 원문으로 저장
            period_end=None,         # TODO: ACONTEXT에서 날짜 파싱
            fiscal_year=result.fiscal_year,
            fiscal_period=result.fiscal_period,
            amount=amount,
            col_index=col_index,
            row_order=0,
            is_subtotal=False,
            unit_multiplier=result.unit_multiplier,
            source_format="xbrl_acode",
            extraction_confidence=confidence,
            parser_track="A",
        ))


def _fs_prefix_from_code(account_code: str) -> str:
    """account_code 접두어에서 재무제표 종류 판단"""
    if account_code.startswith("bs."):
        return "BS"
    elif account_code.startswith("is."):
        return "IS"
    elif account_code.startswith("cf."):
        return "CF"
    elif account_code.startswith("note."):
        return "NOTE"
    return "BS"


# ── Track B: TITLE+텍스트 기반 파싱 ──────────────────────────────────

_FS_TYPE_MAP = {
    "BS_C": ("consolidated", "point_in_time", "BS_C"),
    "IS_C": ("consolidated", "cumulative_ytd", "IS_C"),
    "CF_C": ("consolidated", "cumulative_ytd", "CF_C"),
    "BS_S": ("separate",     "point_in_time", "BS_S"),
    "IS_S": ("separate",     "cumulative_ytd", "IS_S"),
    "CF_S": ("separate",     "cumulative_ytd", "CF_S"),
    "NOTE_C": ("consolidated", "annual", "NOTE_C"),
    "NOTE_S": ("separate",     "annual", "NOTE_S"),
}


def _extract_note_da(
    root: etree._Element,
    result: ParseResult,
    fiscal_year: int,
) -> None:
    """
    현금흐름표 주석에서 D&A(감가상각비·무형자산상각비) 추출 → result.facts에 추가.

    추출 결과: note.depreciation, note.amortization, note.rou_depreciation, note.da_total
    연간 보고서(FY)에만 실행.
    """
    try:
        da_facts = extract_da_from_cf_notes(root)
    except Exception as e:
        logger.debug(f"note_extractor 오류 ({result.rcept_no}): {e}")
        return

    for nf in da_facts:
        # col_index 0 = 당기(fiscal_year), 1 = 전기(fiscal_year-1)
        fy = fiscal_year - nf.col_index
        fs_type   = "NOTE_C" if nf.is_consolidated else "NOTE_S"
        stmt_type = "consolidated" if nf.is_consolidated else "separate"

        # da_total은 이미 절대금액(unit_multiplier=1)으로 계산됨
        # 나머지는 unit_multiplier가 적용된 절대금액
        # FactRow는 amount를 원 단위로 저장하므로 unit_multiplier=1 처리
        result.facts.append(FactRow(
            fs_type=fs_type,
            statement_type=stmt_type,
            period_type="annual",
            account_code=nf.account_code,
            account_name_raw=nf.account_name_raw,
            period_end=None,        # NOTE는 period_end 없음
            fiscal_year=fy,
            fiscal_period="FY",
            amount=nf.amount,       # 이미 원 단위 절대금액
            col_index=nf.col_index,
            row_order=None,
            is_subtotal=(nf.account_code == "note.da_total"),
            unit_multiplier=1,      # 이미 배수 적용됨
            source_format="note_xml",
            extraction_confidence=0.95,
            parser_track=result.parser_track,
        ))


def _parse_track_b(
    root: etree._Element,
    result: ParseResult,
    fiscal_year: int,
    fiscal_period: str,
) -> None:
    """
    Track B: TITLE 기반 섹션 탐지 + 텍스트 매핑.

    Fallback:
      - 연간 보고서: TITLE 기반 섹션 탐지 (재무상태표/손익계산서/현금흐름표)
      - 분기/반기 보고서에서 섹션 미탐지 시: '요약재무정보' 테이블 파싱
    """
    mapper = get_mapper()
    sections = detect_sections(root)

    # 연간 보고서: BS는 point_in_time, IS/CF는 annual
    # 반기/분기: IS/CF는 cumulative_ytd
    is_annual = (fiscal_period == "FY")

    for section_code, title_elem in sections.items():
        if title_elem is None:
            continue

        # 연결/별도 여부에 따라 FIN_TYPE 체크
        statement_type, period_type, fs_type = _FS_TYPE_MAP[section_code]
        if statement_type == "consolidated" and result.fin_type == "B":
            continue  # 연결 없는 기업의 연결 섹션 무시

        # 반기/분기는 IS/CF가 누적(cumulative_ytd)
        if not is_annual and fs_type in ("IS_C", "CF_C", "IS_S", "CF_S"):
            period_type = "cumulative_ytd"

        # 단위 탐지
        unit = detect_unit_from_section(title_elem)

        # 테이블 탐색
        tables = find_section_tables(title_elem)
        if not tables:
            logger.debug(f"테이블 없음: {section_code}")
            continue

        # 헤더 날짜는 첫 번째 테이블에서 추출
        period_dates = detect_periods_from_header(tables[0])

        # 데이터 테이블: TR이 가장 많은 테이블 우선 (첫 테이블은 보통 헤더만)
        data_tables = sorted(tables, key=lambda t: len(t.findall(".//TR")), reverse=True)

        for table in data_tables:
            rows = extract_rows(table, multiplier=unit)

            for row in rows:
                if not row.account_name:
                    continue

                # 계정과목 표준화 (fs_section 전달로 섹션 우선 매핑)
                # fs_type "IS_C" → "is", "CF_S" → "cf", "NOTE_C" → "note" 등
                _fs_section = fs_type.split("_")[0].lower() if fs_type else None
                mapping: MappingResult = mapper.map(row.account_name, fs_section=_fs_section)

                # Track A와 동일하게 미매핑 계정은 financial_facts에 저장하지 않음.
                # unknown.* 계정은 unknown_accounts 테이블에만 기록되므로 데이터 손실 없음.
                # (재파싱 없이 account_maps 추가 후 DB UPDATE로 소급 적용 가능)
                if mapping.account_code.startswith("unknown."):
                    # unknown_accounts 테이블 추적을 위해 별도 기록
                    from parser.common.amount_normalizer import normalize_account_name as _norm
                    norm = _norm(row.account_name)[:300]
                    if norm not in result.unknown_accounts_seen:
                        result.unknown_accounts_seen[norm] = {
                            "fs_type": fs_type[:6],
                            "count": 0,
                        }
                    result.unknown_accounts_seen[norm]["count"] += 1
                    continue

                for col_idx, amount in enumerate(row.amounts):
                    period_end = None
                    if col_idx < len(period_dates):
                        try:
                            from datetime import date as date_cls
                            parts = period_dates[col_idx].split("-")
                            period_end = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
                        except Exception:
                            pass

                    result.facts.append(FactRow(
                        fs_type=fs_type,
                        statement_type=statement_type,
                        period_type=period_type,
                        account_code=mapping.account_code,
                        account_name_raw=row.account_name,
                        period_end=period_end,
                        fiscal_year=fiscal_year if col_idx == 0 else fiscal_year - col_idx,
                        fiscal_period=fiscal_period,
                        amount=amount,
                        col_index=col_idx,
                        row_order=row.row_order,
                        is_subtotal=row.is_subtotal,
                        unit_multiplier=unit,
                        source_format="xml_text",
                        extraction_confidence=mapping.confidence,
                        parser_track="B",
                    ))

    # ── Fallback: 분기/반기 요약재무정보 테이블 ─────────────────────────
    # 표준 섹션(BS/IS/CF)이 하나도 없으면 '요약재무정보' 테이블 시도
    core_found = any(
        title_elem is not None
        for code, title_elem in sections.items()
        if not code.startswith("NOTE")
    )
    if not core_found and fiscal_period != "FY":
        _parse_summary_tables(root, result, fiscal_year, fiscal_period, mapper)


def _parse_summary_tables(
    root: etree._Element,
    result: ParseResult,
    fiscal_year: int,
    fiscal_period: str,
    mapper,
) -> None:
    """
    분기/반기 '요약재무정보' 테이블 파싱 (표준 섹션 탐지 실패 시 fallback).

    테이블 구조:
      - 연결/별도 구분: P 태그 텍스트 ("가. 요약연결재무정보" / "나. 요약재무정보")
      - 단일 테이블에 BS + IS 항목 혼합
      - 계정과목 타입: account_code 접두어로 BS/IS 판별
    """
    summary = find_summary_tables(root)
    if not any(v is not None for v in summary.values()):
        return

    logger.debug(f"요약재무정보 fallback 파싱: {result.rcept_no}")

    for stmt_key, table_elem in summary.items():
        if table_elem is None:
            continue

        statement_type = "consolidated" if stmt_key == "consolidated" else "separate"
        if statement_type == "consolidated" and result.fin_type == "B":
            continue  # 연결 없는 기업

        # 단위 탐지 (부모 요소에서 탐색)
        unit = _detect_unit_near_table(table_elem)

        # 헤더에서 날짜 추출
        period_dates = detect_periods_from_header(table_elem)

        rows = extract_rows(table_elem, multiplier=unit)

        for row in rows:
            if not row.account_name:
                continue

            # Track A: ACODE 기반이므로 account_name에 한글 계정명이 있으면
            # fs_section 없이 매핑하고, 이후 code prefix로 fs_type 결정
            mapping: MappingResult = mapper.map(row.account_name)

            # 미매핑 계정은 저장하지 않음 (unknown_accounts 추적만)
            if mapping.account_code.startswith("unknown."):
                from parser.common.amount_normalizer import normalize_account_name as _norm
                norm = _norm(row.account_name)[:300]
                if norm not in result.unknown_accounts_seen:
                    result.unknown_accounts_seen[norm] = {
                        "fs_type": "BS_S",  # summary 테이블의 기본 섹션
                        "count": 0,
                    }
                result.unknown_accounts_seen[norm]["count"] += 1
                continue

            # 계정 타입에 따라 fs_type/period_type 결정
            code = mapping.account_code
            if code.startswith("bs."):
                fs_type = "BS_C" if statement_type == "consolidated" else "BS_S"
                period_type = "point_in_time"
            elif code.startswith("is."):
                fs_type = "IS_C" if statement_type == "consolidated" else "IS_S"
                period_type = "cumulative_ytd"
            elif code.startswith("cf."):
                fs_type = "CF_C" if statement_type == "consolidated" else "CF_S"
                period_type = "cumulative_ytd"
            else:
                # note.* 등 → 기본 분류 (저장은 됨)
                fs_type = "BS_C" if statement_type == "consolidated" else "BS_S"
                period_type = "point_in_time"

            for col_idx, amount in enumerate(row.amounts):
                period_end = None
                if col_idx < len(period_dates):
                    try:
                        from datetime import date as date_cls
                        parts = period_dates[col_idx].split("-")
                        period_end = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
                    except Exception:
                        pass

                result.facts.append(FactRow(
                    fs_type=fs_type,
                    statement_type=statement_type,
                    period_type=period_type,
                    account_code=mapping.account_code,
                    account_name_raw=row.account_name,
                    period_end=period_end,
                    fiscal_year=fiscal_year if col_idx == 0 else fiscal_year - col_idx,
                    fiscal_period=fiscal_period,
                    amount=amount,
                    col_index=col_idx,
                    row_order=row.row_order,
                    is_subtotal=row.is_subtotal,
                    unit_multiplier=unit,
                    source_format="xml_text",
                    extraction_confidence=mapping.confidence,
                    parser_track="B",
                ))


def _detect_unit_near_table(table_elem: etree._Element) -> int:
    """
    TABLE 인접 요소에서 단위 배수 탐지.

    우선순위:
      1. 표 자체 첫 행의 단위 셀 (가장 권위 있음)
      2. 표 바로 앞 요소부터 가까운 순서로 탐색한 '명시적 단위 선언'(원 포함)
    '단위: 원' 선언도 채택한다 → 원 단위 표 앞에 다른 표의 천원 선언이 있어도
    가장 가까운 선언(=그 표의 단위)을 쓰므로 ×1000 오적용을 막는다.
    """
    from parser.common.amount_normalizer import detect_unit_declaration

    # 1. 표 자체 첫 행 (가장 권위 있는 단위 선언)
    first_tr = table_elem.find(".//TR")
    if first_tr is not None:
        decl = detect_unit_declaration(''.join(first_tr.itertext()))
        if decl is not None:
            return decl

    parent = table_elem.getparent()
    if parent is None:
        return 1

    siblings = list(parent)
    try:
        idx = siblings.index(table_elem)
    except ValueError:
        return 1

    # 2. table 앞 5개 요소를 가까운 순서(역순)로 탐색 — 가장 가까운 단위 선언 채택
    for s in reversed(siblings[max(0, idx - 5):idx]):
        tag = s.tag.upper() if isinstance(s.tag, str) else ""
        if tag in ("P", "TABLE"):
            decl = detect_unit_declaration(''.join(s.itertext()))
            if decl is not None:
                return decl

    return 1
