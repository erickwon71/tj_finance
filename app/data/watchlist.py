"""
관심종목(워치리스트) — corp_code 순서 목록을 로컬 JSON 에 보관.

저장 위치: ~/.tj_finance/watchlist.json = {"corps": [corp_code, ...]}.
UI(사이드바 빠른이동 · 기업 헤더 ⭐ 토글)에서 소비. app.data._localstore 위임.
"""
from __future__ import annotations

from app.data import _localstore as _ls

_FILE = "watchlist.json"


def get_watchlist() -> list[str]:
    """관심종목 corp_code 목록(추가 순서 유지)."""
    corps = _ls.load(_FILE).get("corps", [])
    return [c for c in corps if isinstance(c, str)]


def is_watched(corp_code: str) -> bool:
    return corp_code in get_watchlist()


def add(corp_code: str) -> None:
    corps = get_watchlist()
    if corp_code not in corps:
        corps.append(corp_code)
        _ls.save(_FILE, {"corps": corps})


def remove(corp_code: str) -> None:
    corps = [c for c in get_watchlist() if c != corp_code]
    _ls.save(_FILE, {"corps": corps})


def toggle(corp_code: str) -> bool:
    """추가/해제 토글 후 새 상태(watched 여부) 반환."""
    if is_watched(corp_code):
        remove(corp_code)
        return False
    add(corp_code)
    return True
