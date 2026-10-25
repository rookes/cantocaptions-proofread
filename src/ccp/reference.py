"""Get a reference subtitle (Standard Chinese preferred, English as a fallback) onto the
draft's timeline.

Order of preference, first hit wins unless the caller names a source:
  1. a reference file already on disk (CantoCaptions Standard Chinese/English folders,
     *.chs siblings, subtitle files next to the media)
  2. an embedded *text* subtitle stream (extracted with ffmpeg)
  3. an embedded *bitmap* stream (PGS/VobSub/DVB), OCR'd by cantocaptions-ai
     (`cantocaptions MEDIA --references_only`, which needs its `ocr` extra) into the
     workspace -- only when the caller passes ocr=True, because it takes the GPU for about a
     minute.

The reference is evidence for meaning and for how names are written. Its wording is
Standard Chinese and must never be copied into a Cantonese cue.
"""
from __future__ import annotations

import bisect
import json
import os
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


OCR_UNAVAILABLE = ("OCR of image subtitle tracks needs cantocaptions-ai with its `ocr` extra "
                   "(`uv sync --inexact --extra ocr` there), which this machine does not have")
# The languages cantocaptions-ai can OCR (its --reference_ocr_lang values), for `--ocr-lang`.
OCR_LANGS = {"chinese_cht": "Traditional Chinese", "ch": "Simplified Chinese", "en": "English",
             "japan": "Japanese", "korean": "Korean"}
_TAGGED = {"chi", "zho", "zh", "chs", "cht", "yue", "cmn", "eng", "en", "jpn", "ja", "kor", "ko"}


def _ocr_lang_hint(stream_index: int) -> str:
    choices = ", ".join(f"{k} ({v})" for k, v in OCR_LANGS.items())
    return (f"Stream {stream_index} has no language tag, so the OCR does not know what to read. Ask the "
            f"user which language its subtitles are in, then run `ccp reference <id> --stream "
            f"{stream_index} --ocr --ocr-lang LANG` with one of: {choices}.")


def needs_ocr_lang(s: dict) -> bool:
    """An image track cantocaptions-ai cannot pick a recogniser for by itself: no language tag
    it knows, and no Chinese in its title."""
    return (s["kind"] == "bitmap" and s["language"].lower() not in _TAGGED
            and not re.search(r"中|CH[ST]|chinese", s["title"], re.I))


