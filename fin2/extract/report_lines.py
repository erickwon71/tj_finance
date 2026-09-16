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

import json
import re

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import (
    extract_rows, _split_label_amounts, _get_cells, _NUMBER_PATTERN, expand_table_grid,
    RowData, _header_rule_name, _is_fs_title_row, _detect_indent, _first_cell_indent,
    _table_has_comma_note_column, _table_has_note_header,
    parse_header_columns, select_by_header_columns, drop_mismatched_granularity_columns,
    HeaderColumn,
)

# ★R116(2026-09-14, 사용자 원문대조로 확정) — 형지I&C 20160516001490·드림시큐리티
# 20160511001294: Q1 보고서인데 IS 표 전체가 "3개월" 칸만 채우고 "누적" 칸은 통째로
# 공란이다("당기순이익" 행만 예외적으로 둘 다 채워 두 값이 동일함을 필자 스스로 증명).
# 1분기는 정의상 3개월=누적이라 원문 자체의 기재누락으로 판단되지만, 이 등식이 Q1
# 에서만 성립하고(H1/Q3 는 다름) 실측도 이 두 필링에서만 확인됐으므로 R3/R85 원칙(누적
# 공란 → 3개월로 대체 안 함)을 전사 정책으로 뒤집지 않고 이 예외목록으로만 좁힌다.
# 상세 근거는 `parser/xml/table_extractor.py::select_by_header_columns` R116 docstring.
_Q1_CUM_BLANK_USE_3M_RCEPTS = frozenset({
    "20160516001490",  # 형지I&C 2016 Q1
    "20160511001294",  # 드림시큐리티 2016 Q1
    "20170512001930",  # 조광페인트 2017 Q1(2026-09-14 후속 실측, 동일 패턴)
    "20190527000008",  # 자이글 2019 Q1(2026-09-14 후속 실측, 동일 패턴)
    "20180515002398",  # 평화산업 2018 Q1(2026-09-15 후속 실측, IS_separate 이상치
                        # 재검증 중 발견 — 별도 손익계산서만 3개월 채우고 누적은
                        # 공란, 당기순이익 행만 예외로 둘 다 채워 등식 확인)
    "20210517001891",  # APS 2021 Q1(2026-09-16 후속 실측, 최종 전체 재적재 후
                        # IS_separate 이상치 재검증 중 발견 — 형지I&C/평화산업과
                        # 완전히 같은 패턴: 당기순이익 행만 3개월=누적 두 값 다 채워
                        # 등식을 필자 스스로 증명, 나머지 전 행은 누적 공란)
    "20150514004898",  # 형지I&C 2015 Q1(2026-09-16 후속 실측 — 위 20160516001490과
                        # 다른 rcept·다른 연도, 같은 회사가 다른 분기에도 같은 패턴을
                        # 반복. 6열 헤더(당기 3개월/누적, 전기 3개월/누적, 전전기 FY,
                        # 전전전기 FY) — 당기·전기 둘 다 "누적" 열이 공란)
})

# ★R120(2026-09-14, 사용자 확정 — "예외목록으로만 좁힐") — 웹케시 20180814001946,
# 우리기술투자 20200813000621: H1 보고서 IS 표가 같은 라벨을 구분 텍스트 없이 물리적
# 으로 다른 2열에 반복하는데 두 열 다 실제 값이고 서로 다르다(3개월≠누적). DART
# 관행상 무표지 2열은 [3개월,누적] 순서 — Q1 당기순이익 + 이 표 1번째 열 = 이 표
# 2번째 열임을 산수로 직접 검증(사용자 확인). 일반 규칙화 대신 예외목록으로만 좁힌다
# (R6 정책 유지). 상세 근거는 `table_extractor.py::select_by_header_columns` R120.
_HEADERLESS_MERGE_LAST_IS_CUMULATIVE_RCEPTS = frozenset({
    "20180814001946",  # 웹케시 2018 H1
    "20200813000621",  # 우리기술투자 2020 H1
    "20150817000794",  # 삼성생명 2015 H1(2026-09-15 후속 실측, IS_consolidated 이상치
                        # 재검증 중 발견 — 연결 포괄손익계산서가 "제N(당)반기"/
                        # "제N(전)반기" 무표지 COLSPAN=2 병합군 2개 + 단일 FY열 2개인
                        # 6열 헤더. 당반기 병합군 뒷열(14,198,956)이 다른 요약재무정보
                        # 표의 같은 기간 값과 정확히 일치함을 대조 확인)
    # ★2026-09-16(같은 날 후속, 5번 임계값 재검토 스캔 — 사용자 지시 "지금 원인
    # 조사+수정") 3건 추가 — 전부 "요약재무정보" 서식(공식 재무제표 섹션이 빈
    # placeholder)의 IS 표가 "3개월"/"누적" 서브헤더 행을 아예 누락한 채 COLSPAN=2
    # 무표지 병합군만 남긴 경우. R120과 동일 메커니즘(같은 문서 안 다른 basis의
    # 같은 표가 서브헤더를 정상 보유 — 물리열 순서가 항상 [3개월,누적]임을 재확인),
    # 서로 다른 실측 근거로 개별 확정:
    "20191129000890",  # 바이오플러스 2019 Q3(IS_consolidated) — 별도 표는 "3개월"/
                        # "누적" 서브헤더 정상 보유, 연결 표만 서브헤더 행 자체가
                        # 없음(원문 결함). 매출액 등 물리열 값이 별도 표와 동일 값
                        # (12,050,665,141)을 가진 열이 뒤쪽(position1) — DART
                        # 관행([3개월,누적]) 그대로.
    "20201116001931",  # 우리기술투자 2020 Q3(IS_consolidated) — header_cols 는
                        # 성공하나(THEAD 아닌 TBODY 헤더행이라 R88 grid가 subtype
                        # 텍스트 "3개월"/"누 적"를 못 읽음) subtype=None 상태로
                        # 판정불가 분기에 진입. 별도 표는 정상 처리되던 것과 비교해
                        # 값 크기(영업수익 3개월 16,495,257,853 < 누적
                        # 18,344,549,484)가 [3개월,누적] 순서와 일치함을 확인.
    "20210210000442",  # 메이슨캐피탈 2021 Q3(IS_separate) — 위 2건과 반대로
                        # **별도** 표만 서브헤더가 없고 연결 표는 정상 보유(같은
                        # 문서 안에서 basis에 따라 어느 쪽이 결함인지 다를 수 있음을
                        # 보여주는 사례). 영업수익 3개월 1,201,859,418 < 누적
                        # 4,499,489,903 로 [3개월,누적] 순서 일치 확인.
})

# ★R118(2026-09-14, 사용자 원문대조로 확정 — "별도는 정상인데 연결이 원문 오타") —
# 제주은행 20160516002967 CF 연결 표 헤더가 "제57기 1분기"를 물리적으로 다른 두 열에
# **완전히 동일한 텍스트**로 중복 기재했다(구분 텍스트 전혀 없어 일반 규칙으로 판별
# 불가). 회계항등식(기초=전기말) 역산으로 확인: 두 번째 열(position1)은 실제로는
# "제56기 1분기"(전기, 2015 Q1)인데 원문 필자가 라벨을 잘못 복사했다 — 첫 열의
# 기초현금이 3번째 열("제56기" 연간표)의 기말현금과 일치하고, 두 번째 열의 기초/기말
# 현금은 "제56기"/"제55기" 연간표의 기초·기말과 정확히 이어진다(사용자 확인).
# 텍스트만으로는 절대 구분 불가능해 일반 규칙으로 확장하지 않고, 이 rcept 의 이
# statement×basis 조합 하나에만 한정한 예외 교정으로 처리한다.
_R118_DUPLICATE_PERIOD_LABEL_FIX: dict[tuple[str, str, str], dict[int, int]] = {
    # (rcept_no, statement, basis) -> {position(라벨열 제외 0-based): 교정된 period_rank}
    ("20160516002967", "CF", "consolidated"): {1: 1},  # 제주은행 2016 Q1
    # 제주은행 2022FY CF 연결(사용자 확인, "제주은행 보고서 단순 오타야") — 헤더가
    # "제62기"(당기,정상) / "제62기"(전기, 원문에 제61기라고 썼어야 함) / "제61기"
    # (전전기, 원문에 제60기라고 썼어야 함) 순으로 전부 한 기수씩 밀려 중복·오기재
    # 됐다. 회계항등식(기초=전기말) 역산 확인: position2/3(2번째 "제62기" 그룹)의
    # 기초현금(302,547)이 position4/5(3번째 그룹, "제61기")의 기말현금과 정확히
    # 일치 → 2번째 그룹은 전기(rank1), 3번째 그룹은 전전기(rank2)로 교정.
    ("20230314001271", "CF", "consolidated"): {2: 1, 3: 1, 4: 2, 5: 2},
    # 이노시뮬레이션 2019FY IS 별도(사용자 확인, "단순 오타로 보여") — 헤더가
    # "제19기(2018.01.01~2018.12.31)"를 완전히 동일하게 2번 반복하는데, 같은 필링의
    # BS 별도는 정상(제20기/제19기/제18기, 중복 없음) — IS 만 position0 이 "제20기"
    # 라고 썼어야 할 걸 "제19기"로 잘못 복사했다. position1(원 rank0)→전기(rank1),
    # position2(원 rank1)→전전기(rank2)로 한 칸씩 밀어 교정.
    ("20200330004128", "IS", "separate"): {1: 1, 2: 2},
    # DSC인베스트먼트 2023 Q1 IS 별도(4개 이상치 카테고리 재검증 중 발견, 2026-09-15) —
    # 헤더가 "제11(당)기 1분기"를 COLSPAN=2(3개월/누적) 그룹째로 완전히 동일하게 2번
    # 반복한다. 실측 값 대조로 확정: 두 그룹의 값이 서로 다르다(예: 영업수익
    # 6,806,498,698 vs 8,016,968,098) — 원문이 두 번째 그룹 제목을 "제10(전)기
    # 1분기"라고 썼어야 할 걸 복붙 실수로 "제11(당)기 1분기"라고 잘못 적었다.
    # position2/3(2번째 그룹, 3개월/누적)을 전기(rank1)로 교정.
    ("20230515002273", "IS", "separate"): {2: 1, 3: 1},
    # 이랜시스 2018FY CF 별도(4개 이상치 카테고리 재검증 중 발견, 2026-09-15) — 헤더가
    # "제1(당)기"를 완전히 동일하게 2번 반복(설립 첫해 신설법인). 회계항등식으로 확정:
    # 2번째 열의 기말현금(322,115,040)이 1번째 열의 기초현금과 정확히 일치 → 2번째
    # 열은 실제로 전기(설립일~2017.12.31, rank1)인데 원문이 "제1(당)기"라고 잘못
    # 복사했다. position2(주석열 제외 2번째 실데이터열)를 전기(rank1)로 교정.
    ("20190401000391", "CF", "separate"): {2: 1},
    # 신영증권 2022FY CF 별도(CF_separate 이상치 재검증 중 발견, 2026-09-15) — 헤더가
    # "제68기"(당기, 정상)/"제67기"(전기)/"제66기"(전전기) 순이어야 할 걸 "제67기"를
    # 2번 반복해 첫 그룹(당기)까지 전기와 같은 텍스트로 오기재했다. 원래는 rank0(4개
    # 물리열 병합)·rank1(2개 물리열)로 잘못 묶여, rank0 안에서 "실값 2개"(당기+전기가
    # 뒤섞임)로 R6 판정불가 → col0 대부분 유실. position0/1은 그대로 rank0(당기),
    # position2/3(2번째 "제67기" 그룹=진짜 전기)을 rank1로, position4/5("제66기"=
    # 전전기)를 rank2로 분리 교정.
    ("20220615000399", "CF", "separate"): {2: 1, 3: 1, 4: 2, 5: 2},
}


def _apply_duplicate_period_label_fix(header_cols, rcept_no, statement, basis):
    """R118 — 위 예외목록에 있는 (rcept, statement, basis)에서만 특정 position 의
    period_rank 를 교정한다. 목록에 없으면 무변경(회귀 없음)."""
    fix = _R118_DUPLICATE_PERIOD_LABEL_FIX.get((rcept_no, statement, basis))
    if not fix or header_cols is None:
        return header_cols
    return [
        hc if hc.position not in fix else HeaderColumn(
            position=hc.position, period_key=hc.period_key,
            period_rank=fix[hc.position], subtype=hc.subtype, is_note=hc.is_note,
        )
        for hc in header_cols
    ]


