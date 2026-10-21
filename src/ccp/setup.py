"""`ccp setup`: which of the optional resources this machine has, what each enables, and the
first-use questions.

Nothing here is required. Without the CantoCaptions library, the dataset or cantocaptions-ai
the agent still proofreads, with the fallbacks listed in RESOURCES; setup only finds out which
apply, and records the user's answers in config/paths.local.toml so they are asked once.
"""
from __future__ import annotations

from pathlib import Path

from . import paths

# What each resource gives the agent, and what happens without it. Keys are [paths] keys.
RESOURCES = {
    "cantocaptions": {
        "what": "the CantoCaptions subtitle library (a git repo; its Subtitles/ folder)",
        "enables": "finding a subtitle by show and episode, the standardized corpus (with the "
                   "dataset), publishing into the library, the library's own lint",
        "without": "give the subtitle's path, or pick one next to the media; no corpus; "
                   "publish only with --to PATH",
    },
    "dataset": {
        "what": "cantocaptions-dataset (data/manifest.json, quality tiers, standardization rules)",
        "enables": "subtitle-to-media links, quality tiers, the strict-tier corpus, the latest "
                   "spelling-variant rules",
        "without": "media is found by name in your media folders (always confirmed with you); "
                   "no tiers and no corpus; lint uses the bundled copy of the variant rules",
    },
    "cantocaptions_ai": {
        "what": "cantocaptions-ai with its .venv and models (ASR, alignment, OCR)",
        "enables": "audio evidence (evidence, listen, score, timing), realign and transcribe, "
                   "OCR of image subtitle tracks (with its `ocr` extra)",
        "without": "a text-only proofread against the reference and the conventions; nothing "
                   "is checked against the audio, and no transcription of new videos",
    },
    "media_root": {
        "what": "the media root the dataset manifest's media paths are relative to",
        "enables": "the dataset's own subtitle-to-media links",
        "without": "media is inferred from sibling episodes or searched for in your media folders",
    },
    "media_dirs": {
        "what": "your own media folders (any layout), searched by show and episode",
        "enables": "finding an episode's media without the dataset",
        "without": "give each media file's path yourself",
    },
}


def capabilities() -> dict:
    from . import corpus
    library = paths.has("subtitles")
    dataset = paths.has("dataset")
    dirs = paths.media_dirs()
    if dataset and library:
        mode = "dataset"
    elif library:
        mode = "library"
    elif dirs:
        mode = "media_dirs"
    else:
        mode = "paths_only"
    std = paths.get("dataset") / "rules" / "standardization.toml"
    return {
        "locate_mode": mode,
        "library": library,
        "dataset": dataset,
        "audio_evidence": paths.has("cantocaptions_ai"),
        "ocr": paths.ccai_has_ocr(),
        "corpus": corpus.available(),
        "lint_rules": "dataset" if std.is_file() else "snapshot",
        "media_root": paths.has("media_root"),
        "media_dirs": [str(d) for d in dirs],
    }


def _found(key: str) -> bool:
    if key == "media_dirs":
        return bool(paths.media_dirs())
    if key == "cantocaptions":
        return paths.has("cantocaptions") and paths.has("subtitles")
    return paths.has(key)


def _relevant(key: str, caps: dict) -> bool:
    # The manifest's media root only matters with the dataset; one's own media folders only
    # matter without the dataset's links (or as a fallback for media it never linked).
    if key == "media_root":
        return caps["dataset"]
    if key == "media_dirs":
        return not (caps["dataset"] and caps["media_root"])
    return True


SETUP_SCRIPT = r"powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"


def environment() -> dict:
    """What this repo itself needs: programs on PATH, the skills link Claude Code reads, and
    the dictionary caches (built once, about a minute). scripts/setup.ps1 provides all of it."""
    import shutil
    link = paths.ROOT / ".claude" / "skills"
    cache = paths.get("cache")
    env = {
        "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")),
        "skills_linked": (link / "investigate-line" / "SKILL.md").exists(),
        "caches_built": (cache / "wordshk.pkl").exists() and (cache / "readings.json").exists(),
        "js_runtime": bool(shutil.which("node") or shutil.which("deno")),
    }
    needed = [k for k in ("ffmpeg", "ffprobe", "skills_linked", "caches_built") if not env[k]]
    if needed:
        env["run_setup_script"] = {"missing": needed, "command": SETUP_SCRIPT}
    return env


def status() -> dict:
    state = paths.setup_state()
    caps = capabilities()
    missing = []
    for key, info in RESOURCES.items():
        if _found(key) or not _relevant(key, caps):
            continue
        configured = None if key == "media_dirs" else str(paths.get(key))
        missing.append({"key": key, "configured": configured, **info,
                        "declined": key in state["declined"]})
    first_run = not state["completed"]
    ask = [m["key"] for m in missing if first_run and not m["declined"]]
    out = {"first_run": first_run, "environment": environment(), "capabilities": caps,
           "missing": missing, "ask": ask}
    if out["environment"].get("run_setup_script"):
        out["next"] = (f"Run `{SETUP_SCRIPT}` first (it installs what is missing: "
                       f"{', '.join(out['environment']['run_setup_script']['missing'])}), then `ccp setup` again.")
    elif ask:
        out["next"] = ("First use: ask the user, in one message, where each of these is (or whether "
                       "they have it at all), saying what each enables. Then `ccp setup --set KEY=PATH`, "
                       "`--add-media-dir PATH`, `--decline KEY` for what they do not have, and `--done`.")
    elif first_run:
        out["next"] = "Nothing to ask: run `ccp setup --done`."
    return out


