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
  * otherwise: flags graded `fix` (and `suggest` too with --include-suggest). Never particle
    flags (their measured precision is poor), and never structural flags unless --structure is
    given: re-timing and splitting need the user's go-ahead. --include names flags to apply
    regardless.
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
    flags = {f["id"]: f for f in flagstore.load(episode_id)}
    chosen: list[dict] = []

    def pick(f, kind, text, expect):
        chosen.append({"flag": f, "kind": kind, "text": text, "expect": expect})

    if only is not None:
        for i in only:
            f = flags.get(i)
            if f and f["status"] not in ("rejected", "applied") and f.get("proposed") is not None:
                pick(f, "text", f["proposed"], f["draft"])
        return chosen

    if decisions:
        data = json.loads(Path(decisions).read_text(encoding="utf-8"))
        for d in data.get("decisions", []):
            f = flags.get(int(d["flag"]))
            if f is None:
                continue
            already = f["status"] == "applied"
            if d["decision"] == "rejected":
                if already and not f.get("proposed_cues"):
                    # The reviewer rejects a correction the agent already applied: undo it.
                    pick(f, "revert", f["draft"], f.get("applied_text"))
                else:
                    f["status"] = "rejected"
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
    for f in flags.values():
        if f["status"] in ("rejected", "applied", "kept"):
            continue
        has_fix = f.get("proposed") is not None or bool(f.get("proposed_cues"))
        kind = "structure" if f.get("proposed_cues") else "text"
        if f["id"] in include:
            if has_fix:
                pick(f, kind, f.get("proposed"), f["draft"])
            continue
        if (not has_fix or f["category"] == "particle" or f["grade"] not in grades
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
    shifts: list[tuple[int, int]] = []          # (cue position, cues added after it)
    # Last cue first, so a split never moves a cue that is still to be edited.
    reverted = []
    for item in sorted(chosen, key=lambda x: -x["flag"]["cue"]):
        f, kind, text = item["flag"], item["kind"], item["text"]
        cue = srt.cue(f["cue"])
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
                shifts.append((f["cue"], len(new) - 1))
            applied.append({"flag": f["id"], "cue": f["cue"], "from": f["draft"],
                            "to": [f"{c['start']:.3f}-{c['end']:.3f} {c['text']}" for c in f["proposed_cues"]]})
        else:
            if text == cue.text:
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
    if dry_run or not (applied or reverted):
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
    undone = {r["flag"] for r in reverted}
    for fl in all_flags:
        if fl["id"] in done:
            fl["status"] = "applied"
            fl["applied_text"] = done[fl["id"]]
        if fl["id"] in undone:
            fl["status"] = "rejected"
            fl.pop("applied_text", None)
            fl["reverted"] = True
        # Flags on later cues move down by the cues a split inserted before them.
        fl["cue"] += sum(n for c, n in shifts if fl["cue"] > c)
    flagstore.save(episode_id, all_flags)
    if episode.draft_is_source(ep):
        try:
            stat = subprocess.run(["git", "-C", str(paths.get("cantocaptions")), "diff", "--stat", "--", str(path)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            result["git_diff_stat"] = stat.stdout.strip()
        except Exception:
            pass
    return result
