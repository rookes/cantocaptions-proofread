"""ccp report: a self-contained review page for an episode's flags.

work/<id>/report.html + work/<id>/clips/flag_<n>.m4a (cue ± 1 s, the episode's Cantonese
track; --video adds a 480p mp4). Opens from file:// with no server. Each flag can be
accepted (optionally with edited text) or rejected; "Export decisions" downloads a
decisions.json that `ccp apply --decisions` consumes.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import episode, flags as flagstore
from .render import _ref_placement
from .srtio import short_time

CLIP_PAD = 1.0
CLIP_STATUS: dict = {}       # filled by build(): clips made / failed, for the command's output
GRADE_ORDER = {"fix": 0, "suggest": 1, "query": 2, "keep": 3}


def audio_delay(media: str, track: int) -> float:
    """Seconds the audio track starts after the container's zero (a muxed delay: some dubs put
    their audio a second or more after the video). The same measure as cantocaptions-ai's
    `container_audio_delay`, which the evidence and listen audio already honour."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-select_streams", "a",
           "-show_format", media]
    try:
        data = json.loads(subprocess.run(cmd, capture_output=True, check=False).stdout or b"{}")
    except (OSError, ValueError):
        return 0.0
    streams = data.get("streams") or []
    if not streams:
        return 0.0
    stream = streams[track] if track < len(streams) else streams[0]

    def start(obj) -> float:
        try:
            return float(obj.get("start_time"))
        except (TypeError, ValueError):
            return 0.0
    return max(start(stream) - start(data.get("format") or {}), 0.0)


