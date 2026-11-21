"""B1(→B4 병합) · 수주상황 추출기 — 사업보고서 본문 '수주상황'/'수주계약 현황' 섹션.

DART 는 수주잔고 구조화 API 가 없다(`collector/models.py::OrderBacklog` 독스트링 참조) —
사업보고서 본문표를 파싱한다. biz_section.py 의 그리드 추출·중첩TABLE 배제·숫자파싱을
그대로 재사용(동일 문서 구조·동일 오염 위험이라 이미 검증된 인프라).

실측(2026-07-05, 6개사 — 삼성중공업/한화시스템/현대건설/GS건설/대우건설/한화오션)으로
확인한 3개 구조 유형:
  1. **집계형**(삼성중공업/한화시스템): 사업부문·품목별 소수 행(5행 안팎), 열=수주총액·
     기납품액·수주잔고. 행 그대로 저장(category=품목/사업부문).
  2. **프로젝트 상세형**(현대건설/GS건설, "계약잔액" 명시): 공사·계약별 수십~수백 행, 열=
     기본도급액/완성공사액/계약잔액. 계약잔액이 곧 수주잔고라 프로젝트 전부 합산해 회사
     전체 1행으로 축약(category=None, "전체 프로젝트 합산"으로 표기 — 프로젝트 개수는
     narrative 아닌 raw 로 저장하지 않음, 무손실은 원 raw_report 로 필요시 재조회).
  3. **진행률형**(대우건설/한화오션, "진행률적용 수주계약 현황" — 계약잔액 컬럼 없이
     수주총액+진행률%만): backlog = 수주총액×(1-진행률/100) 파생이 필요한데 진행률
     반올림·초과(개산계약 변경 등) 리스크가 있어 **1차 범위 밖**(TODO, 낮은 신뢰도).
     이 표는 명시적 배제(계약잔액/수주잔고 컬럼 부재로 자연 스킵).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from fin2.extract.biz_section import (
    _FINANCIAL_STMT_KW, _is_clean_number, _is_period_header_cell, _load_root, _narrative_unit,
    _parse_value, _tag, _text, expand_table_grid, is_merged_column_table, is_stacked_amount_cell,
    join_wrapped_number,
)

# 소제목 판정 — biz_section 과 동일하게 짧은 SPAN/P 요소만(내러티브 문단과 구별).
_HEADING_MAX_LEN = 30
_ORDER_HEADING_KW = ("수주상황", "수주 상황", "수주현황", "수주 현황", "수주계약")
# 다음 절 경계 판정 — 가./나. 식 한글순번만 인식(**아라비아 숫자 순번 확장은 시도했다가
# 되돌림**, 2026-08-09). 시도 경위: "5. 수주상황" 다음 진짜 경계 "6. 시장위험과 위험관리"류를
# 놓쳐 무관한 표가 섞일 수 있는 사례(실측 STX엔진 `20150331003320`)를 잡으려 `\d{1,2}\.`를
# 추가했으나, 한국전력공사 등 대기업 보고서에서 수주현황 표 **안**의 항목 라벨("1. 한국전력기술
# (주)" 같은 회사명 리스트, 한글이 있어 한글가드로도 못 거름)까지 절 경계로 오인해 진짜 수주
# 데이터를 대량 삭제하는 훨씬 심각한 회귀를 냄(실측 KEPCO 100→39행 등 6개사 확인, 전수 스캔
# 1,002개사 중 원래 버그의 실제 영향은 1개사뿐이었던 것과 비교해 손익이 맞지 않음). 원래 버그는
# `_MAX_TABLES_PER_MARKER` 상한 + `map_order_table`의 컬럼형태 가드가 대부분 걸러줘 실질 피해가
# 거의 없었으므로(Phase6 2026-08-09 감사 기록), 아라비아 숫자 확장 없이 원래 규칙을 유지한다.
_NUMBERED_HEADING_RE = re.compile(r"^[가-힣]\s*\.\s*\S")

# 열 판별 키워드(회사마다 표기 변이 — 괄호부기 "(A+B)"/"(매출액,A)" 등은 in 매칭이라 무관).
# "도급"(GS건설 "기본 도급금액"처럼 "도급액" 사이에 "금"이 끼는 변이까지 포괄하는 안전한 substring).
# "계약금액"(위세아이텍 — "수주총액" 대신 이 표현 사용).
_TOTAL_KW = ("수주총액", "도급", "계약금액", "수주금액", "용역금액")
# "기납품"(액 없이, 실측 에너토크)·"수익인식액"(위세아이텍 — 진행기준 수익인식 = 누적 완료분).
# R347: recognition columns seen in the 2023+ census ("공사수익", "매출액", "기성", "누적매출액",
# "완성계약액", "기매출액", "매출인식액", "총매출누계액"). Matched on the whitespace-stripped header.
_COMPLETED_KW = ("기납품", "완성공사액", "수익인식액", "공사수익", "매출액", "매출인식", "기성",
                 "완성계약", "기매출", "매출누계", "누적수입", "매출계상", "수익계상", "납품액",
                 # R365: "기인식액(B)" (씨케이솔루션·M83 FY2024), "공급금액" (한국피아이엠 FY2024)
                 "기인식", "공급금액")
# R365: one-word headers, matched on the whole header without notes — "수익" is the period
# recognition of a rollforward (케이씨텍 "기초공사계약잔액 | 신규수주 | 수익 | 기말공사계약잔액"),
# "수주" is the order amount (제놀루션 "수주 | 기납품 | 수주잔고") unless its cells are dates.
_EXACT_COMPLETED = ("수익", "매출")  # 동일고무벨트 "수주 | 매출 | 수주잔액"
_EXACT_TOTAL = ("수주",)
# R365: a column whose every printed cell is a year-month(-day) is a date column even when its
# header has no date word (한국피아이엠 "수주" = "2024.09").
# One-word headers are taken as amounts only when every printed cell is an integer amount
# (LG이노텍 "수주" holds "`06.11").
_AMOUNT_CELL_RE = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})*\)?$")
_DATE_CELL_RE = re.compile(r"^(?:19|20)\d{2}\s*[.\-/년]\s*\d{1,2}(?:\s*[.\-/월]\s*\d{1,2})?\s*[.일]?$")
_BACKLOG_KW = ("수주잔고", "계약잔액", "수주잔액")
# R347: rollforward-in-columns tables (기초잔고 | 신규 | 기납품 | 기말잔고). The opening column
# must be recognised before the backlog keywords — "기초공사계약잔액" also contains "계약잔액".
# "차기이월"/"기말" are the ending balance, so they are checked first.
_ENDING_KW = ("차기이월", "기말")
_OPENING_KW = ("기초", "이월", "전기말")
# Period inflow columns of a rollforward table (new orders and other changes). Their printed
# values are summed into new_orders so that opening + new_orders - completed = backlog.
_NEW_FLOW_KW = ("신규", "산규계약", "수주증가", "증가", "증감", "변경", "변동", "환율", "취소", "추가")
# R362: backlog that enters or leaves with a change of the group (business combination, merger,
# disposal of a subsidiary). It is not an order of the period, so it is kept out of new_orders
# and stored in scope_change with its printed sign (실측 HD현대중공업 FY2025 "사업결합"
# 11,376,357, 동원시스템즈 FY2018 "종속기업처분으로 제거" (578,926,705)).
_SCOPE_CHANGE_KW = ("사업결합", "합병", "연결범위", "종속기업처분", "종속기업취득")
# R364: a balance keyword followed by a change word is a period change of the balance, not the
# balance itself (실측 파인텍 FY2016 "기초잔액 | 연결범위의 변동 | 계약잔액 변경 | 기납품액 | 수주잔고":
# "계약잔액 변경" 62,845,983 was taken as backlog and then overwritten by 수주잔고).
_BALANCE_CHANGE_SUFFIX_RE = re.compile(r"(?:변경|변동|증감|증가|감소)(?:액|금액)?(?:\(.*\))?$")
# Columns that are neither a dimension nor an order amount (contract assets, receivables,
# allowances, counts) — kept out of category. Matched on the whitespace-stripped header.
_META_COL_KW = ("미청구공사", "초과청구", "공사미수금", "매출채권", "대손충당금", "손상차손", "계약자산",
                "계약부채", "수주건수", "순번", "진행율",
                # R365: deferred revenue adjustment (유진기업 "이연수익(*2)"), printed in brackets
                # but added back in the report's own identity — neither a flow we can sign nor a label.
                "이연수익")
# 진행률형(계약잔액 없이 진행률%만) 판별 — 발견 시 낮은 신뢰도로 스킵.
_PROGRESS_ONLY_KW = ("진행률", "미청구공사", "공사미수금")
# 날짜/기한 열 — category 라벨에서 제외(실측: 삼성중공업 "수주일자"/"납기", 에너토크 "수주
# 년도", 위세아이텍 "계약종료일"[="계약"+"종료일", "계약일" substring 미포함이라 "종료일"
# 별도 추가] 열이 라벨에 섞여 오염되던 것 방지).
_DATE_COL_KW = ("일자", "기한", "계약일", "착공", "완공", "납기", "년도", "종료일",
                # R347: matched on the whitespace-stripped header ("납   기", "계 약 일").
                "준공", "시작일", "만료", "완료예정", "수주일", "계약기간")
# 진행률(%) 열 — category 라벨에서 제외(위세아이텍 "50%"가 계약명에 섞이던 것 방지).
_PROGRESS_COL_KW = ("진행률",)
# "당기 XX" 미분류 열(환종별 롤포워드표 — 기초계약잔액/당기신규·변동/당기공사수익/기말계약잔액
# 형태, 실측 KC코트렐 "주요 환종별 수주상황") — "당기신규/변동"·"당기공사수익"은 total/completed
# 키워드에 안 걸려 dim_col 로 새어 category 오염("KRW 49,100,522 61,642,403"). "당기"류는
# 기간흐름 열이지 차원(부문/품목) 아니므로 미분류 시 일괄 제외(backlog 는 "계약잔액"이 기초/
# 기말 양쪽에 매치돼도 마지막 값=기말=현재잔고를 취하므로 이미 올바르게 처리됨).
_PERIOD_FLOW_COL_KW = ("당기",)
# 라벨 셀 안에 박힌 단위주 제거(실측 풍산홀딩스 "㈜풍산 (단위: M/T, 백만원)").
_UNIT_NOTE_RE = re.compile(r"[\(（]\s*단위\s*[:：][^)\]）]*[\)）]")
# "완성공사액" 등 completed 열이 "29,961,564(72,900,381)" 처럼 당기(누적) 두 숫자를 한 셀에
# 담는 관행(실측 제이오) — 앞 숫자는 당기분, 괄호 안은 누적(=계약잔액 계산에 실제 쓰이는 값:
# 기본도급액-누적완성공사액=계약잔액 정확히 성립, 당기분으로는 안 맞음). 괄호 안 숫자를 우선 채택.
_TRAILING_PAREN_NUM_RE = re.compile(r"\(([\d,]+)\)\s*$")
# 원문이 "없음"을 표로 말하는 표기(D3). 공란은 여기 넣지 않는다 — 병합 셀과 구분되지 않는다.
_DASH_MARKS = frozenset(("-", "－", "—", "―", "─"))

# 롤포워드형(전치형: 라벨=행, 연도=열) 수주현황표 — "구분|당기|전기" 또는 "구분|2017년|2016년"
# 헤더에 기초/신규수주/수익인식/기말 수주잔액이 행으로 나열된 형태. map_order_table 의 열-기반
# 판정(수주총액/기납품/수주잔고 헤더열)과 정반대라 별도 경로가 필요. 실측: 싸이맥스 FY2017
# `20180330000166` table_ord=12(0행 처리되던 커버리지 공백, 2026-08-09 order_backlog 검증 중 발견).
_ROLLFORWARD_BACKLOG_LABEL_KW = ("수주잔액", "수주잔고", "계약잔액")
_ROLLFORWARD_OPEN_KW = ("기초",)
_ROLLFORWARD_END_KW = ("기말",)
_ROLLFORWARD_NEW_KW = ("신규수주",)


LAYOUT_CUMULATIVE = "cumulative"    # 수주총액 | 기납품(누적) | 수주잔고
LAYOUT_ROLLFORWARD = "rollforward"  # 기초잔고 | 당기 수주 | 당기 매출인식 | 기말잔고


@dataclass
class OrderBacklogRow:
    """One order_backlog row (R347 meanings).

    cumulative : contract_total = 수주총액(누적 계약금액), completed = 누적 기납품, new_orders = NULL
                 unless the table prints a separate period-new column.
    rollforward: opening_backlog = 기초잔고, new_orders = 당기 수주 증가(신규 + 변경 등 증감 합),
                 completed = 당기 매출인식(양수), contract_total = NULL,
                 scope_change = 사업결합·종속기업 처분 등 범위 변동(R362, 인쇄 부호 그대로),
                 so opening + new_orders + scope_change - completed = backlog.
    """
    category: Optional[str]
    backlog_amt: Optional[int]
    new_orders: Optional[int]
    completed: Optional[int]
    unit: Optional[str]
    opening_backlog: Optional[int] = None
    contract_total: Optional[int] = None
    layout: Optional[str] = None
    scope_change: Optional[int] = None  # R362 rollforward only: business combination / disposal


_MAX_TABLES_PER_MARKER = 4  # biz_section 과 동일 방어 — 헤딩 텍스트가 러닝헤더로 반복 출현해
# (실측: 에너토크 "4. 수주상황" 이 문서 뒤쪽 재무제표 구간에서도 재등장) 다음 경계를 못 찾고
# 창이 무관한 표(부채총계/현금성자산/외화자산 등)까지 쓸어담는 것을 표 개수 상한으로 차단.


def find_order_subsections(root) -> list[tuple[str, Optional[str], list[list[str]]]]:
    """'수주상황' 계열 소제목 다음에 오는 표들을 (heading, unit, grid) 리스트로 반환.
    다음 순번 소제목(가./나. 등)을 만나면 창을 자른다(biz_section 과 동일 전략). 단위는
    보통 데이터표 앞의 "(단위 : 억원)" 같은 1행짜리 안내표에 있고 회사마다 억원/백만원이
    달라(실측: 삼성중공업=억원, 한화시스템=백만원) 반드시 캡처해야 수치 스케일을 안다."""
    elements = list(root.iter())
    marker_positions = []
    for i, el in enumerate(elements):
        if _tag(el) not in ("SPAN", "P"):
            continue
        t = _text(el)
        if t and len(t) <= _HEADING_MAX_LEN and any(k in t for k in _ORDER_HEADING_KW):
            marker_positions.append((i, t))

    results: list[tuple[str, Optional[str], list[list[str]]]] = []
    for idx, (pos, heading) in enumerate(marker_positions):
        next_pos = marker_positions[idx + 1][0] if idx + 1 < len(marker_positions) else len(elements)
        for j in range(pos + 1, next_pos):
            t = _text(elements[j])
            if (_tag(elements[j]) in ("SPAN", "P") and len(t) <= _HEADING_MAX_LEN
                    and _NUMBERED_HEADING_RE.match(t) and not any(k in t for k in _ORDER_HEADING_KW)):
                next_pos = j
                break
        seen = set()
        window_unit = None
        n_tables = 0
        for j in range(pos + 1, next_pos):
            if n_tables >= _MAX_TABLES_PER_MARKER:
                break
            el = elements[j]
            if _tag(el) == "TABLE" and id(el) not in seen:
                seen.add(id(el))
                grid = expand_table_grid(el)
                if len(grid) <= 1:
                    u = _narrative_unit(" ".join(c for row in grid for c in row))
                    if u:
                        window_unit = u
                    continue
                results.append((heading, window_unit, grid))
                n_tables += 1
    return results


def _col_kind(header_text: str, qty_is_amount: bool = False) -> Optional[str]:
    h = re.sub(r"\s+", "", header_text)
    if "수량" in h and "금액" not in h and not qty_is_amount:
        return None  # quantity sub-column of an amount column — never an amount (R347);
        # a merged "수량금액" header (실측 01344336 FY2025) is still the amount column. When the
        # table has no 금액 column at all the "수량" label is the only one printed and the
        # values are the amounts (실측 삼성중공업 FY2019 20200330004469) — qty_is_amount.
    if any(k in h for k in _SCOPE_CHANGE_KW):
        return "scope"  # R362
    is_balance = any(k in h for k in _BACKLOG_KW)
    is_total = any(k in h for k in _TOTAL_KW)
    is_completed = any(k in h for k in _COMPLETED_KW)
    if any(k in h for k in _ENDING_KW) and (is_balance or "차기이월" in h):
        return "backlog"
    if (is_balance and _BALANCE_CHANGE_SUFFIX_RE.search(h) and not is_total
            and not any(k in h for k in _OPENING_KW)):
        return "new"  # R364
    # "금액(이월금액)" is an amount column with a note, not the opening balance.
    h_open = re.sub(r"[\(（][^)）]*[\)）]", "", h)
    if h_open.startswith(_OPENING_KW) or (any(k in h_open for k in _OPENING_KW)
                                          and not (is_total or is_completed)):
        return "opening"
    if is_balance:
        return "backlog"
    if h_open in _EXACT_COMPLETED:
        return "completed"  # R365
    if h_open in _EXACT_TOTAL:
        return "total"  # R365
    # "변경계약금액"/"변경도급액" is the current contract amount, not a period change.
    if any(k in h for k in _NEW_FLOW_KW) and not is_total:
        return "new"
    header_text = h
    if any(k in header_text for k in _COMPLETED_KW):
        return "completed"
    if any(k in header_text for k in _TOTAL_KW):
        return "total"
    return None


def _map_rollforward_table(header_rows: list[list[str]], data_rows: list[list[str]], ncols: int,
                           default_unit: Optional[str] = None) -> Optional[OrderBacklogRow]:
    """롤포워드형(기초/신규수주/수익인식/기말 수주잔액 = 행, 당기/전기 = 열) 표 하나를 회사
    전체 1행으로 축약. `map_order_table`의 열-기반 판정이 실패했을 때(헤더에 수주총액/기납품/
    수주잔고 같은 열이 없을 때)만 폴백으로 호출된다(이미 나눠둔 header_rows/data_rows 재사용).
    신뢰불가면 None(짐작 금지, R0)."""
    header = header_rows[-1] if header_rows else [""] * ncols

    rows_by_kind: dict[str, list[str]] = {}
    for row in data_rows:
        # T12 가드(docs/PARSING_RULES.md 부록A) — 원문이 자간을 공백으로 벌려 쓰는 일이 흔하다
        # (실측: 00164724 "수 익 인 식 액"). 공백 제거 후 매칭.
        label = re.sub(r"\s+", "", row[0])
        if any(k in label for k in _ROLLFORWARD_END_KW) and any(
                k in label for k in _ROLLFORWARD_BACKLOG_LABEL_KW):
            rows_by_kind["end"] = row
        elif any(k in label for k in _ROLLFORWARD_OPEN_KW) and any(
                k in label for k in _ROLLFORWARD_BACKLOG_LABEL_KW):
            rows_by_kind["open"] = row  # 참고용(현재 스키마엔 opening 컬럼이 없어 저장 안 함)
        elif any(k in label for k in _ROLLFORWARD_NEW_KW):
            rows_by_kind["new"] = row
        elif any(k in label for k in _COMPLETED_KW):
            rows_by_kind["completed"] = row

    if "end" not in rows_by_kind:
        return None  # 기말 수주잔액 행이 없으면 이 형태가 아님 — 신뢰 불가

    # 현재 기간 열 = 헤더에 "당기" 있으면 그 열, 없으면 첫 데이터열(DART 관행상 당기가 좌측).
    col = 1
    for c in range(1, ncols):
        if "당기" in re.sub(r"\s+", "", header[c]):
            col = c
            break

    def _cell_int(row: Optional[list[str]]) -> Optional[int]:
        if row is None or col >= len(row):
            return None
        v, _, _ = _parse_value(row[col])
        return int(v) if v is not None and math.isfinite(v) else None

    backlog_amt = _cell_int(rows_by_kind.get("end"))
    if backlog_amt is None:
        return None
    completed = _cell_int(rows_by_kind.get("completed"))
    return OrderBacklogRow(
        category=None, backlog_amt=backlog_amt, new_orders=_cell_int(rows_by_kind.get("new")),
        completed=abs(completed) if completed is not None else None, unit=default_unit,
        opening_backlog=_cell_int(rows_by_kind.get("open")), layout=LAYOUT_ROLLFORWARD,
    )


def map_order_table(grid: list[list[str]], default_unit: Optional[str] = None) -> list[OrderBacklogRow]:
    """표 그리드 → OrderBacklogRow 리스트. 계약잔액/수주잔고 컬럼이 없으면(진행률형) 빈 리스트.
    default_unit: 표 앞 "(단위 : 억원)" 식 안내문에서 캡처한 단위(행별 단위열 없을 때 폴백)."""
    grid = [list(r) for r in grid if r]
    if len(grid) < 2:
        return []
    # T14 가드(docs/PARSING_RULES.md 부록A) — 제출사가 여러 줄을 셀 하나(P 스택)에 몰아넣으면
    # 그리드 확장 후에도 열 값이 구분자 없이 이어붙어 날조된 수치가 된다(실측 00633835 FY2010:
    # 69개 프로젝트 금액이 한 셀에 뭉쳐 float('inf') → OverflowError). biz_metrics(map_biz_table)와
    # 동일한 검증된 가드를 재사용 — 자릿수로 판정하므로 진짜 큰 값(조 단위 등)은 오탐하지 않는다.
    if is_merged_column_table(grid):
        return []
    ncols = max(len(r) for r in grid)
    grid = [r + [""] * (ncols - len(r)) for r in grid]

    # T7 가드(docs/PARSING_RULES.md 부록A) — "2017년"/"2016년"처럼 연도만 있는 헤더 셀도
    # _is_clean_number 엔 수치로 보여 first_data=0 이 되고 표가 통째로 버려진다(biz_section.
    # map_biz_table·biz_catalog 엔 이미 있던 가드, order_backlog 엔 누락 — 실측 싸이맥스 FY2017
    # 롤포워드표가 이 경로로 0행 처리되고 있었다).
    first_data = next((i for i, r in enumerate(grid)
                       if any(_is_clean_number(c) and not _is_period_header_cell(c) for c in r)),
                      None)
    if first_data is None or first_data == 0:
        return []
    header_rows, data_rows = grid[:first_data], grid[first_data:]

    header_text_all = " ".join(header_rows[r][c] for r in range(len(header_rows)) for c in range(ncols))
    if any(k in header_text_all for k in _PROGRESS_ONLY_KW) and not any(k in header_text_all for k in _BACKLOG_KW):
        return []  # 진행률형 — 1차 범위 밖

    # 재무제표/외화자산 표 가드(biz_section 의 _FINANCIAL_STMT_KW 재사용) — 헤딩이 러닝헤더로
    # 반복 출현해 창이 무관한 표까지 쓸어담는 경우의 2차 방어(실측: 에너토크 부채총계/현금성자산).
    all_row_text = " ".join(data_rows[r][c] for r in range(len(data_rows)) for c in range(ncols))
    if any(k in all_row_text for k in _FINANCIAL_STMT_KW):
        return []

    # R347: quantity sub-columns are dropped only when the table prints amount columns too.
    heads_ns = [re.sub(r"\s+", "", " ".join(header_rows[r][c] for r in range(len(header_rows))))
                for c in range(ncols)]
    qty_is_amount = not any("금액" in h for h in heads_ns)
    col_kind: dict[int, str] = {}
    unit_col = None
    skip_cols: set[int] = set()  # 날짜/진행률/기간흐름 등 category 라벨에서 제외할 비수치 메타열
    for c in range(ncols):
        head = " ".join(header_rows[r][c] for r in range(len(header_rows)))
        head_ns = re.sub(r"\s+", "", head)
        # "단위" 완전일치만 단위열로 인정 — substring 매칭이면 "회사명(단위)"(실측 풍산홀딩스,
        # 회사명 셀값 "풍산특수금속㈜ (단위: M/T, 백만원)"=22자가 unit 으로 오인돼 varchar(20)
        # 초과 크래시 + 진짜 카테고리(회사명)가 통째로 사라지는 이중 사고로 이어졌다.
        if head.strip() == "단위":
            unit_col = c
            continue
        if any(kw in head_ns for kw in _META_COL_KW):
            skip_cols.add(c)  # R347: contract asset / receivable / count columns
            continue
        cells = [r[c].strip() for r in data_rows if r[c].strip() and r[c].strip() not in _DASH_MARKS
                 and not _is_total_label(r[c].strip()) and r[c].strip() != "계"]
        if cells and all(_DATE_CELL_RE.match(v) for v in cells):
            skip_cols.add(c)  # R365: date column without a date word in its header
            continue
        k = _col_kind(head, qty_is_amount)  # total/completed/backlog 매칭을 먼저 시도(우선순위 상위)
        h_core = re.sub(r"[\(（][^)）]*[\)）]", "", head_ns)
        if k and h_core in _EXACT_COMPLETED + _EXACT_TOTAL and not (
                cells and all(_AMOUNT_CELL_RE.match(v) for v in cells)):
            k = None  # R365: one-word header without amount cells
        if k:
            col_kind[c] = k
            continue
        if "수량" in head_ns and "금액" not in head_ns and not qty_is_amount:
            skip_cols.add(c)  # R347: quantity sub-column of a known amount column
            continue
        if (any(kw in head_ns for kw in _DATE_COL_KW) or any(kw in head_ns for kw in _PROGRESS_COL_KW)
                or any(kw in head_ns for kw in _PERIOD_FLOW_COL_KW)):
            skip_cols.add(c)
    if "backlog" not in col_kind.values():
        # R347: "이월계약잔액" printed as the last balance column of a rollforward table is the
        # balance carried to the next period (ending), not the opening (실측 대우조선 FY2009~2011
        # "기초계약잔액 | 신규수주액 | 기타증감액 | 당기누적수익계상 | 이월계약잔액").
        carried = [c for c, k in col_kind.items() if k == "opening" and "이월" in heads_ns[c]
                   and not heads_ns[c].startswith(("전기", "기초"))
                   and any(kw in heads_ns[c] for kw in _BACKLOG_KW)]
        if carried and any(k == "opening" and c not in carried for c, k in col_kind.items()):
            col_kind[max(carried)] = "backlog"
    if "backlog" not in col_kind.values():
        # 열-기반 판정 실패 — 롤포워드형(행=기초/신규수주/수익인식/기말, 열=당기/전기)일 수
        # 있으니 폴백으로 확인(실측 싸이맥스 FY2017). 둘 다 아니면 신뢰 파생 불가 → 스킵.
        rf = _map_rollforward_table(header_rows, data_rows, ncols, default_unit)
        return [rf] if rf else []

    dim_cols = [c for c in range(ncols) if c not in col_kind and c != unit_col and c not in skip_cols]
    unit = None
    if unit_col is not None:
        for r in range(len(data_rows)):
            v = data_rows[r][unit_col].strip()
            if v:
                unit = v
                break
    if unit is None:
        unit = default_unit

    # R347: an opening-balance column makes the whole table a rollforward (period flows).
    rollforward = "opening" in col_kind.values()
    layout = LAYOUT_ROLLFORWARD if rollforward else LAYOUT_CUMULATIVE
    rows: list[OrderBacklogRow] = []
    for drow in data_rows:
        # R366: a row whose amount cells stack one value per item (에스엠벡셀 FY2018 "43,148\n5,114\n…"
        # under "W/PUMPO/PUMPAL HEAD…") cannot be split by item — R6, no row.
        # "2,702,100\n(53,921,791)" in a cumulative completed column is 당기(누적), read below.
        if any(is_stacked_amount_cell(drow[c]) for c, k in col_kind.items()
               if not (k == "completed" and not rollforward
                       and _TRAILING_PAREN_NUM_RE.search(drow[c].strip()))):
            continue
        # "-" 단독 placeholder(대손충당 등 값없는 열)는 의미 있는 라벨이 아니므로 제외.
        # 회사명 셀에 "(단위: M/T, 백만원)" 처럼 단위주가 박혀있는 경우(실측 풍산홀딩스) 라벨에서
        # 정리(숫자/backlog 계산엔 영향 없음 — 이미 단위열 완전일치 판정으로 별도 처리됨).
        labels = [_UNIT_NOTE_RE.sub("", drow[c]).strip() for c in dim_cols
                 if drow[c].strip() and drow[c].strip() not in ("-", "－", "—")]
        labels = [lb for lb in labels if lb]
        category = " ".join(dict.fromkeys(labels))[:150] or None
        vals: dict[str, int] = {}
        for c, kind in col_kind.items():
            cell = join_wrapped_number(drow[c])  # R363
            if kind == "completed" and not rollforward:
                m = _TRAILING_PAREN_NUM_RE.search(cell.strip())
                if m:
                    vals[kind] = int(m.group(1).replace(",", ""))
                    continue
            v, _, _ = _parse_value(cell)
            if v is None or not math.isfinite(v):
                continue
            if kind in ("new", "scope"):
                # several period-change columns (신규 / 변경 / 환율 …) add up, printed sign kept
                vals[kind] = vals.get(kind, 0) + int(v)
            else:
                vals[kind] = int(v)
        if rollforward:
            # R347: opening + period inflow - recognised = ending. A total column next to an
            # opening column is the period's new orders (실측 "전기이월누계|수주총액|기납품액|수주잔고":
            # 360,387 + 260,300 - 298,189 = 322,498). Recognition printed as a deduction
            # ("(300,624)" / "-300,624") is stored positive.
            if "new" not in vals and "total" in vals:
                vals["new"] = vals.pop("total")
            if "completed" in vals:
                vals["completed"] = abs(vals["completed"])
        # 불변식 가드: 수주잔고(backlog)는 수주총액(total)을 초과할 수 없다(backlog=total-completed
        # 이므로 completed≥0 이면 항상 backlog≤total). 위반 시 이 행은 신뢰 불가로 폐기 —
        # 실측(엔케이젠바이오텍코리아): 품목 셀이 원본 문서에서 비정상 rowspan 으로 3칸에 걸쳐
        # 중복돼 데이터가 2칸 밀리면서 납기일자("2032.12.31")가 수주총액으로 오파싱(→2032)되고
        # 실제 수주총액(973,902,752,000)이 completed 자리로, backlog(20억)만 제자리 아닌 값으로
        # 밀려 backlog(20억) > total(2032) 라는 명백히 불가능한 조합이 됨. 이런 행은 조용히 버린다
        # (같은 표의 다른 정상 행·소스 자체 계산인 합계행은 영향 없음 — 실측으로 합계행 수치는
        # 정확함을 확인).
        total_v, backlog_v = vals.get("total"), vals.get("backlog")
        if (not rollforward and total_v is not None and backlog_v is not None
                and backlog_v > total_v):
            continue
        common = dict(category=category, new_orders=vals.get("new"), completed=vals.get("completed"),
                      unit=unit, opening_backlog=vals.get("opening"),
                      contract_total=vals.get("total"), layout=layout,
                      scope_change=vals.get("scope") if rollforward else None)
        if "backlog" in vals:
            rows.append(OrderBacklogRow(backlog_amt=vals.get("backlog"), **common))
        elif any(vals.get(k) is not None for k in ("total", "completed", "opening", "new")) and any(
                drow[c].strip() in _DASH_MARKS for c, k in col_kind.items() if k == "backlog"):
            # ★잔고 열이 있는데 그 칸이 '-' 인 행(사용자 결정 D3, 2026-07-31).
            #   실측(20250313000769 레미콘): 수주총액 40,385,176 · 기납품액 40,385,176 ·
            #   수주잔고 '-' — 납품이 끝나 **잔고가 실제로 0** 인 회사다. 종전에는 이 행이
            #   통째로 사라져 수주총액·기납품액(실데이터)까지 같이 없어졌다.
            #   ⚠ 다른 열에 실데이터가 있을 때만 만든다 — 전 열이 비면 그건 빈 행이다.
            #   ⚠ 공란이 아니라 **명시적 대시**만 인정한다: 빈 칸은 '해당 없음'인지 '병합 셀'
            #     인지 원문이 말해주지 않으므로 0 이라고 적을 근거가 없다.
            rows.append(OrderBacklogRow(backlog_amt=0, **common))
    return rows


def is_prior_period_row(new: dict, existing: dict) -> bool:
    """R362-b: True when `new` is the prior-period rollforward of `existing` (same filing, same
    category) — its ending balance is the opening balance of `existing`. Filings often print the
    current and the prior rollforward table with the same category labels; keyed by category, the
    later (prior) table overwrote the current one (실측 동원시스템즈 FY2018 20190329000207: 당기
    기말 0 ← 전기 기말 541,286,219). The printed chain ending(prior) = opening(current) is the proof.
    """
    if new.get("layout") != LAYOUT_ROLLFORWARD or existing.get("layout") != LAYOUT_ROLLFORWARD:
        return False
    b_new, o_cur, b_cur = new.get("backlog_amt"), existing.get("opening_backlog"), existing.get("backlog_amt")
    return b_new is not None and o_cur is not None and b_new == o_cur and b_new != b_cur


def _is_total_label(category: Optional[str]) -> bool:
    return bool(category) and category.replace(" ", "") in ("합계", "총계", "소계")


def _aggregate_if_detail(rows: list[OrderBacklogRow]) -> list[OrderBacklogRow]:
    """행이 많으면(프로젝트 상세형) 회사 전체 합산 1행으로 축약. 적으면(집계형) 그대로.
    이미 "합계" 행이 표에 포함돼 있으면(실측: LS — 부문별 11행+합계 1행=12행) 그 행을 그대로
    채택 — 전부 다시 합산하면 합계행까지 더해져 정확히 2배로 부풀려진다(실측: 149,834→299,668)."""
    labels = [r.category for r in rows if r.category]
    if len(rows) <= 10 and len(labels) != len(set(labels)):
        # R365 (user decision 2026-11-21): repeated labels are separate contracts of one item
        # (M83 "VFX 용역" x5, 한국피아이엠 발주처 "A" x3). Keyed by category the loader kept only the
        # last one. With a printed total row the table becomes that row; without one the rows are
        # left as they were — summing could double merged cells (최초/연장 rows sharing 잔고).
        printed_total = next((r for r in rows if _is_total_label(r.category)), None)
        if printed_total is not None:
            return [replace(printed_total, category=None)]
    if len(rows) <= 10:
        return rows
    existing_total = next((r for r in rows if _is_total_label(r.category)), None)
    if existing_total is not None:
        return [replace(existing_total, category=None)]

    def _sum(attr: str) -> Optional[int]:
        vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return sum(vals) or None

    return [OrderBacklogRow(
        category=None, backlog_amt=sum(r.backlog_amt or 0 for r in rows),
        new_orders=_sum("new_orders"), completed=_sum("completed"),
        unit=next((r.unit for r in rows if r.unit), None),
        opening_backlog=_sum("opening_backlog"), contract_total=_sum("contract_total"),
        layout=next((r.layout for r in rows if r.layout), None),
        scope_change=_sum("scope_change"),
    )]


def parse_order_backlog(file_path: Path, corp_code: str, fiscal_year: int) -> list[dict]:
    """파일 하나 → order_backlog 행 딕셔너리 리스트(멱등 upsert 는 수집기가 담당)."""
    root = _load_root(file_path)
    if root is None:
        return []
    out: list[dict] = []
    for _heading, unit, grid in find_order_subsections(root):
        rows = map_order_table(grid, default_unit=unit)
        rows = _aggregate_if_detail(rows)
        for r in rows:
            out.append({
                "corp_code": corp_code, "fiscal_year": fiscal_year,
                "category": r.category, "backlog_amt": r.backlog_amt,
                "new_orders": r.new_orders, "completed": r.completed,
                "opening_backlog": r.opening_backlog, "contract_total": r.contract_total,
                "layout": r.layout,
                # DB 컬럼길이 방어 클리핑(unit=varchar(20)) — 실측 풍산홀딩스 크래시 재발 방지용
                # 최후 안전망(주 방지책은 위 단위열 완전일치 판정).
                "unit": (r.unit or "")[:20] or None, "source": "html_parse",
            })
    return out
