"""Find a subtitle file and its media from a free-text request.

The starting point is cantocaptions-dataset's `data/manifest.json` (srt_path relative to
CantoCaptions/Subtitles, media_path relative to the media root), but the manifest is only a
snapshot and does not cover everything, so every lookup is checked against the disk:

* **Excluded records** (WIP, AI-generated, ...) are found like any other, marked with their
  exclusion. The dataset drops them from training; they are perfectly proofreadable.
* **Stale paths.** A file renamed since the manifest was built (`[WIP]X.S1E02` -> `X.S1E02`)
  is found again in the same folder by its season/episode.
* **Missing media.** The dataset never pairs media for excluded records. Media is then
  inferred from the show's other episodes: the folders their media lives in are searched for
  a file with the same episode number (ReZero E01 is `.../Season 1/01.mkv`, so E03 is `03.mkv`).
* **Files the manifest has never seen** get a record synthesised from their path.

Nothing here writes to the dataset. If a guess is wrong, `ccp locate --srt X --media Y`
overrides it.

Every source is optional. Without the dataset the library on disk is the catalogue; without
the library either, an episode's media is searched for by name in the user's own media
folders (`media_dirs`, see `search_media`). A match found that way is only a candidate: it
never creates a workspace by itself, and the agent confirms it with the user first.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from . import corpus, paths

REF_LANG_DIRS = ("Standard Chinese", "English", "Simplified - 簡體字", "Traditional - 繁體字")
MEDIA_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".m2ts", ".mts", ".webm", ".mov", ".wmv", ".flv"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt"}


@lru_cache(maxsize=1)
def manifest() -> list[dict]:
    """The dataset's records, or [] without the dataset."""
    p = paths.get("dataset") / "data" / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8"))["records"] if p.is_file() else []


def _show_folder(rec: dict) -> str:
    parts = Path(rec["srt_path"]).parts
    return parts[2] if len(parts) > 2 else parts[0]


def _initials(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name.split("--")[0])
    return "".join(w[0] for w in words).lower()


def _fold(s: str) -> str:
    return re.sub(r"[^a-z0-9㐀-鿿]", "", s.lower())


def parse_request(text: str) -> tuple[str, int | None, int | None]:
    """('attack on titan', season, episode) from 'Attack on Titan Season 1 Episode 3',
    'AoT S1E03', '進擊的巨人 第3集', 'Doraemon E523'."""
    t = text
    season = episode = None
    m = re.search(r"\bS(\d{1,2})\s*E[Pp]?(\d{1,4})\b", t, re.I)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        t = t[:m.start()] + t[m.end():]
    m = re.search(r"\bseason\s*(\d{1,2})\b", t, re.I) or re.search(r"第\s*(\d{1,2})\s*季", t)
    if m and season is None:
        season = int(m.group(1))
        t = t[:m.start()] + t[m.end():]
    m = (re.search(r"\b(?:episode|ep|e)\s*\.?\s*(\d{1,4})\b", t, re.I)
         or re.search(r"第\s*(\d{1,4})\s*[集話话]", t))
    if m and episode is None:
        episode = int(m.group(1))
        t = t[:m.start()] + t[m.end():]
    if episode is None:
        m = re.search(r"(?<![\w])(\d{1,4})\s*$", t.strip())
        if m:
            episode = int(m.group(1))
            t = t.strip()[:m.start()]
    return re.sub(r"\s+", " ", t).strip(" -_,"), season, episode


