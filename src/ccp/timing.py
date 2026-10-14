"""Timing proposals for one cue: a retime, or a split into several cues, computed from the
emissions `ccp evidence` stored. No GPU.

The cue's whole group is force-aligned (the same port of the pipeline's trellis that scoring
uses), which gives every character an *onset*. That trellis lets a character's span run on
through any pause after it, so a character is taken to end at the next character's onset,
and at most MAX_CHAR seconds after its own.

Proposals follow the CantoCaptions style guide: a cue starts 0-50 ms before speech (LEAD),
trails the end of speech by about 350 ms (TRAIL), lasts at least 750 ms when it has three or
more characters, and never overlaps its neighbours. They are suggestions for a reviewer:
`ccp timing` saves one, `ccp flag add --timing` attaches it to a flag, and nothing changes
the file until the flag is accepted.
"""
from __future__ import annotations

import json
import statistics

import numpy as np

from . import episode
from .ctcscore import Store, force_align_path
from .jyutping import is_sound
from .srtio import from_display, short_time, to_display

LEAD = 0.05
TRAIL = 0.35
MIN_DURATION = 0.75
MAX_CHAR = 0.6
WEAK = 0.1


def char_times(episode_id: str, pos: int) -> tuple[list[dict], list[str]]:
    """[{char, onset, end, peak}] (seconds) for the sound characters of cue *pos*."""
    ep = episode.load(episode_id)
    cues = episode.srt(ep).cues
    store = Store(episode_id)
    c = cues[pos - 1]
    g = store.group_for(c.start, c.end)
    if g is None:
        return [], ["the cue lies outside the stored emissions"]
    em = np.asarray(np.load(store.dir / f"g{g['group']:04d}.npy"), dtype=np.float32)
    rate = g["rate"]
    members = [p for p in g["cues"] if cues[p - 1].start < g["end"] and cues[p - 1].end > g["start"]]
    if pos not in members:
        members = sorted(set(members) | {pos})
    seq, owner, ids, where = [], [], [], []
    for p in members:
        for ch in cues[p - 1].text:
            if is_sound(ch):
                seq.append(ch)
                owner.append(p)
    for k, ch in enumerate(seq):
        tok = store.table.tokens.get(ch.lower())
        if tok:
            ids.append(tok[0])
            where.append(k)
    path = force_align_path(em, ids, store.table.blank)
    notes = []
    if path is None:
        return [], ["forced alignment failed for this group"]
    onset = [None] * len(seq)
    peak = [0.0] * len(seq)
    for k, step in zip(where, path):
        onset[k] = g["start"] + step["onset"] / rate
        peak[k] = step["peak"]
    # Characters without a token get the midpoint of their neighbours' onsets.
    known = [k for k, t in enumerate(onset) if t is not None]
    for k in range(len(seq)):
        if onset[k] is None and known:
            before = max((j for j in known if j < k), default=None)
            after = min((j for j in known if j > k), default=None)
            if before is not None and after is not None:
                onset[k] = (onset[before] + onset[after]) / 2
            else:
                onset[k] = onset[before if before is not None else after]
            notes.append(f"{seq[k]} has no aligner token; its time is interpolated")
    out = []
    for k, ch in enumerate(seq):
        if owner[k] != pos:
            continue
        nxt = onset[k + 1] if k + 1 < len(seq) else g["end"]
        out.append({"char": ch, "onset": round(onset[k], 3),
                    "end": round(min(nxt, onset[k] + MAX_CHAR), 3), "peak": round(peak[k], 3)})
    return out, notes


def _neighbours(cues, pos):
    prev_end = next((c.end for c in reversed(cues[:pos - 1]) if not c.an8), 0.0)
    nxt_start = next((c.start for c in cues[pos:] if not c.an8), None)
    return prev_end, nxt_start


