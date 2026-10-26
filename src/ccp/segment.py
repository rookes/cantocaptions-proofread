"""ccp segment: re-cut cues in the cleanup pass, without touching their words.

Messy subtitles are cut badly: two sentences or two speakers in one cue, long lines broken in
two, a cue cut inside a word. The agent decides what goes in which cue; this tool checks that
the words stay exactly as they were and puts the result in the draft. One line per regroup,
cue numbers as `ccp render` shows them:

    30|佢話今晚會嚟 // 叫我哋唔使等|3.9 s holding two clauses, a pause at the comma
    41-42|佢哋個學校好遠|學|校 was cut in two across 41 and 42
    57|你去邊啊？ // 我去學校|two speakers in one cue: one cue each

`N` or `N-M` is the range of cues replaced, ` // ` separates the new cues, `⏎` is a line break,
and the reason is required. The sound characters of the new cues must spell out the old ones
exactly: only punctuation, line breaks and speaker dashes may change. A comma left at the end
of a cue is dropped (a cue never ends in one).

It works in two steps around the cleanup's realign, because a messy file's cue lengths say
little until the realign has timed them (a transcriber who pads cues too tightly makes every
line look like a fragment):

* **Before the realign: split and re-cut.** One line per cue is much preferred to two, so a
  cue holding two sentences or two speakers becomes two cues, and a line break is refused
  where the text fits on one line. Two speakers are never joined into one cue here. Each new
  cue gets rough times (each character placed proportionally inside the cue it came from);
  the realign then times them against the audio, keeping these cuts.
* **After the realign: join quick exchanges.** Two lines of different speakers whose starts
  are under JOIN_S apart (JOIN_SHORT_S when both are short) cannot each be read on their own,
  so they share one cue as `-甲⏎-乙`. The joined cue runs from the first start to the second
  end. Nothing else is re-cut after the realign: it timed the cuts it was given.

Outside the cleanup it refuses: in a hand-made file that is not being cleaned, cutting is the
subtitler's choice. Each regroup is recorded (a `segmentation` flag with `span`) and applied
at once; the report leaves them out.

`signals()` gives the review stream its `S` lines: where to look, never a decision.
"""
from __future__ import annotations

import time

from . import episode, flags as flagstore
from .jyutping import is_sound
from .lint import config as lint_config, display_width
from .srtio import Cue, from_display, to_display
from .words import word_across

SEP = "//"
LONG = 2.5              # a cue this long with a clause break inside may want cutting
CLOSE = 0.3             # neighbours closer than this read as one utterance cut in two
JOIN_S = 0.75           # after the realign: start-to-start under this, two speakers share a cue
JOIN_SHORT_S = 0.65     # ... or under this when both lines are short
SHORT_LINE = 4.0        # display width of a "short" line, for JOIN_SHORT_S
CUT_MARKS = "，？！…；：、"
END_MARKS = CUT_MARKS + "。」』）)"
TRAILING = "，、,"       # dropped from the end of a new cue


def sounds(text: str) -> str:
    return "".join(ch for ch in text if is_sound(ch))


def _width_limit() -> float:
    return lint_config()["limits"].get("line_width", 17.5)


def _lines(text: str) -> list[str]:
    return text.split("\n")


def _dash_pair(text: str) -> bool:
    lines = _lines(text)
    return len(lines) == 2 and all(ln.startswith("-") for ln in lines)


def join_limit(a: str, b: str) -> float:
    """The start-to-start gap under which lines *a* and *b* share one cue."""
    short = display_width(a.lstrip("-")) <= SHORT_LINE and display_width(b.lstrip("-")) <= SHORT_LINE
    return JOIN_SHORT_S if short else JOIN_S


# ------------------------------------------------------------------------------- signals

def signals(cues: list[Cue], after_realign: bool = False) -> dict[int, list[str]]:
    """{cue: [S notes]} for the main-track cues of a file: what to re-cut before the realign,
    or which lines to join after it."""
    main = [c for c in cues if not c.an8]
    out: dict[int, list[str]] = {}

    def note(pos, text):
        out.setdefault(pos, []).append(text)

    if after_realign:
        limit = _width_limit()
        for a, b in zip(main, main[1:]):
            if "\n" in a.text or "\n" in b.text:
                continue
            gap = b.start - a.start
            if gap < join_limit(a.text, b.text) and max(display_width(a.text), display_width(b.text)) + 0.5 <= limit:
                note(a.pos, f"quick exchange: cue {b.pos} starts {gap:.2f} s after this one; if another "
                            f"speaker says it, join them as -甲⏎-乙")
        return out
    for a, b in zip(main, main[1:] + [None]):
        dur = a.end - a.start
        inner = a.text.rstrip(END_MARKS)
        if dur > LONG and any(m in inner for m in CUT_MARKS):
            mark = next(m for m in CUT_MARKS if m in inner)
            note(a.pos, f"long: {dur:.1f} s with a break inside (after {mark}): two cues?")
        if b is not None and b.start - a.end < CLOSE and a.text and not a.text.endswith(tuple(END_MARKS)):
            w = word_across(_lines(a.text)[-1], _lines(b.text)[0].lstrip("-"))
            if w:
                note(a.pos, f"cut inside a word: {w} runs on into cue {b.pos}")
    for c in main:
        lines = _lines(c.text)
        dashed = [ln.startswith("-") for ln in lines]
        if len(lines) > 2:
            note(c.pos, f"layout: {len(lines)} lines: split it")
        elif any(dashed) and not all(dashed):
            note(c.pos, "layout: only one line has a speaker dash")
        elif _dash_pair(c.text):
            note(c.pos, "two speakers in one cue: split it into two cues (quick exchanges are joined after the realign)")
        elif len(lines) == 2:
            note(c.pos, "two lines: split it into two cues if it reads as two")
    return out


