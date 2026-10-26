"""Run cantocaptions-ai on an episode and make its output the working draft.

    realign     put an existing transcript or subtitle (by default the episode's source file)
                on the recording's timeline: `cantocaptions MEDIA --realign FILE --realign_mode M`
    transcribe  transcribe the episode from scratch (ASR) into a new draft

The command runs from cantocaptions-ai's own directory, so the user's config/user.cfg there
applies (vocal isolation, diarization, batch size...), exactly as when they run it by hand.
Output and the debug directory go into the workspace (work/<id>/pipeline/<run>/), never into
cantocaptions-ai or CantoCaptions. The resulting SRT becomes work/<id>/draft.srt: the source
file is not touched until `ccp publish`.

A realign run also leaves `realign/suspect.srt`: the cues whose placement it does not trust,
each with a reason. Those become work/<id>/timing.jsonl and show up as `T` lines in
`ccp render` and `ccp cue`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import episode, flags as flagstore, paths, signals
from .srtio import SrtFile

MODES = ["auto", "transcript", "sync", "adjust"]
NOISE = ("it/s]", "s/it]", "%|", "Warning", "warn(", "Loading weights")


def _cmd(ep: dict, run_dir: Path, extra: list[str]) -> list[str]:
    return (["uv", "run", "--project", str(paths.get("cantocaptions_ai")), "--no-sync", "cantocaptions",
             ep["media"], "--audio_track", str(ep.get("audio_track", 0)),
             "--output_dir", str(run_dir), "--output_format", "srt",
             "--debug_dir", str(run_dir / "debug")] + extra)


def _run(cmd: list[str], log_path: Path) -> int:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONIOENCODING"] = "utf-8"
    ccai = paths.get("cantocaptions_ai")
    with open(log_path, "w", encoding="utf-8") as log, subprocess.Popen(
            cmd, cwd=str(ccai), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace") as proc:
        for line in proc.stdout:
            log.write(line)
            for part in line.replace("\r", "\n").splitlines():
                part = part.rstrip()
                if part.strip() and not any(n in part for n in NOISE):
                    print(f"  [cantocaptions] {part}", file=sys.stderr, flush=True)
        return proc.wait()


def _timing_notes(ep_id: str, run_dir: Path, draft: Path) -> int:
    """realign/suspect.srt -> timing.jsonl: one row per draft cue the realign doubts."""
    suspects = list((run_dir / "debug").rglob("suspect.srt"))
    rows = []
    if suspects:
        cues = SrtFile(draft).cues
        by_time = {(round(c.start, 2), round(c.end, 2)): c.pos for c in cues}
        for s in SrtFile(suspects[0]).cues:
            m = re.match(r"^\[([^\]]+)\]\s*", s.text)
            reason = m.group(1) if m else "suspect"
            pos = by_time.get((round(s.start, 2), round(s.end, 2)))
            if pos is None:   # nearest start as a fallback
                near = min(cues, key=lambda c: abs(c.start - s.start))
                pos = near.pos if abs(near.start - s.start) < 0.05 else None
            if pos is not None:
                rows.append({"cue": pos, "kind": "realign_suspect", "reason": reason})
    episode.write_jsonl(ep_id, "timing.jsonl", rows)
    return len(rows)


def run(episode_id: str, kind: str, mode: str = "adjust", input_path: str | None = None,
        extra: list[str] = (), force: bool = False) -> dict:
    ep = episode.load(episode_id)
    if not ep.get("media_exists"):
        raise SystemExit("this workspace has no media; give it with `ccp locate ... --media PATH`")
    if not paths.has("cantocaptions_ai"):
        raise SystemExit(f"`ccp pipeline {kind}` runs cantocaptions-ai, which is not set up on this "
                         "machine (see `ccp setup`). Without it there is no realign or transcription: "
                         "proofread the existing subtitle text-only, or tell the user.")
    applied =[f for f in flagstore.load(episode_id) if f["status"] == "applied"]
    # Realigning the draft itself carries its corrections into the new draft, so nothing is lost.
    carries = kind == "realign" and input_path == "draft"
    if applied and not episode.draft_is_source(ep) and not carries and not force:
        raise SystemExit(f"the current working draft has {len(applied)} applied corrections that a new "
                         "pipeline run would set aside (they stay in previous/). Publish them first, "
                         "realign the draft itself with --input draft, or pass --force.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    flags: list[str] = []
    notes: list[str] = []
    if kind == "realign":
        src = (ep["srt"] if input_path == "draft" else input_path) or ep.get("source_srt")
        if not src or not Path(src).exists():
            raise SystemExit("nothing to realign: this workspace has no source subtitle (give --input FILE)")
        flags = ["--realign", str(Path(src).resolve()), "--realign_mode", mode]
        if carries and ep.get("segmentation") and mode == "adjust" and not any(
                x.startswith("--realign_split") for x in extra):
            # The agent has decided where every cue is cut: the realign times them, it does
            # not cut them again at its own pauses.
            flags += ["--realign_split", "off"]
            notes.append("the draft was re-segmented, so the realign keeps its cues as they are "
                         "(--realign_split off)")
        run_dir = episode.path(episode_id, "pipeline") / f"realign-{mode}-{stamp}"
    elif kind == "transcribe":
        src = None
        run_dir = episode.path(episode_id, "pipeline") / f"transcribe-{stamp}"
    else:
        raise ValueError(kind)
    run_dir.mkdir(parents=True)
    cmd = _cmd(ep, run_dir, flags + list(extra))
    (run_dir / "command.txt").write_text(" ".join(f'"{c}"' if " " in c else c for c in cmd), encoding="utf-8")
    print(f"  [pipeline] {kind}" + (f" ({mode})" if kind == "realign" else "")
          + f" on {Path(ep['media']).name}; this takes several minutes", file=sys.stderr, flush=True)
    t0 = time.time()
    code = _run(cmd, run_dir / "run.log")
    outputs = [p for p in run_dir.glob("*.srt")]
    if code != 0 or not outputs:
        tail = (run_dir / "run.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
        raise SystemExit(f"cantocaptions-ai failed (exit {code}); full log: {run_dir / 'run.log'}\n" + "\n".join(tail))
    out = max(outputs, key=lambda p: p.stat().st_mtime)
    origin = {"kind": kind, "mode": mode if kind == "realign" else None, "input": str(src) if src else None,
              "run_dir": str(run_dir), "output": str(out), "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    if carries and episode.machine_draft(ep):
        origin["machine"] = True          # still the models' text, however much it was cleaned
    if carries and applied:
        origin["carried_corrections"] = len(applied)
    if carries:
        for key in ("cleanup", "segmentation"):
            if ep.get(key):
                origin[key] = ep[key]
    old_cues = SrtFile(Path(ep["srt"])).cues if carries else []
    old_records = flagstore.load(episode_id) if carries else []
    old_signals = signals.load(episode_id) if carries else {}
    moved = episode.set_draft(ep, out, origin)
    draft = Path(moved["draft"])
    n_suspect = _timing_notes(episode_id, run_dir, draft) if kind == "realign" else 0
    result = {"status": "ok", "kind": kind, "mode": origin["mode"], "seconds": round(time.time() - t0),
              "draft": str(draft), "cues": len(SrtFile(draft).cues), "run_dir": str(run_dir),
              "moved_to_previous": moved["moved_to_previous"]}
    if notes:
        result["notes"] = notes
    if old_records or old_signals:
        result["records_carried"] = carry_records(episode_id, old_cues, SrtFile(draft).cues,
                                                  old_records, old_signals)
    if src and Path(src).exists():
        result["input_cues"] = len(SrtFile(Path(src)).cues)
    if kind == "realign":
        result["timing_suspects"] = n_suspect
    if episode.path(episode_id, "reference.srt").exists():
        from . import reference
        ref = reference.measure(episode_id)
        result["reference_agreement"] = ref.get("agreement")
    result["next"] = ("run `ccp evidence <id>` on the new draft, then proofread it; corrections go into "
                      "the draft, and " + ("`ccp publish <id>` puts it into CantoCaptions once the user agrees"
                                           if ep.get("source_srt") else "`ccp export <id>` hands it back"))
    return result


def cue_mapping(old: list, new: list) -> dict[int, int]:
    """Old cue position -> new cue position across a realign of the draft itself. The realign
    keeps every cue's text and order (it can drop a cue the recording lacks, and outside a
    re-segmented draft split one at a pause), so the texts are lined up in sequence; a split
    cue maps to its first piece."""
    import difflib
    a = [c.text for c in old]
    b = [c.text for c in new]
    out: dict[int, int] = {}
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.update({old[i1 + k].pos: new[j1 + k].pos for k in range(i2 - i1)})
            continue
        # A cue split at a pause: its pieces spell it out in order.
        j = j1
        for i in range(i1, i2):
            joined = ""
            for jj in range(j, j2):
                joined += b[jj].replace("\n", "")
                if joined == a[i].replace("\n", ""):
                    out[old[i].pos] = new[j].pos
                    j = jj + 1
                    break
                if not a[i].replace("\n", "").startswith(joined):
                    break
    return out


def carry_records(episode_id: str, old_cues: list, new_cues: list, records: list[dict],
                  sig: dict[int, dict]) -> dict:
    """Put the records (and the tool signals) of the draft that was just realigned onto the new
    draft, so the report shows every cleanup edit, regrouping and inserted line at its new
    time. The old copies stay in previous/. Records on a cue the realign dropped stay there
    only."""
    from . import signals as sigstore
    m = cue_mapping(old_cues, new_cues)
    by_pos = {c.pos: c for c in new_cues}
    kept, lost = [], []
    for f in records:
        if f.get("insert") and f["status"] != "applied":
            new_pos = m.get(f["cue"], 0) if f["cue"] else 0       # still waiting to go in after its cue
            if f["cue"] and not new_pos:
                lost.append(f["id"])
                continue
            f["cue"] = new_pos
            kept.append(f)
            continue
        new_pos = m.get(f["cue"])
        if new_pos is None:
            lost.append(f["id"])
            continue
        c = by_pos[new_pos]
        if f.get("span"):
            n = f["span"][1] - f["span"][0]
            f["span"] = [new_pos, new_pos + n]
            if f["status"] == "applied":
                f["realigned"] = True       # its times are the realign's now; it stays as it is
            else:
                f["draft_cues"] = [{"start": x.start, "end": x.end, "text": x.text}
                                   for x in new_cues[new_pos - 1:new_pos + n]]
        f["cue"], f["start"], f["end"] = new_pos, c.start, c.end
        kept.append(f)
    flagstore.save(episode_id, sorted(kept, key=lambda f: (f["cue"], f["id"])))
    if sig:
        moved = {m[p]: v for p, v in sig.items() if p in m}
        episode.path(episode_id, sigstore.FILE).write_text(
            json.dumps({str(k): v for k, v in sorted(moved.items())}, ensure_ascii=False), encoding="utf-8")
    out = {"records": len(kept)}
    if lost:
        out["not_carried"] = {"flags": lost, "why": "their cues are gone from the realigned draft (the recording "
                                                    "lacks them); the records are kept in previous/"}
    return out


def _library_name(name: str) -> str:
    """A library-style file name: leading tags such as [CCAI] / [AIGEN V2] / [WIP] dropped,
    ending in .yue.cht.srt."""
    stem = re.sub(r"^(\[[^\]]*\]\s*)+", "", name)
    stem = re.sub(r"\.srt$", "", stem, flags=re.I)
    if not re.search(r"\.(yue\.cht|cht\.yue|yue)$", stem, re.I):
        stem += ".yue.cht"
    return stem + ".srt"


def main_area_path(ep: dict, name: str | None = None) -> tuple[Path, list[str]]:
    """Where an AI-generated (or WIP) episode belongs in the main library: the same category
    and tree without "(AI-generated)", the same show (an existing folder for it if there is
    one), the same season sub-folders (genre folders dropped), a library-style file name."""
    from .locate import AI_TREE, show_names
    root = paths.get("subtitles")
    src = Path(ep["source_srt"])
    try:
        parts = src.relative_to(root).parts
    except ValueError:
        raise SystemExit("--to-main needs a source file inside CantoCaptions/Subtitles"
                         + ("" if paths.has("subtitles") else " (no CantoCaptions library on this machine)")
                         + "; use --to PATH")
    category, tree = parts[0], parts[1].replace(AI_TREE, "")
    show = ep.get("show_folder") or parts[2]
    inner = parts[2:-1]
    sub = inner[inner.index(show) + 1:] if show in inner else ()
    notes = []
    tree_dir = root / category / tree
    folder = show
    existing = [d.name for d in tree_dir.iterdir() if d.is_dir() and show_names(d.name) & show_names(show)] \
        if tree_dir.is_dir() else []
    if existing:
        folder = existing[0]
        notes.append(f"uses the existing main-area folder {folder!r}")
    else:
        notes.append(f"creates a new folder {category}/{tree}/{folder}")
    return root / category / tree / folder / Path(*sub) / (name or _library_name(src.name)), notes


def publish(episode_id: str, to: str | None = None, dry_run: bool = False, to_main: bool = False,
            name: str | None = None, overwrite: bool = False) -> dict:
    """Copy the working draft over the source file, to *to*, or into the main library area
    (*to_main*). The agent must have the user's go-ahead: this is the step that changes
    CantoCaptions. An existing file other than the source is never overwritten without
    *overwrite*."""
    ep = episode.load(episode_id)
    notes: list[str] = []
    if to_main:
        target, notes = main_area_path(ep, name)
    elif to:
        target = Path(to)
        if target.is_dir() or not target.suffix:
            target = target / (name or _library_name(Path(ep.get("source_srt") or ep["srt"]).name))
    else:
        if episode.draft_is_source(ep):
            return {"status": "nothing to publish: the draft is the source file itself (edits were applied in place)"}
        target = Path(ep["source_srt"]) if ep.get("source_srt") else None
        if target is None:
            raise SystemExit("no source file to replace; give --to PATH")
    draft = Path(ep["srt"])
    replacing_source = ep.get("source_srt") and target.resolve() == Path(ep["source_srt"]).resolve()
    if target.exists() and not replacing_source and not overwrite:
        return {"status": "refused: the target already exists and is not this episode's source file",
                "to": str(target), "hint": "ask the user; --overwrite replaces it, --name picks another file name"}
    result = {"from": str(draft), "to": str(target), "replaces_existing": target.exists(),
              "cues": len(SrtFile(draft).cues), "dry_run": dry_run}
    if notes:
        result["notes"] = notes
    if ep.get("ai_generated") and not replacing_source:
        result["warning"] = ("This file started as AI-generated subtitles. Outside the '(AI-generated)' "
                             "trees, cantocaptions-dataset will treat it as hand-made ground truth unless it "
                             "is excluded (a name containing AIGEN, or an exclude glob in "
                             "cantocaptions-dataset/config/corpus.toml). Tell the user.")
    if target.exists():
        result["cues_before"] = len(SrtFile(target).cues)
    if dry_run:
        return result
    data = draft.read_bytes()
    if target.exists():
        # Keep the library file's conventions: BOM and line endings.
        old_bytes = target.read_bytes()
        bom = b"\xef\xbb\xbf"
        body = (data[3:] if data.startswith(bom) else data).replace(b"\r\n", b"\n")
        if b"\r\n" in old_bytes:
            body = body.replace(b"\n", b"\r\n")
        data = (bom if old_bytes.startswith(bom) else b"") + body
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    ep["published"] = {"to": str(target), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    episode.save(ep)
    repo = paths.get("cantocaptions")
    try:
        target.resolve().relative_to(repo.resolve())
        inside_library = (repo / ".git").exists()
    except ValueError:
        inside_library = False
    if inside_library:
        try:
            st = subprocess.run(["git", "-C", str(repo), "diff", "--stat", "--", str(target)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            result["git_diff_stat"] = st.stdout.strip()
        except Exception:
            pass
    return result


def copy_draft(episode_id: str) -> dict:
    """Make a workspace copy of the source the working draft, so corrections never touch the
    source file (for "put the edits into a new file"). `ccp publish --to/--to-main` later
    writes the copy wherever the user wants it."""
    ep = episode.load(episode_id)
    if not ep.get("source_srt"):
        raise SystemExit("this workspace has no source subtitle to copy")
    if not episode.draft_is_source(ep):
        return {"status": "the working draft is already a separate copy", "draft": ep["srt"],
                "draft_origin": ep.get("draft_origin")}
    moved = episode.set_draft(ep, Path(ep["source_srt"]),
                              {"kind": "copy", "source": ep["source_srt"],
                               "finished": time.strftime("%Y-%m-%d %H:%M:%S")})
    if episode.path(episode_id, "reference.srt").exists():
        from . import reference
        reference.measure(episode_id)
    return {"status": "ok", "draft": moved["draft"], "moved_to_previous": moved["moved_to_previous"],
            "note": "corrections now go into the copy; the source file stays as it is"}


def runs(episode_id: str) -> list[dict]:
    base = episode.path(episode_id, "pipeline")
    out = []
    for d in sorted(base.iterdir()) if base.exists() else []:
        if d.is_dir():
            out.append({"run": d.name, "outputs": [p.name for p in d.glob("*.srt")],
                        "command": (d / "command.txt").read_text(encoding="utf-8") if (d / "command.txt").exists() else None})
    return out