from parser.common.amount_normalizer import detect_unit_declaration, parse_amount, normalize_account_name

from parser.xml.section_detector import (
    assign_tables_to_dart_sections, assign_note_tables_with_titles,
    SEC_CONSOL_NOTE, SEC_SEP_NOTE, table_direct_rows,
)
from fin2.extract.text import (
    _SECTION_META, _detect_fin_type, _detect_body_statement_tables,
    _interim_cumulative_cols, _adecimal_from_unit, _synth_acontext,
    declared_unit, declaration_text, inherited_declaration_text, _table_has_data_rows,
    document_default_unit, nearest_section_default_unit,
)
from fin2.extract.units import ColumnUnits, FX_ONLY, SRC_FX
from fin2.extract.legacy_pre2015 import (
    detect_pre2015_body_statement_tables, detect_squished_bs_total_assets,
)
from fin2.extract.report_lines_inline_xbrl_overlay import (
    overlay_dividends_paid_sign,
    overlay_tax_expense_value,
)

# report_fiscal_year 가 이 값 이하면 pre-2015 K-GAAP 라우팅을 먼저 시도한다(설계문서
# `docs/plans/pre2015_layer2_backfill_phase2_design_2026-08-10.md` §2-1·§3-3 잔여항목③
# "2009~2010 전환기 라우팅 순서"의 구현 결정). 2011+ 는 손대지 않는다 — Phase2 실측
# (`pre2015_boundary_walk_prototype_probe_2026-08-10.md`)이 **2011~2014 는 기존 2015+
# 주경로가 이미 100% 성공**(TITLE 소멸로 우연히 형제 back-scan 이 맞아떨어짐)한다고 확정했고,
# 새 경로는 1999~2010 표본에서만 검증됐다(회귀 방지 원칙, 설계문서 §4).
_PRE2015_ROUTING_MAX_FY = 2010

# ★R121(2026-09-14, 사용자 확인 — "더블유게임즈 해당 기간 3,4기는 연결대상이 아니야")
# 더블유게임즈 20160520000534(2015FY): 문서의 "2. 연결재무제표" 섹션에 물리적으로 표가
# 있어(유진로봇류 "완전공백 섹션"과 다름) 정상 추출 경로를 그대로 타지만, 그 표들이
# 담은 값은 이 필링 자신의 당기(제4기)·전기(제3기) 것이 아니라 **제2기(2013) 시점의
# 옛 자본변동표/EPS 수치**뿐이다(SCE 전 col_index 가 "2013.01.01"/"2013.12.31" 날짜
# 라벨, IS 는 EPS 2줄만) — 지주사 전환 이전 시절 데이터가 남아있는 것으로, 사용자가
# 원문 확인 후 "3,4기는 연결대상 아니다"로 확정. 이런 표는 "빈 섹션"이 아니라서
# `_detect_body_statement_tables`가 정상적으로 찾아버리고, 값 자체도 억지로 재계산할
# 근거가 없어(제2기 수치를 당기/전기로 재배정할 방법이 없음) 아예 배제한다.
# 연결(_C) 섹션 코드를 통째로 스킵 — 별도(_S)는 무영향.
_MANUAL_NO_CONSOLIDATED_FS_RCEPTS = frozenset({
    "20160520000534",  # 더블유게임즈 2015FY [기재정정]사업보고서 — 제3·4기 연결비대상(사용자 확인)
    # 위와 같은 회사·같은 기간의 원본(정정 전, is_final=False) — 4개 이상치 카테고리
    # 재검증 중 발견(원본도 report_lines 에 적재돼 IS_consolidated=2건으로 걸림).
    # 같은 이슈(제4기 당기 연결 열이 원문 자체에서 전부 공란)라 동일 처리.
    "20160329000657",  # 더블유게임즈 2015FY 사업보고서(원본)
})

# ★R132(2026-09-16, 사용자 확인 — "이 rcept만 단위 오버라이드 예외 추가") 넷마블
# 20180402005173(2017FY): 연결·별도 IS·CF 표 전부 "(단위: 백만원)"이라고 선언돼 있는데,
# 실제 셀 값은 이미 원(WON) 단위 그대로다(자기모순 단위선언 — 원문 자체의 오기재,
# 표시통화·소수점 문제 아님). 예: 연결 영업수익 "2,424,755,040,569"는 그대로 2.42조원
# (넷마블 2017 실제 공시 매출과 일치) — 만약 정말 백만원 단위였다면 2.42×10¹⁸원이라는
# 불가능한 값이 된다. `_AMOUNT_SANE_MAX`(1경원 상한, R3)가 ×1,000,000 을 적용한 결과를
# 정상적으로 거부해 매출액/영업이익/당기순이익 등 핵심 행 대부분이 통째로 결측 처리됐다
# (실측: IS_separate 19행 중 12행, CF_separate 유사 붕괴). 이 자기모순은 문서 전체(BS
# 포함 4개 표×연결/별도)에 걸쳐 있어 표별이 아니라 rcept 단위로 배수를 1(원)로 강제한다.
# 일반화하지 않는 이유 — 이런 "선언 배수가 실제 자릿수와 안 맞음"은 단위 declaration
# 파싱 성공/실패와 무관한 **필자의 오기재**라 다른 필링에 이 정도로 큰(10⁶배) 자기모순이
# 항상 존재한다고 가정할 근거가 없다(원문대조로 확인된 필링에만 좁힌다, R6 유지).
_MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS: dict[str, int] = {
    "20180402005173": 1,  # 넷마블 2017FY — "(단위: 백만원)" 선언이 자기모순, 실제는 원(WON)
    # ★2026-09-16(같은 날 후속, BS 전수스캔 — 사용자 지시 "1,3,5번 이어서") 4건 추가.
    # 넷마블과 동일 유형(재무상태표가 "(단위 : 백만원)"이라고 선언했는데 실제 셀 값이
    # 이미 원(WON) 단위) — 각각 문서 내 다른 단위(천원/백만원)로 같은 계정을 중복 공시한
    # 별도 표(부채비율 주석, 배당 관련 요약재무정보 등)와 원문 대조해 확정.
    "20191114000246": 1,  # 아즈텍WB 2019Q3 — 자산총계 원문 114,055,541,787(부채비율
                          # 주석의 "천원" 표시 20,117,419천원=20,117,419,000원과 일치)
    "20210817001851": 1,  # HL D&I 2021H1 — 장기매출채권 원문 5,178,755,690(부채비율
                          # 주석의 "백만원" 표시 5,179백만원과 일치)
    "20170814002311": 1,  # 동성케미컬 2017H1 — 유동자산 원문 363,304,597,206(반기 시점
                          # 회사 규모상 3,633억원이 타당, 백만원 그대로면 363경원 불가능값)
    "20241114002786": 1,  # 소노스퀘어 2024Q3 — 유동자산 원문 61,190,747,942(소형사
                          # 규모상 612억원이 타당, 백만원 그대로면 61경원 불가능값)
}

def _merge_missing_codes(primary: dict, fallback_fn) -> dict:
    """`primary` 가 못 채운 섹션코드만 `fallback_fn()` 결과로 보충. 덮어쓰지 않는다.

    본문 탐지기 전용이 아니다 — 딕셔너리 {섹션코드: [(표, 단위, ...)]} in/out 계약만
    지키면 어떤 탐지기 쌍이든 재사용 가능(설계문서 `docs/plans/era_routing_fallback_
    and_fiscal_year_correction_parsing_design_2026-09-12.md` §2 — 언젠가 주석에도
    시대별 탐지기가 생기면 같은 헬퍼를 그대로 얹을 수 있다). 호출측이 "언제
    fallback_fn 을 부를지"(항상/primary 가 비었을 때만)를 정한다 — 이 헬퍼 자체는
    "채우는 방법"만 담당(단일 책임).
    """
    groups = dict(primary)
    for code, tables in fallback_fn().items():
        groups.setdefault(code, tables)
    return groups


# ★2026-08-10(Phase3 구현, canary 실측으로 발견) — 문서 전체 단위 "신규경로 빈 결과 시에만
# 폴백"은 전환기(2009~2010)에서 손해다: 신규경로가 IS/CF 는 잡지만 BS 는 못 잡는 문서에서
# "그룹이 비지 않았다"는 이유로 기존 2015+ 경로가 그 문서에서 BS 를 잡을 기회(설계문서 §1-1
# 실측: 2010년 BS 30%·IS/CF 90%, 둘 다 부분적으로 맞는 구간)를 통째로 버린다. 대신 **섹션
# 코드(BS_C/IS_S 등) 단위로 병합**한다 — 신규경로가 채운 키는 그대로 두고, 신규경로가 못 채운
# 키만 기존경로 결과로 보충한다. 같은 표가 두 경로에서 서로 다른 키로 갈릴 위험은 있으나(실측
# 안 됨, 극히 드묾) 완전 누락보다 낫고, 같은 키에 두 번 담기는 중복은 애초에 발생하지 않는다
# (덮어쓰지 않고 setdefault 로만 채움).
def _detect_pre2015_body_statement_tables_merged(root, fin_type: str) -> dict[str, list[tuple]]:
    return _merge_missing_codes(
        detect_pre2015_body_statement_tables(root, fin_type, include_sce=True),
        lambda: _detect_body_statement_tables(root, fin_type, include_sce=True))

# 로컬 선언이 전혀 없을 때 문서 전체 기본 단위를 썼다는 provenance(2026-08-05).
# `fin2/extract/text.py::document_default_unit` 참고.
# ★ report_lines.unit_source 는 varchar(14) — "document_default"(16자)는 INSERT 를 터뜨린다.
SRC_DOC_DEFAULT = "doc_default"
# R67(2026-09-03) — 로컬 선언은 없지만 같은 SECTION-2(재무제표/연결재무제표) 안의 다른
# 표에서 단위를 찾은 경우. `fin2/extract/text.py::nearest_section_default_unit` 참고.
# "section_default"(15자)는 varchar(14)를 터뜨리므로 축약.
SRC_SECTION_DEFAULT = "section_def"
# (A-3, 2026-09-05) 통짜-셀 레거시 BS 표에서 `detect_squished_bs_total_assets()`가
# 복구한 total_assets 단일값 provenance. 단위 자체가 declared/section_def/doc_default
# 어느 경로로 잡혔는지와 무관하게(§design doc §3-4) **이 값이 통짜-셀 복구 경로 산물임을
# 우선 기록** — PDF복구(unit_source='pdf', 항목1)와 같은 관례. 정확히 14자.
SRC_SQUISHED_TOTAL = "squished_total"


