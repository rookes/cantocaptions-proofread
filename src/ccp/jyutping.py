"""Character -> every Jyutping reading, most common first.

pycantonese gives one reading per character (亂 -> lyun6 only), but a mishearing often
keeps the tone of a *less common* reading (亂 also reads lyun1/lyun2). Readings are
therefore harvested from words.hk: every term whose character count equals its syllable
count contributes one (char, syllable) pair per position, and `其他讀音` pointers add
alternates. pycantonese fills in characters words.hk never spells out.
"""
from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache

from . import dictionary, paths

CACHE_VERSION = 1


def is_cjk(ch: str) -> bool:
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return (0x3400 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x3134F
            or ch in "〇")


def is_sound(ch: str) -> bool:
    """A character that is pronounced: CJK, Latin letters, digits."""
    return unicodedata.category(ch)[0] not in "PZSC"


@lru_cache(maxsize=1)
def _table() -> dict[str, list[str]]:
    src = paths.get("dictionary")
    stat = src.stat()
    key = f"{CACHE_VERSION}:{stat.st_size}:{int(stat.st_mtime)}"
    cache = paths.cache_dir() / "readings.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("key") == key:
                return data["table"]
        except Exception:
            pass
    counts: dict[str, Counter] = defaultdict(Counter)
    for s in dictionary.senses():
        for jp, weight in ((s.jyutping, 1), (s.other_reading, 1)):
            syl = jp.split()
            if not syl or not all(dictionary.RE_SYLLABLE.match(x) for x in syl):
                continue
            for form in {s.term, s.altterm} - {""}:
                chars = [c for c in form if is_cjk(c)]
                if len(chars) == len(syl) and len(chars) == len([c for c in form if is_sound(c)]):
                    for c, y in zip(chars, syl):
                        counts[c][y] += weight
    table = {c: [y for y, _ in cnt.most_common()] for c, cnt in counts.items()}
    cache.write_text(json.dumps({"key": key, "table": table}, ensure_ascii=False), encoding="utf-8")
    return table


@lru_cache(maxsize=None)
def _pycantonese(ch: str) -> tuple[str, ...]:
    try:
        import pycantonese
    except ImportError:
        return ()
    try:
        out = pycantonese.characters_to_jyutping(ch)
    except Exception:
        return ()
    if out and out[0][1]:
        return tuple(out[0][1].split()[:1])
    return ()


@lru_cache(maxsize=1)
def _convention() -> dict:
    import tomllib
    p = paths.CONFIG / "particle_readings.toml"
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def particle_readings() -> dict[str, str]:
    return _convention().get("readings", {})


def exclusive_readings() -> dict[str, list[str]]:
    return _convention().get("exclusive", {})


def readings(ch: str) -> list[str]:
    """All known readings of one character, most common first ([] if unknown). A
    sentence-final particle's CantoCaptions reading always comes first; characters the
    conventions reserve for one reading (噉 gam2, 咁 gam3) get only that."""
    if ch in exclusive_readings():
        return list(exclusive_readings()[ch])
    found = list(_table().get(ch, ()))
    fixed = particle_readings().get(ch)
    if fixed:
        found = [fixed] + [r for r in found if r != fixed]
    for r in _pycantonese(ch) if is_cjk(ch) else ():
        if r not in found:
            found.append(r)
    return found


def reading(ch: str) -> str | None:
    r = readings(ch)
    return r[0] if r else None


def text_readings(text: str) -> list[tuple[str, list[str]]]:
    """[(char, readings)] for each CJK character of *text* (punctuation, Latin skipped)."""
    return [(c, readings(c)) for c in text if is_cjk(c)]


def romanize(text: str, all_readings: bool = False) -> str:
    """Space-separated Jyutping for the CJK characters of *text*. Unknown characters show
    as '?'. With all_readings, polyphones show as 'lyun6|lyun1|lyun2'."""
    out = []
    for c, rs in text_readings(text):
        if not rs:
            out.append("?")
        elif all_readings and len(rs) > 1:
            out.append("|".join(rs[:4]))
        else:
            out.append(rs[0])
    return " ".join(out)


def toneless(syl: str) -> str:
    return syl.rstrip("123456")
