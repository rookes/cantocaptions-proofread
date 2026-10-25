"""Particle collocations: which phrases pull a clause toward one sentence-final particle.

Two kinds, both checked by `ccp particles`:

* **Mined** from the strict corpus (never looser tiers): for every clause that ends in a
  particle of a confusion set (config/particles.toml), each CJK substring of 1–3 characters
  in the clause is a feature (position-free, so 一定…喇 counts), and so are the last one and
  two characters before the particle, anchored (`就得$`). Questions (a `？` after the
  particle) and statements are counted apart as well as together: a question takes other
  particles whatever its words, so it is only compared with questions. A feature is kept when
  it occurs in enough clauses across enough shows. It is notable only when it shifts the
  choice: its particle well above that particle's usual rate (`min_lift`), and significantly
  so (a log-odds z-score with an informative Dirichlet prior). A common phrase that merely
  follows the base rate (唔… → 啊, as most clauses are) says nothing.
* **Recorded** in particles/collocations.toml: from the standards, the user, or an agent that
  found one deciding a line (`ccp particles note add`, status `proposed` until the user
  confirms it). A trigger may be any regex, so it can state what mining cannot see.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from . import corpus, paths
from .particles import config as pconfig, members, set_of, slots

CACHE_VERSION = 2
NOTES = paths.ROOT / "particles" / "collocations.toml"
_CJK = re.compile(r"[㐀-鿿\U00020000-\U0003134f]")
PRIOR = 50.0          # pseudo-count of the set's base rate added to every feature


@dataclass
class Clause:
    show: str
    where: str          # episode#cue
    text: str           # the clause before the particle, as written
    run: str            # its particle run
    question: bool = False


def clause_text(slot_clause: str) -> str:
    """A clause as triggers see it: no leading speaker dash, no surrounding spaces."""
    return slot_clause.strip().lstrip("-").strip()


def _features(text: str) -> set[str]:
    chars = "".join(_CJK.findall(text))
    feats = {chars[i:i + k] for k in (1, 2, 3) for i in range(len(chars) - k + 1)}
    feats |= {chars[-k:] + "$" for k in (1, 2) if len(chars) >= k}
    return feats


# --------------------------------------------------------------------------- mining

def _keys(name: str, question: bool) -> tuple[str, str]:
    """The tables a clause counts in: its set, and its set among questions or statements."""
    return name, _key(name, question)


def _key(name: str, question: bool | None) -> str:
    return name if question is None else f"{name}/{'q' if question else 's'}"


def _mine(tier: str, exclude: tuple[str, ...]) -> dict:
    lines = [ln for ln in corpus.lines(tier) if ln.show not in exclude]
    clauses: list[Clause] = []
    for ln in lines:
        for s in slots(ln.text):
            if set_of(s.last):
                clauses.append(Clause(ln.show, f"{ln.episode}#{ln.pos}", clause_text(s.clause), s.run,
                                      s.question))
    cfg = pconfig()["colloc"]
    counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    base: dict[str, Counter] = defaultdict(Counter)
    for c in clauses:
        p = c.run[-1]
        feats = _features(c.text)
        for name in _keys(set_of(p), c.question):
            base[name][p] += 1
            for f in feats:
                counts[name][f][p] += 1
    keep = {name: {f for f, d in feats.items() if sum(d.values()) >= cfg["min_clauses"]}
            for name, feats in counts.items()}
    shows: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for c in clauses:
        feats = _features(c.text)
        for name in _keys(set_of(c.run[-1]), c.question):
            for f in feats & keep[name]:
                shows[name][f].add(c.show)
    features = {name: {f: {"n": sum(counts[name][f].values()), "shows": len(shows[name][f]),
                           "dist": dict(counts[name][f])}
                       for f in keep[name] if len(shows[name][f]) >= cfg["min_shows"]}
                for name in keep}
    return {"base": {k: dict(v) for k, v in base.items()}, "features": features, "clauses": clauses}


@lru_cache(maxsize=4)
def mined(tier: str = "strict", exclude: tuple[str, ...] = ()) -> dict:
    """The mined table (cached under cache/), or empty tables without a corpus."""
    lines = corpus.lines(tier)
    if not lines:
        return {"base": {}, "features": {}, "clauses": []}
    stamp = (CACHE_VERSION, tier, exclude, len(lines), sum(len(ln.text) for ln in lines),
             json.dumps(pconfig()["sets"], ensure_ascii=False), json.dumps(pconfig()["colloc"]))
    suffix = "_x" + hashlib.sha1("|".join(exclude).encode()).hexdigest()[:10] if exclude else ""
    cache = paths.cache_dir() / f"colloc_{tier}{suffix}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as f:
                stored, data = pickle.load(f)
            if stored == stamp:
                return data
        except Exception:
            pass
    data = _mine(tier, exclude)
    with cache.open("wb") as f:
        pickle.dump((stamp, data), f, protocol=pickle.HIGHEST_PROTOCOL)
    return data


def z_score(dist: dict[str, int], base: dict[str, int], p: str) -> float:
    """How much more often *p* ends the feature's clauses than the set's base rate predicts:
    log-odds ratio with an informative Dirichlet prior, divided by its standard error."""
    total_b = sum(base.values())
    if not total_b:
        return 0.0
    a = PRIOR * base.get(p, 0) / total_b + 0.01
    n, y, b = sum(dist.values()), dist.get(p, 0), base.get(p, 0)
    delta = (math.log((y + a) / (n + PRIOR - y - a + 1e-9))
             - math.log((b + a) / (total_b + PRIOR - b - a + 1e-9)))
    return delta / math.sqrt(1 / (y + a) + 1 / (b + a))


@dataclass
class Pull:
    feature: str        # 一定, 就得$
    set: str
    n: int              # clauses with the feature
    shows: int
    dist: dict[str, int]
    best: str           # the particle it favours most
    z: float            # how strongly
    share: float        # the best particle's share of the feature's clauses
    base: dict[str, int] = field(default_factory=dict)   # the set's counts over all its clauses

    def share_of(self, p: str) -> float:
        return self.dist.get(p, 0) / self.n if self.n else 0.0

    def base_share(self, p: str) -> float:
        total = sum(self.base.values())
        return self.base.get(p, 0) / total if total else 0.0

    @property
    def lift(self) -> float:
        """How many times its usual rate the favoured particle ends these clauses."""
        b = self.base_share(self.best)
        return self.share / b if b else 0.0


def _pull(feature: str, name: str, row: dict, base: dict) -> Pull:
    # The particle the feature's clauses mostly end with, and how far above its usual rate:
    # a rare particle's z can be high on a few clauses, but it does not pull the clause.
    best = max(row["dist"], key=row["dist"].get)
    return Pull(feature, name, row["n"], row["shows"], row["dist"], best,
                z_score(row["dist"], base, best), row["dist"][best] / row["n"], base)


def _notable(p: Pull) -> bool:
    cfg = pconfig()["colloc"]
    return p.z >= cfg["min_z"] and p.lift >= cfg["min_lift"]


def pulls(clause: str, particle: str, question: bool | None = None, tier: str = "strict", top: int = 3,
          exclude: tuple[str, ...] = ()) -> list[Pull]:
    """The mined features present in *clause* that shift the choice within *particle*'s set,
    strongest first: among questions or statements when *question* says which the clause is."""
    name = _key(set_of(particle), question)
    data = mined(tier, exclude)
    feats = data["features"].get(name, {})
    base = data["base"].get(name, {})
    found = [_pull(f, name, feats[f], base) for f in _features(clause_text(clause)) if f in feats]
    return _distinct([p for p in found if _notable(p)])[:top]


def _distinct(found: list[Pull]) -> list[Pull]:
    """Strongest first, one per idea: overlapping features with the same pull (已 / 已經 / 經)
    say one thing, so keep the stronger, or the longer when it is nearly as strong (it reads
    better)."""
    found = sorted(found, key=lambda p: -p.z)
    out: list[Pull] = []
    for p in found:
        core = p.feature.rstrip("$")
        same = next((q for q in out if q.best == p.best
                     and (core in q.feature.rstrip("$") or q.feature.rstrip("$") in core)), None)
        if same is None:
            out.append(p)
        elif len(core) > len(same.feature.rstrip("$")) and p.z >= 0.9 * same.z:
            out[out.index(same)] = p
    return out


def against(clause: str, particle: str, question: bool | None = None, tier: str = "strict",
            exclude: tuple[str, ...] = ()) -> Pull | None:
    """A mined collocation that counts against *particle* in *clause*: notable, frequent,
    spread over shows, with another particle dominant and this one rare, and rarer than usual;
    and no other phrase in the clause pulling toward this particle."""
    cfg = pconfig()["colloc"]
    found = pulls(clause, particle, question, tier, top=5, exclude=exclude)
    if any(p.best == particle for p in found):
        return None
    for p in found:
        mine = p.share_of(particle)
        if (p.best != particle and p.share >= cfg["other_share"] and mine <= cfg["draft_share"]
                and mine <= p.base_share(particle) / 2):
            return p
    return None


def top(particle: str, vs: str | None = None, tier: str = "strict", n: int = 20) -> list[Pull]:
    """The mined features that most favour *particle* (over *vs* only, when given)."""
    name = set_of(particle)
    data = mined(tier)
    feats, base = data["features"].get(name, {}), data["base"].get(name, {})
    keep = {particle, vs} if vs else None
    if keep:
        base = {p: c for p, c in base.items() if p in keep}
    out = []
    for f, row in feats.items():
        dist = {p: c for p, c in row["dist"].items() if keep is None or p in keep}
        if not dist.get(particle) or sum(dist.values()) < pconfig()["colloc"]["min_clauses"]:
            continue
        total = sum(dist.values())
        pull = Pull(f, name, total, row["shows"], dist, particle, z_score(dist, base, particle),
                    dist[particle] / total, base)
        if _notable(pull):
            out.append(pull)
    return _distinct(out)[:n]


# --------------------------------------------------------------------------- recorded notes

@dataclass
class Note:
    trigger: str
    among: str
    note: str
    prefer: str = ""
    source: str = "guide"
    status: str = "confirmed"
    added: str = ""
    examples: list[str] = field(default_factory=list)

    @property
    def options(self) -> list[str]:
        """The competing particles or runs, longest first."""
        opts = self.among.split("|") if "|" in self.among else list(members(self.among))
        return sorted(opts, key=len, reverse=True)

    def applies(self, clause: str, run: str) -> bool:
        return (any(run.endswith(o) for o in self.options)
                and re.search(self.trigger, clause_text(clause)) is not None)

    def wants_other(self, run: str) -> bool:
        return bool(self.prefer) and not run.endswith(self.prefer)


def notes() -> list[Note]:
    if not NOTES.is_file():
        return []
    return [Note(**{k: v for k, v in e.items() if k in Note.__dataclass_fields__})
            for e in tomllib.loads(NOTES.read_text(encoding="utf-8")).get("colloc", [])]


def notes_for(clause: str, run: str) -> list[Note]:
    return [n for n in notes() if n.applies(clause, run)]


def search_notes(text: str) -> list[Note]:
    """Recorded notes whose trigger matches *text*, or that mention it."""
    out = []
    for n in notes():
        try:
            hit = re.search(n.trigger, text) is not None
        except re.error:
            hit = False
        if hit or text in n.trigger or text in n.note:
            out.append(n)
    return out


def note_counts(trigger: str, among: str, tier: str = "strict", examples: int = 2) -> dict:
    """How the strict corpus ends the clauses *trigger* matches, among *among*."""
    probe = Note(trigger, among, "")
    counts: Counter = Counter()
    ex: dict[str, list[str]] = defaultdict(list)
    for c in mined(tier)["clauses"]:
        opt = next((o for o in probe.options if c.run.endswith(o)), None)
        if opt and re.search(trigger, c.text):
            counts[opt] += 1
            if len(ex[opt]) < examples:
                ex[opt].append(f"{c.where}  {c.text}{c.run}")
    total = sum(counts.values())
    return {"total": total, "counts": [{"form": f, "count": k, "share": round(k / total, 3),
                                        "examples": ex[f]} for f, k in counts.most_common()]}


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _dump(entries: list[Note]) -> str:
    text = NOTES.read_text(encoding="utf-8") if NOTES.is_file() else ""
    head = text.split("[[colloc]]", 1)[0].rstrip() + "\n"
    blocks = []
    for n in entries:
        lines = ["[[colloc]]", f"trigger = {_toml_str(n.trigger)}", f"among = {_toml_str(n.among)}"]
        if n.prefer:
            lines.append(f"prefer = {_toml_str(n.prefer)}")
        lines += [f"note = {_toml_str(n.note)}", f"source = {_toml_str(n.source)}",
                  f"status = {_toml_str(n.status)}", f"added = {_toml_str(n.added)}"]
        if n.examples:
            lines.append("examples = [" + ", ".join(_toml_str(e) for e in n.examples) + "]")
        blocks.append("\n".join(lines))
    return head + "\n" + "\n\n".join(blocks) + "\n"


def add_note(trigger: str, among: str, note: str, prefer: str = "", source: str = "agent",
             examples: list[str] | None = None) -> dict:
    """Record a collocation (status `proposed`), or update a proposed one with the same
    trigger and set. Confirmed entries are the user's: they are not changed here."""
    try:
        re.compile(trigger)
    except re.error as e:
        raise ValueError(f"trigger is not a valid regex: {e}") from None
    probe = Note(trigger, among, note, prefer)
    from .corpus import FINAL_PARTICLES
    if not probe.options or any(not o or any(c not in FINAL_PARTICLES for c in o) for o in probe.options):
        raise ValueError("among must be a set name (laa, aa, gaa, ze, wo, le) or particles separated by |")
    if prefer and prefer not in probe.options:
        raise ValueError(f"prefer {prefer!r} is not one of among ({'|'.join(probe.options)})")
    if not note.strip():
        raise ValueError("note is required: what the choice means, citing the standards section")
    entries = notes()
    same = next((n for n in entries if n.trigger == trigger and n.among == among), None)
    if same and same.status == "confirmed":
        return {"recorded": False, "reason": "already recorded and confirmed", "entry": same.__dict__,
                "corpus": note_counts(trigger, among)}
    if same:
        same.note, same.prefer, same.source = note, prefer, source
        same.examples = list(dict.fromkeys(same.examples + (examples or [])))
        entry, action = same, "updated"
    else:
        entry = Note(trigger, among, note, prefer, source, "proposed", date.today().isoformat(),
                     list(examples or []))
        entries.append(entry)
        action = "added"
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    NOTES.write_text(_dump(entries), encoding="utf-8")
    return {"recorded": True, "action": action, "entry": entry.__dict__, "corpus": note_counts(trigger, among)}
