"""
Track B 텍스트 추출기 (fin2 E-레이어 폴백).

ACONTEXT/ACODE 가 없는 DART 정기보고서(분기/반기 다수, 구형 연간)에서
한국어 계정명+테이블 텍스트로 fact_v2 행을 추출한다.

설계:
  - 기존 leaf 모듈(section_detector/table_extractor/account_mapper/amount_normalizer)
    재사용. **레거시 오케스트레이터(dart_xml_parser)에 의존하지 않음** → P6 폐기 대비.
  - XBRL 과 달리 권위있는 구조(ADECIMAL/ACONTEXT)가 없다. **그렇다고 추측하지 않는다**
    (2026-07-17 재설계): 연결/별도·BS/IS/CF 는 **DART 섹션**에서 확정하고, 단위는 그 표가
    **명시 선언한 것만** 쓴다. 확정 못 하는 표는 채우지 않고 **통째로 건너뛴다**(보류).
    결측 > 오염 — 추측으로 채운 값은 정상 행과 구분되지 않아 사후 제거가 불가능하다.
  - **무손실**: 매핑 실패(canonical NULL)해도 행을 버리지 않고 raw 계정명(acode)과 함께
    저장 → 추후 account_maps 보강 후 재파싱 없이 복구 가능(레거시는 미매핑 행 폐기).
  - **provenance 기록**: section_kind / mapping_stage / mapping_confidence / unit_source 를
    행마다 남긴다 → "무엇을 근거로 이 값이 됐는지"가 DB 에서 SQL 로 검증 가능.
  - fact_v2 정합:
      acode              = 정규화된 한국어 계정명(텍스트 레벨 source 개념)
      canonical_account  = account_mapper 결과(텍스트의 concept_map 역할), 미매핑 NULL
      adecimal           = 단위 배수 역산(amount_won = 표기값 × 10^(-adecimal) 불변식 유지)
      acontext_raw       = 합성 토큰 "text:..."(원 ACONTEXT 없음 → uq_fact_v2_cell 유지)
      context_parsed     = False(합성)

run.py extract2 에서 Track A(xbrl)가 0행이면 자동 폴백으로 호출.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from loguru import logger

from parser.common.account_mapper import get_mapper, MappingResult
from parser.common.amount_normalizer import normalize_account_name, detect_unit_declaration
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_tables_to_dart_sections, table_direct_rows,
    SEC_CONSOL_FS, SEC_SEP_FS,
)
from parser.xml.table_extractor import extract_rows
from fin2.extract.xbrl import ExtractedFact
from fin2.extract.statement_titles import (
    title_text, classify_statement_in_body_section, SECTION_CODE_OF,
)

# 섹션 코드 → (basis, period_kind)
_SECTION_META = {
    "BS_C": ("consolidated", "instant"),
    "IS_C": ("consolidated", "duration"),
    "CF_C": ("consolidated", "duration"),
    "BS_S": ("separate", "instant"),
    "IS_S": ("separate", "duration"),
    "CF_S": ("separate", "duration"),
    # 자본변동표 — 계층2 전용. period_kind=None: SCE 는 instant(잔액)와 duration(변동)이 한 표에
    # 섞여 행마다 다르므로 표 단위로 주장하지 않는다(계층3 이 행에서 판단).
    "SCE_C": ("consolidated", None),
    "SCE_S": ("separate", None),
}

# 보고서 기간(fiscal_period) → fact_v2 period_type
_PERIOD_TYPE = {"FY": "FY", "H1": "FH", "Q1": "FQ", "Q3": "FQ", "Q2": "FQ"}


def _adecimal_from_unit(unit: int) -> int:
    """단위 배수 → ADECIMAL 역산. 1→0, 1000→-3, 1000000→-6. (amount_won 불변식 유지)"""
    if unit <= 1:
        return 0
    return -int(round(math.log10(unit)))


_CUM_RE = re.compile(r"누적|누계")
_THREE_M_RE = re.compile(r"3개월|3 개월|삼개월")


def _interim_cumulative_cols(table) -> dict[int, int] | None:
    """
    반기/3분기 IS·CF 표의 2단 헤더(제N기 × [3개월|누적])에서 **누적 금액컬럼만** 골라
    {amount_position: period_offset} 을 반환한다. 누적/3개월 구분이 없으면 None(현 동작 유지).

    배경: Track B 가 위치순으로 col_index 를 매겨, [당기3개월, 당기누적, 전기3개월, 전기누적]
    레이아웃에서 당기3개월(Q)을 당기누적으로 오라벨하고 연도까지 밀렸음. 헤더의 '누적' 토큰
    위치로 누적컬럼만 추출하면 표준 반기/누적 지표가 정확해진다.

    amount_position 은 데이터행 금액셀(라벨 제외)의 0-base 인덱스. period_offset 은
    0=당기, 1=전기, ... (누적컬럼 등장 순서).
    """
    from parser.xml.table_extractor import _get_cells
    for tr in table.findall(".//TR"):
        cells = _get_cells(tr)
        joined = "".join(cells)
        if not _CUM_RE.search(joined) or not _THREE_M_RE.search(joined):
            continue  # 2단(3개월/누적) 헤더가 아니면 대상 아님
        # 라벨/빈 선두 셀 제거 → 금액컬럼 헤더와 정렬
        sub = list(cells)
        while sub and not (_CUM_RE.search(sub[0]) or _THREE_M_RE.search(sub[0])):
            sub.pop(0)
        cum = [i for i, c in enumerate(sub) if _CUM_RE.search(c)]
        if not cum:
            continue
        return {pos: off for off, pos in enumerate(cum)}
    return None


def _detect_fin_type(root) -> str:
    """SUMMARY EXTRACTION 의 FIN_TYPE (A=연결있음/B=별도만). 없으면 'A' 가정."""
    for ex in root.findall(".//EXTRACTION"):
        if ex.get("ACODE", "") == "FIN_TYPE":
            return (ex.text or "A").strip() or "A"
    return "A"


def _synth_acontext(basis: str, period_kind: str, col_idx: int, ctx_fy: int | None,
                    stmt: str = "") -> str:
    """텍스트 셀의 합성 컨텍스트 토큰(고유성 키). 원 ACONTEXT 부재를 명시.

    ★ stmt(BS/IS/CF) 포함: 같은 계정명(acode)이 손익계산서와 현금흐름표 양쪽에 등장하는 경우
    (예 '당기순이익(손실)' = IS 총당기순이익 + CF 간접법 시작라인)가 둘 다 period_kind='duration'
    이라 stmt 없이는 acontext_raw 가 충돌 → uq_fact_v2_cell 에서 한쪽(주로 IS net_income)이 소실.
    stmt 를 키에 포함해 IS/CF 셀을 분리한다(BS 는 'instant'라 기존에도 분리됐으나 일관성 위해 포함)."""
    return f"text:{stmt}:{basis[:3]}:{'e' if period_kind == 'instant' else 'd'}:c{col_idx}:{ctx_fy}"


def _canonical_of(mapping: MappingResult) -> str | None:
    """매핑 결과 → 적재할 canonical. **퍼지 매치는 canonical 을 주지 않는다**(추측 금지).

    퍼지(Stage 3)는 '포함 관계면 0.90~0.99' · 'Jaro-Winkler ≥ 0.88' 로 **닮았다는 이유만으로**
    표준계정을 부여한다. 부분포함은 사실상 무조건 승리라 과잉매핑이 기본값이고, account_mapper 의
    가드 6종(EBT·포괄손익귀속·지분법·계속영업·영업외·주당)이 전부 **사고 후 retrofit** 이라는 것이
    그 증거다 — 가드는 이미 터진 오매핑만 막을 뿐 아직 안 터진 것은 그대로 통과한다.

    ⟹ exact/normalized(사전 일치)와 guard(명시 규칙)만 canonical 을 갖는다.
    행 자체는 버리지 않는다(무손실 원칙): canonical 이 없어도 acode 원문 + mapping_stage='fuzzy'
    로 남으므로 alias 보강 후 **재파싱 없이 승격**할 수 있고, 그때까지 소비계층은 이 행을 보지
    못한다(canonical NULL = build 의 수집 대상 아님).

    ── ★ 이걸 켠 대가와 갚는 법 (2026-07-17 실측, 2015+ 무작위 287보고서) ──────────────
    퍼지는 두 가지 일을 **동시에** 하고 있었다. 끄면 둘 다 멈춘다:

      (B) **과잉매핑** — 이번 재구축의 표적. 없어지는 게 정답:
          '금융부채'→bs.short_term_debt · '기타무형자산'→bs.intangibles(무형자산의 부분집합!) ·
          '매출채권 및 기타유동채권'→bs.trade_receivables · 'I. 현금및예치금'→bs.cash
          (뒤 둘은 _FUZZY_BLOCK 의 '현금및예적금' 과 **같은 계열**의 합산성 라벨이다).

      (A) **정당한 표기변형 구제** — alias 미등록이라 퍼지로만 붙던 것. 이건 **빚**이다:
          '법인세비용(수익)'(alias='법인세비용(이익)') · '판매비와일반관리비'(alias='판매비와관리비')
          · '경상연구개발비'(alias='연구개발비') · '지배기업의 소유주에게 귀속되는 당기순이익(손실)'
          ⟹ 실측 **287건 중 214건(74.6%)** 에서 std_v2 소비 canonical 이 사라진다:
             is.controlling_ni 130 · bs.trade_payables 70 · bs.trade_receivables 64 ·
             bs.controlling_equity 54 · is.tax_expense 47 · is.net_income 25 …

    (A)는 **Phase C 패턴루프에서 account_maps alias 승격으로 갚는다**(값을 손으로 넣는 게 아니라
    파서를 고친다 — 계획 §2 원칙 4). 갚기 전에는 커버리지가 크게 빈다: **재구축 결과를 DB 에
    반영하기 전에 반드시 (A) 승격을 끝낼 것.** 작업목록은 이제 SQL 로 뽑을 수 있다 —
    `SELECT acode, count(*) FROM fact_v2 WHERE mapping_stage='fuzzy' GROUP BY 1 ORDER BY 2 DESC`
    (이 stage 기록이 없던 게 애초에 (A)/(B)를 구분 못 하던 이유였다).
    """
    if mapping.stage == "fuzzy":
        return None
    if mapping.account_code.startswith("unknown."):
        return None
    return mapping.account_code


def _row_to_fact(
    *, row, col_idx, amount, basis, period_kind, mapping: MappingResult,
    corp_code, rcept_no, report_fiscal_year, report_fiscal_period,
    fiscal_period, unit, fs_type, section_kind,
) -> ExtractedFact:
    ctx_fy = report_fiscal_year - col_idx
    canonical = _canonical_of(mapping)
    is_cumulative = period_kind == "duration" and fiscal_period != "FY"
    acode = (normalize_account_name(row.account_name) or row.account_name)[:120]
    return ExtractedFact(
        corp_code=corp_code,
        rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year,
        report_fiscal_period=report_fiscal_period,
        acode=acode,
        basis=basis,
        context_fiscal_year=ctx_fy,
        col_index=col_idx,
        period_kind=period_kind,
        period_type=_PERIOD_TYPE.get(fiscal_period, "FY"),
        is_cumulative=is_cumulative,
        extra_dims=None,
        is_dimensional=False,
        adecimal=_adecimal_from_unit(unit),
        amount_won=amount,
        source_format="xml_text",
        source_ref=f"{fs_type}/{row.account_name[:80]}"[:180],
        acontext_raw=_synth_acontext(basis, period_kind, col_idx, ctx_fy, fs_type.split("_")[0]),
        context_parsed=False,
        canonical_account=canonical,
        # provenance: 이 행이 어느 DART 섹션에서 왔고, canonical 을 무슨 근거로 얻었고,
        # 단위를 어디서 읽었는지. 이 경로는 선언 단위만 통과시키므로 unit_source 는 항상 declared.
        section_kind=section_kind,
        mapping_stage=mapping.stage,
        mapping_confidence=mapping.confidence,
        unit_source="declared",
    )


def _detect_body_statement_tables(root, fin_type: str,
                                  include_sce: bool = False) -> dict[str, list[tuple]]:
    """**DART 섹션 기반 본문표 식별**(2026-07-17 재설계).

    `2.연결재무제표` / `4.재무제표` 섹션 **내부 표만** 본문 후보로 삼는다. 주석·요약은
    다른 섹션이므로 **후보에 진입조차 못 한다**.

    ── 왜 바꿨나 ────────────────────────────────────────────────────────────
    구버전은 문서의 **모든 TABLE**(`root.findall(".//TABLE")`)을 후보로 놓고 표제 정규식으로
    주석·요약을 걸러냈다. 그 정규식(`classify_statement_title`)에 사각지대가 있어
    (접두 `반기`/`분기` 미허용 + 재무제표명 내부 공백 미처리) DB손해보험 20230927000457 은
    **6개 섹션이 전부 거부**돼 레거시 폴백으로 떨어졌고, 앵커 없는 폴백이 **주석표**를 집어
    별도 이익잉여금 **8.5경원**(정답 8.56조 × 10⁶)이 소비계층까지 적재됐다.

    ── 실측 근거 ────────────────────────────────────────────────────────────
    · 무작위 400건(fy≥2015): 표준 5섹션 보유 **399/400(99.8%)**
    · 본문 섹션 표 **6,229** vs 주석 섹션 표 **149,831** → **전체 표의 96%가 주석**
    · 검증: DB손해보험 6/6 섹션 정상 검출(구버전 0/6) · 3S 6/6 · 메가스터디 6/6

    ⚠ 이 경로는 **2015+ 서식 전용**이다(사용자 결정). 2009~2013 은 `XI. 재무제표 등` +
    `<P>` 구분자, 2000~2008 은 위치 미확인 → Track 3 별도 트랙. 해당 시대는 여기서 빈 dict 가
    나오고 호출측이 보류 처리한다(추측으로 채우지 않는다).

    반환: {section_code: [(table_elem, unit, section_kind), ...]}.
    """
    sec_tables = assign_tables_to_dart_sections(root)
    groups: dict[str, list[tuple]] = {}

    for sec_kind, basis in ((SEC_CONSOL_FS, "consolidated"), (SEC_SEP_FS, "separate")):
        if basis == "consolidated" and fin_type == "B":
            continue  # 연결 없는 기업의 연결 표 무시
        for tbl in sec_tables.get(sec_kind, []):
            # 섹션이 이미 '본문'을 보장하므로 주석 배제 가드가 불필요 → 재무제표명만 본다
            # (공백·반기/분기 접두 허용). 자본변동표(SCE)는 분류기가 배제한다 —
            # include_sce=True(계층2 report_lines 전용)일 때만 'SCE' 로 통과시킨다.
            stmt = classify_statement_in_body_section(title_text(tbl), include_sce=include_sce)
            if stmt is None:
                continue
            # 데이터행 없는 stub(단위표·footer)·wrapper 배제. **직접 행 기준**(깨진 XML 대응).
            if not _table_has_data_rows(tbl):
                continue
            section_code = SECTION_CODE_OF[(basis, stmt)]
            # 단위는 **그 표가 명시 선언한 것만** 신뢰한다(추측 금지). 없으면 None → 보류.
            unit = declared_unit(tbl)
            # sec_kind 를 그대로 들고 간다(basis 에서 되유도하지 않음) — 적재된 행의
            # section_kind 는 **실제로 귀속된 섹션**이어야 감사에 쓸 수 있다.
            groups.setdefault(section_code, []).append((tbl, unit, sec_kind))
    return groups


def declared_unit(tbl) -> int | None:
    """표가 **자기 단위를 명시 선언**한 경우만 그 배수를 반환. 없으면 None(추측 금지).

    허용하는 선언 위치 — 둘 다 **그 표 소유**라 추측이 아니다:
      1) 표제(직전 형제) — 예 '연결 재무상태표 제33기 … (단위 : 백만원)'
      2) 표 자신의 첫 행 — 단위를 표 안 첫 줄에 쓰는 서식

    ★ 의도적으로 **하지 않는** 것(구 `_detect_unit_near_table` 이 하던 추측):
      · 앞 형제 <P> 를 5개까지 거슬러 스캔 — 남의 표 단위를 주워온다
        (엘브이엠씨 2019: USD 기준 BS 표가 4형제 앞 '연결현금흐름표 단위:백만원' 을 주워
         ×10⁶ → 자산총계 586조)
      · 못 찾으면 원(1)으로 가정 — DB손해보험 별도 BS 가 ×10⁶ 오염된 경로의 사촌
    선언이 없으면 **보류**(호출측이 스킵)한다. 결측 > 오염.
    """
    decl = detect_unit_declaration(title_text(tbl))
    if decl is not None:
        return decl
    first_tr = next(iter(table_direct_rows(tbl)), None)
    if first_tr is not None:
        decl = detect_unit_declaration("".join(first_tr.itertext()))
        if decl is not None:
            return decl
    return None


_HANGUL_RE = re.compile(r"[가-힣]")


# 실제 금액 표기 = 콤마 3자리 그룹('55,102,004,323', '(1,234)'). DART 재무제표 금액은 항상
# 콤마 구분이라, 이 패턴이 '금액이 있는 데이터행'과 '날짜만 있는 표제행'을 가른다.
_AMOUNT_CELL_RE = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+\)?$")


def _table_has_data_rows(tbl, minimum: int = 2) -> int:
    """표에 **실제 금액**을 가진 직접 데이터행이 minimum 개 이상인지(표제표·stub·wrapper 배제).

    ★ 두 가지를 모두 지켜야 한다(각각 실측 사고에서 나옴):

    1) **직접 행만** 센다(`.//TR` 금지) — 깨진 XML(</TABLE> 누락)에서 wrapper 가 문서 전체를
       품으면 `.//TR` 은 수천 행을 세어 stub 을 데이터표로 오인한다
       (메가스터디 20190401004405: wrapper 직접 1행 vs `.//TR` 3,573행).

    2) **콤마 금액**을 요구한다(`\\d{2,}` 금지) — DART 본문은 [표제표, 데이터표] 쌍 구조이고
       표제표에도 '제 4 기 2023.12.31 현재' 같은 **날짜 숫자**가 있어 `\\d{2,}` 로는 데이터표와
       구분되지 않는다. 실측(2015+ 무작위 120건): 이 조건 없이는 본문 표의 **147개가 표제표**인데
       데이터표로 오인돼 '단위 미선언'으로 집계됐다(전체 미선언 160개의 92%).
    """
    from parser.xml.table_extractor import _get_cells
    n = 0
    for tr in table_direct_rows(tbl):
        cells = [c.strip() for c in _get_cells(tr)]
        has_label = any(_HANGUL_RE.search(c) for c in cells)
        has_amount = any(_AMOUNT_CELL_RE.match(c) for c in cells)
        if has_label and has_amount:
            n += 1
            if n >= minimum:
                return True
    return False


def _emit_section(
    section_code: str,
    tables_with_unit: list[tuple],
    *,
    add,
    mapper,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> None:
    """한 섹션(BS_C 등)의 데이터 TABLE 들을 컬럼기반으로 읽어 fact 방출.

    tables_with_unit = [(table_elem, unit, section_kind), ...].
    interim(H1/Q1/Q3) IS·CF 2단 누적컬럼 처리 포함.
    """
    basis, period_kind = _SECTION_META[section_code]
    fs_section = section_code.split("_")[0].lower()
    tables = [t for t, _, _ in tables_with_unit]
    unit_of = {id(t): u for t, u, _ in tables_with_unit}
    kind_of = {id(t): k for t, _, k in tables_with_unit}
    # 반기/1·3분기 flow(IS·CF) 표는 [3개월|누적] 2단 헤더에서 누적컬럼만 채택(연도 정합).
    # Q1 은 3개월=누적이라 [당기3개월,당기누적,전기3개월,전기누적] 4열에서 위치기반 num_cols=3
    # 절삭 시 당기값이 전기 슬롯에 중복되고 전기값이 전전기로 오라벨되는 버그가 있었음(DEF-4).
    interim_flow = fs_section in ("is", "cf") and report_fiscal_period in ("H1", "Q1", "Q3")
    cum_maps = {id(t): (_interim_cumulative_cols(t) if interim_flow else None) for t in tables}
    # 금융업 interim IS·CF 는 [당기3개월|당기누적|전기3개월|전기누적] 2단 표와 별도 [전기|전전기]
    # 연간비교 표가 공존한다. 연간비교 표를 위치순 처리하면 전년 FY값이 당기 컬럼으로 오염된다.
    # ⟹ 2단 표가 하나라도 있으면 2단 표만 처리(연간비교 표 스킵; 그 FY값은 연간보고서서 취득).
    has_2tier = interim_flow and any(v is not None for v in cum_maps.values())
    data_tables = sorted(tables, key=lambda t: len(t.findall(".//TR")), reverse=True)

    for table in data_tables:
        cum_map = cum_maps[id(table)]
        if has_2tier and cum_map is None:
            continue  # 2단 표 존재 시 연간비교(비2단) 표는 스킵
        unit = unit_of[id(table)]
        # ★ 단위 미선언 표는 **추측하지 않고 통째로 건너뛴다**(추측 금지 원칙).
        # 과거엔 앞 형제 5개를 뒤져 단위를 주워오거나(_detect_unit_near_table) 없으면 원(1)으로
        # 가정했다. 그 추측이 3S(원문 (단위:백만원) 오기)·네오크레마(천원 오기) 같은 원문 결함과
        # 겹치면 ×10³~10⁶ 오염이 그대로 적재된다. 미선언은 **보류큐** 대상이지 추측 대상이 아니다.
        if unit is None:
            logger.debug(f"[extract2/text] 단위 미선언 → 스킵(보류): {rcept_no} {section_code}")
            continue
        # 누적컬럼이 4번째 등 뒤쪽일 수 있으므로 금액셀을 넉넉히 확보
        n_cols = max(cum_map) + 1 if cum_map else 3
        # ★ 귀속 섹션 컨텍스트(보험/금융 손익계산서): '당기순이익의 귀속' 다음의 지배/비지배는
        # 당기순이익 귀속(controlling/noncontrolling_ni 정답), '총포괄이익(손익)의 귀속' 다음은
        # 총포괄손익 귀속 → 같은 라벨('지배기업의소유주')이 max-abs 로 controlling_ni 를 총포괄값
        # (예 한화손해보험 267B vs 정답 손익귀속 61.26B)으로 오염. 총포괄 귀속 헤더 이후는 제외.
        comp_attr = False
        # direct_only=True: 깨진 XML(</TABLE> 누락)에서 wrapper 가 문서 전체를 품는 경우
        # `.//TR` 은 주석·후속 섹션 행까지 재무제표로 읽는다(DB손해보험 51행 → 5,218행).
        for row in extract_rows(table, multiplier=unit, num_cols=n_cols, direct_only=True):
            if not row.account_name:
                continue
            nm = row.account_name
            if "귀속" in nm:
                # '총포괄손익의 귀속' 뿐 아니라 '포괄손익의 귀속'(총 없이)도 총포괄 귀속 헤더다.
                # 분기 결합표는 [총포괄손익 총계 → 당기순이익의 귀속(지배/비지배) → 포괄손익의 귀속
                # (지배/비지배)] 순이라, 당기순이익 귀속 헤더가 total_comprehensive 통과 플래그를
                # 되돌린 뒤 '포괄손익의 귀속' 헤더로 다시 총포괄 귀속임을 표시해야 지배분 소유주지분
                # 총포괄값(삼성물산 2023Q3 지배 50,712억 vs 정답 손익귀속분)이 오염되지 않는다.
                if "총포괄" in nm or "포괄손익" in nm:
                    comp_attr = True
                elif "순이익" in nm or "순손익" in nm:
                    comp_attr = False
            mapping = mapper.map(row.account_name, fs_section=fs_section)
            if comp_attr and mapping.account_code in ("is.controlling_ni", "is.noncontrolling_ni"):
                continue  # 총포괄손익 귀속 라인 — 당기순이익 귀속(controlling/noncontrolling) 오염 방지
            # ★ '총포괄...귀속' 헤더가 없는 보고서 대응: 'X.총포괄손익' 총계 라인을 통과하면 이후의
            # 지배/비지배 귀속은 (당기순이익 귀속이 아니라) 총포괄손익 귀속이다. 번호형 소항목
            # ('1.지배기업소유주지분')만 나열해 '귀속' 키워드가 없는 케이스(현대해상 등, 손익귀속
            # 5,746억 vs 총포괄귀속 -6,479억 오염)를 잡는다. 총포괄손익 총계 자체는 이 라인에서
            # is.total_comprehensive_income 로 매핑돼 스킵 대상이 아니므로 emit 후 플래그만 켠다.
            if mapping.account_code == "is.total_comprehensive_income":
                comp_attr = True
            if cum_map is not None:
                pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
                         if pos < len(row.amounts) and row.amounts[pos] is not None]
                if not pairs:
                    # ★ 축약(누적-only) 요약행: 상세행은 [3개월,누적,3개월,누적] 4셀이나 총계/귀속
                    # 요약행(당기순이익·지배/비지배 귀속)은 누적값 2개만 가져 누적컬럼(1,3) 위치가 비고
                    # 값이 0·2 등에 실린다 → 누적컬럼이 전부 비면 존재 값을 순서대로 col0,col1.. 로 채택.
                    # (상세행은 누적셀 존재 → 폴백 미발동. interim net_income/controlling 소실 해결.)
                    present = [a for a in row.amounts if a is not None]
                    pairs = list(enumerate(present))
            else:
                # ★ 선두 None(주석/빈 컬럼) 제거 후 열거: 보고서 금액 컬럼은 항상 당기(col0)부터
                # 시작하므로, 표 파서가 끼워넣은 phantom 선두 빈칸은 col_index 를 한 칸씩 밀어
                # 당기 값을 전기 연도로 오귀속한다(보험 손익계산서 'VIII.당기순이익' [None,48.25B,…]
                # → col1=전년 오귀속 → net_income 소실 → net_income_fill 이 총포괄 지배귀속 채택).
                # 내부 None 은 보존(컬럼 의미 유지), 선두 None 만 절삭해 첫 실값=당기(col0).
                amts = row.amounts
                lead = 0
                while lead < len(amts) and amts[lead] is None:
                    lead += 1
                pairs = list(enumerate(amts[lead:]))
            for col_idx, amount in pairs:
                if amount is None:
                    continue
                add(_row_to_fact(
                    row=row, col_idx=col_idx, amount=amount,
                    basis=basis, period_kind=period_kind, mapping=mapping,
                    corp_code=corp_code, rcept_no=rcept_no,
                    report_fiscal_year=report_fiscal_year,
                    report_fiscal_period=report_fiscal_period,
                    fiscal_period=report_fiscal_period, unit=unit,
                    fs_type=section_code, section_kind=kind_of[id(table)],
                ))


def extract_facts(
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """
    Track B(텍스트) 추출. **표제기반 본문표 식별이 1차**, 놓친 핵심 섹션만 레거시 detect_sections
    폴백, 그래도 핵심 섹션 전무면 요약재무정보 폴백.
    같은 (acode, 합성 context) 셀 중복 시 1개로 합치되 금액 보유 행 우선.
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        logger.warning(f"[extract2/text] XML 루트 없음: {file_path}")
        return []

    fin_type = _detect_fin_type(root)
    mapper = get_mapper()
    dedup: dict[tuple[str, str], ExtractedFact] = {}

    conflicts: set[tuple[str, str]] = set()

    def _add(fact: ExtractedFact):
        """같은 (acode, acontext) 셀 중복 처리.

        ★ 2026-07-17: **max-abs 채택 폐지**(추측 금지 원칙).
        구버전은 충돌 시 '더 큰 |금액|이 단위완전=정답'이라며 큰 쪽을 채택했다. 근거는 단일
        사례(엘브이엠씨 USD/KRW 표)였는데, 그 가정을 **모든 충돌에 일반화**해 사실상 단위 추측을
        dedup 으로 위장한 것이었다(패자는 흔적 없이 소멸). 실제로 원문 단위 오기(3S ×10⁶,
        네오크레마 ×10³)가 실재하므로 '큰 쪽=정답'은 성립하지 않는다.
        ⟹ **금액이 다른 충돌이 나면 둘 다 버리고 보류**한다(결측 > 오염).
        금액이 같은 중복은 무해하므로 1개만 유지한다.
        """
        key = (fact.acode, fact.acontext_raw)
        prev = dedup.get(key)
        if prev is None:
            dedup[key] = fact
            return
        if prev.amount_won is None:
            dedup[key] = fact
            return
        if fact.amount_won is None or fact.amount_won == prev.amount_won:
            return                      # 동일값 중복 → 무해, 기존 유지
        conflicts.add(key)              # 값이 다른 충돌 → 판정 불가 → 보류

    # ── DART 섹션 기반 본문표 식별 (유일 경로) ────────────────────────────
    groups = _detect_body_statement_tables(root, fin_type)

    # ★ 폴백 2종 폐지(2026-07-17). 되살리지 말 것 — 둘 다 실제 오염원이었다:
    #
    #  · F4 레거시 갭필(detect_sections + find_section_tables): 표제 앵커가 없어 **주석표를
    #    집었다**. DB손해보험 20230927000457 은 구 표제정규식이 6섹션을 전부 거부해 이 폴백으로
    #    떨어졌고, 폴백이 빈 표제의 주석표(백만원 단위)를 BS_S 로 채택 → 별도 이익잉여금
    #    **8.5경원**(정답 8.56조 × 10⁶)이 std_v2 에 적재돼 DQ=1(정상)로 앱에 노출됐다.
    #    (DQ 는 항등식을 보는데 양변이 균일하게 ×10⁶ 되면 항등식이 성립해 못 잡는다.)
    #
    #  · F5 요약재무정보 폴백(_extract_summary): 요약표를 **본문과 동일한 fs_type/source_ref**
    #    (`BS_C/자산총계`)로 적재해 사후 구분이 불가능했다. 요약은 본문이 아니다.
    #
    # 이제 섹션이 없거나(구형 서식) 본문 섹션에서 표를 못 찾으면 **빈 결과**를 반환한다.
    # 호출측이 보류로 처리한다 — 추측으로 채우지 않는다(결측 > 오염).
    for code, tables_with_unit in groups.items():
        _emit_section(
            code, tables_with_unit, add=_add, mapper=mapper,
            corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year,
            report_fiscal_period=report_fiscal_period,
        )

    # 값이 엇갈린 충돌 셀은 판정 불가 → 적재하지 않는다(보류큐 대상).
    for key in conflicts:
        dedup.pop(key, None)
    if conflicts:
        logger.debug(f"[extract2/text] 값 충돌로 보류한 셀 {len(conflicts)}개: {rcept_no}")

    if not groups:
        logger.debug(f"[extract2/text] 본문 섹션 없음 → 빈 결과(보류): {rcept_no} "
                     f"fy{report_fiscal_year} {report_fiscal_period}")

    return list(dedup.values())