def _pick_fallback_unit(table, section_unit_cache: dict, doc_default_unit: tuple):
    """R67(2026-09-03) — 로컬 선언도 FX 도 아닐 때, 같은 SECTION-2 폴백
    (`nearest_section_default_unit`)과 문서 전체 폴백(`doc_default_unit`) 중 **배수가
    더 작은 쪽**을 고른다.

    ★왜 "같은 섹션이 항상 우선"이 아니라 "더 작은 배수"인가(00171867 2006Q3 실측 반례로
    발견) — 같은 "4. 재무제표" SECTION-2 **안에서도** 인쇄 관행이 섞일 수 있다: 이 필링은
    본문 대차대조표/손익계산서가 "(단위 :천원)"으로 정상 선언돼 있는데, 그 뒤쪽 같은 섹션에
    로컬선언이 공란인 별도 "3개월/누적" 상세표가 있고, 이 상세표는 이미 **압축 없는 원 단위
    숫자**("18,805,337,508")를 그대로 인쇄해놨다. 단순히 "같은 섹션 첫 선언"만 썼다면 이
    상세표에 ×1000(천원)이 잘못 적용돼 18.8억이 아니라 18.8조가 됐을 것 — 인접 분기값들
    (7~38억원대, 전부 `declared`)과 3~4자리수 어긋나는 명백한 회귀. 반면 `doc_default_unit`
    (이 필링은 "요약재무정보"에 선언이 없어 회계정책 주석의 "…원(KRW)…" 문구로 unit=1)이
    이미 정답을 갖고 있었다.

    실측 전수(dry-run, 976개 필링·48,500건 교정) 결과 **97.98%가 "더 작은 배수가 정답"**
    방향(과다배수 오적용이 압도적 다수 실패모드)이라, 두 후보 중 작은 쪽을 taking 하는
    것이 가장 보수적이고 안전한 선택이다 — section_def 가 doc_default 보다 사실상 항상
    "더 국지적이라 더 신뢰할 만하다"는 가정을 버리고, 대신 "덜 부풀리는 쪽"을 신뢰한다.
    두 후보 배수가 같으면 section_def 를 우선(더 국지적인 게 여전히 근거로는 낫다).
    반환: (unit, decl_raw, unit_source) — 후보가 하나도 없으면 (None, None, None).
    """
    section_unit, section_decl = nearest_section_default_unit(table, section_unit_cache)
    candidates = [(u, d, src) for u, d, src in (
        (section_unit, section_decl, SRC_SECTION_DEFAULT),
        (doc_default_unit[0], doc_default_unit[1], SRC_DOC_DEFAULT),
    ) if u is not None]
    if not candidates:
        return None, None, None
    return min(candidates, key=lambda c: c[0])

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
    # ── 표 단위 메타(F3, 2026-07-31) — **DB 의 행에는 안 들어간다.**
    #   `store_report_tables` 가 (rcept_no, statement, basis, table_seq) 로 묶어
    #   `report_tables` 한 행으로 적는다. 메모리에서만 행에 붙여 다니는 이유는 추출기 반환
    #   시그니처를 바꾸지 않기 위해서다(호출부가 여럿이다).
    unit_decl_raw: str | None = None
    unit_kind: str | None = None
    unit_inherited: bool = False
    # 표시통화(ISO 코드). **원화 표는 None** — 외화로 표시된 표만 채운다. 이것도 표 단위
    # 사실이라 report_tables.currency 로 간다(행마다 반복하지 않는다).
    # 행 수준에서 "이 값이 원화가 아니다"는 `unit_source='fx_declared'` 로 알 수 있다.
    currency: str | None = None

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
    unit_source="declared", currency=None, unit_decl_raw=None,
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
        # 미선언 표는 호출측에서 이미 스킵됐다. 'fx_declared' 는 **표시통화 금액 그대로**라는
        # 뜻이다(원화 환산 아님) — 통화 코드는 report_tables.currency.
        unit_source=unit_source,
        source_ref=f"{section_code}/{row.account_name[:80]}"[:180],
        context_raw=_synth_acontext(basis, period_kind, col_idx, ctx_fy, statement),
        row_order=row.row_order,
        depth=row.raw_indent,                 # 원문 들여쓰기(전각공백 수) — 구조 그대로
        node_role=node_role,
        table_seq=table_seq,
        table_title=table_title,
        # 본문은 열별 판정을 하지 않는다(열=기간). 표가 적은 선언 원문만 표 메타로 남긴다(F3).
        unit_decl_raw=unit_decl_raw,
        unit_kind=None,
        currency=currency,
    )


# ★EPS(주당손익) 오판 가드(2026-08-15) — 라벨의 "주당" 부분문자열만으로 EPS 여부를
# 판정하면 "지배주주당기순이익(손실)"/"비지배주주당기순이익"(=지배+주주+당기순이익,
# 우연히 "주당" 부분문자열이 생김) 같은 NI귀속(총액, 원 단위) 라벨이 EPS(원/주)로
# 오판된다 — "보통주주당이익"(=보통주+주당이익, 진짜 EPS) 과 문자열 레벨에서 원리적으로
# 구분 불가(라벨 텍스트 규칙으로는 못 가른다, 실측 확인). 대신 파싱된 금액의 **크기**로
# 가른다 — 진짜 EPS(원/주)는 실측 최댓값이 5,890,065원(2015년 이후·깨끗한 라벨·알려진
# 오판 회사 제외, 약 75,000행 모집단, `docs/plans/gate_b_controlling_ni_groupbc_
# kbimetal_eps_label_trap_fix_design_2026-08-15.md` §3-A)이라 1,000만원이면 1.7배
# 여유. NI귀속 오판값은 억~수백억원대라 자릿수가 수십~수천 배 차이 나 안전하게 갈린다.
# 금액이 상한을 넘으면 EPS 취급을 포기하고 본류(_emit_section_lines)로 흘려보낸다(결측
# 판단 없이 기존 정상 라벨매칭에 위임 — 새 "선택" 로직 아님, 게이트만 좁힘).
_EPS_MAX_PLAUSIBLE_WON = 10_000_000


def _looks_like_eps_amounts(amounts) -> bool:
    """파싱된 금액들이 EPS(원/주)치고 비현실적으로 크면 False. 값이 전부 없으면(None)
    판단 불가 → 보수적으로 True(기존 동작 유지, 결측>오염 — 짐작 말고 기존 경로 유지)."""
    present = [a for a in amounts if a is not None]
    if not present:
        return True
    return all(abs(a) <= _EPS_MAX_PLAUSIBLE_WON for a in present)


# ★K-GAAP 구서식(00269852류) "헤드라인 순이익 + 괄호 안 EPS 노트" 통짜라벨
# 목록(2026-08-15, R28). 이 행들은 '주당' 부분문자열 때문에 EPS 경로로
# 들어오지만 실제로는 그 표의 헤드라인 당기순이익 행이다 — EPS 로 emit 하지
# 않고 본류(_emit_section_lines)가 표 단위를 적용해 일반 행으로 전사하게
# 넘긴다(R27 과 같은 계열, 단 값크기로는 못 걸러 curated 키를 쓴다).
#
# 키는 rcept_no 단독이 아니라 (rcept_no, statement, basis, table_seq,
# label_raw) 5-튜플이다 — rcept_no 단독 키를 시도했다가 **같은 표 안에
# 별개의 정상 EPS 행이 같이 있는 필링 2건을 실측으로 발견**(설계문서 §4-B
# 6번), 그 행까지 잘못 건드릴 뻔했다.
#
# ★블랭킷 규칙 아님 — 이 집합 밖의 EPS 행(정상 168,579건 포함, 같은 표
# 안의 형제 정상 EPS 행 포함)은 기존 동작 그대로다(설계문서 §2 실측: 일반규칙은 위험).
# 생성: scripts/purge_eps_curated_false_positives_2026-08-15.py (설계문서 §8 Phase 1)
# 데이터: fin2/extract/data/eps_kgaap_headline_not_eps_keys_2026-08-15.json
# 설계문서: docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md
_EPS_KGAAP_KEYS_PATH = (
    Path(__file__).resolve().parent / "data" / "eps_kgaap_headline_not_eps_keys_2026-08-15.json"
)


def _load_kgaap_keys() -> frozenset[tuple[str, str, str, int, str]]:
    # 데이터파일 유실을 침묵 무효화로 넘기면 백필이 조용히 아무것도 안 하게
    # 된다 — 실패 시 예외를 그대로 올린다(설계문서 §8 Phase 2-2).
    with open(_EPS_KGAAP_KEYS_PATH, encoding="utf-8") as f:
        raw_keys = json.load(f)
    return frozenset(
        (rcept_no, statement, basis, int(table_seq), label)
        for rcept_no, statement, basis, table_seq, label in raw_keys
    )


_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS: frozenset[tuple[str, str, str, int, str]] = _load_kgaap_keys()