def episode_of(name: str) -> tuple[int | None, list[int]]:
    """(season or None, [episodes]) parsed from a subtitle or media file name:
    S01E03 / S1E523-524 / 1x03 / E03 / a bare number (03.mkv)."""
    stem = Path(name).stem
    m = re.search(r"S(\d{1,2})\s*E[Pp]?(\d{1,4})(?:-E?[Pp]?(\d{1,4}))?", stem, re.I)
    if m:
        a, b = int(m.group(2)), int(m.group(3) or m.group(2))
        return int(m.group(1)), list(range(a, b + 1)) if b >= a else [a]
    m = re.search(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)", stem)
    if m:
        return int(m.group(1)), [int(m.group(2))]
    m = re.search(r"(?<![A-Za-z0-9])E[Pp]?\s*(\d{1,4})(?:-E?[Pp]?(\d{1,4}))?(?![0-9])", stem)
    if m:
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        return None, list(range(a, b + 1)) if b >= a else [a]
    # A bare number, ignoring resolutions, years, CRCs and codec numbers.
    cleaned = re.sub(r"\[[0-9A-Fa-f]{8}\]|\d{3,4}p|(19|20)\d\d|[xh]\.?26[45]|10bit|5\.1|2\.0", " ", stem)
    nums = re.findall(r"(?<![A-Za-z0-9])(\d{1,4})(?![0-9])", cleaned)
    return (None, [int(nums[0])]) if len(nums) == 1 else (None, [])


def _season_from_dir(p: Path) -> int | None:
    for part in reversed(p.parts):
        m = re.match(r"^(?:S|Season\s*)(\d{1,2})\b", part, re.I)
        if m:
            return int(m.group(1))
    return None


def _show_score(query: str, folder: str) -> float:
    q = _fold(query)
    if not q:
        return 0.0
    en, _, zh = folder.partition("--")
    en_f = _fold(re.sub(r"\(\d{4}\)", "", en))
    zh_f = _fold(re.sub(r"\(\d{4}\)", "", zh))
    if q == _initials(folder):
        return 0.95
    best = max(difflib.SequenceMatcher(None, q, en_f).ratio(),
               difflib.SequenceMatcher(None, q, zh_f).ratio() if zh_f else 0.0)
    if q in en_f or (zh_f and q in zh_f):
        best = max(best, 0.9 if (en_f.startswith(q) or zh_f.startswith(q)) else 0.85)
    return round(best, 3)


# ---------------------------------------------------------------------------- resolution

def resolve_srt(rec: dict) -> tuple[Path | None, list[str]]:
    """The record's subtitle on disk, re-found by season/episode if it was renamed."""
    root = paths.get("subtitles")
    p = root / rec["srt_path"]
    if p.exists():
        return p, []
    eps = rec.get("episodes") or []
    found = []
    for d in [p.parent, p.parent.parent]:
        if not d.is_dir():
            continue
        for q in d.rglob("*"):
            if q.suffix.lower() in SUB_EXT and not q.name.endswith(".bookmarks"):
                season, qe = episode_of(q.name)
                if set(eps) & set(qe) and (season is None or rec.get("season") in (None, season)):
                    if not any(x in q.parts for x in REF_LANG_DIRS):
                        found.append(q)
        if found:
            break
    if len(found) == 1:
        return found[0], [f"manifest path is stale; the file is now {found[0].name}"]
    if found:
        return None, [f"manifest path is stale and {len(found)} files match this episode: "
                      + "; ".join(str(f) for f in found)]
    return None, [f"subtitle not found: {p}"]


# ---------------------------------------------------------------------------- the library on disk

AI_TREE = " (AI-generated)"
SEASONISH = re.compile(r"^(S\d|Season|Series\s*\d|E\d+-E?\d+|Blu-?ray|BD|DVD|NF|AMZN|Netflix|Disney|TVB|"
                       r"WIP|OVA|Specials?|Movies?)\b", re.I)


def show_names(folder: str) -> set[str]:
    """Folded names a show folder can be matched by: its English part (without year) and
    its Chinese part. 'Journey to the West -- 西遊記 (1996)' and 'Journey To the West - 西遊記'
    share 'journeytothewest' and '西遊記'."""
    name = re.sub(r"\(\d{4}\)", "", folder)
    parts = [p for p in re.split(r"\s+[-–—]{1,2}\s+", name) if p.strip()]
    out = {_fold(name)}
    out.update(_fold(p) for p in parts)
    return {n for n in out if len(n) >= 2}


