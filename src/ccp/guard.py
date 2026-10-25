"""A tripwire for changes to this repository's own code during an agent's session.

Agents proofread with `ccp`; they must not change `ccp` (AGENTS.md, hard rules). When `ccp`
cannot do something, the agent asks the user; it does not patch the tool, however small the
patch looks. Harnesses differ in what they let an agent edit, so `ccp` checks for itself:

- `ccp setup` (the first command of every session) records a fingerprint of the watched files;
  changes made between sessions are the user's, and setup reports them;
- every other command compares the files with that fingerprint and refuses to run while any
  differs, naming the files, so a change made during the session stops the work and reaches
  the user. Running `ccp setup` again (the user's say-so) records the new state.

Watched: the code, scripts, tests, configuration, skills and agent instructions. Not watched:
what `ccp` itself writes (config/paths.local.toml, particles/collocations.toml through
`ccp particles note`, glossaries/, work/, cache/).
"""
from __future__ import annotations

import hashlib
import json

from . import paths

WATCHED = ("src/ccp/**/*.py", "scripts/*.py", "scripts/*.ps1", "tests/**/*.py", "config/*.toml",
           "pyproject.toml", "AGENTS.md", "CLAUDE.md", ".agents/**/*.md")
NOT_WATCHED = {"config/paths.local.toml"}


def _file():
    return paths.cache_dir() / "code_fingerprint.json"


def fingerprint() -> dict[str, str]:
    out = {}
    for pattern in WATCHED:
        for p in paths.ROOT.glob(pattern):
            rel = p.relative_to(paths.ROOT).as_posix()
            if p.is_file() and rel not in NOT_WATCHED and "__pycache__" not in rel:
                out[rel] = hashlib.sha1(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def _diff(old: dict[str, str], new: dict[str, str]) -> list[str]:
    return sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))


def record() -> list[str]:
    """Record the current state; returns what changed since the last record (the user's
    changes between sessions)."""
    f = _file()
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    new = fingerprint()
    f.write_text(json.dumps(new, indent=0), encoding="utf-8")
    return _diff(old, new) if old is not None else []


def changed() -> list[str]:
    """Watched files that differ from the last record ([] when nothing was recorded yet)."""
    f = _file()
    if not f.exists():
        return []
    try:
        old = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return _diff(old, fingerprint())


def refusal(files: list[str]) -> str:
    shown = ", ".join(files[:8]) + (f" and {len(files) - 8} more" if len(files) > 8 else "")
    return ("ccp will not run: its own files changed during this session (" + shown + "). Agents must "
            "not change ccp's code, skills or configuration without the user's explicit request "
            "(AGENTS.md, hard rule 8). Stop and tell the user which files changed and why. Do not "
            "undo or redo the change yourself. Once the user has decided, `uv run ccp setup` records "
            "the files as they are and ccp runs again.")
