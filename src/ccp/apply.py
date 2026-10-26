"""ccp apply: write accepted corrections into the working draft, in place.

The working draft is the episode's subtitle in CantoCaptions, unless `ccp pipeline` produced
a new one (work/<id>/draft.srt); then corrections go into that copy and `ccp publish` puts it
into CantoCaptions later. Nothing is ever committed.

Text corrections change only the text lines of their cues: timings, counters, BOM, line
endings and every untouched line stay byte-identical, so `git diff` shows exactly the
corrections. Structural corrections (flags with proposed_cues: a retime or a split) replace
the whole cue block; after a split the counters are rewritten in the file's own style
(sequential, or start-time milliseconds). A flag whose cue changed since it was made is
skipped.

Selection:
  * with --decisions (exported from report.html): exactly the accepted flags, using the text
    the reviewer left in the box (structural flags are applied as proposed);
  * otherwise: flags graded `fix` (and `suggest` too with --include-suggest). A particle flag
    only as a fix that carries the standards' meaning and an independent signal
    (flags.particle_fix_problems: the rule every particle fix is recorded under now); older
    particle records, made when their precision was poor, never. Never structural flags unless
    --structure is given: re-timing and splitting need the user's go-ahead. --include names
    flags to apply regardless.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import episode, flags as flagstore, paths
from .srtio import SrtFile, from_display



def _lint(path: Path) -> list[str]:
    script = paths.get("cantocaptions") / ".github" / "scripts" / "srtfmt.py"
    if not script.exists():
        return []
    proc = subprocess.run([sys.executable, str(script), "--lint", str(path)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    lines = (proc.stdout + proc.stderr).splitlines()
    return [ln.split(":", 2)[-1].strip() if str(path) in ln else ln.strip() for ln in lines if ln.strip()]


def select(episode_id: str, decisions: Path | None, include_suggest: bool,
           include: list[int], structure: bool, only: list[int] | None = None) -> list[dict]:
    """[{flag, kind: text|structure|revert, text, expect}]: *expect* is the cue text the edit
    must find (the draft, or for an already-applied flag the text it applied). *only*: exactly
    these open flags (ccp clean)."""
    from . import rounds
    flags = {f["id"]: f for f in flagstore.load(episode_id)}
    this_round = rounds.current(episode_id)
    chosen: list[dict] = []

    def pick(f, kind, text, expect):
        chosen.append({"flag": f, "kind": kind, "text": text, "expect": expect})

    if only is not None:
        for i in only:
            f = flags.get(i)
            if f and f["status"] not in ("rejected", "applied") and f.get("remove"):
                pick(f, "delete", None, f["draft"])
            elif f and f["status"] not in ("rejected", "applied") and f.get("proposed_cues"):
                pick(f, "structure", None, f["draft"])
            elif f and f["status"] not in ("rejected", "applied") and f.get("proposed") is not None:
                pick(f, "text", f["proposed"], f["draft"])
        return chosen

    if decisions:
        data = json.loads(Path(decisions).read_text(encoding="utf-8"))
        for d in data.get("decisions", []):
            f = flags.get(int(d["flag"]))
            if f is None or f["round"] != this_round:     # an earlier round's, already acted on
                continue
            already = f["status"] == "applied"
            # The reviewer's verdict, kept for the pass statistics: they agreed, reworded the
            # change, turned it down, or corrected a line the agent had kept.
            reviewer_text = from_display(d["text"]) if d.get("text") else None
            if d["decision"] == "rejected":
                f["review"] = "rejected"
            elif f["grade"] == "keep":
                f["review"] = "corrected"
            elif reviewer_text and reviewer_text != f.get("proposed"):
                f["review"] = "edited"
            else:
                f["review"] = "accepted"
            if d["decision"] == "rejected":
                if already and f.get("remove"):
                    # A line the cleanup took out: put it back where it was.
                    pick(f, "undelete", None, None)
                elif already and f.get("insert"):
                    # An inserted line the reviewer does not want: take it out again.
                    pick(f, "remove", None, f.get("applied_text"))
                elif already and not f.get("proposed_cues"):
                    # The reviewer rejects a correction the agent already applied: undo it.
                    pick(f, "revert", f["draft"], f.get("applied_text"))
                elif not already:
                    f["status"] = "rejected"
                else:
                    # An applied regrouping stays: the realign after it timed every cue anew.
                    pick(f, "keep_regroup", None, None)
                continue
            if f.get("proposed_cues"):
                if not already:
                    pick(f, "structure", None, f["draft"])
                continue
            text = from_display(d["text"]) if d.get("text") else f.get("proposed")
            if not text:
                continue
            if already:
                if text != f.get("applied_text"):
                    pick(f, "text", text, f.get("applied_text"))      # the reviewer's own wording
            else:
                pick(f, "text", text, f["draft"])
        flagstore.save(episode_id, sorted(flags.values(), key=lambda f: (f["cue"], f["id"])))
        return chosen
    grades = ("fix", "suggest") if include_suggest else ("fix",)
    ep = episode.load(episode_id)
    for f in flags.values():
        if f["status"] in ("rejected", "applied", "kept"):
            continue
        has_fix = f.get("proposed") is not None or bool(f.get("proposed_cues")) or bool(f.get("remove"))
        kind = "delete" if f.get("remove") else "structure" if f.get("proposed_cues") else "text"
        if f["id"] in include:
            if has_fix:
                pick(f, kind, f.get("proposed"), f["draft"])
            continue
        particle_ok = (f["category"] != "particle"
                       or (f["grade"] == "fix" and not flagstore.particle_fix_problems(ep, f)))
        if (not has_fix or not particle_ok or f["grade"] not in grades
                or (kind == "structure" and not structure)):
            continue
        pick(f, kind, f.get("proposed"), f["draft"])
    return chosen


def apply(episode_id: str, decisions: Path | None = None, include_suggest: bool = False,
          include: list[int] = (), dry_run: bool = False, structure: bool = False,
          only: list[int] | None = None) -> dict:
    ep = episode.load(episode_id)
    path = Path(ep["srt"])
    srt = SrtFile(path)
    style = srt.numbering()
    chosen = select(episode_id, decisions, include_suggest, list(include), structure, only)
    before_lint = _lint(path)
    applied, skipped = [], []
    # (position, change): every flag on a cue after that position moves by the change (cues
    # added by a split or an insert, taken away by a merge or a removed line).
    shifts: list[tuple[int, int, int]] = []   # (position, change, flag id)
    inserted: dict[int, int] = {}               # flag id -> position of its new cue
    # Last cue first, so a split never moves a cue that is still to be edited (an insert sits
    # between its cue and the next).
    reverted, removed, restored = [], [], []
    not_undone = [{"flag": x["flag"]["id"], "cue": x["flag"]["cue"]} for x in chosen if x["kind"] == "keep_regroup"]
    chosen = [x for x in chosen if x["kind"] != "keep_regroup"]
    for item in sorted(chosen, key=lambda x: -(x["flag"]["cue"] + (0.5 if x["flag"].get("insert") else 0))):
        f, kind, text = item["flag"], item["kind"], item["text"]
        if kind == "structure" and f.get("insert"):
            if f["cue"] > len(srt.cues):
                skipped.append({"flag": f["id"], "cue": f["cue"], "reason": "the cue it follows is gone"})
                continue
            new = [(c["start"], c["end"], c["text"]) for c in f["proposed_cues"]]
            srt.insert_after(f["cue"], new)
            shifts.append((f["cue"], len(new), f["id"]))
            inserted[f["id"]] = f["cue"] + 1
            applied.append({"flag": f["id"], "cue": f["cue"], "from": "(no line)",
                            "to": [f"{c['start']:.3f}-{c['end']:.3f} {c['text']}" for c in f["proposed_cues"]]})
            continue
        if kind == "undelete":
            srt.insert_after(f["cue"], [(f["start"], f["end"], f["draft"])])
            shifts.append((f["cue"], 1, f["id"]))
            restored.append({"flag": f["id"], "cue": f["cue"] + 1, "text": f["draft"]})
            continue
        cue = srt.cue(f["cue"])
        if kind == "delete":
            if cue.text != item["expect"]:
                skipped.append({"flag": f["id"], "cue": f["cue"], "reason": "cue changed since the flag was made"})
                continue
            srt.delete_cue(f["cue"])
            shifts.append((f["cue"], -1, f["id"]))
            applied.append({"flag": f["id"], "cue": f["cue"], "from": cue.text, "to": "(removed)"})
            continue
        if kind == "remove":
            if cue.text != item["expect"]:
                skipped.append({"flag": f["id"], "cue": f["cue"], "reason": "the inserted line changed since"})
                continue
            srt.delete_cue(f["cue"])
            shifts.append((f["cue"], -1, f["id"]))
            removed.append({"flag": f["id"], "cue": f["cue"], "text": cue.text})
            continue
        if f.get("span") and kind == "structure":
            first, last = f["span"]
            now = [{"start": c.start, "end": c.end, "text": c.text} for c in srt.cues[first - 1:last]]
            same = len(now) == len(f["draft_cues"]) and all(
                a["text"] == b["text"] and abs(a["start"] - b["start"]) <= 0.002 and abs(a["end"] - b["end"]) <= 0.002
                for a, b in zip(now, f["draft_cues"]))
            if not same:
                skipped.append({"flag": f["id"], "cue": f["cue"], "reason": "cues changed since the flag was made"})
                continue
            new = [(c["start"], c["end"], c["text"]) for c in f["proposed_cues"]]
            srt.replace_cues(first, last, new)
            if len(new) != last - first + 1:
                shifts.append((last, len(new) - (last - first + 1), f["id"]))
            applied.append({"flag": f["id"], "cue": f["cue"], "from": f["draft"],
                            "to": [f"{c['start']:.3f}-{c['end']:.3f} {c['text']}" for c in f["proposed_cues"]]})
            continue
        unchanged = cue.text == item["expect"]
        if kind != "revert" and f["status"] != "applied":
            unchanged = unchanged and abs(cue.start - f["start"]) <= 0.002 and abs(cue.end - f["end"]) <= 0.002
        if not unchanged:
            skipped.append({"flag": f["id"], "cue": f["cue"], "reason": "cue changed since the flag was made"})
            continue
        if kind == "structure":
            new = [(c["start"], c["end"], c["text"]) for c in f["proposed_cues"]]
            srt.replace_cue(f["cue"], new)
            if len(new) > 1:
                shifts.append((f["cue"], len(new) - 1, f["id"]))
            applied.append({"flag": f["id"], "cue": f["cue"], "from": f["draft"],
                            "to": [f"{c['start']:.3f}-{c['end']:.3f} {c['text']}" for c in f["proposed_cues"]]})
        else:
            # Invisible characters (a zero-width space...) go without touching the markup.
            stripped = srt.strip_invisible(f["cue"]) if f.get("strip_invisible") and kind != "revert" else 0
            if text == cue.text:
                if stripped:
                    applied.append({"flag": f["id"], "cue": f["cue"], "from": f.get("draft_shown", item["expect"]),
                                    "to": text})
                else:
                    skipped.append({"flag": f["id"], "cue": f["cue"], "reason": "no change"})
                continue
            srt.set_text(f["cue"], text)
            if kind == "revert":
                reverted.append({"flag": f["id"], "cue": f["cue"], "from": cue.text, "to": text})
            else:
                applied.append({"flag": f["id"], "cue": f["cue"], "from": item["expect"], "to": text})
    target = ("the source file (in place)" if episode.draft_is_source(ep) else
              "the working draft (publish it with `ccp publish`)" if ep.get("source_srt") else
              "the working draft (hand it back with `ccp export`)")
    result = {"file": str(path), "edited": target, "applied": applied, "skipped": skipped, "dry_run": dry_run}
    if reverted:
        result["reverted"] = reverted
    if removed:
        result["removed"] = removed
    if restored:
        result["restored"] = restored
    if not_undone:
        result["not_undone"] = {"regroups": not_undone,
                                "why": "a re-cut that the realign has since timed cannot be undone on its own; "
                                       "tell the reviewer, and re-cut those cues again with `ccp segment` if they want"}
    if dry_run or not (applied or reverted or removed or restored):
        return result
    if shifts:
        srt.renumber("ms" if style == "ms" else "sequential")
        result["renumbered"] = "start-time milliseconds" if style == "ms" else "sequential"
    srt.save()
    after_lint = _lint(path)
    new = [w for w in after_lint if w not in before_lint]
    if new:
        result["new_lint_warnings"] = new
    all_flags = flagstore.load(episode_id)
    done = {a["flag"]: a["to"] for a in applied}
    undone = {r["flag"] for r in reverted} | {r["flag"] for r in removed} | {r["flag"] for r in restored}
    for fl in all_flags:
        if fl["id"] in done:
            fl["status"] = "applied"
            fl["applied_text"] = done[fl["id"]]
        if fl["id"] in undone:
            fl["status"] = "rejected"
            fl.pop("applied_text", None)
            fl["reverted"] = True
        def moved(base: int) -> int:
            return sum(n for c, n, fid in shifts if base > c and fid != fl["id"])
        if fl["id"] in inserted:
            # From now on the record points at the line it added (a removal looks for it there).
            fl["applied_text"] = fl["proposed_cues"][0]["text"]
            fl["cue"] = inserted[fl["id"]] + moved(inserted[fl["id"]])
            continue
        if fl.get("remove") and fl["id"] in done:
            fl["cue"] = fl["cue"] - 1 + moved(fl["cue"])     # it now marks the cue the line followed
            continue
        if fl.get("remove") and fl["id"] in undone:
            fl["cue"] = fl["cue"] + 1 + moved(fl["cue"] + 1)  # the restored line
            continue
        if fl.get("insert") and fl["id"] in undone:
            fl["cue"] = fl["cue"] - 1 + moved(fl["cue"])     # back to the cue it followed
            continue
        # Flags on later cues move by the cues added or taken away before them.
        delta = moved(fl["cue"])
        fl["cue"] += delta
        if fl.get("span") and fl["id"] in done:
            fl["span"] = [fl["cue"], fl["cue"] + len(fl["proposed_cues"]) - 1]
        elif fl.get("span") and delta:
            fl["span"] = [x + delta for x in fl["span"]]
    flagstore.save(episode_id, all_flags)
    if episode.draft_is_source(ep):
        try:
            stat = subprocess.run(["git", "-C", str(paths.get("cantocaptions")), "diff", "--stat", "--", str(path)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            result["git_diff_stat"] = stat.stdout.strip()
        except Exception:
            pass
    return result
