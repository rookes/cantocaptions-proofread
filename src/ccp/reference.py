"""Get a reference subtitle (Standard Chinese preferred, English as a fallback) onto the
draft's timeline.

Order of preference, first hit wins unless the caller names a source:
  1. a reference file already on disk (CantoCaptions Standard Chinese/English folders,
     *.chs siblings, subtitle files next to the media)
  2. an embedded *text* subtitle stream (extracted with ffmpeg)
  3. an embedded *bitmap* stream (PGS/VobSub/DVB), OCR'd with sub-convert -- only when the
     caller passes ocr=True, because it is slow and writes a file next to the media.

The reference is evidence for meaning and for how names are written. Its wording is
Standard Chinese and must never be copied into a Cantonese cue.
"""
from __future__ import annotations

import bisect
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import episode, paths
from .srtio import SrtFile

AGREEMENT_TOLERANCE = 0.5
MIN_AGREEMENT = 0.6
CHINESE = {"chi", "zho", "zh", "chs", "cht", "yue", "cmn"}


def _share_near(points: list[float], targets: list[float]) -> float:
    targets = sorted(targets)
    hit = 0
    for t in points:
        i = bisect.bisect_left(targets, t)
        near = min(abs(targets[j] - t) for j in (i - 1, i) if 0 <= j < len(targets))
        hit += near <= AGREEMENT_TOLERANCE
    return hit / len(points) if points else 0.0


def agreement(cue_starts: list[float], ref_starts: list[float], shift: float = 0.0) -> float:
    """Share of starts within 0.5 s of a start on the other side (the better direction).
    Ported from cantocaptions_ai.pipeline.proofread.render.reference_agreement."""
    ref = [r + shift for r in ref_starts]
    if not cue_starts or not ref:
        return 0.0
    return max(_share_near(ref, cue_starts), _share_near(cue_starts, ref))


def best_shift(cue_starts: list[float], ref_starts: list[float], span: float = 10.0,
               step: float = 0.05) -> tuple[float, float]:
    n = int(round(span / step))
    scored = [(round(k * step, 3), agreement(cue_starts, ref_starts, k * step)) for k in range(-n, n + 1)]
    top = max(s for _, s in scored)
    best = [sh for sh, s in scored if s >= top - 1e-9]
    return best[len(best) // 2], top


def _is_chinese_name(name: str) -> bool:
    return bool(re.search(r"(\.|_|-|\b)(chi|chs|cht|zh|zho|sc|tc)([.\-_]|\b)|Standard Chinese|簡體|繁體", name, re.I))


def _to_srt(src: Path, dst: Path) -> None:
    if src.suffix.lower() == ".srt":
        shutil.copyfile(src, dst)
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), str(dst)], check=True)


def _extract_stream(media: str, stream_index: int, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", media, "-map", f"0:{stream_index}",
                    "-c:s", "srt", str(dst)], check=True)


