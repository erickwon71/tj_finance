"""
차트빌더 프리셋 저장/로드 — 로컬 JSON(단일 사용자).

저장 위치: ~/.tj_finance/chart_presets.json (repo 밖, 세션·재시작 넘어 유지).
프리셋 payload = JSON 직렬화 가능한 dict:
  {base_ids: [...], derived: [{op,a,b}, ...], overlay_price: bool, overlay_ids: [...]}

저장소 I/O 는 app.data._localstore(원자적·손상관대)에 위임.
"""
from __future__ import annotations

from app.data import _localstore as _ls

_FILE = "chart_presets.json"


def list_presets() -> list[str]:
    """저장된 프리셋 이름(정렬)."""
    return sorted(_ls.load(_FILE).keys())


def get_preset(name: str) -> dict | None:
    return _ls.load(_FILE).get(name)


def save_preset(name: str, payload: dict) -> None:
    data = _ls.load(_FILE)
    data[name] = payload
    _ls.save(_FILE, data)


def delete_preset(name: str) -> None:
    data = _ls.load(_FILE)
    if name in data:
        del data[name]
        _ls.save(_FILE, data)
