"""
저장된 스크리너 구성(saved screens) — 스크리너 세션 위젯 상태의 스냅샷을 로컬 JSON 에 보관.

스크리너 페이지의 필터/정렬/집계 구성은 st.session_state 위젯 키(`scr_*`, `p{i}_*`)에
흩어져 있다. 저장 = 그 키들의 값 dict 스냅샷, 로드 = 그대로 되돌린 뒤 rerun.
저장 위치: ~/.tj_finance/saved_screens.json = {name: {key: value, ...}, ...}.
"""
from __future__ import annotations

from app.data import _localstore as _ls

_FILE = "saved_screens.json"


def list_screens() -> list[str]:
    return sorted(_ls.load(_FILE).keys())


def get_screen(name: str) -> dict | None:
    return _ls.load(_FILE).get(name)


def save_screen(name: str, config: dict) -> None:
    data = _ls.load(_FILE)
    data[name] = config
    _ls.save(_FILE, data)


def delete_screen(name: str) -> None:
    data = _ls.load(_FILE)
    if name in data:
        del data[name]
        _ls.save(_FILE, data)
