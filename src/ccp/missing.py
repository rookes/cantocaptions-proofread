"""Reference lines with no cue: where the draft may be missing a line.

A line machine-made subtitles drop (VAD missed quiet or overlapped speech, the recogniser
heard nothing) often still has its reference line. `ccp missing` lists every reference line
the draft's cues cover for less than 30% of its length (`render.ref_orphans`), numbered by its
place in the reference (`+R#57` in the review stream), with the cues on either side.

Most are not missing lines: the reference is timed to another release and a neighbouring
cue already says it, or it is on-screen text, or a line the subtitles leave out on purpose.
The agent judges that from the meaning. For a line that really is missing it listens to the
span and records the line with `ccp flag add --missing N`, which inserts it after the cue
before it, timed at the reference line's place between its neighbours. In the cleanup of a
machine draft the adjust realign that follows places it against the audio.
"""
from __future__ import annotations

from . import episode
from .render import on_screen, ref_orphans
from .srtio import short_time, to_display

MIN_DURATION = 0.75


def orphans(episode_id: str) -> tuple[list, list[dict]]:
    ep = episode.load(episode_id)
    cues = episode.srt(ep).cues
    return cues, ref_orphans(cues, episode.reference_cues(episode_id))


def find(episode_id: str, n: int) -> tuple[list, dict]:
    cues, rows = orphans(episode_id)
    o = next((r for r in rows if r["n"] == n), None)
    if o is None:
        raise ValueError(f"reference line {n} has a cue already, or there is none: `ccp missing {episode_id}` "
                         "lists the reference lines without one")
    return cues, o


def neighbours(cues, o: dict) -> tuple[object | None, object | None]:
    main = [c for c in cues if not c.an8]
    before = next((c for c in reversed(main) if c.pos <= o["after"]), None)
    after = next((c for c in main if c.pos > o["after"]), None)
    return before, after


def gap(cues, o: dict) -> tuple[float, float]:
    """The room the line has: from the end of the cue before to the start of the cue after."""
    before, after = neighbours(cues, o)
    return (before.end if before else 0.0), (after.start if after else o["end"] + 5.0)


def span(cues, o: dict, pad: float = 0.3) -> tuple[float, float]:
    """The audio to hear for line *o*: its reference span ± pad, kept inside the gap."""
    lo, hi = gap(cues, o)
    s, e = max(lo, o["start"] - pad), min(hi, o["end"] + pad)
    if e - s < 0.3:
        s, e = o["start"], o["end"]
    return round(max(0.0, s), 3), round(e, 3)


def placed(cues, o: dict) -> tuple[float, float]:
    """Where an inserted line goes before anything times it: the reference line's own span,
    inside the gap, at least MIN_DURATION long when the gap allows."""
    lo, hi = gap(cues, o)
    s, e = max(lo, o["start"]), min(hi, o["end"])
    if e - s < MIN_DURATION:
        e = min(hi, s + MIN_DURATION)
        s = max(lo, min(s, e - MIN_DURATION))
    if e <= s:
        s, e = o["start"], o["end"]
    return round(s, 3), round(e, 3)


def listing(episode_id: str) -> dict:
    cues, rows = orphans(episode_id)
    if not episode.reference_cues(episode_id):
        return {"missing": [], "note": "no reference: run `ccp reference <id>` first"}
    out = []
    for o in rows:
        before, after = neighbours(cues, o)
        out.append({
            "ref": o["n"], "at": f"{short_time(o['start'])}–{short_time(o['end'])}", "text": to_display(o["text"]),
            "kind": "on-screen text" if o["on_screen"] else "speech?",
            "before": f"{before.pos}|{to_display(before.text)} @{short_time(before.start)}–{short_time(before.end)}" if before else None,
            "after": f"{after.pos}|{to_display(after.text)} @{short_time(after.start)}" if after else None,
            "room_s": round(gap(cues, o)[1] - gap(cues, o)[0], 1),
        })
    spoken = sum(1 for r in out if r["kind"] != "on-screen text")
    return {"missing": out, "count": len(out), "spoken": spoken,
            "note": ("candidates, not findings: most are mistimed reference lines a neighbouring cue already "
                     "says, on-screen text, or lines the subtitles leave out on purpose. Judge each by meaning "
                     "first (clean-draft, Missing lines)")}


# The four ways `ccp listen --missing` hears a span. Measured on 105 lines machine drafts lacked
# (cantocaptions-ai docs/missing-lines.md): each recovers a different share of them, and the
# agent's own line, written from all of them, the reference and the neighbours, beats every
# single one. The reference as a hint helps the recognisers find the words but never confirms
# them; a wider span runs into the neighbours.
WAYS = (("close", 0.3, False, False), ("isolated", 0.3, True, False),
        ("wider", 1.0, False, False), ("hinted", 0.3, False, True))
WAY_NAMES = {"close": "close (0.3 s around the line)", "isolated": "close, voices isolated from music and noise",
             "wider": "wider (1 s around it: may include the neighbours)",
             "hinted": "with the reference as a hint (finds words, can recite the reference: no confirmation)"}
CONTEXT = "［普通話參考字幕］：{text}"        # cantocaptions-ai reference_context's `labelled` template
PLAIN = ("close", "isolated")              # the hearings a grade may rest on
AGREE_CER = 0.2


