"""
로컬 사용자 데이터 JSON 저장소 — 프리셋·관심종목·저장스크린 공용 백엔드.

~/.tj_finance/ 아래 파일별로 원자적(tmp→replace) 읽기/쓰기. 손상·부재 파일엔 관대(빈 dict).
단일 사용자 로컬 앱 전제라 잠금·동시성은 고려하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".tj_finance"


def _path(name: str) -> Path:
    return CONFIG_DIR / name


def load(name: str) -> dict:
    """파일명 → dict. 없거나 손상되면 빈 dict."""
    try:
        with open(_path(name), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def save(name: str, data: dict) -> None:
    """dict → 파일명(원자적 tmp→replace)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(name)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(p)
