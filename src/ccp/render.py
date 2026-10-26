"""The review stream: one window of cues as plain text, with every piece of evidence
placed under the cue it belongs to. Format (see the proofread-subtitles skill):

    37|阿媽食多都亂瞓唔着㗎  @3:21.5
    R 媽媽一定坐立不安睡不著的
    ≠ft 你阿媽食多多亂瞓唔着㗎
    ≠qw [你]阿媽食攞攞攣，瞓唔著嘅
    ! hard to hear: 多 都
    L variant 俾→畀
    F#3 essential/mishearing → 阿媽實囉囉攣瞓唔着㗎
    --
"""
from __future__ import annotations

from pathlib import Path

from . import episode, flags as flagstore, lint
from .corpus import FINAL_PARTICLES
from .jyutping import is_sound
from .srtio import Cue, short_time, to_display

PAUSE_S, SCENE_S = 1.0, 3.0
WEAK_PEAK = 0.05
MAX_WEAK = 4
MODEL_TAGS = {"ft": "≠ft", "qw": "≠qw"}


# Pure spelling variants (same sound, the standard picks one): folded before comparing any
# recogniser with the draft, so an ASR line appears only for a difference in what was said.
# Every firm one-character variant rule of the linter (config/lint.toml plus the dataset's
# standardization.toml), plus lint.toml's `asr_fold` for spellings that are not a rule.
VARIANT_FOLD = lint.spelling_folds()
# Pairs CantoCaptions distinguishes *by sound* (噉 gam2 / 咁 gam3, 邊 bin1 / 便 bin6,
# 着 zoek / 著 zyu3, 吖 aa1 / 啊 aa3 / 呀 aa4) but stock Qwen3-ASR does not: it writes 咁, 邊,
# 著, 呀 whatever was said. Its spelling of these is no evidence, so they are folded only
# when comparing *its* output. The fine-tuned model was trained on CantoCaptions and does
# make these distinctions, so a difference there is shown.
QWEN_FOLD = {"咁": "噉", "便": "邊", "著": "着", "呀": "啊", "吖": "啊"}
FOLDS = {"ft": str.maketrans(VARIANT_FOLD), "qw": str.maketrans({**VARIANT_FOLD, **QWEN_FOLD})}


def content_key(text: str, model: str = "ft") -> str:
    """Sound characters with clause-final particle runs removed, spelling variants folded for
    *model*: what must match for a hypothesis to 'say the same thing' as the draft."""
    text = text.translate(FOLDS.get(model, FOLDS["ft"]))
    out, clause = [], []

    def close():
        k = len(clause)
        while k > 0 and clause[k - 1] in FINAL_PARTICLES:
            k -= 1
        out.extend(clause[:k])
        clause.clear()

    for ch in text:
        if is_sound(ch):
            clause.append(ch.lower())
        else:
            close()
    close()
    return "".join(out)


COVER_MIN = 0.3        # share of a reference line the draft's cues must cover for it to be "there"
BRACKETS = ("（）", "()", "【】", "［］", "[]", "《》")


def on_screen(text: str) -> bool:
    """A reference line that is written text (a sign, a caption in brackets), not speech."""
    t = text.strip()
    return any(t.startswith(o) and t.endswith(c) for o, c in BRACKETS)


def ref_orphans(cues: list[Cue], refs: list[dict]) -> list[dict]:
    """Reference lines the draft's cues cover for less than COVER_MIN of their length: lines
    the draft may be missing (or a mistimed reference line, whose words a neighbouring cue
    already has). `n` is the line's number in the reference (stable while the reference
    stays), `after` the draft cue before it (0: before the first)."""
    import bisect
    main = [c for c in cues if not c.an8]
    starts = [c.start for c in main]
    mids = [(c.start + c.end) / 2 for c in main]
    out = []
    for k, r in enumerate(refs, 1):
        dur = r["end"] - r["start"]
        if dur <= 0:
            continue
        i = bisect.bisect_left(starts, r["end"])
        cover = sum(max(0.0, min(c.end, r["end"]) - max(c.start, r["start"])) for c in main[max(0, i - 8):i])
        if cover >= COVER_MIN * dur:
            continue
        j = bisect.bisect_left(mids, (r["start"] + r["end"]) / 2)
        after = main[j - 1].pos if j else 0
        out.append({"n": k, "start": r["start"], "end": r["end"], "text": r["text"], "after": after,
                    "on_screen": on_screen(r["text"])})
    return out


