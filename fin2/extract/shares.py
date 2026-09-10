"""사업보고서 '주식의 총수 등' 섹션에서 발행주식 총수(보통주) 추출.

DART stockTotqySttus API 는 ~2016+ 만 보유 → pre-2016(및 2016+ DART 결측) 주식수는 보고서 본문에서
직접 파싱한다. 표 구조:

    구분                              | 보통주      | 우선주     | 합계      | 비고
    Ⅰ. 발행할 주식의 총수             | 400,000,000 | ...
    Ⅱ. 현재까지 발행한 주식의 총수    | 155,609,337 | ...
    Ⅲ. 현재까지 감소한 주식의 총수    |   8,310,000 | ...
    Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)        | 147,299,337 | ...   ← DART istc_totqy 와 동일(=채택)
    Ⅴ. 자기주식수                     |  17,094,741 | ...
    Ⅵ. 유통주식수 (Ⅳ-Ⅴ)             | 130,204,596 | ...

채택 = Ⅳ '발행주식의 총수' 보통주(첫 숫자 컬럼). DART(2016+)와 정확 일치 검증됨.
DART document.xml 은 보통 EUC-KR(utf-8 로 잘못 선언) → 인코딩 폴백.

★2026-09-09 R90 — 단위 "천주" 미인식으로 ×1000 축소(발견 경위: 계층2 검토 캠페인 중
사용자가 "시총 오류 확인해봐" 지시 → stock_prices.market_cap 전종목 정체(9/1~) 조사
과정에서 부수 발견). 표 헤더가 "(단위 : 천주, %)"인 서식(현대로템·크린앤사이언스·에스텍·
서산·해성디에스·파이버프로·CJ씨푸드 등 다수 실측)에서 이 함수가 인쇄된 숫자를 "주" 단위로
그대로 채택해 정확히 1000배 축소됐다(현대로템 실측: 표에 "200,000" 인쇄, 비고란 "정관상
발행 가능한 주식 총수 : 2억주" 로 200,000×1,000=200,000,000 검증).

★★"(단위 : 천주)" 캡션을 그대로 믿으면 안 된다 — **원문 자체가 캡션을 잘못 붙인 필링이
실측된다**(일승 01396676·한일철강 00163196: 캡션은 "천주"인데 프로즈가 표에 인쇄된 숫자와
그대로 일치해 실제로는 "주" 단위다 — 캡션만 믿었으면 새 불가값을 만들었을 것이다,
2026-09-09 이 수정 검증 중 발견). 그래서 `_table_multiplier()`는 프로즈("...총수는 [보통주]
N주")·비고("N억주")의 평문 숫자를 **Ⅰ(발행할)/Ⅱ(현재까지 발행한) 행과 대조**해 표 전체에
적용할 배수 하나를 정한다 — Ⅳ(=Ⅱ−Ⅲ)는 산술값이라 프로즈에 거의 안 나오므로 Ⅳ 자체를
대조하면 못 잡는다(한일철강 실측: Ⅱ-Ⅲ 만 프로즈에, Ⅳ 는 계산값이라 프로즈에 없음).
교차검증 대상이 아예 없을 때만 캡션을 그대로 신뢰한다(짐작 금지 R0 — 근거 있는 것만
숫자를 바꾼다)."""
from __future__ import annotations

import re
from pathlib import Path

