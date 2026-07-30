"""
계층2 추출기 — 보고서 원문을 report_lines tree 로 **판단 없이** 충실전사한다
(4계층 재설계, docs/plans/rearchitecture_4layer_2026-07-19.md §계층2).

fin2/extract/text.py(Track B) 의 추출엔진을 그대로 재사용한다 — 섹션 네비게이터
(`_detect_body_statement_tables`)·단위선언(`declared_unit`)·금액셀 정규식(`_AMOUNT_CELL_RE`,
간접적으로 `table_extractor.extract_rows` 를 통해)·직접행 순회(`table_direct_rows`)까지 전부
동일 경로. **다른 점은 canonical 매핑을 아예 호출하지 않는다는 것**뿐이다:
  - account_mapper.map() 호출 없음 → canonical_account 컬럼 자체가 없음.
  - text.py 의 comp_attr(귀속행 라우팅)·total_comprehensive_income 스킵 트릭은 canonical
    라우팅 전용 로직이라 여기선 불필요(그 라벨들도 label_raw 그대로 각자 행으로 남는다).
  - 값 충돌 시 "둘 다 버리고 보류"(text.py `_add`)도 여기선 없음 — 같은 라벨이 서로 다른
    위치(예 금융업 이중섹션)에 나오면 **둘 다 보존**하는 게 계층2 의 목적이다(계층3 이 합산).

row_order/depth(raw_indent)는 `RowData`(table_extractor.extract_rows)가 이미 계산해 두므로 그대로
옮겨 담는다(신규 로직 아님). section_path(들여쓰기 stack 경로)·node_role(P/S/F)·table_seq/
table_title 은 여기서 산출한다.

★ is_subtotal 컬럼은 두지 않는다 — 2026-07-21 실측 결론. 진짜 소계의 55.3% 가 '자식을 거느린
행'(node_role='P')이고 라벨에 '계'가 없어(유동자산·영업활동현금흐름 …) 텍스트 규칙으로는 잡히지
않는다. 반대로 IS 의 매출총이익·영업이익은 자식이 없는 워터폴 이정표라 이중계산 위험 자체가 없고,
그건 canonical 매핑(=계층3) 문제다. 그래서 계층2 는 node_role(구조 사실)만 남긴다. 근거·수치는
`collector/models.py:ReportLine` docstring 과 `scripts/measure_subtotal_position.py` 참고.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

import re

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import (
    extract_rows, _split_label_amounts, _get_cells, _NUMBER_PATTERN,
)
from parser.common.amount_normalizer import detect_unit_declaration, parse_amount, normalize_account_name

from parser.xml.section_detector import (
    assign_tables_to_dart_sections, assign_note_tables_with_titles,
    SEC_CONSOL_NOTE, SEC_SEP_NOTE, table_direct_rows,
)
from fin2.extract.text import (
    _SECTION_META, _detect_fin_type, _detect_body_statement_tables,
    _interim_cumulative_cols, _adecimal_from_unit, _synth_acontext,
    declared_unit, declaration_text, inherited_declaration_text, _table_has_data_rows,
)
from fin2.extract.units import ColumnUnits

# 주석 표 한 행에서 캡처할 최대 컬럼 수(위치 기준). 주석 표는 컬럼 의미가 제각각(5개년·
# 만기구간·공정가치수준 등)이라 넉넉히 잡아 위치 그대로 전사한다. 값 판단 아님.
#
# ★2026-07-30: 8 → 200. 전수 정방향 조사에서 `extract_rows(num_cols=N)` 의
#   `range(num_cols)` 가 N 번째 이후를 **조용히 버리는 것**이 확인됐다 — 주석
#   3,592,401 셀(주석 원문의 1.62%). 잘리던 것이 유형자산 증감표(토지·건물·기계장치…)
#   처럼 **D&A 산출의 1차 소스**였다. 실측 열 수 분포: 상한 8 은 표의 98.235% 만 덮고
#   최대 열 수는 169 다(`scripts/qa_column_width_dist.py`).
#   상한을 올려도 **빈 열은 행을 만들지 않는다**(None 은 방출 안 함) — 늘어나는 저장량은
#   회수되는 실데이터 그 자체다. 그래서 '넉넉한 안전 한계'로 두고 실제 폭은 표가 정한다.
_NOTE_MAX_COLS = 200

# 자본변동표 금액 열 최대 수. 열은 기간이 아니라 자본 구성요소라 위치 그대로 전사한다.
# ★2026-07-30: 12 → 200(같은 이유). 실측 최대 15 열이고 12 는 98.759% 만 덮었다 —
#   잘리던 col 12~14 에 자본총계가 있었다(20240927000935 '2021.01.01 (기초자본)').
_SCE_MAX_COLS = 200

# 표 헤더의 '제 N 기 (당)/(전)/(전전)' 기간 표기. 기간 수 판정용.
_PERIOD_HDR_RE = re.compile(r"제\s*\d+\s*[（(]?\s*[당전]")


def _detect_period_layout(table) -> tuple[int, bool]:
    """(n_periods, is_multicol) — 표의 기간 수와 '기간당 다열(명세/소계 등)' 여부.

    ★ 보험/증권 재무제표는 한 기간을 2열([당기명세, 당기소계, 전기명세, 전기소계, …])로 인쇄한다.
    그러면 각 데이터행은 기간마다 셀 하나만 채워, num_cols=3 으로는 전전기 이후가 잘린다(삼성생명
    2016 CF 전전기 결측이 이 원인). 헤더의 '제 N 기(당/전)' 수 = n_periods, 데이터행 최대 금액셀
    수 = raw. **raw ≥ 2×n_periods 면 multicol** 로 보고, 호출측이 비어있지 않은 금액을 압축해
    기간값(당기/전기/전전기)으로 매핑한다. (raw ≤ n_periods 정상표는 위치 그대로 = 내부 공란 보존.)

    2×n_periods 기준(엄격)인 이유: 주석번호 열 1개 추가(raw=n_periods+1) 같은 경우를 multicol 로
    오판하지 않기 위함. 압축은 내부 공란을 지우므로 정상표엔 위험 → 다열이 확실할 때만 켠다."""
    n_periods = 0
    max_amt = 0
    for tr in table_direct_rows(table):
        cells = _get_cells(tr)
        if not cells:
            continue
        p = len(_PERIOD_HDR_RE.findall(" ".join(cells)))
        if p:
            n_periods = max(n_periods, p)
        _, amts = _split_label_amounts(cells)
        if len(amts) > max_amt:
            max_amt = len(amts)
    n_periods = min(n_periods or 3, 3)          # report_lines 는 당기/전기/전전기(≤3)만 매핑
    return n_periods, (max_amt >= 2 * n_periods and n_periods >= 1)


@dataclass
class ReportLineRow:
    """report_lines 한 행의 추출 산출물(DB 비의존, 테스트 가능)."""
    corp_code: str
    rcept_no: str
    report_fiscal_year: int
    report_fiscal_period: str
    statement: str                        # BS/IS/CF
    basis: str | None
    label_raw: str
    col_index: int | None
    context_fiscal_year: int | None
    period_kind: str | None
    is_cumulative: bool
    value_won: int | None
    adecimal: int | None
    unit_source: str | None
    source_ref: str | None
    context_raw: str | None
    section_path: str | None = None       # 조상 라벨 경로(들여쓰기 stack)
    row_order: int | None = None
    depth: int | None = None
    node_role: str | None = None          # P/S/F — 순수 구조(다음 행 들여쓰기 비교). 소계 주장 아님
    table_seq: int | None = None          # 섹션 내 표 문서 순번. 정렬키=(table_seq, row_order)
    table_title: str | None = None        # 그 표의 원문 제목(위치 기록)
    col_label: str | None = None          # 열 헤더 원문(SCE 전용 — 열=자본 구성요소)
    # 셀 원문 문자열. **value_won 을 채우지 못한 칸에만** 넣는다(F1, 2026-07-31):
    # 단위를 확정하지 못했거나 비금액 열이라 원 단위로 환산할 수 없는 경우. 값이 채워진 칸은
    # 원문이 value_won 에서 복원되므로 NULL 로 둬 용량을 쓰지 않는다.
    value_raw: str | None = None
    # 헤더 판정 규칙 이름(F2, 2026-07-31). NULL = 규칙에 안 걸린 평범한 데이터 행.
    # 계층3 소비자는 기본적으로 `header_hint IS NULL` 로 거른다(fin2/layer3 가드).
    header_hint: str | None = None

    def as_row(self) -> dict:
        """SQLAlchemy bulk insert 용 dict (ReportLine 컬럼명 기준)."""
        return {
            "corp_code": self.corp_code,
            "rcept_no": self.rcept_no,
            "report_fiscal_year": self.report_fiscal_year,
            "report_fiscal_period": self.report_fiscal_period,
            "statement": self.statement,
            "basis": self.basis,
            "section_path": self.section_path,
            "row_order": self.row_order,
            "depth": self.depth,
            "node_role": self.node_role,
            "table_seq": self.table_seq,
            "table_title": self.table_title,
            "label_raw": self.label_raw,
            "col_index": self.col_index,
            "col_label": self.col_label,
            "context_fiscal_year": self.context_fiscal_year,
            "period_kind": self.period_kind,
            "is_cumulative": self.is_cumulative,
            "value_won": self.value_won,
            "value_raw": self.value_raw,
            "header_hint": self.header_hint,
            "adecimal": self.adecimal,
            "unit_source": self.unit_source,
            "source_ref": self.source_ref,
            "context_raw": self.context_raw,
        }


def _assign_section_paths(rows, statement: str) -> dict[int, str | None]:
    """표 내 행들(표 등장 순서)에 section_path 부여 — **순수 구조(들여쓰기) 판단, 값 판단 아님**.

    indent-stack: 각 행의 raw_indent(원문 선행 공백)로 조상 헤더 체인을 만든다. 자기보다 같거나
    더 들여쓴 스택 항목을 pop 하면 남는 것이 '더 얕은(=상위) 헤더'들이다. 그 체인 = section_path.
    → 금융업 이중섹션(유동자산 288.7B / 금융업자산 2.1B)이 **구조로 구분**된다.

    ★ 자산/부채/자본 같은 top 라벨을 **주입하지 않는다**. K-IFRS 재무상태표는 그 최상위 계정을
    원문에 실제 행(예 '자산' ind0)으로 두므로 스택이 자동으로 '자산>유동자산' / '자산>금융업자산'
    을 만든다(충실전사). 원문에 top 행이 없는 서식은 접두 없이 '유동자산'/'금융업자산' 이 되며
    그래도 이중섹션은 구분된다. **총계 경계·자산/부채/자본 하드코딩 없음** = 값·의미 판단 배제.
    합산·top 귀속은 계층3 몫(여기선 위치만 기록).

    반환: {id(row): section_path or None}. (같은 표 내 row 객체는 서로 다른 id.)
    statement 인자는 향후 IS/CF 전용 처리 여지를 위해 유지(현재 분기 없음 — 순수 구조 동일 적용).
    """
    stack: list[tuple[int, str]] = []   # [(raw_indent, label)]
    out: dict[int, str | None] = {}
    for row in rows:
        ind = row.raw_indent
        while stack and stack[-1][0] >= ind:
            stack.pop()
        out[id(row)] = ">".join(lbl for _, lbl in stack) if stack else None
        stack.append((ind, row.account_name))
    return out


def _classify_positions(rows) -> dict[int, str]:
    """각 행의 node_role(P/S/F) — **다음 행과의 raw_indent 비교만**. 텍스트를 보지 않는다.

        P : 다음 행이 더 깊다  → 자식을 거느린 행. 예 `자산 288,712` 밑에 유동/비유동자산
        S : 다음 행이 더 얕다 or 표 끝 → 형제 run 을 닫는 행. 예 `자산총계`
        F : 다음 행이 같은 깊이 → 형제 중간. 예 IS 의 `매출총이익`

    배타적·전수 분류라 모든 행이 정확히 하나를 받는다. "소계인가"를 주장하지 않는다 —
    들여쓰기에서 기계적으로 나오는 사실만 기록하고, 해석은 계층3 몫(ReportLine docstring 참고).
    """
    out: dict[int, str] = {}
    for i, row in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt is None or nxt.raw_indent < row.raw_indent:
            out[id(row)] = "S"
        elif nxt.raw_indent > row.raw_indent:
            out[id(row)] = "P"
        else:
            out[id(row)] = "F"
    return out


def _row_to_line(
    *, row, col_idx, amount, basis, period_kind, statement,
    corp_code, rcept_no, report_fiscal_year, report_fiscal_period,
    unit, section_code, section_path, node_role, table_seq, table_title,
) -> ReportLineRow:
    ctx_fy = report_fiscal_year - col_idx
    is_cumulative = period_kind == "duration" and report_fiscal_period != "FY"
    return ReportLineRow(
        corp_code=corp_code,
        rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year,
        report_fiscal_period=report_fiscal_period,
        statement=statement,
        basis=basis,
        section_path=section_path,
        label_raw=row.account_name,           # ★ 정규화 없음 — 원문 그대로(text.py acode 와 다름)
        col_index=col_idx,
        context_fiscal_year=ctx_fy,
        period_kind=period_kind,
        is_cumulative=is_cumulative,
        value_won=amount,
        adecimal=_adecimal_from_unit(unit),
        unit_source="declared",               # 미선언 표는 호출측에서 이미 스킵됨
        source_ref=f"{section_code}/{row.account_name[:80]}"[:180],
        context_raw=_synth_acontext(basis, period_kind, col_idx, ctx_fy, statement),
        row_order=row.row_order,
        depth=row.raw_indent,                 # 원문 들여쓰기(전각공백 수) — 구조 그대로
        node_role=node_role,
        table_seq=table_seq,
        table_title=table_title,
    )


def _emit_eps_lines(table, *, emit, basis, statement, corp_code, rcept_no,
                    report_fiscal_year, report_fiscal_period,
                    table_seq=None, table_title=None) -> None:
    """주당손익(EPS) 행을 **per-row 단위**로 전사한다(IS 표 전용).

    ★ 왜 별도 처리인가: 주당이익 라벨은 '계속영업기본주당이익 (단위 : 원)' 처럼 **행 자체에 단위**를
    달고 있어 (a) `_is_header_cell` 이 '단위:' 로 헤더 오인해 드롭하고, (b) 표 단위(천원/백만원)를
    적용하면 원(₩)/주 값이 배로 오염된다. 그래서 표 본류에서 '주당' 행은 건너뛰고(_emit_section_lines),
    여기서 **라벨 인라인 단위(없으면 원=1)**로 직접 파싱해 담는다. context_fiscal_year 는 당기/전기로
    매핑(재무제표 컬럼과 동일)하되, 값은 원(₩)/주 그대로."""
    for tr in table_direct_rows(table):
        cells = _get_cells(tr)
        if not cells or "주당" not in cells[0]:
            continue
        label = cells[0].strip()
        unit = detect_unit_declaration(label) or 1     # 주당은 원(₩)/주 — 인라인 단위, 없으면 원
        _, amt_cells = _split_label_amounts(cells)
        present = [a for a in (parse_amount(c, unit) for c in amt_cells) if a is not None]
        for col_idx, amount in enumerate(present[:3]):
            ctx_fy = report_fiscal_year - col_idx
            emit(ReportLineRow(
                corp_code=corp_code, rcept_no=rcept_no,
                report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
                statement=statement, basis=basis, section_path="주당손익",
                label_raw=label, col_index=col_idx, context_fiscal_year=ctx_fy,
                period_kind="duration", is_cumulative=(report_fiscal_period != "FY"),
                value_won=amount, adecimal=_adecimal_from_unit(unit), unit_source="declared",
                source_ref=f"eps/{label[:70]}"[:180],
                context_raw=_synth_acontext(basis, "duration", col_idx, ctx_fy, statement),
                # EPS 는 표 본류 순회 밖(별도 패스)이라 행 위치를 주장하지 않는다 → node_role NULL.
                row_order=None, depth=None, node_role=None,
                table_seq=table_seq, table_title=table_title,
            ))


def _emit_section_lines(
    section_code: str,
    tables_with_unit: list[tuple],
    *,
    emit,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> None:
    """한 섹션(BS_C 등)의 데이터 TABLE 들을 컬럼기반으로 읽어 report_lines 행 방출.

    text.py `_emit_section` 과 동일한 표 선택/컬럼 판독 로직(interim 누적컬럼 선택 포함) —
    canonical 매핑·귀속행 라우팅만 제거. 상세 판단 근거는 text.py 쪽 주석 참고(그대로 재사용).
    """
    basis, period_kind = _SECTION_META[section_code]
    statement = section_code.split("_")[0]
    tables = [t for t, _, _ in tables_with_unit]
    unit_of = {id(t): u for t, u, _ in tables_with_unit}
    # ★ table_seq 는 **문서 순서**여야 한다. 아래 data_tables 는 표 크기순으로 정렬해 순회하므로
    #   (큰 표 우선 = 기존 표 선택 로직) enumerate 를 쓰면 안 된다. tables 가 문서 순서다.
    # ★같은 표 객체가 tables 에 두 번 담기는 경우가 있다(섹션 감지가 같은 TABLE 중복 수집).
    #   dict 인 doc_seq 는 마지막 인덱스로 덮이는데 아래 루프는 그 표를 **두 번 순회**해,
    #   같은 키(table_seq·row_order·col_index)에 **같은 값 행이 두 벌** 쌓였다 — 전수 실측
    #   report_lines 중복 키 1,076,974 그룹의 정체(2026-07-30). dict 는 삽입 순서를
    #   보존하므로 문서 순서를 유지한 채 중복만 제거한다.
    tables = list(dict.fromkeys(tables))
    doc_seq = {id(t): i for i, t in enumerate(tables)}
    interim_flow = statement in ("IS", "CF") and report_fiscal_period in ("H1", "Q1", "Q3")
    cum_maps = {id(t): (_interim_cumulative_cols(t) if interim_flow else None) for t in tables}
    has_2tier = interim_flow and any(v is not None for v in cum_maps.values())
    data_tables = sorted(tables, key=lambda t: len(t.findall(".//TR")), reverse=True)

    for table in data_tables:
        cum_map = cum_maps[id(table)]
        if has_2tier and cum_map is None:
            continue  # 2단(3개월/누적) 표 존재 시 연간비교(비2단) 표는 스킵(중복 데이터원 배제)
        unit = unit_of[id(table)]
        if unit is None:
            logger.debug(f"[report_lines] 단위 미선언 → 스킵(보류): {rcept_no} {section_code}")
            continue

        # 보험/증권 기간당 다열 포맷 감지(2단 누적표는 별도 경로라 제외).
        n_periods, multicol = (3, False) if cum_map is not None else _detect_period_layout(table)
        n_cols = max(cum_map) + 1 if cum_map else (8 if multicol else 3)

        # 표 전체 행을 먼저 materialize → 들여쓰기 stack 으로 section_path 부여(행 순서 필요).
        table_rows = list(extract_rows(table, multiplier=unit, num_cols=n_cols,
                                        direct_only=True, skip_junk=False))
        section_paths = _assign_section_paths(table_rows, statement)
        node_roles = _classify_positions(table_rows)
        table_seq = doc_seq[id(table)]
        # 표 제목 — 주석 표에 쓰던 것과 **같은 헬퍼**(직전 형제 텍스트 탐색). 신규 로직 아님.
        # 2표식이면 여기서 '연결손익계산서' / '연결포괄손익계산서' 가 각각 잡힌다.
        table_title = _note_heading(table)

        # 주당손익(EPS)은 per-row 단위(원/주)라 표 본류에서 제외하고 아래 EPS 패스로 전사.
        if statement == "IS":
            _emit_eps_lines(table, emit=emit, basis=basis, statement=statement,
                            corp_code=corp_code, rcept_no=rcept_no,
                            report_fiscal_year=report_fiscal_year,
                            report_fiscal_period=report_fiscal_period,
                            table_seq=table_seq, table_title=table_title)

        for row in table_rows:
            if not row.account_name or "주당" in row.account_name:
                continue
            section_path = section_paths.get(id(row))
            if cum_map is not None:
                pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
                         if pos < len(row.amounts) and row.amounts[pos] is not None]
                if not pairs:
                    present = [a for a in row.amounts if a is not None]
                    pairs = list(enumerate(present))
            elif multicol:
                # 기간당 다열: 비어있지 않은 금액을 압축 → [당기, 전기, 전전기] 로 매핑.
                present = [a for a in row.amounts if a is not None]
                pairs = list(enumerate(present[:n_periods]))
            else:
                amts = row.amounts
                lead = 0
                while lead < len(amts) and amts[lead] is None:
                    lead += 1
                pairs = list(enumerate(amts[lead:]))
            for col_idx, amount in pairs:
                if amount is None:
                    continue
                emit(_row_to_line(
                    row=row, col_idx=col_idx, amount=amount,
                    basis=basis, period_kind=period_kind, statement=statement,
                    corp_code=corp_code, rcept_no=rcept_no,
                    report_fiscal_year=report_fiscal_year,
                    report_fiscal_period=report_fiscal_period,
                    unit=unit, section_code=section_code, section_path=section_path,
                    node_role=node_roles.get(id(row)),
                    table_seq=table_seq, table_title=table_title,
                ))


def _cell_span(td, attr: str) -> int:
    """COLSPAN/ROWSPAN 값(대소문자 혼용 대응). 없거나 파싱 불가면 1."""
    for k in (attr, attr.lower(), attr.capitalize()):
        if k in td.attrib:
            try:
                return max(1, int(td.attrib[k]))
            except (TypeError, ValueError):
                return 1
    return 1


def _build_col_labels(table, all_cells: bool = False) -> dict[int, str]:
    """헤더 TR 들을 **COLSPAN/ROWSPAN 그리드로 복원**해 {금액열 인덱스: 열 라벨} 반환.

    ★ 왜 필요한가: 자본변동표는 열이 기간이 아니라 자본 구성요소(자본금/자본잉여금/이익잉여금/
    비지배지분/…)다. col_index 만으로는 어느 열인지 알 수 없어 데이터가 무의미해진다.
    XBRL ACONTEXT(ComponentsOfEquityAxis)에도 같은 정보가 있지만 실측 커버리지가 **21.5%**
    뿐이라(Track A 만 마킹) 헤더 복원이 주 경로다.

    헤더는 다단이고 ROWSPAN 이 섞인다 — 단순 COLSPAN 확장만 하면 단마다 길이가 어긋난다:
        TR0: [라벨칸 ROWSPAN=3][자본 COLSPAN=7]
        TR1: [지배기업…지분 COLSPAN=5][비지배지분 ROWSPAN=2][자본 합계 ROWSPAN=2]
        TR2: [자본금][자본잉여금][기타자본항목][이익잉여금][지배지분 합계]
    → HTML 표와 동일한 방식으로 (row, col) 그리드를 채운 뒤 열별로 단을 위→아래 연결한다.

    헤더 행 = **첫 데이터 행 직전까지**. 데이터 행은 '첫 셀 외에 숫자 셀이 있는 행'으로 본다.
    반환 키는 **금액열 인덱스** — RowData.amounts 인덱스와 맞춘다.

    ★ 라벨 영역이 몇 열인지는 **가정하지 않고 데이터에서 유도**한다. 실측상 1열이 아닌 표가
      25.6% 다 — 라벨 칸이 `COLSPAN=3` 이거나(계정명 영역이 3열로 쪼개짐), 'Ⅱ.자본의 변동 >
      (1)포괄손익 > 세부' 처럼 행 계층이 별도 열로 들어간다. 1열로 가정하면 열 라벨이 통째로
      밀려 이익잉여금이 자본금으로 읽힌다. 그래서 **오른쪽 정렬**한다:
          offset = 그리드 폭 − 금액열 수      (금액열 수 = 데이터 행의 금액 셀 수)
    """
    trs = table_direct_rows(table)
    if not trs:
        return {}

    # 헤더 구간 = 첫 데이터 행 전까지
    n_header = 0
    for tr in trs:
        cells = [" ".join("".join(td.itertext()).split()) for td in tr]
        if len(cells) > 1 and any(_NUMBER_PATTERN.search(c) for c in cells[1:]):
            break
        n_header += 1
    if n_header == 0 or n_header >= len(trs):
        return {}

    # 금액열 수 — 데이터 행들이 실제로 갖는 금액 셀 수(빈 셀 포함, 위치 보존 전제).
    # ★all_cells=True 는 `extract_rows(keep_all_amount_cells=True)` 와 **같은 셈**을 해야 한다
    #   (주석 경로). 한쪽만 비숫자 셀을 빼면 오른쪽 정렬 offset 이 어긋나 열 라벨이 밀린다.
    n_amounts = 0
    for tr in trs[n_header:]:
        cells = _get_cells(tr)
        if all_cells:
            n_amounts = max(n_amounts, max(0, len(cells) - 1))
        else:
            _, amount_cells = _split_label_amounts(cells)
            n_amounts = max(n_amounts, len(amount_cells))
    if n_amounts == 0:
        return {}

    grid: dict[tuple[int, int], str] = {}
    occupied: set[tuple[int, int]] = set()
    for r, tr in enumerate(trs[:n_header]):
        c = 0
        for td in tr:
            while (r, c) in occupied:
                c += 1
            txt = " ".join("".join(td.itertext()).split())
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
                    if txt:
                        grid[(r + dr, c + dc)] = txt
            c += cs

    width = max((col for _, col in occupied), default=0) + 1
    offset = width - n_amounts                       # 앞쪽 라벨 영역 폭(1 이라고 가정하지 않음)
    if offset < 0:
        return {}                                    # 헤더가 데이터보다 좁음 → 정렬 불가(보류)

    out: dict[int, str] = {}
    for col in range(offset, width):
        parts: list[str] = []
        for r in range(n_header):
            t = grid.get((r, col))
            if t and (not parts or parts[-1] != t):  # 같은 셀이 세로로 늘어난 중복 제거
                parts.append(t)
        if parts:
            out[col - offset] = ">".join(parts)      # 금액열 인덱스로 변환
    return out


def _note_heading(table) -> str | None:
    """주석 표 직전의 제목/설명 텍스트(section_path 로케이터). **위치 기록**이지 추측 아님.

    앞 형제를 8개까지 거슬러 첫 '실질' 텍스트를 취한다. **순수 단위선언 라인('(단위: 천원)'
    등)은 건너뛴다** — 그건 표 사이에 끼는 메타행이라 로케이터로 쓸모없고, 단위는 이미
    adecimal 로 잡혔다. 단위선언만 있고 설명이 없으면 그 단위선언이라도 반환(무보다 나음).

    주석 제목은 '33. 매출'·설명문장 등 형태가 제각각이라 정제하지 않고 원문 그대로 담는다."""
    prev = table.getprevious()
    steps = 0
    unit_only_fallback: str | None = None
    while prev is not None and steps < 8:
        txt = " ".join("".join(prev.itertext()).split())
        if txt:
            # 순수 단위선언 라인은 건너뛰고 설명 제목을 찾는다.
            stripped = txt.replace(" ", "")
            is_unit_only = detect_unit_declaration(txt) is not None and (
                stripped.startswith("(단위") or (len(stripped) <= 20 and "단위" in stripped)
            )
            if is_unit_only:
                if unit_only_fallback is None:
                    unit_only_fallback = txt[:255]
            else:
                return txt[:255]
        prev = prev.getprevious()
        steps += 1
    return unit_only_fallback


def _emit_note_lines(
    root, *, emit, corp_code, rcept_no, report_fiscal_year, report_fiscal_period,
) -> None:
    """주석 섹션(연결/별도) 표를 tree 로 전사한다 — **본문과 동일 원칙**(충실전사·판단 없음).

    ★ 커버 범위(2026-07-31 F1 로 확대): **데이터행이 있는 주석 표는 전부** 전사한다.
    종전에는 '단위를 선언한 표'만 적재했다(미선언은 표째 보류). 전수 census 실측 결과 그
    보류가 다음을 통째로 버리고 있었다(`docs/qa/unit_declaration_census_2026-07-30.md`):
      · 비금액 단독 선언('(단위: 주)'·'(단위: %)')  2,871,937 셀 — 주식수·지분율 전량 부재
      · 금액을 선언했는데 못 읽은 표                2,626,779 셀 — 정규식 결함(F1 으로 해소)
      · 미선언 표 중 **데이터표**                  약 9,100,000 셀(주주현황·주당손익·외화환산)
    이제는 적재하되 **단위를 확정한 열만 value_won 을 채우고**, 나머지는 `value_raw`(셀 원문)
    로 남긴다 — 결측 > 오염 원칙은 표 단위에서 **열 단위**로 내려온 것이고, 원문은 잃지 않는다.
    열 귀속 규칙은 `fin2/extract/units.py` 참고.

    ★ 본문과의 차이 — **컬럼을 연도로 판단하지 않는다**. 주석 컬럼은 자산총계/부채총계 같은
    지표거나 만기구간·5개년·공정가치수준이라 '당기/전기'가 아니다. 따라서:
      · col_index = 위치(0,1,2,…) 그대로, context_fiscal_year = **NULL**(연도 주장 안 함).
      · period_kind = NULL. section_path = 주석 제목(로케이터).
    interim 누적컬럼 로직도 적용 안 함(주석엔 무의미)."""
    sec_tables = assign_note_tables_with_titles(root)
    for sec_kind, basis in ((SEC_CONSOL_NOTE, "consolidated"), (SEC_SEP_NOTE, "separate")):
        for table_seq, (table, note_title) in enumerate(sec_tables.get(sec_kind, [])):
            if not _table_has_data_rows(table):
                continue
            # section_path = 관장 번호 주석 제목('27. 현금흐름표')이 우선 — 주석 정체성 로케이터.
            # 없으면 표 직전 설명 텍스트로 폴백. table_title 엔 지역 설명을 따로 남긴다.
            local_heading = _note_heading(table)
            heading = note_title or local_heading
            # ★열 헤더 복원(2026-07-29). 주석 열은 기간일 수도(당기/전기) 자산분류일 수도
            #   (토지/건물/기계) 있는데, 지금까지 col_label 을 안 채워 계층3 가 col_index 만으로
            #   추측해야 했다(유형자산 증감표를 기간축으로 오인하는 원인). SCE 에서 쓰던
            #   _build_col_labels 를 그대로 재사용한다 — 새 파싱 로직이 아니다.
            #   ★2026-07-31: 열 위치를 원문 그대로 보존해 라벨 밀림을 없앤다
            #   (`keep_all_amount_cells` — 그 docstring의 장기차입금 실측 참고).
            note_col_labels = _build_col_labels(table, all_cells=True)
            # ★단위는 표 단위가 아니라 **열 단위**로 정한다(F1, 2026-07-31 — units.py).
            #   선언이 없어도 전사는 계속한다: value_won 은 비고 value_raw 에 원문이 남는다.
            #   표 자신의 선언이 없으면 **앞선 '선언 전용 표'** 에서만 상속한다(D1) —
            #   상속 조건은 `inherited_declaration_text` docstring 참고(그 외엔 아무것도 안 줍는다).
            own_decl = declaration_text(table)
            inherited = None if own_decl else inherited_declaration_text(table)
            cu = ColumnUnits.from_declaration(own_decl or inherited, note_col_labels,
                                              inherited=bool(inherited))
            # 셀 원문 확보용으로 ×1 파싱한다 — 실제 값은 열 배수로 다시 파싱한다.
            # keep_header_rows=True(F2): 헤더 규칙에 걸린 행도 전사하고 규칙 이름만 남긴다.
            # 행이 기간축인 주석 표('당기말' 행 + 자산분류 열)에서 그 행이 실데이터이기 때문.
            note_rows = list(extract_rows(table, multiplier=1, num_cols=_NOTE_MAX_COLS,
                                          direct_only=True, skip_junk=False,
                                          keep_all_amount_cells=True,
                                          keep_header_rows=True))
            node_roles = _classify_positions(note_rows)
            for row in note_rows:
                if not row.account_name:
                    continue
                for col_idx, amount in enumerate(row.amounts):
                    if amount is None:
                        continue            # 원문에 숫자가 없는 칸 — 행을 만들지 않는다(종전과 동일)
                    raw = row.raw_amounts[col_idx] if col_idx < len(row.raw_amounts) else ""
                    mult = cu.multiplier(col_idx)
                    value = parse_amount(raw, mult) if mult is not None else None
                    emit(ReportLineRow(
                        corp_code=corp_code,
                        rcept_no=rcept_no,
                        report_fiscal_year=report_fiscal_year,
                        report_fiscal_period=report_fiscal_period,
                        statement="note",
                        basis=basis,
                        section_path=heading,           # 관장 번호 주석제목(정체성 로케이터)
                        label_raw=row.account_name,     # 원문 그대로
                        col_index=col_idx,              # 위치(연도 아님)
                        context_fiscal_year=None,       # ★ 연도 주장 안 함
                        period_kind=None,
                        is_cumulative=False,
                        value_won=value,
                        # 단위를 확정한 열만 원문 문자열을 버린다(값으로 복원 가능).
                        # 확정 못 한 열은 **원문을 남긴다** — 그것이 NULL 을 정보손실이
                        # 아니게 만드는 유일한 장치다(units.py docstring 참고).
                        value_raw=None if value is not None else (raw.strip()[:64] or None),
                        adecimal=_adecimal_from_unit(mult) if mult is not None else None,
                        unit_source=cu.source(col_idx),
                        # ★ source_ref / context_raw 는 저장하지 않는다(2026-07-28).
                        #   각각 f"note:{basis}/{label_raw[:80]}" · f"note:{basis}:c{col_index}" 로
                        #   **같은 행의 basis·label_raw·col_index 에서 100% 복원**되는 파생 문자열이라
                        #   정보를 하나도 더하지 않으면서 2.16억 행 기준 약 11.7GB(행당 54B)를 먹었다.
                        #   NULL 은 널비트맵 1비트만 쓰므로 그대로 절감된다.
                        #   (본문 report_lines 경로는 무변경 — 주석 경로만 해당)
                        source_ref=None,
                        context_raw=None,
                        row_order=row.row_order,
                        depth=row.raw_indent,
                        node_role=node_roles.get(id(row)),
                        table_seq=table_seq,
                        table_title=local_heading,   # 표 직전 지역 설명(번호제목은 section_path)
                        col_label=note_col_labels.get(col_idx),  # 열 정체(당기/전기 · 자산분류)
                        # 헤더 규칙에 걸린 행이라는 **관찰**(판단 아님). 계층3 가 표별로 판단한다.
                        header_hint=row.header_hint,
                    ))


def _emit_sce_lines(
    section_code: str,
    tables_with_unit: list[tuple],
    *,
    emit,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> None:
    """자본변동표(SCE)를 전사한다 — **본문/주석과 컬럼 규약이 다르다**.

    SCE 는 '행=변동사유, 열=자본 구성요소'인 행렬이다:

                       자본금  자본잉여금  이익잉여금  비지배지분   총계
        2023.01.01(기초)   X       X         X         X        X
          당기순이익         -       -         X         X        X
          배당              -       -        (X)       (X)      (X)
        2023.12.31(기말)   X       X         X         X        X

    그래서 본문 규약(col_index=0 당기/1 전기 …, ctx_fy=report_fy-col_idx)을 쓰면
    **자본잉여금 열이 '전기 데이터'로 둔갑**한다. 주석 슬라이스와 같은 규약을 쓴다:
      · col_index = 위치, context_fiscal_year = NULL, period_kind = NULL
      · 열 정체는 `col_label`(헤더 그리드 복원)로 별도 기록 — `_build_col_labels` 참고
    또 당기/전기 블록이 **세로로 두 번** 쌓이는데 그 구분도 판단하지 않는다. 기초/기말 행의
    라벨이 날짜("2023.01.01 (기초자본)")로 남으므로 계층3 이 읽는다.

    ★ `date_labels_ok=True` 필수: 기본 경로는 날짜 라벨 행을 기간 헤더로 보고 드롭하는데,
      SCE 에서는 그게 기초/기말 잔액 행이다(실측 2,519행/250보고서 유실).
    """
    basis, _ = _SECTION_META[section_code]
    tables = [t for t, _, _ in tables_with_unit]
    # ★같은 표 객체가 tables 에 두 번 담기는 경우가 있다(섹션 감지가 같은 TABLE 중복 수집).
    #   dict 인 doc_seq 는 마지막 인덱스로 덮이는데 아래 루프는 그 표를 **두 번 순회**해,
    #   같은 키(table_seq·row_order·col_index)에 **같은 값 행이 두 벌** 쌓였다 — 전수 실측
    #   report_lines 중복 키 1,076,974 그룹의 정체(2026-07-30). dict 는 삽입 순서를
    #   보존하므로 문서 순서를 유지한 채 중복만 제거한다.
    tables = list(dict.fromkeys(tables))
    doc_seq = {id(t): i for i, t in enumerate(tables)}

    for table in tables:
        unit = next((u for t, u, _ in tables_with_unit if t is table), None)
        if unit is None:
            logger.debug(f"[report_lines/SCE] 단위 미선언 → 스킵(보류): {rcept_no} {section_code}")
            continue
        table_seq = doc_seq[id(table)]
        table_title = _note_heading(table)
        col_labels = _build_col_labels(table)
        adecimal = _adecimal_from_unit(unit)

        # preserve_col_positions=True 필수: 기본 경로는 앞쪽 빈 셀을 당겨(6-column IS 대응)
        # 열을 밀어버린다. SCE 에서 빈 칸은 '그 자본 항목에 영향 없음'이라는 의미 있는 값이다.
        rows = list(extract_rows(table, multiplier=unit, num_cols=_SCE_MAX_COLS,
                                 direct_only=True, skip_junk=False,
                                 date_labels_ok=True, preserve_col_positions=True))
        section_paths = _assign_section_paths(rows, "SCE")
        node_roles = _classify_positions(rows)

        for row in rows:
            if not row.account_name:
                continue
            for col_idx, amount in enumerate(row.amounts):
                if amount is None:
                    continue
                emit(ReportLineRow(
                    corp_code=corp_code,
                    rcept_no=rcept_no,
                    report_fiscal_year=report_fiscal_year,
                    report_fiscal_period=report_fiscal_period,
                    statement="SCE",
                    basis=basis,
                    section_path=section_paths.get(id(row)),
                    label_raw=row.account_name,
                    col_index=col_idx,                 # 위치(연도 아님)
                    col_label=col_labels.get(col_idx),  # 자본 구성요소
                    context_fiscal_year=None,          # ★ 연도 주장 안 함
                    period_kind=None,                  # instant/duration 이 행마다 다름
                    is_cumulative=False,
                    value_won=amount,
                    adecimal=adecimal,
                    unit_source="declared",
                    source_ref=f"{section_code}/{row.account_name[:80]}"[:180],
                    context_raw=f"sce:{basis}:c{col_idx}",
                    row_order=row.row_order,
                    depth=row.raw_indent,
                    node_role=node_roles.get(id(row)),
                    table_seq=table_seq,
                    table_title=table_title,
                ))


def extract_report_lines(
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
    include_notes: bool = False,
) -> list[ReportLineRow]:
    """계층2 추출 진입점. 본문(BS/IS/CF) 을 tree 로 전사. `include_notes=True` 면 주석 표도.

    text.py 와 달리 **dedup/충돌보류가 없다** — 같은 라벨이 다른 위치에 여러 번 나와도
    (금융업 이중섹션 등) 전부 개별 행으로 보존한다. canonical 이 없으니 애초에 "합쳐야 할
    이유"가 없다(합산 판단은 계층3 몫).

    include_notes 기본 False(본문 먼저·주석 다음, 계획 단계화). 주석은 표 수가 많아(96%)
    볼륨이 크므로 명시적으로 켠다. 주석 커버 범위·컬럼 처리는 `_emit_note_lines` 참고.
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        logger.warning(f"[report_lines] XML 루트 없음: {file_path}")
        return []

    fin_type = _detect_fin_type(root)
    lines: list[ReportLineRow] = []

    # include_sce=True — 계층2 는 자본변동표도 전사한다(fact_v2 는 기본값 False 로 계속 배제).
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    for code, tables_with_unit in groups.items():
        emitter = _emit_sce_lines if code.startswith("SCE") else _emit_section_lines
        emitter(
            code, tables_with_unit, emit=lines.append,
            corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year,
            report_fiscal_period=report_fiscal_period,
        )

    if not groups:
        logger.debug(f"[report_lines] 본문 섹션 없음 → 빈 결과(보류): {rcept_no} "
                     f"fy{report_fiscal_year} {report_fiscal_period}")

    if include_notes:
        _emit_note_lines(
            root, emit=lines.append, corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        )

    return lines