# --------------------------------------------------------------------------------- edits

def parse(lines: list[str]) -> list[dict]:
    out = []
    for raw in lines:
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        rng = parts[0].strip()
        lo, sep, hi = rng.partition("-")
        if len(parts) < 2 or not lo.strip().isdigit() or (sep and not hi.strip().isdigit()):
            raise ValueError(f"not a segment line (N|cue // cue|reason or N-M|...): {line!r}")
        first, last = int(lo), int(hi) if sep else int(lo)
        pieces = [from_display(p.strip()) for p in parts[1].split(SEP)]
        out.append({"first": first, "last": last, "pieces": pieces,
                    "why": parts[2].strip() if len(parts) > 2 else ""})
    return out


def tidy(piece: str) -> str:
    """A new cue as it goes in: no comma left at the end of a line."""
    return "\n".join(ln.rstrip().rstrip(TRAILING).rstrip() for ln in _lines(piece.strip()))


def problems(cues: list[Cue], e: dict, after_realign: bool = False) -> list[str]:
    """Why an edit cannot be applied ([] when it can). *e*'s pieces are already tidied."""
    n = len(cues)
    if not 1 <= e["first"] <= e["last"] <= n:
        return [f"cues {e['first']}-{e['last']} are outside 1-{n}"]
    src = cues[e["first"] - 1:e["last"]]
    out = []
    if any(c.an8 for c in src):
        out.append("a {\\an8} cue is a separate track: leave it out of the range")
    old, new = sounds("".join(c.text for c in src)), sounds("".join(e["pieces"]))
    if old != new:
        out.append(f"the new cues must spell out the old ones exactly (only punctuation, line breaks and "
                   f"speaker dashes may change): {old} vs {new}")
    if [p for p in e["pieces"]] == [c.text for c in src]:
        out.append("nothing changes")
    limit = _width_limit()
    for p in e["pieces"]:
        if not sounds(p):
            out.append(f"{to_display(p) or '(empty)'}: every cue needs at least one spoken character")
            continue
        lines = _lines(p)
        if len(lines) > 2:
            out.append(f"{to_display(p)}: at most two lines")
        dashed = [ln.startswith("-") for ln in lines]
        if any(dashed) and (len(lines) != 2 or not all(dashed)):
            out.append(f"{to_display(p)}: two speakers take two lines, each starting with - (-你去邊？⏎-學校)")
        if any(ln.startswith("- ") for ln in lines):
            out.append(f"{to_display(p)}: no space after the speaker dash")
        for ln in lines:
            if display_width(ln) > limit:
                out.append(f"{ln}: line width {display_width(ln):g} > {limit:g}")
        if len(lines) == 2 and not any(dashed) and display_width("".join(lines)) <= limit:
            out.append(f"{to_display(p)}: fits on one line: write it as one line (or as two cues)")
    if after_realign:
        out += _join_problems(src, e["pieces"])
    elif any(_dash_pair(p) and not any(c.text == p for c in src) for p in e["pieces"]):
        out.append("two speakers are joined into one cue only after the realign, and only when they "
                   "speak in quick succession: before it, give each speaker a cue of their own")
    if len(e["why"].strip()) < flagstore.MIN_REASON:
        out.append("add a reason: what was wrong with the cutting and why this is better")
    return out


def _join_problems(src: list[Cue], pieces: list[str]) -> list[str]:
    """After the realign only one regroup is possible: two neighbouring cues, two speakers in
    quick succession, into one `-甲⏎-乙` cue."""
    if not (len(src) == 2 and len(pieces) == 1 and _dash_pair(pieces[0])):
        return ["after the realign the only re-cut is joining two neighbouring cues of different speakers "
                "into one -甲⏎-乙 cue; splitting and re-cutting come before the realign"]
    a, b = src
    gap = b.start - a.start
    limit = join_limit(a.text, b.text)
    if gap >= limit:
        return [f"cue {b.pos} starts {gap:.2f} s after cue {a.pos}: each can be read on its own (lines are "
                f"joined only under {limit:g} s start to start)"]
    return []


