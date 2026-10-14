"""The review stream: one window of cues as plain text, with every piece of evidence
placed under the cue it belongs to. Format (see the proofread-subtitles skill):

    37|阿媽食多都亂瞓唔着㗎  @3:21.5
    R 媽媽一定坐立不安睡不著的
    ≠ft 你阿媽食多多亂瞓唔着㗎
    ≠qw [你]阿媽食攞攞攣，瞓唔著嘅
    ! 多 0.00  都 0.00
    L variant 俾→畀
    F#3 essential/mishearing → 阿媽實囉囉攣瞓唔着㗎
    --
"""
from __future__ import annotations

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
VARIANT_FOLD = {"裡": "裏", "說": "説", "爲": "為", "搵": "揾", "俾": "畀", "地": "哋"}
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


def _ref_placement(cues: list[Cue], refs: list[dict]) -> dict[int, list[str]]:
    """Each reference line goes after the cue it overlaps most (or the nearest start)."""
    placed: dict[int, list[str]] = {}
    if not cues:
        return placed
    import bisect
    starts = [c.start for c in cues]
    for r in refs:
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
           times: bool = True) -> str:
    ep = episode.load(episode_id)
    cues = episode.srt(ep).cues
    end = min(end or len(cues), len(cues))
    window = [c for c in cues if start <= c.pos <= end]
    refs = episode.reference_cues(episode_id)
    placed = _ref_placement(cues, refs)
    evidence = {e["cue"]: e for e in episode.read_jsonl(episode_id, "evidence.jsonl")}
    groups = {g["group"]: g for g in episode.read_jsonl(episode_id, "groups.jsonl")}
    if episode.path(episode_id, "lint.jsonl").exists():
        lint_rows = episode.read_jsonl(episode_id, "lint.jsonl")
    else:
        from pathlib import Path
        lint_rows = lint.lint_file(Path(ep["srt"]), ep.get("show_slug"))
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
        if times:
            line += f"  @{short_time(c.start)}"
        out.append(line)
        for r in placed.get(c.pos, []):
            out.append(f"R {to_display(r)}")
        differs = False
        for model, tag in MODEL_TAGS.items():
            hyp = ev.get("asr", {}).get(model)
            if not hyp:
                continue
            full = (hyp.get("edge_before", "") + hyp.get("text", "") + hyp.get("edge_after", ""))
            if content_key(full, model) != content_key(c.text, model):
                out.append(_asr_line(tag, hyp))
                differs = True
        weak = [(ch, p) for ch, p, final in ev.get("peaks", []) if not final and p < WEAK_PEAK]
        # A lone weak character where both recognisers agree with the draft is mostly noise
        # (fast speech, music); show weak characters when they corroborate something.
        if weak and (differs or len(weak) >= 2):
            weak = sorted(weak, key=lambda x: x[1])[:MAX_WEAK]
            out.append("! " + "  ".join(f"{ch} {p:.2f}" for ch, p in weak))
        if ev.get("speaker_change"):
            out.append(">> speaker change")
        for r in timing_by.get(c.pos, []):
            out.append(f"T realign doubts this cue's timing: {r['reason']}")
        for r in lint_by.get(c.pos, []):
            sug = f"→{r['suggest']}" if r.get("suggest") else ""
            out.append(f"L {r['kind']} {to_display(r['found'])}{sug}" + (f"  ({r['note']})" if r.get("note") and r['kind'] != 'standard_written_chinese' else ""))
        for f in flags_by.get(c.pos, []):
            prop = f" → {to_display(f['proposed'])}" if f.get("proposed") is not None else ""
            out.append(f"F#{f['id']} {f['severity']}/{f['category']}/{f['status']}{prop}")
        if k + 1 < len(window):
            gap = window[k + 1].start - c.end
            if gap >= SCENE_S:
                out.append("==")
            elif gap >= PAUSE_S:
                out.append("--")
    return "\n".join(out)
