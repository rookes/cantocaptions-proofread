"""words.hk dictionary: parsed senses, lookups by term / alternative form / Jyutping.

The source JSON (one object per *sense*, ~70k) is parsed once into a pickle under cache/.
Each sense's `definition` packs POS, register labels, measure words, the Chinese and
English glosses and examples into one string; `Sense` holds them as fields.
"""
from __future__ import annotations

import json
import pickle
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import paths

RE_SYLLABLE = re.compile(r"^[a-z]+[1-6]$")
_LABELS = re.compile(r"^((?:\[[^\]]+\][、，,\s]*)+)")
_TAGS = re.compile(r"<[^>]+>")
CACHE_VERSION = 2


@dataclass
class Sense:
    term: str
    altterm: str
    jyutping: str                 # space-separated, as in the source
    pos: str = ""                 # 名詞, 動詞, ... ("" for pointer entries)
    labels: list[str] = field(default_factory=list)   # 俚語, 粗俗, 書面語, ...
    zh: str = ""
    en: str = ""
    measure: str = ""             # 量詞, e.g. "個／條"
    example: str = ""
    example_en: str = ""
    other_reading: str = ""       # from a 其他讀音 pointer entry

    @property
    def syllables(self) -> list[str]:
        return self.jyutping.split()

    def valid_jyutping(self) -> bool:
        syl = self.syllables
        return bool(syl) and all(RE_SYLLABLE.match(s) for s in syl)


def _parse(obj: dict) -> Sense:
    s = Sense(term=obj.get("term", "").strip(), altterm=obj.get("altterm", "").strip(),
              jyutping=obj.get("pronunciation", "").strip())
    lines = [ln.strip() for ln in obj.get("definition", "").split("\n") if ln.strip()]
    if lines and lines[0].startswith("其他讀音"):
        s.other_reading = lines[0].split("：", 1)[-1].strip()
        return s
    examples = []
    for ln in lines:
        if ln.startswith("【"):
            m = re.match(r"【(.+?)】[：:]?(.*)", ln)
            if m and not s.pos:
                s.pos, rest = m.group(1), m.group(2).strip()
                lm = _LABELS.match(rest)
                if lm:
                    s.labels = re.findall(r"\[([^\]]+)\]", lm.group(1))
                    rest = rest[lm.end():].strip()
                mm = re.search(r"（量詞：(.+?)）", rest)
                if mm:
                    s.measure = mm.group(1)
                s.zh = rest
        elif ln.startswith("<b>") and not s.en:
            s.en = _TAGS.sub("", ln).strip()
        elif ln.startswith("↳"):
            examples.append(_TAGS.sub("", ln[1:]).strip())
        elif not s.zh and not s.pos:
            s.zh = ln          # e.g. 「X」嘅俗字
    if examples:
        s.example = examples[0]
        if len(examples) > 1 and not re.search(r"[一-鿿]", examples[1]):
            s.example_en = examples[1]
    return s


@lru_cache(maxsize=1)
def senses() -> list[Sense]:
    src = paths.get("dictionary")
    stat = src.stat()
    key = (CACHE_VERSION, stat.st_size, int(stat.st_mtime))
    cache = paths.cache_dir() / "wordshk.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as f:
                stored_key, data = pickle.load(f)
            if stored_key == key:
                return data
        except Exception:
            pass
    data = [_parse(o) for o in json.loads(src.read_text(encoding="utf-8"))]
    with cache.open("wb") as f:
        pickle.dump((key, data), f, protocol=pickle.HIGHEST_PROTOCOL)
    return data


@lru_cache(maxsize=1)
def _index() -> dict:
    by_term: dict[str, list[int]] = {}
    by_jp: dict[str, set[str]] = {}
    by_toneless: dict[str, set[str]] = {}
    for i, s in enumerate(senses()):
        for form in {s.term, s.altterm} - {""}:
            by_term.setdefault(form, []).append(i)
        for jp in {s.jyutping, s.other_reading} - {""}:
            by_jp.setdefault(jp, set()).add(s.term)
            by_toneless.setdefault(re.sub(r"\d", "", jp), set()).add(s.term)
    return {"term": by_term, "jp": by_jp, "toneless": by_toneless}


