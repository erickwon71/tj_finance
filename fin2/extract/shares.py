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
"""
from __future__ import annotations

import re
from pathlib import Path

_NUM = re.compile(r'^-?[\d,]+$')
_TR = re.compile(r'<TR.*?</TR>', re.S | re.I)
_CELL = re.compile(r'<T[DEH][^>]*>(.*?)</T[DEH]>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'\s+')


def _decode(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    try:
        return raw.decode('utf-8')          # 진짜 utf-8 보고서
    except UnicodeDecodeError:
        return raw.decode('cp949', 'replace')  # EUC-KR(대다수)


def _cells(tr: str) -> list[str]:
    return [_WS.sub(' ', _TAG.sub('', c)).strip() for c in _CELL.findall(tr)]


def extract_issued_common_shares(path: str | Path) -> int | None:
    """발행주식의 총수(Ⅳ) 보통주. 없으면 현재까지 발행한 주식의 총수(Ⅱ) 폴백. 실패 시 None."""
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
            val = _pick(rows, "발행주식의 총수")          # Ⅳ
            if val is None:
                val = _pick(rows, "현재까지 발행한 주식의 총수")  # Ⅱ 폴백
            if val is not None:
                return val
    return None


def _pick(rows: list[list[str]], key: str) -> int | None:
    """라벨에 key 포함(단 '발행할'=수권주식 제외)하는 행의 첫 숫자 컬럼(=보통주)."""
    for cells in rows:
        joined = " ".join(cells)
        if key in joined and "발행할" not in joined:
            for c in cells:
                if _NUM.match(c) and c != '-':
                    n = int(c.replace(',', ''))
                    if n > 0:
                        return n
    return None