def _ref_placement(cues: list[Cue], refs: list[dict]) -> dict[int, list[str]]:
    """Each reference line goes after the cue it overlaps most (or the nearest start). Lines
    no cue covers (ref_orphans) are left out: the review stream shows them on their own."""
    placed: dict[int, list[str]] = {}
    if not cues:
        return placed
    import bisect
    orphans = {o["n"] for o in ref_orphans(cues, refs)}
    starts = [c.start for c in cues]
    for k, r in enumerate(refs, 1):
        if k in orphans:
            continue
        i = bisect.bisect_left(starts, r["end"])
        best, best_ov = None, 0.0
        for c in cues[max(0, i - 6):i + 1]:
            ov = min(c.end, r["end"]) - max(c.start, r["start"])
            if ov > best_ov:
                best, best_ov = c, ov
        if best is None:
            j = min(range(max(0, i - 1), min(len(cues), i + 1)), key=lambda k: abs(cues[k].start - r["start"]))
            if abs(cues[j].start - r["start"]) > 2.0:
                continue
            best = cues[j]
        placed.setdefault(best.pos, []).append(r["text"])
    return placed


def _orphan_line(o: dict) -> str:
    what = "on-screen text" if o["on_screen"] else "no cue here: a missing line?"
    return f"+R#{o['n']} {to_display(o['text'])}  @{short_time(o['start'])}–{short_time(o['end'])}  ({what})"


def particle_preferences(episode_id: str, ep: dict, cues: list[Cue]) -> dict[int, list[str]]:
    """`P` lines: where the fine-tuned recogniser clearly prefers, or leans to, another
    particle than the draft's (`ccp particles model`). Only for a hand-made draft: on one that
    recogniser wrote, it only repeats its own choice."""
    if episode.machine_draft(ep):
        return {}
    rows = episode.read_jsonl(episode_id, "particle_model.jsonl")
    if not rows:
        return {}
    from .particle_scan import model_view
    from .particles import slots
    by = {(r["cue"], r["slot"]): r for r in rows}
    out: dict[int, list[str]] = {}
    for c in cues:
        for s in slots(c.text):
            r = by.get((c.pos, s.index))
            if not r or r.get("run") != s.run:
                continue                   # not scored, or the text changed since
            m = model_view(r, s.run, True)
            if m and m.prefers_other and m.level in ("clear", "lean"):
                how = "clearly prefers" if m.level == "clear" else "leans to"
                out.setdefault(c.pos, []).append(f"the fine-tuned recogniser {how} {m.best} over {s.run}")
    return out


def segment_signals(cues: list[Cue], ep: dict | None = None) -> dict[int, list[str]]:
    """`S` lines, only in the cleanup pass: what to re-cut before its realign, which quick
    exchanges to join after it."""
    from .segment import signals
    if ep is None or not episode.cleanup_pass(ep):
        return {}
    return signals(cues, after_realign=episode.realigned(ep))


def asr_differences(text: str, ev: dict) -> dict[str, dict]:
    """The recognisers (ft, qw) whose hypothesis says something other than *text*: what the
    review stream shows as ≠ lines."""
    out = {}
    for model in MODEL_TAGS:
        hyp = ev.get("asr", {}).get(model)
        if not hyp:
            continue
        full = hyp.get("edge_before", "") + hyp.get("text", "") + hyp.get("edge_after", "")
        if content_key(full, model) != content_key(text, model):
            out[model] = hyp
    return out


def hard_to_hear(ev: dict, differs: bool) -> list[str]:
    """The characters the aligner barely heard, as the review stream shows them (`!`), weakest
    first. Only shown when a recogniser differs too, or when there is no recogniser to compare
    with: where the recognisers agree with the draft they are mostly noise (fast speech, music)
    and only send the agent hunting."""
    weak = [(ch, p) for ch, p, final in ev.get("peaks", []) if not final and p < WEAK_PEAK]
    if not weak or not (differs or not ev.get("asr")):
        return []
    return [ch for ch, _ in sorted(weak, key=lambda x: x[1])[:MAX_WEAK]]


def _asr_line(tag: str, hyp: dict) -> str:
    text = hyp.get("text", "")
    if not (text + hyp.get("edge_before", "") + hyp.get("edge_after", "")).strip():
        return f"{tag} (nothing heard)"
    if hyp.get("edge_before"):
        text = f"[{hyp['edge_before']}]" + text
    if hyp.get("edge_after"):
        text = text + f"[{hyp['edge_after']}]"
    return f"{tag} {to_display(text)}"