def lookup(term: str) -> list[Sense]:
    return [senses()[i] for i in _index()["term"].get(term, [])]


def terms_for_jyutping(jp: str, toneless: bool = False) -> list[str]:
    jp = " ".join(jp.lower().split())
    if toneless:
        return sorted(_index()["toneless"].get(re.sub(r"\d", "", jp), ()))
    return sorted(_index()["jp"].get(jp, ()))


def terms_containing(q: str) -> list[str]:
    """Terms (or alternative forms) that contain *q*; if *q* is Jyutping (has tone digits),
    terms whose reading contains that syllable sequence. Shortest first."""
    q = q.strip()
    if any(ch.isdigit() for ch in q):
        seq = " " + " ".join(q.lower().split()) + " "
        found = {t for jp, ts in _index()["jp"].items() if seq in f" {jp} " for t in ts}
    else:
        found = {t for t in _index()["term"] if q in t}
    return sorted(found, key=lambda t: (len(t), t))


def has_term(term: str) -> bool:
    return term in _index()["term"]


def term_readings() -> dict[str, set[str]]:
    """Every distinct term (and alt form) -> its Jyutping readings (valid ones only)."""
    out: dict[str, set[str]] = {}
    for s in senses():
        jps = [jp for jp in (s.jyutping, s.other_reading) if jp]
        for jp in jps:
            if not all(RE_SYLLABLE.match(x) for x in jp.split()):
                continue
            for form in {s.term, s.altterm} - {""}:
                out.setdefault(form, set()).add(jp)
    return out


def particle_senses(jp: str, max_senses: int = 12) -> dict:
    """words.hk particle (助詞) senses for a *reading*, whatever character words.hk spells it
    with. words.hk and CantoCaptions do not always pick the same character for a particle
    (words.hk writes ge2 as 嘅, gaa2 as 㗎, lo1 as 囉, where CantoCaptions writes 𠸏, 𠿪,
    囖), so particles are matched on Jyutping, never on the character."""
    from . import jyutping
    jp = " ".join(jp.lower().split())
    cc_form = "".join(next((c for c, r in jyutping.particle_readings().items() if r == syl), "?")
                      for syl in jp.split())
    rows = []
    for term in terms_for_jyutping(jp):
        for s in lookup(term):
            if s.jyutping == jp and "助詞" in s.pos:
                rows.append({"words_hk_spelling": term, "pos": s.pos, "zh": s.zh, "en": s.en,
                             **({"example": s.example + (f" ({s.example_en})" if s.example_en else "")}
                                if s.example else {})})
    # Same meaning listed under several spellings: keep one row per gloss.
    seen, uniq = set(), []
    for r in rows:
        if r["zh"] in seen:
            continue
        seen.add(r["zh"])
        uniq.append(r)
    out = {"jyutping": jp, "cantocaptions_form": cc_form, "senses": uniq[:max_senses]}
    if len(uniq) > max_senses:
        out["more_senses"] = len(uniq) - max_senses
    if not uniq and len(jp.split()) > 1:
        out["note"] = "no entry for the compound; look up each syllable"
        out["parts"] = [particle_senses(s, 4) for s in jp.split()]
    return out


def describe(term: str, max_senses: int = 4) -> dict:
    """A compact JSON-able summary of every sense of *term*."""
    found = lookup(term)
    readings = sorted({s.jyutping for s in found if s.jyutping} | {s.other_reading for s in found if s.other_reading})
    out = {"term": term, "found": bool(found), "jyutping": readings, "senses": []}
    for s in found:
        if s.other_reading and not s.pos:
            continue
        sense = {"pos": s.pos, "labels": s.labels, "zh": s.zh, "en": s.en}
        if s.measure:
            sense["measure"] = s.measure
        if s.altterm and s.altterm != term:
            sense["alt"] = s.altterm
        if s.example:
            sense["example"] = s.example + (f" ({s.example_en})" if s.example_en else "")
        out["senses"].append(sense)
    total = len(out["senses"])
    out["senses"] = out["senses"][:max_senses]
    if total > max_senses:
        out["more_senses"] = total - max_senses
    return out