def _emit_eps_lines(table, *, emit, basis, statement, corp_code, rcept_no,
                    report_fiscal_year, report_fiscal_period,
                    table_seq=None, table_title=None,
                    cum_map: dict[int, int] | None = None) -> None:
    """주당손익(EPS) 행을 **per-row 단위**로 전사한다(IS 표 전용).

    ★ 왜 별도 처리인가: 주당이익 라벨은 '계속영업기본주당이익 (단위 : 원)' 처럼 **행 자체에 단위**를
    달고 있어 (a) `_is_header_cell` 이 '단위:' 로 헤더 오인해 드롭하고, (b) 표 단위(천원/백만원)를
    적용하면 원(₩)/주 값이 배로 오염된다. 그래서 표 본류에서 '주당' 행은 건너뛰고(_emit_section_lines),
    여기서 **라벨 인라인 단위(없으면 원=1)**로 직접 파싱해 담는다. context_fiscal_year 는 당기/전기로
    매핑(재무제표 컬럼과 동일)하되, 값은 원(₩)/주 그대로.

    ★R85(2026-09-09) — `cum_map`: 호출측(`_emit_section_lines`)이 같은 표에서 이미 계산해둔
    `_interim_cumulative_cols()` 결과. H1/Q3 IS 표는 헤더가 [당기3개월,당기누적,전기3개월,전기누적]
    2단 구조인데, 이 함수는 그동안 그 구조를 모르고 **파싱 순서 앞 3개**를 그냥 [당기,전기,전전기]로
    라벨링했다 — 결과적으로 "당기"라는 이름으로 진짜 누적(반기·3분기 EPS)이 아니라 3개월(당분기 단독)
    값이 저장됐다(원문대조로 확정: 삼성전자 20250814003156 별도 기본주당이익 — 원문 411(3개월)/1,360
    (누적) 중 411이 "당기"로 저장, 반면 같은 필링 반기순이익은 cum_map 경로를 타 9,139,217(누적)로
    정확히 저장됨 — 두 라인의 컬럼선택 로직이 서로 달라 생긴 불일치). `cum_map`이 있으면(2단 헤더
    검출) 표 본류와 동일하게 '누적' 토큰이 붙은 컬럼만 위치 기준으로 골라 담는다 — FY/2단 미검출
    표는 기존 동작(앞 3개 위치순) 그대로."""
    for tr in table_direct_rows(table):
        cells = _get_cells(tr)
        if not cells or "주당" not in cells[0]:
            continue
        label = cells[0].strip()
        # ★R28 — K-GAAP 구서식 헤드라인 순이익 행(EPS 아님) → 본류에 위임.
        if (rcept_no, statement, basis, table_seq, label) in _EPS_KGAAP_HEADLINE_NOT_EPS_KEYS:
            continue
        # ★행 인라인 단위가 **외화**일 수 있다 — '계속영업기본주당이익(손실) (단위 : USD)'
        #   (실측 아남전자). 원화 배수가 없다고 1(원)로 가정하면 USD/주 값이 원/주 로 둔갑한다.
        #   표 경로와 같은 규약으로 fx 를 표시한다(2026-08-05).
        eps_cu = ColumnUnits.from_declaration(label)
        if eps_cu.kind == FX_ONLY:
            unit, eps_source, eps_currency = eps_cu.fx_mult, SRC_FX, eps_cu.currency
        else:
            unit, eps_source, eps_currency = (
                detect_unit_declaration(label) or 1, "declared", None)
        _, amt_cells = _split_label_amounts(cells)
        # 위치보존(라벨/주석컬럼 제외, 그 외 자리는 그대로) — cum_map 은 이 위치 기준.
        amounts_by_pos = [parse_amount(c, unit) for c in amt_cells]
        present = [a for a in amounts_by_pos if a is not None]
        if not _looks_like_eps_amounts(present):
            # NI귀속류 오판 행 — EPS 로 emit 하지 않고 본류가 처리하도록 남겨둔다(아래
            # _emit_section_lines 의 대응 가드와 짝, 2026-08-15).
            continue
        if cum_map is not None:
            # 2단[3개월|누적] 헤더 검출 표 — '누적' 토큰이 붙은 컬럼만 위치로 선택.
            pairs = [(off, amounts_by_pos[pos]) for pos, off in cum_map.items()
                     if pos < len(amounts_by_pos) and amounts_by_pos[pos] is not None]
        else:
            # FY 또는 2단 헤더 미검출 — 기존 동작(파싱 순서 앞 3개 = 당기/전기/전전기).
            pairs = list(enumerate(present[:3]))
        for col_idx, amount in pairs:
            ctx_fy = report_fiscal_year - col_idx
            emit(ReportLineRow(
                corp_code=corp_code, rcept_no=rcept_no,
                report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
                statement=statement, basis=basis, section_path="주당손익",
                label_raw=label, col_index=col_idx, context_fiscal_year=ctx_fy,
                period_kind="duration", is_cumulative=(report_fiscal_period != "FY"),
                value_won=amount, adecimal=_adecimal_from_unit(unit), unit_source=eps_source,
                currency=eps_currency,
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
    doc_default_unit: tuple = (None, None),
    section_unit_cache: dict | None = None,
) -> None:
    """한 섹션(BS_C 등)의 데이터 TABLE 들을 컬럼기반으로 읽어 report_lines 행 방출.

    text.py `_emit_section` 과 동일한 표 선택/컬럼 판독 로직(interim 누적컬럼 선택 포함) —
    canonical 매핑·귀속행 라우팅만 제거. 상세 판단 근거는 text.py 쪽 주석 참고(그대로 재사용).

    `doc_default_unit` — `text.py::document_default_unit()` 이 문서 전체에서 미리 찾아둔
    (multiplier, 근거원문). 그 표에 로컬 선언이 전혀 없을 때 최후 수단으로 쓴다.
    `section_unit_cache` — R67(2026-09-03): `doc_default_unit` 보다 **먼저** 시도하는
    `text.py::nearest_section_default_unit()` 용 문서-수명 캐시(dict, 호출측이 파일 하나당
    한 번 만들어 여러 섹션 호출에 공유). None 이면 이 호출 안에서만 쓰는 빈 dict로 대체.
    """
    if section_unit_cache is None:
        section_unit_cache = {}
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
        # R86(2026-09-09) — else 분기(선두 None 절삭)의 유일한 근거표 신호. extract_rows()가
        # 내부적으로 계산하는 것과 동일한 판정을 여기서도 한 번 더 구해둔다(RowData 는 이
        # 값을 외부로 안 돌려준다 — 아래 else 분기 참고).
        table_trs = table_direct_rows(table)
        table_has_note_column = (
            _table_has_comma_note_column([_get_cells(tr) for tr in table_trs])
            or _table_has_note_header(table_trs))
        unit = unit_of[id(table)]
        unit_source, currency, decl_raw = "declared", None, None
        # R132 — 예외목록에 있는 rcept 만, 선언된 배수가 있어도 강제로 덮어쓴다(자기모순
        # 단위선언 — 위 dict docstring 근거). 선언이 아예 없는(None) 일반 경로는 그대로
        # 아래 폴백을 탄다 — 이 override 는 "선언은 파싱됐지만 틀렸다"는 경우 전용.
        if rcept_no in _MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS:
            unit = _MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS[rcept_no]
            # unit_source 컬럼은 String(14) — "manual_unit"(11자)로 짧게 표기.
            unit_source, decl_raw = "manual_unit", "R132 자기모순 단위선언 수기교정"
        if unit is None:
            # ★ 원화 배수가 없다고 곧바로 버리지 않는다 — **표시통화가 외화**일 수 있다
            #   (실측 아남전자 008700: 2019+ 본문 8표 전부 '(단위 : USD)'). 그 경우 환산하지
            #   않고 표시통화 금액 그대로 담고, unit_source='fx_declared' 로 사실을 남긴다
            #   (사용자 결정 2026-08-05). 외화가 **원화와 섞인** 선언은 FX_ONLY 가 아니므로
            #   여기 오지 않는다 — 그런 표는 종전대로 열 판정을 따른다.
            decl = declaration_text(table) or inherited_declaration_text(table)
            cu = ColumnUnits.from_declaration(decl)
            if cu.kind == FX_ONLY:
                unit = cu.fx_mult
                unit_source, currency, decl_raw = SRC_FX, cu.currency, cu.raw_decl
            else:
                # R67(2026-09-03) — 같은 SECTION-2 폴백과 문서 전체 폴백("요약재무정보")
                # 둘 다 시도해, 배수가 더 작은(=덜 부풀리는) 쪽을 쓴다. "같은 섹션이라 더
                # 안전하다"는 가정이 항상 성립하지 않는다 — `_pick_fallback_unit` 참고.
                unit, decl_raw, unit_source = _pick_fallback_unit(
                    table, section_unit_cache, doc_default_unit)
                if unit is None:
                    logger.debug(f"[report_lines] 단위 미선언 → 스킵(보류): {rcept_no} {section_code}")
                    continue

        # R88(2026-09-09) — THEAD COLSPAN/ROWSPAN 그리드로 표 구조를 **먼저** 읽는다
        # (사용자 제안, 설계: docs/plans/report_lines_header_grid_column_map_design_
        # 2026-09-09.md). 성공하면 아래 cum_map/multicol/else 3갈래 추측(R85~R87이
        # 각자 다른 안전장치로 패치해온 바로 그 추측)을 전부 우회한다 — 실패(THEAD
        # 없음, 모르는 헤더 모양)하면 그 3갈래로 그대로 폴백(무변경, 회귀 위험 0).
        # SCE 는 열이 기간이 아니라 자본 구성요소 축이라 대상 아님(기존과 동일 제외).
        # R125 — 명세/소계 COLSPAN=2 중복 서브타입 열의 행별 유일값 해석은
        # report_fiscal_year>=2015 필링에만 연다(SB성보류 pre-2015 K-GAAP은 이 규칙이
        # 안 맞아 조용히 틀린 값을 냈던 실측 회귀 때문 — table_extractor.py
        # ::_columns_from_grid R125 docstring 참고).
        header_cols = parse_header_columns(
            table, allow_duplicate_subtype=(report_fiscal_year >= 2015),
        ) if statement in ("BS", "IS", "CF") else None
        # R118 — 예외목록(rcept×statement×basis)에 있는 필링만 중복 라벨 열의 rank를
        # 교정한다(원문 자체의 헤더 오타, 위 함수 docstring 근거). R115 필터보다 먼저
        # 적용해야 그 필터가 교정된 rank 기준으로 안전하게 동작한다.
        header_cols = _apply_duplicate_period_label_fix(header_cols, rcept_no, statement, basis)
        # R115 — 분기/반기 보고서 표에 붙은 순수 연도서수(분기/반기 접미사 없는 "제N기")
        # 참고열은 이 보고서의 period_kind 와 다른 기간단위라 col_index 축에서 배제한다
        # (위 함수 docstring 근거). FY 보고서는 조기반환이라 무영향.
        header_cols = drop_mismatched_granularity_columns(header_cols, report_fiscal_period)

        if header_cols is not None:
            n_cols = max(c.position for c in header_cols) + 1
            table_rows = list(extract_rows(table, multiplier=unit, num_cols=n_cols,
                                            direct_only=True, skip_junk=False,
                                            keep_all_amount_cells=True))
        else:
            # 보험/증권 기간당 다열 포맷 감지(2단 누적표는 별도 경로라 제외).
            n_periods, multicol = (3, False) if cum_map is not None else _detect_period_layout(table)
            n_cols = max(cum_map) + 1 if cum_map else (8 if multicol else 3)

            # 표 전체 행을 먼저 materialize → 들여쓰기 stack 으로 section_path 부여(행 순서 필요).
            # preserve_col_positions: cum_map 표만 6-column 압축(선행 None pop-loop)을 끈다 —
            # 그 압축이 "당기3개월 disclosure 없음"(진짜 결측)과 "주석 컬럼이 비어서 생긴 선행
            # None"(_split_label_amounts 가 이미 위에서 제거 — 2026-08-24)을 구분 못 하고 뭉뚱그려
            # 당겨서 cum_map(절대위치 인덱싱)을 오정렬시켰다(Gate B 버그①, 코리안리/00104573/
            # 00172291 원문대조로 확정). 다른 두 소비 경로(multicol/else)는 이미 자체 재압축이라
            # 이 플래그를 안 보므로 결과가 그대로다(§1 실측).
            table_rows = list(extract_rows(table, multiplier=unit, num_cols=n_cols,
                                            direct_only=True, skip_junk=False,
                                            preserve_col_positions=(cum_map is not None)))
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
                            table_seq=table_seq, table_title=table_title,
                            cum_map=cum_map)

        for row in table_rows:
            if not row.account_name:
                continue
            if "주당" in row.account_name and _looks_like_eps_amounts(row.amounts):
                continue  # 진짜 EPS(원/주)만 본류에서 제외 — NI귀속 오판 가드(위 참고)
            section_path = section_paths.get(id(row))
            if header_cols is not None:
                # R88 — 헤더 그리드로 확정된 위치→회계기간 맵으로 직접 선택(설계문서 §3-4).
                # R113 — raw_amounts 를 같이 넘겨 순수 대시("-") 칸을 0으로 채택(원문
                # 정책상 "-"=0, 결측 아님 — 위 select_by_header_columns 주석 참고).
                # R116 — 예외목록에 있는 Q1 필링만 누적 공란 시 3개월 값을 대체 채택.
                # R120 — 예외목록에 있는 필링만 무표지 2열 병합군에서 마지막 열(누적) 채택.
                pairs = list(select_by_header_columns(
                    header_cols, row.amounts, raw_amounts=row.raw_amounts,
                    allow_three_month_as_cumulative=(
                        report_fiscal_period == "Q1"
                        and rcept_no in _Q1_CUM_BLANK_USE_3M_RCEPTS),
                    prefer_last_of_two_as_cumulative=(
                        rcept_no in _HEADERLESS_MERGE_LAST_IS_CUMULATIVE_RCEPTS),
                ).items())
            elif cum_map is not None:
                pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
                         if pos < len(row.amounts) and row.amounts[pos] is not None]
                if not pairs:
                    # ★2026-09-06(R74 후속, 트랙①) — 이 폴백은 "총계/귀속 요약행은 누적값
                    # 2개만 가져 누적컬럼(1,3) 위치가 비고 값이 0·2 등에 실린다"는 **진짜
                    # 결측** 전제로 설계됐다(위 §5.4류 사례). 그런데 cum_map 목표 칸의
                    # `raw_amounts`가 실제 숫자 텍스트인데 `amounts`만 None이면(=
                    # `_AMOUNT_SANE_MAX` 값-거부, R74와 같은 원인) 그 전제가 깨진다 — 실측
                    # 확정(00378363 3S FY2023 Q3 연결IS "매출액"): 당기누적(position1)·
                    # 전기누적(position3) 둘 다 자기모순 단위(×10⁶)로 거부됐는데, 이 폴백이
                    # "값이 있는 아무 칸"(전기 **3개월**, position2)을 주워 당기누적으로
                    # 둔갑시켰다 — 컬럼 밀림이 아니라 **완전히 다른 성격의 값**(3개월 vs
                    # 누적)이 뒤바뀌는, R74의 "else" 분기보다 위험한 변종. cum_map 목표 칸에
                    # 거부의 증거(진짜 숫자 텍스트)가 있으면 이 폴백 자체를 쓰지 않는다 —
                    # 결측으로 남기는 편이 엉뚱한 값보다 안전하다(R3 원칙).
                    raws = row.raw_amounts
                    targets_rejected = any(
                        pos < len(raws) and raws[pos].strip() not in _LABEL_REGION_PLACEHOLDERS
                        for pos in cum_map)
                    if not targets_rejected:
                        present = [a for a in row.amounts if a is not None]
                        pairs = list(enumerate(present))
            elif multicol:
                # 기간당 다열: 비어있지 않은 금액을 압축 → [당기, 전기, 전전기] 로 매핑.
                present = [a for a in row.amounts if a is not None]
                pairs = list(enumerate(present[:n_periods]))
            else:
                # ★2026-08-29(§5.4, classB 유형1) — text.py::_emit_section 의 동형 분기와
                # 반드시 같이 고쳐야 하는 쌍둥이 로직. `acontext_missing[i]=True`(TE+ACODE
                # 있고 ACONTEXT 없음 — DART 원문이 명시한 "이 기간 미공시")인 칸 앞에서는
                # 절삭을 멈춰 진짜 결측으로 남긴다(원문이 실제로 그 기간을 안 비운 경우를
                # 전기/전전기 값이 당기로 오귀속되는 것을 막는다). 신호 없는 칸(TD 등)은 기존
                # 동작 그대로. 근거: docs/plans/gateb_trade_payables_classB_stale_column_
                # investigation_2026-08-29.md §5~6.
                # ★2026-09-06(R73 후속, 트랙①) — 두 번째 정지 신호 추가: `raw_amounts[i]`가
                # 진짜 숫자 텍스트인데 `amounts[i]`가 None이면, 그 칸은 "원문이 비웠다"가
                # 아니라 `parse_amount()`의 `_AMOUNT_SANE_MAX`(R3, 1경원 상한) 가드가 **값을
                # 신뢰 못 해 거부**한 것이다(원문 단위선언이 실제 자릿수와 안 맞는 자기모순
                # 필링 — declared "백만원"인데 본문이 이미 원 단위인 경우 등). 그런 칸을 진짜
                # 공백과 똑같이 절삭하면, 거부된 값 뒤의 진짜 전기/전전기 값이 당기 열로
                # 밀려 들어간다(실측 확정: 00204226 소프트센 FY2022 연결BS `이익잉여금(결손금)`
                # — 당기 17,293,933,213원이 ×10⁶ 스케일에서 1경원 상한에 걸려 거부되고, 전기
                # 6,570,137,526원이 그 자리로 밀려 당기 값으로 둔갑). 이 칸에서도 절삭을
                # 멈춰 결측으로 남긴다 — "오염보다 결측을 택한다"는 R3 자신의 원칙을 이
                # 압축 단계에도 그대로 잇는다. 근거:
                # docs/plans/report_lines_sanemax_reject_compaction_shift_design_2026-09-06.md
                # ★R86(2026-09-09) — 세 번째 정지 신호 추가: `table_has_note_column`(이 표에
                # 주석참조 컬럼이 있다는 구조적 증거, R19/R65). classB(§5.1) 조사가 이미 밝힌
                # 대로, 이 절삭 루프의 **유일한 정당한 존재 이유**는 "라벨 바로 다음 주석참조
                # 칸이 빈 값으로 amount_cells 에 섞여 들어와 생기는 phantom 선두 None"(한화손해
                # 보험류)이었고, 그 근본원인은 R19(2026-08-24)가 `_split_label_amounts_ex()`
                # 단계에서 이미 제거했다 — 주석 컬럼이 있는 표에서만 여전히 필요할 수 있는
                # 잔여 케이스에 대비해 그 표들(`table_has_note_column=True`)에서는 기존 동작을
                # 그대로 둔다. 주석 컬럼이 **없는** 순수 기간열 표(`table_has_note_column=
                # False`)에서 선두가 진짜 공백류(`raws[lead]`가 placeholder)라면, 그건 phantom
                # 이 아니라 **원문이 실제로 그 기간을 비운 것**(K-GAAP→IFRS9 전환 등으로 특정
                # 계정이 최근 기간엔 없고 오래된 기간에만 존재하는 경우 등) — 절삭하면 전기/
                # 전전기 값이 당기 열로 둔갑한다(실측 확정: 삼성전자 20200330003851 2019FY 별도
                # 현금흐름표 "장기매도가능금융자산의 처분/취득" 등 — 원문 [공란,공란,전전기값]
                # 인데 절삭 후 전전기값이 당기로 저장됨). 이 표들에서도 절삭을 멈춰 결측으로
                # 남긴다. 근거: docs/PARSING_RULES.md R86,
                # docs/plans/gateb_trade_payables_classB_stale_column_investigation_2026-08-29.md §5.1.
                amts = row.amounts
                flags = row.acontext_missing
                raws = row.raw_amounts
                lead = 0
                while (lead < len(amts) and amts[lead] is None
                       and not (lead < len(flags) and flags[lead])
                       and (lead >= len(raws) or raws[lead].strip() in _LABEL_REGION_PLACEHOLDERS)
                       and table_has_note_column):
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
                    unit_source=unit_source, currency=currency, unit_decl_raw=decl_raw,
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


