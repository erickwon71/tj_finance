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
from parser.common.amount_normalizer import (normalize_account_name, detect_unit_declaration,
                                             detect_unit_tokens)
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_tables_to_dart_sections, table_direct_rows,
    SEC_CONSOL_FS, SEC_SEP_FS, SEC_LEGACY_FS, iter_section_elements,
    table_has_amount_rows,
)
from parser.xml.table_extractor import extract_rows
from fin2.extract.xbrl import ExtractedFact
from fin2.extract.statement_titles import (
    title_text, title_text_owned, title_text_for_classify,
    classify_statement_in_body_section, SECTION_CODE_OF,
    _is_metadata_only, _STMT_TITLE,
    classify_legacy_statement_heading, is_legacy_note_marker,
    owned_merged_title, titleless_bs_start,
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

    ⚠ 이 경로는 **2015+ 서식 전용**이다(사용자 결정). 2000~2008 은 위치 미확인 → Track 3
    별도 트랙. 해당 시대는 여기서 빈 dict 가 나오고 호출측이 보류 처리한다.

    ★ 구형 레이아웃(`XI. 재무제표 등`) 보완 — 2026-08-04.
      본문 섹션이 **하나도 없는** 문서에 한해 `_detect_legacy_body_statement_tables` 로
      넘긴다(아래 함수 docstring 에 실측 근거). 본문 섹션이 있으면 이 폴백은 발동하지
      않으므로 기존 102,067건의 동작은 그대로다 — 순수 가산.

    반환: {section_code: [(table_elem, unit, section_kind), ...]}.
    """
    sec_tables = assign_tables_to_dart_sections(root)
    if not sec_tables.get(SEC_CONSOL_FS) and not sec_tables.get(SEC_SEP_FS):
        return _detect_legacy_body_statement_tables(root, fin_type, include_sce)
    groups: dict[str, list[tuple]] = {}

    for sec_kind, basis in ((SEC_CONSOL_FS, "consolidated"), (SEC_SEP_FS, "separate")):
        if basis == "consolidated" and fin_type == "B":
            continue  # 연결 없는 기업의 연결 표 무시
        tbls = sec_tables.get(sec_kind, [])
        # R4-2 §3-B 위치 조건(포시에스 패턴) — 섹션의 첫 **금액표** 인덱스를 미리 구해둔다.
        # `titleless_bs_start` 는 이 인덱스와 일치할 때만 시도한다(그 아래 참고).
        first_amount_idx = next(
            (i for i, t in enumerate(tbls) if table_has_amount_rows(t)), None)
        for idx, tbl in enumerate(tbls):
            # 섹션이 이미 '본문'을 보장하므로 주석 배제 가드가 불필요 → 재무제표명만 본다
            # (공백·반기/분기 접두 허용). 자본변동표(SCE)는 분류기가 배제한다 —
            # include_sce=True(계층2 report_lines 전용)일 때만 'SCE' 로 통과시킨다.
            # ★분류용 표제는 데이터표 경계를 넘지 않는다(남의 재무제표 제목 차용 방지).
            stmt = classify_statement_in_body_section(title_text_owned(tbl), include_sce=include_sce)
            if stmt is None:
                # 요약재무정보 서식: 제목과 단위가 별도 <P> 로 분리돼 데이터표의 직전 형제가
                # 단위줄('(단위:천원)')이라 title_text 가 제목을 못 읽는다. 단위줄 1칸만 건너뛰고
                # 재시도(엠로/에스앤디 등 구형 KOSDAQ 요약; v2 는 XBRL 로 잡던 것). 가산적.
                stmt = classify_statement_in_body_section(
                    title_text_for_classify(tbl), include_sce=include_sce)
            # R4-2(2026-08-05, docs/plans/merged_title_data_table_r4-2_2026-08-05.md) —
            # 위 둘이 **모두** 실패했을 때만 시도하는 최후 폴백 2종. 반드시
            # `table_has_amount_rows(tbl)`(=`_table_has_data_rows`) 가 참인 표에만 적용한다 —
            # 그렇지 않으면 표제/데이터표 분리 서식의 순수 제목표에도 걸려 다음 idx 의 정상
            # 분류와 중복 append 된다(owned_merged_title 문서화 참고, 광범위 서식이라 위험).
            used_merged_title = False
            if stmt is None and _table_has_data_rows(tbl):
                stmt = owned_merged_title(tbl, include_sce=include_sce)
                used_merged_title = stmt is not None
            if stmt is None and idx == first_amount_idx and titleless_bs_start(tbl):
                stmt = "BS"
            # 내용기반 **BS오분류 교정**(타이트): BS 로 분류됐으나 IS 내용(매출+영업이익)을 갖고
            # BS 내용(자산총계 등)이 **없는** 표만 IS 로 교정한다. 직전 형제가 'X 재무상태표는
            # 재작성…' 주석이라 BS 로 오분류된 무제목 IS(지노믹트리 2016) 만 정확히 겨냥 —
            # None/정상분류/실제 BS 는 안 건드려 과도발동(컴투스 IS 138→591) 회피.
            if (stmt == "BS" and _table_has_data_rows(tbl)
                    and _looks_like_income_statement(tbl)
                    and not _looks_like_balance_sheet(tbl)):
                stmt = "IS"
            if stmt is None:
                continue
            # ★내용 기반 최종 가드 — 표제가 CF/BS/IS 를 가리켜도 **행 라벨이 처분계산서**면
            #   본문이 아니다(계양전기 20220420000289: 제목표가 현금흐름표와 동일 문자열).
            if _table_has_data_rows(tbl) and _looks_like_appropriation(tbl):
                continue
            section_code = SECTION_CODE_OF[(basis, stmt)]
            # sec_kind 를 그대로 들고 간다(basis 에서 되유도하지 않음) — 적재된 행의
            # section_kind 는 **실제로 귀속된 섹션**이어야 감사에 쓸 수 있다.
            if _table_has_data_rows(tbl):
                # 정상 서식: 제목+데이터가 한 표(단위는 그 표가 명시 선언한 것만 신뢰).
                unit = declared_unit(tbl)
                # R4-2: 병합표(owned_merged_title 로 확정된 표)만 표 **내부** 메타행에서
                # 단위를 추가로 찾는다 — declared_unit 은 직전 형제/표 첫 행만 보므로 여기
                # 있는 단위(제목 다음 몇 행)를 못 찾는다. 정상 표에 이 스캔을 걸면 첫 행이
                # 이미 헤더/데이터라 그 뒤를 단위로 오인할 위험이 있어 이 표에만 좁힌다.
                if unit is None and used_merged_title:
                    unit = merged_table_local_unit(tbl)
                groups.setdefault(section_code, []).append((tbl, unit, sec_kind))
                continue
            # ★ 제목표/데이터표 분리 서식(2026-07-23, docs/qa/layer2_split_table_gap_2026-07-23.md):
            # 재무제표명('연 결 재 무 상 태 표')이 **데이터 없는 별도 표**로 떨어져 있고, 숫자와
            # 단위는 바로 뒤 데이터표에 있다(보험/증권 + 일반사 특정연도, 로더 done 중 2.9%가 0행).
            # 이 경우 다음 '분류되는 제목표' 전까지 스캔해 **첫 데이터표를 이 재무제표의 데이터로
            # 연결**한다. 정상 서식(위 branch)은 건드리지 않는 가산적 처리다.
            title_unit = declared_unit(tbl)   # 드물게 제목표가 단위를 보유
            for nxt in tbls[idx + 1:]:
                if classify_statement_in_body_section(title_text_owned(nxt), include_sce=include_sce) is not None:
                    break   # 다음 재무제표 제목 도달 → 이 재무제표엔 데이터표 없음(보류)
                if _table_has_data_rows(nxt):
                    if _looks_like_appropriation(nxt):
                        break              # 처분계산서 — 이 재무제표의 데이터가 아니다
                    unit = title_unit if title_unit is not None else declared_unit(nxt)
                    groups.setdefault(section_code, []).append((nxt, unit, sec_kind))
                    break   # 첫 데이터표만 연결(재무제표 하나당 데이터표 하나)
    return groups


# 헤딩이 데이터표를 기다릴 수 있는 최대 요소 수. 실측 거리는 1칸 571 · 2칸 48 · 3칸 이상 0
# (`scripts/verify_legacy_detector.py`). 관측 최대의 2배를 상한으로 둔다.
_LEGACY_PENDING_SPAN = 4


def _detect_legacy_body_statement_tables(root, fin_type: str,
                                         include_sce: bool) -> dict[str, list[tuple]]:
    """구형 레이아웃(`XI. 재무제표 등`)에서 본문 재무제표 표를 찾는다 (2026-08-04).

    ── 왜 별도 경로인가 ──────────────────────────────────────────────────────
    2015+ 서식은 `2.연결재무제표`/`4.재무제표` SECTION-2 가 ①본문임을 보장하고 ②basis 를
    알려준다. 구형 서식에는 그 구획이 없다 — **재무제표와 주석이 한 섹션에 같이 산다.**
    실측 문서순서(20141128001023, 글로본 2015H1):

        [연결 BS 제목표][연결 BS 데이터] … [연결 CF 데이터]
        <P>연결재무제표에 대한 주석          ← 여기부터 주석표 150여 개
        [재무상태표 제목표][별도 BS 데이터] … [별도 CF 데이터]
        <P>별도재무제표에 대한 주석

    그래서 섹션 경계는 아무것도 걸러주지 못하고, **표제 헤딩이 유일한 판별 근거**다.
    판별은 `classify_legacy_statement_heading`(앵커 5조건)에 두고, 여기서는 그 헤딩을
    문서순서로 따라가며 **헤딩 다음 첫 데이터표 하나**만 연결한다.

    ── 실측 근거 (2026-08-04, 2015+ 계층2 공백 189건 전수 원문 파싱) ─────────
    · 공백 189건 중 **본문 섹션이 아예 없는 문서 109건** → 그중 87건이 `XI. 재무제표 등` 보유
    · 앵커가 고른 표의 시퀀스는 전부 정상 재무제표 조합이고 **주석표 채택 0건**:
        con.BS→con.IS→con.CF→sep.BS→sep.IS→sep.CF  40건
        sep.BS→sep.IS→sep.CF                        18건 (연결 미작성사)
        con.BS→con.IS→con.IS→con.CF→sep…            15건 (손익계산서+포괄손익계산서 2표 서식)
    · 나머지 22건은 이 섹션 자체가 없다(감사보고서 첨부 서식 · 웅진 계열 XML 절단) — 대상 아님

    ── 안전장치 ──────────────────────────────────────────────────────────────
    1. 이 함수는 본문 섹션이 **하나도 없을 때만** 호출된다(호출측 가드) → 기존 문서 무영향.
    2. 주석 마커(`연결재무제표에 대한 주석`)를 만나면 수집 상태를 **해제**한다. 헤딩 앵커가
       이미 주석을 떨구지만, 구조 신호를 하나 더 둔다(과거 사고 비용이 컸다).
    3. 헤딩 하나당 데이터표 **하나**만 취한다(2015+ 경로의 '제목표/데이터표 분리 서식'과
       같은 규약). 대기는 `_LEGACY_PENDING_SPAN` 요소 안에서만 유효하다 — 실측 거리는
       **1칸 571건 · 2칸 48건 · 그 이상 0건**이라, 멀리 떨어진 표를 끌어오는 것은
       구조가 아니라 추측이다(그런 헤딩은 데이터표 없이 끝난 것으로 보고 버린다).
    4. 단위는 `declared_unit` 규약 그대로 — 못 찾으면 None 으로 두고 계층2 가 보류한다.

    반환 계약은 `_detect_body_statement_tables` 와 동일:
    {section_code: [(table_elem, unit, section_kind), ...]}.
    section_kind 는 실제 귀속 섹션이어야 감사에 쓸 수 있으므로 `SEC_LEGACY_FS` 를 그대로 쓴다.
    """
    elements = iter_section_elements(root, SEC_LEGACY_FS)
    if not elements:
        return {}

    groups: dict[str, list[tuple]] = {}
    pending: tuple[str, str] | None = None   # (basis, stmt) — 데이터표를 기다리는 헤딩
    pending_unit: int | None = None
    pending_age = 0

    for tag, el in elements:
        text_ = " ".join("".join(el.itertext()).split())

        if pending is not None:
            pending_age += 1
            if pending_age > _LEGACY_PENDING_SPAN:
                pending = None                # 데이터표 없이 끝난 헤딩 — 멀리서 끌어오지 않는다
                pending_unit = None

        if tag == "TABLE" and _table_has_data_rows(el):
            if pending is None:
                continue                      # 관장 헤딩 없는 데이터표 = 주석표 → 취하지 않음
            basis, stmt = pending
            if basis == "consolidated" and fin_type == "B":
                pending = None                # 연결 없는 기업의 연결 표 무시(2015+ 경로와 동일)
                continue
            unit = pending_unit if pending_unit is not None else declared_unit(el)
            groups.setdefault(SECTION_CODE_OF[(basis, stmt)], []).append(
                (el, unit, SEC_LEGACY_FS))
            pending = None
            pending_unit = None
            continue

        if is_legacy_note_marker(text_):
            pending = None                    # 주석 구간 진입 — 대기 중 헤딩도 버린다
            pending_unit = None
            continue

        head = classify_legacy_statement_heading(text_, include_sce=include_sce)
        if head is not None:
            pending = head
            pending_age = 0
            # 헤딩이 표(제목표)면 그 표가 단위를 들고 있을 수 있다(A형 '… (단위 : 원)').
            pending_unit = declared_unit(el) if tag == "TABLE" else None

    return groups


def declared_unit(tbl) -> int | None:
    """표가 **자기 단위를 명시 선언**한 경우만 그 배수를 반환. 없으면 None(추측 금지).

    허용하는 선언 위치 — 둘 다 **그 표 소유**라 추측이 아니다:
      1) 표제(직전 형제) — 예 '연결 재무상태표 제33기 … (단위 : 백만원)'
      2) 표 자신의 첫 행 — 단위를 표 안 첫 줄에 쓰는 서식

      3) 요약재무정보 서식의 제목·기간 클러스터(2026-07-24): [제목][기간][회사명·단위] 를
         별도 <P>/표 로 분리하고 데이터표 직전은 빈 요소인 서식(시큐센 2018 등). 데이터표에서
         뒤로 훑되 **재무제표명(제목)을 가진 형제를 만나면 멈춘다** — 그게 이 statement 의 경계라
         남의 표 단위를 넘어가지 않는다(아래 ★엘브이엠씨 회귀를 구조적으로 회피).

    ★ 의도적으로 **하지 않는** 것(구 `_detect_unit_near_table` 이 하던 추측):
      · 재무제표명 형제를 넘어 무제한 거슬러 스캔 — 남의 표 단위를 주워온다
        (엘브이엠씨 2019: USD 기준 BS 표가 4형제 앞 '연결현금흐름표 단위:백만원' 을 주워
         ×10⁶ → 자산총계 586조). ⟹ (3)은 **재무제표명 경계에서 정지**해 이걸 막는다.
      · 못 찾으면 원(1)으로 가정 — DB손해보험 별도 BS 가 ×10⁶ 오염된 경로의 사촌
    선언이 없으면 **보류**(호출측이 스킵)한다. 결측 > 오염.
    """
    txt = declaration_text(tbl)
    return detect_unit_declaration(txt) if txt else None


def declaration_text(tbl) -> str | None:
    """표가 **자기 소유로** 들고 있는 단위 선언의 **원문 텍스트**. 위치 규칙은 위와 동일.

    `declared_unit` 이 이 함수 위에 있다 — 위치 탐색을 한 곳에만 두기 위한 것이다.
    감사 도구(`scripts/audit_unit_declarations.py`)도 이것을 import 해서 같은 위치를 본다.

    ★ 금액 선언만 찾지 않는다(2026-07-31 F1). 종전에는 `detect_unit_declaration` 이 None 인
      위치를 '선언 없음'으로 보고 다음 위치로 넘어갔다. 그래서 표제가 '(단위 : 주)' 인 표가
      뒤쪽 메타 형제의 '(단위 : 천원)' 을 주워 **주식수를 ×1,000** 할 수 있었다.
      이제는 **가장 가까운 유효 선언에서 멈춘다** — 금액 여부는 그 다음 문제다.
    """
    # 직전 형제(표제)의 **잘리지 않은 전체 텍스트**로 단위 탐지. title_text 는 분류용이라 200자
    # 절단이 있어 긴 안내문+제목이 한 <P> 로 붙은 서식(지노믹트리 2016: '…감사받지 않았습니다.
    # 가.재무상태표 제17기…현재 (단위:원)' 260자)에서 끝의 단위를 놓친다. immediate sibling 은
    # 이 표 소유라 전체를 봐도 남의 단위가 아니다.
    prev0 = tbl.getprevious()
    if prev0 is not None:
        t = " ".join("".join(prev0.itertext()).split())
        if detect_unit_tokens(t):
            return t
    first_tr = next(iter(table_direct_rows(tbl)), None)
    if first_tr is not None:
        t = "".join(first_tr.itertext())
        if detect_unit_tokens(t):
            return t
    # (3) 요약재무정보: 제목·기간 클러스터의 메타 형제에서 단위 획득(재무제표명 경계에서 정지).
    prev = tbl.getprevious()
    for _ in range(3):
        if prev is None:
            break
        t = " ".join("".join(prev.itertext()).split())
        if any(p.search(t) for p, _ in _STMT_TITLE):
            break                       # 재무제표명(제목) 도달 = 경계 — 남의 표로 안 넘어감
        if detect_unit_tokens(t):
            return t
        if not _is_metadata_only(t):
            break                       # 라벨있는 비메타(데이터표 등) — 정지
        prev = prev.getprevious()
    return None


# ── R4-2 병합표 내부 단위 (2026-08-05) ───────────────────────────────────────
_MERGED_HEADER_LABELS = ("과목", "계정과목", "계정명")


def merged_table_local_unit(tbl) -> int | None:
    """'제목+데이터 병합 표'(`statement_titles.owned_merged_title` 로 확정된 표) 안,
    헤더행 이전 메타행들에서 단위 배수를 찾는다.

    `declared_unit`(직전 형제 / 표 첫 행만 봄)이 이런 표에서 단위를 못 찾는 이유는 단위가
    **표 안쪽(제목 다음 2~5번째 행)** 에 있기 때문이다(실측 특수건설 20151116001903·
    팬엔터테인먼트 20181114002948: "회사명 : … (단위 : 원)" 행이 헤더 바로 위에 옴).

    ★★ 호출측 필수 조건 — `owned_merged_title(tbl)` 이 이 표의 첫 행을 재무제표명으로
    이미 확정했을 때만 호출할 것(trs[0]을 무조건 제목행으로 보고 건너뛴다). 그 확정 없이
    일반 표에 걸면 첫 행이 이미 헤더/데이터일 수 있어 데이터를 단위로 오인할 위험이 있다.

    헤더행("과목"/"계정명" 등)에 도달하면 멈춘다 — 그 뒤는 데이터이므로 스캔하지 않는다.
    """
    trs = table_direct_rows(tbl)
    for tr in trs[1:]:                       # trs[0] = 제목행(owned_merged_title 이 확정) — 스킵
        txt = " ".join("".join(tr.itertext()).split())
        compact = re.sub(r"\s+", "", txt)
        if compact in _MERGED_HEADER_LABELS:
            break                            # 헤더 도달 — 그 뒤는 데이터, 더 스캔하지 않는다
        unit = detect_unit_declaration(txt)
        if unit is not None:
            return unit
    return None


# 상속 탐색에서 **건너뛰어도 되는 것**은 두 가지뿐이다(사용자 결정 D1, 2026-07-31).
_INHERIT_SPAN = 6


def inherited_declaration_text(tbl) -> str | None:
    """앞선 **'선언 전용 표'** 의 단위 선언을 상속한다. 그 외에는 아무것도 주워오지 않는다.

    왜 필요한가 — 원문 실측 서식(20230515001080 `8. 범주별 금융상품`):

        <P>     (1) … 범주별 금융상품의 내역은 다음과 같습니다.<당분기말>
        <TABLE> (단위: 천원)      ← 데이터 없는 **선언 전용 표**
        <TABLE> [자산 데이터표]    ← 직전 형제가 선언표 → declaration_text 가 잡는다
        <P>     (빈 요소)
        <TABLE> [부채 데이터표]    ← ★여기서 단위를 잃었다(콤마금액 27~29 셀)

    같은 선언이 관장하는 **두 번째 데이터표부터** 단위가 끊긴다. 미선언 데이터표 셀의 53%
    (전수 환산 약 4.9M 셀)가 이 모양이다(`docs/qa/undeclared_bucket_profile_2026-07-31.md`).

    ★ 상속을 '선언 전용 표'로만 한정하는 이유 — 상속은 본질적으로 추측이라, 근거를 **원문
      구조 사실**로 좁혀야 안전하다. 다음 셋을 지킨다:
        · 건너뛸 수 있는 것 = **빈 요소** 와 **데이터표**(같은 선언 아래 형제들)뿐
        · 텍스트가 있는 요소(<P> 문장·제목·재무제표명)를 만나면 **즉시 정지** — 새 소항목의
          시작이기 때문이다. 실측 반례(20230512001205)가 여기서 걸린다: '(단위 : 원/주)'
          선언표 뒤 데이터표 다음에 **주식 적수 표**가 오는데, 그 사이에 설명 <P> 가 있어
          상속이 발동하지 않는다(발동했다면 주식수에 금액 단위가 붙을 뻔했다).
        · 받아들이는 것 = **데이터행이 없고 유효 선언이 있는 표**뿐
      비금액 열 차단(units.py)은 상속된 단위에도 그대로 적용되고, 상속으로 채운 값은
      `unit_source='inherited'` 로 표시돼 계층3 이 구분할 수 있다.
    """
    prev = tbl.getprevious()
    for _ in range(_INHERIT_SPAN):
        if prev is None:
            return None
        tag = prev.tag.upper() if isinstance(prev.tag, str) else ""
        txt = " ".join("".join(prev.itertext()).split())
        if tag == "TABLE":
            if _table_has_data_rows(prev):
                prev = prev.getprevious()   # 같은 선언 아래 형제 데이터표 — 건너뛴다
                continue
            if detect_unit_tokens(txt):
                return txt                  # ★선언 전용 표 — 여기서만 상속한다
            return None                     # 데이터도 선언도 없는 표 → 근거 없음
        if txt:
            # 텍스트가 있는 요소에서 멈춘다. 단 **그 요소 자신이 선언을 가지면** 그것이 이
            # 항목의 선언이다(사용자 결정 D1 보완, 2026-07-31) — 실측 서식:
            #   <P> (2) 담보로 제공된 자산 … 다음과 같습니다. (단위: 천원)
            #   <TABLE> [데이터표A]      <P>(빈)      <TABLE> [데이터표B] ← B 가 상속
            # 항목 내 관장 선언의 **94%가 이 모양**이다(표본 400 filing: 문단 667표/21,268셀
            # vs 선언전용표 68표/1,316셀). 새 소항목은 자기 문단을 가지므로 경계는 유지된다.
            if any(p.search(txt) for p, _ in _STMT_TITLE):
                return None                 # ★재무제표명은 예외 — 남의 statement 경계다
                                            #   (엘브이엠씨 2019: USD 표가 앞 '연결현금흐름표
                                            #    단위:백만원' 을 주워 자산총계 586조가 된 사고)
            return txt if detect_unit_tokens(txt) else None
        prev = prev.getprevious()            # 빈 요소만 건너뛴다
    return None


# ── 문서 전체 기본 단위 (2026-08-05, 사용자 결정) ───────────────────────────
# '재무제표_직접작성' 수기입력 서식은 본문(BS/IS/SCE/CF) 표 자체에 단위를 아예 재선언하지
# 않는 경우가 있다(실측 이엘피 20160330001530·20160513002038, 인카금융서비스
# 20170516000038, 윙스풋 20210517000207 — 4건 전부 로컬 선언 0건). `declaration_text`·
# `inherited_declaration_text` 는 이 표들의 **직전 형제**만 보므로 근거가 없어 스킵된다.
#
# 이건 statement 경계를 넘는 상속(엘브이엠씨 사고의 그 패턴)이 아니라 **문서 전체 공통
# 기본값**이다 — 근거는 magnitude 추론이 아니라 문서 안의 **명시 텍스트 선언 두 곳뿐**:
#   ① '요약재무정보' 섹션 데이터표의 단위 선언(본문과 같은 회사·같은 기간 수치가 그대로
#      반복되므로 같은 단위임이 구조적으로 보장된다 — 실측 이엘피: 유동자산 12,744,686,267
#      이 요약표·본문표에 동일하게 나타남).
#   ② 회계정책 주석의 '표시통화 … 원(KRW)/원화' 문구(재무제표 작성기준 절, 실측
#      인카금융서비스·윙스풋).
# 호출측(`_emit_section_lines`/`_emit_sce_lines`)은 그 표 **자신에게 이미 통화 선언이
# 있으면**(FX_ONLY 등) 여기까지 오지 않는다 — 그래서 엘브이엠씨류(표마다 통화가 다른 문서)
# 사고를 재현하지 않는다: 그 사고는 '다른 표의 선언을 넘겨받는' 경우였고, 여기는 '어느 표도
# 아무것도 선언 안 했을 때 문서 공통 선언을 쓰는' 경우다.
_SUMMARY_SECTION_RE = re.compile(r"요약재무정보")
_PRESENTATION_CCY_RE = re.compile(r"표시통화.{0,40}(원화|원\s*[\(（]\s*KRW\s*[\)）])",
                                  re.IGNORECASE)


def document_default_unit(root) -> tuple[int | None, str | None]:
    """본문 표에 로컬 단위 선언이 전혀 없을 때 쓰는 **문서 전체 기본 단위**.

    반환 (multiplier, 근거 원문). 못 찾으면 (None, None) — 여전히 추측하지 않는다.

    ★2026-08-05(R4-2) — 요약재무정보 섹션 안에서 **단위 선언 표와 데이터 표가 붙어있지
    않을 수 있다**(실측 포시에스 20171114002836: [단위선언 표 "(단위:원)"] → [연결범위
    표(데이터 없음, 단위선언도 없음)] → [실제 데이터 표] 순서라, 데이터 표의 "직전 형제"
    는 연결범위 표라 종전 로직(`declared_unit(tbl)`, 직전 형제/표 첫 행만 봄)이 단위선언
    표를 못 찾았다). 이 섹션은 R4-1 원칙상 이미 "**문서 전체 단일 단위**"로 취급하므로,
    데이터 없는 표를 만나면 그 단위 선언을 **기억해두고**(pending), 데이터 표 자신에게
    선언이 없을 때 최후 수단으로 그걸 쓴다 — 표별 인접성이 아니라 섹션 전체가 근거다.
    """
    for sec2 in root.iter("SECTION-2"):
        title_el = sec2.find("TITLE")
        if title_el is None:
            continue
        if not _SUMMARY_SECTION_RE.search("".join(title_el.itertext())):
            continue
        pending_text: str | None = None
        for tbl in sec2.iter("TABLE"):
            if not _table_has_data_rows(tbl):
                # 데이터 없는 표(단위 전용·연결범위 등) — 단위 선언만 있으면 기억해둔다.
                txt = " ".join("".join(tbl.itertext()).split())
                if detect_unit_tokens(txt):
                    pending_text = txt
                continue
            unit = declared_unit(tbl)
            decl_text = declaration_text(tbl)
            if unit is None and pending_text is not None:
                unit = detect_unit_declaration(pending_text)
                decl_text = pending_text
            if unit is not None:
                return unit, decl_text
        break  # 요약재무정보 섹션은 문서에 하나뿐 — 못 찾았으면 ②로 넘어간다

    for p in root.iter("P"):
        txt = " ".join("".join(p.itertext()).split())
        if _PRESENTATION_CCY_RE.search(txt):
            return 1, txt[:200]
    return None, None


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
    # 판정 실체는 `section_detector.table_has_amount_rows` 한 곳에 있다 —
    # 표제 back-scan 경계(statement_titles)와 같은 술어를 써야 어긋나지 않는다.
    return table_has_amount_rows(tbl, minimum)


# 손익계산서 내용 시그니처: 매출/영업수익 행 + 영업이익/당기순이익 행. BS(잔액)·SCE(자본변동)·
# CF(현금흐름)·주석 어디에도 이 **조합**은 없다 → 무제목 IS·주석문장 오제목('재무상태표' 언급으로
# BS 오분류) 을 내용으로 확정/교정한다(지노믹트리 2016 등).
_IS_REV_RE = re.compile(r"매출액|매출총이익|영업수익|보험영업수익|보험서비스수익")
_IS_PROFIT_RE = re.compile(r"영업이익|영업손익|당기순이익|당기순손익")
_BS_TOTAL_RE = re.compile(r"자산총계|부채총계|자본총계|자산\s*총계|부채와자본총계")


def _looks_like_income_statement(tbl) -> bool:
    """표의 **행 라벨**에 매출/영업수익 계정과 영업이익/당기순이익 계정이 함께 있으면 IS."""
    from parser.xml.table_extractor import _get_cells
    has_rev = has_profit = False
    for tr in table_direct_rows(tbl):
        cells = _get_cells(tr)
        label = cells[0] if cells else ""
        if _IS_REV_RE.search(label):
            has_rev = True
        if _IS_PROFIT_RE.search(label):
            has_profit = True
        if has_rev and has_profit:
            return True
    return False


# 이익잉여금처분계산서/결손금처리계산서의 **행 라벨** 시그니처. 4대 재무제표 어디에도
# 이 계정들은 나오지 않는다(BS 의 '미처분이익잉여금' 은 자본 항목 한 줄이라 아래 ②가 가른다).
_APPROP_ROW_RE = re.compile(
    r"미처분이익잉여금|미처리결손금|처분전이익잉여금|처분전결손금"
    r"|이익잉여금처분액|결손금처리액|차기이월")
# 4대 재무제표임을 확정하는 행 라벨(있으면 처분계산서가 아니다).
# ★2026-08-05(R4-2) — "부채자본총계"·"자본과부채총계"(순서가 뒤바뀐 BS 대차합계 표기) 추가.
#   팬엔터테인먼트 20181114002948 BS(재무제표_직접작성 수기입력 서식)는 대차합계를
#   "부채자본총계"로만 쓰고 "자산총계"/"부채총계"/"부채와자본총계" 어느 것도 안 쓴다.
#   같은 표에 자본 세부항목으로 "미처분이익잉여금" 행이 있어(정상 BS 구성) 이 확정 라벨이
#   없으면 처분계산서로 오판돼 진짜 BS 가 통째로 배제됐다(R4-2 로 분류가 성공하기 전엔
#   stmt=None 에서 이미 걸러져 이 가드에 도달하지 못해 드러나지 않던 결함).
_REAL_STMT_ROW_RE = re.compile(
    r"영업활동현금흐름|영업활동으로인한현금흐름|투자활동현금흐름|재무활동현금흐름"
    r"|자산총계|부채총계|부채와자본총계|부채자본총계|자본과부채총계|매출액|영업수익|매출총이익")


def _looks_like_appropriation(tbl) -> bool:
    """표의 **행 라벨**이 이익잉여금처분계산서/결손금처리계산서인가.

    ★ 왜 내용까지 봐야 하는가(2026-08-05 실측, 계양전기 20220420000289):
      처분계산서의 표제가 **현금흐름표 표제와 글자 그대로 동일**한 문서가 있다 —
      제출사가 같은 제목표를 재사용했다. 제목·구조로는 구분이 불가능하고 내용만이 가른다.
      (이름 표지는 `_APPROPRIATION_RE`, 구조는 `title_text_owned` 가 이미 맡는다.)

    판정은 두 조건을 **모두** 요구한다 — 값이 아니라 계정명만 보므로 추측이 아니다:
      ① 처분계산서 고유 계정이 있다(미처분이익잉여금·이익잉여금처분액·차기이월 …)
      ② 4대 재무제표 확정 계정이 **없다**(영업활동현금흐름·자산총계·매출액 …)
    ②가 없으면 '미처분이익잉여금' 한 줄을 가진 정상 BS 를 처분계산서로 오판한다.
    """
    from parser.xml.table_extractor import _get_cells
    has_approp = False
    for tr in table_direct_rows(tbl):
        cells = _get_cells(tr)
        label = re.sub(r"\s+", "", cells[0]) if cells else ""
        if _REAL_STMT_ROW_RE.search(label):
            return False                 # 진짜 재무제표 — 판정 종료
        if _APPROP_ROW_RE.search(label):
            has_approp = True
    return has_approp


def _looks_like_balance_sheet(tbl) -> bool:
    """표의 행 라벨에 자산/부채/자본 총계가 있으면 BS(잔액표)."""
    from parser.xml.table_extractor import _get_cells
    for tr in table_direct_rows(tbl):
        cells = _get_cells(tr)
        if cells and _BS_TOTAL_RE.search(cells[0]):
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
