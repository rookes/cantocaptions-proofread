"""The standardized part of CantoCaptions as searchable evidence.

Only episodes cantocaptions-dataset's `stdcheck` tiers as `strict` are indexed by default
(`data/std/episodes.json`). Everything else in CantoCaptions -- AI-generated trees, WIP,
loosely standardized files -- is never searched unless a looser tier is asked for
explicitly, so a count here is evidence of what the *standard* writes.

Without the dataset's tiers (or without the library) there is no corpus at all: untiered
files are never searched in its place, since a count over them is no evidence of the
standard. `available()` says which; `ccp corpus` then answers "unavailable".
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from . import jyutping, paths
from .srtio import SrtFile

TIER_ORDER = ["strict", "standard", "loose", "nonstandard", "unknown"]
CACHE_VERSION = 1

# Every sentence-final particle in the CantoCaptions syllable/tone tables.
FINAL_PARTICLES = set(
    "吖嗄啊呀咓𠻺𡅅噃𠺢𠿪㗎嘎㗇噶𠺝𠸏嘅啩吓嚱嗬啦𠸎喇嗱嚹嘞呢咧哩囖咯囉嚛嚕嘛嗎咩𠻹哇喎啝𡁜吒咋喳𠾵咤啫唧")
# Particle families (same syllable, different tone/meaning) for colloc(among=...).
PARTICLE_SETS = {
    "aa": "吖嗄啊呀咓𠻺", "gaa": "𠺢𠿪㗎嘎㗇噶", "ge": "𠸏嘅", "laa": "啦𠸎喇嗱嘞嚹",
    "lo": "囖咯囉", "wo": "喎啝𡁜", "zaa": "吒咋喳𠾵咤", "ze": "啫唧", "gam": "噉咁",
}
CLAUSE_END = set("，。？！…,?!；;：:」』）)\n-")


@dataclass
class Line:
    episode: str
    show: str
    pos: int          # 1-based cue position in its file
    text: str


def episodes_file():
    return paths.get("dataset") / "data" / "std" / "episodes.json"


UNAVAILABLE = ("the standardized corpus needs cantocaptions-dataset's quality tiers "
               "(data/std/episodes.json) and the CantoCaptions library; one is missing (see `ccp setup`)")


def available() -> bool:
    return episodes_file().is_file() and paths.has("subtitles")


@lru_cache(maxsize=1)
def episodes() -> dict:
    """episode_id -> tier record, or {} without the dataset."""
    f = episodes_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def allowed_tiers(tier: str) -> list[str]:
    if tier not in TIER_ORDER:
        raise ValueError(f"unknown tier {tier!r}; one of {TIER_ORDER}")
    return TIER_ORDER[:TIER_ORDER.index(tier) + 1]


@lru_cache(maxsize=4)
def lines(tier: str = "strict") -> list[Line]:
    tiers = set(allowed_tiers(tier))
    if not available():
        return []
    root = paths.get("subtitles")
    chosen = sorted((eid, rec) for eid, rec in episodes().items() if rec.get("tier") in tiers)
    stamp = hashlib.sha1()
    for eid, rec in chosen:
        p = root / rec["srt_path"]
        st = p.stat() if p.exists() else None
        stamp.update(f"{eid}|{st.st_size if st else 0}|{int(st.st_mtime) if st else 0}\n".encode())
    key = (CACHE_VERSION, tier, stamp.hexdigest())
    cache = paths.cache_dir() / f"corpus_{tier}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as f:
                stored, data = pickle.load(f)
            if stored == key:
                return data
        except Exception:
            pass
    out: list[Line] = []
    for eid, rec in chosen:
        p = root / rec["srt_path"]
        if not p.exists():
            continue
        try:
            cues = SrtFile(p).cues
        except Exception:
            continue
        show = rec.get("show_slug", eid.split("_")[0])
        out.extend(Line(eid, show, c.pos, c.text) for c in cues if c.text)
    with cache.open("wb") as f:
        pickle.dump((key, out), f, protocol=pickle.HIGHEST_PROTOCOL)
    return out


def _select(tier: str, show: str | None) -> list[Line]:
    data = lines(tier)
    if show:
        data = [ln for ln in data if ln.show == show or ln.show.startswith(show)]
    return data


def search(pattern: str, tier: str = "strict", show: str | None = None,
           examples: int = 10, context: int = 0) -> dict:
    """Matching lines with counts. With *context* > 0 each example also carries that many
    neighbouring cues on each side (same episode only), marked with the hit as `>`."""
    rx = re.compile(pattern)
    data = _select(tier, show)
    hits, occurrences = [], 0
    by_show: Counter = Counter()
    for i, ln in enumerate(data):
        found = rx.findall(ln.text)
        if found:
            occurrences += len(found)
            hits.append(i)
            by_show[ln.show] += 1
    # Spread examples across episodes rather than taking the first N of one file.
    picked, seen_eps = [], Counter()
    for i in hits:
        ln = data[i]
        if seen_eps[ln.episode] < 2 and len(picked) < examples:
            picked.append(i)
            seen_eps[ln.episode] += 1
    fmt = lambda ln: ln.text.replace(chr(10), " ⏎ ")
    if context > 0:
        ex = []
        for i in picked:
            ln = data[i]
            block = [f"{ln.episode}#{ln.pos}"]
            for j in range(i - context, i + context + 1):
                if 0 <= j < len(data) and data[j].episode == ln.episode:
                    block.append(f"{'>' if j == i else ' '} {data[j].pos}  {fmt(data[j])}")
            ex.append(block)
    else:
        ex = [f"{data[i].episode}#{data[i].pos}  {fmt(data[i])}" for i in picked]
    return {
        "pattern": pattern, "tier": tier, "show": show, "lines_searched": len(data),
        "matching_lines": len(hits), "occurrences": occurrences,
        "by_show": dict(by_show.most_common(8)),
        "examples": ex,
    }


def _final_run(text: str, start: int, window: int) -> str | None:
    """The clause-final particle run of the clause that continues at *start*, or None if
    the clause does not end in particles (or runs longer than *window* characters)."""
    # A comma (or any clause punctuation) ends the clause, so in 一定佢未死喇，梗係唔會啦 the
    # particle that goes with 一定 is 喇, not the 啦 of the next clause. A line break ends it
    # only when the next line is another speaker ("-"); otherwise it is a wrapped sentence.
    j = start
    while j < len(text) and j - start <= window:
        ch = text[j]
        if ch == "\n":
            if text[j + 1:j + 2] == "-":
                break
        elif ch in CLAUSE_END:
            break
        j += 1
    if j - start > window:
        return None
    k = j
    while k > start and text[k - 1] in FINAL_PARTICLES | {"\n"}:
        k -= 1
    run = text[k:j].replace("\n", "")
    return run or "∅"


def colloc(phrase: str, mode: str = "final", tier: str = "strict", show: str | None = None,
           window: int = 8, n: int = 2, examples: int = 3, among: str = "") -> dict:
    """Collocation statistics for *phrase* (a regex).

    final: which clause-final particle run ends the clause the phrase is in (∅ = none).
           With *among* (a set name from PARTICLE_SETS such as "laa", or literal characters
           such as "喇啦"), count only the last member of that set in the run, so 一定…喇
           and 一定…㗎喇 both count as 喇 and clauses without the family are skipped.
    next / prev: the *n* sound characters that follow / precede the phrase.
    """
    rx = re.compile(phrase)
    members = PARTICLE_SETS.get(among, among)
    counts: Counter = Counter()
    ex: dict[str, list[str]] = defaultdict(list)
    for ln in _select(tier, show):
        for m in rx.finditer(ln.text):
            if mode == "final":
                key = _final_run(ln.text, m.end(), window)
                if key is None:
                    continue
                if members:
                    inside = [ch for ch in key if ch in members]
                    if not inside:
                        continue
                    key = inside[-1]
            elif mode == "next":
                tail = re.split(r"[，。？！…,?!\n]", ln.text[m.end():], maxsplit=1)[0]
                key = "".join(c for c in tail if jyutping.is_sound(c))[:n] or "∅"
            elif mode == "prev":
                head = re.split(r"[，。？！…,?!\n]", ln.text[:m.start()])[-1]
                key = "".join(c for c in head if jyutping.is_sound(c))[-n:] or "∅"
            else:
                raise ValueError(mode)
            counts[key] += 1
            if len(ex[key]) < examples:
                ex[key].append(f"{ln.episode}#{ln.pos}  {ln.text.replace(chr(10), ' ⏎ ')}")
    total = sum(counts.values())
    return {
        "phrase": phrase, "mode": mode, "among": members, "tier": tier, "show": show, "total": total,
        "counts": [{"form": k, "count": v, "share": round(v / total, 3) if total else 0,
                    "examples": ex[k]} for k, v in counts.most_common(15)],
    }


def compare(forms: list[str], tier: str = "strict", show: str | None = None) -> dict:
    """Occurrence counts of competing literal forms (e.g. 得㗎喇 vs 得㗎啦)."""
    data = _select(tier, show)
    out = []
    for f in forms:
        c = sum(ln.text.count(f) for ln in data)
        out.append({"form": f, "count": c})
    total = sum(o["count"] for o in out)
    for o in out:
        o["share"] = round(o["count"] / total, 3) if total else 0
    return {"tier": tier, "show": show, "forms": out}


def count(term: str, tier: str = "strict") -> int:
    return sum(ln.text.count(term) for ln in lines(tier))


@lru_cache(maxsize=8)
def ngram_vocab(tier: str = "strict", show: str | None = None, min_count: int = 3,
                sizes: tuple[int, ...] = (2, 3, 4)) -> dict[str, set[str]]:
    """Frequent CJK n-grams of the corpus with their (most common) Jyutping. Names and set
    phrases that words.hk lacks (帕克, 菜月昴) come from here."""
    counts: Counter = Counter()
    for ln in _select(tier, show):
        for run in re.findall(r"[㐀-鿿\U00020000-\U0003134f]+", ln.text):
            for size in sizes:
                for i in range(len(run) - size + 1):
                    counts[run[i:i + size]] += 1
    vocab: dict[str, set[str]] = {}
    for gram, c in counts.items():
        if c < min_count or gram[-1] in FINAL_PARTICLES:
            continue
        syl = [jyutping.reading(ch) for ch in gram]
        if all(syl):
            vocab[gram] = {" ".join(syl)}
    return vocab
