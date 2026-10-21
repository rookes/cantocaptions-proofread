"""Per-episode workspace: work/<episode_id>/episode.json and the files around it.

Two subtitle paths matter:

    source_srt   the file the user means (usually in CantoCaptions). Never written by the
                 pipeline; `ccp apply` edits it in place only while it is also the draft.
    srt          the working draft that every tool reads. It starts as the source. When
                 `ccp pipeline` realigns or transcribes, its output becomes work/<id>/draft.srt;
                 corrections then go into that copy, and `ccp publish` puts it back into
                 CantoCaptions when the user agrees.

Files:
    episode.json     paths, audio track, tier, draft origin, references found
    draft.srt        the working draft when it is not the source
    pipeline/<run>/  cantocaptions-ai runs (output + debug dir)
    timing.jsonl     per-cue timing notes from a realign run (suspect cues and reasons)
    reference.srt / reference.json   the reference subtitle and its time offset
    evidence.jsonl / groups.jsonl / emissions/   ccp evidence
    lint.jsonl, flags.jsonl, report.html, clips/
    previous/<stamp>/  evidence, flags etc. of an earlier draft, moved aside on a new draft
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import locate, paths
from .srtio import SrtFile

DRAFT_DEPENDENT = ["evidence.jsonl", "groups.jsonl", "emissions", "lint.jsonl", "flags.jsonl",
                   "report.html", "clips", "timing.jsonl", "timing_suggestions", "signals.json",
                   "stats.json"]


def _probe(ep: dict, audio_track: int | None) -> dict:
    if ep.get("media_exists"):
        tracks = locate.audio_tracks(ep["media"])
        ep["audio_tracks"] = tracks
        ep["audio_track"] = audio_track if audio_track is not None else locate.pick_cantonese(tracks)
        ep["subtitle_streams"] = locate.subtitle_streams(ep["media"])
        tagged = any(t["language"].lower() in ("yue", "chi", "zho", "zh") or
                     re.search(r"cantonese|粵|粤|廣東|中", t["title"], re.I) for t in tracks)
        if len(tracks) > 1 and audio_track is None and not tagged:
            ep.setdefault("notes", []).append(
                f"{len(tracks)} audio tracks and none is tagged Cantonese/Chinese; track {ep['audio_track']} "
                "was assumed. If the recognisers' text looks like another language, re-run "
                "`ccp locate ... --audio-track N` (ask the user which track is Cantonese)")
    return ep


def create(rec: dict, audio_track: int | None = None, media: str | None = None) -> dict:
    r = locate.resolved(rec)
    if media:
        r["media"], r["media_exists"] = str(Path(media).resolve()), Path(media).exists()
        r["notes"] = [n for n in r["notes"] if "media" not in n] + ["media given explicitly"]
    rel_parts = Path(rec["srt_path"]).parts
    ep = {**r, "source_srt": r["srt"], "draft_origin": {"kind": "source"},
          "show_slug": rec.get("show_slug"), "season": rec.get("season"),
          "episodes": rec.get("episodes"), "source": rec.get("source"),
          "show_folder": rec.get("show_folder") or (rel_parts[2] if len(rel_parts) > 2 else None),
          "category": rec.get("category") or (rel_parts[0] if len(rel_parts) > 2 else None)}
    old = path(ep["episode_id"], "episode.json")
    if old.exists():
        prev = json.loads(old.read_text(encoding="utf-8"))
        # Re-locating must not throw away a pipeline draft in progress.
        if prev.get("draft_origin", {}).get("kind") not in (None, "source"):
            ep["srt"], ep["draft_origin"] = prev["srt"], prev["draft_origin"]
            ep["notes"] = ep["notes"] + ["kept the existing working draft from " + prev["draft_origin"]["kind"]]
    _probe(ep, audio_track)
    ep["reference_files"] = locate.reference_files(ep["source_srt"], ep.get("media"), ep["season"], ep["episodes"] or [])
    save(ep)
    return ep


def create_media_only(media: str, episode_id: str, audio_track: int | None = None) -> dict:
    """A workspace for an episode with no subtitle yet (e.g. to transcribe it first)."""
    m = Path(media).resolve()
    season, eps = locate.episode_of(m.name)
    ep = {"episode_id": episode_id, "srt": None, "source_srt": None, "media": str(m),
          "media_exists": m.exists(), "tier": "unknown", "exclusion": None,
          "notes": ["no subtitle yet: run `ccp pipeline <id> transcribe` to make a draft"],
          "draft_origin": {"kind": "none"}, "show_slug": episode_id.split("_")[0],
          "season": season, "episodes": eps, "reference_files": []}
    _probe(ep, audio_track)
    ep["reference_files"] = locate.reference_files(None, ep["media"], season, eps)
    save(ep)
    return ep


def path(episode_id: str, name: str) -> Path:
    return paths.work_dir(episode_id) / name


def load(episode_id: str) -> dict:
    p = path(episode_id, "episode.json")
    if not p.exists():
        raise SystemExit(f"no workspace for {episode_id!r}; run `ccp locate ...` first")
    ep = json.loads(p.read_text(encoding="utf-8"))
    ep.setdefault("source_srt", ep.get("srt"))
    ep.setdefault("draft_origin", {"kind": "source"})
    return ep


def save(ep: dict) -> None:
    path(ep["episode_id"], "episode.json").write_text(
        json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")


def srt(ep: dict) -> SrtFile:
    if not ep.get("srt"):
        raise SystemExit("this workspace has no subtitle draft yet; run `ccp pipeline <id> transcribe` "
                         "or `ccp locate --srt <file>`")
    return SrtFile(Path(ep["srt"]))


def draft_is_source(ep: dict) -> bool:
    return bool(ep.get("srt")) and ep.get("srt") == ep.get("source_srt")


def machine_draft(ep: dict) -> bool:
    """Was the draft's text written by the speech models (an ASR transcription, an
    AI-generated library file, or a realign of either)? Such drafts get a text-only cleanup
    pass before any audio evidence, and the fine-tuned recogniser is no independent witness
    for them."""
    origin = ep.get("draft_origin") or {}
    return bool(ep.get("ai_generated") or origin.get("kind") == "transcribe" or origin.get("machine"))


def set_draft(ep: dict, new_srt: Path, origin: dict) -> dict:
    """Make *new_srt* the working draft (copied to work/<id>/draft.srt). Everything computed
    on the old draft (evidence, flags, lint, report, timing notes) is moved to previous/."""
    eid = ep["episode_id"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    for name in DRAFT_DEPENDENT:
        p = path(eid, name)
        if p.exists():
            dest = path(eid, "previous") / stamp
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest / name))
            moved.append(name)
    draft = path(eid, "draft.srt")
    shutil.copyfile(new_srt, draft)
    ep["srt"] = str(draft)
    ep["draft_origin"] = origin
    save(ep)
    return {"draft": str(draft), "moved_to_previous": moved}


def read_jsonl(episode_id: str, name: str) -> list[dict]:
    p = path(episode_id, name)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_jsonl(episode_id: str, name: str, rows: list[dict]) -> Path:
    p = path(episode_id, name)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return p


def reference_cues(episode_id: str) -> list[dict]:
    """Reference cues on the draft's timeline (offset applied): [{start, end, text}]."""
    meta_p = path(episode_id, "reference.json")
    ref_p = path(episode_id, "reference.srt")
    if not ref_p.exists():
        return []
    offset = json.loads(meta_p.read_text(encoding="utf-8")).get("offset", 0.0) if meta_p.exists() else 0.0
    out, seen = [], set()
    for c in SrtFile(ref_p).cues:
        # ASS-derived files carry {comments} and repeated karaoke/sign layers.
        text = re.sub(r"\{[^}]*\}", "", c.text).strip()
        key = (round(c.start, 2), text)
        if not text or key in seen:
            continue
        seen.add(key)
        out.append({"start": c.start + offset, "end": c.end + offset, "text": text})
    return out
