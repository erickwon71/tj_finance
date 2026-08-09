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


_LABEL_ISSUED = "발행주식의 총수"              # Ⅳ (채택 우선)
_LABEL_ISSUED_TO_DATE = "현재까지 발행한 주식의 총수"  # Ⅱ (폴백)


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
            val = _pick(rows, _LABEL_ISSUED)          # Ⅳ
            if val is not None:
                return val, _LABEL_ISSUED
            val = _pick(rows, _LABEL_ISSUED_TO_DATE)  # Ⅱ 폴백
            if val is not None:
                return val, _LABEL_ISSUED_TO_DATE
    return None


def extract_issued_common_shares(path: str | Path) -> int | None:
    """발행주식의 총수(Ⅳ) 보통주. 없으면 현재까지 발행한 주식의 총수(Ⅱ) 폴백. 실패 시 None."""
    r = extract_issued_common_shares_detailed(path)
    return r[0] if r else None


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
