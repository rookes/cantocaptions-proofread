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
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import episode, flags as flagstore
from .render import _ref_placement
from .srtio import short_time

CLIP_PAD = 1.0
CLIP_STATUS: dict = {}       # filled by build(): clips made / failed, for the command's output
SEVERITY_ORDER = {"essential": 0, "suggested": 1, "query": 2}


def _clip(media: str, track: int, start: float, end: float, out: Path, video: bool) -> str | None:
    """Cut one clip; None on success, else the error."""
    if out.exists() and out.stat().st_size > 0:
        return None
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", media]
    if video:
        cmd += ["-map", "0:v:0", "-map", f"0:a:{track}", "-vf", "scale=-2:480", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                "-movflags", "+faststart", str(out)]
    else:
        cmd += ["-map", f"0:a:{track}", "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "96k", str(out)]
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
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    left, right = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = html.escape(a[i1:i2]), html.escape(b[j1:j2])
        if op == "equal":
            left.append(x)
            right.append(y)
        else:
            if x:
                left.append(f"<del>{x}</del>")
            if y:
                right.append(f"<ins>{y}</ins>")
    fix = lambda s: s.replace("\n", "<br>")
    return fix("".join(left)), fix("".join(right))


def build(episode_id: str, video: bool = False, include_rejected: bool = False) -> Path:
    ep = episode.load(episode_id)
    srt = episode.srt(ep)
    flags = [f for f in flagstore.load(episode_id) if include_rejected or f["status"] != "rejected"]
    flags.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["cue"]))
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
        def cut(f):
            cue = srt.cue(f["cue"])
            name = f"flag_{f['id']}.{'mp4' if video else 'm4a'}"
            err = _clip(ep["media"], ep.get("audio_track", 0), max(0.0, cue.start - CLIP_PAD),
                        cue.end + CLIP_PAD, clips / name, video)
            return f["id"], (None if err else f"clips/{name}"), err
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
            done = list(pool.map(cut, flags))
        clip_of = {k: v for k, v, _ in done if v}
        errors = [e for _, _, e in done if e]
        CLIP_STATUS.update({"clips": len(clip_of), "failed": len(errors)},
                           **({"first_error": errors[0]} if errors else {}))
    else:
        CLIP_STATUS.update({"clips": 0, "note": "no media linked: the report has no audio"})
    items = []
    for f in flags:
        cue = srt.cue(f["cue"])
        clip_rel = clip_of.get(f["id"])
        cleanup = f.get("pass") == "cleanup"
        current = cue.text
        left, right = _diff_html(f["draft"], f["proposed"]) if f.get("proposed") is not None else (html.escape(f["draft"]).replace("\n", "<br>"), "")
        ctx = []
        for p in range(max(1, f["cue"] - 1), min(len(srt.cues), f["cue"] + 1) + 1):
            if p != f["cue"]:
                ctx.append({"pos": p, "text": srt.cue(p).text})
        ev = evidence.get(f["cue"], {})
        asr = {k: (v.get("edge_before", "") and f"[{v['edge_before']}]") + v.get("text", "")
               + (v.get("edge_after", "") and f"[{v['edge_after']}]") for k, v in ev.get("asr", {}).items()}
        items.append({
            "id": f["id"], "cue": f["cue"], "time": short_time(f["start"]),
            "severity": f["severity"], "category": f["category"], "confidence": f["confidence"],
            "status": f["status"], "draft_html": left, "proposed_html": right,
            "proposed": f.get("proposed"), "alternatives": f.get("alternatives", []),
            "current_at": f"{short_time(cue.start)}–{short_time(cue.end)}",
            "proposed_cues": [{"at": f"{short_time(c['start'])}–{short_time(c['end'])}", "text": c["text"]}
                              for c in f.get("proposed_cues") or []],
            "stale": current != (f.get("applied_text") if f["status"] == "applied"
                                 and isinstance(f.get("applied_text"), str) else f["draft"])
                     and not (f["status"] == "applied" and f.get("proposed_cues")),
            "applied_text": f.get("applied_text") if isinstance(f.get("applied_text"), str) else None,
            "evidence": f["evidence"], "note": f.get("note", ""),
            "reference": refs.get(f["cue"], []), "asr": asr, "context": ctx, "clip": clip_rel,
            "cleanup": cleanup,
        })
    ref_meta = episode.path(episode_id, "reference.json")
    meta = {
        "episode_id": episode_id, "srt": ep["srt"], "media": ep.get("media"),
        "reference": json.loads(ref_meta.read_text(encoding="utf-8")).get("source") if ref_meta.exists() else None,
        "summary": flagstore.summary(flags), "video": video,
    }
    page = TEMPLATE.replace("__TITLE__", html.escape(Path(ep["srt"]).stem)).replace(
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
:root { --bg:#fafaf8; --fg:#1d1d1b; --muted:#6b6b66; --card:#ffffff; --line:#e3e2dc;
  --del:#fde2e1; --del-fg:#9b1c1c; --ins:#dcf3e1; --ins-fg:#14532d; --accent:#2f5d8a;
  --ess:#b42318; --sug:#b26b00; --qry:#5b5b8f; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe6; --muted:#9a9993;
  --card:#1f1f1d; --line:#33322f; --del:#3d1f1f; --del-fg:#f4a3a3; --ins:#1d3324; --ins-fg:#9fdcae;
  --accent:#8db8e6; --ess:#f08a80; --sug:#f0b860; --qry:#a9a9e0; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 system-ui, "Segoe UI", "Microsoft JhengHei", "PingFang HK", "Noto Sans HK", sans-serif; }
main { max-width:920px; margin:0 auto; padding:24px 16px 80px; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:16px; margin:32px 0 10px; }
.meta { color:var(--muted); font-size:13px; word-break:break-all; }
.bar { position:sticky; top:0; background:var(--bg); padding:10px 0; display:flex; gap:8px;
  flex-wrap:wrap; align-items:center; border-bottom:1px solid var(--line); z-index:2; }
button, select { font:inherit; font-size:13px; padding:5px 10px; border-radius:6px;
  border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }
button.primary { background:var(--accent); color:var(--bg); border-color:var(--accent); }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:10px 0; }
.card.accepted { border-left:4px solid var(--ins-fg); } .card.rejected { opacity:.55; }
.head { display:flex; gap:8px; flex-wrap:wrap; align-items:baseline; font-size:13px; color:var(--muted); }
.badge { font-size:12px; padding:1px 7px; border-radius:99px; border:1px solid currentColor; }
.essential { color:var(--ess); } .suggested { color:var(--sug); } .query { color:var(--qry); }
.text { font-size:19px; margin:8px 0 2px; } .label { color:var(--muted); font-size:12px; margin-right:6px; }
del { background:var(--del); color:var(--del-fg); text-decoration:line-through; }
ins { background:var(--ins); color:var(--ins-fg); text-decoration:none; }
.ev { font-size:13px; margin:8px 0 0; padding-left:18px; } .ev li { margin:2px 0; }
.small { font-size:13px; color:var(--muted); } audio, video { width:100%; max-width:480px; margin-top:8px; }
.actions { display:flex; gap:6px; margin-top:10px; flex-wrap:wrap; align-items:center; }
textarea { width:100%; font:inherit; font-size:16px; margin-top:6px; padding:6px; border-radius:6px;
  border:1px solid var(--line); background:var(--bg); color:var(--fg); }
.warn { color:var(--ess); font-size:13px; }
.card.row { padding:8px 12px; margin:6px 0; } .card.row .actions { margin-top:6px; }
</style>
</head>
<body>
<main>
<h1>Proofread: __TITLE__</h1>
<div class="meta" id="meta"></div>
<div class="bar">
  <select id="filter"><option value="">All categories</option></select>
  <button id="acceptEss">Accept all essential</button>
  <button class="primary" id="export">Export decisions</button>
  <span class="small" id="count"></span>
</div>
<div id="list"></div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const KEY = 'ccp-decisions-' + D.meta.episode_id;
let dec = {};
try { dec = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(dec)); } catch (e) {} updateCount(); };
const esc = s => (s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const m = D.meta;
document.getElementById('meta').innerHTML =
  `${esc(m.srt)}<br>media: ${esc(m.media || '—')}<br>reference: ${esc(m.reference || 'none')}<br>` +
  `${m.summary.total} flags · apply with <code>uv run ccp apply ${esc(m.episode_id)} --decisions &lt;decisions.json&gt;</code>`;
const cats = [...new Set(D.items.map(i => i.category))];
const sel = document.getElementById('filter');
cats.forEach(c => sel.insertAdjacentHTML('beforeend', `<option>${c}</option>`));
const groups = [['essential','Essential corrections'],['suggested','Suggested'],['query','Queries (no confident fix)'],
  ['cleanup','Cleanup pass (text only, already applied)']];
const inGroup = (i, g) => g === 'cleanup' ? (i.cleanup && i.status === 'applied') : (i.severity === g && !(i.cleanup && i.status === 'applied'));
function row(it) {
  const d = dec[it.id] || {};
  const ev = it.evidence.map(e => esc(e.source === 'context' ? e.detail : `${e.source}: ${e.detail}`)).join(' · ');
  const text = d.text !== undefined ? d.text : (it.applied_text || it.proposed || '');
  return `<div class="card row ${d.decision || ''}" data-id="${it.id}" data-cat="${it.category}">
    <div class="head"><b>#${it.id}</b> cue ${it.cue} · ${it.time} <span class="badge">${it.category}</span>
      ${it.stale ? '<span class="warn">changed since</span>' : ''}</div>
    <div><span class="label">was</span>${it.draft_html}</div>
    <div><span class="label">now</span>${it.proposed_html}</div>
    ${ev ? `<div class="small">${ev}</div>` : ''}
    ${it.clip ? (D.meta.video ? `<video controls preload="none" src="${it.clip}"></video>` : `<audio controls preload="none" src="${it.clip}"></audio>`) : ''}
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
  const d = dec[it.id] || {};
  const media = it.clip ? (D.meta.video ? `<video controls preload="none" src="${it.clip}"></video>` : `<audio controls preload="none" src="${it.clip}"></audio>`) : '<div class="small">no clip</div>';
  const ev = it.evidence.map(e => `<li><b>${esc(e.source)}</b>: ${esc(e.detail)}</li>`).join('');
  const asr = Object.entries(it.asr).map(([k,v]) => `<div class="small"><span class="label">ASR ${k}</span>${esc(v)}</div>`).join('');
  const ref = it.reference.map(r => `<div class="small"><span class="label">Reference</span>${esc(r)}</div>`).join('');
  const ctx = it.context.map(c => `<div class="small"><span class="label">cue ${c.pos}</span>${esc(c.text)}</div>`).join('');
  const structural = it.proposed_cues.length > 0;
  const prop = structural
    ? `<div class="small"><span class="label">now</span>${it.current_at}</div>` +
      `<div class="text"><span class="label">${it.proposed_cues.length > 1 ? 'split into' : 'retime to'}</span></div>` +
      it.proposed_cues.map(c => `<div class="text" style="font-size:16px"><span class="label">${c.at}</span>${esc(c.text).replace(/\n/g,'<br>')}</div>`).join('')
    : (it.proposed !== null ? `<div class="text"><span class="label">proposed</span>${it.proposed_html}</div>` : '');
  const alts = it.alternatives.length ? `<div class="small"><span class="label">alternatives</span>${it.alternatives.map(esc).join(' · ')}</div>` : '';
  const text = d.text !== undefined ? d.text : (it.applied_text || it.proposed || '');
  return `<div class="card ${d.decision || ''}" data-id="${it.id}" data-cat="${it.category}">
    <div class="head"><b>#${it.id}</b> cue ${it.cue} · ${it.time}
      <span class="badge ${it.severity}">${it.severity}</span><span class="badge">${it.category}</span>
      <span class="badge">${it.confidence}</span>${it.status !== 'open' ? `<span class="badge">${it.status}</span>` : ''}</div>
    ${it.stale ? '<div class="warn">The cue text has changed since this flag was made.</div>' : ''}
    ${it.status === 'applied' && !structural ? '<div class="small">Already applied to the subtitles: Reject undoes it, Accept with edited text replaces it.</div>' : ''}
    <div class="text"><span class="label">draft</span>${it.draft_html}</div>${prop}${alts}
    ${ref}${asr}${ctx}
    ${it.note ? `<div class="small" style="margin-top:6px">${esc(it.note)}</div>` : ''}
    <ul class="ev">${ev}</ul>${media}
    <div class="actions">
      <button data-act="accept">${d.decision === 'accepted' ? '✓ Accepted' : 'Accept'}</button>
      <button data-act="reject">${d.decision === 'rejected' ? '✗ Rejected' : 'Reject'}</button>
      <button data-act="clear">Undecided</button>
    </div>
    ${structural ? '<div class="small">Timing change: accept or reject as proposed.</div>'
      : `<textarea rows="1" placeholder="Edit the text to apply (⏎ = line break)">${esc(text).replace(/\n/g,'⏎')}</textarea>`}
  </div>`;
}
function render() {
  const f = sel.value, list = document.getElementById('list');
  list.innerHTML = groups.map(([sev, title]) => {
    const its = D.items.filter(i => inGroup(i, sev) && (!f || i.category === f));
    return its.length ? `<h2>${title} (${its.length})</h2>` + its.map(card).join('') : '';
  }).join('') || '<p>No flags.</p>';
  updateCount();
}
function updateCount() {
  const v = Object.values(dec);
  document.getElementById('count').textContent =
    `${v.filter(x => x.decision === 'accepted').length} accepted · ${v.filter(x => x.decision === 'rejected').length} rejected · ${D.items.length} flags`;
}
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
  D.items.filter(i => i.severity === 'essential' && i.proposed !== null && !dec[i.id])
    .forEach(i => dec[i.id] = { decision: 'accepted', text: i.proposed });
  save(); render();
});
document.getElementById('export').addEventListener('click', () => {
  const out = { episode_id: D.meta.episode_id, decisions: Object.entries(dec)
    .filter(([, d]) => d.decision).map(([id, d]) => ({ flag: +id, decision: d.decision, text: d.text })) };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' }));
  a.download = 'decisions.json'; a.click();
});
render();
</script>
</body>
</html>
"""