def _show_slug(folder: str) -> str:
    en = re.split(r"\s+[-–—]{1,2}\s+", re.sub(r"\(\d{4}\)", "", folder))[0]
    year = re.search(r"\((\d{4})\)", folder)
    slug = re.sub(r"[^a-z0-9]+", "-", en.lower()).strip("-") or _fold(folder)[:30] or "show"
    return f"{slug}-{year.group(1)}" if year else slug


@lru_cache(maxsize=4096)
def _is_show_dir(d: str) -> bool:
    p = Path(d)
    if re.search(r" -- |\(\d{4}\)", p.name):
        return True
    try:
        kids = list(p.iterdir())
    except OSError:
        return False
    return any(k.is_file() and k.suffix.lower() in SUB_EXT for k in kids) or \
        any(k.is_dir() and SEASONISH.match(k.name) for k in kids)


@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    """Every subtitle file under CantoCaptions/Subtitles, AI-generated and WIP included, with
    its tree (Series/Dubbed, Series/Original (AI-generated), ...), show folder (skipping the
    genre folders of the AI trees) and season/episode. Reference-language folders are skipped."""
    root = paths.get("subtitles")
    out = []
    if not root.is_dir():
        return out
    for f in root.rglob("*.srt"):
        rel = f.relative_to(root)
        parts = rel.parts
        if len(parts) < 3 or any(p in REF_LANG_DIRS for p in parts):
            continue
        inner = parts[2:-1]
        show = None
        for i, comp in enumerate(inner):
            if _is_show_dir(str(root.joinpath(*parts[:2], *inner[:i + 1]))):
                show = (i, comp)
                break
        if show is None:
            show = (0, inner[0]) if inner else (None, f.stem)
        season, eps = episode_of(f.name)
        if season is None:
            season = _season_from_dir(Path(*parts[:-1]))
        out.append({"srt_path": rel.as_posix(), "category": parts[0], "tree": parts[1],
                    "show_folder": show[1], "season": season, "episodes": eps,
                    "ai_generated": AI_TREE in parts[1] or f.name.upper().startswith("[CCAI]"),
                    "wip": "WIP" in f.name or "WIP" in inner})
    return out


def _catalog_record(entry: dict) -> dict:
    """A manifest-shaped record for a library file the dataset manifest does not cover."""
    eps = entry["episodes"]
    tag = (f"s{entry['season']:02d}" if entry["season"] else "") + (f"e{eps[0]:02d}" if eps else "")
    kind = "ai" if entry["ai_generated"] else ("wip" if entry["wip"] else "local")
    slug = _show_slug(entry["show_folder"])
    return {"episode_id": f"{slug}_{tag or _fold(Path(entry['srt_path']).stem)[:20]}_{kind}",
            "srt_path": entry["srt_path"], "show_slug": slug, "season": entry["season"],
            "episodes": eps, "media_path": None, "synthesised": True,
            "ai_generated": entry["ai_generated"], "tree": entry["tree"],
            "category": entry["category"], "show_folder": entry["show_folder"],
            "exclusion": "AI-generated" if entry["ai_generated"] else ("WIP" if entry["wip"] else None)}