# 열이 **기간축**인 statement — 여기서만 col_index 가 '몇 기 전'을 뜻한다
# (`_row_to_line`: context_fiscal_year = report_fiscal_year - col_index).
#   · SCE  : 열 = 자본 구성요소(자본금·이익잉여금…), context_fiscal_year=NULL
#   · note : 열 = 위치(자산분류·만기구간·공정가치수준), context_fiscal_year=NULL
# 그래서 아래 규칙을 SCE/note 에 적용하면 기간이 아닌 실데이터가 삭제된다(SCE 1,555만 행).
_PERIOD_AXIS_STATEMENTS = frozenset({"BS", "IS", "CF"})


def _is_loadable(line: ReportLineRow) -> bool:
    """적재 대상인가 — **당기(col_index=0)만 DB 로 옮긴다**(사용자 결정 2026-07-30).

    이전 기간(전기=col1·전전기=col2)은 **그 기간의 보고서에서** 온다. 상장 후 첫 보고서도
    예외 없이 같은 규칙을 적용한다(그 기업의 상장 이전 기간은 DB 에 존재하지 않는다).
    나중 보고서의 비교컬럼을 쓰면 재작성 값이 원 보고서 값을 덮게 되는데, 그러지 않는다.

    ★추출 단계가 아니라 **적재 단계**에서 걸러야 한다 — `detect_anomalies` 는 추출기 출력
    (`extract_report_lines` 반환값)을 그대로 받아 SCE 기말 행을 BS 전기 열과 연도로 짝지어
    교차검증한다(`fin2/audit/line_anomaly.py:180-196`). 추출기에서 지우면 그 감리가 조용히
    무효화된다. 여기서 걸러야 감리는 온전하고 DB 만 가벼워진다.
    """
    if line.statement in _PERIOD_AXIS_STATEMENTS:
        return (line.col_index or 0) == 0
    return True


