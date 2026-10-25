"""Clause-final particles in a cue ("slots") and the particles that could replace them.

A slot is one run of sentence-final particles directly before a clause boundary or the end
of the cue: the 喇 of 走喇，, the 㗎喇 of 得㗎喇. Its *clause* is the text from the previous
clause boundary up to the run; a comma ends a clause, and a line break only before another
speaker's `-` line (otherwise it is a wrapped sentence). The candidates for a slot come from
config/particles.toml: the particle's confusion set, its question form, a few cross-set
pairs, and whole compound runs.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache

from . import jyutping, paths
from .corpus import CLAUSE_END, FINAL_PARTICLES

# What may directly follow a clause-final particle run.
BOUNDARY = set("，。？！…,.?!；;：:、」』）) \n")
QUESTION_MARKS = set("？?")


def final_mask(text: str) -> list[bool]:
    """True for each character in a clause-final particle run (particles directly before a
    clause boundary or the end of the line): the 𠸏 of 唔痛𠸏, both of 㗎唧 in 判畀佢哋㗎唧？
    Not the 嘅 of 你哋嘅Sa姨 or the 啊 of 殺啊人."""
    mask = [False] * len(text)
    for i in range(len(text) - 1, -1, -1):
        nxt_ok = i + 1 == len(text) or text[i + 1] in BOUNDARY or mask[i + 1]
        mask[i] = text[i] in FINAL_PARTICLES and nxt_ok
    return mask


@dataclass
class Slot:
    index: int          # 0-based, in the order the slots appear in the cue
    start: int          # the run's span in the cue text
    end: int
    run: str            # 喇, 㗎喇
    clause: str         # the clause before the run, punctuation included
    after: str          # the punctuation right after the run ("" at the end of the cue)

    @property
    def last(self) -> str:
        return self.run[-1]

    @property
    def readings(self) -> list[str]:
        return [jyutping.reading(c) or "?" for c in self.run]

    @property
    def question(self) -> bool:
        return self.after[:1] in QUESTION_MARKS


def _clause_start(text: str, end: int) -> int:
    i = end
    while i > 0:
        ch = text[i - 1]
        if ch == "\n":
            if text[i:i + 1] == "-":
                break
        elif ch in CLAUSE_END:
            break
        i -= 1
    return i


def slots(text: str) -> list[Slot]:
    mask = final_mask(text)
    out, i = [], 0
    while i < len(text):
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < len(text) and mask[j]:
            j += 1
        start = _clause_start(text, i)
        k = j
        while k < len(text) and text[k] in BOUNDARY - {"\n", " "}:
            k += 1
        if start < i:       # a particle alone (呀？) is an interjection, not a slot
            out.append(Slot(len(out), i, j, text[i:j], text[start:i], text[j:k]))
        i = j
    return out


@lru_cache(maxsize=1)
def config() -> dict:
    return tomllib.loads((paths.CONFIG / "particles.toml").read_text(encoding="utf-8"))


def set_of(ch: str) -> str | None:
    """The confusion set a particle belongs to (laa, aa, gaa…), or None."""
    return next((name for name, members in config()["sets"].items() if ch in members), None)


def members(among: str) -> str:
    """A set name (laa) or literal particle characters (喇啦), as characters."""
    return config()["sets"].get(among, among)


def alternatives(run: str) -> list[str]:
    """Runs that could replace *run*: the whole run from its compound group, then the last
    particle swapped within its set, for its question or statement form, and its cross-set
    pairs. The draft's own run is not included."""
    cfg = config()
    out: list[str] = []

    def add(r: str) -> None:
        if r != run and r not in out:
            out.append(r)

    for group in cfg.get("compounds", {}).values():
        if run in group:
            for r in group:
                add(r)
    head, last = run[:-1], run[-1]
    for ch in cfg["sets"].get(set_of(last) or "", ""):
        add(head + ch)
    q = cfg.get("question", {})
    for stmt, ques in q.items():
        if last == stmt:
            add(head + ques)
        elif last == ques:
            add(head + stmt)
    for a, b in cfg.get("pairs", {}).items():
        if last == a:
            add(head + b)
        elif last == b:
            add(head + a)
    return out[:cfg["candidates"]["max"]]


def swap(text: str, slot: Slot, run: str) -> str:
    return text[:slot.start] + run + text[slot.end:]


def candidates(text: str, slot: Slot) -> list[tuple[str, str]]:
    """[(run, full cue text)] for the draft's run first, then each alternative."""
    return [(slot.run, text)] + [(r, swap(text, slot, r)) for r in alternatives(slot.run)]


# --------------------------------------------------------------------------- model scoring

TERMINAL = set("，。？！…,?!；;：:")


def model_text(texts: list[str]) -> tuple[str, list[dict[int, int]]]:
    """Cue texts written the way the fine-tuned recogniser writes a stretch of speech: no line
    breaks or speaker dashes, a wrapped line run on, and a comma between cues and speakers
    unless one already ends in punctuation (as the dataset joins them for training). Returns
    the text and, per cue, its character index -> index in the joined text."""
    out: list[str] = []
    maps: list[dict[int, int]] = []

    def sep():
        if out and out[-1] not in TERMINAL:
            out.append("，")

    for t in texts:
        m: dict[int, int] = {}
        lines = t.split("\n")
        pos = 0
        for li, line in enumerate(lines):
            start = pos
            pos += len(line) + 1
            dash = line.startswith("-")
            if li == 0 or dash:
                sep()
            k = 1 if dash else 0
            for j in range(k, len(line)):
                m[start + j] = len(out)
                out.append(line[j])
        maps.append(m)
    return "".join(out), maps


def group_items(cues: list, groups: list) -> list[dict]:
    """One scoring request per group that has particles: the group's model-style text, its
    padded span, and each slot of each cue with its alternatives (`spots`, in the joined
    text's indices, with the cue and slot they came from)."""
    items = []
    for g in groups:
        group_cues = [cues[p - 1] for p in g.cues]
        text, maps = model_text([c.text for c in group_cues])
        spots = []
        for c, m in zip(group_cues, maps):
            for s in slots(c.text):
                alts = alternatives(s.run)
                if not alts or s.start not in m or s.end - 1 not in m:
                    continue
                spots.append({"start": m[s.start], "end": m[s.end - 1] + 1, "alts": alts,
                              "cue": c.pos, "slot": s.index, "run": s.run})
        if spots:
            items.append({"key": g.index, "start": g.start, "end": g.end, "text": text, "spots": spots})
    return items
