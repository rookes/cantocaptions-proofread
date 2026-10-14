"""ccp prune: free the disk space a finished job no longer needs.

Removed (all bulky, all regenerable):
    emissions/                     stored aligner output     -> `ccp evidence <id> --force`
    clips/, output/clips/          report audio clips        -> `ccp report <id>` (+ `ccp export`)
    pipeline/<run>/debug/          cantocaptions-ai debug dir (VAD and vocal-isolation WAVs)
    previous/*/emissions, clips    the same, for earlier drafts
    source/audio.*                 a downloaded video's audio, only with --downloads
                                                             -> `ccp fetch <url> --force`
Kept: episode.json, the draft, flags, evidence/groups/lint/timing notes, references, the
pipeline's output SRT and logs, timing suggestions, the export folder's subtitles and summary,
and report.html (readable, but its audio players are empty until `ccp report` runs again).

Pruning is for the end of a job: after the corrections are applied (and published or
exported) and the user is not going to review the report's audio any more.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import episode, flags as flagstore, paths


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def targets(episode_id: str, downloads: bool = False) -> list[Path]:
    w = paths.work_dir(episode_id)
    out = [w / "emissions", w / "clips", w / "output" / "clips"]
    out += [d / "debug" for d in (w / "pipeline").iterdir() if d.is_dir()] if (w / "pipeline").exists() else []
    if (w / "previous").exists():
        for d in (w / "previous").iterdir():
            out += [d / "emissions", d / "clips"]
    if downloads and (w / "source").exists():
        out += [p for p in (w / "source").glob("audio.*")]
    return [p for p in out if p.exists()]


def reclaimable_mb(episode_id: str) -> float:
    return round(sum(_size(p) for p in targets(episode_id)) / 1e6, 1)


def prune(episode_id: str, dry_run: bool = False, downloads: bool = False) -> dict:
    w = paths.work_dir(episode_id)
    found = targets(episode_id, downloads)
    sizes = {str(p.relative_to(w)): round(_size(p) / 1e6, 1) for p in found}
    result = {"episode_id": episode_id, "remove": sizes, "frees_mb": round(sum(sizes.values()), 1),
              "dry_run": dry_run}
    if dry_run or not found:
        return result
    for p in found:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    ep = episode.load(episode_id)
    ep["pruned"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "removed": sorted(sizes),
                    "freed_mb": result["frees_mb"]}
    episode.save(ep)
    result["to_restore"] = ("`ccp evidence <id> --force` for scoring and timing; `ccp report <id>` for "
                            "the report's audio" + ("; `ccp fetch <url> --force` for the audio" if downloads else ""))
    return result


def finished(ep: dict, flags: list[dict]) -> bool:
    """A job looks done when it was published or exported, or when it has flags and none is
    still open."""
    if ep.get("published") or episode.path(ep["episode_id"], "output").joinpath("summary.json").exists():
        return True
    return bool(flags) and not any(f["status"] in ("open", "investigated") for f in flags)


def prune_finished(dry_run: bool = False, downloads: bool = False) -> dict:
    work = paths.get("work")
    pruned, skipped = [], []
    for d in sorted(work.iterdir()) if work.exists() else []:
        if not (d / "episode.json").exists():
            continue
        eid = d.name
        ep = episode.load(eid)
        if finished(ep, flagstore.load(eid)):
            r = prune(eid, dry_run, downloads)
            if r["frees_mb"]:
                pruned.append({"episode_id": eid, "frees_mb": r["frees_mb"]})
        elif reclaimable_mb(eid) > 0:
            skipped.append({"episode_id": eid, "reason": "job not finished (open flags, not exported or published)",
                            "would_free_mb": reclaimable_mb(eid)})
    return {"dry_run": dry_run, "pruned": pruned, "total_mb": round(sum(p["frees_mb"] for p in pruned), 1),
            "not_finished": skipped}