def listen_items(episode_id: str, n: int) -> list[dict]:
    cues, o = find(episode_id, n)
    out = []
    for way, pad, iso, hint in WAYS:
        s, e = span(cues, o, pad)
        out.append({"key": f"+R#{n} {way}", "start": s, "end": e, "ref": o["text"], "missing": n, "way": way,
                    **({"isolate": True} if iso else {}),
                    **({"context": CONTEXT.format(text=o["text"].replace("\n", " "))} if hint else {})})
    return out


def heard(episode_id: str, items: list[dict], res: dict) -> dict:
    """What `ccp listen --missing` heard, per reference line, saved for the grade check."""
    import json
    by_n: dict[int, dict] = {}
    for it, src in zip(res["items"], items):
        row = by_n.setdefault(src["missing"], {"ref": src["ref"], "at": f"{short_time(src['start'])}–{short_time(src['end'])}",
                                                "heard": {}})
        row["heard"][src["way"]] = {tag: (h["text"] if isinstance(h, dict) else h) for tag, h in it["asr"].items()}
    d = episode.path(episode_id, "missing")
    d.mkdir(exist_ok=True)
    out = []
    for n, row in by_n.items():
        (d / f"{n}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        lines = [f"+R#{n} {to_display(row['ref'])}  @{row['at']}"]
        for way in (w[0] for w in WAYS):
            for tag, text in row["heard"].get(way, {}).items():
                name = "fine-tuned" if tag == "ft" else "stock Qwen"
                lines.append(f"  {WAY_NAMES[way]} · {name}: {to_display(text) or '(nothing heard)'}")
        out.append("\n".join(lines))
    return {"heard": out, "next": ("write the line that was said (written Cantonese, meaning what the reference "
                                   "means; leave out what belongs to the neighbours), then record it with "
                                   f"`ccp flag add {episode_id} --missing N ...`: the grade it may take comes "
                                   "from how the close hearings agree with it")}


def _contained(want: str, heard: str) -> int:
    """Edit distance of *want* against the stretch of *heard* that matches it best: words the
    hearing has before or after it cost nothing. A close span often runs into a neighbour,
    or into the next missing line when several are missing in a row."""
    prev = [0] * (len(heard) + 1)
    for i, x in enumerate(want, 1):
        cur = [i]
        for j, y in enumerate(heard, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return min(prev)


def _sounds(text: str) -> str:
    from .jyutping import is_sound
    from .render import FOLDS
    return "".join(ch.lower() for ch in text.translate(FOLDS["qw"]) if is_sound(ch))


def agreement(episode_id: str, n: int, text: str) -> dict | None:
    """Which recognisers' close hearings (plain or isolated) contain *text* (at most 1
    character in 5 different; extra words around it allowed), from the saved `ccp listen
    --missing` results; None before a listen."""
    import json
    p = episode.path(episode_id, "missing") / f"{n}.json"
    if not p.exists():
        return None
    row = json.loads(p.read_text(encoding="utf-8"))
    want = _sounds(text)
    out = {}
    for tag in ("ft", "qw"):
        hears = [row["heard"].get(way, {}).get(tag, "") for way in PLAIN]
        out[tag] = any(_sounds(h) and _contained(want, _sounds(h)) <= AGREE_CER * max(1, len(want)) for h in hears)
    return out


def allowed_grade(episode_id: str, n: int, text: str | None, on_screen_text: bool) -> tuple[str, str]:
    """The highest grade a missing line may take, and why. Measured (docs/missing-lines.md):
    a line both recognisers' close hearings contain was right 86% of the time, one only the
    fine-tuned recogniser's contains 67%, any other 29-50%."""
    if on_screen_text:
        return "fix", "on-screen text: copied from the reference, no audio needed"
    if not text:
        return "query", "no text"
    agree = agreement(episode_id, n, text)
    if agree is None:
        return "query", f"not listened to yet: run `ccp listen <id> --missing {n}` first"
    if agree["ft"] and agree["qw"]:
        return "fix", "both recognisers heard this line"
    if agree["ft"]:
        return "suggest", "only the fine-tuned recogniser heard this line"
    return "query", "neither recogniser's close hearing says this line: offer it as a candidate (--alt)"


def record(episode_id: str, n: int, grade: str, text: str | None, reason: str, evidence: list,
           alternatives: list[str] = (), category: str = "missing") -> dict:
    """Record the line reference line *n* says is missing: inserted after the cue before it."""
    from . import flags as flagstore
    from .srtio import from_display
    cues, o = find(episode_id, n)
    if grade in ("fix", "suggest"):
        bracketed = bool(text) and on_screen(text) and o["on_screen"]
        cap, why = allowed_grade(episode_id, n, text, bracketed)
        order = ["query", "suggest", "fix"]
        if order.index(grade) > order.index(cap):
            raise ValueError(f"+R#{n}: this line may be graded {cap} at most ({why}). Record it as {cap}"
                             + (" with the text as an alternative (--alt) instead of --proposed" if cap == "query" else ""))
    s, e = placed(cues, o)
    pc = [{"start": s, "end": e, "text": from_display(text)}] if text and grade in ("fix", "suggest") else None
    f = flagstore.add(episode_id, o["after"], category, grade, None, evidence, reason,
                      alternatives=alternatives, proposed_cues=pc, insert={"start": s, "end": e},
                      extra={"ref": n, "ref_text": o["text"]})
    if pc and episode.cleanup_pass(episode.load(episode_id)):
        # The cleanup puts the line in at once (the realign then times it);
        # the reviewer can still remove it from the report.
        from . import apply as applier
        applier.apply(episode_id, only=[f["id"]])
        f = next(x for x in flagstore.load(episode_id) if x["id"] == f["id"])
    return f