def _media_dirs_for(rec: dict) -> list[Path]:
    """Folders holding media of the same show (and season when known), best first: where the
    show's other episodes have media, else a media folder with the same show name in the same
    category (Series, Movies...), whichever tree it is in."""
    media_root = paths.get("media_root")
    same_show = [r for r in manifest() if r.get("show_slug") == rec.get("show_slug") and r.get("media_path")]
    same_season = [r for r in same_show if r.get("season") == rec.get("season")]
    dirs = []
    for r in same_season + same_show:
        d = (media_root / r["media_path"]).parent
        if d not in dirs and d.is_dir():
            dirs.append(d)
    if dirs:
        return dirs
    rel = Path(rec["srt_path"])
    # Mirroring the library's folders onto the media root only means something for a file
    # inside the library (a relative srt_path) and a media root that exists.
    if len(rel.parts) < 3 or rel.is_absolute() or not media_root.is_dir():
        return dirs
    folder = rec.get("show_folder") or rel.parts[2]
    want = show_names(folder)
    category = media_root / rel.parts[0]
    tree = rel.parts[1].replace(AI_TREE, "")
    trees = [category / tree] + ([t for t in category.iterdir() if t.is_dir() and t.name != tree]
                                 if category.is_dir() else [])
    for t in trees:
        if not t.is_dir():
            continue
        for d in [x for x in t.iterdir() if x.is_dir()] + [y for x in t.iterdir() if x.is_dir() for y in x.iterdir() if y.is_dir()]:
            if show_names(d.name) & want:
                dirs += [d] + [s for s in d.rglob("*") if s.is_dir()]
        if dirs:
            break
    return dirs


def resolve_media(rec: dict) -> tuple[Path | None, list[str]]:
    if rec.get("media_path"):
        p = paths.get("media_root") / rec["media_path"]
        if p.exists():
            return p, []
    eps = rec.get("episodes") or []
    if not eps:
        return None, ["no episode number to look media up by"]
    hits = []
    for d in _media_dirs_for(rec):
        dir_season = _season_from_dir(d)
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in MEDIA_EXT:
                continue
            season, fe = episode_of(f.name)
            season = season if season is not None else dir_season
            if fe and fe[0] == eps[0] and (rec.get("season") is None or season in (None, rec.get("season"))):
                hits.append(f)
        if hits:
            break
    if len(hits) == 1:
        return hits[0], [f"media inferred (same episode number in the show's media folder): {hits[0].name}"]
    if hits:
        return None, ["several media files match: " + "; ".join(str(h) for h in hits)
                      + " (choose with --media)"]
    return None, ["no media found for this episode (give it with --media)"]


def resolved(rec: dict) -> dict:
    srt, n1 = resolve_srt(rec)
    media, n2 = resolve_media(rec)
    tier = corpus.episodes().get(rec["episode_id"], {})
    rel = rec["srt_path"]
    extra = {}
    if media is None and paths.media_dirs():
        found = _search(_record_query(rec), rec.get("season"), (rec.get("episodes") or [None])[0])
        if found["media_candidates"]:
            extra = {"media_candidates": found["media_candidates"], "needs_confirmation": True}
            n2 = n2 + ["media candidates found by name in your media folders: confirm one with the "
                       "user, then `ccp locate --select <episode_id> --media PATH` (or --srt ... --media PATH)"]
    return {**extra,
        "episode_id": rec["episode_id"],
        "srt": str(srt) if srt else None,
        "media": str(media) if media else None,
        "media_exists": bool(media and media.exists()),
        "tier": tier.get("tier", "unknown"), "std_score": tier.get("score"),
        "exclusion": rec.get("exclusion"),
        "ai_generated": rec.get("ai_generated", AI_TREE in rel),
        "tree": rec.get("tree") or (Path(rel).parts[1] if len(Path(rel).parts) > 1 else None),
        "notes": n1 + n2,
    }


summary = resolved   # kept for callers


# ---------------------------------------------------------------------------- your own media folders
#
# Without the dataset nothing links a subtitle to its media, so the user's media folders
# (`media_dirs`) are indexed and searched by show name and episode, like the library above.
# Names are matched loosely (release-name junk, initials, either language of a bilingual
# folder), which is why a match is always a *candidate* the user confirms.

