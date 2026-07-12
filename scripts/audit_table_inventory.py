"""Phase 0 — 전수 인벤토리 감사 (PRD 11).

DART 정기보고서 본문에 등장하는 모든 숫자 표를 항목 단위로 분류하여
'수집됨/미수집/수집불가' 매트릭스를 만든다. 두 pass 로 구성:

  --pass1  : SQL 정량 — fact_v2 미매핑 acode 상위빈도, 미승격 캐노니컬별 행수·커버율,
             기존 부가 테이블 커버리지. (수 분)
  --pass2  : 표본 심층 — 층화표본 기업 × 3개년 raw XML 을 순회하며 모든 TABLE 을
             expand_table_grid 로 그리드화, 수치표만 골라 직전 헤딩을 ITEM_STATUS
             룰북으로 분류. (표본 크기에 따라 30~60분)

읽기 전용 — DB/파일 변경 없음. 기존 검증된 인프라(fin2.extract.biz_section)를 재사용한다.

usage:
    python scripts/audit_table_inventory.py --pass1
    python scripts/audit_table_inventory.py --pass2 --limit 10          # 인라인 검증
    python scripts/audit_table_inventory.py --pass2 --sample 300 --out scratchpad/audit.csv
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from collector.db import SessionLocal
from fin2.extract.biz_section import (
    _is_clean_number,
    _load_root,
    _looks_numeric,
    _tag,
    _text,
    expand_table_grid,
)
from fin2.standardize.rules import (
    _AMORT_CANON,
    _CAPEX_CANON,
    _DA_TOTAL_CANON,
    _DEP_CANON,
    DIRECT_MAP,
)
from fin2.taxonomy.concept_map import ACODE_TO_CANONICAL


# ════════════════════════════════════════════════════════════════════════
# ITEM_STATUS 룰북 — 정기보고서 헤딩 → 항목 유형 분류 (PRD 11 §4.2)
# ════════════════════════════════════════════════════════════════════════
# status: collected      — 이미 API/파서로 DB 적재됨
#         planned_phase_N — Phase N(2~5)이 다룰 예정
#         deferred        — 마스터 PRD 결정 5 보류(ROI 재검토)
#         not_collectible — 구조적으로 불가(순수 서술형 등)
#         unclassified    — 룰북 미등록(표본에서 새로 발견되면 여기로 — 이 Phase 의 진짜 발견)

@dataclass(frozen=True)
class ItemType:
    key: str                    # 내부 식별자
    label: str                  # 사람이 읽는 항목명
    section: str                # 보고서 절
    status: str                 # collected / planned_phase_N / deferred / not_collectible
    source: str                 # 최적 소스 힌트
    keywords: tuple[str, ...]   # 헤딩 매칭 키워드(부분일치)


# 순서 중요 — 더 구체적인 항목을 앞에 둔다(첫 매칭 채택).
RULEBOOK: tuple[ItemType, ...] = (
    # ── III. 재무에 관한 사항: 재무제표 본문 (collected via XBRL Track A/B) ──
    ItemType("bs", "재무상태표", "III.재무", "collected", "XBRL face",
             ("재무상태표", "대차대조표")),
    ItemType("is", "손익계산서", "III.재무", "collected", "XBRL face",
             ("손익계산서", "포괄손익계산서")),
    ItemType("cf", "현금흐름표", "III.재무", "collected", "XBRL face",
             ("현금흐름표",)),
    ItemType("sce", "자본변동표", "III.재무", "collected", "XBRL face(dimensional)",
             ("자본변동표",)),
    ItemType("summary_fin", "요약재무정보", "III.재무", "collected", "std_v2 파생",
             ("요약재무정보", "요약연결재무", "요약별도재무", "재무정보 요약")),

    # ── III. 재무제표 주석 ──
    ItemType("note_expense_nature", "비용의 성격별 분류", "III.재무-주석", "planned_phase_4",
             "주석 파서(Phase 4)", ("성격별 분류", "비용의 성격별", "성격별로 분류")),
    ItemType("note_da", "감가상각 주석", "III.재무-주석", "collected", "note.* 파서(부분)",
             ("감가상각비", "감가상각누계")),
    ItemType("note_segment", "영업부문 정보", "III.재무-주석", "deferred", "IFRS8 주석(보류)",
             ("영업부문", "부문정보", "부문별 정보", "사업부문 정보", "부문별 손익")),
    ItemType("note_borrowings", "차입금/사채 주석", "III.재무-주석", "deferred", "주석 파서(보류)",
             ("차입금", "장기차입", "단기차입", "사채", "차입약정", "차입금 및 사채")),
    ItemType("note_lease", "리스 주석", "III.재무-주석", "deferred", "부분(ROU) collected",
             ("리스부채", "리스료", "사용권자산", "운용리스", "금융리스")),
    ItemType("note_financial_instruments", "금융상품 주석", "III.재무-주석", "deferred",
             "주석 파서(보류)", ("금융상품", "공정가치", "금융위험", "위험관리",
                              "신용위험", "유동성위험", "시장위험", "자본위험", "이자율위험")),
    ItemType("note_receivables", "매출채권/대손 주석", "III.재무-주석", "deferred",
             "주석 파서(보류)", ("매출채권", "대손충당금", "대손상각", "대여금", "수취채권")),
    ItemType("note_provisions", "충당부채 주석", "III.재무-주석", "deferred", "주석 파서(보류)",
             ("충당부채", "복구충당")),
    ItemType("note_related_party", "특수관계자 거래", "III.재무-주석", "deferred",
             "주석 파서(보류)", ("특수관계자", "특수관계", "특수 관계자")),
    ItemType("note_sga_detail", "판매비와관리비 상세", "III.재무-주석", "deferred",
             "주석 파서(보류)", ("판매비와관리비", "판매비와 관리비", "판관비")),
    ItemType("note_inventory", "재고자산 상세", "III.재무-주석", "deferred", "주석 파서(보류)",
             ("재고자산",)),
    ItemType("note_ppe", "유형자산/무형자산 명세", "III.재무-주석", "deferred", "주석 파서(보류)",
             ("유형자산", "무형자산")),
    ItemType("note_tax", "법인세 주석", "III.재무-주석", "deferred", "주석 파서(보류)",
             ("법인세", "이연법인세", "유효세율")),
    ItemType("note_pension", "퇴직급여 주석", "III.재무-주석", "deferred", "부분(pension_liab)",
             ("퇴직급여", "확정급여", "순확정급여")),
    ItemType("note_contingency", "우발부채·약정", "III.재무-주석", "deferred", "주석 파서(보류)",
             ("우발부채", "약정사항", "지급보증", "담보제공", "견질")),
    ItemType("note_equity", "자본금/주식 주석", "III.재무-주석", "collected", "부분(capital 계정)",
             ("자본금", "주식발행초과금", "이익잉여금 처분", "이익잉여금의 변동", "이익잉여금 변동",
              "자본잉여금", "기타자본")),

    # ── III. 배당·자금조달 (planned_phase_2 / collected) ──
    ItemType("dividend", "배당에 관한 사항", "III.재무", "planned_phase_2",
             "alotMatter API(Phase 2)",
             ("배당에 관한", "배당정책", "주당 배당", "배당성향", "배당금 총액", "현금배당")),
    ItemType("fundraising", "증권 발행/자금조달", "III.재무", "collected",
             "capital_events(B2)",
             ("자금조달", "증권의 발행", "미상환 증권", "공모자금", "사모자금", "자금의 사용")),

    # ── II. 사업의 내용 ──
    ItemType("sales_result", "매출실적/판매실적", "II.사업", "planned_phase_3",
             "본문 표 파서(Phase 3)",
             ("매출실적", "판매실적", "매출 실적", "판매 실적", "매출유형", "수출 및 내수",
              "판매경로", "지역별 매출", "부문별 매출")),
    ItemType("order_backlog", "수주상황", "II.사업", "collected", "본문 표 파서(B1)",
             ("수주상황", "수주계약", "수주 현황", "수주잔고")),
    ItemType("capacity", "생산능력", "II.사업", "collected", "본문 표 파서(B4)",
             ("생산능력", "생산 능력")),
    ItemType("output", "생산실적", "II.사업", "collected", "본문 표 파서(B4)",
             ("생산실적", "생산 실적")),
    ItemType("utilization", "가동률", "II.사업", "collected", "본문 표 파서(B4)",
             ("가동률", "가동 현황", "가동율")),
    ItemType("raw_material", "원재료/매입 현황", "II.사업", "deferred", "본문 표 파서(보류)",
             ("원재료", "주요 매입", "매입현황", "원재료 가격", "주요 원재료")),
    ItemType("facilities", "생산설비/투자", "II.사업", "deferred", "본문 표 파서(보류)",
             ("생산설비", "설비투자", "설비 현황", "신규시설투자", "유형자산 현황")),
    ItemType("product_price", "주요제품/가격변동", "II.사업", "deferred", "본문 표 파서(보류)",
             ("주요 제품", "주요제품", "제품 가격", "가격변동", "주요 서비스")),
    ItemType("rd_activity", "연구개발활동/비용", "II.사업", "collected", "rd_note 파서",
             ("연구개발비용", "연구개발 비용", "연구개발실적", "연구개발 활동", "연구개발비")),
    ItemType("derivatives", "파생거래/위험관리", "II.사업", "deferred", "본문 표 파서(보류)",
             ("파생상품 거래", "파생거래", "환위험", "위험관리 정책")),

    # ── VII. 주주에 관한 사항 (collected via B3) ──
    ItemType("major_shareholder", "최대주주 현황", "VII.주주", "collected", "hyslrSttus(B3)",
             ("최대주주", "최대 주주", "특수관계인", "5% 이상")),
    ItemType("shareholder_change", "최대주주 변동", "VII.주주", "collected", "hyslrChgSttus(B3)",
             ("최대주주 변동", "주주 변동", "최대주주등의 변동")),
    ItemType("retail_ownership", "소액주주 현황", "VII.주주", "collected", "mrhlSttus(B3)",
             ("소액주주", "소액 주주", "주식 소유현황", "주식소유현황")),
    ItemType("voting", "의결권 현황", "I.회사개요", "not_collectible", "서술/표 혼재",
             ("의결권", "의결권 있는 주식")),

    # ── VIII. 임원 및 직원 (planned_phase_2 / collected) ──
    ItemType("exec_status", "임원 현황", "VIII.임직원", "collected", "exctvSttus(B3)",
             ("임원 현황", "임원현황", "등기임원", "미등기임원")),
    ItemType("employee", "직원 현황", "VIII.임직원", "planned_phase_2", "empSttus API(Phase 2)",
             ("직원 현황", "직원현황", "직원의 현황", "종업원 현황", "평균 근속", "1인평균 급여",
              "직원 등 현황")),
    ItemType("exec_pay", "임원 보수", "VIII.임직원", "planned_phase_2",
             "hmvAudit/indvdlByPay(Phase 2)",
             ("보수총액", "보수 총액", "이사·감사", "이사ㆍ감사", "개인별 보수", "보수지급금액",
              "임원의 보수", "5억원 이상")),

    # ── IX. 계열회사 / 타법인 출자 (planned_phase_2) ──
    ItemType("other_investment", "타법인 출자현황", "IX.계열", "planned_phase_2",
             "otrCprInvstmntSttus API(Phase 2)",
             ("타법인 출자", "타법인출자", "출자현황", "출자 현황", "계열회사 현황")),

    # ── I. 회사의 개요 (일부 collected — 자본금/주식수) ──
    ItemType("capital_change", "자본금 변동사항", "I.회사개요", "collected", "capital_events(B2)",
             ("자본금 변동", "자본금의 변동", "증자(감자)", "자본금 현황")),
    ItemType("total_shares", "주식의 총수", "I.회사개요", "collected", "shares 파서",
             ("주식의 총수", "발행할 주식", "발행주식의 총수", "미발행주식")),
    ItemType("company_history", "회사 연혁/개요", "I.회사개요", "not_collectible", "서술형",
             ("회사의 연혁", "연혁", "회사의 개요", "설립", "본점 소재지")),

    # ── IV. MD&A (서술형) ──
    ItemType("mda", "경영진단 및 분석의견", "IV.MD&A", "not_collectible", "서술형",
             ("경영진단", "경영진의 진단", "분석의견", "재무상태 및 영업실적")),

    # ── V. 감사 (deferred / not_collectible) ──
    ItemType("audit_fee", "외부감사 보수/시간", "V.감사", "deferred", "표 파서(보류)",
             ("감사보수", "감사 보수", "감사시간", "감사계약", "감사인")),
    ItemType("internal_control", "내부회계관리제도", "V.감사", "not_collectible", "서술형",
             ("내부회계관리", "내부통제", "회계관리·운영조직", "회계관리 운영조직")),

    # ── VI. 이사회 등 기관 (not_collectible 서술 위주) ──
    ItemType("board", "이사회/지배구조", "VI.기관", "not_collectible", "서술/표 혼재",
             ("이사회", "사외이사", "감사위원회", "주주총회")),

    # ── X. 대주주 등과의 거래 (deferred) ──
    ItemType("related_party_txn", "대주주 등과의 거래", "X.거래", "deferred", "표 파서(보류)",
             ("대주주 등과의 거래", "대주주와의 거래", "특수관계인과의 거래")),
)

_HEADING_MAX_LEN = 60
# 헤딩 후보 판정 — 순번 소제목(가./1./(1)/①/Ⅰ.) 또는 TITLE 태그 또는 룰북 키워드 포함
_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:[가-힣]\s*\.|\d+\s*[.)]|\(\s*\d+\s*\)|[①-⑳]|[Ⅰ-Ⅻ]\s*\.|[IVX]+\s*\.)")


def classify_heading(heading: str) -> ItemType | None:
    """헤딩 텍스트를 룰북 항목으로 분류(첫 매칭). 미매칭은 None(=unclassified).
    한글 보고서는 띄어쓰기가 들쭉날쭉("요약 연결재무정보" vs "요약연결재무")이라
    양쪽 공백을 모두 제거하고 부분일치로 매칭한다."""
    if not heading:
        return None
    norm = re.sub(r"\s+", "", heading)
    for item in RULEBOOK:
        for kw in item.keywords:
            if kw.replace(" ", "") in norm:
                return item
    return None


# 비정보성 마커 — 표 내부의 기간/순번 표식(진짜 절 캡션 아님). 이런 요소는 "직전 헤딩"으로
# 채택하지 않고 건너뛴다 → 주석 하위표가 상위 주석 제목(분류가능)에 귀속되게 함.
_PERIOD_MARKER_RE = re.compile(
    r"^[①-⑳()\d.)\s]*\s*(당기|전기|당반기|전반기|당분기|전분기)\s*(말|초)?\s*$")
_BARE_NUMBERING_RE = re.compile(r"^[①-⑳()\d.)\s·]+$")


def _is_substantive(t: str) -> bool:
    """실제 절/표 캡션인지 — 순수 기간마커·순번마커는 캡션이 아니라 배제."""
    if _PERIOD_MARKER_RE.match(t) or _BARE_NUMBERING_RE.match(t):
        return False
    return True


def _is_heading_candidate(el) -> bool:
    """이 요소가 표의 캡션/소제목이 될 만한지(짧은 텍스트 + 순번패턴/TITLE/키워드).
    순수 기간마커(① 당기 등)·순번마커는 비정보성이라 배제한다."""
    tag = _tag(el)
    if tag not in ("SPAN", "P", "TITLE", "STITLE", "TE"):
        return False
    t = _text(el)
    if not t or len(t) > _HEADING_MAX_LEN:
        return False
    if not _is_substantive(t):
        return False
    if tag in ("TITLE", "STITLE"):
        return True
    if _NUMBERED_HEADING_RE.match(t):
        return True
    return classify_heading(t) is not None


# ════════════════════════════════════════════════════════════════════════
# PASS 1 — SQL 정량
# ════════════════════════════════════════════════════════════════════════

def _unpromoted_canonicals() -> list[str]:
    """concept_map 이 매핑하지만 std_v2 wide 컬럼으로 승격되지 않은 캐노니컬 집합.
    하드코딩 대신 DIRECT_MAP(직접매핑) + 합산규칙 소비분을 제외해 동적 산출."""
    promoted = set(DIRECT_MAP.keys())
    for grp in (_CAPEX_CANON, _DEP_CANON, _AMORT_CANON, _DA_TOTAL_CANON):
        promoted |= set(grp)
    all_canon = set(ACODE_TO_CANONICAL.values())
    return sorted(all_canon - promoted)


def run_pass1() -> None:
    session = SessionLocal()
    try:
        print("=" * 78)
        print("PASS 1 — SQL 정량 인벤토리")
        print("=" * 78)

        # (1) 미매핑 acode 상위 빈도
        print("\n[1] fact_v2 미매핑 acode 상위 30 (canonical_account IS NULL)")
        rows = session.execute(text("""
            SELECT acode, COUNT(*) AS n
            FROM fact_v2
            WHERE canonical_account IS NULL
            GROUP BY acode ORDER BY n DESC LIMIT 30
        """)).fetchall()
        for acode, n in rows:
            print(f"    {n:>10,}  {acode[:70]}")

        # (2) 미승격 캐노니컬별 커버리지
        print("\n[2] 미승격 캐노니컬 커버리지 (당기·비차원, corp×fy DISTINCT)")
        unpromoted = _unpromoted_canonicals()
        print(f"    (동적 산출: 매핑 {len(set(ACODE_TO_CANONICAL.values()))}종 중 "
              f"미승격 {len(unpromoted)}종)")
        cov = session.execute(text("""
            SELECT canonical_account,
                   COUNT(*) AS n_rows,
                   COUNT(DISTINCT corp_code || '|' || report_fiscal_year) AS corp_fy
            FROM fact_v2
            WHERE canonical_account = ANY(:cs)
              AND col_index = 0 AND NOT is_dimensional AND amount_won IS NOT NULL
            GROUP BY canonical_account ORDER BY corp_fy DESC
        """), {"cs": unpromoted}).fetchall()
        print(f"    {'canonical':<34}{'행수':>12}{'corp×fy':>12}")
        seen = set()
        for canon, n_rows, corp_fy in cov:
            seen.add(canon)
            print(f"    {canon:<34}{n_rows:>12,}{corp_fy:>12,}")
        empty = [c for c in unpromoted if c not in seen]
        if empty:
            print(f"    (데이터 0행 캐노니컬 {len(empty)}종): {', '.join(empty)}")

        # (3) 기존 부가 테이블 커버리지
        print("\n[3] 기존 부가 테이블 커버리지")
        tbls = [
            ("biz_metrics", "corp_code"),
            ("order_backlog", "corp_code"),
            ("executives", "corp_code"),
            ("capital_events", "corp_code"),
            ("major_shareholders", "corp_code"),
            ("regulatory_events", "corp_code"),
            ("stock_prices", "stock_code"),
        ]
        for tbl, corpcol in tbls:
            try:
                r = session.execute(text(
                    f"SELECT COUNT(*) AS n, COUNT(DISTINCT {corpcol}) AS c FROM {tbl}"
                )).fetchone()
                print(f"    {tbl:<24} 행 {r[0]:>12,}   기업 {r[1]:>8,}")
            except Exception as e:
                session.rollback()
                print(f"    {tbl:<24} (조회 실패: {str(e)[:40]})")

        print("\nPASS 1 완료.")
    finally:
        session.close()


# ════════════════════════════════════════════════════════════════════════
# PASS 2 — 표본 심층 스캔
# ════════════════════════════════════════════════════════════════════════

@dataclass
class ScanStats:
    files_scanned: int = 0
    files_failed: int = 0
    numeric_tables: int = 0
    item_counts: Counter = field(default_factory=Counter)          # item.key -> table 수
    item_corps: dict = field(default_factory=lambda: defaultdict(set))  # item.key -> {corp}
    unclassified: Counter = field(default_factory=Counter)          # heading -> 빈도


def _table_is_numeric(grid: list[list[str]]) -> bool:
    """셀 중 숫자로 파싱되는 비율 ≥30% 면 수치표로 판정."""
    cells = [c for row in grid for c in row if c and c.strip()]
    if len(cells) < 4:
        return False
    numeric = sum(1 for c in cells if _looks_numeric(c) or _is_clean_number(c))
    return numeric / len(cells) >= 0.30


def scan_file(file_path: Path, corp_code: str, stats: ScanStats) -> None:
    """파일 하나를 순회하며 각 수치표를 직전 헤딩으로 분류해 stats 누적."""
    root = _load_root(file_path)
    if root is None:
        stats.files_failed += 1
        return
    stats.files_scanned += 1

    elements = list(root.iter())
    last_heading = ""
    seen_tables = set()
    for el in elements:
        if _is_heading_candidate(el):
            last_heading = re.sub(r"\s+", " ", _text(el)).strip()
            continue
        if _tag(el) != "TABLE" or id(el) in seen_tables:
            continue
        seen_tables.add(id(el))
        try:
            grid = expand_table_grid(el)
        except Exception:
            continue
        if not grid or not _table_is_numeric(grid):
            continue
        stats.numeric_tables += 1
        item = classify_heading(last_heading)
        if item is None:
            if last_heading:
                stats.unclassified[last_heading[:_HEADING_MAX_LEN]] += 1
        else:
            stats.item_counts[item.key] += 1
            stats.item_corps[item.key].add(corp_code)


def _stratified_sample(session, n: int) -> list[tuple[str, str]]:
    """시장 × 업종대분류 × 시총3분위 층화표본 ~n 사. (corp_code, corp_name) 반환.
    시총은 stock_prices 최신값이 없을 수 있어 std_v2 revenue 를 규모 프록시로 사용."""
    rows = session.execute(text("""
        WITH latest_rev AS (
            SELECT DISTINCT ON (corp_code) corp_code, revenue
            FROM std_financials_v2
            WHERE statement_type = 'consolidated' AND fiscal_period = 'FY'
                  AND NOT is_stub AND NOT is_discrete AND revenue IS NOT NULL
            ORDER BY corp_code, fiscal_year DESC
        )
        SELECT c.corp_code, c.corp_name, c.market,
               COALESCE(LEFT(c.induty_code, 2), '00') AS induty2,
               COALESCE(lr.revenue, 0) AS rev
        FROM corporations c
        LEFT JOIN latest_rev lr ON lr.corp_code = c.corp_code
        WHERE c.is_active AND c.stock_code IS NOT NULL
              AND c.coverage_class = 'periodic'
    """)).fetchall()
    # 층 구성: (market, induty2, size_tercile)
    by_rev = sorted(rows, key=lambda r: r[4])
    third = max(1, len(by_rev) // 3)
    tercile = {}
    for i, r in enumerate(by_rev):
        tercile[r[0]] = 0 if i < third else (1 if i < 2 * third else 2)
    strata: dict = defaultdict(list)
    for r in rows:
        strata[(r[2], r[3], tercile[r[0]])].append((r[0], r[1]))
    rng = random.Random(42)
    out: list[tuple[str, str]] = []
    keys = list(strata.keys())
    rng.shuffle(keys)
    # 각 층에서 비례 추출(최소 1)
    per = max(1, n // max(1, len(keys)))
    for k in keys:
        bucket = strata[k]
        rng.shuffle(bucket)
        out.extend(bucket[:per])
        if len(out) >= n:
            break
    return out[:n]


def _sample_files(session, corp_code: str) -> list[Path]:
    """corp 의 사업보고서(annual) 파일 — 최신/2020/2016 최대 3개."""
    rows = session.execute(text("""
        SELECT f.fiscal_year, dt.file_path
        FROM filings f
        JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
        WHERE f.corp_code = :c AND f.report_type = 'annual'
              AND dt.status = 'completed' AND dt.file_path IS NOT NULL
              AND dt.file_type = 'xml'
        ORDER BY f.fiscal_year DESC
    """), {"c": corp_code}).fetchall()
    if not rows:
        return []
    by_year = {r[0]: r[1] for r in rows}
    picks: list[Path] = []
    latest = max(by_year)
    for yr in (latest, 2020, 2016):
        if yr in by_year:
            p = Path(by_year[yr])
            if p.exists():
                picks.append(p)
    # 중복 제거(연도 겹칠 때)
    seen, uniq = set(), []
    for p in picks:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _all_corps(session) -> list[tuple[str, str]]:
    """전 활성 보통주(정기보고 대상) — 층화 없이 전수. --all 용."""
    rows = session.execute(text("""
        SELECT corp_code, corp_name FROM corporations
        WHERE is_active AND stock_code IS NOT NULL AND coverage_class = 'periodic'
        ORDER BY corp_code
    """)).fetchall()
    return [(r[0], r[1]) for r in rows]


def run_pass2(sample: int, limit: int | None, out_csv: str | None,
              all_corps: bool = False, shard: str | None = None) -> None:
    session = SessionLocal()
    try:
        print("=" * 78)
        mode = "전수(--all)" if all_corps else f"층화표본 sample={sample}"
        print(f"PASS 2 — 표본 심층 스캔 ({mode}, limit={limit}, shard={shard})")
        print("=" * 78)
        corps = _all_corps(session) if all_corps else _stratified_sample(session, sample)
        if shard:
            # 기존 verify_corp_sequential.py 컨벤션과 동일: --shard a/n → i % n == a.
            # corp_code 오름차순 리스트라 각 샤드는 서로소(disjoint) — 결과 CSV 는 단순 합산으로 병합 가능.
            a, n = (int(x) for x in shard.split("/"))
            corps = [c for i, c in enumerate(corps) if i % n == a]
        if limit:
            corps = corps[:limit]
        print(f"표본 기업 {len(corps)}사")

        stats = ScanStats()
        for i, (corp_code, corp_name) in enumerate(corps, 1):
            files = _sample_files(session, corp_code)
            for fp in files:
                scan_file(fp, corp_code, stats)
            if i % 25 == 0 or i == len(corps):
                print(f"  [{i}/{len(corps)}] {corp_name[:20]:<20} "
                      f"파일 {stats.files_scanned} · 수치표 {stats.numeric_tables}")

        # ── 결과 요약 ──
        print("\n" + "=" * 78)
        print("항목별 출현 (수치표 수 / 등장 기업 수)")
        print("=" * 78)
        by_status: dict = defaultdict(list)
        item_by_key = {it.key: it for it in RULEBOOK}
        for key, cnt in stats.item_counts.most_common():
            it = item_by_key[key]
            by_status[it.status].append((it, cnt, len(stats.item_corps[key])))
        for status in ("collected", "planned_phase_2", "planned_phase_3",
                       "planned_phase_4", "deferred", "not_collectible"):
            items = by_status.get(status, [])
            if not items:
                continue
            print(f"\n[{status}]")
            for it, cnt, ncorp in items:
                print(f"    {it.label:<24}{it.section:<16} 표 {cnt:>6}  기업 {ncorp:>5}")

        print("\n" + "=" * 78)
        print(f"미분류(unclassified) 헤딩 상위 40 — 룰북 미등록 (총 {len(stats.unclassified)}종)")
        print("=" * 78)
        for heading, cnt in stats.unclassified.most_common(40):
            print(f"    {cnt:>5}  {heading}")

        n_files = stats.files_scanned + stats.files_failed
        print(f"\n스캔 파일 {stats.files_scanned} (실패 {stats.files_failed}) · "
              f"수치표 {stats.numeric_tables} · "
              f"분류 {sum(stats.item_counts.values())} · "
              f"미분류 {sum(stats.unclassified.values())}")
        classified = sum(stats.item_counts.values())
        total_tbl = classified + sum(stats.unclassified.values())
        if total_tbl:
            print(f"분류율 {classified / total_tbl * 100:.1f}%")

        if out_csv:
            _write_csv(out_csv, stats, item_by_key)
            print(f"\nCSV 저장: {out_csv}")
    finally:
        session.close()


def _write_csv(path: str, stats: ScanStats, item_by_key: dict) -> None:
    parent = Path(path).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["kind", "key", "label", "section", "status", "source",
                    "table_count", "corp_count"])
        # 병합(--merge)용 요약 행 — corp_count 열을 재사용해 스칼라 값 보존.
        w.writerow(["summary", "files_scanned", "", "", "", "", "", stats.files_scanned])
        w.writerow(["summary", "files_failed", "", "", "", "", "", stats.files_failed])
        w.writerow(["summary", "numeric_tables", "", "", "", "", "", stats.numeric_tables])
        for key, cnt in stats.item_counts.most_common():
            it = item_by_key[key]
            w.writerow(["classified", it.key, it.label, it.section, it.status,
                        it.source, cnt, len(stats.item_corps[key])])
        for heading, cnt in stats.unclassified.most_common():
            w.writerow(["unclassified", "", heading, "", "unclassified", "", cnt, ""])


def merge_csvs(paths: list[str], out_csv: str) -> None:
    """--shard 로 나눠 돌린 여러 CSV 를 합산한다. 샤드는 corp_code 로 서로소이므로
    table_count/corp_count 단순 합산이 정확(같은 기업이 두 샤드에 겹치지 않음)."""
    item_by_key = {it.key: it for it in RULEBOOK}
    classified: dict[str, int] = defaultdict(int)     # key -> table_count
    corp_counts: dict[str, int] = defaultdict(int)     # key -> corp_count
    unclassified: dict[str, int] = defaultdict(int)    # heading -> count
    summary: dict[str, int] = defaultdict(int)         # files_scanned 등

    for p in paths:
        with open(p, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["kind"] == "summary":
                    summary[row["key"]] += int(row["corp_count"] or 0)
                elif row["kind"] == "classified":
                    classified[row["key"]] += int(row["table_count"] or 0)
                    corp_counts[row["key"]] += int(row["corp_count"] or 0)
                elif row["kind"] == "unclassified":
                    unclassified[row["label"]] += int(row["table_count"] or 0)

    parent = Path(out_csv).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["kind", "key", "label", "section", "status", "source",
                    "table_count", "corp_count"])
        for name, val in summary.items():
            w.writerow(["summary", name, "", "", "", "", "", val])
        for key, cnt in sorted(classified.items(), key=lambda kv: -kv[1]):
            it = item_by_key.get(key)
            if it is None:
                continue
            w.writerow(["classified", it.key, it.label, it.section, it.status,
                        it.source, cnt, corp_counts[key]])
        for heading, cnt in sorted(unclassified.items(), key=lambda kv: -kv[1]):
            w.writerow(["unclassified", "", heading, "", "unclassified", "", cnt, ""])

    n_files = summary.get("files_scanned", 0)
    n_tables = summary.get("numeric_tables", 0)
    n_classified = sum(classified.values())
    n_unclassified = sum(unclassified.values())
    total = n_classified + n_unclassified
    print(f"병합 완료: {len(paths)}개 샤드 → {out_csv}")
    print(f"  파일 {n_files} · 수치표 {n_tables} · 분류 {n_classified} · 미분류 {n_unclassified}")
    if total:
        print(f"  분류율 {n_classified / total * 100:.1f}%")


# ════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 0 전수 인벤토리 감사")
    ap.add_argument("--pass1", action="store_true", help="SQL 정량 인벤토리")
    ap.add_argument("--pass2", action="store_true", help="표본 심층 스캔")
    ap.add_argument("--sample", type=int, default=300, help="층화표본 기업 수(pass2)")
    ap.add_argument("--all", action="store_true",
                    help="전 활성 보통주 전수 스캔(층화표본 대신, 수 시간)")
    ap.add_argument("--shard", help="병렬 샤딩 a/n (i %% n == a) — 여러 터미널에서 --all 과 병행,"
                                     " 완료 후 --merge 로 합산")
    ap.add_argument("--limit", type=int, default=None, help="기업 수 상한(인라인 검증용)")
    ap.add_argument("--out", type=str, default=None, help="pass2 결과 CSV 경로(디렉터리 자동생성)")
    ap.add_argument("--merge", nargs="+", metavar="CSV", default=None,
                    help="샤드별 CSV 여러 개를 합산(다른 옵션과 병행 불가, --out 필수)")
    args = ap.parse_args()

    if args.merge:
        if not args.out:
            ap.error("--merge 는 --out 필수(병합 결과 저장 경로)")
        merge_csvs(args.merge, args.out)
        return

    if not (args.pass1 or args.pass2):
        ap.error("--pass1 또는 --pass2 중 하나 이상 지정")
    if args.pass1:
        run_pass1()
    if args.pass2:
        run_pass2(args.sample, args.limit, args.out, all_corps=args.all, shard=args.shard)


if __name__ == "__main__":
    main()
