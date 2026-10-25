"""`ccp particles scan`: every clause-final particle of a draft, with what each source says.

For each slot (particles.slots) of each cue:

* **the standards**: the particle's reading and one-line meaning (guide.convention);
* **force**: whether the line asks and whether its reference line (`R`) does;
* **the fine-tuned recogniser** (work/<id>/particle_model.jsonl, from `ccp evidence` or
  `ccp particles model`): how much more likely it finds another particle there;
* **collocations**: recorded ones (particles/collocations.toml) and mined strict-corpus ones;
* **form checks**: a tone-4 question particle without `？`, or a question with no question
  word ending in a statement particle that has a question form;
* the recognisers' own particles in the cue, shown but never a reason: they insert, drop
  and swap particles freely (AGENTS.md principle 4).

A slot is a suspect when the model clearly or leaningly prefers another particle, a
collocation counts against it, its force differs from `R`, or a form check fails.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import colloc, episode, guide, jyutping
from .particles import Slot, alternatives, config, slots

QUESTION_PARTICLES = set("呀嘎嗱喳啝咩嗎")
TONE4 = set("呀嘎嗱喳啝")
# A question word or an A-not-A pattern makes a question without a tone-4 particle.
QUESTION_WORDS = re.compile(r"咩|乜|點|邊|幾|誰|未|定係|係咪|有冇|可唔可以|使唔使|(.)唔\1")


@dataclass
class Model:
    draft: float
    best: str
    margin: float           # best minus draft (> 0: another is preferred); else draft minus runner-up
    prefers_other: bool
    level: str             # clear | lean | none
    independent: bool

    def phrase(self, run: str) -> str:
        label = "" if self.independent else " (not independent: the draft came from this recogniser)"
        if self.prefers_other:
            how = {"clear": "clearly prefers", "lean": "leans to"}.get(self.level, "slightly prefers")
            return f"the fine-tuned recogniser {how} {self.best} over {run}{label}"
        if self.level == "clear":
            return f"the fine-tuned recogniser clearly agrees with {run}{label}"
        if self.level == "lean":
            return f"the fine-tuned recogniser leans to {run}, as written{label}"
        return f"the fine-tuned recogniser cannot tell {run} from {self.best}{label}"


@dataclass
class SlotReport:
    cue: int
    slot: Slot
    reading: str
    meaning: str
    reference: list[str]
    model: Model | None = None
    notes: list[colloc.Note] = field(default_factory=list)
    pulls: list[colloc.Pull] = field(default_factory=list)
    against: colloc.Pull | None = None
    checks: list[str] = field(default_factory=list)
    force: str = ""
    asr: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def suspect(self) -> bool:
        return bool(self.reasons)


def _level(margin: float, a: str = "", b: str = "") -> str:
    """clear / lean / none for a preference of *margin* between particles *a* and *b*; a pair
    the recogniser tells apart poorly is a lean at most."""
    cfg = config()["model"]
    weak = any({a[-1:], b[-1:]} == set(p) for p in cfg.get("weak_pairs", []))
    if margin >= cfg["clear"] and cfg.get("calibrated") and not weak:
        return "clear"
    if margin >= cfg["lean"]:
        return "lean"
    return "none"


def model_view(row: dict | None, run: str, independent: bool) -> Model | None:
    if not row or run not in row["logprobs"] or len(row["logprobs"]) < 2:
        return None
    lps = row["logprobs"]
    draft = lps[run]
    others = {w: lp for w, lp in lps.items() if w != run}
    best = max(others, key=others.get)
    if others[best] > draft:
        margin = others[best] - draft
        return Model(draft, best, margin, True, _level(margin, run, best), independent)
    margin = draft - others[best]
    return Model(draft, best, margin, False, _level(margin, run, best), independent)


def _force(text: str, refs: list[str]) -> str:
    """'' when the cue and its reference agree, else a plain description of the mismatch.
    Judged on the cue's last slot: a cue that asks has `？` or ends in a question particle."""
    if not refs:
        return ""
    # A reference cue can hold two lines (真的是這樣嗎？  只是日出而已): it asks what this cue
    # ends on only if its last line asks, and states only if none of its lines asks.
    ref = refs[-1].strip()
    asks = lambda t: "？" in t or "?" in t
    ref_asks = asks(re.split(r"\s{2,}|\n", ref)[-1])
    cue_asks = asks(text) or (slots(text) and slots(text)[-1].last in QUESTION_PARTICLES)
    if ref_asks and not cue_asks:
        return "the reference asks a question, the line states"
    if cue_asks and not asks(ref) and not ("！" in ref or "!" in ref):
        return "the line asks a question, the reference states"
    return ""


