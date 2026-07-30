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

    for tr in trs:
        cells = _get_cells(tr)
        if not cells:
            continue

        first_text = cells[0].strip() if cells else ""

        # 헤더/제목/단위 행 감지 → 위치에 관계없이 항상 건너뜀
        # (DART 테이블은 반복 헤더 행 또는 섹션 구분 행이 중간에 나올 수 있음)
        if _is_header_cell(first_text, allow_date_label=date_labels_ok):
            continue

        # 재무제표 이름만 있는 제목 행 건너뜀 (예: "재무상태표", "포괄손익계산서")
        if _is_fs_title_row(cells):
            continue

        # 계정과목명 + 금액 분리
        label, amount_cells = _split_label_amounts(cells)

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
        if len(all_parsed) >= 4 and not preserve_col_positions:
            while all_parsed and all_parsed[0] is None:
                all_parsed.pop(0)

        amounts: list[Optional[int]] = []
        for i in range(num_cols):
            amounts.append(all_parsed[i] if i < len(all_parsed) else None)

        indent = _detect_indent(label)
        label_clean = label.lstrip()  # 들여쓰기 공백 제거

        rows.append(RowData(
            account_name=label_clean,
            amounts=amounts,
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


_NOTE_REF_PATTERN = re.compile(r'^[1-9]\d{0,2}(,[1-9]\d{0,2})*$')
# 정상 3자리 그룹 금액(예: "2,433", "496,412,633,753"). 주석 교차참조와 구별용.
# 주석은 1~2자리 그룹의 비정규 나열("2,4,32,34,35,36")이라 이 패턴에 안 맞는다.
_AMOUNT_GROUPED_PATTERN = re.compile(r'^\(?\d{1,3}(,\d{3})+\)?$')


def _split_label_amounts(cells: list[str]) -> tuple[str, list[str]]:
    """
    셀 리스트에서 계정과목명(첫 번째 비숫자 셀)과 금액 셀을 분리한다.

    DART XML 구조:
      [계정과목명, 당기금액, 전기금액, 전전기금액, (주석)]

    6-column IS 구조 (금융업 보험/증권):
      [계정과목명, 주석번호, 당기명세, 당기합계, 전기명세, 전기합계]
      → 주석번호("34", "4,28" 등 소정수)는 금액 셀로 오인하지 않도록 건너뜀
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
            # 첫 번째 숫자-유사 셀이 주석번호 패턴(소정수 나열)이면 건너뜀.
            # 예: "34", "4,28", "2,4,32,34,35,36"(금융업 다중 주석참조).
            # ⚠ 반드시 쉼표 보존 문자열로 판정 — 쉼표 제거 시 "2,4,32,…"→"243234…" 로
            #    금액과 혼동(컬럼 1칸 밀림 버그). 정상 3자리그룹 금액("2,433")은 주석 아님.
            if (not amount_cells
                    and _NOTE_REF_PATTERN.match(cell_nospace)
                    and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)):
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
    """
    첫 번째 셀이 헤더/단위/기수 표기이면 True.
    DART 테이블에서 반복 출현하는 비데이터 행 패턴을 모두 포함.

    allow_date_label: True 면 "기간 날짜" 규칙만 끈다 — **자본변동표(SCE) 전용**.
        SCE 는 기초/기말 잔액 행의 라벨이 날짜다("2023.01.01 (기초자본)"). BS/IS/CF 에서
        이 규칙은 기간 헤더 행을 거르는 올바른 동작이지만, SCE 에 그대로 적용하면 그 표의
        **앵커 행이 통째로 사라진다**(실측 2,519행/250보고서 — 기초+Σ변동=기말 검산 불가).
        날짜 '범위' 헤더("2023.01.01~2023.12.31")는 아래 별도 규칙이 계속 잡으므로 안전하다.
    """
    if not text:
        return False
    # 기간 날짜: "2023.12.31", "2023-12-31", "2023년"
    # ★2026-07-30: 날짜/숫자·구두점을 걷어낸 뒤 **한글이 남으면 데이터 행**이다. 종전에는
    #   `search` 라 라벨 어디에든 4자리 연도가 있으면 헤더로 봤고, 그래서
    #   '지앤피2025-01호벤처투자조합'(25.00|1,500|1,451|1,451) 같은 실데이터 행이 통째로
    #   사라졌다(전수 정방향 조사에서 발견).
    if not allow_date_label and re.search(r'\d{4}[.\-년]', text) \
            and not re.search(r'[가-힣]', re.sub(r'[\d.\-년월일\s()~／/]', '', text)):
        return True
    # 기수 표기: "제 72 기", "제72기"
    if re.search(r'제\s*\d+\s*기', text):
        return True
    # 단위 표기: "(단위 : 원)", "단위:천원"
    if re.search(r'단위\s*[:\(]', text):
        return True
    # 열 헤더: "구 분", "구분", "과 목", "과목"
    if re.fullmatch(r'[구과]\s*[분목]', text):
        return True
    # 기간 표기 열 헤더: "3개월", "6개월", "당분기(3개월)" 등 IS 분기 표 컬럼 헤더
    # ★2026-07-30: 셀 **전체**가 기간 표기일 때만. 종전 `search` 는 라벨 안에 '개월' 이
    #   들어가기만 하면 잡아 '12개월 기대신용손실측정 금융자산으로 대체'(대손충당금 변동
    #   주석의 실데이터 행)를 통째로 버렸다.
    if _PERIOD_MONTH_CELL.fullmatch(text):
        return True
    # 분기 레이블: "1분기", "2분기", "3분기", "4분기"
    if re.fullmatch(r'\d분기', text):
        return True
    # 날짜 범위 헤더: "2023.01.01~2023.03.31"
    if re.search(r'\d{4}\.\d{2}\.\d{2}[~\-～]', text):
        return True
    # "(기준일 :" 으로 시작하는 NOTE 날짜 표기
    if text.startswith("(기준일") or text.startswith("기준일"):
        return True
    # NOTE 테이블 period-end 열 헤더: "당기말", "전기말", "당기초", "당분기말", "당반기말" 등
    if re.fullmatch(r'(당기|전기|당기초|전기초|당분기|전분기|당반기|전반기)(말|초)?', text):
        return True
    # NOTE 공정가치 계층 열 헤더: "수준 1", "수준 2", "수준 3"
    if re.fullmatch(r'수준\s*[123]', text):
        return True
    # 빈 값이거나 "-"만 있는 첫 셀
    if re.fullmatch(r'[\s\-\─\—\―　]*', text):
        return True
    return False


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