INDEX_VERSION = 1
INDEX_MAX_AGE_S = 24 * 3600
_SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information"}
_EPISODE_TAG = re.compile(r"\bS\d{1,2}\s*E[Pp]?\d|\bE[Pp]?\s*\d{1,4}\b|(?<![\w])-\s*\d{1,4}\b|\b\d{1,4}\s*$"
                          r"|第\s*\d+\s*[集話话]|\b(?:19|20)\d\d\b|\b\d{3,4}p\b", re.I)


def title_part(stem: str) -> str:
    """The show-name part of a release file name: bracketed tags, the episode tag and all
    after it dropped. '[MiniMTBB] Shingeki no Kyojin - 26 (BD 1080p) [8A68A9A7]' ->
    'Shingeki no Kyojin'; 'Ghost.in.the.Shell.S01E01.1080p-Main10' -> 'Ghost in the Shell'."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", " ", stem)
    t = re.sub(r"[._]+", " ", t)
    m = _EPISODE_TAG.search(t)
    if m:
        t = t[:m.start()]
    return re.sub(r"\s+", " ", t).strip(" -_")


def _index_path() -> Path:
    return paths.cache_dir() / "media_index.json"


def media_index(rescan: bool = False) -> list[dict]:
    """Every media and subtitle file under the media folders, with its folders (relative to
    the media folder) and season/episode. Cached for a day in cache/media_index.json, and
    rebuilt at once when the folder list changes or with *rescan*."""
    dirs = [str(d) for d in paths.media_dirs()]
    p = _index_path()
    if not rescan and p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if (data.get("version") == INDEX_VERSION and data.get("dirs") == dirs
                    and time.time() - data.get("built", 0) < INDEX_MAX_AGE_S):
                return data["files"]
        except (ValueError, KeyError):
            pass
    files = []
    for root in dirs:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
            rel = Path(dirpath).relative_to(root)
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                kind = "media" if ext in MEDIA_EXT else "subtitle" if ext in SUB_EXT else None
                if kind is None:
                    continue
                season, eps = episode_of(fn)
                if season is None and rel.parts:
                    season = _season_from_dir(rel)
                files.append({"path": str(Path(dirpath) / fn), "kind": kind,
                              "folders": list(rel.parts), "season": season, "episodes": eps})
    p.write_text(json.dumps({"version": INDEX_VERSION, "dirs": dirs, "built": time.time(),
                             "files": files}, ensure_ascii=False), encoding="utf-8")
    return files


def _media_score(query: str, f: dict) -> float:
    names = [*f["folders"], title_part(Path(f["path"]).stem)]
    return max((_show_score(query, n) for n in names if n), default=0.0)


def _subtitles_near(f: dict, subs_by_dir: dict) -> list[str]:
    """Subtitle files beside a media file that belong to it: the same stem, or the same episode."""
    media = Path(f["path"])
    out = []
    for s in subs_by_dir.get(str(media.parent), []):
        sp = Path(s["path"])
        same_stem = sp.stem.lower().startswith(media.stem.lower())
        same_ep = bool(set(s["episodes"]) & set(f["episodes"])) and \
            (s["season"] is None or f["season"] is None or s["season"] == f["season"])
        if same_stem or same_ep:
            out.append(str(sp))
    return sorted(out)


def _suggested_id(f: dict, query: str) -> str:
    # Named after whichever name matched the request best: the show folder, or the file's title.
    names = [n for n in [*f["folders"], title_part(Path(f["path"]).stem)] if n and not SEASONISH.match(n)]
    name = max(names, key=lambda n: _show_score(query, n), default="") or query
    eps = f["episodes"]
    tag = (f"s{f['season']:02d}" if f["season"] else "") + (f"e{eps[0]:02d}" if eps else "")
    return f"{_show_slug(name)}_{tag or 'x'}_local"


def _search(query: str, season: int | None, episode: int | None, rescan: bool = False,
            limit: int = 8) -> dict:
    files = media_index(rescan)
    subs_by_dir = defaultdict(list)
    for f in files:
        if f["kind"] == "subtitle":
            subs_by_dir[str(Path(f["path"]).parent)].append(f)
    scored = []
    for f in files:
        if f["kind"] != "media":
            continue
        if episode is not None and episode not in f["episodes"]:
            continue
        if season is not None and f["season"] not in (None, season):
            continue
        sc = _media_score(query, f) if query else 0.0
        if sc >= 0.5:
            scored.append((round(sc, 3), f))
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))
    top = [x for x in scored if x[0] >= scored[0][0] - 0.15][:limit] if scored else []
    return {"media_candidates": [{"path": f["path"], "score": sc, "season": f["season"],
                                  "episodes": f["episodes"],
                                  "subtitles_near": _subtitles_near(f, subs_by_dir),
                                  "suggested_id": _suggested_id(f, query)} for sc, f in top],
            "more_media": max(0, len(scored) - len(top))}


def _record_query(rec: dict) -> str:
    """The show name of a library record, for searching media by name."""
    rel = Path(rec.get("srt_path") or "")
    # Only a library-relative path has the show folder at a known depth; a file elsewhere is
    # named by its own release name, or its folder's.
    if rel.is_absolute():
        return title_part(rel.stem) or title_part(rel.parent.name)
    folder = rec.get("show_folder") or (rel.parts[2] if len(rel.parts) > 2 else "")
    if folder:
        return re.split(r"\s+[-–—]{1,2}\s+", re.sub(r"\(\d{4}\)", "", folder))[0].strip()
    return title_part(rel.stem)


MEDIA_CONFIRM = ("Matched by name only. Show the user the best candidate (path, and the subtitle "
                 "you would proofread) and ask whether it is the right episode; never use one "
                 "unconfirmed. Then create the workspace with `ccp locate --srt SUBTITLE --media MEDIA "
                 "--id ID` (a subtitle from subtitles_near, or one the user names), or `--media MEDIA "
                 "--id ID` alone for an episode with no subtitle yet.")


def search_media(request: str, rescan: bool = False, limit: int = 8) -> dict:
    """Media in the user's media folders matching a free-text request ('AoT S2E26')."""
    query, season, episode = parse_request(request)
    words = query.split()
    query = " ".join(w for w in words if w.lower() not in REQUEST_NOISE) or query
    out = {"query": query, "season": season, "episode": episode,
           "media_dirs": [str(d) for d in paths.media_dirs()]}
    if not out["media_dirs"]:
        out.update(media_candidates=[], note=(
            "no media folders are set (and no dataset links subtitles to media): ask the user "
            "for the files and run `ccp locate --srt PATH --media PATH --id NAME`, or add a "
            "folder with `ccp setup --add-media-dir PATH`"))
        return out
    out.update(_search(query, season, episode, rescan, limit))
    if out["media_candidates"]:
        out.update(needs_confirmation=True, next=MEDIA_CONFIRM)
    else:
        out["note"] = ("nothing in the media folders matches; ask the user for the media file "
                       "(`ccp locate ... --media PATH`), or `--rescan` if it was added today")
    return out


