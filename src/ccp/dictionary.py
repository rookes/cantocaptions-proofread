"""words.hk dictionary: parsed senses, lookups by term / alternative form / Jyutping.

The source is words.hk's CSV export (`dictionaries/words.hk-ordered.csv`, the `dictionary`
path; one row per *sense*, ~70k), parsed once into a pickle under cache/. Every words.hk lookup
in ccp goes through this module and that one file. Its columns hold POS, labels, glosses,
measure word, synonyms and alternative readings separately, and its examples carry their
Jyutping, which is how a particle's tone is known in each example.
"""
from __future__ import annotations

import csv
import pickle
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import paths

RE_SYLLABLE = re.compile(r"^[a-z]+[1-6]$")
CACHE_VERSION = 3


@dataclass
class Example:
    yue: str
    jyutping: str = ""            # the whole sentence's reading, "" when words.hk gives none
    en: str = ""


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
    other_reading: str = ""       # another reading of the same term
    examples: list[Example] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    reviewed: bool = False

    @property
    def syllables(self) -> list[str]:
        return self.jyutping.split()

    def valid_jyutping(self) -> bool:
        syl = self.syllables
        return bool(syl) and all(RE_SYLLABLE.match(s) for s in syl)


# An example's reading, in parentheses at the end of its yue: line.
_EX_READING = re.compile(r"\s*\(([^()]*\b[a-z]+[1-6]\b[^()]*)\)\s*$")


def _examples(field_text: str) -> list[Example]:
    """`<eg>`-separated blocks of `yue:` / `zho:` / `eng:` lines. Each yue line is one
    example (a block can give two Cantonese versions of one sentence); zho (Standard
    Chinese) lines are skipped; the block's eng line goes with every yue line."""
    out = []
    for block in field_text.split("<eg>"):
        yues, en = [], ""
        for ln in block.split("\n"):
            lang, _, text = ln.strip().partition(":")
            if lang == "yue" and text.strip():
                yues.append(text.strip())
            elif lang == "eng" and not en:
                en = re.sub(r"^\[[^\]]*\]\s*", "", text.strip())   # [ChatGPT] and similar tags
        for y in yues:
            m = _EX_READING.search(y)
            text, jp = (y[:m.start()], m.group(1)) if m else (y, "")
            jp = " ".join(re.sub(r"[^a-z1-6 ]", " ", jp.lower()).split())
            out.append(Example(text.replace("#", "").strip(), jp, en))
    return out


def _from_row(row: dict) -> Sense:
    measure = re.sub(r"^（量詞：|）$", "", row.get("Measure_Word", "").strip())
    split = lambda v: [x.strip() for x in re.split(r"[、;；]", v) if x.strip()]
    s = Sense(term=row["Term"].strip(), altterm=row.get("Altterm", "").strip(),
              jyutping=row.get("Reading", "").strip(), pos=row.get("POS_Yue", "").strip(),
              labels=split(row.get("Labels_Yue", "")), zh=row.get("Definition_Yue", "").strip(),
              en=row.get("Definition_Eng", "").strip(), measure=measure,
              other_reading=row.get("Alt_Reading", "").strip(),
              examples=_examples(row.get("Examples", "")),
              synonyms=split(row.get("Synonyms", "")), antonyms=split(row.get("Antonyms", "")),
              reviewed=row.get("isReviewed") == "True")
    if not row.get("Explanation", "").strip():
        # A reading pointer: no meaning of its own, only another reading of the term.
        s.pos = s.zh = s.en = ""
    if s.examples:
        s.example, s.example_en = s.examples[0].yue, s.examples[0].en
    return s


def _read_csv(src) -> list[Sense]:
    csv.field_size_limit(1 << 30)
    out, seen = [], set()
    with open(src, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["Term"], row.get("Altterm"), row.get("Reading"), row.get("Alt_Reading"),
                   row.get("Explanation"), row.get("Examples"))
            if key in seen:          # the export repeats some rows verbatim
                continue
            seen.add(key)
            out.append(_from_row(row))
    return out


@lru_cache(maxsize=1)
def senses() -> list[Sense]:
    src = paths.get("dictionary")
    if src.suffix.lower() != ".csv":
        raise ValueError(f"the words.hk dictionary must be its CSV export (dictionaries/words.hk-ordered.csv), "
                         f"not {src.name}: check `dictionary` in config/paths.toml and paths.local.toml")
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
    data = _read_csv(src)
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


def show_example(e: Example) -> str:
    """One example on one line: the sentence, its Jyutping in brackets, its English."""
    out = e.yue
    if e.jyutping:
        out += f" [{e.jyutping}]"
    if e.en:
        out += f" ({e.en})"
    return out


@dataclass
class ExampleParticle:
    example: Example
    slot: object        # particles.Slot over the example as words.hk writes it
    run: str            # the run in CantoCaptions characters ("" when its tone is unknown)
    readings: list[str]

    def respelled(self) -> str:
        """The sentence with this run in CantoCaptions characters."""
        text = self.example.yue
        return text[:self.slot.start] + (self.run or self.slot.run) + text[self.slot.end:]


