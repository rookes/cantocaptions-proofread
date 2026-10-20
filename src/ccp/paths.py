"""Project paths, read from config/paths.toml (+ optional config/paths.local.toml).

The sibling repositories are optional. `has()` says whether one is really there, and every
command that uses one falls back to doing without it (`ccp setup` lists what each enables).
`config/paths.local.toml` holds this machine's overrides under [paths] and, under [setup],
whether first-use setup is done and which resources the user said they do not have.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
LOCAL = CONFIG / "paths.local.toml"


def _read_local() -> dict:
    return tomllib.loads(LOCAL.read_text(encoding="utf-8")) if LOCAL.exists() else {}


@lru_cache(maxsize=1)
def _table() -> dict:
    table = tomllib.loads((CONFIG / "paths.toml").read_text(encoding="utf-8"))["paths"]
    table.update(_read_local().get("paths", {}))
    return table


def _resolve(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def get(name: str) -> Path:
    """Absolute path for a key of [paths]."""
    return _resolve(_table()[name])


def media_dirs() -> list[Path]:
    """The user's own media folders (`media_dirs`), searched by name when no dataset links
    a subtitle to its media. Only folders that exist."""
    dirs = _table().get("media_dirs") or []
    return [p for p in (_resolve(d) for d in dirs) if p.is_dir()]


def has(name: str) -> bool:
    """Is the resource behind a [paths] key really there (not just configured)?"""
    try:
        p = get(name)
    except KeyError:
        return False
    if name == "dataset":
        return (p / "data" / "manifest.json").is_file()
    if name == "dataset_tiers":
        return (get("dataset") / "data" / "std" / "episodes.json").is_file()
    if name == "cantocaptions":
        return (p / "Subtitles").is_dir() or (p / "README.md").is_file()
    if name == "cantocaptions_ai":
        return (p / "pyproject.toml").is_file() and (p / ".venv").is_dir()
    if name in ("subtitles", "media_root", "work", "cache", "glossaries"):
        return p.is_dir()
    return p.exists()


def ccai_has_ocr() -> bool:
    """Is cantocaptions-ai's `ocr` extra (PaddleOCR) installed in its environment?"""
    if not has("cantocaptions_ai"):
        return False
    venv = get("cantocaptions_ai") / ".venv"
    return any(venv.glob("Lib/site-packages/paddleocr")) or any(venv.glob("lib/python*/site-packages/paddleocr"))


def setup_state() -> dict:
    """[setup] of paths.local.toml: {"completed": bool, "declined": [keys]}."""
    s = _read_local().get("setup", {})
    return {"completed": bool(s.get("completed")), "declined": list(s.get("declined", []))}


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "/").replace('"', '\\"')
    return f'"{s}"'


def write_local(paths: dict | None = None, setup: dict | None = None) -> Path:
    """Merge *paths* into [paths] and *setup* into [setup] of paths.local.toml (a value of None
    removes the key), keeping everything else that is there."""
    data = _read_local()
    for section, updates in (("paths", paths or {}), ("setup", setup or {})):
        table = data.setdefault(section, {})
        for k, v in updates.items():
            if v is None:
                table.pop(k, None)
            else:
                table[k] = v
    lines = ["# This machine's paths and first-use setup state (written by `ccp setup`; gitignored).", ""]
    for section, table in data.items():
        if not table:
            continue
        lines.append(f"[{section}]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in table.items()]
        lines.append("")
    LOCAL.write_text("\n".join(lines), encoding="utf-8")
    _table.cache_clear()
    return LOCAL


def work_dir(episode_id: str) -> Path:
    d = get("work") / episode_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = get("cache")
    d.mkdir(parents=True, exist_ok=True)
    return d