# -------------------------------------------------------------------------------- timing

def _proportional(src: list[Cue]) -> list[tuple[float, float]]:
    """(start, end) of every sound character of *src*, spread over its own cue by width."""
    out = []
    for c in src:
        chars = [ch for ch in c.text if is_sound(ch)]
        widths = [display_width(ch) or 0.5 for ch in chars]
        total, at = sum(widths), c.start
        for w in widths:
            step = (c.end - c.start) * w / total
            out.append((at, at + step))
            at += step
    return out


def proposed_cues(src: list[Cue], pieces: list[str], times: list[tuple[float, float]]) -> list[dict]:
    """Rough times for *pieces*: the outer edges stay where the range was; inner edges come
    from the characters on each side of a cut. The realign times them properly."""
    spans, k = [], 0
    for p in pieces:
        n = len(sounds(p))
        spans.append((times[k], times[k + n - 1]))
        k += n
    out = []
    for i, (p, (first, last)) in enumerate(zip(pieces, spans)):
        s = src[0].start if i == 0 else first[0]
        e = src[-1].end if i == len(pieces) - 1 else min(last[1], spans[i + 1][0][0])
        if out:
            s = max(s, out[-1]["end"])
        e = max(e, s + 0.1)
        out.append({"start": round(s, 3), "end": round(e, 3), "text": p})
    return out


# ------------------------------------------------------------------------------- command

def segment(episode_id: str, edits: list[dict], dry_run: bool = False) -> dict:
    from . import apply as applier
    ep = episode.load(episode_id)
    if not episode.cleanup_pass(ep):
        raise SystemExit("`ccp segment` is part of the cleanup pass (skill clean-draft): in a normal proofread "
                         "the cutting is the subtitler's choice and the timing the realign's. If the cutting is "
                         "poor throughout, say so and offer the cleanup instead.")
    after = episode.realigned(ep)
    cues = episode.srt(ep).cues
    edits = sorted(({**e, "pieces": [tidy(p) for p in e["pieces"]]} for e in edits), key=lambda e: e["first"])
    refused, planned = [], []
    for a, b in zip(edits, edits[1:]):
        if b["first"] <= a["last"]:
            refused.append({"cues": f"{b['first']}-{b['last']}", "problems": [f"overlaps cues {a['first']}-{a['last']}"]})
    bad = {r["cues"] for r in refused}
    for e in edits:
        key = f"{e['first']}-{e['last']}"
        why = problems(cues, e, after)
        if why or key in bad:
            if why:
                refused.append({"cues": key, "problems": why})
            continue
        src = cues[e["first"] - 1:e["last"]]
        if after:
            pc = [{"start": src[0].start, "end": src[-1].end, "text": e["pieces"][0]}]
        else:
            pc = proposed_cues(src, e["pieces"], _proportional(src))
        planned.append({**e, "proposed_cues": pc})
    result = {"episode_id": episode_id, "step": "joins after the realign" if after else "re-cutting before the realign",
              "regroups": len(planned), "cues_before": sum(p["last"] - p["first"] + 1 for p in planned),
              "cues_after": sum(len(p["pieces"]) for p in planned)}
    if refused:
        result["refused"] = refused
        result["refused_note"] = ("fix these lines and submit only them again; the others "
                                  + ("are fine" if dry_run else "went ahead"))
    if dry_run:
        result["dry_run"] = True
        result["planned"] = [f"{p['first']}-{p['last']} → " + " // ".join(to_display(c["text"]) for c in p["proposed_cues"])
                             for p in planned]
        return result
    made = []
    for p in planned:
        try:
            f = flagstore.add(episode_id, p["first"], "segmentation", "fix", None, [], p["why"],
                              proposed_cues=p["proposed_cues"], span=(p["first"], p["last"]),
                              extra={"pass": "segmentation", "step": "join" if after else "cut"})
            made.append(f["id"])
        except ValueError as err:
            result.setdefault("refused", []).append({"cues": f"{p['first']}-{p['last']}", "problems": [str(err)]})
    res = applier.apply(episode_id, only=made)
    result["applied"] = len(res["applied"])
    result["file"] = res["file"]
    if res["skipped"]:
        result["skipped"] = res["skipped"]
    ep = episode.load(episode_id)
    key = "joins" if after else "segmentation"
    done = ep.get(key) or {"regroups": 0}
    ep[key] = {"regroups": done["regroups"] + len(res["applied"]), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    episode.save(ep)
    result["cues_now"] = len(episode.srt(ep).cues)
    result["next"] = ("cue numbers changed: render the next window fresh" + (
        "" if after else f". When the whole file is re-cut, realign it: `ccp pipeline {episode_id} realign "
                         "--mode adjust --input draft`"))
    return result
