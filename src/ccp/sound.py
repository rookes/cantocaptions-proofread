"""Weighted Jyutping distance and the sounds-like search.

A misheard span keeps much of its sound: 食多都亂 (sik6 do1 dou1 lyun1) was really
實囉囉攣 (sat6 lo1 lo1 lyun1), with every tone intact. `search` ranks dictionary words
(and optionally strict-corpus n-grams) by how closely they sound like the suspect span,
under *several* hypotheses at once (the draft and each ASR's text), using every reading of
every character and the confusion costs in config/confusions.toml.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations

from . import jyutping, paths

_INITIALS = sorted(["b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "ng", "h", "gw", "kw",
                    "w", "z", "c", "s", "j"], key=len, reverse=True)
_VOWELS = ("aa", "a", "oe", "eo", "e", "i", "o", "u", "yu")


def split(syl: str) -> tuple[str, str, str]:
    """('gw', 'aa', '3'); syllabic m/ng keep an empty initial."""
    tone = syl[-1] if syl and syl[-1].isdigit() else ""
    body = syl[:-1] if tone else syl
    if body in ("m", "ng"):
        return "", body, tone
    for ini in _INITIALS:
        if body.startswith(ini) and len(body) > len(ini):
            return ini, body[len(ini):], tone
    return "", body, tone


def _nucleus_coda(final: str) -> tuple[str, str]:
    for v in _VOWELS:
        if final.startswith(v):
            return v, final[len(v):]
    return final, ""


@lru_cache(maxsize=1)
def config() -> dict:
    cfg = tomllib.loads((paths.CONFIG / "confusions.toml").read_text(encoding="utf-8"))
    pairs = {}
    for part in ("initial", "final", "tone"):
        table: dict[tuple[str, str], float] = {}
        for entry in cfg.get(part, []):
            for a, b in combinations(entry["set"], 2):
                key = tuple(sorted((a, b)))
                table[key] = min(table.get(key, 1.0), float(entry["cost"]))
        pairs[part] = table
    return {"weights": cfg["weights"], "fallback": cfg["fallback"], "pairs": pairs}


def _part_cost(part: str, a: str, b: str) -> float:
    if a == b:
        return 0.0
    c = config()["pairs"][part].get(tuple(sorted((a, b))))
    if c is not None:
        return c
    if part == "final":
        fb = config()["fallback"]
        if a.replace("aa", "a") == b.replace("aa", "a"):
            return fb["a_aa"]
        (na, ca), (nb, cb) = _nucleus_coda(a), _nucleus_coda(b)
        if na.replace("aa", "a") == nb.replace("aa", "a"):
            if ca in ("p", "t", "k") and cb in ("p", "t", "k"):
                return fb["same_nucleus_stop"]
            if ca in ("m", "n", "ng") and cb in ("m", "n", "ng"):
                return fb["same_nucleus_nasal"]
            return fb["same_nucleus"]
    return 1.0


@lru_cache(maxsize=200_000)
def syllable_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    w = config()["weights"]
    ia, fa, ta = split(a)
    ib, fb, tb = split(b)
    return round(w["initial"] * _part_cost("initial", ia, ib)
                 + w["final"] * _part_cost("final", fa, fb)
                 + w["tone"] * _part_cost("tone", ta, tb), 4)


def position_cost(options: tuple[str, ...], syl: str) -> float:
    """Cost of a query position (a char with several readings) against one syllable."""
    if not options:
        return 0.8          # unknown reading: neither a match nor a full mismatch
    return min(syllable_cost(o, syl) for o in options)


def align(query: list[tuple[str, ...]], term: list[str]) -> tuple[float, int, int]:
    """Semi-global alignment: every syllable of *term* is used; the query may be skipped at
    either end (cheaply), so a word can match part of a wider suspect span.
    Returns (cost, query_start, query_end)."""
    w = config()["weights"]
    indel, skip = w["indel"], w["skip"]
    n, m = len(query), len(term)
    # D[i][j]: term[:i] aligned ending at query[:j]; S tracks where the match started.
    prev = [j * skip for j in range(n + 1)]
    prev_start = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [prev[0] + indel] + [0.0] * n
        cur_start = [0] + [0] * n
        t = term[i - 1]
        for j in range(1, n + 1):
            sub = prev[j - 1] + position_cost(query[j - 1], t)
            dele = prev[j] + indel            # term syllable with no query syllable
            ins = cur[j - 1] + indel          # query syllable inside the match, unmatched
            best = min(sub, dele, ins)
            cur[j] = best
            cur_start[j] = (prev_start[j - 1] if best == sub
                            else prev_start[j] if best == dele else cur_start[j - 1])
        prev, prev_start = cur, cur_start
    best_j = min(range(n + 1), key=lambda j: prev[j] + (n - j) * skip)
    return prev[best_j] + (n - best_j) * skip, prev_start[best_j], best_j


def query_of(text: str) -> tuple[list[tuple[str, ...]], list[str]]:
    """(per-position reading options, the CJK chars) for a hypothesis text."""
    pairs = jyutping.text_readings(text)
    return [tuple(r) for _, r in pairs], [c for c, _ in pairs]


def span_distance(a: str, b: str) -> float:
    """Normalised sound distance between two texts (0 same, ~1 unrelated)."""
    qa, _ = query_of(a)
    qb, _ = query_of(b)
    if not qa or not qb:
        return 1.0
    best = 1e9
    for syls in _expansions(qb):
        cost, _, _ = align(qa, syls)
        best = min(best, cost)
    return round(best / max(len(qa), len(qb)), 3)


def _expansions(q: list[tuple[str, ...]], limit: int = 16) -> list[list[str]]:
    """A few concrete syllable sequences for a multi-reading text (most common first)."""
    seqs = [[]]
    for opts in q:
        opts = opts or ("?",)
        seqs = [s + [o] for s in seqs for o in opts[:2]][:limit]
    return seqs


def plain_distance(cost: float) -> str:
    """A match's per-syllable distance as words, for records a reviewer reads (results come
    ranked, closest first, so the number itself is never needed)."""
    if cost <= 0.0:
        return "the same sounds"
    if cost < 0.15:
        return "almost the same"
    if cost < 0.35:
        return "close"
    return "loosely similar"


@dataclass
class Match:
    term: str
    jyutping: str
    score: float                         # combined, normalised (lower is closer)
    per_hyp: list[float] = field(default_factory=list)
    span: tuple[int, int] = (0, 0)       # matched span of the primary query, char indexes
    replaced: str = ""                   # primary text with the span replaced by the term
    source: str = "dict"
    in_hyp: list[int] = field(default_factory=list)   # hypotheses that already contain the term verbatim


def search(primary: str, hyps: list[str] = (), n: int = 20, min_len: int | None = None,
           max_len: int | None = None, vocab: dict[str, set[str]] | None = None,
           source: str = "dict") -> list[Match]:
    """Rank *vocab* terms (default: words.hk) by sound against *primary* and *hyps*."""
    if vocab is None:
        from . import dictionary
        vocab = dictionary.term_readings()
    queries = [query_of(t) for t in [primary, *hyps] if t]
    queries = [q for q in queries if q[0]]
    if not queries:
        return []
    q0, chars0 = queries[0]
    longest = max(len(q) for q, _ in queries)
    lo = min_len if min_len is not None else max(1, min(len(q) for q, _ in queries) - 2)
    hi = max_len if max_len is not None else longest + 1
    cleaned = "".join(chars0)
    texts = ["".join(c) for _, c in queries]
    results: list[Match] = []
    for term, jps in vocab.items():
        for jp in jps:
            syl = jp.split()
            if not lo <= len(syl) <= hi:
                continue
            per = []
            span0 = (0, 0)
            for k, (q, _) in enumerate(queries):
                cost, s, e = align(q, syl)
                per.append(cost / max(len(syl), 1))
                if k == 0:
                    span0 = (s, e)
            score = 0.5 * min(per) + 0.5 * (sum(per) / len(per))
            results.append(Match(term, jp, round(score, 3), [round(p, 3) for p in per], span0,
                                 cleaned[:span0[0]] + term + cleaned[span0[1]:], source,
                                 [k for k, t in enumerate(texts) if term in t]))
    results.sort(key=lambda m: (m.score, -len(m.term)))
    seen, out = set(), []
    for r in results:
        if r.term in seen:
            continue
        seen.add(r.term)
        out.append(r)
        if len(out) >= n:
            break
    return out