# ---------------------------------------------------------------------------- lookups

REQUEST_NOISE = {"the", "subtitles", "subtitle", "subs", "sub", "for", "of", "episode", "please",
                 "ai", "ai-generated", "generated", "ccai", "aigen", "wip", "file", "files"}


def _folders() -> dict[str, list[dict]]:
    """Show folder -> records: every library file on disk (manifest record when the dataset
    knows it, a synthesised one otherwise), plus manifest records whose file has moved."""
    by_path = {r["srt_path"]: r for r in manifest()}
    folders: dict[str, list[dict]] = {}
    on_disk = set()
    for e in catalog():
        on_disk.add(e["srt_path"])
        rec = by_path.get(e["srt_path"])
        rec = {**rec, "ai_generated": e["ai_generated"], "tree": e["tree"]} if rec else _catalog_record(e)
        folders.setdefault(e["show_folder"], []).append(rec)
    for r in manifest():
        if r["srt_path"] not in on_disk:
            folders.setdefault(_show_folder(r), []).append(r)
    return folders


def find(request: str, include_excluded: bool = True, limit: int = 8, rescan: bool = False) -> dict:
    """Records matching a request, from the dataset manifest *and* the library on disk (so
    AI-generated, WIP and not-yet-scanned files are found too). Words like "AI" or "WIP" in
    the request rank those files first; otherwise finished files come first."""
    query, season, episode = parse_request(request)
    words = query.split()
    want_ai = any(w.lower() in ("ai", "ai-generated", "ccai", "aigen") for w in words)
    want_wip = any(w.lower() == "wip" for w in words)
    query = " ".join(w for w in words if w.lower() not in REQUEST_NOISE) or query
    folders = _folders()
    if not folders:
        # No library and no dataset on this machine: look for the media by name instead.
        return {"shows": [], "closest_shows": [], "candidates": [], "more": 0,
                "library": "none (see `ccp setup`)", **search_media(request, rescan, limit)}
    scored = sorted(((_show_score(query, f), f) for f in folders), reverse=True)
    top = [f for s, f in scored if s >= max(0.5, scored[0][0] - 0.1)][:3] if scored else []
    candidates = []
    for f in top:
        for rec in folders[f]:
            if season is not None and rec.get("season") not in (season, None):
                continue
            if episode is not None and episode not in (rec.get("episodes") or []):
                continue
            if rec.get("exclusion") and not include_excluded:
                continue
            candidates.append(rec)
    is_ai = lambda r: bool(r.get("ai_generated") or AI_TREE in r["srt_path"])
    is_wip = lambda r: "WIP" in r["srt_path"]
    candidates.sort(key=lambda r: (want_ai != is_ai(r), want_wip != is_wip(r),
                                   bool(r.get("exclusion")) and not (want_ai or want_wip)))
    out = {"query": query, "season": season, "episode": episode,
           "shows": list(top),
           "closest_shows": [{"show": f, "score": sc} for sc, f in scored[:5]],
           "candidates": [resolved(r) for r in candidates[:limit]],
           "more": max(0, len(candidates) - limit)}
    if not candidates and paths.media_dirs():
        # Not in the library: it may be an episode the user has only as media (and subtitles
        # beside it).
        found = search_media(request, rescan, limit)
        out.update({k: v for k, v in found.items() if k not in out})
    return out


