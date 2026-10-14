"""ccp export: hand the results of a job back as one folder.

    <name>.yue.srt                the final subtitles (the working draft as it stands now)
    <name>.asr.yue.srt            the original ASR output, untouched (when the draft came from
                                  `ccp pipeline ... transcribe`; for realign, the realigned output)
    <name>.reference.<lang>.srt   each reference subtitle used or downloaded
    report.html + clips/          the review page, if one was built
    summary.json                  where it all came from, and what changed

Default folder: work/<id>/output/. Exporting again overwrites the files with the current
state, so export after every round of corrections.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import episode, flags as flagstore
from .srtio import SrtFile


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name).strip().rstrip(".")
    return re.sub(r"\s+", " ", name)[:80] or "subtitles"


def export(episode_id: str, to: str | None = None, name: str | None = None) -> dict:
    ep = episode.load(episode_id)
    if not ep.get("srt"):
        raise SystemExit("nothing to export: this workspace has no draft yet")
    out = Path(to) if to else episode.path(episode_id, "output")
    out.mkdir(parents=True, exist_ok=True)
    origin = ep.get("origin") or {}
    base = _safe(name or origin.get("title") or Path(ep.get("source_srt") or ep["srt"]).stem.split(".")[0] or episode_id)
    files = {}

    final = out / f"{base}.yue.srt"
    shutil.copyfile(ep["srt"], final)
    files["final"] = str(final)

    d = ep.get("draft_origin") or {}
    if d.get("kind") in ("transcribe", "realign") and d.get("output") and Path(d["output"]).exists():
        label = "asr" if d.get("kind") == "transcribe" else f"realign-{d.get('mode')}"
        first = out / f"{base}.{label}.yue.srt"
        shutil.copyfile(d["output"], first)
        files["pipeline_output"] = str(first)
    if ep.get("source_srt") and Path(ep["source_srt"]).exists() and not episode.draft_is_source(ep):
        orig = out / f"{base}.original.yue.srt"
        shutil.copyfile(ep["source_srt"], orig)
        files["original"] = str(orig)

    refs = []
    ref_meta_p = episode.path(episode_id, "reference.json")
    ref_meta = json.loads(ref_meta_p.read_text(encoding="utf-8")) if ref_meta_p.exists() else {}
    used = episode.path(episode_id, "reference.srt")
    if used.exists():
        lang = ref_meta.get("language") or "ref"
        p = out / f"{base}.reference.{lang}.srt"
        shutil.copyfile(used, p)
        refs.append({"path": str(p), "language": lang, "used": True, "kind": ref_meta.get("kind")})
    for r in ep.get("reference_files") or []:
        rp = Path(r)
        if not rp.exists() or rp.suffix.lower() != ".srt":
            continue
        m = re.search(r"\.([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)\.srt$", rp.name)
        lang = m.group(1) if m else rp.stem
        if any(x["language"] == lang for x in refs):
            continue
        p = out / f"{base}.reference.{lang}.srt"
        shutil.copyfile(rp, p)
        refs.append({"path": str(p), "language": lang, "used": False})
    files["references"] = refs

    report = episode.path(episode_id, "report.html")
    if report.exists():
        shutil.copyfile(report, out / "report.html")
        clips = episode.path(episode_id, "clips")
        if clips.exists():
            if (out / "clips").exists():
                shutil.rmtree(out / "clips")
            shutil.copytree(clips, out / "clips")
        files["report"] = str(out / "report.html")

    fl = flagstore.load(episode_id)
    summary = {
        "episode_id": episode_id, "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
        "origin": origin or {"source_srt": ep.get("source_srt"), "media": ep.get("media")},
        "draft_origin": {k: d.get(k) for k in ("kind", "mode", "finished") if d.get(k)},
        "cues": {"final": len(SrtFile(final).cues),
                 **({"pipeline_output": len(SrtFile(Path(files["pipeline_output"])).cues)}
                    if "pipeline_output" in files else {})},
        "corrections": {"applied": sum(f["status"] == "applied" for f in fl),
                        "open": sum(f["status"] in ("open", "investigated") for f in fl),
                        "rejected": sum(f["status"] == "rejected" for f in fl),
                        **flagstore.summary(fl)},
        "reference": {k: ref_meta.get(k) for k in ("language", "kind", "label", "agreement", "offset") if k in ref_meta},
        "files": files,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"folder": str(out), **files, "summary": str(out / "summary.json")}