def store_report_lines(session, rcept_no: str, lines: list[ReportLineRow]) -> int:
    """rcept_no 단위 delete-then-insert(재추출 재현성). fact_v2 처럼 셀 단위 upsert 가 아님 —
    report_lines 는 값판단이 없어 충돌 개념 자체가 없고, 재추출은 그 보고서의 이전 tree 를
    통째로 교체하는 게 자연스럽다.

    ★본문(BS/IS/CF/SCE)만 적재한다. statement='note' 는 별도 테이블 note_lines 로
    (`store_note_lines`) — 주석 볼륨(본문의 ~4.7배)을 본문 조회에서 격리(2026-07-25).

    ★★당기(col_index=0)만 적재한다 — 사용자 결정 2026-07-30(`_PERIOD_AXIS_STATEMENTS`).
    상세는 `_is_loadable` 참고."""
    from sqlalchemy import delete, insert
    from collector.models import ReportLine

    body = [l for l in lines if l.statement != "note" and _is_loadable(l)]
    session.execute(delete(ReportLine).where(ReportLine.rcept_no == rcept_no))
    if not body:
        return 0

    rows = [l.as_row() for l in body]
    now = datetime.utcnow()
    for r in rows:
        r["parsed_at"] = now
    session.execute(insert(ReportLine).values(rows))
    return len(rows)