def render(episode_id: str, start: int = 1, end: int | None = None, show_groups: bool = False,
           times: bool = True, only: set[str] | None = None) -> str:
    """The review stream for cues *start*..*end*. *only* keeps just the cues with one of those
    tool hints (signals.KINDS: lint, asr, weak, timing), e.g. every lint line in the file."""
    ep = episode.load(episode_id)
    cues = episode.srt(ep).cues
    end = min(end or len(cues), len(cues))
    window = [c for c in cues if start <= c.pos <= end]
    refs = episode.reference_cues(episode_id)
    placed = _ref_placement(cues, refs)
    orphans_after: dict[int, list[dict]] = {}
    for o in ref_orphans(cues, refs):
        orphans_after.setdefault(o["after"], []).append(o)
    seg = segment_signals(cues, ep)
    evidence = {e["cue"]: e for e in episode.read_jsonl(episode_id, "evidence.jsonl")}
    particle_lines = particle_preferences(episode_id, ep, cues)
    groups = {g["group"]: g for g in episode.read_jsonl(episode_id, "groups.jsonl")}
    lint_rows = lint.lint_file(Path(ep["srt"]), ep.get("show_slug"))     # cheap: always fresh
    lint_by: dict[int, list[dict]] = {}
    for r in lint_rows:
        lint_by.setdefault(r["cue"], []).append(r)
    timing_by: dict[int, list[dict]] = {}
    for r in episode.read_jsonl(episode_id, "timing.jsonl"):
        timing_by.setdefault(r["cue"], []).append(r)
    flags_by: dict[int, list[dict]] = {}
    for f in flagstore.load(episode_id):
        flags_by.setdefault(f["cue"], []).append(f)

    out = [f"# {ep['episode_id']}  cues {start}-{end} of {len(cues)}"
           + (f"  (only cues with: {', '.join(sorted(only))})" if only else "")
           + ("" if evidence else
              ("  (text only: machine-made draft, clean it before any audio evidence)"
               if not ep.get("cleanup") else "  (text only: no ASR evidence)")
              if episode.machine_draft(ep) else
              "  (no ASR evidence yet: run `ccp evidence`)")
           + ("" if refs else "  (no reference)")]
    if refs and evidence:
        out.append("# R = what is meant (a fix must agree with it); ≠ft/≠qw = how it sounded "
                   "(they can share a mishearing)")
    last_group = None
    if only:
        def kinds(c):
            ev = evidence.get(c.pos, {})
            differ = asr_differences(c.text, ev)
            return {k for k, on in (("lint", c.pos in lint_by), ("asr", bool(differ)),
                                    ("weak", bool(hard_to_hear(ev, bool(differ)))),
                                    ("timing", c.pos in timing_by), ("seg", c.pos in seg),
                                    ("missing", c.pos in orphans_after)) if on}
        window = [c for c in window if kinds(c) & only]
    if start == 1 and (not only or "missing" in only):
        out += [_orphan_line(o) for o in orphans_after.get(0, [])]
    for k, c in enumerate(window):
        ev = evidence.get(c.pos, {})
        g = ev.get("group")
        if show_groups and g is not None and g != last_group and g in groups:
            gr = groups[g]
            for tag, txt in gr.get("asr", {}).items():
                out.append(f"G{g} {tag} {to_display(txt)}")
        last_group = g
        line = f"{c.pos}|{to_display(c.text)}"
        if c.an8:
            line += "  {an8}"
        opening = list(dict.fromkeys(t for t in c.markup if not t.startswith("</")))
        if opening:
            line += f"  ⟨markup: {' '.join(opening)}⟩"      # hidden from the text; `ccp cue` shows where
        if times:
            line += f"  @{short_time(c.start)}"
        out.append(line)
        for r in placed.get(c.pos, []):
            out.append(f"R {to_display(r)}")
        differ = asr_differences(c.text, ev)
        for model, hyp in differ.items():
            out.append(_asr_line(MODEL_TAGS[model], hyp))
        weak = hard_to_hear(ev, bool(differ))
        if weak:
            out.append("! hard to hear: " + " ".join(weak))
        if ev.get("speaker_change"):
            out.append(">> speaker change")
        for r in timing_by.get(c.pos, []):
            out.append(f"T realign doubts this cue's timing: {r['reason']}")
        for r in lint_by.get(c.pos, []):
            sug = f"→{r['suggest']}" if r.get("suggest") else ""
            out.append(f"L {r['kind']} {to_display(r['found'])}{sug}" + (f"  ({r['note']})" if r.get("note") and r['kind'] != 'standard_written_chinese' else ""))
        for note in particle_lines.get(c.pos, []):
            out.append(f"P {note}")
        for note in seg.get(c.pos, []):
            out.append(f"S {note}")
        for f in flags_by.get(c.pos, []):
            if f.get("insert") and f["status"] != "applied":
                continue                           # shown with its reference line below
            prop = f" → {to_display(f['proposed'])}" if f.get("proposed") is not None else ""
            out.append(f"F#{f['id']} {f['grade']}/{f['category']}/{f['status']}{prop}")
        for o in orphans_after.get(c.pos, []):
            out.append(_orphan_line(o))
            for f in flags_by.get(c.pos, []):
                if f.get("insert") and f["status"] != "applied" and f.get("ref") == o["n"]:
                    out.append(f"F#{f['id']} {f['grade']}/missing/{f['status']} + "
                               + to_display(" // ".join(x["text"] for x in f.get("proposed_cues") or [])))
        if only:
            out.append("")              # filtered cues are not neighbours: no pause marks
        elif k + 1 < len(window):
            gap = window[k + 1].start - c.end
            if gap >= SCENE_S:
                out.append("==")
            elif gap >= PAUSE_S:
                out.append("--")
    return "\n".join(out)