def _checks(s: Slot) -> list[str]:
    out = []
    # After a comma the question may go on (你肯定呀，芙莉蓮大人？): only a sentence that ends
    # on the particle without a question mark is doubted.
    if s.last in TONE4 and not s.question and s.after[:1] not in ("，", ","):
        out.append(f"{s.last} {jyutping.reading(s.last)} is a question particle, but no question mark follows")
    q = config().get("question", {})
    if s.question and s.last in q and not QUESTION_WORDS.search(s.clause + s.run[:-1]):
        out.append(f"a question without a question word usually takes {q[s.last]} "
                   f"{jyutping.reading(q[s.last])}, the question form of {s.last}")
    return out


def scan(episode_id: str, start: int = 1, end: int | None = None) -> list[SlotReport]:
    from .render import _ref_placement
    ep = episode.load(episode_id)
    srt = episode.srt(ep)
    placed = _ref_placement(srt.cues, episode.reference_cues(episode_id))
    evidence = {e["cue"]: e for e in episode.read_jsonl(episode_id, "evidence.jsonl")}
    model_rows = {(r["cue"], r["slot"]): r for r in episode.read_jsonl(episode_id, "particle_model.jsonl")}
    independent = not episode.machine_draft(ep)
    out = []
    for c in srt.cues:
        if c.pos < start or (end is not None and c.pos > end):
            continue
        refs = placed.get(c.pos, [])
        cue_slots = slots(c.text)
        force = _force(c.text, refs)
        asr = {}
        for tag, h in evidence.get(c.pos, {}).get("asr", {}).items():
            runs = [s.run for s in slots(h.get("text", ""))]
            asr[tag] = " ".join(runs) if runs else "none"
        for s in cue_slots:
            if not alternatives(s.run):
                continue
            row = model_rows.get((c.pos, s.index))
            if row and row.get("run") != s.run:
                row = None          # the draft changed since it was scored
            conv = guide.convention(s.last) or ""
            rep = SlotReport(c.pos, s, " ".join(s.readings), conv.split("—", 1)[-1].strip() if conv else "",
                             refs, model_view(row, s.run, independent),
                             colloc.notes_for(s.clause, s.run), colloc.pulls(s.clause, s.last, s.question),
                             colloc.against(s.clause, s.last, s.question), _checks(s),
                             force if s.index == cue_slots[-1].index else "", asr)
            m = rep.model
            if m and m.prefers_other and m.level in ("clear", "lean"):
                rep.reasons.append(m.phrase(s.run))
            # A collocation is a tendency: where the recogniser, as an independent witness,
            # already hears the draft's particle, the tendency alone is no reason to look again
            # (the line still shows it).
            heard = m is not None and m.independent and not m.prefers_other and m.level in ("clear", "lean")
            for n in ([] if heard else rep.notes):
                if n.wants_other(s.run):
                    rep.reasons.append(f"recorded collocation ({n.status}): {n.trigger} usually takes {n.prefer}")
            if rep.against and not heard:
                p = rep.against
                rep.reasons.append(f"strict subtitles end clauses with {p.feature.rstrip('$')} in {p.best} "
                                   f"{round(100 * p.share)}% of the time, {s.last} {round(100 * p.share_of(s.last))}%")
            rep.reasons += rep.checks
            if rep.force:
                rep.reasons.append(rep.force)
            out.append(rep)
    return out


def as_text(reports: list[SlotReport], only_suspects: bool = False) -> str:
    from .srtio import to_display
    lines = []
    for r in reports:
        if only_suspects and not r.suspect:
            continue
        s = r.slot
        head = f"{'?' if r.suspect else ' '} {r.cue}[{s.index}] {s.run} {r.reading}  ·  {to_display(s.clause.strip())}{s.run}{s.after}"
        lines.append(head)
        if r.meaning:
            lines.append(f"    means: {r.meaning}")
        for ref in r.reference[-1:]:
            lines.append(f"    R: {to_display(ref)}")
        if r.model:
            lines.append(f"    model: {r.model.phrase(s.run)}")
        for n in r.notes:
            pref = f" → {n.prefer}" if n.prefer else ""
            lines.append(f"    recorded ({n.status}): {n.trigger}{pref}: {n.note}")
        for p in r.pulls:
            dist = ", ".join(f"{k} {v}" for k, v in sorted(p.dist.items(), key=lambda kv: -kv[1])[:4])
            lines.append(f"    strict: {p.feature} → {p.best} {round(100 * p.share)}% of {p.n} ({p.shows} shows; {dist})")
        if r.asr:
            lines.append("    recognisers wrote (weak): " + " · ".join(f"{k} {v}" for k, v in r.asr.items()))
        for why in r.reasons:
            lines.append(f"    ? {why}")
    return "\n".join(lines)


def summary(reports: list[SlotReport]) -> dict:
    return {"slots": len(reports), "suspects": sum(r.suspect for r in reports),
            "scored_by_model": sum(r.model is not None for r in reports),
            "calibrated": bool(config()["model"].get("calibrated"))}
