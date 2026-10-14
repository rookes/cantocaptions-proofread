"""`ccp`: the proofreading agent's tool belt. Run `uv run ccp <command> -h` for details."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _out(obj) -> None:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader stopped early (e.g. `| Select-Object -First 5`): not an error.
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0)


# ---------------------------------------------------------------------------- workspace

def cmd_locate(a):
    from . import episode, locate
    if a.media and not a.srt and not a.select and not a.request:
        if not a.id:
            raise SystemExit("a media-only workspace needs --id NAME")
        return _out(episode.create_media_only(a.media, a.id, a.audio_track))
    if a.srt:
        rec = locate.record_for_srt(a.srt)
        if a.id:
            rec = {**rec, "episode_id": a.id}
        return _out(episode.create(rec, a.audio_track, a.media))
    if a.select:
        rec = locate.by_id(a.select)
        if rec is None:
            raise SystemExit(f"no manifest record {a.select!r}")
        return _out(episode.create(rec, a.audio_track, a.media))
    if not a.request:
        raise SystemExit("give a request (e.g. 'AoT S1E03'), --select EPISODE_ID, --srt PATH or --media PATH --id NAME")
    res = locate.find(" ".join(a.request))
    if len(res["candidates"]) == 1 and not a.no_create:
        rec = locate.by_id(res["candidates"][0]["episode_id"])
        res["workspace"] = episode.create(rec, a.audio_track, a.media)
    elif len(res["candidates"]) > 1:
        res["next"] = "several matches: pick one with `ccp locate --select <episode_id>` (ask the user if unclear)"
    _out(res)


def cmd_status(a):
    from . import episode, flags
    from .prune import reclaimable_mb
    ep = episode.load(a.id)
    w = episode.path(a.id, "x").parent
    ref = w / "reference.json"
    rows = flags.load(a.id)
    machine = episode.machine_draft(ep)
    done = ep.get("cleanup")
    _out({
        "episode": ep, "workspace": str(w),
        "machine_draft": machine,
        **({"cleanup": (f"done: {done['edits']} edits applied, {done['queries']} queries ({done['at']})" if done else
                        "not cleaned yet: start with the text-only cleanup pass (skill clean-draft), no evidence needed")}
           if machine or done else {}),
        "reference": json.loads(ref.read_text(encoding="utf-8")) if ref.exists() else None,
        "evidence": (w / "evidence.jsonl").exists(),
        "emissions": (w / "emissions" / "tokens.json").exists(),
        "flags": flags.summary(rows), "report": (w / "report.html").exists(),
        "prunable_mb": reclaimable_mb(a.id),
        **({"pruned": ep["pruned"]} if ep.get("pruned") else {}),
    })


def cmd_reference(a):
    from . import reference
    _out(reference.prepare(a.id, a.file, a.stream, a.ocr))


def cmd_evidence(a):
    from . import episode, gpu_bridge
    ep = episode.load(a.id)
    if not ep.get("media_exists"):
        raise SystemExit("no media linked to this workspace")
    if not ep.get("srt"):
        raise SystemExit("no draft yet: run `ccp pipeline <id> transcribe` first")
    models = a.models
    if models is None:
        # A transcribed draft was written by the fine-tuned model: re-running it only vouches
        # for its own output, so only the independent recogniser is run.
        machine = episode.machine_draft(ep)
        models = "qw" if machine else "ft,qw"
        if machine:
            print("  [evidence] machine-made draft (ASR or AI-generated subtitles): using only the "
                  "independent recogniser (stock Qwen3-ASR); pass --models ft,qw for both", file=sys.stderr)
    out = episode.path(a.id, "evidence.jsonl")
    if out.exists() and not a.force:
        return _out({"status": "exists", "path": str(out), "hint": "pass --force to recompute"})
    res = gpu_bridge.run("evidence", {
        "episode_id": a.id, "srt": ep["srt"], "media": ep["media"],
        "audio_track": ep.get("audio_track", 0), "models": models.split(","),
        "gap": a.gap, "max_len": a.max_len, "pad": a.pad, "diarize": a.diarize,
        "out_dir": str(out.parent)})
    _out(res)


def cmd_render(a):
    from .render import render
    _out(render(a.id, a.start, a.end, a.groups, not a.no_times))


MAX_CUES = 20


def _cue_numbers(items: list[str]) -> list[int]:
    """`9 11 24`, `230-235` or `230,231`: cue numbers, at most MAX_CUES of them."""
    out: list[int] = []
    for it in items:
        for part in str(it).replace("..", "-").split(","):
            lo, sep, hi = part.strip().strip("()").partition("-")
            if not lo.isdigit() or (sep and not hi.isdigit()):
                raise SystemExit(f"not a cue number or range: {part!r} (use 9 11 24 or 230-235)")
            out += list(range(int(lo), int(hi) + 1)) if sep else [int(lo)]
    if len(out) > MAX_CUES:
        raise SystemExit(f"{len(out)} cues asked for: `ccp cue` is for suspects, at most {MAX_CUES} per call. "
                         "Read a window with `ccp render <id> --from N --to M`, then ask `cue` only for "
                         "the cues you are unsure of.")
    return out


def cmd_cue(a):
    """Everything known about one or more cues. Compact text by default (one block per cue,
    so many suspects fit in one call); --json for the full structure."""
    from . import episode, flags as fl
    from .render import _ref_placement
    a.cue = _cue_numbers(a.cue)
    ep = episode.load(a.id)
    srt = episode.srt(ep)
    evidence = {e["cue"]: e for e in episode.read_jsonl(a.id, "evidence.jsonl")}
    placed = _ref_placement(srt.cues, episode.reference_cues(a.id))
    from . import lint
    lint_rows = lint.lint_file(Path(ep["srt"]), ep.get("show_slug")) + episode.read_jsonl(a.id, "timing.jsonl")
    flag_rows = fl.load(a.id)
    out = [_cue_detail(a, srt, srt.cue(n), evidence, placed, lint_rows, flag_rows) for n in a.cue]
    if a.json:
        return _out(out[0] if len(out) == 1 else out)
    _out(chr(10).join(_cue_text(d) + chr(10) for d in out).rstrip())


def _cue_detail(a, srt, c, evidence, placed, lint_rows, flag_rows) -> dict:
    from . import jyutping
    from .render import content_key
    ev = evidence.get(c.pos, {})
    refs = placed.get(c.pos, [])
    hyps = {}
    for tag, h in ev.get("asr", {}).items():
        full = h.get("edge_before", "") + h.get("text", "") + h.get("edge_after", "")
        hyps[tag] = {**h, "jyutping": jyutping.romanize(full),
                     "same_content_as_draft": content_key(full, tag) == content_key(c.text, tag)}
    return {
        "cue": c.pos, "start": c.start, "end": c.end, "number": c.number,
        "text": c.text, "jyutping": jyutping.romanize(c.text, all_readings=True),
        "previous": [srt.cue(p).text for p in range(max(1, c.pos - a.context), c.pos)],
        "next": [srt.cue(p).text for p in range(c.pos + 1, min(len(srt.cues), c.pos + a.context) + 1)],
        "reference": refs, "asr": hyps,
        "peaks": "  ".join(f"{ch} {p:.2f}" for ch, p, fin in ev.get("peaks", [])),
        "weak": [(ch, p) for ch, p, fin in ev.get("peaks", []) if not fin and p < 0.3],
        "speaker": ev.get("speaker"),
        "lint": [r for r in lint_rows if r["cue"] == c.pos],
        "flags": [f for f in flag_rows if f["cue"] == c.pos],
    }


def _cue_text(d: dict) -> str:
    """One compact block per cue. ASR lines are marked = (same content as the draft) or ≠."""
    from .srtio import short_time, to_display
    jp_main = " ".join(x.split("|")[0] for x in d["jyutping"].split())
    poly = [f"{ch} {x.replace('|', '/')}" for ch, x in zip([c for c in d["text"] if _is_cjk(c)],
                                                            d["jyutping"].split()) if "|" in x]
    lines = [f"── cue {d['cue']}  @{short_time(d['start'])}–{short_time(d['end'])}"
             + (f"  speaker {d['speaker']}" if d.get("speaker") else ""),
             f"draft  {to_display(d['text'])}",
             f"       {jp_main}"]
    if poly:
        lines.append(f"       other readings: {'; '.join(poly[:8])}")
    # Meaning first (the reference and the conversation), then how it sounded (the recognisers).
    for r in d["reference"]:
        lines.append(f"R      {to_display(r)}")
    if d["previous"]:
        lines.append(f"prev   {' ｜ '.join(to_display(t) for t in d['previous'])}")
    if d["next"]:
        lines.append(f"next   {' ｜ '.join(to_display(t) for t in d['next'])}")
    differs = False
    for tag, h in d["asr"].items():
        text = ((f"[{h['edge_before']}]" if h.get("edge_before") else "") + h.get("text", "")
                + (f"[{h['edge_after']}]" if h.get("edge_after") else ""))
        if not text.strip():
            lines.append(f"{tag} ≠  (nothing heard)")
        elif h["same_content_as_draft"]:
            lines.append(f"{tag} =  {to_display(text)}")
        else:
            lines.append(f"{tag} ≠  {to_display(text)}   {h['jyutping']}")
            differs = True
    if differs and d["reference"]:
        lines.append("check  R sets the meaning; the recognisers only show how it sounded. Keep the draft if "
                     "their version means something R does not (they can share a mishearing).")
    if d["weak"]:
        content = [w for w in d["peaks"].split("  ") if w]
        if len(d["weak"]) >= max(4, len(content) - 1):
            lines.append(f"weak   {len(d['weak'])} of {len(content)} characters: the aligner hears almost none of "
                         "this cue (no speech, on-screen text, music or fast speech)")
        else:
            lines.append("weak   " + "  ".join(f"{ch} {p:.2f}" for ch, p in d["weak"]))
    for r in d["lint"]:
        if r["kind"] == "realign_suspect":
            lines.append(f"timing realign doubts this cue: {r['reason']}")
            continue
        lines.append(f"lint   {r['kind']} {to_display(r['found'])}" + (f"→{r['suggest']}" if r.get("suggest") else ""))
    for f in d["flags"]:
        prop = f" → {to_display(f['proposed'])}" if f.get("proposed") is not None else ""
        lines.append(f"flag   #{f['id']} {f['grade']}/{f['category']}/{f['status']}{prop}")
    return chr(10).join(lines)


def _is_cjk(ch: str) -> bool:
    from .jyutping import is_cjk
    return is_cjk(ch)


# ---------------------------------------------------------------------------- language

def cmd_sounds_like(a):
    from . import corpus, dictionary, sound
    vocab = None
    if a.source in ("corpus", "both") or a.show:
        cv = corpus.ngram_vocab(a.tier, a.show, a.min_count)
        vocab = cv if a.source == "corpus" else {**dictionary.term_readings(), **cv}
    matches = sound.search(a.text, a.hyp or [], n=a.n, min_len=a.min_len, max_len=a.max_len, vocab=vocab)
    rows = []
    for m in matches:
        senses = dictionary.lookup(m.term)
        gloss = next((s for s in senses if s.pos), None)
        row = {"term": m.term, "jyutping": m.jyutping, "score": m.score, "per_hyp": m.per_hyp,
               "replaced": m.replaced}
        if m.in_hyp:
            row["already_in_hyp"] = m.in_hyp
        if gloss:
            row["gloss"] = (f"[{','.join(gloss.labels)}] " if gloss.labels else "") + gloss.zh[:60] + " | " + gloss.en[:60]
        elif not senses:
            row["gloss"] = "(not in words.hk: corpus n-gram)"
        if a.counts:
            row["strict_corpus_count"] = corpus.count(m.term)
        rows.append(row)
    from . import jyutping
    _out({"query": a.text, "query_jyutping": jyutping.romanize(a.text, all_readings=True),
          "hyps": [{"text": h, "jyutping": jyutping.romanize(h, all_readings=True)} for h in a.hyp or []],
          "matches": rows})


def cmd_dict(a):
    from . import dictionary, jyutping
    q = " ".join(a.query)
    if a.contains:
        terms = dictionary.terms_containing(q)
        return _out({"contains": q, "terms": [dictionary.describe(t, 1) for t in terms[:a.limit]],
                     "more": max(0, len(terms) - a.limit)})
    fixed = jyutping.particle_readings()
    if q and all(ch in fixed for ch in q) and not a.literal:
        # words.hk spells particles its own way: look them up by reading.
        return _out(dictionary.particle_senses(" ".join(fixed[ch] for ch in q), 8))
    if any(ch.isdigit() for ch in q) or a.toneless:
        terms = dictionary.terms_for_jyutping(q, toneless=a.toneless)
        return _out({"jyutping": q, "terms": [dictionary.describe(t, 1) for t in terms[:a.limit]],
                     "more": max(0, len(terms) - a.limit)})
    _out(dictionary.describe(q, a.senses))


def cmd_corpus(a):
    from . import corpus
    if a.vs:
        return _out(corpus.compare([a.pattern, *a.vs], a.tier, a.show))
    if a.final:
        return _out(corpus.colloc(a.pattern, "final", a.tier, a.show, 8, 2, a.examples, a.among))
    _out(corpus.search(a.pattern, a.tier, a.show, a.examples, a.context))


# ---------------------------------------------------------------------------- audio

def _span_items(a, ep, srt):
    from .groups import listen_span
    if a.batch:
        return json.loads(Path(a.batch).read_text(encoding="utf-8"))
    if a.cue:
        items = []
        for pos in a.cue:
            s, e = listen_span(srt.cues, pos, a.pad if a.pad is not None else a.default_pad,
                               clamp=a.pad is None)
            items.append({"key": f"cue {pos}", "cue": pos, "start": round(s, 3), "end": round(e, 3)})
        return items
    if a.start is not None and a.end is not None:
        return [{"key": f"{a.start}-{a.end}", "start": a.start, "end": a.end}]
    raise SystemExit("give --cue N, --start/--end, or --batch FILE")


def cmd_listen(a):
    from . import episode, gpu_bridge, jyutping
    from .render import content_key
    ep = episode.load(a.id)
    srt = episode.srt(ep)
    a.default_pad = 1.0
    items = _span_items(a, ep, srt)
    res = gpu_bridge.run("listen", {"media": ep["media"], "audio_track": ep.get("audio_track", 0),
                                    "models": a.models.split(","), "isolate": a.isolate, "items": items})
    for it, src in zip(res["items"], items):
        if src.get("cue"):
            draft = srt.cue(src["cue"]).text
            it["draft"] = draft
        for tag, text in list(it["asr"].items()):
            it["asr"][tag] = {"text": text, "jyutping": jyutping.romanize(text)}
            if src.get("cue"):
                it["asr"][tag]["same_content_as_draft"] = content_key(text, tag) == content_key(it["draft"], tag)
    res["note"] = ("A padded span includes neighbouring speech; compare only the part that "
                   "corresponds to the cue.")
    _out(res)


def cmd_score(a):
    """Scores come from the emissions `ccp evidence` stored (light, about a second). Items
    that cannot be scored exactly from them (an explicit --pad or --start/--end span, a
    character outside the stored token table, no stored emissions) go to the GPU in one
    one-shot batch."""
    from . import ctcscore, episode, gpu_bridge
    from .groups import listen_span
    ep = episode.load(a.id)
    srt = episode.srt(ep)
    a.default_pad = 0.3
    if a.batch:
        items = json.loads(Path(a.batch).read_text(encoding="utf-8"))
    else:
        if not a.cue or len(a.cue) != 1:
            raise SystemExit("give exactly one --cue with candidates, or --batch FILE")
        items = _span_items(a, ep, srt)
        items[0]["candidates"] = a.candidates
    explicit_span = a.pad is not None or (a.start is not None and a.end is not None)
    for it in items:
        it.setdefault("key", f"cue {it['cue']}" if "cue" in it else None)
        if "draft" not in it:
            it["draft"] = srt.cue(it["cue"]).text
        if "start" not in it:
            it["start"], it["end"] = listen_span(srt.cues, it["cue"], 0.3)
    try:
        store = None if explicit_span else ctcscore.Store(a.id)
    except FileNotFoundError:
        store = None
    results: list = [None] * len(items)
    if store is not None:
        for k, it in enumerate(items):
            r = ctcscore.score_item(store, it["start"], it["end"], it["draft"], it["candidates"])
            if r is not None:
                results[k] = {"key": it["key"], **r}
    todo = [k for k, r in enumerate(results) if r is None]
    if todo:
        why = ("an explicit span" if explicit_span else
               "no stored emissions (re-run `ccp evidence --force` to store them)" if store is None else
               "characters or spans outside the stored emissions")
        print(f"  [score] {len(todo)} item(s) need the GPU ({why}); loading the aligner, 20-40 s",
              file=sys.stderr, flush=True)
        res = gpu_bridge.run("score", {"media": ep["media"], "audio_track": ep.get("audio_track", 0),
                                       "items": [items[k] for k in todo]})
        for k, r in zip(todo, res["items"]):
            results[k] = {**r, "scored_on": "gpu (clip alone)"}
    _out({"items": results})


def cmd_fetch(a):
    from . import fetch
    _out(fetch.fetch(a.url, a.id, a.sub_langs.split(",") if a.sub_langs else None, a.force))


def cmd_export(a):
    from . import export
    _out(_prune_hint(export.export(a.id, a.to, a.name), a.id))


def cmd_timing(a):
    from . import timing
    _out(timing.suggest(a.id, a.cue, a.split, a.retime))


def cmd_pipeline(a):
    from . import pipeline
    if a.action == "runs":
        return _out(pipeline.runs(a.id))
    _out(pipeline.run(a.id, a.action, a.mode, a.input, a.extra, a.force))


def cmd_publish(a):
    from . import pipeline
    res = pipeline.publish(a.id, a.to, a.dry_run, a.to_main, a.name, a.overwrite)
    _out(res if a.dry_run or "from" not in res else _prune_hint(res, a.id))


def cmd_copy_draft(a):
    from . import pipeline
    _out(pipeline.copy_draft(a.id))


# ---------------------------------------------------------------------------- findings

def _legacy_grade(a) -> str | None:
    """--severity/--confidence from older instructions → a grade."""
    if a.grade or not (a.severity or a.confidence):
        return a.grade
    if a.severity == "query" or a.confidence == "low":
        return "query"
    return "fix" if (a.confidence or "medium") == "high" else "suggest"


def cmd_flag(a):
    from . import flags
    a.grade = _legacy_grade(a)
    a.reason = a.reason or a.note
    if a.action == "add":
        if a.json_file:
            items = json.loads(Path(a.json_file).read_text(encoding="utf-8-sig"))
            return _out([flags.fmt(f) for f in flags.add_many(a.id, items if isinstance(items, list) else [items])])
        need = [k for k in ("cue", "category", "grade", "reason") if getattr(a, k) is None]
        if need:
            raise SystemExit(f"missing --{', --'.join(need)}")
        pc = flags.saved_timing(a.id, a.cue) if a.timing else None
        f = flags.add(a.id, a.cue, a.category, a.grade, a.proposed, a.evidence or [], a.reason,
                      a.related or [], a.alt or [], a.replace, pc)
        return _out(flags.fmt(f))
    if a.action == "keep":
        if a.cue is None or not a.reason:
            raise SystemExit("give --cue N and --reason \"why the line is right\"")
        return _out(flags.fmt(flags.keep(a.id, a.cue, a.reason, a.evidence or [], a.category or "other")))
    if a.action == "update":
        if a.flag_id is None:
            raise SystemExit("give the flag id: ccp flag update ID FLAG_ID ...")
        pc = None
        if a.timing:
            cue = next(f["cue"] for f in flags.load(a.id) if f["id"] == a.flag_id)
            pc = flags.saved_timing(a.id, cue)
        f = flags.update(a.id, a.flag_id, category=a.category, grade=a.grade, proposed=a.proposed,
                         evidence=a.evidence, reason=a.reason, status=a.status, alternatives=a.alt,
                         proposed_cues=pc)
        return _out(flags.fmt(f))
    rows = flags.load(a.id)
    if a.grade:
        rows = [f for f in rows if f["grade"] == a.grade]
    if a.status:
        rows = [f for f in rows if f["status"] == a.status]
    if a.json:
        return _out(rows)
    _out("\n".join([f"{flags.summary(rows)}"] + [flags.fmt(f) for f in rows]))


def cmd_report(a):
    from . import report
    p = report.build(a.id, video=a.video, include_rejected=a.include_rejected)
    res = {"report": str(p), "open": p.as_uri(), **report.CLIP_STATUS}
    if report.CLIP_STATUS.get("failed"):
        res["warning"] = ("some audio clips could not be cut, so their cards have no player; "
                          "tell the user and quote first_error")
    _out(res)


def _prune_hint(res: dict, episode_id: str) -> dict:
    """After a step that may end a job, say how much `ccp prune` would free."""
    from .prune import reclaimable_mb
    mb = reclaimable_mb(episode_id)
    if mb >= 1:
        res["prune"] = (f"`ccp prune {episode_id}` frees {mb} MB (stored emissions, report audio, pipeline "
                        "debug files) once the job is finished and the user is done reviewing")
    return res


def cmd_apply(a):
    from . import apply
    # --min-severity/--min-confidence are the old spelling of --include-suggest.
    include_suggest = a.include_suggest or a.min_severity in ("suggested", "query") \
        or a.min_confidence in ("medium", "low")
    res = apply.apply(a.id, Path(a.decisions) if a.decisions else None, include_suggest,
                      a.include or [], a.dry_run, a.structure)
    _out(res if a.dry_run or not res.get("applied") else _prune_hint(res, a.id))


def cmd_clean(a):
    from . import clean
    lines = list(a.edit or [])
    if a.edits:
        lines += Path(a.edits).read_text(encoding="utf-8-sig").splitlines()
    if not lines and not a.lint:
        raise SystemExit("give edits (N|new text|reason) as arguments or with --edits FILE, and/or --lint")
    _out(clean.clean(a.id, clean.parse(lines), a.lint, a.skip_lint or [], a.dry_run, a.no_apply))


def cmd_prune(a):
    from . import prune
    if a.finished:
        return _out(prune.prune_finished(a.dry_run, a.downloads))
    if not a.id:
        raise SystemExit("give a workspace id, or --finished for every finished workspace")
    _out(prune.prune(a.id, a.dry_run, a.downloads))


# ---------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    from .flags import CATEGORIES, GRADES, STATUSES
    p = argparse.ArgumentParser(prog="ccp", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("locate", help="find a subtitle + media and create its workspace")
    s.add_argument("request", nargs="*", help="e.g. 'Attack on Titan S1E03', '進擊的巨人 第3集'")
    s.add_argument("--select", metavar="EPISODE_ID", help="create the workspace for this manifest record")
    s.add_argument("--srt", help="a subtitle path (anywhere) instead of a request")
    s.add_argument("--id", help="workspace id (required with --media alone; optional with --srt)")
    s.add_argument("--media", help="the media file, overriding the inferred one; alone (with --id): an episode with no subtitle yet")
    s.add_argument("--audio-track", type=int, help="audio stream (0-based among audio streams)")
    s.add_argument("--no-create", action="store_true", help="do not create a workspace on a unique match")
    s.set_defaults(fn=cmd_locate)

    s = sub.add_parser("fetch", help="download a video's audio (+ its subtitles as references) from a link")
    s.add_argument("url"); s.add_argument("--id", help="workspace id (default: yt-<video id>)")
    s.add_argument("--sub-langs", help="only these subtitle languages, comma-separated (e.g. zh-Hant,en)")
    s.add_argument("--force", action="store_true", help="download again even if the audio is already here")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("export", help="write the final subtitles, the original ASR, references and report to one folder")
    s.add_argument("id"); s.add_argument("--to", help="folder (default work/<id>/output)")
    s.add_argument("--name", help="file name stem (default: the video title or source name)")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("status", help="what the workspace holds so far")
    s.add_argument("id"); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("reference", help="find / extract / OCR a reference subtitle and time it")
    s.add_argument("id"); s.add_argument("--file", help="use this subtitle file")
    s.add_argument("--stream", type=int, help="use this embedded stream (absolute stream index)")
    s.add_argument("--ocr", action="store_true", help="allow OCR of a bitmap track (ask the user first)")
    s.set_defaults(fn=cmd_reference)

    s = sub.add_parser("evidence", help="(GPU) both ASRs + aligner peaks for every cue")
    s.add_argument("id"); s.add_argument("--models", default=None,
                                         help="ft,qw (default), or qw alone (the default for an ASR draft)")
    s.add_argument("--diarize", action="store_true"); s.add_argument("--force", action="store_true")
    s.add_argument("--gap", type=float, default=0.8); s.add_argument("--max-len", type=float, default=20.0)
    s.add_argument("--pad", type=float, default=0.5)
    s.set_defaults(fn=cmd_evidence)

    s = sub.add_parser("render", help="the review stream for a window of cues")
    s.add_argument("id"); s.add_argument("--from", dest="start", type=int, default=1)
    s.add_argument("--to", dest="end", type=int); s.add_argument("--groups", action="store_true")
    s.add_argument("--no-times", action="store_true"); s.set_defaults(fn=cmd_render)

    s = sub.add_parser("cue", help="everything known about one or more cues")
    s.add_argument("id"); s.add_argument("cue", nargs="+", help=f"suspect cue numbers (9 11 24) or a range (230-235); at most {MAX_CUES}")
    s.add_argument("--context", type=int, default=1, help="neighbouring cues shown on each side")
    s.add_argument("--json", action="store_true", help="full JSON instead of compact text")
    s.set_defaults(fn=cmd_cue)

    s = sub.add_parser("sounds-like", help="words that sound like a suspect span")
    s.add_argument("text", help="the suspect span from the draft (tight: just the doubtful words)")
    s.add_argument("--hyp", action="append", help="another hypothesis for the same span (ASR text); repeatable")
    s.add_argument("-n", type=int, default=20); s.add_argument("--min-len", type=int); s.add_argument("--max-len", type=int)
    s.add_argument("--source", choices=["dict", "corpus", "both"], default="dict")
    s.add_argument("--show", help="add n-grams from this show's strict episodes (names)")
    s.add_argument("--tier", default="strict"); s.add_argument("--min-count", type=int, default=2)
    s.add_argument("--counts", action="store_true", help="add strict-corpus counts per match")
    s.set_defaults(fn=cmd_sounds_like)

    s = sub.add_parser("dict", help="words.hk lookup by term or Jyutping (a particle is looked up by its reading)")
    s.add_argument("query", nargs="+"); s.add_argument("--toneless", action="store_true")
    s.add_argument("--senses", type=int, default=4); s.add_argument("--limit", type=int, default=15)
    s.add_argument("--literal", action="store_true", help="look a particle character up as written")
    s.add_argument("--contains", action="store_true",
                   help="list words containing the text (or the Jyutping sequence, e.g. 'gam2 ji5')")
    s.set_defaults(fn=cmd_dict)

    s = sub.add_parser("corpus", help="regex search over the strict-tier corpus")
    s.add_argument("pattern"); s.add_argument("--show"); s.add_argument("--tier", default="strict")
    s.add_argument("--examples", type=int, default=10)
    s.add_argument("--vs", nargs="+", help="compare counts of literal forms: PATTERN vs these")
    s.add_argument("-C", "--context", type=int, default=0,
                   help="show N neighbouring cues around each example (same episode)")
    s.add_argument("--final", action="store_true",
                   help="which clause-final particles follow PATTERN (a comma ends the clause)")
    s.add_argument("--among", default="",
                   help="with --final: a particle family (laa, aa, gaa, ge, lo, wo, zaa, ze, gam) or literal chars")
    s.set_defaults(fn=cmd_corpus)

    for name, fn, helptext in (("listen", cmd_listen, "(GPU) re-run both ASRs on a cue or span"),
                               ("score", cmd_score, "(GPU) CTC-score candidate texts against a cue's audio")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("id")
        s.add_argument("--cue", type=int, action="append")
        s.add_argument("--pad", type=float, help="seconds of padding (explicit: not clamped to neighbours)")
        s.add_argument("--start", type=float); s.add_argument("--end", type=float)
        s.add_argument("--batch", help="JSON list of items")
        if name == "listen":
            s.add_argument("--models", default="ft,qw"); s.add_argument("--isolate", action="store_true")
        else:
            s.add_argument("candidates", nargs="*")
        s.set_defaults(fn=fn)

    s = sub.add_parser("timing", help="propose a retime or a split for a cue from the stored audio alignment")
    s.add_argument("id"); s.add_argument("cue", type=int)
    s.add_argument("--split", help="the cue's text cut into pieces with |, e.g. '走喇|你唔好再嚟'")
    s.add_argument("--retime", action="store_true", help="with --split: also move the outer edges to the speech")
    s.set_defaults(fn=cmd_timing)

    s = sub.add_parser("pipeline", help="(GPU) run cantocaptions-ai: realign or transcribe into a new working draft",
                       epilog="Extra cantocaptions flags go after a bare --, e.g. "
                              "ccp pipeline ID realign --mode adjust -- --realign_pause_gap 0.4")
    s.add_argument("id")
    s.add_argument("action", choices=["realign", "transcribe", "runs"])
    s.add_argument("--mode", choices=["auto", "transcript", "sync", "adjust"], default="adjust",
                   help="realign mode (default adjust: keep roughly-right timings, fix them against the audio)")
    s.add_argument("--input", help="realign this file instead of the source subtitle ('draft' = the current working draft)")
    s.add_argument("--force", action="store_true", help="replace a draft that already has applied corrections")
    s.set_defaults(fn=cmd_pipeline)

    s = sub.add_parser("publish", help="copy the working draft into CantoCaptions (ask the user first)")
    s.add_argument("id"); s.add_argument("--to", help="target file or folder (default: replace the source file)")
    s.add_argument("--to-main", action="store_true",
                   help="into the main library area: the same show outside the '(AI-generated)' tree")
    s.add_argument("--name", help="file name for --to-main / a --to folder (default: library-style name of the source)")
    s.add_argument("--overwrite", action="store_true", help="replace an existing file that is not the source")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("prune", help="free disk space at the end of a job (emissions, report audio, debug files)")
    s.add_argument("id", nargs="?")
    s.add_argument("--finished", action="store_true", help="every workspace whose job is finished")
    s.add_argument("--downloads", action="store_true", help="also delete downloaded audio (ccp fetch)")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_prune)

    s = sub.add_parser("copy-draft", help="work on a copy of the source (edits then go to a new file, not the source)")
    s.add_argument("id"); s.set_defaults(fn=cmd_copy_draft)

    s = sub.add_parser("flag", help="record findings: add / keep / update / list")
    s.add_argument("action", choices=["add", "keep", "update", "list"]); s.add_argument("id")
    s.add_argument("flag_id", nargs="?", type=int)
    s.add_argument("--cue", type=int); s.add_argument("--category", choices=CATEGORIES)
    s.add_argument("--grade", choices=GRADES,
                   help="fix (confident) | suggest (reviewer decides) | query (no confident fix) | keep (checked, right)")
    s.add_argument("--reason", help="required: why the line is wrong (or right) and why the proposal is right")
    s.add_argument("--severity", help=argparse.SUPPRESS); s.add_argument("--confidence", help=argparse.SUPPRESS)
    s.add_argument("--note", help=argparse.SUPPRESS)
    s.add_argument("--proposed", help="full new cue text (⏎ or \\n between lines); fix and suggest only")
    s.add_argument("--evidence", action="append", help="'source: detail', repeatable")
    s.add_argument("--alt", action="append", help="alternative full texts (for a query)")
    s.add_argument("--related", type=int, action="append")
    s.add_argument("--status", choices=STATUSES); s.add_argument("--replace", action="store_true")
    s.add_argument("--timing", action="store_true",
                   help="attach the retime/split that `ccp timing` saved for this cue")
    s.add_argument("--json-file", help="add: a JSON object or list of flags")
    s.add_argument("--json", action="store_true", help="list: raw JSON")
    s.set_defaults(fn=cmd_flag)

    s = sub.add_parser("clean", help="text-only cleanup pass: record and apply confident edits in bulk")
    s.add_argument("id")
    s.add_argument("edit", nargs="*", help="'N|new full text|reason' (reason optional; '?' as the text = a query)")
    s.add_argument("--edits", help="a UTF-8 file with one edit per line, same format")
    s.add_argument("--lint", action="store_true",
                   help="also apply the mechanical lint fixes (spelling variants, glossary forms, punctuation)")
    s.add_argument("--skip-lint", type=int, action="append", metavar="CUE",
                   help="leave this cue's lint hits alone (e.g. a variant inside a name or quotation)")
    s.add_argument("--dry-run", action="store_true", help="show the planned edits, change nothing")
    s.add_argument("--no-apply", action="store_true", help="record the flags but do not edit the draft")
    s.set_defaults(fn=cmd_clean)

    s = sub.add_parser("report", help="HTML review page with clips")
    s.add_argument("id"); s.add_argument("--video", action="store_true")
    s.add_argument("--include-rejected", action="store_true"); s.set_defaults(fn=cmd_report)

    s = sub.add_parser("apply", help="write accepted corrections into the subtitle (never commits)")
    s.add_argument("id"); s.add_argument("--decisions", help="decisions.json exported from the report")
    s.add_argument("--include-suggest", action="store_true",
                   help="also apply flags graded suggest (default: only fix)")
    s.add_argument("--min-severity", help=argparse.SUPPRESS)
    s.add_argument("--min-confidence", help=argparse.SUPPRESS)
    s.add_argument("--include", type=int, action="append", help="also apply this flag id")
    s.add_argument("--structure", action="store_true",
                   help="also apply retimes and splits (flags with proposed cues); only when the user asked")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_apply)
    return p


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    if "--" in argv:                      # everything after a bare -- goes to the wrapped tool
        k = argv.index("--")
        argv, passthrough = argv[:k], argv[k + 1:]
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    args.extra = passthrough
    if extra:
        # Show the subcommand's own options, not the top-level usage, so a guessed flag
        # (e.g. grep's -C) can be corrected in one step.
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        sp = sub.choices[args.cmd]
        sp.print_help(sys.stderr)
        sp.exit(2, f"\nccp {args.cmd}: error: unrecognized arguments: {' '.join(extra)}\n")
    try:
        args.fn(args)
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
