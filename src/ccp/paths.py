"""Project paths, read from config/paths.toml (+ optional config/paths.local.toml)."""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


@lru_cache(maxsize=1)
def _table() -> dict:
    table = tomllib.loads((CONFIG / "paths.toml").read_text(encoding="utf-8"))["paths"]
    local = CONFIG / "paths.local.toml"
    if local.exists():
        table.update(tomllib.loads(local.read_text(encoding="utf-8")).get("paths", {}))
    return table


def get(name: str) -> Path:
    """Absolute path for a key of [paths]."""
    p = Path(_table()[name])
    return p if p.is_absolute() else (ROOT / p).resolve()


def work_dir(episode_id: str) -> Path:
    d = get("work") / episode_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = get("cache")
    d.mkdir(parents=True, exist_ok=True)
    return d