def suggest(episode_id: str, pos: int, split: str | None = None, retime: bool = False) -> dict:
    ep = episode.load(episode_id)
    cues = episode.srt(ep).cues
    c = cues[pos - 1]
    chars, notes = char_times(episode_id, pos)
    if not chars:
        raise SystemExit(f"cannot time cue {pos}: {'; '.join(notes)} (re-run `ccp evidence --force`?)")
    peaks = [x["peak"] for x in chars]
    if statistics.median(peaks) < WEAK:
        notes.append("the aligner barely hears this cue (median peak below 0.1): treat these times as rough")
    prev_end, next_start = _neighbours(cues, pos)
    limit_end = next_start if next_start is not None else c.end + 5

    def shape(start, end, n_chars, lo, hi):
        start, end = max(lo, start), min(hi, end)
        if n_chars >= 3 and end - start < MIN_DURATION:
            end = min(hi, start + MIN_DURATION)
        return round(start, 3), round(max(end, start + 0.1), 3)

    if split:
        parts = [p for p in from_display(split).split("|")]
        flat = lambda t: t.replace("\n", "").replace(" ", "")
        if flat("".join(parts)) != flat(c.text):
            raise SystemExit(f"the parts must spell out the cue exactly (separated by |): "
                             f"{to_display(c.text)!r} vs {to_display('|'.join(parts))!r}")
        sizes = [sum(1 for ch in p if is_sound(ch)) for p in parts]
        if any(n == 0 for n in sizes):
            raise SystemExit("every part needs at least one spoken character")
        pieces, k = [], 0
        for p, n in zip(parts, sizes):
            seg = chars[k:k + n]
            k += n
            pieces.append({"text": p.strip("\n"), "first": seg[0], "last": seg[-1], "n": n})
        proposed, gaps = [], []
        for i, pc in enumerate(pieces):
            s = (pc["first"]["onset"] - LEAD) if (i > 0 or retime) else c.start
            e = (pc["last"]["end"] + TRAIL) if (i < len(pieces) - 1 or retime) else c.end
            hi = pieces[i + 1]["first"]["onset"] - LEAD if i + 1 < len(pieces) else limit_end
            lo = proposed[-1]["end"] if proposed else prev_end
            s, e = shape(s, e, pc["n"], lo, hi)
            proposed.append({"start": s, "end": e, "text": pc["text"]})
            if i + 1 < len(pieces):
                gaps.append(round(pieces[i + 1]["first"]["onset"] - pc["last"]["onset"], 2))
        result = {"action": "split", "onset_gaps_s": gaps,
                  "note": "onset gap = time from the last character of a piece to the first of the next; "
                          "a real pause between sentences is usually 0.7 s or more"}
    else:
        s, e = shape(chars[0]["onset"] - LEAD, chars[-1]["end"] + TRAIL, len(chars), prev_end, limit_end)
        proposed = [{"start": s, "end": e, "text": c.text}]
        result = {"action": "retime",
                  "shift_start_s": round(s - c.start, 2), "shift_end_s": round(e - c.end, 2)}
    result.update({
        "cue": pos, "current": {"start": c.start, "end": c.end, "text": c.text,
                                "at": f"{short_time(c.start)}–{short_time(c.end)}"},
        "chars": "  ".join(f"{x['char']} {short_time(x['onset'])} ({x['peak']:.2f})" for x in chars),
        "proposed_cues": proposed,
        "proposed_at": [f"{short_time(p['start'])}–{short_time(p['end'])}  {to_display(p['text'])}" for p in proposed],
    })
    if notes:
        result["notes"] = notes
    saved = episode.path(episode_id, "timing_suggestions")
    saved.mkdir(exist_ok=True)
    (saved / f"{pos}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["saved"] = f"attach it to a flag with `ccp flag add {episode_id} --cue {pos} --timing ...`"
    return result


def load_saved(episode_id: str, pos: int) -> dict | None:
    p = episode.path(episode_id, "timing_suggestions") / f"{pos}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