def as_text(st: dict) -> str:
    """`ccp setup --text`: the same report for a person, a few short lines."""
    env, caps = st["environment"], st["capabilities"]
    ok = lambda b: "ok  " if b else "--  "
    lines = ["This repo",
             f"  {ok(env['ffmpeg'] and env['ffprobe'])}ffmpeg and ffprobe"
             + ("" if env["ffmpeg"] and env["ffprobe"] else "  (needed for audio and clips)"),
             f"  {ok(env['caches_built'])}dictionary caches",
             f"  {ok(env['skills_linked'])}skills linked for Claude Code"]
    if not env["js_runtime"]:
        lines.append("  note no Node.js or deno: only needed to download from YouTube (`ccp fetch`)")
    lines += ["", "Optional repositories (the proofreader works without them)"]
    found = {"cantocaptions": caps["library"], "dataset": caps["dataset"],
             "cantocaptions_ai": caps["audio_evidence"]}
    names = {"cantocaptions": "CantoCaptions library", "dataset": "cantocaptions-dataset",
             "cantocaptions_ai": "cantocaptions-ai"}
    for key, name in names.items():
        if found[key]:
            extra = " (with OCR)" if key == "cantocaptions_ai" and caps["ocr"] else ""
            lines.append(f"  ok  {name}{extra}: {paths.get(key)}")
        else:
            lines.append(f"  --  {name}: not found. Without it: {RESOURCES[key]['without']}")
    dirs = caps["media_dirs"]
    lines.append(f"  {'ok  ' if dirs else '    '}media folders: {', '.join(dirs) if dirs else 'none'}")
    if st.get("next"):
        lines += ["", "Next: " + st["next"]]
    elif not st.get("ask"):
        lines += ["", "Ready. Open this folder in Claude Code or Antigravity and ask, for example: "
                      "\"Proofread Attack on Titan S1E03 and give me a report.\""]
    return "\n".join(lines)


def _check(key: str, value: str) -> str | None:
    """Why *value* is not a usable path for *key*, or None."""
    p = Path(value)
    p = p if p.is_absolute() else (paths.ROOT / p).resolve()
    if not p.exists():
        return f"{p} does not exist"
    expect = {
        "dataset": (p / "data" / "manifest.json", "data/manifest.json (run its scan)"),
        "cantocaptions_ai": (p / ".venv", "a .venv (run `uv sync` there)"),
        "cantocaptions": (p / "Subtitles", "a Subtitles folder"),
    }.get(key)
    if expect and not expect[0].exists():
        return f"{p} has no {expect[1]}"
    return None


def apply(sets: list[str], add_dirs: list[str], remove_dirs: list[str], decline: list[str],
          done: bool) -> dict:
    """Record the user's answers, then report the new status (with any problems)."""
    problems, path_updates = [], {}
    for item in sets:
        key, sep, value = item.partition("=")
        key, value = key.strip(), value.strip().strip('"')
        if not sep or not value:
            problems.append(f"{item!r}: give KEY=PATH")
            continue
        if key not in paths._table() or key == "media_dirs":
            problems.append(f"{key!r}: not a path key (one of "
                            f"{', '.join(k for k in paths._table() if k != 'media_dirs')})")
            continue
        why = _check(key, value)
        if why:
            problems.append(f"{key}: {why}; not saved")
            continue
        path_updates[key] = str(Path(value))
        if key == "cantocaptions":
            path_updates.setdefault("subtitles", str(Path(value) / "Subtitles"))
    dirs = [str(Path(d)) for d in (paths._table().get("media_dirs") or [])]
    for d in add_dirs:
        if not Path(d).is_dir():
            problems.append(f"media dir {d}: not a folder; not added")
        elif str(Path(d)) not in dirs:
            dirs.append(str(Path(d)))
    dirs = [d for d in dirs if d not in {str(Path(r)) for r in remove_dirs}]
    if add_dirs or remove_dirs:
        path_updates["media_dirs"] = dirs
    state = paths.setup_state()
    declined = sorted(set(state["declined"]) | {k for k in decline if k in RESOURCES})
    for k in decline:
        if k not in RESOURCES:
            problems.append(f"{k!r}: not a resource (one of {', '.join(RESOURCES)})")
    # A resource configured now is no longer declined.
    declined = [k for k in declined if k not in path_updates and not (k == "media_dirs" and dirs)]
    setup_updates = {"declined": declined}
    if done:
        setup_updates["completed"] = True
    paths.write_local(path_updates, setup_updates)
    out = status()
    if problems:
        out["problems"] = problems
    return out