# 라벨 영역 판정(LV′, 아래 `_build_col_labels`)에서 "금액이 아니어도 금액열 취급"할 placeholder.
# 원문에서 값이 없는 금액 열은 대시/공란으로 표기되는데, 그 열이 표본 행 전체에서 우연히
# 전부 이 표기이면 "금액 후보"로도 안 잡혀 라벨 영역이 과대해진다(T1.1 에서 반증된 첫 후보의
# 실패 원인) — 그래서 파싱 성공 **또는** 이 집합에 속하면 금액열로 카운트한다.
_LABEL_REGION_PLACEHOLDERS = frozenset(["", "-", "‐", "―", "–", "—", "ㅡ"])


def _grid_header_split(table):
    """`expand_table_grid`로 표를 펼치고 헤더 구간(n_header)·라벨 영역 폭(offset=LV′)·
    헤더 그리드 폭(width)을 계산한다 — **한 곳에서만** 한다.

    ★왜 공용 함수인가(T1.3 반드시 지킬 전제) — 헤더 라벨 사전(`_build_col_labels`)과 본문
    행 산출(`_emit_note_lines`)이 서로 **다른 offset 계산**을 쓰면 `col_label.get(col_idx)`
    조회가 어긋난다. 두 곳이 각자 다시 계산하게 두면 알고리즘이 미묘하게 갈릴 위험이 있어
    (예: whitespace 정규화를 한쪽만 빼먹는 식) 계산 자체를 여기 하나로 묶는다.

    Returns:
        `(grid_rows, n_header, offset, width)` — 판정 불가(헤더/본문 경계 못 찾음·표가
        비어 있음)면 `(grid_rows_or_[], None, None, None)`. `grid_rows`는 판정 실패해도
        (호출자가 원하면) 그대로 돌려준다 — 표 자체는 파싱됐을 수 있어서다.
    """
    grid_rows = expand_table_grid(table)
    if not grid_rows:
        return grid_rows, None, None, None

    # 헤더 구간 = 첫 데이터 행 전까지. 판정 텍스트는 이 행의 **물리적** 셀만 본다(상속 칸은
    # 원문에 없는 칸이라 이 판정에 넣지 않는다) — whitespace 접기는 구 버전과 동일하게
    # 유지한다(멀티라인 헤더 셀 대응, `_NUMBER_PATTERN`이 앵커드 패턴이라 접지 않으면
    # 내부개행이 있는 셀에서 판정이 갈린다).
    n_header = 0
    for row in grid_rows:
        physical_texts = [" ".join(c.text.split()) for c in row if not c.inherited]
        if len(physical_texts) > 1 and any(_NUMBER_PATTERN.search(t) for t in physical_texts[1:]):
            break
        n_header += 1
    if (n_header == 0 or n_header >= len(grid_rows)) and len(grid_rows) > 1:
        # ★2026-08-08(T3.6 회귀 수정): 판정 실패의 두 형태를 전부 헤더=1행으로 강제 폴백한다.
        #   ①n_header==0 — 첫 행 자체가 "숫자처럼" 보여 즉시 break(예: 헤더 셀이 연도 "2020"
        #     하나뿐 — _NUMBER_PATTERN 은 콤마 없는 4자리 숫자도 맞다고 본다).
        #   ②n_header>=len(grid_rows) — 끝까지 한 번도 안 깨져 전부 헤더처럼 보임(예: 데이터
        #     행이 죄다 음수인데 "-1,339"처럼 **선행 마이너스**라 `_NUMBER_PATTERN`이 숫자로
        #     못 잡음 — 괄호식 "(1,339)"만 인식). 실측(잔여, `census_note_header_none_
        #     fallback.py` 수정후 재실행) 775건/15,070,642표.
        #   DART 표는 관례상 데이터 앞에 헤더 행이 최소 하나 있다(`_table_has_data_rows`
        #   게이트를 통과했다는 것 자체가 진짜 데이터 표란 뜻이지, 첫 행부터 데이터란 뜻이
        #   아니다) — 두 경우 다 첫 행을 데이터로 오인하는 것보다 헤더로 강제 취급하는 쪽이
        #   훨씬 안전하다. 이 보정이 없으면 호출부가 offset=0 폴백으로 빠져 라벨 열 폭을
        #   반영 못 해 값 열이 통째로 밀린다(수정 전 실측 348,099 값 셀/1,629 필링). 표에
        #   물리 행이 1개뿐이면(강제해도 본문이 안 남음) 아래 가드가 그대로 막는다.
        n_header = 1
    if n_header >= len(grid_rows):
        # ★2026-08-08(T3.6 2차 보정): 물리 행이 1개뿐이라 위 강제(n_header=1)조차 못 하는
        #   경우 — 헤더 자체가 원래 없는 표다(성호전자 `20240814002619` "순금융비용" 단일행
        #   표, 현대위아 `20240320001675` "납입자본금" 단일행 표 등 실측). 그래도 offset 은
        #   이 행 자신을 본문으로 보고 LV′ 로 구할 수 있다 — 헤더가 없으니 col_label 은
        #   못 채우지만(진짜 없으니 정상), 값 열 위치는 안전하게 나온다. `None` 폴백(offset
        #   강제 0)보다 훨씬 안전하다 — `_grid_body_rows`가 어차피 physical[0]을 라벨로
        #   빼므로, offset 을 안 구하면 그 라벨 폭만큼 값 열이 밀린다.
        n_header = 0
    if not grid_rows[n_header:]:
        return grid_rows, None, None, None

    header_rows = grid_rows[:n_header]
    body_rows = grid_rows[n_header:]

    # width — 표 전체 그리드 폭. 위 보정으로 header_rows 가 비어 있을 수 있으니(헤더 없는
    # 표) header_rows 대신 grid_rows 전체에서 구한다 — 정상 표는 헤더도 본문과 같은 폭을
    # 채우므로(HTML 표 관례) 결과가 달라지지 않는다.
    width = 0
    for row in grid_rows:
        for c in row:
            width = max(width, c.grid_col + c.colspan)

    # 라벨 영역 폭(L=offset) — LV′: 본문(물리 셀만, 각 행의 첫 물리 셀=그 행의 라벨은 제외)에서
    # 한 번이라도 금액 또는 placeholder 였던 grid_col 중 가장 왼쪽 것.
    amount_cols: set[int] = set()
    for row in body_rows:
        physical = [c for c in row if not c.inherited]
        for c in physical[1:]:                        # physical[0] = 이 행 자신의 라벨 셀
            if parse_amount(c.text, 1) is not None or c.text.strip() in _LABEL_REGION_PLACEHOLDERS:
                amount_cols.add(c.grid_col)

    offset = 0
    while offset < width and offset not in amount_cols:
        offset += 1
    # 본문에 금액 후보가 전혀 없으면(amount_cols 공집합) offset==width 로 끝나 호출자가
    # 빈 결과를 낸다 — 구 버전의 "n_amounts==0 → {}" 조기 반환과 동치.

    return grid_rows, n_header, offset, width