def _ocr(media: str, stream: dict, dst: Path) -> Path:
    sc = paths.get("sub_convert")
    media_p = Path(media)
    codec = {"hdmv_pgs_subtitle": "pgs", "dvd_subtitle": "dvdsub", "dvb_subtitle": "dvb"}.get(stream["codec"])
    spec = f"{codec}:{stream['stream_index']}" if codec else str(stream["stream_index"])
    before = time.time() - 1
    cmd = ["uv", "run", "--project", str(sc), "--no-sync", "sub-convert", "-p", media,
           "-T", spec, "-ol", "chinese_cht", "-t", "cuda"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    made = [p for p in media_p.parent.glob("*.srt") if p.stat().st_mtime >= before]
    if proc.returncode != 0 or not made:
        raise SystemExit(f"sub-convert failed (exit {proc.returncode}):\n{proc.stderr[-2000:]}")
    newest = max(made, key=lambda p: p.stat().st_mtime)
    shutil.copyfile(newest, dst)
    return newest


def options(ep: dict) -> list[dict]:
    opts = []
    for f in ep.get("reference_files", []):
        opts.append({"kind": "file", "path": f, "chinese": _is_chinese_name(f)})
    for s in ep.get("subtitle_streams", []):
        opts.append({"kind": "stream_" + s["kind"], "stream_index": s["stream_index"], "codec": s["codec"],
                     "language": s["language"], "title": s["title"],
                     "chinese": s["language"].lower() in CHINESE or bool(re.search(r"中|CH[ST]|chinese", s["title"], re.I))})
    return opts


def prepare(episode_id: str, file: str | None = None, stream: int | None = None,
            ocr: bool = False, extra: dict | None = None) -> dict:
    ep = episode.load(episode_id)
    dst = episode.path(episode_id, "reference.srt")
    opts = options(ep)
    chosen = None
    if file:
        chosen = {"kind": "file", "path": file, "chinese": _is_chinese_name(file)}
    elif stream is not None:
        chosen = next((o for o in opts if o.get("stream_index") == stream), None)
        if chosen is None:
            raise SystemExit(f"no subtitle stream with index {stream}; options: {json.dumps(opts, ensure_ascii=False)}")
    else:
        ranked = ([o for o in opts if o["kind"] == "file" and o["chinese"]]
                  + [o for o in opts if o["kind"] == "stream_text" and o["chinese"]]
                  + ([o for o in opts if o["kind"] == "stream_bitmap" and o["chinese"]] if ocr else [])
                  + [o for o in opts if o["kind"] in ("file", "stream_text") and not o["chinese"]])
        chinese_bitmap = [o for o in opts if o["kind"] == "stream_bitmap" and o["chinese"]]
        if not ranked or (not ranked[0]["chinese"] and chinese_bitmap and not ocr):
            return {"status": "needs_decision", "options": opts,
                    "message": ("No Chinese text reference is available. "
                                + ("A Chinese bitmap track can be OCR'd with --ocr (slow; sub-convert "
                                   "writes an .srt next to the media file). " if chinese_bitmap else "")
                                + ("An English text reference can be used with --file/--stream. " if ranked else "")
                                + "Ask the user which to use.")}
        chosen = ranked[0]

    if chosen["kind"] == "file":
        _to_srt(Path(chosen["path"]), dst)
        source = chosen["path"]
    elif chosen["kind"] == "stream_text":
        _extract_stream(ep["media"], chosen["stream_index"], dst)
        source = f"{ep['media']} stream {chosen['stream_index']} ({chosen['codec']})"
    else:
        if not ocr:
            raise SystemExit("that stream is a bitmap track; pass --ocr to OCR it (ask the user first)")
        made = _ocr(ep["media"], chosen, dst)
        source = f"OCR of {ep['media']} stream {chosen['stream_index']} via sub-convert (also written to {made})"

    meta = measure(episode_id, {"source": source, "chinese": chosen["chinese"], **(extra or {})})
    return {"status": "ok", **meta}


def measure(episode_id: str, base: dict | None = None) -> dict:
    """(Re)measure the reference's time offset against the current draft and save
    reference.json. Called again whenever the draft is replaced (e.g. after a realign)."""
    meta_p = episode.path(episode_id, "reference.json")
    computed = ("cues", "agreement_unshifted", "offset", "agreement", "warning", "note")
    if base is None:
        base = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        base = {k: v for k, v in base.items() if k not in computed}
    ep = episode.load(episode_id)
    ref = SrtFile(episode.path(episode_id, "reference.srt")).cues
    if not ep.get("srt"):
        # No draft yet (e.g. a downloaded video before transcription): the offset is measured
        # when `ccp pipeline` makes one.
        meta = {**base, "cues": len(ref), "offset": 0.0,
                "note": "timing not measured yet: there is no draft to compare with"}
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta
    draft = [c.start for c in episode.srt(ep).cues]
    raw = agreement(draft, [c.start for c in ref])
    shift, best = best_shift(draft, [c.start for c in ref])
    offset = shift if best > raw + 0.05 else 0.0
    meta = {**base, "cues": len(ref), "agreement_unshifted": round(raw, 3), "offset": offset,
            "agreement": round(best if offset else raw, 3)}
    if meta["agreement"] < MIN_AGREEMENT:
        meta["warning"] = ("Reference timing agrees poorly with the draft even after shifting; it may "
                           "be timed to another release. Use it for names and meaning only, never for "
                           "placing lines.")
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
