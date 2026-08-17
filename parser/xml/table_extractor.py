"""
DART XML TABLE 구조에서 재무 행 데이터 추출

입력: TABLE 요소 (lxml etree._Element)
출력: list[RowData] — (계정과목명, [당기, 전기, 전전기]) 형태의 행 리스트

DART XML TABLE 구조:
  <TABLE>
    <THEAD> or first TBODY rows → 헤더 (기수/날짜)
    <TBODY>
      <TR>
        <TD> 계정과목명 </TD>
        <TD ALIGN="RIGHT"> 당기금액 </TD>
        <TD ALIGN="RIGHT"> 전기금액 </TD>
        <TD ALIGN="RIGHT"> 전전기금액 </TD>   ← 사업보고서만
      </TR>
    </TBODY>
  </TABLE>

주의사항:
  - TE 태그: ACODE 속성 있는 데이터 셀 (Track A 전용)
  - TD 태그: 일반 셀
  - TH 태그: 헤더 셀
  - TU 태그: 단위/날짜 셀
  - 소계 행: 앞에 공백 있거나 굵게 표시된 합계 행 탐지
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from lxml import etree

from parser.common.amount_normalizer import parse_amount, normalize_account_name, _TRAIL_DECOR_RE


# 숫자 컬럼으로 판단할 패턴 (쉼표 구분 숫자, 괄호음수 등)
_NUMBER_PATTERN = re.compile(
    r'^[\s\-\─\—\―]$|'              # 공란 / 대시
    r'^\([\d,]+\.?\d*\)$|'           # (음수) — 소수 허용(주당손익·비율 등)
    r'^\(-\)[\d,]+\.?\d*$|'          # (-)음수 — 괄호로 안 감싸고 "(-)" 자체를 부호마커로 붙이는
                                      #   이중표기(일부 K-GAAP filer 실측, 2026-08-10 pre-2015
                                      #   파일럿 백필 항등식 검증 중 발견 — 이 게이트를 안 넓히면
                                      #   `parse_amount` 가 이 형태를 읽게 고쳐도 셀 자체가 여기서
                                      #   "숫자 아님"으로 걸러져 amount_cells 에 못 들어간다)
    r'^-[\d,]+\.?\d*$|'               # -음수 — 괄호 없는 순수 하이픈 음수(R31, T22, 2026-08-16).
                                      #   T21(위 "(-)" 대안)의 자매결함: 첫 대안 `^[\s\-─—―]$`은
                                      #   대시 "한 글자"만인 셀(공란 마커)만 잡아, "-466,274"처럼
                                      #   뒤에 숫자가 붙은 셀은 어느 대안에도 안 걸려 여기서 "숫자
                                      #   아님"으로 드롭됐다 — placeholder도 안 남기고 셀 자체가
                                      #   사라져 뒤 컬럼이 배열 안에서 앞으로 밀렸다(interim 2단헤더
                                      #   cum_map 이 헤더 위치 기준이라 밀린 배열과 어긋나
                                      #   전기/무관 컬럼값이 당기 자리로 오emit되거나 당기값 자체가
                                      #   유실됨). `parse_amount` 는 이미 순수 "-N"을 정상적으로
                                      #   음수 처리한다(`amount_normalizer.py`) — T21과 달리 그쪽은
                                      #   수정 불필요, **이 게이트만의 결함**이었다. 뒤에 숫자를
                                      #   요구하므로("[\d,]+") 대시 한 글자 대안과 충돌 없음.
                                      #   실측 스코프(census 259필링, 2026-08-16): 본문 BS/IS/CF
                                      #   행의 0.25%가 조용히 틀린 값으로 적재돼 있었다(전부
                                      #   pre-2010 K-GAAP 서식) — docs/PARSING_RULES.md R31·부록A T22.
    r'^[\d,]+\.?\d*$|'               # 양수 — 소수 허용
    r'^△[\d,]+\.?\d*$|'              # △음수
    r'^▲[\d,]+\.?\d*$'               # ▲음수
)

# 소계/합계 행 판단 키워드
_SUBTOTAL_KEYWORDS = frozenset([
    "합계", "소계", "총계", "계",
    "자산총계", "부채총계", "자본총계",
    "매출총이익", "영업이익", "당기순이익",
    "유동자산합계", "비유동자산합계",
    "유동부채합계", "비유동부채합계",
    # 금융업 IS 섹션 합계 (보험/증권 6-column 형식에서 section total)
    "영업수익",
])

# 재무 데이터로 저장하지 않아야 할 잡 행 (헤더/메타데이터/순수 레이블)
# NOTE: is_subtotal=True인 계정명은 별도 처리되므로 여기서는 제외
_JUNK_ACCOUNT_NAMES = frozenset([
    # 테이블 열 헤더 (period/context labels)
    "3개월", "6개월", "9개월", "12개월",
    "1분기", "2분기", "3분기", "4분기",
    "당 기", "전 기", "당기", "전기",  # 단독 셀 (계정명 아님)
    "기초", "기말",                    # 단독으로만 쓰인 경우
    # 메타데이터 컬럼 레이블
    "회사명", "기업명", "법인명",
    "주주명", "성명", "이름", "주 주 명",
    "계정과목", "계정명",
    "사업연도", "결산기",
    "기준일", "기초금액",
    "취득원가",                        # NOTE 유형자산 세부 테이블 열 헤더
    # NOTE 테이블 메타 레이블
    "잔여만기", "사모", "미상환잔액",
    "지급보증금액",
    # NOTE 주주명부 / 지배구조 테이블 행 레이블 (금융 데이터 아님)
    "종속기업명", "관계기업명", "공동기업명",
    "우리사주조합", "기타주주", "소액주주", "최대주주", "특수관계인",
    "국내법인", "외국법인", "외국인",
    # NOTE/BS 공시 메타 레이블 (계정과목 아님)
    "연결에 포함된 회사수", "연결포함회사수",
    "자본과 부채",          # BS 섹션 구분 헤더 (K-GAAP)
    "자산과 부채",          # BS 섹션 구분 헤더 변형
    # 투자 평가방법 공시 (NOTE 항목, 금융 데이터 아님)
    "종속ㆍ관계ㆍ공동기업투자주식의 평가방법",
    "종속ㆍ관계ㆍ공동기업투자주식의평가방법",
    "종속·관계·공동기업투자주식의 평가방법",
    # 공정가치 계층 레이블 (NOTE 공정가치 측정 테이블)
    "수준 1", "수준 2", "수준 3", "수준1", "수준2", "수준3",
    "Level 1", "Level 2", "Level 3",
    # 소계/합계 단독 레이블 (BS·IS 내 섹션 소계 — is_subtotal=True로 처리되나
    # NOTE 테이블에서 단독으로 나타나면 unknown_accounts 오염 방지)
    "소계",
    # PPE NOTE 세부 항목 (주석 유형자산 변동표 컬럼 헤더/행 레이블)
    "감가상각누계액", "손상차손누계액", "정부보조금",
    # 손익계산서 비용 성격별 분류 세부항목 — 개별 행은 집계 불필요
    # (영업비용/판관비 합계로 SGA 포착, 개별 항목 저장 시 이중계산 위험)
    "지급수수료", "복리후생비", "광고선전비", "기부금",
    "여비교통비", "보험료", "소모품비", "세금과공과",
    "접대비", "통신비", "수선비", "차량유지비", "운반비",
    "교육훈련비", "도서인쇄비", "회의비",  # 잡비는 is.other_expense에 있으므로 junk 제외
    "수도광열비", "견본비", "포장비",       # 추가 세부 비용
    # 재고자산 세부 항목 (재고자산 합계로 bs.inventory 포착)
    "원재료", "재공품", "저장품", "미착원재료", "미착품",
    # 대손충당금 — BS 매출채권 차감 항목, 독립 BS 항목 아님
    "대손충당금", "대손충당금(차감)",
    # K-GAAP BS 중간 소계 (개별 항목도 포함되어 이중집계 방지)
    "당좌자산",   # K-GAAP 유동자산 내 당좌자산 소계 (현금+단기투자+매출채권 등)
    # K-GAAP 자본 세부항목 (이익잉여금 총액으로 bs.retained_earnings 포착)
    "법정적립금", "임의적립금", "미처분이익잉여금", "처분후이익잉여금",
    # 자본 조정항목 (자본총계에 포함됨)
    "지분법자본변동",
    # PPE 차감항목 (PPE 순액으로 이미 bs.ppe 포착됨)
    "국고보조금", "평가충당금",
    # 기타 메타/연결 정보
    "연결에포함된회사수",
    # 국민연금전환금 (구 회계기준 특수항목)
    "국민연금전환금",
    # 기간/분기 컬럼 헤더 — 분기보고서 IS에서 컬럼명이 행으로 추출되는 경우
    "3개월", "6개월", "9개월", "12개월",
    "1개월", "2개월", "4개월", "5개월", "7개월", "8개월", "10개월", "11개월",
    # 테이블 메타 레이블 — 계정과목 아님 (주주명부, 주석 헤더 등)
    "회사명", "주주명", "성명", "계정과목", "사업연도", "대표이사",
    "(기준일 :", "기준일",
    "미상환잔액", "잔여만기", "사모", "공모",
    "기초금액", "취득원가", "장부금액",
    # EPS 및 주당 지표 — financial_facts 집계 항목 아님
    "주당손익", "주당이익", "주당손실", "주당배당금", "기본주당이익", "희석주당이익",
    # BS 이중계산 방지 — 합계 레이블 변형 (= 자산총계, total_liabilities 오염 방지, P0-5)
    # normalize_account_name 이 공백은 제거하나 및↔와↔과 는 통일하지 않으므로 변형을 모두 등재.
    "자본과부채총계",          # = 자산총계 (BS 우변 합계, 중복)
    "부채및자본총계",          # = 자산총계 변형
    "부채와자본총계",          # = 자산총계 변형(와) — 구형 K-GAAP 다수(한국석유공업·황금에스티 등)
    "부채와자본의총계", "부채및자본의총계",   # '의' 삽입 변형
    "자본및부채총계",          # 순서 변형(및)
    "자산및부채총계",
    # OCI 세부 분류 헤더 — is.oci 합계로 포착됨, 세부 행은 이중계산 방지
    "후속적으로당기손익으로재분류되지않는항목",
    "후속적으로당기손익으로재분류될수있는항목",
    "당기손익으로재분류되지않는항목",
    "당기손익으로재분류될수있는항목",
    "당기손익으로재분류되지않는항목의법인세",
    "확정급여제도의재측정효과",
    "확정급여제도의재측정요소",
    "해외사업환산차이",          # OCI 항목
    "위험회피파생상품평가이익",   # OCI 항목
    "위험회피파생상품평가손실",   # OCI 항목
    # IS 금융수익 세부 헤더 (금융수익 합계로 포착됨)
    "이자수익(유효이자율법)",
    # CF 선수수익 변동 (영업CF 조정항목, 독립 집계 불필요)
    "선수수익의증가", "선수수익의감소",
    # NOTE 증권사/기관 이름 (주석 테이블 행/열 레이블)
    "NH투자증권", "부국증권", "한국투자증권", "미래에셋증권",
    "키움증권", "삼성증권", "대신증권", "신한투자증권", "KB증권",
])


@dataclass
class RowData:
    account_name: str              # 원문 계정과목명
    amounts: list[Optional[int]]   # [당기, 전기, 전전기] (None=공란)
    # 금액 셀의 **원문 문자열**(amounts 와 같은 인덱스). 단위를 확정하지 못해 value_won 을
    # 비우는 열(fin2/extract/units.py)에서 원문을 잃지 않기 위한 것 — F1, 2026-07-31.
    # 재정렬(6열 IS 선행공란 제거)에도 amounts 와 **함께** 이동한다.
    raw_amounts: list[str] = field(default_factory=list)
    # 헤더 판정 규칙 이름(`_header_rule_name`) — `keep_header_rows=True` 로 뽑았을 때만 채워진다.
    # 값이 있으면 "이 행은 헤더 규칙에 걸렸다"는 **관찰**이지 "헤더다"라는 판단이 아니다(F2).
    header_hint: Optional[str] = None
    row_order: int = 0
    is_subtotal: bool = False      # 합계/소계 행 여부
    indent_level: int = 0          # 들여쓰기 수준 (0=최상위, 1=하위...) — _detect_indent(//2)
    raw_indent: int = 0            # 첫 셀 원문 선행 공백 수(전각 U+3000 포함, strip 전).
    # ★ indent_level 은 _get_cells 가 strip 한 뒤라 항상 0(사문화). raw_indent 는 원문 들여쓰기를
    #   그대로 보존한다 — 계층2 report_lines 의 section_path(하위섹션 tree) 산출용.


def extract_rows(
    table_elem: etree._Element,
    multiplier: int = 1,
    num_cols: int = 3,
    direct_only: bool = False,
    skip_junk: bool = True,
    date_labels_ok: bool = False,
    preserve_col_positions: bool = False,
    keep_all_amount_cells: bool = False,
    keep_header_rows: bool = False,
) -> list[RowData]:
    """
    TABLE 요소에서 재무 행 데이터를 추출한다.

    Args:
        table_elem: lxml TABLE 요소
        multiplier: 금액 단위 배수 (1 또는 1000)
        num_cols:   금액 열 수 (사업보고서=3, 반기/분기=2 가능)
        direct_only: True 면 **직접 자식 행만** 읽고 중첩 TABLE 안의 행은 무시한다.
            ★ 필요한 이유: DART 원문 XML 이 깨진 경우(</TABLE> 누락)가 흔해 lxml 이 이후 문서
            전체를 그 표 안쪽에 중첩시킨다. 실측 — DB손해보험 20230927000457 연결 BS 는
            `.//TR` 이 **5,218행**(중첩 TABLE 775개)이지만 **직접 행 51개**가 진짜 재무상태표다.
            기본값 False = 기존 호출자(biz_section·order_backlog 등) 동작 보존.
        skip_junk: True(기본) 면 `_JUNK_ACCOUNT_NAMES`(집계 이중계산 회피용 블록리스트)에 든
            라벨 행을 버린다 — **fact_v2(집계) 파이프라인 동작**. False 면 그 블록리스트를 적용하지
            않는다 — **계층2 report_lines(원문 충실전사)용**: 지분법자본변동·미처분이익잉여금·
            대손충당금·재고 세부 등은 원문 face 라인이므로 전사해야 한다(집계 이중계산 회피는
            계층3 몫). 진짜 열헤더(3개월·회사명 등)는 금액이 없어 자연 미방출되므로 무해하다.
        date_labels_ok: True 면 첫 셀이 날짜여도 데이터 행으로 취급 — **자본변동표(SCE) 전용**.
            상세는 `_is_header_cell(allow_date_label=)` 참고. 기본 False = 기존 동작 보존.
        preserve_col_positions: True 면 앞쪽 빈 셀을 당기지 않고 **열 위치를 그대로 보존**한다 —
            열이 기간이 아니라 축(자본 구성요소 등)인 행렬 표 전용. 기본 False = 기존 동작 보존.
        keep_all_amount_cells: True 면 라벨 뒤의 **모든 셀**을 열 위치 그대로 담는다(숫자가
            아닌 셀도 자리를 차지하고 값은 None). **주석 전용**(2026-07-31 F1).
            ★필요한 이유 — 열 라벨 밀림: 기본 경로는 숫자가 아닌 셀('4.27%'·'일반대(장기)')을
              amount_cells 에서 **빼버려** 열 위치가 앞으로 당겨진다. 그런데 `col_label` 은
              헤더 그리드의 위치로 붙으므로 둘이 어긋난다. 실측(에쎈테크 20150817000851
              14.장기차입금): 원문 [차입처|만기|이자율|당반기말|전기말|대출종류] 인데 '4.27%'
              가 빠져 당반기말 금액 813,559 에 '당반기말현재이자율' 라벨이 붙었다. F1 은 이
              라벨로 단위를 정하므로(비금액 열이면 value_won 을 비운다) 밀림이 곧 오판이다.
              숫자가 아닌 셀은 parse_amount 가 None 이라 **값을 만들지 않는다** — 자리만 잡는다.
        keep_header_rows: True 면 헤더 규칙에 걸린 행을 **버리지 않고** `RowData.header_hint` 에
            규칙 이름을 담아 전사한다. **주석 전용**(F2, 2026-07-31 — 설계안
            `docs/plans/layer2_header_hint_lossless_2026-07-30.md`). 기본 False = 기존 동작.

    Returns:
        RowData 리스트 (헤더 행 제외, 빈 행 제외)
    """
    rows: list[RowData] = []
    row_order = 0

    # TBODY 또는 직접 TR 탐색
    if direct_only:
        from parser.xml.section_detector import table_direct_rows
        trs = table_direct_rows(table_elem)
    else:
        trs = table_elem.findall(".//TR")

    # R19: 이 표에 콤마 다중참조 주석 컬럼이 있는지 한 번만 미리 판정 — 콤마 없는 단일 숫자
    # 후보의 주석 여부는 행 하나로는 못 정하고 이 표 단위 컨텍스트가 있어야 한다(아래
    # _split_label_amounts 호출에 전달). `_table_has_comma_note_column` docstring 참고.
    table_has_note_column = _table_has_comma_note_column(
        [_get_cells(tr) for tr in trs])

    for tr in trs:
        cells = _get_cells(tr)
        if not cells:
            continue

        first_text = cells[0].strip() if cells else ""

        # 헤더/제목/단위 행 감지 → 위치에 관계없이 항상 건너뜀
        # (DART 테이블은 반복 헤더 행 또는 섹션 구분 행이 중간에 나올 수 있음)
        # ★keep_header_rows=True(F2·주석 전용)면 **버리지 않고 규칙 이름만 기록**한다.
        #   행이 기간축인 표에서 '당기말'·'전기초' 는 헤더가 아니라 데이터 행이기 때문 —
        #   판단은 계층3 이 header_hint 를 보고 한다(`_header_rule_name` docstring).
        header_hint = _header_rule_name(first_text, allow_date_label=date_labels_ok)
        if header_hint and not keep_header_rows:
            continue

        # 재무제표 이름만 있는 제목 행 건너뜀 (예: "재무상태표", "포괄손익계산서")
        if _is_fs_title_row(cells):
            continue

        # 계정과목명 + 금액 분리
        if keep_all_amount_cells:
            label, amount_cells = cells[0], list(cells[1:])   # 위치 보존(주석 전용)
        else:
            label, amount_cells = _split_label_amounts(cells, table_has_note_column)

        if not label:
            continue

        # 명백한 메타데이터/레이블 행 건너뜀 (재무 데이터 아님).
        # skip_junk=False(계층2 충실전사)면 집계용 블록리스트를 적용하지 않는다.
        label_clean_check = label.strip()
        if skip_junk and label_clean_check in _JUNK_ACCOUNT_NAMES:
            continue

        # 금액 파싱 (전체 amount_cells 파싱 후 재정렬)
        all_parsed = [parse_amount(ac, multiplier) for ac in amount_cells]

        # 6-column IS 형식 대응: 앞쪽 구조적 빈 셀(None) 제거
        # 예: [None, None, 42647억, None, 43360억] → [42647억, None, 43360억]
        # 조건: amount_cells ≥ 4개 (3-column IS는 영향 없음)
        # ★ preserve_col_positions=True 면 하지 않는다 — 자본변동표처럼 **열이 기간이 아니라
        #   축(자본금/이익잉여금/…)**인 표에서는 선행 공란이 구조적 잡음이 아니라 "이 변동은
        #   그 자본 항목에 영향이 없었다"는 **의미 있는 값**이다. 여기서 당기면 열이 통째로
        #   밀려 이익잉여금 값이 자본금 열로 들어간다(실측: SCE 행 내부정합 95.3% 의 주원인).
        # 원문 문자열은 파싱값과 **같은 인덱스**를 유지해야 한다(value_raw 용) — 아래 재정렬에서
        # 함께 이동시킨다. 따로 움직이면 원문이 다른 열의 값으로 붙는다.
        all_raw: list[str] = list(amount_cells)
        if len(all_parsed) >= 4 and not (preserve_col_positions or keep_all_amount_cells):
            while all_parsed and all_parsed[0] is None:
                all_parsed.pop(0)
                if all_raw:
                    all_raw.pop(0)

        amounts: list[Optional[int]] = []
        raw_amounts: list[str] = []
        for i in range(num_cols):
            amounts.append(all_parsed[i] if i < len(all_parsed) else None)
            raw_amounts.append(all_raw[i] if i < len(all_raw) else "")

        indent = _detect_indent(label)
        label_clean = label.lstrip()  # 들여쓰기 공백 제거

        rows.append(RowData(
            account_name=label_clean,
            amounts=amounts,
            raw_amounts=raw_amounts,
            header_hint=header_hint,
            row_order=row_order,
            is_subtotal=_is_subtotal(label_clean),
            indent_level=indent,
            raw_indent=_first_cell_indent(tr),
        ))
        row_order += 1

    return rows


def _first_cell_indent(tr: etree._Element) -> int:
    """첫 셀 원문의 선행 공백 수(전각 U+3000·NBSP 포함) — 원문 들여쓰기 계층 신호.

    `_get_cells` 는 `.strip()` 으로 셀 텍스트를 다듬어 선행 공백(계층 정보)을 지운다. 여기서는
    첫 데이터 셀의 raw itertext 를 직접 읽되, `<TE>`↔`<P>` 사이의 구조적 개행(`\\n`)만 건너뛰고
    그 뒤의 들여쓰기 공백을 센다. **위치(구조) 판단이지 값 판단이 아니다**(재설계 원칙 유지)."""
    for child in tr:
        tag = child.tag.upper() if isinstance(child.tag, str) else ""
        if tag in ("TD", "TH", "TE", "TU"):
            raw = "".join(child.itertext()).lstrip("\n\r")
            n = 0
            for ch in raw:
                if ch in (" ", "\t", "　", "\xa0"):
                    n += 1
                else:
                    break
            return n
    return 0


def _get_cells(tr: etree._Element) -> list[str]:
    """TR 요소의 모든 셀 텍스트 리스트 반환 (TD, TH, TE, TU)"""
    cells = []
    for child in tr:
        tag = child.tag.upper() if isinstance(child.tag, str) else ""
        if tag in ("TD", "TH", "TE", "TU"):
            text = ''.join(child.itertext()).strip()
            cells.append(text)
    return cells


def _is_cell_element(el: etree._Element) -> bool:
    """True 면 이 자식이 셀(TD/TH/TE/TU)이다 — `_get_cells` 와 같은 태그 집합."""
    tag = el.tag.upper() if isinstance(el.tag, str) else ""
    return tag in ("TD", "TH", "TE", "TU")


def _grid_cell_span(el: etree._Element, attr: str) -> int:
    """COLSPAN/ROWSPAN 값(대소문자 혼용 대응). 없거나 파싱 불가면 1.

    `fin2/extract/report_lines.py::_cell_span` 과 판정 로직이 동일해야 한다 — 헤더 그리드
    복원(`_build_col_labels`)과 이 파일의 본문 확장(`expand_table_grid`)이 서로 다른
    COLSPAN/ROWSPAN 판정을 쓰면 두 좌표계가 어긋난다. `report_lines.py` 가 이미 이 모듈에서
    `extract_rows` 등을 임포트하므로 반대 방향 임포트는 순환이 된다 — 그래서 여기 복제한다.
    """
    for k in (attr, attr.lower(), attr.capitalize()):
        if k in el.attrib:
            try:
                return max(1, int(el.attrib[k]))
            except (TypeError, ValueError):
                return 1
    return 1


@dataclass
class GridCell:
    """확장 그리드(`expand_table_grid`)의 한 칸.

    `inherited=False` — 이 칸이 실제 `<TD>`/`<TH>`/`<TE>`/`<TU>` 원문 셀의 좌상단 origin이다
    (`text`는 그 셀의 원문, `colspan`/`rowspan`은 그 셀의 선언값).
    `inherited=True` — 이 칸엔 이 행 자신의 물리적 셀이 없다. 더 위쪽 행의 ROWSPAN 이
    이어져 채워진 칸이라, `text`/`colspan`/`rowspan`은 **origin 셀의 값을 그대로 복사**해
    "이 칸에 논리적으로 무엇이 있는지"를 보여준다 — 물리적 `<TD>` 가 실제로 여기 있다는
    뜻이 아니다.
    """
    text: str
    grid_row: int
    grid_col: int
    colspan: int
    rowspan: int
    inherited: bool


def expand_table_grid(table_elem: etree._Element) -> list[list[GridCell]]:
    """표를 헤더·본문을 관통하는 **하나의 연속 (row,col) occupied-grid** 로 펼친다.

    `fin2/extract/report_lines.py::_build_col_labels`가 헤더 행에만 해 오던 ROWSPAN/COLSPAN
    그리드 복원을, 본문 행까지 **같은 좌표계로 이어서** 계산한다. 반환값은 TR 순서의
    리스트이고, 각 원소는 그 행이 차지하는 그리드 칸을 왼쪽부터 나열한 `GridCell` 리스트다
    (물리적 칸이든 ROWSPAN 이 이어받은 칸이든 전부 포함) — 그래서 어느 행이든
    `row[k].grid_col` 이 **진짜** 열 위치다. 이 표의 물리적 `<TD>` 등장 순서를 그대로
    열 인덱스로 쓰면(`_get_cells`/`extract_rows` 의 현재 동작) ROWSPAN 이어짐 행·COLSPAN
    병합 라벨 행마다 그 이후 값이 왼쪽으로 밀려 엉뚱한 열에 저장된다 — 부록 A T16·T17,
    R11 참고.

    ★기존 `_get_cells`/`extract_rows` 는 이 함수가 있어도 **동작이 전혀 바뀌지 않는다.**
    이 함수는 새로 추가된 것일 뿐이고, 기존 호출자(biz_section·order_backlog·본문
    report_lines)는 여전히 물리적 위치 기반 경로를 그대로 쓴다. 본문(BS/IS/CF)은 이
    결함의 영향이 실측 0건이므로(`docs/qa/handoff_note_lines_span_misattribution_
    2026-08-07.md` §10) 옵트인 대상이 아니다 — 주석(note)·SCE 경로만 이 함수로 옮겨간다
    (계획 `docs/plans/note_span_fix_plan_2026-08-07.md` Phase 2, T2.3/T2.4 — 이 함수 자체는
    아직 어디서도 호출되지 않는다).

    원형 — `scripts/census_note_span_misattribution.py::analyze_table`(조사 전용 스크립트가
    먼저 이 그리드 워크로 결함 규모를 쟀다). 이 함수는 그 로직을 파이프라인 유틸로 옮긴
    것이다.

    Args:
        table_elem: lxml TABLE 요소

    Returns:
        행(TR)별 `GridCell` 리스트. 직접 TR 이 없는 표는 `[]`.
    """
    from parser.xml.section_detector import table_direct_rows

    trs = table_direct_rows(table_elem)
    # (grid_row, grid_col) → 그 칸을 예약한 origin 셀의 (text, colspan, rowspan).
    # ROWSPAN 이 남은 미래 행이 자기 칸을 건너뛸 때(= "상속" GridCell 을 만들 때) 참조한다.
    occupied: dict[tuple[int, int], tuple[str, int, int]] = {}
    grid_rows: list[list[GridCell]] = []

    for r, tr in enumerate(trs):
        row_cells: list[GridCell] = []
        c = 0
        for el in tr:
            if not _is_cell_element(el):
                continue
            # 이 물리적 셀을 놓기 전, ROWSPAN 이 이어받은 칸을 전부 "상속" 항목으로 채운다
            # (이 루프가 앞쪽 몇 칸을 채우고 나면 텔코웨어 `ROWSPAN=6` 처럼 그 행의 진짜 첫
            #  물리 셀이 grid_col 0 이 아니라 1 에서 시작하게 된다 — 이게 이 함수의 핵심).
            while (r, c) in occupied:
                otext, ocs, ors = occupied[(r, c)]
                row_cells.append(GridCell(otext, r, c, ocs, ors, True))
                c += 1
            text = ''.join(el.itertext()).strip()
            cs = _grid_cell_span(el, "COLSPAN")
            rs = _grid_cell_span(el, "ROWSPAN")
            row_cells.append(GridCell(text, r, c, cs, rs, False))
            for dr in range(rs):
                for dc in range(cs):
                    if dr == 0 and dc == 0:
                        continue  # 이 칸 자체는 방금 물리 셀로 넣었다
                    occupied[(r + dr, c + dc)] = (text, cs, rs)
            c += cs
        # 이 행의 마지막 물리 셀 오른쪽에 남은 ROWSPAN 이어짐 칸도 채운다 — 안 그러면
        # (이 행 자신에겐 그 뒤로 물리 셀이 없는 경우) 그 행의 오른쪽 끝 칸이 그리드에서
        # 누락된다.
        while (r, c) in occupied:
            otext, ocs, ors = occupied[(r, c)]
            row_cells.append(GridCell(otext, r, c, ocs, ors, True))
            c += 1
        grid_rows.append(row_cells)

    return grid_rows


_NOTE_REF_PATTERN = re.compile(r'^[1-9]\d{0,2}(,[1-9]\d{0,2})*$')
# 정상 3자리 그룹 금액(예: "2,433", "496,412,633,753"). 주석 교차참조와 구별용.
# 주석은 1~2자리 그룹의 비정규 나열("2,4,32,34,35,36")이라 이 패턴에 안 맞는다.
_AMOUNT_GROUPED_PATTERN = re.compile(r'^\(?\d{1,3}(,\d{3})+\)?$')


def _table_has_comma_note_column(rows_cells: list[list[str]]) -> bool:
    """표 전체를 한 번 미리 훑어, **콤마로 구분된 다중 주석참조**("2,4,32,34,35,36")가 라벨
    바로 다음 칸(i==1)에 실제로 있는 행이 하나라도 있는지 판정한다.

    ★왜 필요한가(R19): 콤마 없는 단일 숫자("11", "654")는 행 하나의 셀 내용만 봐서는 "진짜
    주석번호"인지 "콤마 없는 실제 소액"인지 원리적으로 구별 불가능 — 실측 반례: 한양증권
    "Ⅷ.무형자산 | 11 | 1,660,475,560 | 1,660,475,560"(같은 표 다른 행에 "10,37","3,4,5,8,39"
    같은 진짜 다중주석이 있어 "11"도 진짜 주석) vs 진원생명과학 "7.미지급배당금(주석15) | 512 |
    2,174 | 455,208 | 455,208"(표 전체에 주석 컬럼 자체가 없음 — 주석은 라벨에 인라인 표기,
    "512"는 진짜 금액). 둘은 셀 모양이 완전히 같아 행 단독으로는 판정 불가 — **같은 표의
    다른 행에 콤마 다중참조가 하나라도 있는지**가 유일한 신뢰 가능한 신호다. 콤마 다중참조는
    항상 진짜 주석(0건 오탐, root-cause 문서 §단일 주석번호 추가조사)이므로 이 시그널로
    "이 표는 주석 컬럼을 쓴다"를 판정한 뒤, 그 표의 콤마 없는 단일 숫자 후보에도 적용한다.
    """
    for cells in rows_cells:
        if len(cells) < 2:
            continue
        cell_nospace = _TRAIL_DECOR_RE.sub('', cells[1].replace(' ', ''))
        if (',' in cell_nospace
                and _NOTE_REF_PATTERN.match(cell_nospace)
                and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
            return True
    return False


def _split_label_amounts(
    cells: list[str], table_has_note_column: bool = False,
) -> tuple[str, list[str]]:
    """
    셀 리스트에서 계정과목명(첫 번째 비숫자 셀)과 금액 셀을 분리한다.

    DART XML 구조:
      [계정과목명, 당기금액, 전기금액, 전전기금액, (주석)]

    6-column IS 구조 (금융업 보험/증권 등, 업종 무관):
      [계정과목명, 주석번호, 당기명세, 당기합계, 전기명세, 전기합계]
      → 주석번호는 금액 셀로 오인하지 않도록 건너뜀. 판정은 두 층:
        1) 콤마구분 다중 그룹("4,28", "2,4,32,34,35,36")은 **행 하나만 보고도** 항상 주석으로
           확정(정상 3자리그룹 금액 "2,433"과 패턴이 달라 오탐 없음, 실측 0건).
        2) 콤마 없는 단일 숫자("34")는 행 하나로는 주석인지 실제 소액금액인지 구별 불가 —
           R19: `table_has_note_column`(호출측이 같은 표를 한 번 미리 훑어 콤마 다중참조가
           있는지로 판정, `_table_has_comma_note_column` 참고)이 True 인 표에서만 주석으로
           본다. 실측 반례(한양증권 vs 진원생명과학, 셀 모양 동일·정답 반대)로 행 단독 판정이
           불가능함을 확인 — `docs/PARSING_RULES.md` R19.
      두 경우 모두 **라벨 바로 다음 칸(i==1)에서만** 판정한다 — 아니면 콤마 없는 소액이
      연달아 나오는 행(예: "992 | 766")에서 둘 다 드롭되는 연쇄 오탐이 생긴다.
    """
    label = ""
    amount_cells: list[str] = []

    for i, cell in enumerate(cells):
        if i == 0:
            # 첫 셀은 항상 계정과목명
            label = cell
        else:
            cell_nospace = cell.replace(' ', '')             # 쉼표 보존(주석 판정용)
            # 합계행 밑줄 장식(숫자 뒤 '====' 등) 제거 — 숫자 셀 인식용(parse_amount 도 동일 처리).
            cell_nospace = _TRAIL_DECOR_RE.sub('', cell_nospace)
            cell_stripped = cell_nospace.replace(',', '')      # 쉼표 제거(금액 판정용)
            # 라벨 바로 다음 칸(i==1)이 주석번호 패턴이면 건너뜀 — 콤마 다중참조는 항상,
            # 콤마 없는 단일 숫자는 이 표에 진짜 주석 컬럼이 있다고 확인됐을 때만(R19).
            # ⚠ 반드시 쉼표 보존 문자열로 판정 — 쉼표 제거 시 "2,4,32,…"→"243234…" 로
            #    금액과 혼동(컬럼 1칸 밀림 버그). 정상 3자리그룹 금액("2,433")은 주석 아님.
            if (i == 1
                    and not amount_cells
                    and _NOTE_REF_PATTERN.match(cell_nospace)
                    and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)
                    and (',' in cell_nospace or table_has_note_column)):
                continue
            # 숫자 패턴이거나 공란이면 금액 셀
            if _NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
                amount_cells.append(cell)
            # 숫자가 아닌 추가 텍스트 → 무시

    return label, amount_cells


# 셀 전체가 '기간(개월)' 열 헤더인 경우만: '3개월' '(3개월)' '당분기(3개월)' '3개월 누적' 등.
# 라벨 본문에 '개월' 이 섞인 데이터 행('12개월 기대신용손실측정 …')은 여기 걸리지 않는다.
_PERIOD_MONTH_CELL = re.compile(
    r'[\s()]*(?:(?:당|전)?(?:분|반)?기?)?[\s()]*\d+\s*개월[\s()]*(?:누적)?[\s()]*'
)


def _is_header_cell(text: str, allow_date_label: bool = False) -> bool:
    """첫 셀이 헤더/단위/기수 표기이면 True — 판정은 `_header_rule_name` 이 한다(동작 동일).

    ★F2(2026-07-31): 규칙은 그대로 두고 **결과를 쓰는 방식만** 열었다. 어느 규칙에 걸렸는지를
      밖(=`extract_rows(keep_header_rows=True)`)에서 `header_hint` 로 전사할 수 있게 하기 위함.
    """
    return _header_rule_name(text, allow_date_label) is not None


def _header_rule_name(text: str, allow_date_label: bool = False) -> Optional[str]:
    """첫 셀이 헤더 표기면 **어느 규칙에 걸렸는지**(고정 이름), 아니면 None.

    왜 이름을 돌려주나 — 계층2 는 "판단 없이 충실전사"가 원칙인데 이 규칙들은 집계가 필요했던
    구 fact_v2 파이프라인의 유산이라, 규칙이 틀리면 **행이 조용히 사라진다.** 실측
    (`docs/plans/layer2_header_hint_lossless_2026-07-30.md`): 유형자산 증감표처럼 행이 기간축인
    주석 표에서 '당기말'·'전기초' 는 열 헤더가 아니라 **데이터 행 라벨**이고 금액 4 개가 통째로
    드롭됐다(정방향 미도달 셀의 95%가 '기간라벨'·'날짜' 두 규칙).
    ⇒ 이름을 `header_hint` 로 전사해 두면 판단은 계층3 이 표별로 하고, 조사도 원문 재파싱 대신
      SQL 로 된다. 이름은 **고정 집합**이라 새 표 구조를 만날 때마다 늘어나지 않는다
      (규칙에 안 걸리면 hint=NULL 인 평범한 데이터 행이 될 뿐).

    DART 테이블에서 반복 출현하는 비데이터 행 패턴을 모두 포함.

    allow_date_label: True 면 "기간 날짜" 규칙만 끈다 — **자본변동표(SCE) 전용**.
        SCE 는 기초/기말 잔액 행의 라벨이 날짜다("2023.01.01 (기초자본)"). BS/IS/CF 에서
        이 규칙은 기간 헤더 행을 거르는 올바른 동작이지만, SCE 에 그대로 적용하면 그 표의
        **앵커 행이 통째로 사라진다**(실측 2,519행/250보고서 — 기초+Σ변동=기말 검산 불가).
        날짜 '범위' 헤더("2023.01.01~2023.12.31")는 아래 별도 규칙이 계속 잡으므로 안전하다.
    """
    if not text:
        return None
    # 기간 날짜: "2023.12.31", "2023-12-31", "2023년"
    # ★2026-07-30: 날짜/숫자·구두점을 걷어낸 뒤 **한글이 남으면 데이터 행**이다. 종전에는
    #   `search` 라 라벨 어디에든 4자리 연도가 있으면 헤더로 봤고, 그래서
    #   '지앤피2025-01호벤처투자조합'(25.00|1,500|1,451|1,451) 같은 실데이터 행이 통째로
    #   사라졌다(전수 정방향 조사에서 발견).
    if not allow_date_label and re.search(r'\d{4}[.\-년]', text) \
            and not re.search(r'[가-힣]', re.sub(r'[\d.\-년월일\s()~／/]', '', text)):
        return "날짜"
    # 기수 표기: "제 72 기", "제72기"
    # ★2026-08-16(R28): 위 "날짜" 규칙과 같은 부분일치 함정이 여기도 있었다 — `search` 라
    #   라벨 어디에든 "제N기" 가 있으면 헤더로 봐서, "XV.연결당기순이익 (연결주당경상이익:
    #   제54기: 1,713원 제53기: 2,118원)" 같은 실데이터 헤드라인 행이나 배당주석의
    #   "배당금(율) 제36기: 80원(16%) 제35기: 80원(16%)" 같은 실데이터 행이 통째로
    #   드롭됐다(`note_lines` 실측: header_hint='기수' 로 잡힌 행 중 상당수가 원/% 를 포함한
    #   진짜 데이터 행). 진짜 기수 헤더 셀("제 21기(당기)", "제59기 기초(2016.1.1)")은
    #   원/% 를 포함하지 않는다 — 이 신호로 가른다(날짜 규칙처럼 잔여 한글 검사 대신 원/%
    #   포함 여부를 쓴 이유: "당기"·"기초"·"1분기말" 같은 정상 부기 주석까지 잔여 한글로
    #   걸려 헤더 오분류가 나기 때문 — 원/% 는 오탐 없이 데이터 행만 정확히 가른다).
    if re.search(r'제\s*\d+\s*기', text) and not re.search(r'원|%', text):
        return "기수"
    # 단위 표기: "(단위 : 원)", "단위:천원"
    if re.search(r'단위\s*[:\(]', text):
        return "단위표기"
    # 열 헤더: "구 분", "구분", "과 목", "과목"
    if re.fullmatch(r'[구과]\s*[분목]', text):
        return "구분과목"
    # 기간 표기 열 헤더: "3개월", "6개월", "당분기(3개월)" 등 IS 분기 표 컬럼 헤더
    # ★2026-07-30: 셀 **전체**가 기간 표기일 때만. 종전 `search` 는 라벨 안에 '개월' 이
    #   들어가기만 하면 잡아 '12개월 기대신용손실측정 금융자산으로 대체'(대손충당금 변동
    #   주석의 실데이터 행)를 통째로 버렸다.
    if _PERIOD_MONTH_CELL.fullmatch(text):
        return "N개월"
    # 분기 레이블: "1분기", "2분기", "3분기", "4분기"
    if re.fullmatch(r'\d분기', text):
        return "N분기"
    # 날짜 범위 헤더: "2023.01.01~2023.03.31"
    if re.search(r'\d{4}\.\d{2}\.\d{2}[~\-～]', text):
        return "날짜범위"
    # "(기준일 :" 으로 시작하는 NOTE 날짜 표기
    if text.startswith("(기준일") or text.startswith("기준일"):
        return "기준일"
    # NOTE 테이블 period-end 열 헤더: "당기말", "전기말", "당기초", "당분기말", "당반기말" 등
    if re.fullmatch(r'(당기|전기|당기초|전기초|당분기|전분기|당반기|전반기)(말|초)?', text):
        return "기간라벨"
    # NOTE 공정가치 계층 열 헤더: "수준 1", "수준 2", "수준 3"
    if re.fullmatch(r'수준\s*[123]', text):
        return "공정가치수준"
    # 빈 값이거나 "-"만 있는 첫 셀
    if re.fullmatch(r'[\s\-\─\—\―　]*', text):
        return "빈셀"
    return None


# 재무제표 이름만 있는 단독 행 (섹션 제목이 TABLE 안에 포함된 경우)
_FS_TITLE_PATTERNS = re.compile(
    r'^(연결|별도)?\s*(재무상태표|손익계산서|포괄손익계산서|현금흐름표|'
    r'자본변동표|이익잉여금처분계산서)\s*$'
)


def _is_fs_title_row(cells: list[str]) -> bool:
    """
    재무제표 이름만 있는 제목 행 감지.
    예: ["재무상태표"], ["연결 포괄손익계산서"]
    → 금액 열이 없고 첫 셀이 재무제표명이면 제목 행으로 판단.
    """
    if not cells:
        return False
    first = cells[0].strip()
    if _FS_TITLE_PATTERNS.match(first):
        # 나머지 셀이 모두 비어 있거나 숫자가 아닌 경우
        rest_are_empty = all(
            not c.strip() or re.fullmatch(r'[\s\-\─\—\―　]*', c.strip())
            for c in cells[1:]
        )
        return rest_are_empty
    return False


def _is_subtotal(label: str) -> bool:
    """합계/소계 행 판단"""
    label_norm = normalize_account_name(label)
    return any(kw in label_norm for kw in _SUBTOTAL_KEYWORDS)


def _detect_indent(label: str) -> int:
    """
    앞쪽 공백 수로 들여쓰기 수준 추정
    (DART XML은 공백으로 계층 구조를 표현하는 경우가 많음)
    """
    count = 0
    for ch in label:
        if ch in (' ', '\t', '　'):
            count += 1
        else:
            break
    # 공백 2~3개당 1 레벨
    return min(count // 2, 5)