_NUM = re.compile(r'^-?[\d,]+$')
_TR = re.compile(r'<TR.*?</TR>', re.S | re.I)
_CELL = re.compile(r'<T[DEH][^>]*>(.*?)</T[DEH]>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'\s+')

# 물리적 상한: KOSPI/KOSDAQ 최다주식(삼성전자 ~60억주)도 10^10 미만. 10^11 초과는 불가값
# (단위 오인·셀 병합 등 파싱 오류 신호) → 채택 거부. shares_out 10^6 과다저장 재발 방지(P0-3).
_MAX_PLAUSIBLE_SHARES = 100_000_000_000  # 10^11


def _decode(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    try:
        return raw.decode('utf-8')          # 진짜 utf-8 보고서
    except UnicodeDecodeError:
        return raw.decode('cp949', 'replace')  # EUC-KR(대다수)


def _cells(tr: str) -> list[str]:
    return [_WS.sub(' ', _TAG.sub('', c)).strip() for c in _CELL.findall(tr)]


_LABEL_AUTHORIZED = "발행할 주식의 총수"       # Ⅰ (교차검증 전용 — 값 자체는 채택 안 함)
_LABEL_ISSUED = "발행주식의 총수"              # Ⅳ (채택 우선)
_LABEL_ISSUED_TO_DATE = "현재까지 발행한 주식의 총수"  # Ⅱ (폴백 + 교차검증)

_UNIT_DECL = re.compile(r'단위\s*[:：]\s*([^)]*)')
_UNIT_WINDOW = 400   # 표 시작 직전 이 정도 범위 안에 캡션이 있다(현대로템 실측 42자 거리).

# 프로즈(평문) 진술 — "발행한/발행할 주식의 총수는 [보통주] N주[이며/입니다]". 단위 표기
# 자체가 없는 "주" 리터럴이라 캡션보다 신뢰도가 높다(오탈자 캡션에 안 걸림).
_PLAIN_TOTAL_PROSE = re.compile(r'총수는\s*(?:보통주\s*)?([\d,]+)\s*주')
# 비고란의 "정관상 발행 가능한 주식 총수 : 2억주" 류 — 억주 단위 평문 진술.
_EOK_JU = re.compile(r'([\d,]+(?:\.\d+)?)\s*억\s*주')


def _corroborating_values(segment: str) -> set[int]:
    """프로즈/비고에서 뽑은, 이미 "주" 단위로 확정된 절대값들(있으면 캡션보다 우선)."""
    out: set[int] = set()
    for m in _PLAIN_TOTAL_PROSE.finditer(segment):
        out.add(int(m.group(1).replace(',', '')))
    for m in _EOK_JU.finditer(segment):
        out.add(int(float(m.group(1).replace(',', '')) * 100_000_000))
    return out


def _unit_multiplier(text: str, table_start: int) -> int:
    """표 시작 직전 캡션의 "(단위 : 천주, %)" 선언에서 배수를 뽑는다(교차검증 실패 시
    폴백용). 가장 가까운(=표에 직결된) 선언만 본다 — 창을 넓게 잡으면 훨씬 앞선 무관한
    표의 단위선언을 잘못 물 수 있다. 선언이 없거나 "주"(다수, 기본값)면 배수 1."""
    seg = text[max(0, table_start - _UNIT_WINDOW):table_start]
    matches = list(_UNIT_DECL.finditer(seg))
    if not matches:
        return 1
    unit = _WS.sub('', matches[-1].group(1))   # 표에 가장 가까운(마지막) 선언
    return 1000 if '천주' in unit else 1


def _table_multiplier(text: str, section_start: int, table_start: int, table_end: int,
                      rows: list[list[str]]) -> int:
    """이 표 전체에 적용할 배수 하나. Ⅰ(발행할)·Ⅱ(현재까지 발행한) 행의 **인쇄된 그대로의
    숫자**를 프로즈/비고의 평문 "주" 진술과 대조해 정한다 — 한 표 안에서 단위는 하나이므로
    Ⅰ/Ⅱ 중 아무거나 대조에 성공하면 그 표 전체(Ⅳ 포함)에 적용한다. Ⅳ(=Ⅱ−Ⅲ)는 산술값이라
    프로즈에 거의 안 나와 그것만 대조하면 못 잡는다(한일철강 실측, 위 모듈 docstring 참고).
    교차검증 대상이 없을 때만 캡션(`_unit_multiplier`)을 그대로 신뢰한다.

    ★프로즈 검색 범위는 표 시작이 아니라 섹션 헤더('주식의 총수 등') 시작부터 잡는다 —
    일승 실측: 캡션 전용 표(단위선언만 있고 라벨 없어 `_pick` 이 건너뜀)가 프로즈와 진짜
    데이터표 사이에 끼어 있어, 데이터표 기준 고정폭 창(400자)으론 791자 떨어진 프로즈를
    놓친다. 캡션은 반대로 표에 딱 붙어 있어야 그 표 것이라 확신할 수 있어 좁은 창을 쓴다."""
    corroborated = _corroborating_values(_TAG.sub(' ', text[section_start:table_end]))
    if corroborated:
        for label in (_LABEL_AUTHORIZED, _LABEL_ISSUED_TO_DATE):
            v = _pick_raw(rows, label)
            if v is None:
                continue
            if v in corroborated:
                return 1
            if v * 1000 in corroborated:
                return 1000
    return _unit_multiplier(text, table_start)


def extract_issued_common_shares_detailed(path: str | Path) -> tuple[int, str] | None:
    """발행주식의 총수(Ⅳ) 보통주. 없으면 현재까지 발행한 주식의 총수(Ⅱ) 폴백. 실패 시 None.
    반환 (shares, matched_label) — matched_label 은 provenance(어느 원문 항목을 채택했는지,
    계층2 전사 source_ref 용, 2026-08-09 Phase 2)."""
    text = _decode(path)
    # '주식의 총수' 출현마다(목차 포함) 이후 가까운 TABLE 들에서 행 탐색.
    for sec in (m.start() for m in re.finditer("주식의 총수", text)):
        pos = sec
        for _ in range(3):  # 섹션 직후 최대 3개 TABLE
            st = text.find("<TABLE", pos)
            if st < 0:
                break
            en = text.find("</TABLE>", st)
            if en < 0:
                break
            pos = en + 8
            rows = [_cells(tr) for tr in _TR.findall(text[st:pos])]
            mult = _table_multiplier(text, sec, st, pos, rows)
            val = _pick(rows, _LABEL_ISSUED)          # Ⅳ
            if val is not None:
                return val * mult, _LABEL_ISSUED
            val = _pick(rows, _LABEL_ISSUED_TO_DATE)  # Ⅱ 폴백
            if val is not None:
                return val * mult, _LABEL_ISSUED_TO_DATE
    return None


def extract_issued_common_shares(path: str | Path) -> int | None:
    """발행주식의 총수(Ⅳ) 보통주. 없으면 현재까지 발행한 주식의 총수(Ⅱ) 폴백. 실패 시 None."""
    r = extract_issued_common_shares_detailed(path)
    return r[0] if r else None


def _pick_raw(rows: list[list[str]], key: str) -> int | None:
    """라벨에 key 포함하는 행의 첫 숫자 컬럼(=보통주). 배타조건 없음(교차검증용, Ⅰ 포함)."""
    for cells in rows:
        joined = " ".join(cells)
        if key in joined:
            for c in cells:
                if _NUM.match(c) and c != '-':
                    n = int(c.replace(',', ''))
                    if 0 < n <= _MAX_PLAUSIBLE_SHARES:
                        return n
    return None


def _pick(rows: list[list[str]], key: str) -> int | None:
    """라벨에 key 포함(단 '발행할'=수권주식 제외)하는 행의 첫 숫자 컬럼(=보통주).

    물리적 불가값(> 10^11 = 삼성전자 발행주식수의 10배 초과)은 단위 오인·셀 병합 등 파싱 오류로
    보고 채택하지 않는다(shares_out 10^6 과다저장 재발 방지, P0-3)."""
    for cells in rows:
        joined = " ".join(cells)
        if key in joined and "발행할" not in joined:
            for c in cells:
                if _NUM.match(c) and c != '-':
                    n = int(c.replace(',', ''))
                    if 0 < n <= _MAX_PLAUSIBLE_SHARES:
                        return n
    return None