def _example_readings(e: Example) -> dict[int, str]:
    """Character index -> syllable, from the example's own Jyutping. Each CJK character is
    one syllable; a Latin word or a number has an unknown count, so past one the syllables
    are matched from the end of the sentence (where the particles are) back to it."""
    from .jyutping import is_cjk, is_sound
    syl = e.jyutping.split()
    if not syl:
        return {}
    cjk = [i for i, c in enumerate(e.yue) if is_cjk(c)]
    other = any(is_sound(c) and not is_cjk(c) for c in e.yue)
    if not other and len(cjk) == len(syl):
        return dict(zip(cjk, syl))
    out, k = {}, len(syl) - 1
    for i in range(len(e.yue) - 1, -1, -1):
        c = e.yue[i]
        if is_cjk(c):
            if k < 0:
                break
            out[i] = syl[k]
            k -= 1
        elif is_sound(c):
            break
    return out


@lru_cache(maxsize=1)
def _single_particle_readings() -> dict[str, str]:
    """words.hk spellings with exactly one particle reading (喇 laa3, 啦 laa1): the reading of
    that spelling in an example without Jyutping. Spellings with several (囉, 呀, 㗎) get none."""
    seen: dict[str, set[str]] = {}
    for s in senses():
        if "助詞" in s.pos and len(s.term) == 1 and RE_SYLLABLE.match(s.jyutping):
            seen.setdefault(s.term, set()).add(s.jyutping)
    return {t: next(iter(r)) for t, r in seen.items() if len(r) == 1}


@lru_cache(maxsize=1)
def example_particles() -> list[ExampleParticle]:
    """Every clause-final particle run in words.hk's example sentences, with its reading and
    its CantoCaptions spelling."""
    from .jyutping import particle_readings
    from .particles import slots
    by_reading = {r: c for c, r in particle_readings().items()}
    single = _single_particle_readings()
    out = []
    for s in senses():
        for e in s.examples:
            found = slots(e.yue)
            if not found:
                continue
            reads = _example_readings(e)
            for sl in found:
                rs = [reads.get(i) or single.get(e.yue[i], "") for i in range(sl.start, sl.end)]
                run = "".join(by_reading.get(r, "") for r in rs) if all(rs) else ""
                out.append(ExampleParticle(e, sl, run if len(run) == len(sl.run) else "", rs))
    return out


def particle_examples(trigger: str, options: list[str], limit: int = 4) -> dict:
    """words.hk example sentences whose clause matches *trigger* (a regex) and ends in one of
    *options* (particles or runs, in CantoCaptions characters), counted per option. Each
    example is shown with the particle re-spelled the CantoCaptions way, and words.hk's own
    spelling when it differs."""
    from .colloc import clause_text
    rx = re.compile(trigger)
    opts = sorted(options, key=len, reverse=True)
    counts: dict[str, int] = {}
    shown: dict[str, list[str]] = {}
    seen = set()
    for ep in example_particles():
        if not ep.run:
            continue
        opt = next((o for o in opts if ep.run.endswith(o)), None)
        if not opt or not rx.search(clause_text(ep.slot.clause)):
            continue
        key = (ep.example.yue, ep.slot.start)
        if key in seen:
            continue
        seen.add(key)
        counts[opt] = counts.get(opt, 0) + 1
        if len(shown.setdefault(opt, [])) < limit:
            line = show_example(Example(ep.respelled(), ep.example.jyutping, ep.example.en))
            if ep.slot.run != ep.run:
                line += f" — words.hk writes {ep.slot.run}"
            shown[opt].append(line)
    total = sum(counts.values())
    return {"total": total, "counts": [{"form": o, "count": counts[o], "examples": shown[o]}
                                       for o in sorted(counts, key=counts.get, reverse=True)]}


def particle_senses(jp: str, max_senses: int = 12, max_examples: int = 3) -> dict:
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
                             **({"examples": [show_example(e) for e in s.examples[:max_examples]]}
                                if s.examples else {})})
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
        out["parts"] = [particle_senses(s, 4, 1) for s in jp.split()]
    return out


def describe(term: str, max_senses: int = 4, max_examples: int = 2) -> dict:
    """A compact JSON-able summary of every sense of *term*."""
    found = lookup(term)
    readings = sorted({s.jyutping for s in found if s.jyutping} | {s.other_reading for s in found if s.other_reading})
    out = {"term": term, "found": bool(found), "jyutping": readings, "senses": []}
    for s in found:
        if not s.pos and not s.zh:      # a reading pointer: its reading is listed above
            continue
        sense = {"pos": s.pos, "labels": s.labels, "zh": s.zh, "en": s.en}
        if s.measure:
            sense["measure"] = s.measure
        if s.altterm and s.altterm != term:
            sense["alt"] = s.altterm
        if s.synonyms:
            sense["synonyms"] = s.synonyms[:6]
        if s.examples:
            sense["examples"] = [show_example(e) for e in s.examples[:max_examples]]
        out["senses"].append(sense)
    total = len(out["senses"])
    out["senses"] = out["senses"][:max_senses]
    if total > max_senses:
        out["more_senses"] = total - max_senses
    return out
