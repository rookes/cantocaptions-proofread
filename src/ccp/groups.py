"""Cue groups for the ASR pass: merge first, then pad only the group edges.

Transcribing each cue alone clips onsets and strips the context the recognisers need;
padding cues individually makes neighbouring clips overlap so words are heard twice.
So consecutive cues closer than `gap` seconds are merged (up to `max_len` seconds, split
at the largest internal gap when longer), `{\\an8}` cues get groups of their own, and
each group is padded by up to `pad` seconds into the silence on each side, never past
the midpoint of the gap to its neighbour. Groups never overlap.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .srtio import Cue


@dataclass
class Group:
    index: int
    cues: list[int] = field(default_factory=list)    # cue positions
    start: float = 0.0          # padded audio span
    end: float = 0.0
    cue_start: float = 0.0      # unpadded span (first cue start .. last cue end)
    cue_end: float = 0.0


def _split_long(run: list[Cue], max_len: float) -> list[list[Cue]]:
    if len(run) == 1 or run[-1].end - run[0].start <= max_len:
        return [run]
    gaps = [(run[i + 1].start - run[i].end, i) for i in range(len(run) - 1)]
    # Prefer the largest gap that leaves both halves usable; fall back to the middle.
    _, cut = max(gaps, key=lambda g: (g[0], -abs(g[1] - len(run) / 2)))
    return _split_long(run[:cut + 1], max_len) + _split_long(run[cut + 1:], max_len)


def make_groups(cues: list[Cue], gap: float = 0.8, max_len: float = 20.0, pad: float = 0.5,
                audio_end: float | None = None) -> list[Group]:
    main = [c for c in cues if not c.an8 and c.end > c.start]
    runs: list[list[Cue]] = []
    for c in main:
        if runs and c.start - runs[-1][-1].end < gap and c.start >= runs[-1][-1].start:
            runs[-1].append(c)
        else:
            runs.append([c])
    split: list[list[Cue]] = [part for run in runs for part in _split_long(run, max_len)]
    split += [[c] for c in cues if c.an8 and c.end > c.start]
    split.sort(key=lambda r: r[0].start)

    groups = [Group(i, [c.pos for c in run], cue_start=run[0].start, cue_end=max(c.end for c in run))
              for i, run in enumerate(split)]
    main_groups = [g for g in groups if not any(cues[p - 1].an8 for p in g.cues)]
    for g in groups:
        g.start, g.end = max(0.0, g.cue_start - pad), g.cue_end + pad
        if audio_end is not None:
            g.end = min(g.end, audio_end)
    # Clamp main-track groups against each other at the gap midpoint ({\an8} groups overlap
    # dialogue by design and are left padded).
    for a, b in zip(main_groups, main_groups[1:]):
        mid = (a.cue_end + b.cue_start) / 2
        if a.end > mid:
            a.end = max(a.cue_end, mid)
        if b.start < mid:
            b.start = min(b.cue_start, mid)
    return groups


def listen_span(cues: list[Cue], pos: int, pad: float = 1.0, clamp: bool = True) -> tuple[float, float]:
    """Audio span for re-listening to one cue: ±pad, clamped to the gap midpoints with its
    neighbours unless clamp is False (an explicit --pad)."""
    c = cues[pos - 1]
    start, end = max(0.0, c.start - pad), c.end + pad
    if clamp:
        prev = next((x for x in reversed(cues[:pos - 1]) if not x.an8), None)
        nxt = next((x for x in cues[pos:] if not x.an8), None)
        if prev is not None and prev.end <= c.start:
            start = max(start, (prev.end + c.start) / 2)
        if nxt is not None and nxt.start >= c.end:
            end = min(end, (c.end + nxt.start) / 2)
    return start, end
