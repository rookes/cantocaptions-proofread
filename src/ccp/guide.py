"""The standards prose about particles, served one particle at a time.

`references/particle-usage.md` (a standards page: how the problem particles are used, near
pairs, question particles, compounds, set phrases) is split into its `###` sections, each
with its `####` usages. A section is found by the particle characters (or readings) in its
heading; a section whose heading names none (`### 我都話咗…`, `### gaa laa`) is found by the
particles in its text. `conventions.md` adds each particle's one-line meaning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import jyutping, paths
from .corpus import FINAL_PARTICLES

REFS = paths.ROOT / ".agents" / "skills" / "cantocaptions-standards" / "references"
USAGE = REFS / "particle-usage.md"
CONVENTIONS = REFS / "conventions.md"
_READING = re.compile(r"\b[a-z]+[1-6]\b")


@dataclass
class Section:
    group: str          # the `##` heading it sits under (Single Particles, Special Phrases…)
    heading: str        # 喇 laa3
    text: str           # the section with its usages, as Markdown
    keys: set[str]      # particle characters and readings that find it
    by_heading: bool    # keys come from the heading (else from the text)

    @property
    def ref(self) -> str:
        return f"particle-usage: {self.heading}"


def _keys(text: str) -> set[str]:
    chars = {c for c in text if c in FINAL_PARTICLES}
    return chars | set(_READING.findall(text))


@lru_cache(maxsize=1)
def sections() -> list[Section]:
    if not USAGE.is_file():
        return []
    out: list[Section] = []
    group, heading, lines = "", None, []

    def close():
        if heading is not None:
            body = "\n".join(lines).strip()
            keys = _keys(heading)
            out.append(Section(group, heading, body, keys or _keys(body), bool(keys)))

    for ln in USAGE.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## ") and not ln.startswith("### "):
            close()
            group, heading, lines = ln[3:].strip(), None, []
        elif ln.startswith("### "):
            close()
            heading, lines = ln[4:].strip(), [ln]
        elif heading is not None:
            lines.append(ln)
    close()
    return out


def _query_keys(query: str) -> set[str]:
    query = query.strip()
    if _READING.fullmatch(query):
        chars = {c for c, r in jyutping.particle_readings().items() if r == query}
        return {query} | chars
    keys = {c for c in query if c in FINAL_PARTICLES}
    keys |= {jyutping.particle_readings()[c] for c in keys if c in jyutping.particle_readings()}
    return keys


def lookup(query: str) -> list[Section]:
    """Sections about a particle (喇, laa3) or a compound (㗎喇): the ones that name it in
    their heading first, then the ones that discuss it."""
    keys = _query_keys(query)
    if not keys:
        return []
    found = [s for s in sections() if s.keys & keys]
    return sorted(found, key=lambda s: (not s.by_heading, -len(s.keys & keys)))


@lru_cache(maxsize=1)
def _convention_lines() -> dict[str, str]:
    if not CONVENTIONS.is_file():
        return {}
    out = {}
    for ln in CONVENTIONS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- (\S+) ([a-z]+[1-6](?: [a-z]+[1-6])*)\b(.*)$", ln)
        if m and all(c in FINAL_PARTICLES for c in m.group(1)):
            out.setdefault(m.group(1), ln[2:].strip())
    return out


def convention(particle: str) -> str | None:
    """The particle's line in conventions.md: `喇 laa3 — change of state …`."""
    return _convention_lines().get(particle)