def _clip(media: str, track: int, start: float, end: float, out: Path, video: bool,
          delay: float = 0.0) -> str | None:
    """Cut one clip; None on success, else the error.

    ffmpeg seeks on the container's timeline, which is right once past a muxed audio delay.
    Inside the delay there is no audio to seek to, so it starts at the first audio packet and
    the clip would come out short, with the speech early. The missing lead is put back as
    silence (`adelay`) on an audio track rebased to the clip's zero (`asetpts`), so the clip
    covers [start, end] exactly, with the video too (players do not reliably honour an audio
    start offset inside an mp4)."""
    if out.exists() and out.stat().st_size > 0:
        return None
    lead_ms = round((delay - start) * 1000)
    pad = ["-af", f"adelay={lead_ms}:all=1,asetpts=PTS-STARTPTS"] if lead_ms > 0 else []
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", media]
    if video:
        cmd += ["-map", "0:v:0", "-map", f"0:a:{track}", "-vf", "scale=-2:480", *pad, "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                "-movflags", "+faststart", str(out)]
    else:
        cmd += ["-map", f"0:a:{track}", "-vn", *pad, "-ac", "1", "-c:a", "aac", "-b:a", "96k", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return None
    except FileNotFoundError:
        return "ffmpeg was not found on PATH"
    except subprocess.CalledProcessError as e:
        lines = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return lines[-1] if lines else f"ffmpeg exited with {e.returncode}"
    except Exception as e:
        return str(e)


def _diff_html(a: str, b: str) -> tuple[str, str]:
    """The draft and the proposal as two rows that line up character for character: each
    changed piece sits in a cell (`.seg`) that is also sized by the other row's piece, so both
    rows reserve the width of the wider one. The other piece lives in an attribute drawn by an
    invisible ::before, which a browser never copies; the cell is an inline-block, because an
    inline grid makes Chrome copy a line break on each side of it. Line breaks show as ⏎ to
    keep each text on one row."""
    a, b = a.replace("\n", "⏎"), b.replace("\n", "⏎")
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    left, right = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = html.escape(a[i1:i2]), html.escape(b[j1:j2])
        if op == "equal":
            left.append(x)
            right.append(y)
        else:
            left.append(f'<span class="seg" data-w="{y}">{f"<del>{x}</del>" if x else ""}</span>')
            right.append(f'<span class="seg" data-w="{x}">{f"<ins>{y}</ins>" if y else ""}</span>')
    return "".join(left), "".join(right)


# Words a reviewer may not know, as the tools once printed them and records may still carry:
# numbers from the audio scorer and the aligner become what they mean. Records written now say
# it in words already (investigate-line, "Recording"); this keeps older ones readable.
_NUM = r"[+-]?\d+(?:\.\d+)?"
_CJK = "㐀-鿿\U00020000-\U0003134f"


def _fit(m) -> str:
    from .ctcscore import plain_fit
    return plain_fit(float(m.group(1)))


_PLAIN = [
    (re.compile(rf"\bCTC\b(?:\s+score)?(?:\s+(?:favou?rs)(?:\s+(?:the\s+fix|it|this|the\s+candidate))?)?"
                rf"(?:\s+by)?\s+({_NUM})(?:\s*nats)?", re.I), lambda m: "the audio check: " + _fit(m)),
    (re.compile(rf"(?:scores?\s+)?({_NUM})\s*nats(?:\s+over\s+(?:the\s+)?draft)?", re.I), _fit),
    (re.compile(r"(?:has\s+)?(?:alignment\s+|aligner\s+)?peaks?\s+(?:of\s+)?0\.\d+(?:\s*/\s*0\.\d+)*", re.I),
     lambda m: ("is " if m.group(0).lower().startswith("has") else "") + "barely heard"),
    (re.compile(rf"\bweak\s+(?=[{_CJK}])"), lambda m: ""),
    (re.compile(rf"([{_CJK}])\s+0\.[0-2]\d\b"), lambda m: f"{m.group(1)} barely heard"),
    (re.compile(r"(?:has\s+(?:a\s+)?)?sound_distance\s+(?:of\s+)?(\d\.\d+)"), lambda m: "sounds " + _sounds(float(m.group(1)))),
    (re.compile(rf"\bR\s+(?=[{_CJK}])"), lambda m: "the reference "),
    (re.compile(r"(?<![\w&])R(?![\w&])"), lambda m: "the reference"),
    (re.compile(r"\bCTC\b"), lambda m: "audio check"),
    (re.compile(r"\b(?:asr_)?ft\b"), lambda m: "the CantoCaptions recogniser"),
    (re.compile(r"\b(?:asr_)?(?:qw|qwen)\b", re.I), lambda m: "Qwen"),
]


def _sounds(cost: float) -> str:
    from .sound import plain_distance
    return plain_distance(cost)


def plain(text: str) -> str:
    for rx, sub in _PLAIN:
        text = rx.sub(sub, text)
    return text


def _title(ep: dict) -> str:
    """A readable title: the show's name and episode, else the file name without release tags."""
    from .locate import title_part
    name = None
    if ep.get("show_folder"):
        name = re.split(r"\s+[-–—]{1,2}\s+", re.sub(r"\(\d{4}\)", "", ep["show_folder"]))[0].strip()
    stem = Path(ep.get("source_srt") or ep.get("srt") or ep["episode_id"]).stem
    name = name or title_part(stem) or stem
    eps, season = ep.get("episodes") or [], ep.get("season")
    tag = (f"S{season}" if season else "") + (f"E{eps[0]:02d}" if eps else "")
    return f"{name} · {tag}" if tag else name


def _reference_note(ep_id: str) -> dict | None:
    p = episode.path(ep_id, "reference.json")
    if not p.exists():
        return None
    r = json.loads(p.read_text(encoding="utf-8"))
    src = str(r.get("source") or "")
    kind = "OCR of the video's image subtitles" if src.startswith("OCR of") else \
        "the video's own subtitle track" if " stream " in src else "a subtitle file"
    lang = "Chinese" if r.get("chinese") else "another language"
    agreement = r.get("agreement")
    timing = None if agreement is None else ("lines up with the subtitles" if agreement >= 0.6
                                             else "timed differently: a reference line may sit next to the wrong cue")
    return {"text": f"{lang}, from {kind}", "timing": timing, "file": src}


def build(episode_id: str, video: bool = False, include_rejected: bool = False) -> Path:
    from . import signals, stats as passstats
    ep = episode.load(episode_id)
    srt = episode.srt(ep)
    flags = [f for f in flagstore.load(episode_id) if include_rejected or f["status"] != "rejected"]
    flags.sort(key=lambda f: (GRADE_ORDER[f["grade"]], f["cue"]))
    work = episode.path(episode_id, "x").parent
    clips = work / "clips"
    clips.mkdir(exist_ok=True)
    refs = _ref_placement(srt.cues, episode.reference_cues(episode_id))
    evidence = {e["cue"]: e for e in episode.read_jsonl(episode_id, "evidence.jsonl")}
    media_ok = ep.get("media_exists") and ep.get("media")
    CLIP_STATUS.clear()
    # Every flag gets a clip, cleanup edits included. A cleanup pass can make hundreds of
    # edits, so clips are cut in parallel (ffmpeg seeks before decoding; each one is short).
    clip_of: dict[int, str] = {}
    if media_ok:
        delay = audio_delay(ep["media"], ep.get("audio_track", 0))

        def cut(f):
            cue = srt.cue(f["cue"])
            name = f"flag_{f['id']}.{'mp4' if video else 'm4a'}"
            err = _clip(ep["media"], ep.get("audio_track", 0), max(0.0, cue.start - CLIP_PAD),
                        cue.end + CLIP_PAD, clips / name, video, delay)
            return f["id"], (None if err else f"clips/{name}"), err
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
            done = list(pool.map(cut, flags))
        clip_of = {k: v for k, v, _ in done if v}
        errors = [e for _, _, e in done if e]
        CLIP_STATUS.update({"clips": len(clip_of), "failed": len(errors)},
                           **({"first_error": errors[0]} if errors else {}))
    else:
        CLIP_STATUS.update({"clips": 0, "note": "no media linked: the report has no audio"})
    stats = passstats.compute(episode_id)
    passstats.save(episode_id, stats)
    sig = signals.load(episode_id)
    items = []
    for f in flags:
        cue = srt.cue(f["cue"])
        clip_rel = clip_of.get(f["id"])
        cleanup = f.get("pass") == "cleanup"
        current = cue.text
        before = f.get("draft_shown") or f["draft"]       # with invisible characters spelled out
        left, right = _diff_html(before, f["proposed"]) if f.get("proposed") is not None else (html.escape(f["draft"].replace("\n", "⏎")), "")
        prev = srt.cue(f["cue"] - 1).text if f["cue"] > 1 else None
        nxt = srt.cue(f["cue"] + 1).text if f["cue"] < len(srt.cues) else None
        ev = evidence.get(f["cue"], {})
        asr = {k: (v.get("edge_before", "") and f"[{v['edge_before']}]") + v.get("text", "")
               + (v.get("edge_after", "") and f"[{v['edge_after']}]") for k, v in ev.get("asr", {}).items()}
        items.append({
            "id": f["id"], "cue": f["cue"], "time": short_time(f["start"]),
            "grade": f["grade"], "category": f["category"], "reason": plain(f.get("reason", "")),
            "status": f["status"], "draft": f["draft"], "draft_html": left, "proposed_html": right,
            "proposed": f.get("proposed"), "alternatives": f.get("alternatives", []),
            "current_at": f"{short_time(cue.start)}–{short_time(cue.end)}",
            "proposed_cues": [{"at": f"{short_time(c['start'])}–{short_time(c['end'])}", "text": c["text"]}
                              for c in f.get("proposed_cues") or []],
            "stale": current != (f.get("applied_text") if f["status"] == "applied"
                                 and isinstance(f.get("applied_text"), str) else f["draft"])
                     and not (f["status"] == "applied" and f.get("proposed_cues")),
            "applied_text": f.get("applied_text") if isinstance(f.get("applied_text"), str) else None,
            "evidence": [{**e, "detail": plain(str(e.get("detail", "")))} for e in f["evidence"]],
            "reference": refs.get(f["cue"], []), "asr": asr, "prev": prev, "next": nxt, "clip": clip_rel,
            "cleanup": cleanup, "found_by": passstats.found_by(f, sig),
        })
    meta = {
        "episode_id": episode_id, "title": _title(ep), "srt": ep["srt"],
        "source_srt": ep.get("source_srt"), "media": ep.get("media"),
        "reference": _reference_note(episode_id), "summary": flagstore.summary(flags), "video": video,
        "machine_draft": episode.machine_draft(ep), "audio_checked": bool(evidence),
        "kinds": {k: {"label": v[0], "tip": v[1]} for k, v in signals.KINDS.items()},
        "stats": stats,
    }
    page = TEMPLATE.replace("__TITLE__", html.escape(meta["title"])).replace(
        "__DATA__", json.dumps({"meta": meta, "items": items}, ensure_ascii=False).replace("</", "<\\/"))
    out = work / "report.html"
    out.write_text(page, encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="yue-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proofread: __TITLE__</title>
<style>
:root { --bg:#fafaf8; --fg:#1d1d1b; --muted:#6b6b66; --card:#ffffff; --line:#e3e2dc; --soft:#f1f0ea;
  --del:#fde2e1; --del-fg:#9b1c1c; --ins:#dcf3e1; --ins-fg:#14532d; --accent:#2f5d8a;
  --ess:#b42318; --sug:#b26b00; --qry:#5b5b8f; --tool:#2f6f5e; --agent:#7a4f9a; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe6; --muted:#9a9993;
  --card:#1f1f1d; --line:#33322f; --soft:#262624; --del:#3d1f1f; --del-fg:#f4a3a3; --ins:#1d3324; --ins-fg:#9fdcae;
  --accent:#8db8e6; --ess:#f08a80; --sug:#f0b860; --qry:#a9a9e0; --tool:#8fd1bd; --agent:#c9a6e6; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 system-ui, "Segoe UI", "Microsoft JhengHei", "PingFang HK", "Noto Sans HK", sans-serif; }
main { max-width:920px; margin:0 auto; padding:24px 16px 80px; }
h1 { font-size:22px; margin:2px 0 10px; } h2 { font-size:16px; margin:32px 0 10px; }
.eyebrow { color:var(--muted); font-size:12px; letter-spacing:.06em; text-transform:uppercase; }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; }
.chip { font-size:13px; padding:2px 10px; border-radius:99px; background:var(--soft); border:1px solid var(--line); }
.chip b { font-weight:650; }
.facts { display:grid; grid-template-columns:max-content 1fr; gap:3px 14px; font-size:14px; margin:0 0 8px; }
.facts dt { color:var(--muted); } .facts dd { margin:0; }
.howto { font-size:14px; background:var(--soft); border-radius:8px; padding:8px 12px; margin:10px 0 0; }
details.files { font-size:12px; color:var(--muted); margin-top:8px; word-break:break-all; }
details.files summary { cursor:pointer; }
.bar { position:sticky; top:0; background:var(--bg); padding:10px 0; display:flex; gap:8px;
  flex-wrap:wrap; align-items:center; border-bottom:1px solid var(--line); z-index:3; margin-top:14px; }
button, select { font:inherit; font-size:13px; padding:5px 10px; border-radius:6px;
  border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }
button.primary { background:var(--accent); color:var(--bg); border-color:var(--accent); }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:10px 0; }
.card.accepted { border-left:4px solid var(--ins-fg); } .card.rejected { opacity:.55; }
.head { display:flex; gap:8px; flex-wrap:wrap; align-items:baseline; font-size:13px; color:var(--muted); }
.head .where { color:var(--fg); font-weight:600; }
.head .found { margin-left:auto; display:flex; gap:4px; align-items:baseline; }
.badge { font-size:12px; padding:1px 7px; border-radius:99px; border:1px solid currentColor; }
.fix { color:var(--ess); } .suggest { color:var(--sug); } .query { color:var(--qry); } .keep { color:var(--muted); }
.by { font-size:11px; padding:0 6px; border-radius:4px; border:1px solid currentColor; position:relative; cursor:help; }
.by.tool { color:var(--tool); } .by.agent { color:var(--agent); }
.reason { font-size:14px; margin:8px 0 2px; } .reason b { color:var(--accent); }
details.kept > summary { cursor:pointer; font-size:16px; font-weight:600; margin:32px 0 10px; }
.text { font-size:19px; margin:8px 0 2px; }
.label { color:var(--muted); font-size:12px; margin-right:6px; }
del { background:var(--del); color:var(--del-fg); text-decoration:line-through; }
ins { background:var(--ins); color:var(--ins-fg); text-decoration:none; }
.pair { display:grid; grid-template-columns:5.5em 1fr; column-gap:6px; align-items:baseline; margin:8px 0 2px; }
.pair .label { margin:0; } .pair .line { font-size:19px; white-space:pre; overflow-x:auto; }
.row .pair .line { font-size:16px; }
.seg { display:inline-block; }
.seg::before { content:attr(data-w); display:block; height:0; overflow:hidden; visibility:hidden; }
/* A labelled line: a small boxed tag (hover for what it is), then the text. */
.lines { display:grid; grid-template-columns:5.5em 1fr; column-gap:6px; row-gap:2px; margin:8px 0 2px; align-items:baseline; }
.lines .t { font-size:15px; } .lines .t.dim { color:var(--muted); font-size:14px; }
.lines .note { grid-column:2; font-size:13px; color:var(--muted); }
.tag { justify-self:start; display:inline-block; font:600 11px/1.5 ui-monospace, Consolas, monospace; padding:0 5px;
  border:1px solid currentColor; border-radius:4px; color:var(--muted); position:relative; cursor:help; white-space:nowrap; }
.tag.ref { color:var(--accent); }
[data-tip]:hover::after { content:attr(data-tip); position:absolute; left:0; top:calc(100% + 4px); z-index:5;
  background:var(--fg); color:var(--bg); font:12px/1.4 system-ui, sans-serif; padding:3px 8px; border-radius:5px;
  white-space:nowrap; pointer-events:none; }
.found [data-tip]:hover::after { left:auto; right:0; }
.ev { font-size:13px; margin:8px 0 0; padding-left:0; list-style:none; } .ev li { margin:2px 0; }
.ev .src { color:var(--muted); font-size:12px; margin-right:6px; }
.small { font-size:13px; color:var(--muted); } audio, video { width:100%; max-width:480px; margin-top:8px; }
.actions { display:flex; gap:6px; margin-top:10px; flex-wrap:wrap; align-items:center; }
textarea { width:100%; font:inherit; font-size:16px; margin-top:6px; padding:6px; border-radius:6px;
  border:1px solid var(--line); background:var(--bg); color:var(--fg); }
.warn { color:var(--ess); font-size:13px; }
.card.row { padding:8px 12px; margin:6px 0; } .card.row .actions { margin-top:6px; }
#stats { margin-top:40px; border-top:1px solid var(--line); padding-top:6px; }
#stats ul { padding-left:18px; margin:6px 0 14px; } #stats li { margin:3px 0; }
table { border-collapse:collapse; font-size:14px; width:100%; }
th, td { text-align:left; padding:5px 8px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:500; font-size:12px; } th:not(:first-child) { text-align:right; } td.n { text-align:right; font-variant-numeric:tabular-nums; }
</style>
</head>
<body>
<main>
<header id="top"></header>
<div class="bar">
  <select id="filter"><option value="">All kinds</option></select>
  <button id="acceptEss">Accept all fixes</button>
  <button class="primary" id="export">Export decisions</button>
  <span class="small" id="count"></span>
  <span class="small" id="saved"></span>
</div>
<div id="list"></div>
<section id="stats"></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const KEY = 'ccp-decisions-' + D.meta.episode_id;
let dec = {};
try { dec = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
const SERVED = location.protocol.startsWith('http');
const save = () => {
  try { localStorage.setItem(KEY, JSON.stringify(dec)); } catch (e) {}
  updateCount();
  if (SERVED) { clearTimeout(saveTimer); document.getElementById('saved').textContent = 'saving…'; saveTimer = setTimeout(push, 600); }
};
const esc = s => (s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const m = D.meta;
const CAT = { mishearing:'misheard', standard:'convention', particle:'particle', punctuation:'punctuation',
  name:'name', missing:'missing word', extra:'extra word', segmentation:'line split', timing:'timing', other:'other' };
const GRADE = { fix:'fix', suggest:'suggestion', query:'question', keep:'kept' };
const SRC = { dict:'Dictionary', corpus:'Standard subtitles', sounds_like:'Sounds like', ctc:'Audio check',
  lint:'Conventions', context:'Context', glossary:'Glossary', reference:'Reference' };
const tag = (text, tip, cls) => `<span class="tag ${cls || ''}" data-tip="${esc(tip)}">${text}</span>`;
const TAGS = {
  ref: tag('REF', 'Reference subtitle', 'ref'), ft: tag('CC', 'CantoCaptions recogniser'),
  qw: tag('Qw', 'Qwen recogniser'), listen: tag('↻', 'Listened again'),
  prev: tag('← prev', 'Previous line'), next: tag('next →', 'Next line') };

// ---- header: what this is, how much there is, what it was checked against, what to do
const fileName = p => (p || '').split(/[\\/]/).pop();
const isCleanup = i => i.cleanup && i.status === 'applied';
const nOf = g => D.items.filter(i => !isCleanup(i) && i.grade === g).length;
const S = { fix: nOf('fix'), suggest: nOf('suggest'), query: nOf('query'), keep: nOf('keep') };
const nCleanup = D.items.filter(isCleanup).length;
const chip = (n, what) => n ? `<span class="chip"><b>${n}</b> ${what}</span>` : '';
const ref = m.reference;
document.getElementById('top').innerHTML = `
  <div class="eyebrow">Proofreading report</div>
  <h1>${esc(m.title)}</h1>
  <div class="chips">${chip(S.fix, 'fixes')}${chip(S.suggest, 'suggestions')}${chip(S.query, 'questions')}${chip(nCleanup, 'cleanup edits')}${chip(S.keep, 'checked and kept')}${D.items.length ? '' : '<span class="chip">nothing to review</span>'}</div>
  <dl class="facts">
    <dt>Reference</dt><dd>${ref ? esc(ref.text) + (ref.timing ? ` · ${esc(ref.timing)}` : '') : 'none: lines were judged from the conversation alone'}</dd>
    <dt>Audio</dt><dd>${m.audio_checked ? 'checked line by line' : (m.machine_draft ? 'not checked (a text-only cleanup)' : 'not checked')}${m.media ? ' · each card has a clip' : ' · no clips (no media)'}</dd>
    <dt>Subtitles</dt><dd>${esc(fileName(m.source_srt || m.srt))}</dd>
  </dl>
  <div class="howto" id="howto">Play the clip, then <b>Accept</b> or <b>Reject</b> each card (edit the text first if you like).
    When you are done, press <b>Export decisions</b> and give <code>decisions.json</code> to the agent.</div>
  <details class="files"><summary>Files</summary>Working subtitles: ${esc(m.srt)}${m.source_srt && m.source_srt !== m.srt ? `<br>Original: ${esc(m.source_srt)}` : ''}<br>Media: ${esc(m.media || '—')}${ref ? `<br>Reference: ${esc(ref.file)}` : ''}</details>`;

const cats = [...new Set(D.items.map(i => i.category))];
const sel = document.getElementById('filter');
cats.forEach(c => sel.insertAdjacentHTML('beforeend', `<option value="${c}">${CAT[c] || c}</option>`));
const groups = [['fix','Fixes'],['suggest','Suggestions (you decide)'],['query','Questions (no confident fix)'],
  ['cleanup','Cleanup pass (text only, already applied)'],['keep','Checked and kept']];
const inGroup = (i, g) => g === 'cleanup' ? (i.cleanup && i.status === 'applied') : (i.grade === g && !(i.cleanup && i.status === 'applied'));
const reason = it => it.reason ? `<div class="reason"><b>Reason:</b> ${esc(it.reason)}</div>` : '';
const player = it => it.clip ? (D.meta.video ? `<video controls preload="none" src="${it.clip}"></video>` : `<audio controls preload="none" src="${it.clip}"></audio>`) : '';
// Who pointed the line out: the tool signals it carried, or the agent alone.
const found = it => `<span class="found">` + (it.found_by.length
  ? it.found_by.map(k => `<span class="by tool" data-tip="${esc(m.kinds[k].tip)}">${esc(m.kinds[k].label)}</span>`).join('')
  : `<span class="by agent" data-tip="No tool pointed this line out">Agent</span>`) + '</span>';
const head = (it, extra) => `<div class="head"><span class="where">Line ${it.cue}</span> ${it.time} ${extra || ''}${found(it)}</div>`;
// Draft and proposal in one grid, so the two texts start at the same point and (with the
// padded diff cells) line up character for character.
const pair = (l1, t1, l2, t2) => `<div class="pair"><span class="label">${l1}</span><span class="line">${t1}</span>` +
  (t2 != null ? `<span class="label">${l2}</span><span class="line">${t2}</span>` : '') + '</div>';
// The supporting lines, each behind its tag: the reference (and what the agent cited from it
// when that differs), what the recognisers heard, re-listening, and the neighbouring lines.
function linesBlock(it, withContext) {
  const rows = [];
  it.reference.forEach(r => rows.push(TAGS.ref + `<span class="t">${esc(r)}</span>`));
  const cited = it.evidence.filter(e => e.source === 'reference' && !it.reference.includes(e.detail));
  if (!it.reference.length && cited.length) rows.push(TAGS.ref + '<span class="t dim">(none placed on this line)</span>');
  cited.forEach(e => rows.push(`<span class="note">${esc(e.detail)}</span>`));
  Object.entries(it.asr).forEach(([k, v]) => rows.push((TAGS[k] || tag(esc(k), 'Speech recogniser')) + `<span class="t dim">${esc(v) || '(nothing heard)'}</span>`));
  it.evidence.filter(e => e.source === 'listen').forEach(e => rows.push(TAGS.listen + `<span class="t dim">${esc(e.detail)}</span>`));
  if (withContext) {
    if (it.prev != null) rows.push(TAGS.prev + `<span class="t dim">${esc(it.prev)}</span>`);
    if (it.next != null) rows.push(TAGS.next + `<span class="t dim">${esc(it.next)}</span>`);
  }
  return rows.length ? `<div class="lines">${rows.join('')}</div>` : '';
}
// The remaining evidence, under plain names.
const SHOWN = ['reference', 'asr_ft', 'asr_qwen', 'listen'];
const otherEv = it => it.evidence.filter(e => !SHOWN.includes(e.source));
const evList = it => { const ev = otherEv(it); return ev.length ? '<ul class="ev">' + ev.map(e =>
  `<li><span class="src">${esc(SRC[e.source] || e.source)}</span>${esc(e.detail)}</li>`).join('') + '</ul>' : ''; };
function keepRow(it) {
  const d = dec[it.id] || {};
  const text = d.text !== undefined ? d.text : it.draft;
  return `<div class="card row ${d.decision || ''}" data-id="${it.id}" data-cat="${it.category}">
    ${head(it, '<span class="badge keep">kept</span>')}
    ${pair('line', it.draft_html)}
    ${reason(it)}
    ${linesBlock(it, false)}
    ${player(it)}
    <div class="actions">
      <button data-act="accept">${d.decision === 'accepted' ? '✓ Correct to my text' : 'Correct to my text'}</button>
      <button data-act="clear">Leave it</button>
      <textarea rows="1" style="flex:1;min-width:200px;margin:0">${esc(text).replace(/\n/g,'⏎')}</textarea>
    </div>
  </div>`;
}
function row(it) {
  const d = dec[it.id] || {};
  const ev = otherEv(it).map(e => esc(e.source === 'context' ? e.detail : `${SRC[e.source] || e.source}: ${e.detail}`)).join(' · ');
  const text = d.text !== undefined ? d.text : (it.applied_text || it.proposed || '');
  return `<div class="card row ${d.decision || ''}" data-id="${it.id}" data-cat="${it.category}">
    ${head(it, `<span class="badge">${CAT[it.category] || it.category}</span>` + (it.stale ? '<span class="warn">changed since</span>' : ''))}
    ${pair('was', it.draft_html, 'now', it.proposed_html)}
    ${reason(it)}
    ${linesBlock(it, false)}
    ${ev ? `<div class="small">${ev}</div>` : ''}
    ${player(it)}
    <div class="actions">
      <button data-act="reject">${d.decision === 'rejected' ? '✗ Undone' : 'Undo'}</button>
      <button data-act="accept">${d.decision === 'accepted' ? '✓ Use my text' : 'Use my text'}</button>
      <button data-act="clear">Keep</button>
      <textarea rows="1" style="flex:1;min-width:200px;margin:0">${esc(text).replace(/\n/g,'⏎')}</textarea>
    </div>
  </div>`;
}
function card(it) {
  if (it.cleanup && it.status === 'applied') return row(it);
  if (it.grade === 'keep') return keepRow(it);
  const d = dec[it.id] || {};
  const media = it.clip ? player(it) : '<div class="small">no clip</div>';
  const structural = it.proposed_cues.length > 0;
  const texts = structural || it.proposed === null ? pair('draft', it.draft_html)
    : pair('draft', it.draft_html, 'proposed', it.proposed_html);
  const prop = structural
    ? `<div class="small"><span class="label">now</span>${it.current_at}</div>` +
      `<div class="text"><span class="label">${it.proposed_cues.length > 1 ? 'split into' : 'retime to'}</span></div>` +
      it.proposed_cues.map(c => `<div class="text" style="font-size:16px"><span class="label">${c.at}</span>${esc(c.text).replace(/\n/g,'<br>')}</div>`).join('')
    : '';
  const alts = it.alternatives.length ? `<div class="small"><span class="label">could be</span>${it.alternatives.map(esc).join(' · ')}</div>` : '';
  const text = d.text !== undefined ? d.text : (it.applied_text || it.proposed || it.alternatives[0] || '');
  return `<div class="card ${d.decision || ''}" data-id="${it.id}" data-cat="${it.category}">
    ${head(it, `<span class="badge ${it.grade}">${GRADE[it.grade]}</span><span class="badge">${CAT[it.category] || it.category}</span>` +
      (it.status === 'applied' ? '<span class="badge">already applied</span>' : ''))}
    ${it.stale ? '<div class="warn">The line has changed since this card was made.</div>' : ''}
    ${it.status === 'applied' && !structural ? '<div class="small">Already applied to the subtitles: Reject undoes it, Accept with edited text replaces it.</div>' : ''}
    ${texts}${prop}${alts}
    ${reason(it)}
    ${linesBlock(it, true)}
    ${evList(it)}${media}
    <div class="actions">
      <button data-act="accept">${d.decision === 'accepted' ? '✓ Accepted' : 'Accept'}</button>
      <button data-act="reject">${d.decision === 'rejected' ? '✗ Rejected' : 'Reject'}</button>
      <button data-act="clear">Undecided</button>
    </div>
    ${structural ? '<div class="small">Timing change: accept or reject as proposed.</div>'
      : `<textarea rows="1" placeholder="Edit the text to apply (⏎ = line break)">${esc(text).replace(/\n/g,'⏎')}</textarea>`}
  </div>`;
}
// The "Checked and kept" section stays open or closed across re-renders (each button press
// re-renders the list).
let keptOpen = false;
function render() {
  const f = sel.value, list = document.getElementById('list');
  list.innerHTML = groups.map(([g, title]) => {
    const its = D.items.filter(i => inGroup(i, g) && (!f || i.category === f));
    if (!its.length) return '';
    if (g === 'keep') return `<details class="kept"${keptOpen ? ' open' : ''}><summary>${title} (${its.length})</summary>` + its.map(card).join('') + '</details>';
    return `<h2>${title} (${its.length})</h2>` + its.map(card).join('');
  }).join('') || '<p>Nothing to review.</p>';
  updateCount();
}
document.getElementById('list').addEventListener('toggle', e => {
  if (e.target.matches && e.target.matches('details.kept')) keptOpen = e.target.open;
}, true);
function updateCount() {
  const v = Object.values(dec);
  document.getElementById('count').textContent =
    `${v.filter(x => x.decision === 'accepted').length} accepted · ${v.filter(x => x.decision === 'rejected').length} rejected · ${D.items.length} cards`;
}

// ---- the statistics: how the lines in this report were found
function statsSection() {
  const s = m.stats; if (!s) return '';
  const th = s.tool_hints;
  const rows = Object.entries(th.by_kind).filter(([, v]) => v.shown).map(([k, v]) =>
    `<tr><td>${tag(esc(m.kinds[k].label), m.kinds[k].tip)}</td><td class="n">${v.shown}</td><td class="n">${v.in_report}</td>` +
    `<td class="n">${v.changed}</td><td class="n">${v.kept}</td><td class="n">${v.shown - v.in_report}</td></tr>`).join('');
  const alone = s.found_by_agent_alone;
  return `<h2>About this proofread</h2><ul>${s.summary.map(l => `<li>${esc(l)}</li>`).join('')}</ul>` +
    (rows ? `<table><thead><tr><th>What the tools pointed out</th><th>lines</th><th>in the report</th><th>changed</th>` +
      `<th>checked and kept</th><th>left alone</th></tr></thead><tbody>${rows}` +
      `<tr><td>${tag('Agent', 'Lines no tool pointed out')} found on its own</td><td class="n">${alone.records}</td>` +
      `<td class="n">${alone.records}</td><td class="n">${alone.changes}</td><td class="n">–</td><td class="n">–</td></tr>` +
      `</tbody></table><p class="small">A line can carry more than one hint, so the rows can add up to more than the lines.</p>` : '');
}
document.getElementById('stats').innerHTML = statsSection();

document.getElementById('list').addEventListener('click', e => {
  const b = e.target.closest('button[data-act]'); if (!b) return;
  const c = b.closest('.card'), id = c.dataset.id, ta = c.querySelector('textarea');
  if (b.dataset.act === 'clear') delete dec[id];
  else dec[id] = { decision: b.dataset.act === 'accept' ? 'accepted' : 'rejected',
                   text: ta ? ta.value.replace(/⏎/g, '\n') : undefined };
  save(); render();
});
document.getElementById('list').addEventListener('input', e => {
  if (e.target.tagName !== 'TEXTAREA') return;
  const id = e.target.closest('.card').dataset.id;
  dec[id] = Object.assign(dec[id] || {}, { text: e.target.value.replace(/⏎/g, '\n') }); save();
});
sel.addEventListener('change', render);
document.getElementById('acceptEss').addEventListener('click', () => {
  D.items.filter(i => i.grade === 'fix' && i.proposed !== null && i.status !== 'applied' && !dec[i.id])
    .forEach(i => dec[i.id] = { decision: 'accepted', text: i.proposed });
  save(); render();
});
const payload = () => ({ episode_id: D.meta.episode_id, decisions: Object.entries(dec)
  .filter(([, d]) => d.decision).map(([id, d]) => ({ flag: +id, decision: d.decision, text: d.text })) });
const download = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload(), null, 2)], { type: 'application/json' }));
  a.download = 'decisions.json'; a.click();
};
// Opened from the report server (`ccp report`), decisions save straight into the workspace as
// you go, and "Done reviewing" saves them once more. Opened as a file, the page downloads
// decisions.json for you to hand over, as before.
const savedEl = document.getElementById('saved');
const exportBtn = document.getElementById('export');
let saveTimer = null;
async function push() {
  try {
    const r = await fetch('decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                         body: JSON.stringify(payload()) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.status);
    savedEl.textContent = `✓ ${j.saved} decision${j.saved === 1 ? '' : 's'} saved for the agent at ${j.at}`;
    return true;
  } catch (e) {
    savedEl.textContent = '⚠ not saved: the report server has stopped. Use Download, or ask the agent to reopen the report.';
    return false;
  }
}
if (SERVED) {
  exportBtn.textContent = 'Done reviewing';
  exportBtn.insertAdjacentHTML('afterend', '<button id="download" title="Save a copy of decisions.json">Download</button>');
  document.getElementById('download').addEventListener('click', download);
  document.getElementById('howto').innerHTML = 'Play the clip, then <b>Accept</b> or <b>Reject</b> each card (edit the ' +
    'text first if you like). Your choices are saved for the agent as you go. When you are done, press ' +
    '<b>Done reviewing</b> and tell the agent.';
  exportBtn.addEventListener('click', async () => {
    clearTimeout(saveTimer);
    if (await push()) savedEl.textContent += '. All done: tell the agent you have finished reviewing.';
  });
  // Decisions saved earlier (in another browser, say) come back when this one has none.
  if (!Object.keys(dec).length) fetch('decisions').then(r => r.json()).then(saved => {
    (saved.decisions || []).forEach(d => dec[d.flag] = { decision: d.decision, text: d.text });
    if (Object.keys(dec).length) { try { localStorage.setItem(KEY, JSON.stringify(dec)); } catch (e) {} render(); }
  }).catch(() => {});
} else {
  exportBtn.addEventListener('click', download);
}
render();
</script>
</body>
</html>
"""