# note_lines = report_lines 구조 트윈(별도 테이블, collector/db 마이그레이션 생성). 모델 중복을
# 피하려 Core 로 raw insert 한다(컬럼명 = ReportLineRow.as_row() + parsed_at).
_NOTE_INSERT_COLS = (
    "corp_code rcept_no report_fiscal_year report_fiscal_period statement basis "
    "section_path row_order depth node_role table_seq table_title label_raw col_index "
    "col_label context_fiscal_year period_kind is_cumulative value_won value_raw adecimal "
    "unit_source header_hint source_ref context_raw parsed_at"
).split()


def store_note_lines(session, rcept_no: str, lines: list[ReportLineRow]) -> int:
    """statement='note' 행을 note_lines 로 delete-then-insert(rcept 단위, 재현성).
    본문과 동일 원칙 — 값판단 없음. mixed lines 를 넘겨도 note 만 걸러 적재한다."""
    from sqlalchemy import text as _text

    notes = [l for l in lines if l.statement == "note"]
    session.execute(_text("DELETE FROM note_lines WHERE rcept_no = :r"), {"r": rcept_no})
    if not notes:
        return 0

    now = datetime.utcnow()
    rows = []
    for l in notes:
        d = l.as_row()
        d["parsed_at"] = now
        rows.append(d)
    cols = ", ".join(_NOTE_INSERT_COLS)
    ph = ", ".join(f":{c}" for c in _NOTE_INSERT_COLS)
    session.execute(_text(f"INSERT INTO note_lines ({cols}) VALUES ({ph})"), rows)
    return len(rows)