def by_id(episode_id: str) -> dict | None:
    """A record by episode id: the manifest's, else one synthesised from the library on disk
    (AI-generated, WIP or not-yet-scanned files)."""
    rec = next((r for r in manifest() if r["episode_id"] == episode_id), None)
    if rec is not None:
        return rec
    return next((r for recs in _folders().values() for r in recs if r["episode_id"] == episode_id), None)


def record_for_srt(path: str) -> dict:
    """The manifest record for a subtitle path, re-found by season/episode if the file was
    renamed, or synthesised from the path when the manifest has never seen it."""
    p = Path(path).resolve()
    root = paths.get("subtitles")
    try:
        rel = p.relative_to(root)
    except ValueError:
        rel = None
    if rel is not None:
        rel_s = rel.as_posix()
        for rec in manifest():
            if rec["srt_path"] == rel_s:
                return rec
        entry = next((e for e in catalog() if e["srt_path"] == rel_s), None)
        if entry is not None:
            return _catalog_record(entry)
        season, eps = episode_of(p.name)
        season = season if season is not None else _season_from_dir(p.parent)
        same_dir = [r for r in manifest() if Path(r["srt_path"]).parent == rel.parent]
        for r in same_dir:
            if eps and set(eps) & set(r.get("episodes") or []) and r.get("season") in (None, season):
                return {**r, "srt_path": rel_s}           # the record of a renamed file
        show_recs = [r for r in manifest() if len(rel.parts) > 2 and _show_folder(r) == rel.parts[2]]
        slug = show_recs[0]["show_slug"] if show_recs else _fold(rel.parts[2] if len(rel.parts) > 2 else p.stem)[:40]
    else:
        season, eps = episode_of(p.name)
        slug = _fold(p.parent.name)[:40] or "file"
    ep_tag = (f"s{season:02d}" if season else "") + (f"e{eps[0]:02d}" if eps else "")
    return {"episode_id": f"{slug}_{ep_tag or _fold(p.stem)[:20]}_local",
            "srt_path": rel.as_posix() if rel is not None else str(p),
            "show_slug": slug, "season": season, "episodes": eps, "media_path": None,
            "synthesised": True}