def _ocr(episode_id: str, media: str, stream: dict, dst: Path, ocr_lang: str | None = None) -> Path:
    """OCR one bitmap stream with cantocaptions-ai into work/<id>/references/; returns the SRT."""
    if not paths.ccai_has_ocr():
        raise SystemExit(OCR_UNAVAILABLE + "; use another reference or none.")
    if ocr_lang is not None and ocr_lang not in OCR_LANGS:
        raise SystemExit(f"--ocr-lang must be one of: {', '.join(OCR_LANGS)}")
    if ocr_lang is None and stream.get("needs_ocr_lang"):
        raise SystemExit(_ocr_lang_hint(stream["stream_index"]))
    ccai = paths.get("cantocaptions_ai")
    out_dir = episode.path(episode_id, "references")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["uv", "run", "--project", str(ccai), "--no-sync", "cantocaptions", media,
           "--references_only", "--reference_tracks", str(stream["stream_index"]),
           "--output_dir", str(out_dir),
           "--log_file", "none", "--print_progress", "False"]
    if ocr_lang:
        cmd += ["--reference_ocr_lang", ocr_lang]
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    # From cantocaptions-ai's own folder, so the user's config/user.cfg there applies.
    proc = subprocess.run(cmd, cwd=str(ccai), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    # cantocaptions-ai names the manifest by its own rules (it trims the stem of `519-520 .mkv`,
    # for one), so take the one this run wrote rather than guess the name.
    written = sorted((p for p in out_dir.glob("*.references.json") if p.stat().st_mtime >= started - 1),
                     key=lambda p: p.stat().st_mtime)
    if proc.returncode != 0 or not written:
        raise SystemExit(f"cantocaptions-ai OCR failed (exit {proc.returncode}):\n"
                         + (proc.stdout + proc.stderr)[-2000:])
    data = json.loads(written[-1].read_text(encoding="utf-8"))
    track = next((t for t in data.get("tracks", []) if t["stream"]["index"] == stream["stream_index"]), None)
    if track is None or not track.get("path") or track.get("error"):
        why = (track or {}).get("error") or next(
            (k["reason"] for k in data.get("skipped", []) if k["stream"]["index"] == stream["stream_index"]),
            "no output")
        if "no OCR language" in why:
            raise SystemExit(_ocr_lang_hint(stream["stream_index"]))
        raise SystemExit(f"cantocaptions-ai could not OCR stream {stream['stream_index']}: {why}")
    shutil.copyfile(track["path"], dst)
    return Path(track["path"])


def options(ep: dict) -> list[dict]:
    opts = []
    for f in ep.get("reference_files", []):
        opts.append({"kind": "file", "path": f, "chinese": _is_chinese_name(f)})
    can_ocr = paths.ccai_has_ocr()
    for s in ep.get("subtitle_streams", []):
        if s["kind"] == "bitmap" and not can_ocr:
            # Listed, so the user hears it exists, but marked: nothing here can read it.
            opts.append({"kind": "stream_bitmap_no_ocr", "stream_index": s["stream_index"],
                         "codec": s["codec"], "language": s["language"], "title": s["title"],
                         "chinese": s["language"].lower() in CHINESE or bool(re.search(r"中|CH[ST]|chinese", s["title"], re.I)),
                         "note": OCR_UNAVAILABLE})
            continue
        opts.append({"kind": "stream_" + s["kind"], "stream_index": s["stream_index"], "codec": s["codec"],
                     "language": s["language"], "title": s["title"],
                     "chinese": s["language"].lower() in CHINESE or bool(re.search(r"中|CH[ST]|chinese", s["title"], re.I)),
                     **({"needs_ocr_lang": True, "note": "no language tag: ask the user which language it is, "
                         "then --ocr --ocr-lang"} if needs_ocr_lang(s) else {})})
    return opts


def prepare(episode_id: str, file: str | None = None, stream: int | None = None,
            ocr: bool = False, ocr_lang: str | None = None, extra: dict | None = None) -> dict:
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
        no_ocr_chinese = [o for o in opts if o["kind"] == "stream_bitmap_no_ocr" and o["chinese"]]
        untagged = [o["stream_index"] for o in opts if o.get("needs_ocr_lang")]
        if not ranked or (not ranked[0]["chinese"] and (chinese_bitmap or no_ocr_chinese or untagged) and not ocr):
            return {"status": "needs_decision", "options": opts,
                    "message": ("No Chinese text reference is available. "
                                + ("A Chinese image track can be OCR'd with --ocr (cantocaptions-ai, "
                                   "about a minute on the GPU). " if chinese_bitmap else "")
                                + ("There is a Chinese image track, but " + OCR_UNAVAILABLE + ". "
                                   if no_ocr_chinese and not chinese_bitmap else "")
                                + (f"Image track(s) {', '.join(map(str, untagged))} have no language tag: they "
                                   "can be OCR'd once the user says which language they are in (--stream N "
                                   "--ocr --ocr-lang LANG). " if untagged else "")
                                + ("An English text reference can be used with --file/--stream. " if ranked else "")
                                + "Ask the user which to use.")}
        chosen = ranked[0]

    if chosen["kind"] == "file":
        _to_srt(Path(chosen["path"]), dst)
        source = chosen["path"]
    elif chosen["kind"] == "stream_text":
        _extract_stream(ep["media"], chosen["stream_index"], dst)
        source = f"{ep['media']} stream {chosen['stream_index']} ({chosen['codec']})"
    elif chosen["kind"] == "stream_bitmap_no_ocr":
        raise SystemExit(OCR_UNAVAILABLE + "; use another reference or none.")
    else:
        if not ocr:
            raise SystemExit("that stream is an image track; pass --ocr to OCR it")
        made = _ocr(episode_id, ep["media"], chosen, dst, ocr_lang)
        if ocr_lang in ("chinese_cht", "ch"):
            chosen = {**chosen, "chinese": True}      # untagged, but the user says it is Chinese
        source = f"OCR of {ep['media']} stream {chosen['stream_index']} by cantocaptions-ai ({made.name})"

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
