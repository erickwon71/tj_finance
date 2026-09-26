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

from parser.common.amount_normalizer import (parse_amount, normalize_account_name,
                                             strip_cell_whitespace, _TRAIL_DECOR_RE,
                                             _is_complete_number)


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
    # amounts 와 같은 인덱스: True 면 그 칸의 원본이 `<TE ACODE=...>`인데 `ACONTEXT` 속성이
    # 없는 셀 — DART 원문이 스스로 "이 기간 미공시"라 밝힌 것(§5.4, `_cell_acontext_missing`
    # 참고). `<TD>`(비XBRL) 등 신호가 없는 칸은 항상 False. 소비측(text.py/report_lines.py의
    # 선두 None 절삭)이 "파서 아티팩트로 생긴 선두공백"과 "원문이 실제로 비운 것"을 구분하는 데
    # 쓴다 — 근거: docs/plans/gateb_trade_payables_classB_stale_column_investigation_
    # 2026-08-29.md §5~6.
    acontext_missing: list[bool] = field(default_factory=list)
    # 헤더 판정 규칙 이름(`_header_rule_name`) — `keep_header_rows=True` 로 뽑았을 때만 채워진다.
    # 값이 있으면 "이 행은 헤더 규칙에 걸렸다"는 **관찰**이지 "헤더다"라는 판단이 아니다(F2).
    header_hint: Optional[str] = None
    row_order: int = 0
    is_subtotal: bool = False      # 합계/소계 행 여부
    indent_level: int = 0          # 들여쓰기 수준 (0=최상위, 1=하위...) — _detect_indent(//2)
    raw_indent: int = 0            # 첫 셀 원문 선행 공백 수(전각 U+3000 포함, strip 전).
    # ★ indent_level 은 _get_cells 가 strip 한 뒤라 항상 0(사문화). raw_indent 는 원문 들여쓰기를
    #   그대로 보존한다 — 계층2 report_lines 의 section_path(하위섹션 tree) 산출용.


# ★R152(2026-09-20) — 금융업(은행·증권·보험)은 **보충 표기**를 재무제표 본문 안에 함께
#   인쇄한다: 이익잉여금 밑에 "(대손준비금 적립액)/(대손준비금 적립예정금액)",
#   당기순이익 밑에 "대손준비금 반영후 조정이익/비상위험준비금 반영후 조정이익".
#   원문이 이 3개 논리행을 **물리적으로 <TR> 1개**에 담고(HEIGHT=76~99 = 3줄),
#   라벨 3개와 금액 3개가 각각 한 칸에 병합돼 온다.
_SUPPLEMENTARY_RESERVE_RE = re.compile(r"대손준비금|비상위험준비금")

# 금액다움 — 천단위 콤마 묶음이 있거나 4자리 이상. 주석번호(1~3자리 맨숫자)를 배제한다.
_AMOUNT_LIKE_RE = re.compile(
    r"^[(\[]?\s*[-−△▲]?\s*(?:\d{1,3}(?:,\d{3})+|\d{4,})[\d,\.]*[)\]]?,?$")

# 공백 없이 괄호로 이어붙은 압축칸의 **선행 본항목** — '1,828,134(13,701)(2,886)'.
#
# ★R152-b(2026-09-23) — 보충표기 중 **값이 0 인 것을 붙임표로 찍는** 변형을 허용한다.
#   실측: 우리금융지주 20200330004490 [별도] BS '5. 이익잉여금 (대손준비금 적립액)
#   (대손준비금 전입필요액) (대손준비금 전입예정액)' 행의 금액칸이
#   `'623,930- (692)(692)'` 다. 보충표기 3개 중 첫째(적립액)가 0 이라 `-` 로 찍혔고,
#   그래서 본항목 바로 뒤가 `(` 가 아니라 `-` 라 이 정규식이 빗나갔다 → 칸이 결측이 되고
#   **이익잉여금 행이 통째로 유실**됐다(캠페인 이슈#32, camp_run 발견).
#   붙임표/전각 대시는 한국 재무제표에서 0(해당없음)의 관용 표기다. 버릴 값이므로
#   자리만 건너뛴다. 라벨 게이트(대손준비금·비상위험준비금)가 이미 좁히고 있어
#   일반 금액칸에는 닿지 않는다.
_COMPACTED_PAREN_HEAD_RE = re.compile(
    r"^([-−△▲]?\s*(?:\d{1,3}(?:,\d{3})+|\d{4,}))\s*[-−–—]?\s*\(")


def _first_of_compacted_supplementary_cell(cell_text: str) -> str:
    """압축된 보충표기 칸에서 **본항목 값(첫 토큰)** 만 남긴다.

    ## 왜 필요한가

    `parse_amount` 의 R1 가드는 "한 셀에 온전한 숫자가 둘 이상이면 어느 것이 이 셀
    값인지 원문이 말하지 않으므로 결측"으로 처리한다(날조 방지, 정당한 규칙). 그런데
    이 서식에서는 **원문이 말해준다** — 라벨이 [본항목, 보충1, 보충2] 순이고 금액도
    같은 순서다. 그래서 첫 토큰이 본항목 값이다. 가드를 그대로 두면 **자본/손익 본항목
    행이 통째로 유실**된다.

    ## 첫 토큰 = 본항목 이라는 것의 산술 검증 (2026-09-20)

    · 대신증권 20150515002053 [연결] BS `'4. 연결이익잉여금(주석25) (대손준비금 적립액)
      (대손준비금 적립예정금액)'` / 칸 `'581,929,430 5,320,412647,720'`
      → 지배기업의 소유주지분 1,632,979,218 − (자본금 434,867,000 + 연결자본잉여금
        694,981,258 + 연결기타포괄손익누계액 99,813,409 + 자본조정 △178,611,879)
        = **581,929,430** = 첫 토큰. (단위 천원)
    · 코리안리 20150515002691 [연결] IS `'Ⅷ. 분기연결순이익 대손준비금 반영후 조정이익
      비상위험준비금 반영후 조정이익(손실)'` / 칸
      `'60,042,793,551 54,525,604,742 40,084,010,260'`
      → 법인세비용차감전순이익 79,277,840,399 − 법인세비용 19,235,046,848
        = **60,042,793,551** = 첫 토큰.

    두 건 모두 **독립 산술로 정확히 일치**한다 — 순서 가정이 맞다는 실측 근거다.

    ## 하지 않는 것

    보충표기 값(둘째·셋째 토큰)은 **버린다**. 라벨 경계가 원문 마크업에 표시돼 있지
    않아(코리안리는 TD 가 평문 한 덩어리) 어느 값이 어느 보충 이름인지 단정할 수 없고,
    애초에 4대 재무제표 항목이 아니다. 라벨도 원문 그대로(병합된 채) 남긴다 — 쪼개면
    그게 추측이 된다(R0/R6 짐작 금지).

    구분자 없이 이어붙은 칸(`'576,044,2464,652,625667,787'`, 대신증권 전기열)은 토큰이
    1개라 여기서 손대지 않고 종전대로 결측이 된다 — 자릿수 경계가 원문에 없으므로
    복원하면 날조다. BS 는 당기열만 적재하므로 실질 영향도 없다.

    ★조건은 **첫 토큰만** 온전한 숫자일 것이다(뒤 토큰은 안 본다). 대신증권 당기열
    `'581,929,430 5,320,412647,720'` 은 둘째 토큰의 콤마 묶음이 깨져 있어(412647 = 6자리)
    "모든 토큰이 온전한 숫자" 조건으로는 걸리지 않았다. 뒤 토큰은 버릴 값이므로 그 상태를
    따질 이유가 없다 — 필요한 것은 "첫 토큰이 읽을 수 있는 금액인가" 뿐이다.

    ★★그리고 첫 토큰은 **금액다워야** 한다(천단위 콤마 묶음이 있거나 4자리 이상).
      이 가드가 없으면 **주석번호를 금액으로 날조**한다 — 실측: 미래에셋증권
      20150515001242 의 `'5. 이익잉여금 (대손준비금 적립액) (대손준비금 적립예정액)'` 행은
      주석칸이 `'26, 27'`(주석 26번·27번)이다. 라벨 게이트에 걸리므로 첫 토큰 `'26,'` 이
      그대로 채택돼 26 × 단위배수 라는 값이 생긴다. 스코프 스캔 599건에서 이 패턴이
      압축칸 6개 중 2개였다 — 드물지 않다.
    """
    toks = cell_text.split()

    # ★R152-c(2026-09-23, camp_run 이슈#41) — 첫 토큰이 콤마로 끝나 아직 안 끝난
    #   숫자 조각일 수 있다. 원인은 R150 과 같다(콤마 바로 뒤가 공백/개행) — 다만
    #   여기서는 그 공백이 *셀 경계*가 아니라 **같은 셀 안, `<SPAN>` 경계 사이의
    #   원문 개행**이다. 실측: 미래에셋증권 20160516002286 [연결] BS `5. 이익잉여금`
    #   행 — 원문이 `<TD>1,\n<SPAN>958,360&cr;</SPAN>...` 로 찍혀 본항목 금액이
    #   `'1,'` 과 `'958,360'` 으로 쪼개진 채 이 함수에 들어온다. `_get_cells` 가
    #   `itertext()` 로 그 개행을 그대로 보존하기 때문. 같은 필링 [별도] BS 의 같은
    #   행은 이 서식이 아니라서(평문 TD, SPAN 없음) 멀쩡히 뽑혔다 — 그래서 연결만
    #   깨지고 별도는 안 깨진 비대칭이 나온다. R150 과 같은 방식으로 콤마로 끝나는
    #   선행 토큰을 다음 토큰과 이어붙인다.
    if len(toks) >= 2 and toks[0].endswith(","):
        joined = toks[0] + toks[1]
        if _is_complete_number(joined):
            toks = [joined] + toks[2:]

    if len(toks) >= 2 and _is_complete_number(toks[0]) and _AMOUNT_LIKE_RE.match(toks[0]):
        return toks[0]

    # ★변형 — 공백 없이 **괄호로 이어붙은** 서식: '1,828,134(13,701)(2,886)'.
    #   본항목이 먼저 괄호 없이 오고, 보충 두 값이 괄호로 붙는다(실측: 미래에셋증권
    #   20150515001242 [연결]/[별도] BS 이익잉여금 — 공백이 없어 위 토큰 분해로는 안
    #   걸리고 종전엔 통째로 결측이었다). 선행 금액이 온전할 때만 그 앞부분을 취한다 —
    #   음수를 괄호로 표기한 본항목은 셀이 '(' 로 시작하므로 여기 걸리지 않는다(무해).
    head = _COMPACTED_PAREN_HEAD_RE.match(cell_text.strip())
    if head and _AMOUNT_LIKE_RE.match(head.group(1)):
        return head.group(1)
    return cell_text