def _build_col_labels(table) -> dict[int, str]:
    """헤더 TR 들을 **COLSPAN/ROWSPAN 그리드로 복원**해 {금액열 인덱스: 열 라벨} 반환.

    ★ 왜 필요한가: 자본변동표는 열이 기간이 아니라 자본 구성요소(자본금/자본잉여금/이익잉여금/
    비지배지분/…)다. col_index 만으로는 어느 열인지 알 수 없어 데이터가 무의미해진다.
    XBRL ACONTEXT(ComponentsOfEquityAxis)에도 같은 정보가 있지만 실측 커버리지가 **21.5%**
    뿐이라(Track A 만 마킹) 헤더 복원이 주 경로다.

    헤더는 다단이고 ROWSPAN 이 섞인다 — 단순 COLSPAN 확장만 하면 단마다 길이가 어긋난다:
        TR0: [라벨칸 ROWSPAN=3][자본 COLSPAN=7]
        TR1: [지배기업…지분 COLSPAN=5][비지배지분 ROWSPAN=2][자본 합계 ROWSPAN=2]
        TR2: [자본금][자본잉여금][기타자본항목][이익잉여금][지배지분 합계]
    → HTML 표와 동일한 방식으로 (row, col) 그리드를 채운 뒤 열별로 단을 위→아래 연결한다
    (`table_extractor.expand_table_grid`가 헤더·본문을 **관통하는 하나의 그리드**로 이 계산을
    한다 — 여기서는 그 결과를 재사용할 뿐, 그리드 워크 자체를 다시 하지 않는다).

    헤더 행 = **첫 데이터 행 직전까지**. 데이터 행은 '첫 셀 외에 숫자 셀이 있는 행'으로 본다.
    반환 키는 **금액열 인덱스** — RowData.amounts 인덱스와 맞춘다.

    ★ 라벨 영역 폭(L, 아래에서는 `offset`) 판정 — R11/T1.1(2026-08-07)로 재정의됐다.
    **구 버전(2026-08-07 이전)**은 "데이터 행의 **물리적** 금액 셀 수 최댓값"으로 냈다
    (`all_cells` 인자로 주석/SCE 가 셈법을 조금씩 달리했다 — 인자는 이제 폐지). ROWSPAN
    이어짐·COLSPAN 병합 라벨 행이 있으면 물리적 셀 수 자체가 행마다 원문 열 개수보다
    줄어들어 이 셈법이 깨진다 — 부록 A T16·T17, R11(`docs/PARSING_RULES.md`)이 문서화한
    결함이 정확히 이것이다.

    실측(유진증권 `20220316000791` table 4) — 헤더 [구분(COLSPAN=2)｜제69(당)기｜제68(전)기],
    ROWSPAN 이어짐 행이 섞여 있어 물리 셀 수 기반 계산은 `offset=1`(오답)을 냈지만, 그리드
    폭 4 중 라벨 영역은 실제로 **2**칸이다. 물리 셀 수는 "표 전체에서 가장 넓었던 행이 몇
    칸이었는지"일 뿐 "라벨이 몇 칸인지"를 말해주지 않는다 — 최댓값을 취해도 소용없다.

    **새 규칙(`LV′`, T1.1 확정)** — **헤더 구조가 아니라 본문 값의 유무로 판정한다**: 그리드
    열 중 "본문 전체를 통틀어 파싱 가능한 금액 또는 `-`/공란류 placeholder 가 **한 번도**
    나온 적 없는" 선행 열까지가 라벨 영역이다. 헤더 구조 신호(세로 관통 셀·최하단 행 등)
    만으로는 판정할 수 없다 — 실측 표의 41.8%가 헤더 행 1개뿐이라 그런 구조 신호 자체가
    없다(`docs/plans/note_span_fix_plan_2026-08-07.md` T1.1, 156→800필링·123,475표
    재검증). `LV′`는 결함 없는 표에서 구 `offset`과 95.3% 일치하고, 잔여 4.7%도 저장 결과
    (값·라벨)에 영향이 없음이 구조적으로 보장된다(위 문서 §T1.1 안전성 논증 — `LV′`는
    정의상 진짜 금액 열의 grid_col보다 항상 작거나 같다, 음수 인덱스 발생 불가).

    ★`all_cells` 인자는 폐지됐다(2026-08-07) — 구 셈법에서만 의미가 있었다. `LV′`는 본문
    전체를 다시 훑어 판정하므로 호출자가 물리 셀을 어떻게 골라내든(주석·SCE) 관계없이
    **하나의 규칙**으로 통일된다(핸드오프 §T1.4).
    """
    grid_rows, n_header, offset, width = _grid_header_split(table)
    if n_header is None:
        return {}
    return _label_dict_from_header(grid_rows[:n_header], n_header, offset, width)


def _label_dict_from_header(header_rows, n_header: int, offset: int, width: int) -> dict[int, str]:
    """`_grid_header_split`이 이미 나눈 헤더 구간·offset·width로 {금액열 인덱스: 열 라벨}을
    만든다 — `_build_col_labels`(테이블 전체를 받는 공개 진입점)와 `_emit_note_lines`
    (본문 행 산출과 **같은 한 번의 `_grid_header_split` 호출**을 공유해야 하는 호출자, T1.3)
    양쪽에서 쓴다. 순수 함수 — 여기서 그리드를 다시 만들지 않는다.
    """
    # 물리 셀만 자기 (rowspan×colspan) 영역에 텍스트를 새긴다(상속 칸은 origin 텍스트를 이미
    # 복사해 두므로 다시 채울 필요 없음 — 중복 방지를 위해 물리 셀만).
    grid: dict[tuple[int, int], str] = {}
    for row in header_rows:
        for c in row:
            if c.inherited:
                continue
            txt = " ".join(c.text.split())
            if not txt:
                continue
            for dr in range(c.rowspan):
                for dc in range(c.colspan):
                    grid[(c.grid_row + dr, c.grid_col + dc)] = txt

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


def _grid_body_rows(
    table, grid_rows, n_header: int, offset: int, *,
    multiplier: int = 1, allow_date_label: bool = False, keep_header_rows: bool = True,
) -> list[RowData]:
    """`expand_table_grid`의 본문(헤더 이후) 그리드 행을 `RowData`로 변환한다(R11) —
    주석(`_emit_note_lines`, T2.4)·SCE(`_emit_sce_lines`, T2.5) **공용**. T1.4가 "L 규칙은
    LV′ 하나로 통일(노트·SCE 공용 그리드 확장 유틸, 배선은 각자)"이라 정한 대로, 그리드
    워크는 여기 하나로 묶고 호출부별 차이(단위 배수·헤더행 처리)만 인자로 받는다.

    ★ 이게 결함을 실제로 고치는 지점이다. 옛 경로(`extract_rows`)는 각 행의 **물리적** 셀
    위치를 그대로 `amounts` 인덱스로 썼다 — ROWSPAN 이어짐 행은 물리적 셀 수가 줄어들어 그
    인덱스가 진짜 열보다 왼쪽으로 밀린다(R11 본문, 텔코웨어 실측 — 미수수익 행의
    442,190/470,100 이 물리 위치 0·1 로 저장되던 것). 여기서는 각 값 셀의 **진짜
    grid_col**(`expand_table_grid`가 이미 계산해 둠)에서 `offset`을 빼 `col_idx`를 정한다 —
    `offset`은 `_build_col_labels`/`_label_dict_from_header`가 쓰는 것과 **반드시 같은
    값**이어야 하므로(T1.3), 호출자가 `_grid_header_split`을 **한 번만** 호출해 여기와
    공유한다(이 함수는 다시 계산 안 함).

    T1.2 결정(상속 안 함) — `label_raw`는 **이 행 자신의 첫 물리 셀** 그대로 쓴다. 옛
    코드도 실은 이미 그랬다(`_get_cells(tr)[0]`은 물리 셀 기준이라 ROWSPAN 을 상속받지
    않는다) — 바뀌는 건 값 열 산출뿐, 라벨은 무변경이다.

    각 값 후보 셀이 `offset` 보다 왼쪽 grid_col 이면(=라벨 영역 안의 텍스트 열, 예: 유진증권
    표의 '거래처'류) 건너뛴다 — `LV′`의 안전성 논증(T1.1)대로 이런 셀은 애초에 금액으로
    파싱되지 않으므로 버려도 정보 손실이 없다(음수 col_idx 로 배열을 역방향 인덱싱하는 버그도
    막는다). 이게 옛 `preserve_col_positions=True`(SCE)가 하려던 것을 **더 정확히** 한다 —
    필터링된 위치가 아니라 진짜 그리드 열을 그대로 쓰므로, 이 인자 자체가 필요 없어졌다.

    Args:
        table: 원본 TABLE 요소 — `raw_indent`(원문 선행공백, section_path/depth 신호)는
            `expand_table_grid`가 버리므로(텍스트만 `.strip()` 해 담는 최소가공 계약, T2.2)
            원 TR을 다시 대조해 구한다.
        grid_rows: 호출자가 `_grid_header_split(table)`로 이미 만든 전체 그리드(헤더+본문).
        n_header: 헤더 구간 행 수 — `grid_rows[n_header:]`가 본문.
        offset: `_build_col_labels`와 공유하는 라벨 영역 폭(`LV′`).
        multiplier: 값 셀을 파싱할 때 바로 곱할 배수. 주석은 옛 `extract_rows(multiplier=1,
            ...)`과 동일하게 **×1**로 원문만 확보하고 호출부가 열별 배수로 다시 파싱한다
            (`units.py`, 표마다 열 단위가 다를 수 있어서). SCE는 표 전체가 단일 배수라
            (옛 `extract_rows(multiplier=unit, ...)`과 동일하게) 여기서 바로 최종값을 낸다.
        allow_date_label: True 면 날짜 라벨을 헤더 판정에서 뺀다(`_header_rule_name`
            `allow_date_label`) — **SCE 전용**. 기초/기말 잔액 행의 라벨이 날짜라 이 규칙이
            켜져 있으면 그 앵커 행이 통째로 사라진다(옛 `date_labels_ok=True`와 동일).
        keep_header_rows: False 면 `header_hint` 가 붙는 행을 **버린다**(옛 SCE 기본,
            `extract_rows(keep_header_rows=False 기본)`). True(주석 기본, F2)면 버리지 않고
            hint 만 기록한다.
    """
    trs = table_direct_rows(table)          # expand_table_grid 내부와 같은 순서(순수 함수)
    body_rows = grid_rows[n_header:]
    body_trs = trs[n_header:]

    out: list[RowData] = []
    row_order = 0
    for tr, row in zip(body_trs, body_rows):
        physical = [c for c in row if not c.inherited]
        if not physical:
            continue                        # ROWSPAN 이 이 행 전체를 흡수(자기 물리 셀 없음)
        label = physical[0].text
        # ★순서는 옛 `extract_rows`와 동일해야 한다: header_hint 판정·드롭 → 제목행 가드 →
        #   label 공백 가드. 셋 다 "이 행을 아예 버릴지"를 정하는 게이트라 순서가 바뀌면
        #   드문 조합(예: 빈 라벨인데 헤더 패턴)에서 결과가 갈릴 수 있다.
        header_hint = _header_rule_name(label.strip(), allow_date_label=allow_date_label)
        if header_hint and not keep_header_rows:
            continue                        # 옛 SCE 기본 동작(keep_header_rows=False)
        if _is_fs_title_row([c.text for c in physical]):
            continue                        # 재무제표 이름만 있는 제목 행(기존과 동일 가드)
        if not label:
            continue

        value_cells = [c for c in physical[1:] if c.grid_col >= offset]
        max_idx = max((c.grid_col - offset for c in value_cells), default=-1)
        amounts: list[int | None] = [None] * (max_idx + 1)
        raw_amounts: list[str] = [""] * (max_idx + 1)
        for c in value_cells:
            idx = c.grid_col - offset
            amounts[idx] = parse_amount(c.text, multiplier)
            raw_amounts[idx] = c.text

        out.append(RowData(
            account_name=label.lstrip(),
            amounts=amounts,
            raw_amounts=raw_amounts,
            header_hint=header_hint,
            row_order=row_order,
            indent_level=_detect_indent(label),
            raw_indent=_first_cell_indent(tr),
        ))
        row_order += 1
    return out


def note_table_retained(table, minimum: int = 1) -> bool:
    """Whether a note table survives the F1/D4 loader gate (2026-07-31) — the *only* real
    criterion. There is no unit-declared requirement any more: a note table is kept whenever
    it has at least `minimum` direct data row(s) with a comma amount (`_table_has_data_rows`).
    Column-level unit determination (value_won vs value_raw-only) is separate — see
    `note_column_units`. Audit tools (`layer2_forward_cells.py`, `layer2_note_drop_audit.py`,
    `layer2_note_heading_fix_verify.py`) must call this instead of reimplementing the gate —
    that reimplementation (`declared_unit(tb) is None`) is exactly the "old contract" bug this
    function exists to prevent from recurring (docs/plans/verification_tools_4_refresh_2026-08-09.md).
    """
    return _table_has_data_rows(table, minimum=minimum)


