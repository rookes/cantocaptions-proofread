"""What the tools pointed out on each cue: the lines the review stream marks for the agent.

    lint     a convention check (`L` line): a spelling variant, punctuation, line length...
    asr      a speech recogniser heard something else (`≠ft` / `≠qw` lines)
    weak     the aligner barely heard part of the cue (`!` line)
    timing   realign doubted the cue's timing (`T` line)
    particle the particle scan doubted a sentence-final particle (`ccp particles scan`)
    seg      the segmentation check pointed at how the cue is cut (`S` line)
    missing  a reference line no cue covers follows the cue (`+R` line)

A cue with none of these was found by the agent alone. They are kept in
work/<id>/signals.json as first seen, so an edit that clears a lint hit does not erase the fact
that the tool raised it: `snapshot()` runs whenever the agent is shown cues (render, cue) and
before the cleanup edits, and only adds to what a cue had while its text is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import episode, lint

# kind -> (short label, what it means), for the report and the stats.
KINDS = {
    "lint": ("Conventions", "the convention checker flagged it"),
    "asr": ("Recognisers", "a speech recogniser heard something else"),
    "weak": ("Hard to hear", "part of the line barely matched the audio"),
    "timing": ("Timing", "the realign doubted its timing"),
    "particle": ("Particle scan", "the particle scan doubted its sentence-final particle"),
    "seg": ("Segmentation", "the segmentation check pointed at how the line is cut"),
    "missing": ("Reference only", "a reference line had no subtitle line: one may be missing"),
}
FILE = "signals.json"


def current(episode_id: str) -> dict[int, dict]:
    """{cue: {"text": cue text, "kinds": [...]}} for the draft as it is now."""
    from .render import asr_differences, hard_to_hear, ref_orphans, segment_signals
    ep = episode.load(episode_id)
    if not ep.get("srt"):
        return {}
    cues = episode.srt(ep).cues
    evidence = {e["cue"]: e for e in episode.read_jsonl(episode_id, "evidence.jsonl")}
    linted = {r["cue"] for r in lint.lint_file(Path(ep["srt"]), ep.get("show_slug"))}
    timed = {r["cue"] for r in episode.read_jsonl(episode_id, "timing.jsonl")}
    particled = _particle_suspects(episode_id)
    seg = segment_signals(cues, ep)
    before_orphan = {o["after"] for o in ref_orphans(cues, episode.reference_cues(episode_id))}
    out = {}
    for c in cues:
        ev = evidence.get(c.pos, {})
        differ = asr_differences(c.text, ev)
        kinds = [k for k, on in (("lint", c.pos in linted), ("asr", bool(differ)),
                                 ("weak", bool(hard_to_hear(ev, bool(differ)))),
                                 ("timing", c.pos in timed), ("particle", c.pos in particled),
                                 ("seg", c.pos in seg), ("missing", c.pos in before_orphan)) if on]
        out[c.pos] = {"text": c.text, "kinds": kinds}
    return out


def _particle_suspects(episode_id: str) -> set[int]:
    from . import particle_scan
    try:
        return {r.cue for r in particle_scan.scan(episode_id) if r.suspect}
    except Exception:   # the scan is a hint: never let it stop the command that asked
        return set()


def load(episode_id: str) -> dict[int, dict]:
    p = episode.path(episode_id, FILE)
    if not p.exists():
        return {}
    return {int(k): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


def snapshot(episode_id: str) -> dict[int, dict]:
    """Merge the current signals into signals.json and return the result. A cue's first-seen
    text is kept; kinds are added only while the cue still has that text."""
    try:
        now = current(episode_id)
    except (SystemExit, FileNotFoundError, ValueError):
        return load(episode_id)
    seen = load(episode_id)
    for pos, cur in now.items():
        old = seen.get(pos)
        if old is None:
            seen[pos] = cur
        elif old["text"] == cur["text"]:
            old["kinds"] = [k for k in KINDS if k in set(old["kinds"]) | set(cur["kinds"])]
    episode.path(episode_id, FILE).write_text(
        json.dumps({str(k): v for k, v in sorted(seen.items())}, ensure_ascii=False), encoding="utf-8")
    return seen