# ---------------------------------------------------------------------------- media probes

def audio_tracks(media: str) -> list[dict]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index,codec_name,channels:stream_tags=language,title", "-of", "json", media],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        streams = json.loads(out.stdout or "{}").get("streams", [])
    except Exception:
        return []
    return [{"track": i, "codec": s.get("codec_name"), "channels": s.get("channels"),
             "language": (s.get("tags") or {}).get("language", ""),
             "title": (s.get("tags") or {}).get("title", "")} for i, s in enumerate(streams)]


def pick_cantonese(tracks: list[dict]) -> int:
    """yue / 'cantonese' / 粵 first, then any Chinese track, then the first."""
    for t in tracks:
        if t["language"].lower() == "yue" or re.search(r"cantonese|粵|粤|廣東", t["title"], re.I):
            return t["track"]
    for t in tracks:
        if t["language"].lower() in ("chi", "zho", "zh"):
            return t["track"]
    return 0


def subtitle_streams(media: str) -> list[dict]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
             "stream=index,codec_name:stream_tags=language,title:stream_disposition=forced",
             "-of", "json", media], capture_output=True, text=True, encoding="utf-8", timeout=60)
        streams = json.loads(out.stdout or "{}").get("streams", [])
    except Exception:
        return []
    bitmap = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
    return [{"sub_index": i, "stream_index": s.get("index"), "codec": s.get("codec_name"),
             "kind": "bitmap" if s.get("codec_name") in bitmap else "text",
             "language": (s.get("tags") or {}).get("language", ""),
             "title": (s.get("tags") or {}).get("title", ""),
             "forced": bool((s.get("disposition") or {}).get("forced"))} for i, s in enumerate(streams)]


def reference_files(srt: str | None, media: str | None, season: int | None, eps: list[int]) -> list[str]:
    """Existing reference-language subtitle files for this episode: CantoCaptions'
    Standard Chinese / English / Simplified folders and *.chs siblings, and subtitle files
    next to the media."""
    out = []

    def same_episode(name: str) -> bool:
        s, e = episode_of(name)
        return bool(set(e) & set(eps)) and (s is None or season is None or s == season)

    if srt:
        srt_p = Path(srt)
        show_dir = srt_p.parent
        for d in [show_dir, show_dir.parent]:
            for sub in REF_LANG_DIRS:
                for p in sorted((d / sub).rglob("*.srt")) if (d / sub).is_dir() else []:
                    if same_episode(p.name):
                        out.append(str(p))
        for p in sorted(show_dir.glob("*.srt")):
            if p != srt_p and re.search(r"\.chs\.srt$|\.chi\.srt$|\.zh", p.name) and same_episode(p.name):
                out.append(str(p))
    if media:
        m = Path(media)
        if m.parent.exists():
            for p in sorted(m.parent.iterdir()):
                if p.suffix.lower() in (".srt", ".ass", ".ssa") and (
                        p.stem.startswith(m.stem) or same_episode(p.name)):
                    out.append(str(p))
    return list(dict.fromkeys(out))