def note_column_units(table, note_col_labels: dict) -> "ColumnUnits":
    """Per-column unit determination for a note table — the exact code path `_emit_note_lines`
    uses to decide, column by column, whether a cell gets `value_won` (multiplier resolved) or
    stays `value_raw`-only (multiplier is None). Factored out so audit tools can reproduce the
    real "emit" split instead of guessing at it (F1, 2026-07-31 — units.py)."""
    own_decl = declaration_text(table)
    inherited = None if own_decl else inherited_declaration_text(table)
    return ColumnUnits.from_declaration(own_decl or inherited, note_col_labels,
                                        inherited=bool(inherited))


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
            # ★게이트 완화(사용자 결정 D4, 2026-07-31): 콤마 금액 행 **1 개**면 전사한다.
            #   기본값 2 는 '16. 결손금'(2셀)·'담보설정금액'(1셀)·'특수관계자 자금거래'(1셀)
            #   처럼 **작지만 진짜인 표**를 버렸다 — 전수 2,199,735 표 / 9,501,682 셀.
            #   표본 30건 원문 대조에서 표제표·stub 은 0 건이었다(`probe_data_row_gate.py`).
            #   1 이어도 콤마 금액 행을 최소 하나는 요구하므로 숫자 없는 표제표는 통과 못 한다.
            #   ⚠ 기본값은 2 로 **그대로 둔다** — 본문 제목표/데이터표 연결 판정 등 다른
            #     호출부의 동작을 바꾸지 않기 위해 주석 경로에서만 인자로 낮춘다.
            if not note_table_retained(table):
                continue
            # section_path = 관장 번호 주석 제목('27. 현금흐름표')이 우선 — 주석 정체성 로케이터.
            # 없으면 표 직전 설명 텍스트로 폴백. table_title 엔 지역 설명을 따로 남긴다.
            local_heading = _note_heading(table)
            heading = note_title or local_heading
            # ★열 헤더 복원(2026-07-29). 주석 열은 기간일 수도(당기/전기) 자산분류일 수도
            #   (토지/건물/기계) 있는데, 지금까지 col_label 을 안 채워 계층3 가 col_index 만으로
            #   추측해야 했다(유형자산 증감표를 기간축으로 오인하는 원인). SCE 에서 쓰던
            #   _build_col_labels 를 그대로 재사용한다 — 새 파싱 로직이 아니다.
            #   ★2026-08-07(R11/T2.3+T2.4): `_grid_header_split`을 **여기서 한 번만** 호출해
            #   헤더 라벨 사전(`_label_dict_from_header`)과 본문 행 산출(`_grid_body_rows`)이
            #   **반드시 같은 offset(LV′)**을 쓰도록 보장한다(T1.3 전제 — 따로 계산하면
            #   좌표계가 어긋날 위험). 물리 위치 기반이던 `extract_rows(keep_all_amount_cells=
            #   True)`는 이제 안 쓴다 — 본문 값도 진짜 grid_col로 산출한다(R11 결함 수정 본체).
            grid_rows, n_header, offset, width = _grid_header_split(table)
            if n_header is None:
                # 헤더 구간을 못 찾았다(데이터가 첫 행부터 시작 — 실전에서 드묾, `_table_has_
                # data_rows` 게이트를 통과한 표는 항상 어딘가에 콤마금액 행이 있으므로
                # n_header>=len(rows) 는 발생 안 함). col_label 없이도 값은 잃지 않는다(R6) —
                # 옛 `_build_col_labels`도 이 경우 {} 를 냈지만 그때도 `extract_rows`는
                # 독립적으로 계속 값을 뽑았다(그 동작 보존). 표 전체를 본문으로, offset=0.
                note_col_labels: dict[int, str] = {}
                note_rows = _grid_body_rows(table, grid_rows, 0, 0, multiplier=1)
            else:
                note_col_labels = _label_dict_from_header(
                    grid_rows[:n_header], n_header, offset, width)
                note_rows = _grid_body_rows(table, grid_rows, n_header, offset, multiplier=1)
            # ★단위는 표 단위가 아니라 **열 단위**로 정한다(F1, 2026-07-31 — units.py).
            #   선언이 없어도 전사는 계속한다: value_won 은 비고 value_raw 에 원문이 남는다.
            #   표 자신의 선언이 없으면 **앞선 '선언 전용 표'** 에서만 상속한다(D1) —
            #   상속 조건은 `inherited_declaration_text` docstring 참고(그 외엔 아무것도 안 줍는다).
            cu = note_column_units(table, note_col_labels)
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
                        # 표 단위 메타(F3) — 행에는 안 들어가고 report_tables 로 모인다.
                        unit_decl_raw=cu.raw_decl,
                        unit_kind=cu.kind,
                        unit_inherited=cu.inherited,
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
    doc_default_unit: tuple = (None, None),
    section_unit_cache: dict | None = None,
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

    ★ `allow_date_label=True` 필수: 기본 경로는 날짜 라벨 행을 기간 헤더로 보고 드롭하는데,
      SCE 에서는 그게 기초/기말 잔액 행이다(실측 2,519행/250보고서 유실).

    ★2026-08-08(R11/T2.5) — 본문 행 산출을 `_grid_body_rows`(주석과 공용, T2.4)로 교체.
      SCE 도 note 와 **같은 구조적 결함**을 갖고 있었다(T1.4 실측, 400필링·741표·69,033값
      중 15.68%의 행에서 값이 밀림 — 비중이 note(11.48%)보다 오히려 크다). 옛 `preserve_
      col_positions=True`는 "필터링(비숫자 셀 제거)된 위치를 보존"하는 근사였는데, ROWSPAN
      이어짐 행은 애초에 그 필터링 전 물리 셀 수 자체가 원문 열 개수보다 줄어 근사가
      깨진다 — `_grid_body_rows`가 쓰는 **진짜 grid_col** 은 이 근사가 필요 없다(그래서
      `preserve_col_positions` 인자 자체를 없앴다). `multiplier=unit`(표 전체 단일 배수 —
      SCE 는 주석과 달리 열별 단위 판정을 안 한다)·`allow_date_label=True`·
      `keep_header_rows=False`(옛 SCE 기본 — 헤더 패턴 행은 버림, 주석과 다른 점)로 호출.
    """
    if section_unit_cache is None:
        section_unit_cache = {}
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
        fx_source, fx_currency, fx_decl = None, None, None
        if unit is None:
            # 본문 경로와 같은 규약 — 외화 표시 표는 버리지 않고 표시통화 그대로 담는다
            # (2026-08-05). 자본변동표도 같은 선언을 공유한다(아남전자 SCE_C/SCE_S).
            cu = ColumnUnits.from_declaration(
                declaration_text(table) or inherited_declaration_text(table))
            if cu.kind == FX_ONLY:
                unit, fx_source, fx_currency, fx_decl = (
                    cu.fx_mult, SRC_FX, cu.currency, cu.raw_decl)
            else:
                # R67(2026-09-03) — 위 _emit_section_lines 의 같은 분기와 동일한 근거
                # (`_pick_fallback_unit`: 배수가 더 작은 쪽을 신뢰).
                unit, fx_decl, fx_source = _pick_fallback_unit(
                    table, section_unit_cache, doc_default_unit)
                if unit is None:
                    logger.debug(f"[report_lines/SCE] 단위 미선언 → 스킵(보류): {rcept_no} {section_code}")
                    continue
        table_seq = doc_seq[id(table)]
        table_title = _note_heading(table)
        # ★2026-08-08(R11/T2.5): `_grid_header_split`을 **여기서 한 번만** 호출해 헤더 라벨
        #   사전(`_label_dict_from_header`)과 본문 행 산출(`_grid_body_rows`)이 반드시 같은
        #   offset(LV′)을 쓰도록 한다(T1.3 전제 — T2.3/T2.4와 동일 패턴, `_build_col_labels`
        #   를 그대로 호출해도 결과는 같지만 두 번 그리드를 만들지 않도록 여기서 공유한다).
        grid_rows, n_header, offset, width = _grid_header_split(table)
        if n_header is None:
            # 헤더 구간을 못 찾음(실전에서 드묾) — col_label 없이도 값은 잃지 않는다(R6).
            col_labels: dict[int, str] = {}
            rows = _grid_body_rows(table, grid_rows, 0, 0, multiplier=unit,
                                   allow_date_label=True, keep_header_rows=False)
        else:
            col_labels = _label_dict_from_header(grid_rows[:n_header], n_header, offset, width)
            rows = _grid_body_rows(table, grid_rows, n_header, offset, multiplier=unit,
                                   allow_date_label=True, keep_header_rows=False)
        adecimal = _adecimal_from_unit(unit)
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
                    unit_source=fx_source or "declared",
                    source_ref=f"{section_code}/{row.account_name[:80]}"[:180],
                    context_raw=f"sce:{basis}:c{col_idx}",
                    row_order=row.row_order,
                    depth=row.raw_indent,
                    node_role=node_roles.get(id(row)),
                    table_seq=table_seq,
                    table_title=table_title,
                    currency=fx_currency, unit_decl_raw=fx_decl,
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

    fin_type = _detect_fin_type(root, file_path=file_path)
    lines: list[ReportLineRow] = []

    # include_sce=True — 계층2 는 자본변동표도 전사한다(fact_v2 는 기본값 False 로 계속 배제).
    # pre-2015(≤2010) 라우팅 — 섹션 코드 단위 병합(위 헬퍼 docstring). 2015+ 소비 경로
    # (`_detect_body_statement_tables`)는 이 분기 밖에서 무변경으로 그대로 쓴다.
    squished_bs: dict[str, tuple[int, "object"]] = {}
    if report_fiscal_year <= _PRE2015_ROUTING_MAX_FY:
        groups = _detect_pre2015_body_statement_tables_merged(root, fin_type)
        # (A-3, 2026-09-05) 통짜-셀 BS 표 — 정상 경로(위 groups)가 못 채운 BS_S/BS_C 만
        # total_assets 단일값으로 보충 시도(완전히 추가적, 정상 표가 있으면 아예 안 씀).
        # 설계: docs/plans/category_c_a3_squished_cell_bs_total_assets_design_2026-09-05.md
        squished_bs = {
            code: v for code, v in detect_squished_bs_total_assets(root, fin_type).items()
            if code not in groups
        }
    else:
        groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
        if not groups:
            # ★신규(2026-09-12 설계 §2) — report_fiscal_year 오판정으로 실제론 pre-2015
            #   서식인 문서가 여기로 잘못 라우팅되면 신경로가 표를 하나도 못 찾는다(실측:
            #   진원생명과학 20220908000421 — 정정본이 원본 접수 16년 뒤라 fiscal_year가
            #   2022로 잘못 계산됨, `docs/plans/era_routing_fallback_and_fiscal_year_
            #   correction_parsing_design_2026-09-12.md` §1 로 근본 원인은 별도 수정).
            #   **완전히 빈 경우에만** 반대 방향(pre-2015 탐지기)으로 재시도한다 — pre-2015→
            #   2015+ 방향과 달리 이 방향은 아직 전수 실측이 없어 부분 병합(섹션코드 단위
            #   상시 setdefault)까지는 가지 않는다(보수적 시작, 위 설계문서 §2).
            groups = _merge_missing_codes(
                groups, lambda: detect_pre2015_body_statement_tables(
                    root, fin_type, include_sce=True))
            if groups:
                logger.warning(
                    f"[report_lines] {rcept_no}: fiscal_year={report_fiscal_year} 로 2015+ "
                    f"라우팅했으나 0행 — pre-2015 폴백으로 {len(groups)}개 섹션 복구. "
                    f"fiscal_year 메타데이터 오판정 의심, 확인 필요.")
        if rcept_no in _MANUAL_NO_CONSOLIDATED_FS_RCEPTS:
            # R121 — 연결(_C) 섹션 코드를 통째로 배제(위 상수 docstring 근거). 물리적
            # 표는 있지만 그 값이 이 필링 자신의 당기/전기 것이 아니라 옛 시절 데이터라
            # 재배정할 근거가 없다(사용자 확인, 짐작 금지).
            groups = {code: v for code, v in groups.items() if not code.endswith("_C")}
    # 문서 전체 기본 단위는 **로컬 선언이 없는 표가 실제로 있을 때만** 찾는다(비용 절감 —
    # 대다수 문서는 표마다 선언이 있어 이 스캔이 불필요하다). `_detect_body_statement_tables`
    # 가 이미 붙여준 표 단위 unit 이 하나라도 None 이면 후보. squished_bs 는 로컬 선언이
    # 없으면 폴백 없이 스킵하므로(위 §A-3 안전장치) 여기 후보에 안 넣는다.
    needs_doc_default = any(u is None for tws in groups.values() for _, u, _ in tws)
    doc_default_unit = document_default_unit(root) if needs_doc_default else (None, None)
    # R67(2026-09-03) — 파일(=문서) 하나 수명의 캐시. `nearest_section_default_unit()`이
    # SECTION-2(id) 당 한 번만 스캔하도록 여러 statement 그룹 호출에 공유한다.
    section_unit_cache: dict = {}
    for code, tables_with_unit in groups.items():
        emitter = _emit_sce_lines if code.startswith("SCE") else _emit_section_lines
        emitter(
            code, tables_with_unit, emit=lines.append,
            corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year,
            report_fiscal_period=report_fiscal_period,
            doc_default_unit=doc_default_unit,
            section_unit_cache=section_unit_cache,
        )

    for code, (raw_value, unit_hint_table) in squished_bs.items():
        # ★2026-09-05(실측 발견, 손오공 20050331001512·코데즈컴바인 20060814001461·
        # KTcs 20060515002002) — 이 표들의 로컬 단위선언이 "(단위 : )"처럼 원문 자체가
        # 비어있어 declared_unit 이 None 이 되고, section_def/doc_default 폴백이 이
        # 문서의 **다른 곳**(요약재무정보 등)에서 찾은 단위(예 백만원)를 잘못 물려받아
        # 값이 10³~10⁶배 뻥튀기됐다(실측 확정 — 인접기간 대비 이상값). 정상 표(§_pick_
        # fallback_unit)는 "같은 SECTION-2 안 다른 표"를 신뢰할 근거(적어도 국지성)가
        # 있지만, 이 통짜-셀 폴백은 검증 표본이 좁아 그 신뢰를 아직 못 준다 — **로컬
        # 선언이 없으면 폴백을 시도하지 않고 조용히 포기한다**(드라이런 실측: 656건 중
        # 7건만 로컬 선언이 없었음 — 손실은 작고, 이 위험군 전체를 원천 차단).
        unit = declared_unit(unit_hint_table)
        if unit is None:
            logger.debug(f"[report_lines] 통짜-셀 total_assets 로컬 단위 미선언 → "
                         f"폴백 없이 스킵(안전 우선): {rcept_no} {code}")
            continue
        basis, period_kind = _SECTION_META[code]
        lines.append(ReportLineRow(
            corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
            statement="BS", basis=basis,
            label_raw="자산총계", col_index=0, context_fiscal_year=report_fiscal_year,
            period_kind=period_kind, is_cumulative=False,
            value_won=raw_value * unit, adecimal=_adecimal_from_unit(unit),
            unit_source=SRC_SQUISHED_TOTAL, source_ref=None, context_raw=None,
            table_seq=0, node_role="F",
        ))

    if not groups and not squished_bs:
        logger.debug(f"[report_lines] 본문 섹션 없음 → 빈 결과(보류): {rcept_no} "
                     f"fy{report_fiscal_year} {report_fiscal_period}")

    if include_notes:
        _emit_note_lines(
            root, emit=lines.append, corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        )

    # 버그#2(dividends_paid 부호) 수정 — 원문에 이미 있는 인라인 XBRL(Track A) 사실로
    # CF 텍스트추출 부호를 보정. docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md.
    n_overlay = overlay_dividends_paid_sign(lines, file_path, report_fiscal_year)
    if n_overlay:
        logger.debug(f"[report_lines] inline XBRL overlay 적용: {n_overlay}건 ({rcept_no})")

    # 버그①(당기 3개월 미공시 시 전기 3개월 컬럼 오채택) 수정 — 같은 원리로 원문
    # 인라인 XBRL(Track A) 사실로 IS 텍스트추출 tax_expense 값을 보정.
    # docs/plans/d_category_col_misselect_ni_label_dup_design_2026-08-23.md §1.
    n_tax_overlay = overlay_tax_expense_value(lines, file_path, report_fiscal_year)
    if n_tax_overlay:
        logger.debug(f"[report_lines] tax_expense inline XBRL overlay 적용: "
                     f"{n_tax_overlay}건 ({rcept_no})")

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


def store_report_lines(session, rcept_no: str, lines: list[ReportLineRow], *,
                       overwrite_manual: bool = False) -> int:
    """rcept_no 단위 delete-then-insert(재추출 재현성). fact_v2 처럼 셀 단위 upsert 가 아님 —
    report_lines 는 값판단이 없어 충돌 개념 자체가 없고, 재추출은 그 보고서의 이전 tree 를
    통째로 교체하는 게 자연스럽다.

    ★본문(BS/IS/CF/SCE)만 적재한다. statement='note' 는 별도 테이블 note_lines 로
    (`store_note_lines`) — 주석 볼륨(본문의 ~4.7배)을 본문 조회에서 격리(2026-07-25).

    ★★당기(col_index=0)만 적재한다 — 사용자 결정 2026-07-30(`_PERIOD_AXIS_STATEMENTS`).
    상세는 `_is_loadable` 참고.

    ★수동입력 보호(2026-09-08, 사용자 지시): 이 함수는 rcept_no 전체를 지우므로, 사람이
    직접 원문을 읽고 타이핑한 `unit_source='manual'` 행(`fin2/extract/manual_report_lines.py`
    ::store_manual_report_lines — 그쪽은 반대로 (rcept,statement,basis) 스코프라 자동추출
    산출물을 지우려면 `overwrite=True` 를 요구한다)이 이 rcept에 하나라도 있으면 **기본적으로
    거부**한다. 없으면 이 안전장치가 자동 재추출(백필 스크립트·`recheck=True` 데일리 재검사
    등, 이 함수를 직접 부르는 15개+ 호출부 전부)이 사람이 검증한 값을 조용히 덮어쓸 수
    있었다 — 반대 방향(수동이 자동을 덮어쓸 때)만 막혀 있던 비대칭을 해소. 호출부는 대부분
    이미 한 건 실패를 로그+스킵으로 흡수하는 try/except라(예: note_lines_sync.py)
    `ValueError`가 파이프라인을 막지 않고 그 rcept만 안전하게 건너뛴다. 의도적으로
    덮어써야 하면(예: 수동입력 자체가 틀렸다고 재판정) `overwrite_manual=True`를 명시."""
    from sqlalchemy import delete, insert, select
    from collector.models import ReportLine

    if not overwrite_manual:
        has_manual = session.execute(
            select(ReportLine.id).where(
                ReportLine.rcept_no == rcept_no, ReportLine.unit_source == "manual",
            ).limit(1)
        ).first()
        if has_manual is not None:
            raise ValueError(
                f"{rcept_no} has manually-reviewed report_lines (unit_source='manual') — "
                f"refusing to auto-overwrite. Pass overwrite_manual=True if this is intentional."
            )

    body = [l for l in lines if l.statement != "note" and _is_loadable(l)]
    session.execute(delete(ReportLine).where(ReportLine.rcept_no == rcept_no))
    if not body:
        return 0

    # ★F3(2026-07-31): `table_title`·`parsed_at` 은 **행에 넣지 않는다** — 표 단위 값이라
    #   `report_tables` 로 갔다(측정된 함수종속, models.ReportTable docstring 참고).
    #   `section_path` 는 본문에서는 들여쓰기 경로라 **행마다 다르므로 그대로 둔다.**
    rows = [{k: v for k, v in l.as_row().items() if k not in _TABLE_LEVEL_COLS} for l in body]
    # ★한때 여기서 `r["parsed_at"] = None` 을 넣었다 — 모델에 파이썬측 default 가 있어서
    #   **키를 빼기만 하면 SQLAlchemy 가 대신 채웠기 때문**이다(재적재 중 482,386/482,386 행이
    #   채워진 것으로 실측). 지금은 모델에서 컬럼 자체를 뺐으므로 그 우회가 필요 없다.
    session.execute(insert(ReportLine).values(rows))
    return len(rows)


# note_lines = report_lines 구조 트윈(별도 테이블, collector/db 마이그레이션 생성). 모델 중복을
# 피하려 Core 로 raw insert 한다(컬럼명 = ReportLineRow.as_row() + parsed_at).
# ★F3(2026-07-31): 표 단위 컬럼은 `report_tables` 로 이동했다. 주석에서는 `section_path`
#   (=관장 주석 제목)도 표 단위라 함께 갔다 — 본문의 동명 컬럼(들여쓰기 경로)과 다른 것이다.
_TABLE_LEVEL_COLS = frozenset(("table_title", "parsed_at"))
_NOTE_TABLE_LEVEL_COLS = _TABLE_LEVEL_COLS | {"section_path"}

_NOTE_INSERT_COLS = (
    "corp_code rcept_no report_fiscal_year report_fiscal_period statement basis "
    "row_order depth node_role table_seq label_raw col_index "
    "col_label context_fiscal_year period_kind is_cumulative value_won value_raw adecimal "
    "unit_source header_hint source_ref context_raw"
).split()


def store_report_tables(session, rcept_no: str, lines: list[ReportLineRow]) -> int:
    """표 단위 메타를 `report_tables` 로 rcept 단위 delete-then-insert (F3, 2026-07-31).

    행 테이블에서 뺀 값들(제목·주석 제목·단위 선언 원문)을 **표마다 한 번** 적는다.
    키는 `(rcept_no, statement, basis, table_seq)` — 함수종속이 측정된 바로 그 키다
    (`collector/models.py:ReportTable` docstring).

    ★ `section_path` 는 **주석 행에서만** 가져온다. 본문의 동명 컬럼은 들여쓰기 경로라 행마다
      다르고, 그건 계속 `report_lines` 에 남는다(같은 이름의 다른 것 — 섞으면 본문 tree 가
      표 단위로 뭉개진다).
    ★ 같은 표의 행이 서로 다른 값을 들고 있으면 **첫 값을 쓴다.** 함수종속은 측정으로 확인됐고
      (표본 300 rcept 위반 0), 그래도 어긋나는 경우는 원문 자체가 그런 것이라 판단하지 않는다.
    """
    from sqlalchemy import delete, insert
    from collector.models import ReportTable

    session.execute(delete(ReportTable).where(ReportTable.rcept_no == rcept_no))
    stored = [l for l in lines
              if (l.statement == "note") or _is_loadable(l)]
    if not stored:
        return 0

    now = datetime.utcnow()
    seen: dict[tuple, dict] = {}
    for l in stored:
        key = (l.statement, l.basis, l.table_seq)
        row = seen.get(key)
        if row is None:
            row = seen[key] = {
                "rcept_no": rcept_no, "statement": l.statement, "basis": l.basis,
                "table_seq": l.table_seq, "table_title": None, "section_path": None,
                "unit_decl_raw": l.unit_decl_raw, "declared_unit": None,
                "unit_kind": l.unit_kind, "unit_inherited": bool(l.unit_inherited),
                "currency": l.currency,
                "parsed_at": now,
            }
        if row["table_title"] is None:
            row["table_title"] = l.table_title
        if l.statement == "note" and row["section_path"] is None:
            row["section_path"] = l.section_path
        if row["unit_decl_raw"] is None:
            row["unit_decl_raw"] = l.unit_decl_raw
        if row["currency"] is None:
            row["currency"] = l.currency
        if row["declared_unit"] is None and l.adecimal is not None:
            row["declared_unit"] = 10 ** (-l.adecimal) if l.adecimal <= 0 else None
    if not seen:
        return 0
    session.execute(insert(ReportTable).values(list(seen.values())))
    return len(seen)


def store_note_lines(session, rcept_no: str, lines: list[ReportLineRow]) -> int:
    """statement='note' 행을 note_lines 로 delete-then-insert(rcept 단위, 재현성).
    본문과 동일 원칙 — 값판단 없음. mixed lines 를 넘겨도 note 만 걸러 적재한다."""
    from sqlalchemy import text as _text

    notes = [l for l in lines if l.statement == "note"]
    session.execute(_text("DELETE FROM note_lines WHERE rcept_no = :r"), {"r": rcept_no})
    if not notes:
        return 0

    rows = [{k: v for k, v in l.as_row().items() if k not in _NOTE_TABLE_LEVEL_COLS}
            for l in notes]
    cols = ", ".join(_NOTE_INSERT_COLS)
    ph = ", ".join(f":{c}" for c in _NOTE_INSERT_COLS)
    session.execute(_text(f"INSERT INTO note_lines ({cols}) VALUES ({ph})"), rows)
    return len(rows)