def extract_rows(
    table_elem: etree._Element,
    multiplier: int = 1,
    num_cols: int = 3,
    direct_only: bool = False,
    skip_junk: bool = True,
    date_labels_ok: bool = False,
    preserve_col_positions: bool = False,
    keep_all_amount_cells: bool = False,
    rcept_no: Optional[str] = None,
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
    # R65(2026-09-02): 콤마 다중참조 신호는 "매 행이 주석을 하나씩만 인용"하는 표에서
    # 영원히 False로 남는다(콤마가 표 안에 단 한 번도 안 나옴) — 이때 R19 안전장치가 아예
    # 발동을 안 해 주석번호가 진짜 금액으로 오채택된다. 헤더 `<TH>`에 "주석" 텍스트가 있으면
    # 콤마 여부와 무관하게 이 표가 구조적으로 주석 컬럼을 둔다는 훨씬 신뢰도 높은 신호이므로
    # OR로 병행한다(`_table_has_note_header` 참고, 설계
    # docs/plans/note_ref_multicol_compaction_value_corruption_design_2026-09-02.md §5.1).
    table_has_note_column = (
        _table_has_comma_note_column([_get_cells(tr) for tr in trs])
        or _table_has_note_header(trs))

    for tr in trs:
        cells = _get_cells(tr)
        if not cells:
            continue
        cells_el = _get_cell_elements(tr)

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
            cell_flags = [_cell_acontext_missing(el) for el in cells_el[1:]]
        else:
            label, amount_cells, cell_flags = _split_label_amounts_ex(
                cells, table_has_note_column, cells_el)

        if not label:
            continue

        # 명백한 메타데이터/레이블 행 건너뜀 (재무 데이터 아님).
        # skip_junk=False(계층2 충실전사)면 집계용 블록리스트를 적용하지 않는다.
        label_clean_check = label.strip()
        if skip_junk and label_clean_check in _JUNK_ACCOUNT_NAMES:
            continue

        # ★R152(2026-09-20) — 금융업 보충표기가 본항목과 **같은 칸**에 압축된 행.
        #   `_first_of_compacted_supplementary_cell` docstring 에 근거·검산.
        if _SUPPLEMENTARY_RESERVE_RE.search(label):
            amount_cells = [_first_of_compacted_supplementary_cell(ac)
                            for ac in amount_cells]

        # ★R158(2026-09-22) — 천단위 구분자가 마침표로 깨진 셀을 **같은 행의 정수
        #   칸과 대조해** 복원한다. 짝이 없으면 손대지 않는다(주당손익류 정상 소수
        #   보호). 근거·실측은 `_repair_dot_grouped_cells` docstring.
        # ★R159 — 원문 오타 교정을 **복원보다 먼저** 적용한다(교정된 셀은 정상
        #   정수가 되므로 R158 이 건드릴 일이 없어진다).
        amount_cells = apply_source_typo_fixes(amount_cells, rcept_no)
        amount_cells = _repair_dot_grouped_cells(amount_cells, label)

        # 금액 파싱 (전체 amount_cells 파싱 후 재정렬)
        all_parsed = [parse_amount(ac, multiplier) for ac in amount_cells]
        # ★R160 — 해결되지 않은 마침표 셀은 **값을 버린다**(결측). 원문 텍스트는
        #   `raw_amounts` 에 그대로 남겨 보고·감사가 가능하게 한다.
        for _i in unresolved_dot_cell_indices(amount_cells, label):
            if _i < len(all_parsed):
                all_parsed[_i] = None

        # 6-column IS 형식 대응: 앞쪽 구조적 빈 셀(None) 제거
        # 예: [None, None, 42647억, None, 43360억] → [42647억, None, 43360억]
        # 조건: amount_cells ≥ 4개 (3-column IS는 영향 없음)
        # ★ preserve_col_positions=True 면 하지 않는다 — 자본변동표처럼 **열이 기간이 아니라
        #   축(자본금/이익잉여금/…)**인 표에서는 선행 공란이 구조적 잡음이 아니라 "이 변동은
        #   그 자본 항목에 영향이 없었다"는 **의미 있는 값**이다. 여기서 당기면 열이 통째로
        #   밀려 이익잉여금 값이 자본금 열로 들어간다(실측: SCE 행 내부정합 95.3% 의 주원인).
        # ★R86 후속(2026-09-09) — `table_has_note_column`도 요구한다. report_lines.py::
        #   _emit_section_lines()의 else 분기(선두 None 절삭)와 **동형 결함**이 여기 하나 더
        #   있었다: 4열 이상인 표(예 삼성전자 2017Q1 [당기1분기,전기1분기,전기,전전기] 4열 CF —
        #   `_interim_cumulative_cols()`가 3개월/누적 2단 헤더를 못 찾아 cum_map=None →
        #   preserve_col_positions=False)에서, 원문이 당기(또는 당기+전기) 컬럼을 진짜로
        #   비워둔 행이 이 절삭에 걸려 전기/전전기 값이 당기 열로 둔갑한다(실측: rcpNo=
        #   20170515003806 별도·연결 현금흐름표 "단기매도가능금융자산의 처분"·"자기주식의
        #   처분" 등 — 사용자가 원문대조로 발견). else 분기와 **같은 근거**(주석참조 컬럼이
        #   있는 표에서만 이 절삭의 원 동기 사례가 성립, classB §5.1)로 같은 신호를 적용 —
        #   주석 컬럼이 없는 표는 절삭하지 않고 결측으로 남긴다. `table_has_note_column`은
        #   바로 위에서 표 하나당 한 번 이미 계산해둔 값이라 추가 비용 없음. 근거:
        #   docs/PARSING_RULES.md R86.
        # 원문 문자열은 파싱값과 **같은 인덱스**를 유지해야 한다(value_raw 용) — 아래 재정렬에서
        # 함께 이동시킨다. 따로 움직이면 원문이 다른 열의 값으로 붙는다.
        all_raw: list[str] = list(amount_cells)
        all_flags: list[bool] = list(cell_flags)
        if (len(all_parsed) >= 4 and not (preserve_col_positions or keep_all_amount_cells)
                and table_has_note_column):
            while all_parsed and all_parsed[0] is None:
                all_parsed.pop(0)
                if all_raw:
                    all_raw.pop(0)
                if all_flags:
                    all_flags.pop(0)

        amounts: list[Optional[int]] = []
        raw_amounts: list[str] = []
        acontext_missing: list[bool] = []
        for i in range(num_cols):
            amounts.append(all_parsed[i] if i < len(all_parsed) else None)
            raw_amounts.append(all_raw[i] if i < len(all_raw) else "")
            acontext_missing.append(all_flags[i] if i < len(all_flags) else False)

        indent = _detect_indent(label)
        label_clean = label.lstrip()  # 들여쓰기 공백 제거

        rows.append(RowData(
            account_name=label_clean,
            amounts=amounts,
            raw_amounts=raw_amounts,
            acontext_missing=acontext_missing,
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


def _get_cell_elements(tr: etree._Element) -> list[etree._Element]:
    """`_get_cells`와 **완전히 같은 태그 필터·순서**로 셀 엘리먼트 자체(텍스트가 아니라)를
    반환한다 — §5.4(classB 유형1) 근거. `_get_cells`가 버리는 ACODE/ACONTEXT 속성을
    나중에(`_cell_acontext_missing`) 읽기 위한 것. 반드시 `_get_cells`와 인덱스가
    1:1로 대응해야 한다 — 태그 필터를 따로 바꾸지 말 것."""
    return [child for child in tr
            if (child.tag.upper() if isinstance(child.tag, str) else "") in ("TD", "TH", "TE", "TU")]


def _cell_acontext_missing(el: etree._Element) -> bool:
    """True: `<TE ACODE=...>` 인데 `ACONTEXT` 속성 자체가 없는 셀 — DART 원문이 스스로
    "이 기간엔 이 계정을 태깅하지 않았다(=미공시)"라고 구조적으로 밝힌 것과 같은 신호다
    (`fin2/extract/xbrl.py`의 Track A가 `ACONTEXT` 없는 셀을 스킵하는 것과 동일 원리).
    `<TD>`(ACODE 자체가 없는 구형 비XBRL 셀)는 이 신호가 없으므로 항상 False —
    그런 셀은 판단을 보류하고 기존 로직(R19 포함)을 그대로 따른다.

    원문대조 근거: `docs/plans/gateb_trade_payables_classB_stale_column_investigation_
    2026-08-29.md` §5(6개사 12행 전건 확인, 반례 0건) + §6(corpus 파급범위 census,
    397/33,457행·1.19%가 이 신호로 갈림, 오탐 방향 없음)."""
    tag = el.tag.upper() if isinstance(el.tag, str) else ""
    if tag != "TE":
        return False
    if not el.get("ACODE"):
        return False
    return el.get("ACONTEXT") is None


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


# ★R112(2026-09-13, CF_separate 항목수 분포 이상치 조사 중 발견) — 한양증권(00162416)
# 20160329000677 실측: 주석 컬럼 헤더가 글자당 공백을 넣는 옛 강조체("주  석")를 써서
# 옛 `"주석" in text` 정확매치가 실패 → 이 컬럼이 주석열로 인식 안 돼 주석번호("35")가
# 진짜 금액 열처럼 취급되면서 "나.당기순이익에 대한 조정" 등에 엉뚱한 값 "35" 행이
# 추가로 끼어듦(원래 값 -4,501,035,344는 정상 적재됐지만 "35" 중복행이 같이 들어감).
# 아래(`_columns_from_grid`)의 동형 검사도 함께 고친다.
_NOTE_HEADER_RE = re.compile(r"주\s*석")
# ★R126(2026-09-15, 잔여 72건 재조사) — "전환일"(IFRS 최초채택 시 3번째 비교재무상태표
# 기준일)·"설립일 현재"(설립연도 신규상장사가 전기 실적이 없어 대신 넣는 기준일) 열은
# 회계기간이 아니라 **참고용 고정 기준일**이다. 항상 진짜 "제N(당)기" 열과 나란히
# 등장하고(그 열이 이미 rank0 으로 정상 인식됨), 정책상(`_is_loadable`) 어차피
# rank0 만 저장하므로 이 열의 값을 인식 못 해도 저장 데이터엔 영향이 없다 — 반대로
# 인식 못 한다고 표 전체를 폴백시키면 rank0(진짜 당기 값)까지 구버전 휴리스틱으로
# 잘못 재구성될 위험이 생긴다(실측: 롤링스톤·에스엘에스바이오·다원넥스뷰·패션
# 플랫폼·와이즈버즈·TS트릴리온·프로이천·포커스에이아이 등 8개사). R117의 주석열
# 처리와 동일하게 is_note=True 로 건너뛴다.
_REFERENCE_ONLY_HEADER_RE = re.compile(r"전\s*환\s*일|설\s*립\s*일")


def _table_has_note_header(trs: list[etree._Element]) -> bool:
    """R65(2026-09-02): 표의 어느 `<TH>` 셀이든 텍스트에 "주석"이 있으면 True.

    ★왜 필요한가: `_table_has_comma_note_column()`은 콤마로 묶인 다중 주석참조("10,37")가
    표 안에 하나라도 있어야만 True를 준다 — 그런데 매 행이 주석을 하나씩만 인용하는 표(드물지
    않음, 콤마가 표 전체에 단 한 번도 안 나옴)에서는 이 신호가 영원히 False로 남아 R19 안전
    장치가 발동하지 않는다. 그러면 라벨 바로 다음 칸의 주석번호("5"/"21"/"22" 등)가 금액으로
    오채택되고, 하류 multicol 압축(`report_lines.py`)이 위치 그대로 압축하면서 진짜 당기금액이
    한 칸씩 밀리거나(오분류) FY 표의 col_index≥1 적재제외 규칙에 걸려 소실된다(원문대조 확정:
    00537337 2011FY, 00132202 2020FY — 둘 다 헤더에 `<TH>주석</TH>` 명시).

    헤더 텍스트는 콤마 신호와 달리 데이터 행의 값 모양에 기대지 않는 **구조적** 신호라 훨씬
    신뢰도가 높다 — 표 헤더가 "주석"이라는 컬럼을 실제로 선언했다는 원문 그 자체다. 설계
    `docs/plans/note_ref_multicol_compaction_value_corruption_design_2026-09-02.md` §5.1.
    """
    for tr in trs:
        for child in tr:
            tag = child.tag.upper() if isinstance(child.tag, str) else ""
            if tag == "TH" and _NOTE_HEADER_RE.search(''.join(child.itertext())):
                return True
    return False


# ────────────────────────────────────────────────────────────────────────────
# THEAD COLSPAN/ROWSPAN 그리드 기반 컬럼판정 (2026-09-09)
#
# 배경·설계: docs/plans/report_lines_header_grid_column_map_design_2026-09-09.md
# R85(EPS 컬럼선택)·R86(else 분기 선두절삭)·R87(extract_rows 동형결함) 전부 "표가
# 몇 열이고 각 열이 어느 회계기간인지를 데이터 행의 공란 패턴으로 사후 추측"해온
# 결함이었다 — 원문 THEAD 가 COLSPAN/ROWSPAN(+ 종종 ENG 속성)으로 이미 그 구조를
# 명시적으로 선언하고 있는데도 안 읽고 있었다. 이 블록은 그 헤더를 **먼저** 읽어
# 위치→회계기간 맵을 만든다 — 실패(THEAD 없음·기간패턴 인식 실패)하면 `None`을
# 반환해 호출측(`report_lines.py::_emit_section_lines`)이 기존 cum_map/multicol/
# else 경로(R85~R87 가드 포함)로 안전하게 폴백한다.
# ────────────────────────────────────────────────────────────────────────────

# ★R122(2026-09-14, 레이크머티리얼즈 20180813000607·케이엠제약 20170814000310·자비스
# 20180515000191 등 CF 별도 저조 이상치 스크리닝 중 발견) — "제N(당)기 반기"/"제N(당)기
# 1분기"류 표기에서 필자가 괄호 바로 뒤 "기"를 빠뜨리고 "제N(당) 반기"/"제N(당) 1분기"
# 로 적는 오타가 여러 회사에 걸쳐 반복 확인됐다(같은 회계 소프트웨어/템플릿을 쓰는
# 소형사 군의 공통 결함으로 추정 — 한 회사만의 우연이 아니라 최소 3개 서로 무관한
# 회사에서 동일 패턴). "기"가 빠져도 뒤따르는 "반기"/"N분기" 자체가 이미 기간구분을
# 명확히 하므로, "기" 없이 곧장 "반기"/"N분기"로 이어지는 것도 인정한다(원래는 "기"
# 뒤에 오는 "분기"/"반기" 접미사만 옵션이었는데, "기" 자체를 옵션으로 넓힌다).
# ★R123(2026-09-15, 2015+ 전수 폴백 스캔[`scripts/scan_header_fallback_2015plus_
# 2026-09-14.py`]로 발견) — 표 559,701건 중 폴백 1,333건(0.24%)을 회사별로 집계하니
# 상위 다수가 증권사(유안타증권·NH투자증권·키움증권·DB증권·다올투자증권 등)에 몰려
# 있었다. 실측 3가지 서로 다른 미인식 형태:
#   ① 증권사류 관행 — "제N기" 서수 대신 "2015회계연도 1분 기"(연도+"회계연도", 글자당
#      공백까지 포함) 표기. "제" 접두 자체가 없어 기존 regex 가 아예 진입 못 함.
#   ② 크래프톤(00760971) CF 연결 — 두 번째 열이 "제" 접두를 빠뜨리고 "11기 1분기"로만
#      적음(첫 열은 정상 "제 12기 1분기") — 46건 반복이라 회사 관행으로 판단.
#   ③ 에스바이오메딕스(01258020) 등 — "제 16(당) 분기말"처럼 분기 서수(숫자) 없이
#      "분기"만 붙는 표기("N분기"가 아니라 순수 "분기" 하나). 기존 `[1-4]\s*분기` 는
#      숫자가 필수라 안 걸림.
#   ④ NH투자증권(00120182, R123 적용 후에도 162건 그대로) — 서수 자체가 아예 없고
#      "당분기말"/"전기말"처럼 상대어("당기"/"전기")에 "분기"/"반기"가 붙은 합성어를
#      쓴다. 기존 상대어 브랜치는 "당\s*기"/"전\s*기" 뿐이라 "당" 과 "기" 사이에
#      "분"이 끼면(글자 수가 달라져) 매치가 안 됐다.
# 셋 다 "제" 접두를 옵션으로 넓히고, "회계연도"(연도서수 대체) 대안 브랜치와 숫자없는
# "분기" 대안, "당분기"류 상대어 합성 대안을 추가해 해결한다. "분기"/"반기" 안의
# 글자당 공백(예: "1분 기")도 허용한다.
#
# ★R126(2026-09-15, R123+R125 적용 후 잔여 72건 재조사) — "제N기" 서수 체계 자체를
# 아예 안 쓰고 **달력 날짜**로만 기간을 표기하는 회사들 실측 확인:
#   ① 신라젠(00919966) — "2015.03.31"/"2014.12.31"(점 구분, 서수 없음)
#   ② FSN(01061497) — "2015-03-31"(하이픈 구분) / "2015년 1Q"(연도+영문분기)
#   ③ 우리금융지주(01350869) — "2018년 12월"/"2018년말"/"2018년 반기"/"2018년"
#      (지주사 분할 직후 전신 합산실적을 "제N기" 없이 달력연도로만 표기)
#   ④ 티로보틱스(00867098) — "2017년"/"2016년"/"2015년"(3개년 비교, 서수 없음)
#   ⑤ 토박스코리아(01064069) — "2015년 반기"(연도+반기, 서수 없음)
# 모두 같은 헤더 안에 "제N기"류 서수 열이 전혀 없거나(①②④⑤ 전부 또는 일부 열),
# 있어도 나머지 비교열이 달력표기라 전체 표가 인식실패로 폴백했다. 날짜/연도
# 문자열 자체를 period_key 로 인정한다(같은 행 안에서 등장 순서로 rank 부여되므로
# 서수가 없어도 왼쪽=최신 관례가 그대로 유지된다).
#
# ★R126b(2026-09-15, 잔여 72건 재조사) — "제N(당)기"류 표기에서 **여는 괄호**만
# 빠뜨리는 오타를 최소 4개 서로 무관한 회사(삼성화재해상보험·보라티알·듀켐바이오·
# 키움증권)에서 반복 확인: "제20전)기"(제20(전)기), "제17당)기"(제17(당)기),
# "제5당)기"(제5(당)기) — 닫는 괄호는 있는데 여는 괄호가 없다. R122(닫는 괄호 뒤
# "기" 탈락)의 거울상 오타로, 같은 서수 브랜치 안에 "여는 괄호 없이 상대어+닫는
# 괄호"만 오는 대안을 추가해 흡수한다.
#
# ★R128(2026-09-15, 4개 이상치 카테고리 재검증 중 발견, 바이오솔루션 20161114001893
# IS 별도 등) — "당N분기"/"전N분기"(상대어+숫자+분기, 예: "당3분기"/"전3분기") 표기가
# 인식이 아예 안 되던 게 아니라 **잘못 인식**되고 있었다. 위 서수 브랜치가 "제" 접두를
# 옵션으로 허용해(R123) "당3분기"의 "당"을 그냥 건너뛰고 "3분기"부터 매치해버려서,
# "당3분기"와 "전3분기" 둘 다 period_key="3분기"로 같은 rank 에 병합됐다(물리적으로
# 다른 두 기간이 하나로 합쳐짐 — R6 판정불가로 대부분 행 유실). "당분기"/"전분기"
# (숫자 없는 버전)는 이미 있었는데 숫자 있는 버전이 빠져 있었다. 서수 브랜치보다
# 먼저 매치를 가로채도록(같은 시작위치서 이 대안이 성공하면 search() 가 이를 채택)
# 상대어+숫자+분기 대안을 추가한다.
_PERIOD_KEY_RE = re.compile(
    r"당\s*[1-4]\s*분\s*기|전\s*전\s*[1-4]\s*분\s*기|전\s*[1-4]\s*분\s*기"
    r"|(?:제\s*)?\d+\s*(?:\([^)]{0,4}\)|(?:당|전\s*전|전)\s*\))?\s*"
    r"(?:기(?:\s*[1-4]\s*분\s*기|\s*반\s*기)?|[1-4]\s*분\s*기|분\s*기|반\s*기)"
    r"|\d{4}\s*회계연도(?:\s*[1-4]\s*분\s*기|\s*반\s*기)?"
    r"|당\s*분\s*기|전\s*분\s*기|전\s*전\s*분\s*기"
    r"|당\s*반\s*기|전\s*반\s*기|전\s*전\s*반\s*기"
    r"|당\s*기|전\s*기|전\s*전\s*기|전\s*전\s*전\s*기"
    r"|\d{4}\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2}"
    r"|\d{4}\s*년\s*[1-4]\s*[Qq]"
    r"|\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*말)?(?:\s*반\s*기)?"
    r"|\d{2}\s*년\s*[1-4]\s*분\s*기")
# ★R128b(2026-09-15, 이노시뮬레이션 20191129001722 CF 연결 실측, NO THEAD 헤더리스
# 서식) — "19년 3분기"/"18년 3분기"처럼 연도를 2자리로 줄여 쓰는 표기. 4자리
# 연도("2019년...") 브랜치는 이미 있었으나 2자리는 없어 "3분기"만 매치되고 "19"/
# "18" 구분이 사라져 당기·전기가 같은 rank 로 병합됐다. "분기" 앞 필수라 오탐 위험
# 낮음(4자리 연도 텍스트는 그 브랜치가 이미 왼쪽에서 먼저 매치를 채가므로 충돌 없음).
# ★R111(2026-09-13, IS_separate 항목수 분포 이상치 조사 중 발견) — 파워넷(00231354)
# 20150515001597 실측: 서브타입 헤더 셀이 글자당 공백을 넣는 옛 강조체("3 개 월",
# "누  적")를 쓰는데 옛 정규식(`3\s*개월` 은 "3"-"개월" 사이만, `누적` 은 공백 전혀
# 불허)이 매칭 못 해 subtype=None으로 남음 → `select_by_header_columns()`가 3개월/
# 누적 구분 안 된 컬럼을 당기로 잘못 선택(당기누적 25,781,758,600 대신 무관한 제22기
# 열 82,662,901,775 채택). `fin2/extract/text.py::_interim_cumulative_cols()`의 동형
# 정규식과 함께 고친다(같은 문서에 두 벌 존재 — R88 헤더그리드 경로 전용 사본).
_SUBTYPE_CUM_RE = re.compile(r"누\s*적|누\s*계")
_SUBTYPE_3M_RE = re.compile(r"3\s*개\s*월|삼\s*개\s*월")


@dataclass
class HeaderColumn:
    """THEAD 그리드에서 읽어낸 데이터 열 하나의 신원.

    `position`은 라벨열을 제외한 **원시** 금액셀 위치 — `extract_rows(...,
    keep_all_amount_cells=True)`가 돌려주는 `RowData.amounts`와 같은 인덱스라야
    한다(호출측이 그 모드로 뽑아야 정합이 맞음)."""
    position: int
    period_key: str
    period_rank: int
    subtype: Optional[str] = None   # "cumulative" | "three_month" | None(구분 텍스트 없음)
    is_note: bool = False


def _resolve_header_grid(header_trs: list[etree._Element]) -> Optional[list[list[str]]]:
    """THEAD 의 TR 들을 표준 HTML 표 COLSPAN/ROWSPAN 규칙으로 해석해
    `grid[row][col] -> 셀 텍스트`(스팬 영역은 같은 텍스트 반복)로 돌려준다.
    TR 이 없으면 None."""
    if not header_trs:
        return None
    n_rows = len(header_trs)
    cells_by_row: list[dict[int, str]] = [dict() for _ in range(n_rows)]
    for r, tr in enumerate(header_trs):
        col = 0
        for cell in tr:
            tag = cell.tag.upper() if isinstance(cell.tag, str) else ""
            if tag not in ("TH", "TD"):
                continue
            while col in cells_by_row[r]:
                col += 1
            try:
                colspan = int(cell.get("COLSPAN", "1") or "1")
            except ValueError:
                colspan = 1
            try:
                rowspan = int(cell.get("ROWSPAN", "1") or "1")
            except ValueError:
                rowspan = 1
            text = " ".join("".join(cell.itertext()).split())
            for rr in range(r, min(r + rowspan, n_rows)):
                for cc in range(col, col + max(colspan, 1)):
                    cells_by_row[rr][cc] = text
            col += max(colspan, 1)
    n_cols = max((max(d.keys()) + 1 for d in cells_by_row if d), default=0)
    if n_cols == 0:
        return None
    return [[cells_by_row[r].get(c, "") for c in range(n_cols)] for r in range(n_rows)]


def _header_column_stack(grid: list[list[str]], col: int) -> list[str]:
    """그리드의 한 열을 위→아래로 읽어, 빈 문자열을 빼고 ROWSPAN 으로 생긴 연속중복만
    지운 텍스트 스택을 만든다(예: ['제 57 기 반기', '3개월'])."""
    stack: list[str] = []
    for row in grid:
        text = row[col] if col < len(row) else ""
        if not text:
            continue
        if stack and stack[-1] == text:
            continue
        stack.append(text)
    return stack


def _row_has_amount(cell_texts: list[str]) -> bool:
    """`cell_texts` 중 하나라도 진짜 금액처럼 보이면(`_NUMBER_PATTERN` 매치) True."""
    return any(_NUMBER_PATTERN.match(t.strip()) for t in cell_texts if t.strip())


def _looks_like_header_row(cell_texts: list[str]) -> bool:
    """THEAD 가 없는 표에서, TBODY 선두 TR 하나가 헤더행인지 **내용으로** 판정한다
    (모양/위치가 아니라 R6 원칙과 같은 맥락 — 확정 못 하면 추측하지 않는다).

    라벨열(cell_texts[0])을 제외한 나머지 셀 중: ①하나라도 진짜 금액처럼 보이면
    (`_NUMBER_PATTERN` 매치, "제28기" 류는 숫자만 있는 게 아니라 안 걸림) 즉시
    본문 데이터 행으로 판정(False) — 헤더행에 진짜 금액이 있을 리 없다. ②그 외의
    경우, 기간패턴(`_PERIOD_KEY_RE`)이나 서브타입 토큰(3개월/누적)이 하나라도 있으면
    헤더행(True). 전부 공란이거나 아무 마커도 없으면(예: "자산"류 섹션 헤더행)
    False — 이런 행까지 헤더로 흡수하면 안 된다(R5, header_hint 는 별도 개념)."""
    rest = cell_texts[1:]
    if _row_has_amount(rest):
        return False
    return any(_PERIOD_KEY_RE.search(t.strip()) or _SUBTYPE_CUM_RE.search(t.strip())
               or _SUBTYPE_3M_RE.search(t.strip()) for t in rest if t.strip())


def _table_colgroup_ncols(table: etree._Element) -> Optional[int]:
    """`<COLGROUP><COL/>...</COLGROUP>`가 선언한 표의 총 물리 열 수. 없으면 None
    (호출측이 판정 불가로 보고 완전 폴백)."""
    colgroup = table.find("COLGROUP")
    if colgroup is None:
        return None
    n = len(colgroup.findall("COL"))
    return n or None


def _headerless_header_trs(table: etree._Element) -> list[etree._Element]:
    """R88 §7 확장(2026-09-10) — THEAD 없이 헤더행이 TBODY 선두에 섞여 오는 구서식
    (pre-2015 K-GAAP 등)에서, 선두 TR들 중 `_looks_like_header_row`에 걸리는 것만
    THEAD 대용으로 모은다. 처음으로 안 걸리는(=진짜 데이터) TR을 만나면 즉시 멈춘다
    — 그 뒤도 계속 훑으면 우연히 패턴이 맞는 데이터 행을 헤더로 오인할 위험이 있다.

    ★R95(2026-09-12) — **배너/캡션행 건너뛰기.** 원문 표는 실제 헤더행("계정명｜
    주석｜제N(당)기｜제N(전)기") 앞에 표제목("재무상태표")·기준일("제 45기 2015년
    09월 30일 현재")·"회사명 : (주)OOO / (단위 : 원)" 같은 COLSPAN 병합 행을 여러 줄
    둔다. 이 행들은 `_looks_like_header_row`가 진짜 데이터 행과 구분 못 해(금액도
    마커도 없음 — "자산"류 섹션행과 신호가 동일) 첫 줄에서 바로 멈춰버렸다(실측:
    00186939 특수건설 20151116001903, 미착품/장기차입금 등 **당기 값이 원문에
    아예 없는데 전기값이 당기로 오적재** — `_detect_period_layout` multicol 폴백의
    위치기반 압축이 원인. `docs/plans/table_header_banner_row_skip_design_
    2026-09-12.md`).
    구분 기준은 **모양**(COLSPAN)이 아니라 `<COLGROUP>`이 선언한 총 물리 열 수 대비
    "이 행의 실제 TD 개수가 더 적은가" — 배너/캡션행은 병합 때문에 항상 물리 셀이
    적고, "자산"류 섹션행은 다른 데이터행과 똑같이 표 전체 폭(물리 셀 수 = 총 열수)
    을 채운다(값이 전부 공란이어도 칸 자체는 살아있다). `<COLGROUP>`이 없으면
    판정 근거가 없으므로 전부 원래 동작(변경 없음) — R6 원칙대로 모르면 확장 않음.
    배너/캡션행이라도 진짜 금액이 있으면(드묾, 안전장치) 데이터 행으로 보고 멈춘다.

    ★R95 후속(같은 날, 손익계산서 표 재확인) — **완전공백행**(라벨칸까지 포함해
    모든 물리 셀이 빈 문자열)은 COLSPAN 병합 없이 개별 빈 `<TD>`를 표 전체 폭만큼
    나열해두는 경우가 있어(실측: 위 특수건설 표의 포괄손익계산서 — 표제목 바로
    다음 줄이 물리 셀 5개짜리 빈 행) 물리 셀 수가 선언 열수와 **같아**
    `is_banner` 판정을 피해간다. 그런데 이런 행은 라벨조차 없어 애초에 "자산"류
    섹션행(라벨은 반드시 있음)이 될 수 없다 — 라벨 유무로 완전히 갈리므로 폭
    비교보다 먼저, 무조건 건너뛴다."""
    tbody = table.find("TBODY")
    candidate_trs = list(tbody.findall("TR")) if tbody is not None else list(table.findall("TR"))
    n_cols_declared = _table_colgroup_ncols(table)
    header_trs: list[etree._Element] = []
    for tr in candidate_trs:
        cells = _get_cells(tr)
        if cells and not any(c.strip() for c in cells):
            continue  # 완전공백행(라벨도 없음) — 무조건 건너뜀
        is_banner = n_cols_declared is not None and 0 < len(cells) < n_cols_declared
        if is_banner:
            if _row_has_amount(cells[1:]):
                break
            if _looks_like_header_row(cells):
                header_trs.append(tr)
            continue  # 마커 없는 배너/캡션행 — 건너뛰고 계속 스캔
        if not _looks_like_header_row(cells):
            break
        header_trs.append(tr)
    return header_trs


def _columns_from_grid(
    grid: list[list[str]], allow_duplicate_subtype: bool = False,
) -> Optional[list[HeaderColumn]]:
    """해석된 헤더 그리드(`_resolve_header_grid`/BS4 어댑터 등 출처 무관) → 위치→
    회계기간 맵. `parse_header_columns()`의 THEAD 경로와 §7 확장(TBODY-선두) 경로가
    공유한다 — 어느 쪽에서 만든 grid든 이 함수 하나로 해석한다(중복 구현 방지).

    실패 조건: 라벨열 뒤에 기간패턴을 못 찾은 열이 있음(=아직 모르는 헤더 모양 — §5
    정책대로 여기서 확장하지 말고 폴백시켜 다음에 발견한 사례로 넓힌다).

    `allow_duplicate_subtype` — R125(2026-09-15) 참고. 기본값 False 는 아래 "애매한
    중복" 가드를 그대로 유지(회귀 0)."""
    n_cols = len(grid[0])
    if n_cols < 2:
        return None

    # ★라벨열은 항상 딱 1개(첫 칸)로 고정 — `extract_rows(..., keep_all_amount_cells=
    # True)`가 라벨로 취급하는 것도 정확히 `cells[0]` 하나뿐이다(parser/xml/table_
    # extractor.py 위쪽 keep_all_amount_cells 분기 참고). 예전엔 "기간패턴이 없으면
    # 라벨"로 보고 계속 늘렸는데, 그러면 라벨 바로 다음의 **주석참조 열**(흔히 헤더가
    # "주석"이라고만 쓰고 기간패턴은 없음, R19)까지 라벨로 흡수해버려 `position` 이
    # 실제 데이터 배열과 한 칸씩 어긋났다(실측 회귀: 한화손해보험/코리안리 등 주석열
    # 있는 표에서 값이 전부 한 칸씩 밀림, 2026-09-09). 라벨을 1개로 고정하면 주석열은
    # 아래에서 `is_note=True`인 채 자기 위치를 그대로 갖고, `select_by_header_columns`
    # 가 안전하게 건너뛴다.
    label_cols = 1

    columns: list[HeaderColumn] = []
    period_rank_of: dict[str, int] = {}
    for col in range(label_cols, n_cols):
        stack = _header_column_stack(grid, col)
        period_key = None
        subtype_text = ""
        for i, text in enumerate(stack):
            m = _PERIOD_KEY_RE.search(text)
            if m:
                period_key = m.group(0)
                # ★R119(2026-09-14, 푸른저축은행 20150213000097 IS 별도 실측) — THEAD가
                # 없는 구서식은 헤더가 한 줄뿐이라("계정과목|제45기반기(3개월)|제45기반기
                # (누적)|…") 서브타입 표시가 별도 스택행이 아니라 **같은 셀 안에서 기간
                # 텍스트 바로 뒤 괄호**로 붙는다("(3개월)"/"(누적)"). 기존엔 매치된 셀
                # 이후의 다른 스택행만 subtype_text 로 모아, 이 서식에서 매치된 셀
                # 자신의 나머지 텍스트(괄호 부분)가 통째로 버려져 subtype=None으로
                # 남았다 — 결과: 3개월/누적 구분이 안 돼 두 물리열 다 "값 있음"이 돼
                # R6 판정불가로 행 전체 유실(IS 24행 중 23행). 매치된 셀 자신의 잔여
                # 텍스트(m.end() 이후)도 subtype_text 에 포함시킨다.
                subtype_text = text[m.end():] + " " + " ".join(stack[i + 1:])
                break
        position = col - label_cols
        if period_key is None:
            # ★R117(2026-09-14, 아주IB투자 20150817001086 CF 연결 실측) — 주석번호
            # 참조열인데 헤더 셀 자체가 완전공란(`<TH/>` 자기닫힘, "주석"이라는 글자조차
            # 없음)인 서식이 있다. 기존엔 "기간패턴도 주석표시도 없는 열"로 보고 표 전체를
            # 폴백(구버전 cum_map/multicol/else 경로로 떨어짐)시켰는데, 그 폴백이 이
            # 표에서는 부정확해 "조정"/"순운전자본의변동" 단 2행만 건지고 나머지(영업/투자/
            # 재무활동현금흐름 등 실제 CF 본체)는 전부 유실됐다. 헤더 스택이 **전부 빈
            # 문자열**이면 애초에 기간패턴이 나올 수 없는 열이므로(주석열이든 진짜 빈
            # 열이든, 어느 쪽이든 period 값을 못 낸다는 결론은 같다) 주석열과 동일하게
            # is_note=True 로 건너뛴다 — `select_by_header_columns`가 이미 is_note 열을
            # 무조건 skip 하므로 안전(값 판정에 영향 없음), 표 전체 유실을 막는다.
            if (any(_NOTE_HEADER_RE.search(s) for s in stack)
                    or any(_REFERENCE_ONLY_HEADER_RE.search(s) for s in stack)
                    or not any(s.strip() for s in stack)):
                columns.append(HeaderColumn(position=position, period_key="", period_rank=-1,
                                            is_note=True))
                continue
            return None  # 라벨열 뒤인데 기간패턴도 주석표시도 없는 열(내용 있음) — 모르는 모양, 폴백
        if period_key not in period_rank_of:
            period_rank_of[period_key] = len(period_rank_of)
        subtype = None
        if _SUBTYPE_CUM_RE.search(subtype_text):
            subtype = "cumulative"
        elif _SUBTYPE_3M_RE.search(subtype_text):
            subtype = "three_month"
        columns.append(HeaderColumn(position=position, period_key=period_key,
                                    period_rank=period_rank_of[period_key], subtype=subtype))

    # ★애매한(period_rank, subtype) 중복 — 기본은 안전하게 폴백. 예: K-GAAP 구서식
    # IS(2003년대)는 "3개월"/"누적" 아래 다시 COLSPAN=2 하위열(둘 다 텍스트가 "금액"
    # 으로 동일)이 있어 헤더 텍스트만으론 어느 쪽이 진짜 금액칸인지 구분이 안 된다
    # (실측: 00132725 SB성보 2003Q3 IS, rank0 에 subtype="three_month" 열이 2개·
    # "cumulative" 열이 2개). 아무거나 첫 번째를 고르면 조용히 틀린 값을 낼 위험이
    # 있다 — 대신 표 전체를 인식 실패로 보고 기존 cum_map/multicol/else 경로로
    # 폴백한다(§5 정책, 회귀 0 우선). subtype=None 중복은 정상(병합군, 삼성생명류 —
    # select_by_header_columns 가 "값 있는 열 하나" 로직으로 처리) — subtype 이
    # **있는데** 중복인 경우만 애매하다고 본다.
    #
    # ★R125(2026-09-15, 현대해상·다올투자증권·대신증권 등 2015+ 폴백 스캔 후속, 사용자
    # 확인) — 2015+ 보험/증권사 서식을 실측하니 이 COLSPAN=2 하위열이 "명세행(1열)/
    # 소계행(2열)"로 역할이 고정돼 같은 행에서 둘 다 채워지는 일이 없다(사용자: "3개월
    # 아래에 2열로 되어서 1열에 세부항목 2열에 subtotal... 연결 별도 동일한 형태").
    # 그런데 SB성보(2003, pre-2015 K-GAAP)로 직접 검증해보니 그 회사는 이 규칙이 안
    # 맞아 행별 유일값 채택이 조용히 틀린 값을 냈다(R124 최초 시도 회귀, 되돌림) — 두
    # 서식이 헤더 모양만으론 구분이 안 돼, 여기서 일반 규칙으로 확장하지 않는다. 대신
    # 호출측(`report_lines.py`)이 **report_fiscal_year>=2015 일 때만**
    # `allow_duplicate_subtype=True` 를 넘기도록 좁힌다 — SB성보류(pre-2015)는 절대
    # 이 분기를 안 타므로 안전, 2015+ 만 새 규칙 적용(사용자 지시: "지금은 2015+ 보고서에
    # 집중, SB성보는 이후 별도 정리").
    if allow_duplicate_subtype:
        return columns
    seen: dict[tuple, int] = {}
    for hc in columns:
        if hc.is_note or hc.subtype is None:
            continue
        key = (hc.period_rank, hc.subtype)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            return None
    return columns


def parse_header_columns(
    table: etree._Element, allow_duplicate_subtype: bool = False,
) -> Optional[list[HeaderColumn]]:
    """표의 THEAD(또는 THEAD 가 없으면 TBODY 선두의 헤더행류, §7)를 읽어 위치→회계기간
    맵을 만든다. 실패하면 None(호출측 폴백) — §5 정책 그대로, 여기서 억지로 확장하지
    않는다.

    `allow_duplicate_subtype` — R125(2026-09-15): 명세/소계 COLSPAN=2 병합군을
    표 전체 폴백 대신 행별 유일값으로 푼다(호출측이 report_fiscal_year>=2015 일 때만
    True 로 넘기도록 스코프를 좁힌다 — `_columns_from_grid` R125 docstring 참고)."""
    thead = table.find("THEAD")
    if thead is not None:
        header_trs = list(thead.findall("TR"))
    else:
        header_trs = _headerless_header_trs(table)
        if not header_trs:
            return None
    grid = _resolve_header_grid(header_trs)
    if grid is None:
        return None
    return _columns_from_grid(grid, allow_duplicate_subtype=allow_duplicate_subtype)


# ★R115(2026-09-14, 형지I&C 20160516001490·드림시큐리티 20160511001294 실측, 표 헤더
# 정교화 지시로 발견) — 분기/반기 보고서의 IS 표가 자사 분기 열("제41기 1분기" 3개월/누적)
# 뒤에 **참고용 연간 총액 열**("제40기"·"제39기", 분기/반기 접미사 없는 순수 연도서수)을
# 추가로 붙이는 서식이 있다:
#   [제41기 1분기(3개월|누적)] [제40기 1분기(3개월|누적)] [제40기] [제39기]
#     rank0(당기 Q1)          rank1(전기 Q1)             rank2    rank3
# "제40기 1분기"(rank1)와 "제40기"(rank2)는 **같은 회계연도**(2015)인데 물리적으로 다른
# rank 를 받는다 — `_columns_from_grid`의 rank 부여가 "몇 번째로 처음 나온 고유 문구인가"
# 순서일 뿐 실제 연도 간격을 모르기 때문이다. 그 상태로 `report_lines.py::_row_to_line`의
# `context_fiscal_year = report_fiscal_year - col_index`(위치 기반 공식, "col_index 는
# 몇 기 전"이라는 설계 전제)를 그대로 적용하면 rank2 가 2015 대신 2014로 계산된다(실측
# 확정) — 진짜 실적행(매출액·영업이익·당기순이익 등)이 전부 이 잘못된 rank 로 밀려나고,
# 우연히 값이 0/동일해 걸리지 않는 사소한 행(EPS·영업수익=0 등)만 rank0/1 에 남아 DB에
# 껍데기만 남는다(그 필링들이 IS 항목수 이상치 저조구간에 잡힌 이유).
#
# 값을 억지로 재계산해 끼워맞추면(예: 텍스트의 "제N기" 서수를 파싱해 진짜 연도간격을
# 추정) 짐작 금지 원칙에 걸리고, "제40기 1분기"와 "제40기"를 같은 rank 로 합치면 분기
# 누적값과 연간 총액이 같은 col_index 에서 충돌한다(서로 다른 period_kind 인데 같은
# 슬롯에 두 값이 들어가는 판정불가 상태). 그래서 이 열 자체를 **배제**한다 — 분기/반기
# 보고서 본문(BS/IS/CF)에서 col_index 축은 "이 보고서와 같은 기간단위(분기/반기)"만
# 다루는 것으로 스코프를 좁히고, 순수 연도서수(분기/반기 접미사 없는 "제N기") 참고열은
# 통째로 제외한다. FY 보고서는 애초에 전부 순수 연도서수 열이라 이 필터가 아무것도
# 지우지 않는다(조기 반환).
_BARE_FY_ORDINAL_RE = re.compile(r"^제\s*\d+\s*(?:\([^)]{0,4}\))?\s*기$")


def drop_mismatched_granularity_columns(
    columns: Optional[list[HeaderColumn]], report_fiscal_period: str,
) -> Optional[list[HeaderColumn]]:
    """R115 — 분기/반기 보고서에서 분기·반기 접미사 없는 순수 연도서수 참고열을 배제하고,
    남은 열의 period_rank 를 0부터 gap 없이 재부여한다(원래 rank 순서는 유지).

    `columns`가 None 이면 그대로 None(호출측이 `parse_header_columns` 실패를 그대로
    전파할 수 있도록 — 이 함수는 성공한 맵을 다듬을 뿐, 실패를 성공으로 바꾸지 않는다).
    FY 보고서(`report_fiscal_period == "FY"`)는 전부 순수 연도서수 열이라 그대로 반환."""
    if columns is None or report_fiscal_period == "FY":
        return columns
    keep_ranks: dict[int, int] = {}
    result: list[HeaderColumn] = []
    for hc in columns:
        if hc.is_note:
            result.append(hc)
            continue
        if _BARE_FY_ORDINAL_RE.match(hc.period_key.strip()):
            continue   # 분기/반기 보고서 속 연간 참고열 — 배제(R115)
        if hc.period_rank not in keep_ranks:
            keep_ranks[hc.period_rank] = len(keep_ranks)
        result.append(HeaderColumn(
            position=hc.position, period_key=hc.period_key,
            period_rank=keep_ranks[hc.period_rank], subtype=hc.subtype,
            is_note=hc.is_note,
        ))
    if not keep_ranks:
        # 배제하고 나니 기간열이 하나도 안 남았다 — 이 표의 전체 열이 순수 연도서수라는
        # 뜻이라(예: 구형 K-GAAP 표가 분기 보고서에서도 "제43기"만 쓰는 서식), 이때는
        # 애초의 R115 전제(이 보고서 자체 기간단위 열이 별도로 있다)가 안 맞는 것이다.
        # 억지로 다 지우면 표 전체가 유실되므로(R6, 모르면 확장하지 않는다) 원본을
        # 그대로 돌려준다 — 무필터 상태(기존 동작)로 안전 폴백.
        return columns
    return result


# ★R113(2026-09-13, 사용자 원문대조로 발견 — 넥슨게임즈[전 엔에이치기업인수목적9호]
# 00231354 20160513004375 CF 별도, 자비스[전 아이비케이에스제5호기업인수목적] 01174038
# 20170811000259 CF 별도) — "-"(대시)는 한국 재무제표 표기 관행상 "이 항목 금액은
# 0"을 뜻하는데(결측/미공시가 아님 — 사용자 확인: "처음 보고서여서 기초가 없고... -를
# 0으로 표현하는 것이 맞는 구조"), `parse_amount("-")→None`(의도된 전사 정책, `test_
# blank_and_unparseable_still_none` 회귀로 고정돼 있어 그 함수 자체는 안 건드림)이라
# 그 칸이 amounts 에서 None으로 와서 "값이 아예 없는 행"과 구분이 안 돼 행 전체가
# 유실됐다(실측: 넥슨게임즈 "기초 현금및현금성자산"[원문 "-"], 자비스 "Ⅱ.투자활동"/
# "Ⅲ.재무활동"[원문 둘 다 "-"] — 전수확인: CF에서 "투자활동" 라벨 자체가 통째로 없는
# rcept×basis 2,127건, "재무활동" 없는 것 5,244건/전체 285,861건). `parse_amount()`는
# 그대로 두고 이 함수(구조화된 표 본문 셀만 다루는, note열은 이미 제외된 안전한 지점)
# 에서만 원시 텍스트가 순수 대시 하나뿐일 때 0으로 채워 넣는다.
_DASH_ONLY_PATTERNS = frozenset(["-", "─", "—", "―"])


def select_by_header_columns(
    columns: list[HeaderColumn], amounts: list, raw_amounts: Optional[list[str]] = None,
    allow_three_month_as_cumulative: bool = False,
    prefer_last_of_two_as_cumulative: bool = False,
    closing_runs: Optional[dict[int, list]] = None,
) -> dict[int, object]:
    """`HeaderColumn` 맵 + 위치보존 원시 `amounts`(`keep_all_amount_cells=True` 출력)
    → {period_rank: 값}. `_emit_section_lines`가 이 결과를 `col_index=period_rank`로
    그대로 emit 한다.

    규칙(설계문서 §3-4): 같은 period_rank 그룹에 subtype 있는 열이 하나라도 있으면
    "cumulative" 열만 채택(없는 값도 다른 서브타입으로 대체하지 않음 — R3/R85 원칙).
    전부 subtype=None(구분 텍스트 없는 병합군, 예 삼성생명 명세/소계)이면 값이 있는
    열 하나를 채택 — 2개 이상 값이 있으면(판정 불가) 그 rank 는 건너뛴다(R6 원칙).

    `raw_amounts`(R113) — amounts[pos]가 None인 칸의 원시 텍스트가 순수 대시뿐이면
    (공란·주석문자 등 다른 결측과 구분) 0으로 채택한다. 넘기지 않으면(기존 호출자)
    이 판정 자체를 건너뛰어 회귀 위험이 없다.

    ★R114(2026-09-14, 케이엠제약 20160516000811 IS/CF 별도 원문대조로 발견) — R113 직후
    회귀. SPAC 합병 첫 사업연도 표는 "제1(당)기" 하나의 라벨이 COLSPAN=2 로 물리열 2개를
    덮으면서(subtype 구분 텍스트 없음, 위 no-subtype 병합군 분기) 그중 **한 열 전체가
    구조적으로 순수 대시**고 실제 값은 나머지 한 열에만 있다("영업비용" 열1="-" 열2=
    "(21,402,210)"). R113 이 열1의 대시도 0 으로 채택해버리면 두 열 다 "값 있음"이 돼
    R6 판정불가 분기로 떨어져 **행 전체가 유실**됐다(실측: 케이엠제약 IS 별도 11행 중
    9행, CF 별도도 동형 붕괴). 그래서 이 분기에서는 먼저 **진짜 파싱값**(대시 아님)만으로
    후보를 추리고, 그 후보가 정확히 1개면 그 값을 채택한다(대시 열은 셈에서 제외). 진짜
    값이 하나도 없을 때만 — 즉 그룹 **전체**가 대시뿐일 때만 — 구조적 0(R113 취지)으로
    채택한다. 진짜 값이 2개 이상이면 기존대로 판정불가(R6)로 건너뛴다.

    ★R116(2026-09-14, 사용자 원문대조로 확정 — 형지I&C 20160516001490, 드림시큐리티
    20160511001294) — 위 두 Q1 보고서는 IS 표 전체가 "3개월" 칸만 채우고 "누적" 칸은
    통째로 공란인데("당기순이익" 행만 예외적으로 둘 다 채워, 두 값이 완전히 동일함을
    필자 스스로 보여준다), 1분기는 정의상 3개월=누적(연초부터 1분기 말까지 누적 =
    1분기 3개월 그 자체)이라 원문 자체의 기재누락으로 판단된다. 이 등식은 Q1 에서만
    항상 성립하고(H1/Q3 는 3개월≠누적) 이 두 필링에서만 실측 확인됐으므로, R3/R85
    원칙(누적 공란 → 3개월로 대체 안 함)을 전사 정책으로 뒤집지 않고 `allow_three_
    month_as_cumulative=True`일 때만(호출측이 예외 rcept 목록으로 좁혀서 넘김,
    `fin2/extract/report_lines.py::_Q1_CUM_BLANK_USE_3M_RCEPTS`) 누적 공란 시 3개월
    값으로 대체한다. 기본값 False — 넘기지 않는 기존 호출자는 회귀 없음.

    ★R120(2026-09-14, 사용자 확정 — "예외목록으로만 좁힐") — 웹케시 20180814001946,
    우리기술투자 20200813000621: H1 보고서 IS 표가 같은 라벨("제20기 반기" 등)을
    구분 텍스트 전혀 없이 물리적으로 다른 2열에 반복하는데, 두 열 다 실제 값이고
    서로 **다르다**(H1이라 3개월≠누적, 그룹 자체가 진짜 2개 기간을 담고 있음).
    DART 관행상 이런 무표지 2열 병합군은 항상 [3개월 먼저, 누적 나중] 순서인데,
    산수로 직접 검증했다(사용자 확인) — 웹케시: Q1 당기순이익(1,201,200,355) +
    이 표 1번째 열(2,965,233,784, 3개월=Q2단독) = 4,166,434,139 = 2번째 열(누적)과
    정확히 일치. 우리기술투자도 동형 검증. 값 2개가 서로 다른 "진짜 판정불가"
    상황이라 R116(값이 같을 때만 통과)과는 다른 분기 — 사용자가 일반 규칙화 대신
    예외목록으로 좁히기로 결정해(R6 정책 유지), `prefer_last_of_two_as_cumulative=
    True`일 때만(호출측 예외 rcept 목록, `fin2/extract/report_lines.py::
    _HEADERLESS_MERGE_LAST_IS_CUMULATIVE_RCEPTS`) 위치상 마지막 열을 채택한다.

    ★R131(2026-09-16, 사용자 확정 — "값이 완전히 같으면 항상 채택해도 R6 취지에 안
    어긋난다") — KD(케이디) 20200515002825: IS 별도 표 전체가 무표지 COLSPAN=2
    병합군인데("제47기 분기"/"제46기 분기", 3개월/누적 구분 텍스트 없음), 두 물리열이
    행마다 예외 없이 완전히 같은 값을 반복 기재한다(매출액 10,672,141,199 가 두 열
    모두 동일 등). R116 은 이 "값 동일" 판정을 원래도 갖고 있었지만
    `allow_three_month_as_cumulative` 플래그(Q1 누적-공란 대체라는 별개 취지) 뒤에
    갇혀 있어 예외목록에 없는 KD 는 표 전체가 유실됐다. 값이 완전히 같은 경우는
    R6 이 막으려는 "서로 다른 값 중 하나를 짐작"하는 상황 자체가 아니므로(모호함이
    없다) rcept 예외목록 없이 항상 채택하도록 일반화했다 — R116/R120 예외목록은
    각각의 원래 취지(공란 대체/서로 다른 값 중 위치 규칙 채택)로만 남는다."""
    def _amount_or_dash_zero(pos: int):
        if pos < len(amounts) and amounts[pos] is not None:
            return amounts[pos]
        if (raw_amounts is not None and pos < len(raw_amounts)
                and raw_amounts[pos].strip() in _DASH_ONLY_PATTERNS):
            return 0
        return None

    def _is_dash_only(pos: int) -> bool:
        return (raw_amounts is not None and pos < len(raw_amounts)
                and raw_amounts[pos].strip() in _DASH_ONLY_PATTERNS)

    def _is_dash_or_blank(pos: int) -> bool:
        if raw_amounts is None or pos >= len(raw_amounts):
            return False
        txt = raw_amounts[pos].strip()
        return txt == "" or txt in _DASH_ONLY_PATTERNS

    def _pick_from_group(group: list) -> object:
        """R125 — chosen 그룹에 물리열이 여러 개(2015+ 보험/증권사 명세/소계 분리
        서식, `allow_duplicate_subtype=True`로 통과된 경우만 여기 도달)일 때도,
        subtype=None 병합군(R113/R114)과 동일한 규칙으로 행별 유일값을 고른다: 실값이
        정확히 1개면 채택, 전부 대시/공란(대시 증거 최소 1개)이면 구조적 0, 그 외
        (진짜 결측 또는 2개 이상 실값=판정불가)는 None. 그룹이 1개뿐이면(기존 대다수
        호출) 그냥 그 열 값(회귀 없음)."""
        if len(group) == 1:
            return _amount_or_dash_zero(group[0].position)
        real_present = [c for c in group if amounts[c.position] is not None]
        if len(real_present) == 1:
            return amounts[real_present[0].position]
        if (not real_present and any(_is_dash_only(c.position) for c in group)
                and all(_is_dash_or_blank(c.position) for c in group)):
            return 0
        return None

    by_rank: dict[int, list[HeaderColumn]] = {}
    for hc in columns:
        if hc.is_note:
            continue
        by_rank.setdefault(hc.period_rank, []).append(hc)

    result: dict[int, object] = {}
    for rank, cols in by_rank.items():
        has_subtype = any(c.subtype is not None for c in cols)
        if has_subtype:
            cum = [c for c in cols if c.subtype == "cumulative"]
            chosen = cum if cum else [c for c in cols if c.subtype == "three_month"]
            if not chosen:
                chosen = cols
            # R125 — chosen 이 2개 이상(2015+ 명세/소계 분리 서식, allow_duplicate_
            # subtype=True 로 통과된 경우만)이어도 행별 유일값 규칙으로 고른다. 1개면
            # 기존과 동일한 결과(회귀 없음).
            value = _pick_from_group(chosen)
            if value is None and allow_three_month_as_cumulative and cum:
                # R116 — 누적 열이 공란이고(cum 열은 존재하나 값이 없음) 예외목록으로
                # 허용된 필링이면, 3개월 값을 그대로 누적 값으로 채택한다(Q1 한정 등식).
                three_month = [c for c in cols if c.subtype == "three_month"]
                if three_month:
                    value = _pick_from_group(three_month)
            if value is not None:
                result[rank] = value
        else:
            # R114: 진짜 파싱값(대시 아님)이 있는 열만으로 먼저 판정 — 구조적 대시 열은
            # "값 있음" 판정에서 제외해 R113 도입 전과 동일하게 유일값을 골라낸다.
            real_present = [c for c in cols if amounts[c.position] is not None]
            if len(real_present) == 1:
                result[rank] = amounts[real_present[0].position]
            elif (not real_present and cols
                  and any(_is_dash_only(c.position) for c in cols)
                  and all(_is_dash_or_blank(c.position) for c in cols)):
                # 진짜값 없음 + 최소 한 열은 순수대시(0 의 증거) + 나머지도 대시거나 완전공란
                # (다른 물리열 수를 가진 행이 이 열에서 그냥 빈 것뿐 — 이물질 텍스트 아님)
                # → 구조적 0(R113 취지 유지, 넥슨게임즈 "기초 현금및현금성자산" 실측:
                #   note 열 옆 병합군 2열 중 한쪽만 대시고 한쪽은 아예 빈칸).
                result[rank] = 0
            elif (len(real_present) >= 2
                  and len({amounts[c.position] for c in real_present}) == 1):
                # R131(2026-09-16, KD/케이디 20200515002825 IS 별도 원문대조로 발견) —
                # 서브타입 구분 텍스트가 아예 없는 병합군(드림시큐리티류/KD류)인데
                # 물리열들이 전부 **완전히 같은 값**을 중복 기재했다면, 이건 R6 이
                # 막으려는 "서로 다른 값 중 하나를 임의로 고르는" 판정불가 상황이
                # 아니라 애초에 모호함이 없는 이미 확정된 값이다 — 예외목록(rcept
                # 단위)으로 좁힐 이유가 없어 예외 플래그 없이 항상 채택한다(사용자
                # 결정: "값이 완전히 같으면 항상 채택해도 R6 취지에 안 어긋난다").
                # 이전엔 이 분기가 R116 플래그(`allow_three_month_as_cumulative`,
                # Q1 누적-공란 대체용으로 설계된 전혀 다른 취지) 뒤에 갇혀 있어, 그
                # 예외목록에 없는 KD 같은 필링은 매출액 등 핵심 행 전체가 통째로
                # 누락됐다(무표지 COLSPAN=2 병합군 전체가 이 분기 하나로 죽음).
                # R116 예외목록(`_Q1_CUM_BLANK_USE_3M_RCEPTS`)은 이 분기와 무관하게
                # 그대로 유지 — has_subtype 분기(위쪽)의 "누적 열은 있지만 값이
                # 공란" 대체 판정에만 쓰인다(서로 다른 값 중 하나를 채택하는 진짜
                # 판정이라 R6 대상, 예외목록 유지 필요).
                result[rank] = amounts[real_present[0].position]
            elif (prefer_last_of_two_as_cumulative and len(cols) == 2
                  and len(real_present) == 2):
                # R120 — 예외목록 필링: 서브타입 구분 텍스트가 아예 없는 병합군인데
                # 두 열 다 실제 값이고 서로 다르다(H1 등, 진짜 두 기간을 담은 표).
                # DART 관행상 무표지 2열은 항상 [3개월 먼저, 누적 나중] 순서 — 위치상
                # 마지막 열(누적)을 채택한다(호출측이 산수로 직접 검증한 예외목록에서만).
                result[rank] = amounts[max(real_present, key=lambda c: c.position).position]
            elif closing_runs is not None and len(cols) == 2 and len(real_present) == 2:
                # ★R168 — old two-column print layout ([detail, balance] per period):
                #   a group-closing row fills both cells. Pick the detail (left) cell
                #   only when the arithmetic proves the layout — see
                #   `_dual_closing_row_proved()`. Otherwise the rank stays skipped (R6).
                left, right = sorted(real_present, key=lambda c: c.position)
                run = closing_runs.get(rank) or []
                if _dual_closing_row_proved(
                        run, amounts[left.position], amounts[right.position]):
                    result[rank] = amounts[left.position]
            # 진짜값 0개+대시/공란 아닌 결측(진짜 결측) 또는 진짜값 2개 이상(서로 다른
            # 값, 판정불가, R6) 이면 이 rank 는 건너뜀.
    return result


def _dual_closing_row_proved(run: list, left, right) -> bool:
    """R168 — does this row's `left` cell provably belong to the row itself?

    `run` holds the left-only (detail cell) values of the rows since the last row
    that filled the balance cell, in order. The row closes that group when the
    balance cell equals either
      - a deduction chain: run[0] - |run[1]| - ... - |left|  (gross, then contras
        printed without parentheses: 건물 / 감가상각누계액 / 국고보조금), or
      - a signed sum: run[0] + run[1] + ... + left  (contras printed in
        parentheses, or an additive detail group).
    Exact integer equality only — no tolerance, so a coincidence needs the whole
    group to add up to the printed balance."""
    if not run:
        return False
    try:
        if run[0] - sum(abs(v) for v in run[1:]) - abs(left) == right:
            return True
        return sum(run) + left == right
    except TypeError:
        return False


def update_dual_closing_runs(
    columns: Optional[list[HeaderColumn]], amounts: list, runs: dict[int, list],
) -> None:
    """R168 — advance the per-rank detail-cell runs after a row was processed.

    Only two-column, subtype-free period groups are tracked. A row that fills
    only the detail (left) cell extends the run; any other row (balance cell
    filled, or both empty) ends the group."""
    if not columns:
        return
    by_rank: dict[int, list[HeaderColumn]] = {}
    for hc in columns:
        if hc.is_note:
            continue
        by_rank.setdefault(hc.period_rank, []).append(hc)
    for rank, cols in by_rank.items():
        if len(cols) != 2 or any(c.subtype is not None for c in cols):
            continue
        left, right = sorted(cols, key=lambda c: c.position)
        lv = amounts[left.position] if left.position < len(amounts) else None
        rv = amounts[right.position] if right.position < len(amounts) else None
        if lv is not None and rv is None:
            runs.setdefault(rank, []).append(lv)
        else:
            runs[rank] = []


# ★R158(2026-09-22) — 천단위 구분자가 **마침표**로 깨진 셀.
#   실측(전수 스캔 2,528개사 → 11필링 32셀): 재무제표 셀의 콤마 하나가 마침표로
#   렌더돼 소수점처럼 보인다. 결정적 증거는 트리니티항공 20260515001132 —
#   **같은 값**이 연결 표엔 '41,106,779.959', 별도 표엔 '41,106,779,959' 로 찍혔다.
#   코오롱 20260515002605 은 한 행 안에 나란히 있다: '393,211,876', '393,211.876'.
#   이걸 소수로 읽으면 값이 10³~10⁶ 배 작아진다 — 결측이 아니라 **값 왜곡**이라
#   기존 검산이 못 잡는다.
#
#   ★복원은 추측이 아니다. 숫자열은 온전히 남아 있고, 정확한 값이 **같은 행 다른
#   칸에 정수로** 들어 있다(구성요소가 전부 0 인 SCE 변동 행이라 합계 칸이 같은 값).
#   그래서 "같은 행에서 숫자열이 일치하는 정수 칸"을 찾아 그 배율만 가져온다.
#   뒤 0 이 잘리는 경우도 있어(('10,590,556.9') → 10,590,556,900) 텍스트만으로는
#   배율이 안 나오므로, 이 대조가 **유일한** 근거다.
#
#   안 건드리는 것: 주당손익처럼 **원 단위 소수가 정상인** 값. 같은 행에 일치하는
#   정수 칸이 없으면 그대로 둔다(에스티아이 20260515000677 '343.0' 은 주당 금액이고
#   행 안에 짝이 없어 손대지 않는다).
_DOT_GROUPED_RE = re.compile(
    r"^([(\[]?\s*[-−△▲]?\s*)(\d{1,3}(?:,\d{3})*)\.(\d+)(\s*[)\]]?)$")


# ★R159(2026-09-22) — **원문 자체의 오타 셀**을 rcept 단위 예외목록으로 교정한다.
#   R118("원문 자체의 헤더 오타"를 rcept 목록으로 교정)과 **같은 패턴**이고, 같은 이유로
#   일반 규칙화하지 않는다 — 제출인의 오타는 규칙이 없다.
#
#   등재 조건(사용자 확정 2026-09-22): 정정값이 **원문 다른 곳에 그대로 인쇄돼 있어**
#   추측 없이 확정될 때만. 근거를 주석에 반드시 남긴다.
#
#   ★왜 `manual_report_lines` 를 쓰지 않는가 — 그쪽은 (rcept, statement, basis) 스코프를
#   통째로 delete-then-insert 하므로, 셀 4개를 고치려고 SCE 80행을 전부 손으로 옮겨
#   적어야 하고 그 스코프는 이후 자동 재추출에서 영구 제외된다(manual 보호 가드).
#   나머지 76행이 정상인데 파서 개선 혜택을 못 받게 되므로 맞지 않는다.
_SOURCE_TYPO_CELL_FIXES = {
    # 핸즈코퍼레이션 00119140 20260515002776(2026Q1) 연결·별도 자본변동표 **자본금** 열 —
    # 천단위 구분자 자리에 '.5' 가 찍혔다(',500' → '.5' 오타). 같은 표
    # `2025.01.01 (기초자본)` 행의 같은 열에 `10,937,873,500` 이 정수로 인쇄돼 있고
    # 자본금은 그 사이 변동이 없어, 정정값이 원문으로 확정된다(사용자 확인 2026-09-22).
    # R158(행 안의 정수 짝 대조)은 **같은 행**만 보므로 이 건을 복원하지 못한다.
    ("20260515002776", "10,937,873.5"): "10,937,873,500",

    # 트리니티항공 00253770 20260515001132(2026Q1) 자본변동표 — 같은 계열 오타
    # (',' 를 '.' 로 찍음, 사용자 확정 2026-09-22). 세 셀 모두 정정값이 **같은 필링
    # 원문에 정수로 인쇄돼 있다**(등재 조건 충족, 실측 확인):
    #   '41,106,779.959'  → [연결SCE] '2025.01.01 (기초자본)' 같은 열 = 41,106,779,959
    #   '64,885,221.582'  → [연결SCE] '유상증자'                      = 64,885,221,582
    #   '281,021,610.634' → [연결BS]  '주식발행초과금'                 = 281,021,610,634
    # R158(같은 **행**의 정수 짝 대조)은 정답이 다른 행·다른 표에 있어 복원하지 못한다.
    ("20260515001132", "41,106,779.959"): "41,106,779,959",
    ("20260515001132", "64,885,221.582"): "64,885,221,582",
    ("20260515001132", "281,021,610.634"): "281,021,610,634",

    # 코오롱 00110875 20260515002605(2026Q1) 연결 자본변동표 '주식선택권의 부여' —
    # 같은 계열 오타(사용자 확정 2026-09-22). 열 구조는
    # [… 기타자본구성요소, 지배지분 합계, **비지배지분**, 자본 합계] 이고, 한 행에
    # 오타가 **두 칸** 있다(사용자 지적: 왼쪽 '지배지분 합계' 칸도 같은 오타).
    # 왼쪽 칸은 바로 옆 정수와 같은 값이라 R158 이 행 안 대조로 이미 복원한다.
    # 남는 '비지배지분' 칸은 **합계 항등식**이 정확히 확정한다(실측 검산):
    #   138,959,866 + 43,752,934 = 182,712,800   (자본 합계 열, 원문 인쇄값)
    #   393,211,876 +  7,823,674 = 401,035,550   (같음)
    # 즉 정정값의 근거가 원문에 인쇄된 합계라, 추측이 아니다.
    ("20260515002605", "(43,752.934)"): "(43,752,934)",
    ("20260515002605", "7,823.674"): "7,823,674",

    # HD한국조선해양 00164830 20250515002500(2025Q1) 연결 자본변동표 **비지배지분**
    # 열 — 같은 계열 오타(',' 를 '.' 로 찍음). 사용자가 DART 원문을 직접 확인하고
    # 세 칸 모두 콤마 오타(comma-for-dot)로 확정했다(2026-09-23, `.` → `,`
    # 그대로 자릿수 복원). `기타포괄손익-공정가치측정금융자산평가손익`,
    # `파생상품평가손익`(두 행) — 근거가 정수판이나 행 항등식으로 자동 확정되지
    # 않아 `docs/qa/dot_typo_needs_dart_2026-09-23.md` 로 DART 확인을 요청했던 건.
    ("20250515002500", "(41.423)"): "(41,423)",
    ("20250515002500", "(1,259.803)"): "(1,259,803)",
    ("20250515002500", "3,082.923"): "3,082,923",

    # HD한국조선해양 00164830 20250318001131(2024 사업보고서) 연결 자본변동표
    # `파생상품평가손익` **비지배지분** 열 — 같은 계열 오타. 같은 행 `기타포괄손익
    # 누계액` 칸에 정수 `(6,536,415)` 이 이미 인쇄돼 있어 그 옆 `지배기업 소유주지분
    # 합계` 칸의 `(6,536.415)` 는 R158(행 안 정수 짝)이 이미 복원한다(다른 조치 불필요).
    # 남는 **비지배지분** 칸은 사용자가 두 단계 합계 항등식으로 확정했다
    # (2026-09-23, DART 원문 대조): 지배기업 소유주지분 합계 + 비지배지분 = 자본
    # 총계 합계 →  (6,536,415) + (5,039,886) = 11,576,301 (부호는 전부 음수, 원문
    # 인쇄된 자본 총계 합계와 정확히 일치). 이 단계식(부분합+비지배지분=총계)은
    # `_repair_dot_grouped_cells`/`unresolved_dot_cell_indices` 의 **행 전체 누적합만
    # 보는** 항등식 검사가 놓치는 패턴이라 자동 근거가 안 붙었다(부록: 스캔 스크립트
    # 개선 필요 — 아래 `report_dot_typo_candidates.py` 참고).
    ("20250318001131", "(5,039.886)"): "(5,039,886)",

    # 한화투자증권 00148610 20180515001426(2018Q1) 연결 손익계산서 'I. 영업수익'
    # 제58기1분기 열 — 콤마 그룹핑 결손(자릿수 하나 누락: "637,930,27,772"의
    # "27" 그룹이 3자리가 아니라 2자리). 정정값은 **같은 필링** 사업보고서 요약
    # 연결포괄손익계산서(narrative 섹션, "(2) 요약연결포괄손익계산서")에
    # "637,930,827,772"로 정수 인쇄돼 있어 추측 없이 확정된다(등재 조건 충족).
    # 회사도 이 오타를 인지해 별도 정정신고(20180515002604, [기재정정])를 냈지만
    # 그 정정신고 본문은 PDF만 제출돼(XML/XBRL 없음) 통상 재적재 경로로 반영이
    # 안 된다 — 원본 필링(001426) 쪽의 원문 자체를 이 예외목록으로 직접 교정한다
    # (검증 이슈 #84907, 2026-09-26).
    ("20180515001426", "637,930,27,772"): "637,930,827,772",

    # ── R159 배치(2026-09-23) — 사용자 지시 "일괄 확인으로 진행해" ──
    # `scripts/scan_r159_batch_evidence.py` 로 전수 233필링을 재스캔해, 트윈
    # (정수판, 원문 다른 곳에 같은 값이 인쇄됨) 또는 **2개 이상** 구성요소가
    # 정확히 닫히는 행 항등식 근거가 있는 셀만 모았다. 안전장치:
    #   ① 깨진 셀 자신의 자릿수가 5자리 미만이면 제외(우연한 접두어 일치 방지 —
    #      실측: "4.5"→"45" 가 무관한 "4,500,000" 과 우연히 일치했었다),
    #   ② 트윈으로 지목된 정수 자체가 올바른 3자리 콤마 그룹핑인지 검증(실측:
    #      "24,27"·"21" 처럼 그룹핑이 깨진 값과의 우연한 일치를 걸러냄),
    #   ③ 항등식 성분이 1개뿐인 자기순환 매칭 제외(실측: 신라젠 같은 행 두 칸에
    #      같은 텍스트가 중복 인쇄된 경우),
    #   ④ 같은 (rcept, 원문 셀) 이 행마다 다른 값을 요구하면 통째로 제외(이번
    #      배치는 0건 충돌).
    # 감사 기록 전체(제외된 것 포함): `docs/qa/r159_batch_evidence_2026-09-23.md`.
    # 재적재: `scripts/apply_r159_batch_evidence.py --apply`.
    # 제주은행 20150515002022
    ("20150515002022", "310.731"): "310,731",  # twin: [연결] 재무상태표 `자    본    총    계` = `310,731`
    # 신라젠 20151130001214
    ("20151130001214", "(11,928,954,639.0)"): "(11,928,954,639)",  # 항등식(절삭): -11,928,954,639+-1,473,074,695 = -13,402,029,334
    # 지누스 20160516003013
    ("20160516003013", "523,502.188"): "523,502,188",  # twin: [별도] 재무상태표 `1. 상품` = `523,502,188`
    # DSC인베스트먼트 20170515001561
    ("20170515001561", "4,977,266,000.00"): "4,977,266,000",  # 항등식(절삭): 4,977,266,000+2,127,012,652+133,807,957+18,843,646+8,750,000,000 = 16,006,930,255
    # DSC인베스트먼트 20170814000779
    ("20170814000779", "4,977,266,000.00"): "4,977,266,000",  # 항등식(절삭): 4,977,266,000+2,127,012,652+133,807,957+18,843,646+8,750,000,000 = 16,006,930,255
    # DSC인베스트먼트 20171114000364
    ("20171114000364", "4,977,266,000.00"): "4,977,266,000",  # 항등식(절삭): 4,977,266,000+2,127,012,652+133,807,957+18,843,646+8,750,000,000 = 16,006,930,255
    # DSC인베스트먼트 20180515000655
    ("20180515000655", "4,977,266,000.00"): "4,977,266,000",  # 항등식(절삭): 4,977,266,000+2,127,012,652+133,807,957+18,843,646+8,750,000,000 = 16,006,930,255
    # 키움증권 20200813000574
    ("20200813000574", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20201112000299
    ("20201112000299", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20201113001196
    ("20201113001196", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20210319001202
    ("20210319001202", "(3,771,272.00)"): "(3,771,272)",  # 항등식(절삭): -3,771,272+-2,367,766,765 = -2,371,538,037
    ("20210319001202", "999,280,000.00"): "999,280,000",  # 항등식(절삭): 999,280,000+-35,280,000 = 964,000,000
    ("20210319001202", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20210325000836
    ("20210325000836", "(3,771,272.00)"): "(3,771,272)",  # 항등식(절삭): -3,771,272+-2,367,766,765 = -2,371,538,037
    ("20210325000836", "999,280,000.00"): "999,280,000",  # 항등식(절삭): 999,280,000+-35,280,000 = 964,000,000
    ("20210325000836", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20210813001239
    ("20210813001239", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20211112001135
    ("20211112001135", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20220318000997
    ("20220318000997", "(3,771,272.00)"): "(3,771,272)",  # 항등식(절삭): -3,771,272+-2,367,766,765 = -2,371,538,037
    ("20220318000997", "999,280,000.00"): "999,280,000",  # 항등식(절삭): 999,280,000+-35,280,000 = 964,000,000
    ("20220318000997", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20220318001093
    ("20220318001093", "(3,771,272.00)"): "(3,771,272)",  # 항등식(절삭): -3,771,272+-2,367,766,765 = -2,371,538,037
    ("20220318001093", "999,280,000.00"): "999,280,000",  # 항등식(절삭): 999,280,000+-35,280,000 = 964,000,000
    ("20220318001093", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20220324000600
    ("20220324000600", "(3,771,272.00)"): "(3,771,272)",  # 항등식(절삭): -3,771,272+-2,367,766,765 = -2,371,538,037
    ("20220324000600", "999,280,000.00"): "999,280,000",  # 항등식(절삭): 999,280,000+-35,280,000 = 964,000,000
    ("20220324000600", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # 키움증권 20231219000321
    ("20231219000321", "(3,771,272.00)"): "(3,771,272)",  # 항등식(절삭): -3,771,272+-2,367,766,765 = -2,371,538,037
    ("20231219000321", "999,280,000.00"): "999,280,000",  # 항등식(절삭): 999,280,000+-35,280,000 = 964,000,000
    ("20231219000321", "(44,689,600.00)"): "(44,689,600)",  # 항등식(절삭): -44,689,600+-57,762,612,211 = -57,807,301,811
    # GS리테일 20240313001562
    ("20240313001562", "104,717.922"): "104,717,922,000",  # twin: [연결] 재무상태표 `자본금` = `104,717,922,000`
    ("20240313001562", "1,205,490.069642"): "1,205,490,069,642",  # twin: [연결] 재무상태표 `자본잉여금` = `1,205,490,069,642`
    ("20240313001562", "1,208,990.756585"): "1,208,990,756,585",  # twin: [연결] 재무상태표 `자본잉여금` = `1,208,990,756,585`
    ("20240313001562", "1,209,097.777648"): "1,209,097,777,648",  # twin: [연결] 재무상태표 `자본잉여금` = `1,209,097,777,648`
    # 한진칼 20240313001682
    ("20240313001682", "(329,869.431)"): "(329,869,431)",  # 항등식(콤마): -329,869,431+483,404,045 = 153,534,614
    # 동국홀딩스 20240314001784
    ("20240314001784", "101,725.161364"): "101,725,161,364",  # twin: [연결] 재무상태표 `주식발행초과금` = `101,725,161,364`
    ("20240314001784", "(84,749.001951)"): "(84,749,001,951)",  # twin: [연결] 자본변동표 `인적분할` = `(84,749,001,951)`
    ("20240314001784", "115,958.687113"): "115,958,687,113",  # twin: [연결] 재무상태표 `주식발행초과금` = `115,958,687,113`
    # CJ ENM 20240318000857
    ("20240318000857", "101,147,441.547"): "101,147,441,547",  # twin: [연결] 재무상태표 `주식발행초과금 (주23)` = `101,147,441,547`
    # CJ ENM 20240516001775
    ("20240516001775", "101,147,441.547"): "101,147,441,547",  # twin: [연결] 재무상태표 `주식발행초과금 (주17)` = `101,147,441,547`
    # 한국단자공업 20250313001432
    ("20250313001432", "109,776,244.114"): "109,776,244",  # 항등식(절삭): 0+0+0+0+109,776,244 = 109,776,244
    ("20250313001432", "874,627.328"): "874,627",  # 항등식(절삭): 0+0+0+0+874,627 = 874,627
    # 롯데이노베이트 20250313001442
    ("20250313001442", "(30,705,162.852)"): "(30,705,162,852)",  # twin: [연결] 자본변동표 `기타포괄손익` = `(30,705,162,852)`
    ("20250313001442", "3,787,747.74"): "3,787,747,740",  # twin: [연결] 자본변동표 `기타포괄손익` = `3,787,747,740`
    # 동국제강 20250314001555
    ("20250314001555", "248,040.085"): "248,040,085,000",  # twin: [별도] 재무상태표 `자본금 (주1,21)` = `248,040,085,000`
    ("20250314001555", "853,428.562349"): "853,428,562,349",  # twin: [별도] 재무상태표 `주식발행초과금 (주21)` = `853,428,562,349`
    # 동국제강 20250317000722
    ("20250317000722", "248,040.085"): "248,040,085,000",  # twin: [별도] 재무상태표 `자본금 (주1,21)` = `248,040,085,000`
    ("20250317000722", "853,428.562349"): "853,428,562,349",  # twin: [별도] 재무상태표 `주식발행초과금 (주21)` = `853,428,562,349`
    # 에스엠 20250317000813
    ("20250317000813", "11,915,450.5"): "11,915,450,500",  # twin: [연결] 재무상태표 `자본금` = `11,915,450,500`
    # 동부건설 20250317000989
    ("20250317000989", "299,390.911568"): "299,390,911,568",  # twin: [연결] 재무상태표 `자본잉여금` = `299,390,911,568`
    ("20250317000989", "299,392.190088"): "299,392,190,088",  # twin: [연결] 재무상태표 `자본잉여금` = `299,392,190,088`
    ("20250317000989", "301,736.897128"): "301,736,897,128",  # twin: [연결] 재무상태표 `자본잉여금` = `301,736,897,128`
    ("20250317000989", "2,344.70704"): "2,344,707,040",  # twin: [연결] 자본변동표 `무상감자` = `2,344,707,040`
    # 원익피앤이 20250318001050
    ("20250318001050", "23,727,279.5"): "23,727,279,500",  # twin: [연결] 재무상태표 `자본금 (주22)` = `23,727,279,500`
    # 솔브레인홀딩스 20250318001278
    ("20250318001278", "531,385,205.367"): "531,385,205,367",  # twin: [연결] 재무상태표 `주식발행초과금 (주24)` = `531,385,205,367`
    ("20250318001278", "533,516,786.185"): "533,516,786,185",  # twin: [연결] 재무상태표 `주식발행초과금 (주24)` = `533,516,786,185`
    # 엔브이에이치코리아 20250318001375
    ("20250318001375", "19,086,102.95"): "19,086,102,950",  # twin: [별도] 자본변동표 `유상증자` = `19,086,102,950`
    # 선진 20250318001380
    ("20250318001380", "(13,803,943.739)"): "(13,803,943,739)",  # twin: [연결] 재무상태표 `기타포괄손익누계액` = `(13,803,943,739)`
    ("20250318001380", "3,463,875.61"): "3,463,875,610",  # twin: [연결] 재무상태표 `기타포괄손익누계액` = `3,463,875,610`
    # 한국단자공업 20250320000091
    ("20250320000091", "874,627.328"): "874,627",  # 항등식(절삭): 0+0+0+0+874,627 = 874,627
    # 롯데이노베이트 20250320001204
    ("20250320001204", "(30,705,162.852)"): "(30,705,162,852)",  # twin: [연결] 자본변동표 `기타포괄손익` = `(30,705,162,852)`
    ("20250320001204", "3,787,747.74"): "3,787,747,740",  # twin: [연결] 자본변동표 `기타포괄손익` = `3,787,747,740`
    # 티와이홀딩스 20250320001392
    ("20250320001392", "(112,964,672.273)"): "(112,964,672,273)",  # twin: [연결] 자본변동표 `2022.01.01 (기초자본)` = `(112,964,672,273)`
    ("20250320001392", "13,656,184.544"): "13,656,184,544",  # twin: [별도] 자본변동표 `자본에 직접 반영된 소유주와의 거래` = `13,656,184,544`
    ("20250320001392", "(99,308,487.729)"): "(99,308,487,729)",  # twin: [연결] 자본변동표 `2024.01.01 (기초자본)` = `(99,308,487,729)`
    # 비덴트 20250321000629
    ("20250321000629", "345,917,160.507"): "345,917,160,507",  # twin: [연결] 재무상태표 `자본잉여금` = `345,917,160,507`
    ("20250321000629", "(8,996,677.819)"): "(8,996,677,819)",  # 항등식(콤마): -8,996,677,819+8,996,668,000 = -9,819
    ("20250321000629", "336,920,482.688"): "336,920,482,688",  # twin: [연결] 재무상태표 `자본잉여금` = `336,920,482,688`
    ("20250321000629", "337,025,775.548"): "337,025,775,548",  # twin: [연결] 재무상태표 `자본잉여금` = `337,025,775,548`
    # 넥스틸 20250321001479
    ("20250321001479", "40,649,789.36"): "40,649,789,360",  # twin: [연결] 자본변동표 `유상증자` = `40,649,789,360`
    # 솔루스첨단소재 20250514001037
    ("20250514001037", "9,090.4406"): "9,090,440,600",  # twin: [연결] 재무상태표 `자본금 (주20)` = `9,090,440,600`
    # 롯데이노베이트 20250514001058
    ("20250514001058", "(268,324.499)"): "(268,324,499)",  # twin: [연결] 자본변동표 `기타포괄손익` = `(268,324,499)`
    ("20250514001058", "3,911,949.534"): "3,911,949,534",  # twin: [연결] 자본변동표 `기타포괄손익` = `3,911,949,534`
    # 일신방직 20250515000674
    ("20250515000674", "573,371,612.751"): "573,371,612,751",  # twin: [별도] 재무상태표 `이익잉여금 (주22)` = `573,371,612,751`
    ("20250515000674", "589,679,935.414"): "589,679,935,414",  # twin: [별도] 재무상태표 `이익잉여금 (주22)` = `589,679,935,414`
    # 에이피알 20250515001164
    ("20250515001164", "135,004,189.367"): "135,004,189,367",  # 항등식(콤마): 135,004,189,367+148,976,556,909+985,756,870+9,874,289,833+3,792,189,000 = 298,632,981,979
    ("20250515001164", "9,874,289.833"): "9,874,289,833",  # twin: [연결] 자본변동표 `2024.03.31 (기말자본)` = `9,874,289,833`
    ("20250515001164", "148,976,556.909"): "148,976,556,909",  # 항등식(콤마): 148,976,556,909+985,756,870+9,874,289,833+135,004,189,367+3,792,189,000 = 298,632,981,979
    ("20250515001164", "76,585,903.467"): "76,585,903,467",  # twin: [별도] 재무상태표 `기타불입자본` = `76,585,903,467`
    ("20250515001164", "3,604,616.55"): "3,604,616,550",  # twin: [연결] 자본변동표 `주식선택권` = `3,604,616,550`
    ("20250515001164", "110,132,414.567"): "110,132,414,567",  # twin: [별도] 재무상태표 `기타불입자본` = `110,132,414,567`
    ("20250515001164", "11,046,535.968"): "11,046,535,968",  # twin: [연결] 재무상태표 `기타자본` = `11,046,535,968`
    ("20250515001164", "219,837,405.839"): "219,837,405,839",  # twin: [별도] 재무상태표 `이익잉여금` = `219,837,405,839`
    # 비덴트 20250515001373
    ("20250515001373", "337,025,775.548"): "337,025,775,548",  # twin: [연결] 재무상태표 `자본잉여금` = `337,025,775,548`
    ("20250515001373", "336,920,482.688"): "336,920,482,688",  # twin: [별도] 재무상태표 `자본잉여금` = `336,920,482,688`
    # 솔브레인홀딩스 20250515002411
    ("20250515002411", "531,385,205.367"): "531,385,205,367",  # twin: [연결] 재무상태표 `주식발행초과금 (주14)` = `531,385,205,367`
    # 티케이케미칼 20250515002636
    ("20250515002636", "144,984,165.176"): "144,984,165,176",  # twin: [별도] 재무상태표 `기타불입자본 (주23)` = `144,984,165,176`
    # 에스엠 20250718000170
    ("20250718000170", "11,915,450.5"): "11,915,450,500",  # twin: [연결] 재무상태표 `자본금` = `11,915,450,500`
    # 일신방직 20250814001470
    ("20250814001470", "877,985,713.348"): "877,985,713,348",  # twin: [연결] 재무상태표 `이익잉여금 (주21)` = `877,985,713,348`
    ("20250814001470", "893,720,594.622"): "893,720,594,622",  # twin: [연결] 재무상태표 `이익잉여금 (주21)` = `893,720,594,622`
    ("20250814001470", "573,371,612.751"): "573,371,612,751",  # twin: [별도] 재무상태표 `이익잉여금 (주22)` = `573,371,612,751`
    ("20250814001470", "588,788,946.142"): "588,788,946,142",  # twin: [별도] 재무상태표 `이익잉여금 (주22)` = `588,788,946,142`
    # 솔브레인홀딩스 20250814003585
    ("20250814003585", "531,385,205.367"): "531,385,205,367",  # twin: [연결] 재무상태표 `주식발행초과금 (주14)` = `531,385,205,367`
    # 롯데이노베이트 20251113000705
    ("20251113000705", "(4,713,618.23)"): "(471,361,823)",  # 항등식(콤마): 0+0+0+-471,361,823+0 = -471,361,823
    # 솔루스첨단소재 20251113000798
    ("20251113000798", "9,090.4406"): "9,090,440,600",  # twin: [연결] 재무상태표 `자본금 (주20)` = `9,090,440,600`
    # 케이카 20251114001253
    ("20251114001253", "(1,210,134.237)"): "(1,210,134,237)",  # 항등식(콤마): -1,210,134,237+7,273,592,277+319,387,500 = 6,382,845,540
    # 비덴트 20251114002067
    ("20251114002067", "38,600,805.5"): "38,600,805,500",  # twin: [연결] 재무상태표 `자본금 (주21)` = `38,600,805,500`
    ("20251114002067", "337,025,775.548"): "337,025,775,548",  # twin: [연결] 재무상태표 `자본잉여금 (주21)` = `337,025,775,548`
    ("20251114002067", "336,920,482.688"): "336,920,482,688",  # twin: [별도] 재무상태표 `자본잉여금 (주21)` = `336,920,482,688`
    # 트리니티항공 20251114002175
    ("20251114002175", "(2,526,642.904)"): "(2,526,642,904)",  # twin: [별도] 자본변동표 `전환우선주의 보통주전환` = `(2,526,642,904)`
    ("20251114002175", "41,106,779.959"): "41,106,779,959",  # twin: [연결] 재무상태표 `주식발행초과금` = `41,106,779,959`
    ("20251114002175", "81,446,565.793"): "81,446,565,793",  # twin: [별도] 자본변동표 `유상증자` = `81,446,565,793`
    ("20251114002175", "122,553,345.752"): "122,553,345,752",  # twin: [연결] 재무상태표 `주식발행초과금` = `122,553,345,752`
    # 에스엠 20251114002727
    ("20251114002727", "11,915,450.5"): "11,915,450,500",  # twin: [연결] 재무상태표 `자본금` = `11,915,450,500`
    # 솔루스첨단소재 20251121000499
    ("20251121000499", "9,090.4406"): "9,090,440,600",  # twin: [연결] 재무상태표 `자본금 (주20)` = `9,090,440,600`
    # 아이텍 20260312001086
    ("20260312001086", "10,717,148.5"): "10,717,148,500",  # twin: [연결] 재무상태표 `자본금 (주1,23)` = `10,717,148,500`
    # 롯데이노베이트 20260313000002
    ("20260313000002", "3,787,747.74"): "3,787,747,740",  # twin: [연결] 자본변동표 `기타포괄손익-공정가치측정금융자산평가손익` = `3,787,747,740`
    # 사람인 20260313001349
    ("20260313001349", "5,841,631.5"): "5,841,631,500",  # twin: [연결] 재무상태표 `자본금 (주1,21)` = `5,841,631,500`
    ("20260313001349", "40,747,590.194"): "40,747,590,194",  # twin: [별도] 재무상태표 `자본잉여금 (주22)` = `40,747,590,194`
    ("20260313001349", "(12,173,327.829)"): "(12,173,327,829)",  # twin: [별도] 재무상태표 `기타자본 (주22)` = `(12,173,327,829)`
    # 삼호개발 20260316000588
    ("20260316000588", "3,373,888.521"): "3,373,888,521",  # twin: [연결] 재무상태표 `기타포괄손익누계액` = `3,373,888,521`
    ("20260316000588", "(3,437,758.191)"): "(3,437,758,191)",  # twin: [연결] 재무상태표 `기타포괄손익누계액` = `(3,437,758,191)`
    ("20260316000588", "(1,010,683.543)"): "(1,010,683,543)",  # twin: [연결] 재무상태표 `기타포괄손익누계액` = `(1,010,683,543)`
    # SK이노베이션 20260316000827
    ("20260316000827", "801.523"): "801,523",  # 항등식(콤마): 801,523+12,166,592 = 12,968,115
    # 샘씨엔에스 20260316001120
    ("20260316001120", "58,851,243.174"): "58,851,243,174",  # twin: [별도] 재무상태표 `자본잉여금` = `58,851,243,174`
    ("20260316001120", "29,194,031.5"): "29,194,031,500",  # twin: [별도] 재무상태표 `자본금` = `29,194,031,500`
    ("20260316001120", "101,335,589.479"): "101,335,589,479",  # twin: [별도] 재무상태표 `자본잉여금` = `101,335,589,479`
    # 아이텍 20260316001351
    ("20260316001351", "10,717,148.5"): "10,717,148,500",  # twin: [연결] 재무상태표 `자본금 (주1,23)` = `10,717,148,500`
    # 동부건설 20260316001362
    ("20260316001362", "299,392.190088"): "299,392,190,088",  # twin: [연결] 재무상태표 `자본잉여금` = `299,392,190,088`
    ("20260316001362", "(190,090.512691)"): "(190,090,512,691)",  # twin: [연결] 재무상태표 `기타불입자본` = `(190,090,512,691)`
    ("20260316001362", "301,736.897128"): "301,736,897,128",  # twin: [연결] 재무상태표 `자본잉여금` = `301,736,897,128`
    ("20260316001362", "(192,396.860531)"): "(192,396,860,531)",  # twin: [연결] 재무상태표 `기타불입자본` = `(192,396,860,531)`
    # 디아이티 20260317000522
    ("20260317000522", "37,441,783.272"): "37,441,783,272",  # twin: [연결] 재무상태표 `자본잉여금 (주26)` = `37,441,783,272`
    ("20260317000522", "(2,940,546.583)"): "(2,940,546,583)",  # twin: [연결] 재무상태표 `기타자본조정 (주26)` = `(2,940,546,583)`
    ("20260317000522", "176,398,167.157"): "176,398,167,157",  # twin: [별도] 재무상태표 `이익잉여금(결손금) (주26)` = `176,398,167,157`
    ("20260317000522", "37,866,841.428"): "37,866,841,428",  # twin: [연결] 재무상태표 `자본잉여금 (주26)` = `37,866,841,428`
    ("20260317000522", "(2,443,603.429)"): "(2,443,603,429)",  # twin: [연결] 재무상태표 `기타자본조정 (주26)` = `(2,443,603,429)`
    ("20260317000522", "199,549,590.004"): "199,549,590,004",  # twin: [별도] 재무상태표 `이익잉여금(결손금) (주26)` = `199,549,590,004`
    # 가온그룹 20260317000844
    ("20260317000844", "64,185,313.698"): "64,185,313,698",  # twin: [연결] 재무상태표 `주식발행초과금` = `64,185,313,698`
    ("20260317000844", "64,509,534.478"): "64,509,534,478",  # twin: [연결] 재무상태표 `주식발행초과금` = `64,509,534,478`
    # 에스디바이오센서 20260318001064
    ("20260318001064", "62,239,087.5"): "62,239,087,500",  # twin: [연결] 재무상태표 `자본금 (주1,26)` = `62,239,087,500`
    # 한국콜마 20260318001196
    ("20260318001196", "294,691,580.186"): "294,691,580,186",  # twin: [연결] 재무상태표 `자본잉여금` = `294,691,580,186`
    ("20260318001196", "301,017,007.22"): "301,017,007,220",  # twin: [연결] 재무상태표 `자본잉여금` = `301,017,007,220`
    ("20260318001196", "215,040,092.763"): "215,040,092,763",  # twin: [별도] 재무상태표 `자본잉여금` = `215,040,092,763`
    # 솔브레인홀딩스 20260318001251
    ("20260318001251", "531,385,205.367"): "531,385,205,367",  # twin: [연결] 재무상태표 `주식발행초과금 (주24)` = `531,385,205,367`
    ("20260318001251", "530,319,414.958"): "530,319,414,958",  # twin: [연결] 재무상태표 `주식발행초과금 (주24)` = `530,319,414,958`
    # 현대무벡스 20260318001359
    ("20260318001359", "11,754,886.4"): "11,754,886,400",  # twin: [연결] 재무상태표 `자본금 (주22)` = `11,754,886,400`
    ("20260318001359", "11,774,105.8"): "11,774,105,800",  # twin: [연결] 재무상태표 `자본금 (주22)` = `11,774,105,800`
    ("20260318001359", "11,797,003.9"): "11,797,003,900",  # twin: [연결] 재무상태표 `자본금 (주22)` = `11,797,003,900`
    # 비에이치 20260318001437
    ("20260318001437", "17,232,189.5"): "17,232,189,500",  # twin: [연결] 재무상태표 `자본금` = `17,232,189,500`
    # 파크시스템스 20260319000022
    ("20260319000022", "49,189,370.216"): "49,189,370,216",  # twin: [연결] 재무상태표 `자본잉여금` = `49,189,370,216`
    ("20260319000022", "(142,741.576)"): "(142,741,576)",  # twin: [연결] 재무상태표 `기타자본구성요소` = `(142,741,576)`
    ("20260319000022", "50,814,090.318"): "50,814,090,318",  # twin: [연결] 재무상태표 `자본잉여금` = `50,814,090,318`
    ("20260319000022", "1,237,266.166"): "1,237,266,166",  # twin: [연결] 재무상태표 `기타자본구성요소` = `1,237,266,166`
    ("20260319000022", "51,809,405.08"): "51,809,405,080",  # twin: [연결] 재무상태표 `자본잉여금` = `51,809,405,080`
    ("20260319000022", "2,884,245.304"): "2,884,245,304",  # twin: [연결] 재무상태표 `기타자본구성요소` = `2,884,245,304`
    # 헥토이노베이션 20260319001375
    ("20260319001375", "6,788,592.5"): "6,788,592,500",  # twin: [연결] 재무상태표 `자본금` = `6,788,592,500`
    # 티와이홀딩스 20260320000006
    ("20260320000006", "311,658,910.27"): "311,658,910,270",  # twin: [연결] 자본변동표 `2024.01.01 (기초자본)` = `311,658,910,270`
    ("20260320000006", "755,173,526.218"): "755,173,526,218",  # twin: [연결] 재무상태표 `기타불입자본` = `755,173,526,218`
    ("20260320000006", "(99,308,487.729)"): "(99,308,487,729)",  # twin: [연결] 자본변동표 `2023.12.31 (기말금액)` = `(99,308,487,729)`
    ("20260320000006", "278,425,162.402"): "278,425,162,402",  # twin: [별도] 자본변동표 `2025.01.01 (기초자본)` = `278,425,162,402`
    # 컴투스 20260320001410
    ("20260320001410", "1,845,357.21"): "1,845,357,210",  # twin: [연결] 손익계산서 `유형자산재평가잉여금` = `1,845,357,210`
    # 두산 20260323000945
    ("20260323000945", "(35,851.435)"): "(35,851)",  # 항등식(절삭): 0+0+0+0+-35,851 = -35,851
    # 아이텍 20260323001195
    ("20260323001195", "10,717,148.5"): "10,717,148,500",  # twin: [연결] 재무상태표 `자본금 (주1,23)` = `10,717,148,500`
    # 트리니티항공 20260430001360
    ("20260430001360", "(2,526,642.904)"): "(2,526,642,904)",  # twin: [별도] 자본변동표 `전환우선주의 보통주전환` = `(2,526,642,904)`
    ("20260430001360", "41,106,779.959"): "41,106,779,959",  # twin: [연결] 재무상태표 `주식발행초과금` = `41,106,779,959`
    ("20260430001360", "81,446,565.793"): "81,446,565,793",  # twin: [별도] 자본변동표 `유상증자` = `81,446,565,793`
    ("20260430001360", "122,553,345.752"): "122,553,345,752",  # twin: [연결] 재무상태표 `주식발행초과금` = `122,553,345,752`
    # 롯데이노베이트 20260514001479
    ("20260514001479", "3,911,949.534"): "3,911,949,534",  # 항등식(콤마): 0+0+0+3,911,949,534+0 = 3,911,949,534
    ("20260514001479", "1,588,948.074"): "1,588,948,074",  # 항등식(콤마): 0+0+0+1,588,948,074+0 = 1,588,948,074
    # 테스 20260813000486
    ("20260813000486", "16,424,279.872"): "16,424,279,872",  # twin: [별도] 자본변동표 `복합금융상품 전환` = `16,424,279,872`
    # 코나아이 20260813000976
    ("20260813000976", "328,441.563"): "328,441,563",  # 항등식(콤마): 328,441,563+19,545,835 = 347,987,398
    # 트리니티항공 20260813001054
    ("20260813001054", "41,106,779.959"): "41,106,779,959",  # twin: [연결] 자본변동표 `2025.01.01 (기초자본)` = `41,106,779,959`
    ("20260813001054", "64,885,221.582"): "64,885,221,582",  # twin: [별도] 자본변동표 `유상증자` = `64,885,221,582`
    ("20260813001054", "281,021,610.634"): "281,021,610,634",  # twin: [연결] 재무상태표 `주식발행초과금` = `281,021,610,634`
    # 지누스 20260813001752
    ("20260813001752", "(10,142.5)"): "(10,142,500)",  # twin: [별도] 자본변동표 `자기주식 소각` = `(10,142,500)`
    # ISC 20260814000114
    ("20260814000114", "282,597,448.374"): "282,597,448,374",  # twin: [연결] 재무상태표 `기타불입자본 (주21)` = `282,597,448,374`
    # 삼호개발 20260814000878
    ("20260814000878", "(1,772,246.704)"): "(1,772,246,704)",  # twin: [연결] 재무상태표 `기타포괄손익누계액` = `(1,772,246,704)`
    # DMS 20260814001068
    ("20260814001068", "59,947,308.702"): "59,947,308,702",  # twin: [연결] 재무상태표 `기타불입자본 (주23,39)` = `59,947,308,702`
    ("20260814001068", "339,900,260.825"): "339,900,260,825",  # twin: [연결] 재무상태표 `이익잉여금(결손금) (주24)` = `339,900,260,825`
    ("20260814001068", "56,947,310.112"): "56,947,310,112",  # twin: [연결] 재무상태표 `기타불입자본 (주23,39)` = `56,947,310,112`
    ("20260814001068", "25,874,801.049"): "25,874,801,049",  # twin: [연결] 재무상태표 `기타자본구성요소 (주23)` = `25,874,801,049`
    ("20260814001068", "335,475,492.533"): "335,475,492,533",  # twin: [연결] 재무상태표 `이익잉여금(결손금) (주24)` = `335,475,492,533`
    # 달바글로벌 20260814001262
    ("20260814001262", "1,882,709.045"): "1,882,709,045",  # twin: [연결] 자본변동표 `주식기준보상거래를 통한 증가(감소), 지분` = `1,882,709,045`
    ("20260814001262", "2,377,689.05"): "2,377,689,050",  # twin: [연결] 자본변동표 `주식기준보상거래를 통한 증가(감소), 지분` = `2,377,689,050`
    # 티와이홀딩스 20260814001733
    ("20260814001733", "1,746,275.64"): "1,746,275,640",  # twin: [연결] 자본변동표 `자기주식 소각` = `1,746,275,640`
    # 휴비츠 20260814002031
    ("20260814002031", "6,964,579.85"): "6,964,579,850",  # twin: [연결] 재무상태표 `자본잉여금` = `6,964,579,850`
    # HLB 20260814002713
    ("20260814002713", "65,697,424.5"): "65,697,424,500",  # twin: [별도] 자본변동표 `2025.01.01 (기초자본)` = `65,697,424,500`
    ("20260814002713", "451,570,963.518"): "451,570,963,518",  # twin: [별도] 자본변동표 `2025.01.01 (기초자본)` = `451,570,963,518`
    ("20260814002713", "65,718,940.5"): "65,718,940,500",  # twin: [별도] 자본변동표 `2025.06.30 (기말자본)` = `65,718,940,500`
    ("20260814002713", "455,108,416.644"): "455,108,416,644",  # twin: [별도] 자본변동표 `2025.06.30 (기말자본)` = `455,108,416,644`
    ("20260814002713", "66,370,831.5"): "66,370,831,500",  # twin: [연결] 재무상태표 `자본금 (주1,15)` = `66,370,831,500`
    ("20260814002713", "520,287,459.733"): "520,287,459,733",  # twin: [연결] 재무상태표 `주식발행초과금 (주15)` = `520,287,459,733`
    ("20260814002713", "1,344,092.168"): "1,344,092,168",  # twin: [별도] 자본변동표 `주식매입선택권 행사` = `1,344,092,168`
    ("20260814002713", "23,729,107.927"): "23,729,107,927",  # twin: [별도] 자본변동표 `전환사채의 전환` = `23,729,107,927`
    ("20260814002713", "66,602,819.5"): "66,602,819,500",  # twin: [연결] 재무상태표 `자본금 (주1,15)` = `66,602,819,500`
    ("20260814002713", "545,360,659.828"): "545,360,659,828",  # twin: [연결] 재무상태표 `주식발행초과금 (주15)` = `545,360,659,828`
    # 오션인더블유 20260814003068
    ("20260814003068", "86,024,912.543"): "86,024,912,543",  # 항등식(콤마): 86,024,912,543+6,753,618,684+109,199,776,076+84,325,717,500 = 286,304,024,803
    ("20260814003068", "66,932,910.393"): "66,932,910,393",  # twin: [연결] 재무상태표 `이익잉여금 (주1)` = `66,932,910,393`
    ("20260814003068", "75,383,936.428"): "75,383,936,428",  # twin: [연결] 재무상태표 `이익잉여금 (주1)` = `75,383,936,428`
    # HL홀딩스 20260814003923
    ("20260814003923", "86,187,193.68"): "86,187,193,680",  # twin: [연결] 재무상태표 `기타포괄손익누계액 (주19)` = `86,187,193,680`
    # 파크시스템스 20260814004158
    ("20260814004158", "159,389,082.123"): "159,389,082,123",  # twin: [연결] 재무상태표 `자본잉여금` = `159,389,082,123`
    ("20260814004158", "3,743,360.968"): "3,743,360,968",  # twin: [연결] 재무상태표 `기타자본구성요소` = `3,743,360,968`
    # 에이프로 20260814004171
    ("20260814004171", "50,747,524.119"): "50,747,524,119",  # twin: [연결] 재무상태표 `자본잉여금` = `50,747,524,119`

    # 미래에셋증권 00111722 20250515002840(2025Q1) 연결 자본변동표 2025.03.31(기말자본) —
    # ★위 항목들과 반대 해석이다. 이 표는 백만원 선언(ADECIMAL=-6)이고, 소수부는 콤마 오타가
    # 아니라 **진짜 소수 정밀도 아티팩트**다(원문 그대로). 같은 열의 2024.03.31/2025.01.01
    # 은 정수로 인쇄돼 있고, 이 분기 자본의 변동 세부항목이 전부 0이라 기말=기초 항등식으로
    # 반올림값이 자기증명된다(사용자 확인 불요 — 같은 문서 값과 정확히 일치, R159 등재조건
    # 충족). 여기선 소수부를 **반올림해 버린다**(콤마로 이어붙이지 않는다) — 등재값은
    # parse_amount 가 표 배수(×10⁶)로 재해석하므로 정수 형태로 넣는다.
    ("20250515002840", "4,101,960.79"): "4,101,961",  # self-proof: 2024.03.31/2025.01.01 자본금 열 = 4,101,961(변동 0)
    ("20250515002840", "2,157,082.249016"): "2,157,082",  # self-proof: 2024.03.31/2025.01.01 자본잉여금 열 = 2,157,082(변동 0)
}


def apply_source_typo_fixes(cells: list[str],
                            rcept_no: Optional[str]) -> list[str]:
    """`_SOURCE_TYPO_CELL_FIXES` 에 등재된 셀만 교정한다(없으면 원본 그대로).

    ★두 추출 경로(`extract_rows`, `report_lines._grid_body_rows`)가 **같은 함수**를
      불러야 한다 — 같은 판정을 두 경로가 각자 하면 갈린다(R144/R153/R158 교훈).
    """
    if not rcept_no or not _SOURCE_TYPO_CELL_FIXES:
        return cells
    out = None
    for i, c in enumerate(cells):
        fixed = _SOURCE_TYPO_CELL_FIXES.get((rcept_no, (c or "").strip()))
        if fixed is None:
            continue
        if out is None:
            out = list(cells)
        out[i] = fixed
    return out if out is not None else cells


def _digits_only(text: str) -> str:
    return re.sub(r"[^\d]", "", text or "")


# ★주당손익 행은 R158 대상이 아니다 — 주당 금액은 **원 단위 소수가 정상**이고
#   (`'(69.0)'` → -69), 그 행에는 `['주당이익','(1,500.00)','(1,500,000)']` 처럼 짝처럼
#   보이는 배치가 실제로 나온다(핸즈코퍼레이션 20260515002776 IS 실측: `'(1,500.00)'`
#   과 `'(1,500)'` 이 한 행에 있다). 지금 규칙은 우연히 안 걸리지만, 자릿수가 하나만
#   달라지면 EPS 를 1,500,000 으로 **날조**한다. 라벨로 먼저 배제한다.
#   ★'주당' 만으로는 부족하다 — **라벨이 자기 단위를 원으로 선언한 행**도 per-row
#     단위라 소수가 정상이다. 실측: 에스티아이 20260515000677 별도IS
#     `['희석당기순이익 (단위 : 원)', '343.0', ...]` — '주당' 이 라벨에 없지만 343원은
#     주당 금액이고, 결측으로 만들면 **실제 데이터를 잃는다**(R160 테스트에서 드러났다).
#     R149 가 셀 단위 '원' 접미사를 같은 취지로 다루는 것과 짝을 이룬다.
_EPS_ROW_LABEL_RE = re.compile(
    r"주당|per\s*share|[(（]\s*단위\s*[:：]?\s*원\s*[)）]", re.I)


def unresolved_dot_cell_indices(amount_cells: list[str],
                                label: Optional[str]) -> list[int]:
    """R159/R158 로도 **해결되지 않은** 마침표 셀의 위치 — 값을 적재하지 않을 칸.

    ★사용자 정책(2026-09-22): "재무문서에 '.' 으로 되어 있는 큰 금액 오타를 반올림해서
      적재하거나 그대로 하지 말고, 오타로 보고해서 확인 요청할 리스트로 제공하라."

      종전 동작은 둘 다 틀린 값을 남겼다 — `int(float())` 절삭(10³~10⁶ 배 작음)이든
      R157 반올림(±1 움직이지만 여전히 10³ 배 작음)이든 **정밀해 보이는 틀린 값**이
      DB 에 들어가 검산을 통과했다. 결측으로 남기면 그 사실이 드러난다(R6 "오염보다
      결측"). 확인 후 정정값은 R159 예외목록으로 들어간다.

    대상 조건 — 둘 다 만족할 때:
      ① 마침표-구분자 패턴(`_DOT_GROUPED_RE`)이고
      ② 주당손익 행이 **아니다** — 주당 금액은 원 단위 소수가 정상이다(`'343.0'` → 343).

    ★**단위 선언으로 예외를 두지 않는다**(사용자 결정 2026-09-22, B안). 초판은
      `multiplier != 1`(천원/백만원 선언 표)를 "소수가 정상 표기"라며 제외했는데,
      그건 내가 **관측 없이 단정한** 것이었다 — 전수 스캔 2,528개사에서 나온 소수 셀
      32개는 **전부 선언단위 '원'** 이었고, 천원/백만원 표의 소수는 **0건**이다.
      정상이라는 증거가 없으므로 예외를 두지 않고 똑같이 보고한다. 실측 0건이라
      당장 바뀌는 동작은 없고, 그런 필링이 나타날 때 파서가 임의로 판단하지 않게 된다.
      (`parse_amount` 의 R157 소수부 처리는 그대로 남는다 — 주석·XBRL 등 다른 호출
      경로에도 걸리고, 소수부를 버리는 것 자체가 버그다.)

    호출 시점은 R159(오타 교정)·R158(행 안 정수 짝 복원) **뒤**다 — 그 둘이 해결한
    셀은 이미 정상 정수 텍스트로 바뀌어 이 패턴에 안 걸린다.
    """
    if label and _EPS_ROW_LABEL_RE.search(label):
        return []
    return [i for i, c in enumerate(amount_cells)
            if _DOT_GROUPED_RE.match((c or "").strip())]


def _repair_dot_grouped_cells(amount_cells: list[str],
                              label: Optional[str] = None) -> list[str]:
    """행 안에서 짝을 찾아 마침표-구분자 셀을 복원한다(못 찾으면 그대로).

    판정: 깨진 셀의 숫자열이 같은 행의 **정수 칸** 숫자열의 접두사이고, 남는
    꼬리가 전부 0 이면 그 정수 칸의 자릿수를 정답으로 본다.
        '42,549.493'  ↔ '42,549,493'      (정확히 일치)
        '10,590,556.9' ↔ '10,590,556,900' (꼬리 '00' — 잘린 뒤 0)
    """
    if label and _EPS_ROW_LABEL_RE.search(label):
        return amount_cells                 # 주당손익 행 — 위 주석 참고
    broken = [i for i, c in enumerate(amount_cells)
              if _DOT_GROUPED_RE.match((c or "").strip())]
    if not broken:
        return amount_cells

    # 같은 행의 '온전한 정수' 칸들(마침표 없음)의 숫자열
    intact = []
    for c in amount_cells:
        t = (c or "").strip()
        if not t or "." in t:
            continue
        d = _digits_only(t)
        if d:
            intact.append(d)
    if not intact:
        return amount_cells

    out = list(amount_cells)
    for i in broken:
        m = _DOT_GROUPED_RE.match(amount_cells[i].strip())
        digits = _digits_only(m.group(2)) + m.group(3)
        # 더 긴 후보가 여러 개면 판정불가로 두고 손대지 않는다(R6).
        cands = {d for d in intact
                 if len(d) >= len(digits) and d.startswith(digits)
                 and set(d[len(digits):]) <= {"0"}}
        if len(cands) != 1:
            continue
        full = cands.pop()
        out[i] = f"{m.group(1)}{full}{m.group(4)}"
    return out


def _split_label_amounts(
    cells: list[str], table_has_note_column: bool = False,
) -> tuple[str, list[str]]:
    """`_split_label_amounts_ex()`의 (label, amount_cells) 만 쓰는 얇은 래퍼 — 기존
    호출자(테스트 다수 포함)의 2-tuple 시그니처를 그대로 유지한다. 새 필요(§5.4
    acontext_missing 플래그)가 있으면 `_split_label_amounts_ex()`를 직접 쓸 것."""
    label, amount_cells, _flags = _split_label_amounts_ex(cells, table_has_note_column)
    return label, amount_cells


def _split_label_amounts_ex(
    cells: list[str], table_has_note_column: bool = False,
    cells_el: Optional[list[etree._Element]] = None,
) -> tuple[str, list[str], list[bool]]:
    """
    셀 리스트에서 계정과목명(첫 번째 비숫자 셀)과 금액 셀을 분리한다.

    `_split_label_amounts()`의 실제 본체(로직 복제 금지 — 반드시 이 함수 하나만 고칠 것).
    `cells_el`(옵션, `cells`와 같은 인덱스의 원본 엘리먼트 리스트, `_get_cell_elements`
    참고)을 주면 살아남은 각 amount_cells 원소마다 `_cell_acontext_missing()` 플래그를
    **같은 인덱스로** 나란히 반환한다(§5.4). `cells_el=None`이면 세 번째 반환값은 빈 리스트.

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
        3) **빈칸**("")도 `table_has_note_column=True`인 표에서는 항상 주석 칸으로 본다
           (2026-08-24, Gate B 버그① col-misselect 근본원인 재규명). 위 1)/2)는 칸에
           내용이 있을 때만 걸렸다 — 그런데 "이 행은 주석 없음"이라 그 칸이 비어 있는 경우는
           `_NOTE_REF_PATTERN`에 안 걸려 그대로 amount_cells 의 첫 칸(빈칸→None)으로 샜다.
           `table_has_note_column`은 이미 "이 표는 라벨과 금액 사이에 주석 컬럼을 구조적으로
           둔다"를 표 전체 스캔으로 확정한 값이므로, 그 표에서 i==1 칸은 **내용과 무관하게**
           항상 주석 칸이다 — 콤마 다중참조든 단일숫자든 빈칸이든 같은 구조적 위치.
           (코리안리 20211115001569 원문대조로 확정 — 이 칸이 안 걸리면 소비 측이 인터림
           누적컬럼을 절대위치로 인덱싱할 때 한 칸씩 밀려 읽는다, 계획서
           `gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md` §3-4 참고.)
      세 경우 모두 **라벨 바로 다음 칸(i==1)에서만** 판정한다 — 아니면 콤마 없는 소액이
      연달아 나오는 행(예: "992 | 766")에서 둘 다 드롭되는 연쇄 오탐이 생긴다.
    """
    label = ""
    amount_cells: list[str] = []
    flags: list[bool] = []

    for i, cell in enumerate(cells):
        if i == 0:
            # 첫 셀은 항상 계정과목명
            label = cell
        else:
            # 쉼표 보존(주석 판정용). 개행/탭도 공백과 같이 지운다 — 원문이 한 금액을
            # TD 안에서 개행으로 끊어 담는 경우가 있고(R144, `strip_cell_whitespace`
            # 주석 참고), 안 지우면 아래 `_NUMBER_PATTERN`(^…$ 앵커)이 못 맞춰 그 셀이
            # amount_cells 에서 통째로 빠진다 → 뒤 열이 당기 열로 밀리거나 행이 사라진다.
            cell_nospace = strip_cell_whitespace(cell)
            # 합계행 밑줄 장식(숫자 뒤 '====' 등) 제거 — 숫자 셀 인식용(parse_amount 도 동일 처리).
            cell_nospace = _TRAIL_DECOR_RE.sub('', cell_nospace)
            cell_stripped = cell_nospace.replace(',', '')      # 쉼표 제거(금액 판정용)
            # ★2026-08-24: 이 표가 주석 컬럼을 쓴다고 이미 확정됐으면(table_has_note_column)
            # i==1 칸은 빈칸이어도 항상 주석 칸 — "이 행만 주석 없음"이지 칸 자체가 없는 게
            # 아니다. 위 docstring 3) 참고. 빈칸은 콤마/단일숫자 판정과 달리 모호성이 없다
            # (빈칸이 "진짜 소액금액"일 수는 없다 — 그냥 없는 값).
            if (i == 1 and not amount_cells and table_has_note_column
                    and cell_nospace == ''):
                continue
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
                if cells_el is not None:
                    flags.append(_cell_acontext_missing(cells_el[i]) if i < len(cells_el) else False)
            # 숫자가 아닌 추가 텍스트 → 무시

    return label, amount_cells, flags


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

    allow_date_label: True 면 "기간 날짜" 규칙과 "기수" 규칙을 끈다 — **자본변동표(SCE) 전용**.
        SCE 는 기초/기말 잔액 행의 라벨이 날짜다("2023.01.01 (기초자본)"). BS/IS/CF 에서
        이 규칙은 기간 헤더 행을 거르는 올바른 동작이지만, SCE 에 그대로 적용하면 그 표의
        **앵커 행이 통째로 사라진다**(실측 2,519행/250보고서 — 기초+Σ변동=기말 검산 불가).
        날짜 '범위' 헤더("2023.01.01~2023.12.31")는 아래 별도 규칙이 계속 잡으므로 안전하다.

        ★R134(2026-09-16): SCE 앵커 행 라벨이 "2014.04.01 (제26기 분기초)"처럼 날짜에
        "제N기"까지 같이 붙는 경우가 있다. 아래 "기수" 규칙은 "원"·"%" 가 없으면 헤더로
        보는데(BS/IS/CF 주석 헤더 셀 판정용, R28) 이 앵커 행도 "원"·"%" 가 없어 그대로
        걸려 행 전체(모든 열)가 사라진다(메이슨캐피탈 20150817001754 원문대조로 확정).
        SCE 에서 "제N기"가 붙는 라벨은 전부 이런 날짜 앵커 행이라 "기수" 규칙도 같이
        꺼야 한다 — BS/IS/CF 경로는 allow_date_label=False 라 영향 없음.
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
    if not allow_date_label and re.search(r'제\s*\d+\s*기', text) and not re.search(r'원|%', text):
        return "기수"
    # 단위 표기: "(단위 : 원)", "단위:천원" — ★R178(2026-09-26): 라벨 **전체**가 단위
    #   선언뿐일 때만. 종전 `search`는 라벨 어디에든 "단위:"가 있으면 헤더로 봐서,
    #   "자기주식 소각 (단위: 주)"·"발행한 주식수 (단위 : 주)"처럼 **자기 라벨에 단위를
    #   부기한 진짜 데이터 행**(R149 '2,564원'과 같은 계열의 정상 표기)을 헤더로 오분류했다.
    #   실측(note_lines 고유라벨 6,098개 표본): "단위:" 를 포함한 라벨 중 진짜로 그 표기
    #   뿐인 것은 3개뿐(예 "단위 : 천USD,천원") — 나머지 99.95%는 데이터 행이었다.
    #   주석(`keep_header_rows=True`)은 hint만 붙어 행을 잃지 않지만, SCE·BS/IS/CF 본문은
    #   기본이 `keep_header_rows=False`라 오분류 행이 통째로 드롭됐다(카카오 20250318001297
    #   con-SCE "자기주식 소각 (단위: 주)" 3개 회계연도·13셀 실측 — 자본금·자본잉여금·
    #   자본조정·지분합계·자본합계 전부 유실).
    if re.fullmatch(r'[\(（]?\s*단위\s*[:：]?\s*[가-힣A-Za-z0-9%,.\s()（）]*[\)）]?', text):
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
