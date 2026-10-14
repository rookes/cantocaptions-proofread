"""ccp fetch: download a video's audio (and its subtitles, as references) from a link.

yt-dlp runs from this project's environment (`python -m yt_dlp`), so its version is pinned
here (update with `uv lock --upgrade-package yt-dlp` when a site changes). YouTube needs a
JavaScript runtime: deno is used if installed, otherwise node via `--js-runtimes node`.

Audio only (`bestaudio`, preferring a stream without dynamic-range compression); the video
itself is never needed. Subtitles are kept as reference candidates, best first:

  1. manual written Cantonese (yue, yue-HK, ...)
  2. manual Traditional / Hong Kong Chinese (zh-HK, zh-Hant, zh-TW)
  3. other manual Chinese (zh, zh-Hans, zh-CN)
  4. manual English
  5. the site's automatic captions in the video's own language (weak; never auto-translations)

Everything lands in work/<id>/source/, with info.json recording the link, title and what was
found. The workspace's draft is created later by `ccp pipeline <id> transcribe`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import episode, paths, reference

SUB_FORMAT = "vtt/srv3/ttml/best"
LANG_RANK = [
    (re.compile(r"^(yue|zh-yue)(-.*)?$", re.I), 0, "written Cantonese"),
    (re.compile(r"^zh-(HK|Hant|TW|MO)$", re.I), 1, "Traditional Chinese"),
    (re.compile(r"^(zh|zh-.*|cmn.*)$", re.I), 2, "Chinese"),
    (re.compile(r"^en(-.*)?$", re.I), 3, "English"),
]
MAX_REFERENCES = 4


def _js_args() -> list[str]:
    if shutil.which("deno"):
        return []
    if shutil.which("node"):
        return ["--js-runtimes", "node"]
    return []


def _ytdlp(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-progress", *_js_args(), *args]
    return subprocess.run(cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace")


def probe(url: str) -> dict:
    proc = _ytdlp(["-J", "--skip-download", url])
    if proc.returncode != 0 or not proc.stdout.strip():
        err = "\n".join(l for l in proc.stderr.splitlines() if "ERROR" in l or "WARNING" in l)[-1500:]
        raise SystemExit(f"yt-dlp could not read {url}:\n{err or proc.stderr[-1500:]}")
    return json.loads(proc.stdout)


def _rank(lang: str) -> tuple[int, str] | None:
    for rx, rank, label in LANG_RANK:
        if rx.match(lang):
            return rank, label
    return None


def choose_subs(info: dict) -> list[dict]:
    """Reference candidates from yt-dlp's info dict, best first."""
    out = []
    for lang in (info.get("subtitles") or {}):
        r = _rank(lang)
        if r and lang != "live_chat":
            out.append({"lang": lang, "kind": "manual", "rank": r[0], "label": r[1]})
    auto = info.get("automatic_captions") or {}
    own = (info.get("language") or "").lower()
    for lang in auto:
        base = lang[:-5] if lang.endswith("-orig") else lang
        r = _rank(base)
        if not r:
            continue
        # A long list of automatic captions is mostly machine translation: keep only the
        # original-language track ("-orig", or the video's declared language).
        if len(auto) > 10 and not (lang.endswith("-orig") or (own and base.lower().startswith(own))):
            continue
        out.append({"lang": lang, "kind": "auto", "rank": r[0] + 10, "label": r[1] + " (automatic captions)"})
    out.sort(key=lambda s: (s["rank"], s["kind"] != "manual", s["lang"]))
    return out


def _slug(info: dict) -> str:
    site = (info.get("extractor_key") or info.get("extractor") or "web").lower()
    site = "yt" if site.startswith("youtube") else re.sub(r"[^a-z0-9]+", "", site)[:12] or "web"
    vid = re.sub(r"[^A-Za-z0-9_-]+", "", str(info.get("id") or "video"))
    return f"{site}-{vid}"


def fetch(url: str, episode_id: str | None = None, sub_langs: list[str] | None = None,
          force: bool = False) -> dict:
    info = probe(url)
    eid = episode_id or _slug(info)
    work = paths.work_dir(eid)
    src = work / "source"
    if src.exists() and any(src.glob("audio.*")) and not force:
        audio = next(src.glob("audio.*"))
        print(f"  [fetch] audio already downloaded: {audio.name} (pass --force to fetch again)", file=sys.stderr)
    else:
        if src.exists():
            shutil.rmtree(src)
        src.mkdir(parents=True)
        print(f"  [fetch] downloading audio: {info.get('title')}", file=sys.stderr, flush=True)
        proc = _ytdlp(["-f", "bestaudio[format_id!*=drc]/bestaudio/best", "-o", str(src / "audio.%(ext)s"), url])
        found = [p for p in src.glob("audio.*") if not p.name.endswith((".part", ".ytdl"))]
        if proc.returncode != 0 or not found:
            raise SystemExit(f"yt-dlp failed to download the audio:\n{proc.stderr[-1500:]}")
        audio = found[0]

    candidates = choose_subs(info)
    wanted = [c for c in candidates if not sub_langs or c["lang"] in sub_langs][:MAX_REFERENCES]
    downloaded = []
    for kind in ("manual", "auto"):
        langs = [c["lang"] for c in wanted if c["kind"] == kind]
        if not langs:
            continue
        flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
        _ytdlp(["--skip-download", flag, "--sub-langs", ",".join(langs), "--sub-format", SUB_FORMAT,
                "--convert-subs", "srt", "-o", str(src / f"{kind}.%(ext)s"), url])
        for c in wanted:
            if c["kind"] != kind:
                continue
            hits = sorted(src.glob(f"{kind}.{c['lang']}.srt"))
            if hits:
                downloaded.append({**c, "path": str(hits[0])})
    downloaded.sort(key=lambda c: c["rank"])

    meta = {"url": url, "webpage_url": info.get("webpage_url") or url, "id": info.get("id"),
            "title": info.get("title"), "uploader": info.get("uploader") or info.get("channel"),
            "upload_date": info.get("upload_date"), "duration": info.get("duration"),
            "extractor": info.get("extractor_key"), "language": info.get("language"),
            "audio": str(audio), "subtitles_available": candidates, "subtitles_downloaded": downloaded}
    (src / "info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    ep = episode.create_media_only(str(audio), eid)
    ep["origin"] = {k: meta[k] for k in ("url", "webpage_url", "title", "uploader", "upload_date", "duration", "extractor")}
    ep["show_slug"] = _slug(info).split("-")[0]
    ep["reference_files"] = [d["path"] for d in downloaded]
    ep["notes"] = ["downloaded from a link: run `ccp pipeline <id> transcribe` to make the ASR draft"]
    episode.save(ep)

    result = {"episode_id": eid, "title": meta["title"], "duration_s": meta["duration"], "audio": str(audio),
              "references": [{"lang": d["lang"], "kind": d["kind"], "label": d["label"], "path": d["path"]}
                             for d in downloaded]}
    if downloaded:
        best = downloaded[0]
        ref = reference.prepare(eid, file=best["path"],
                                extra={"language": best["lang"], "kind": best["kind"], "label": best["label"],
                                       "chinese": best["rank"] % 10 <= 2,
                                       "written_cantonese": best["rank"] == 0})
        result["reference"] = {"lang": best["lang"], "label": best["label"], "status": ref.get("status")}
    else:
        result["reference"] = None
        result["note"] = "no usable subtitles on this video: proofread without a reference"
    result["next"] = f"uv run ccp pipeline {eid} transcribe   (long-running; then ccp evidence {eid})"
    return result
