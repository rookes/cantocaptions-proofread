"""ccp evidence: one GPU pass over a whole episode.

Request: {"episode_id", "srt", "media", "audio_track", "models": ["ft","qw"],
          "gap": 0.8, "max_len": 20.0, "pad": 0.5, "diarize": false, "out_dir"}
Writes out_dir/evidence.jsonl (one row per cue) and out_dir/groups.jsonl, and, when the
fine-tuned model runs, out_dir/particle_model.jsonl: its likelihood for every clause-final
particle and its alternatives (gpu/particles.py), scored while the model is loaded.

Per group (see ccp.groups): each ASR model transcribes the padded group audio once; the
aligner force-aligns each hypothesis against the group audio and every hypothesis
character is handed to the cue whose span holds its midpoint (padding characters become
`edge_before`/`edge_after` of the first/last cue). The draft text of the group's cues is
force-aligned too, giving each draft character its *peak* probability: low peaks mark
where the audio does not sound like the draft (a where-to-look signal, not a verdict).

Every group's emission is also stored (out_dir/emissions/gNNNN.npy, fp16 log-probs), with
the aligner's token table for every character `ccp score` might meet (emissions/tokens.json,
resolved by the pipeline's own VocabRepair). `ccp score` then scores candidates from disk in
the light environment, with no GPU, no model and no server (see ccp.ctcscore).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np

from _common import SAMPLE_RATE, asr_texts, done, free, io, is_sound, load_asr, load_media_audio, status
import particles
from aligner import Aligner, final_particle_mask
from ccp.groups import make_groups
from ccp.particles import group_items
from ccp.srtio import SrtFile


def split_hypothesis(aln: list[dict], hyp: str, g_start: float, rate: float, cue_spans: list[tuple[int, float, float]]):
    """Assign each character of *hyp* (sound chars carry times; punctuation follows the
    previous char) to a cue. Returns {cue_pos: {"text", "edge_before", "edge_after"}}."""
    out = {pos: {"text": "", "edge_before": "", "edge_after": ""} for pos, _, _ in cue_spans}
    first_pos, last_pos = cue_spans[0][0], cue_spans[-1][0]
    first_start, last_end = cue_spans[0][1], cue_spans[-1][2]
    k = 0
    current = (first_pos, "text")
    for ch in hyp:
        if is_sound(ch):
            slot = aln[k] if k < len(aln) else {"frames": None}
            k += 1
            if slot["frames"] is not None:
                f0, f1 = slot["frames"]
                t = g_start + (f0 + f1 + 1) / 2 / rate
                if t < first_start:
                    current = (first_pos, "edge_before")
                elif t > last_end:
                    current = (last_pos, "edge_after")
                else:
                    inside = [p for p, s, e in cue_spans if s <= t <= e]
                    if inside:
                        current = (inside[0], "text")
                    else:   # in a gap between two cues of the group: nearest cue
                        current = (min(cue_spans, key=lambda c: min(abs(c[1] - t), abs(c[2] - t)))[0], "text")
        pos, field = current
        out[pos][field] += ch
    return out


def main():
    req, result_path = io()
    t0 = time.time()
    cues = SrtFile(Path(req["srt"])).cues
    status(f"loading audio ({req['media']}, track {req['audio_track']})")
    audio = load_media_audio(req["media"], req["audio_track"])
    duration = len(audio) / SAMPLE_RATE
    groups = make_groups(cues, gap=req.get("gap", 0.8), max_len=req.get("max_len", 20.0),
                         pad=req.get("pad", 0.5), audio_end=duration)
    groups = [g for g in groups if g.end - g.start > 0.05 and g.start < duration]
    clips = [audio[int(g.start * SAMPLE_RATE):int(g.end * SAMPLE_RATE)] for g in groups]
    status(f"{len(cues)} cues in {len(groups)} groups")

    hyps: dict[str, list[str]] = {}
    particle_rows = None
    for tag in req.get("models", ["ft", "qw"]):
        status(f"ASR {tag}...")
        if tag == particles.MODEL and req.get("particles", True):
            # The fine-tuned model is loaded anyway: score every particle while it is.
            stage = load_asr(tag)
            hyps[tag] = asr_texts(tag, clips, stage)
            items = group_items(cues, groups)
            index = {g.index: i for i, g in enumerate(groups)}
            status(f"particles: {sum(len(it['spots']) for it in items)} in {len(items)} groups...")
            particle_rows = particles.score(stage, items, [clips[index[it["key"]]] for it in items])
            del stage
            free()
        else:
            hyps[tag] = asr_texts(tag, clips)

    status("aligning...")
    al = Aligner()
    by_cue: dict[int, dict] = {c.pos: {"cue": c.pos, "start": c.start, "end": c.end, "asr": {}, "peaks": []}
                               for c in cues}
    group_rows = []
    out_dir = Path(req["out_dir"])
    em_dir = out_dir / "emissions"
    if em_dir.exists():
        shutil.rmtree(em_dir)
    em_dir.mkdir(parents=True)
    B = 16
    for b in range(0, len(groups), B):
        ems = al.emissions(clips[b:b + B])
        for gi, (em, rate) in zip(range(b, b + B), ems):
            g = groups[gi]
            spans = [(p, cues[p - 1].start, cues[p - 1].end) for p in g.cues]
            # Draft peaks: align the group's draft text as one sequence.
            draft_texts = [cues[p - 1].text for p in g.cues]
            aln = al.force_align(em, "".join(draft_texts))
            k = 0
            for p, text in zip(g.cues, draft_texts):
                n = sum(1 for ch in text if is_sound(ch))
                mask = final_particle_mask(text)
                by_cue[p]["peaks"] = [[a["char"], a["peak"], fin] for a, fin in zip(aln[k:k + n], mask)]
                by_cue[p]["group"] = g.index
                k += n
            np.save(em_dir / f"g{g.index:04d}.npy", em.numpy().astype(np.float16))
            row = {"group": g.index, "start": round(g.start, 3), "end": round(g.end, 3),
                   "cues": g.cues, "asr": {}, "frames": int(em.shape[0]), "rate": rate}
            for tag, texts in hyps.items():
                hyp = texts[gi]
                row["asr"][tag] = hyp
                hal = al.force_align(em, hyp) if hyp else []
                parts = split_hypothesis(hal, hyp, g.start, rate, spans) if hyp else {}
                for p in g.cues:
                    by_cue[p]["asr"][tag] = parts.get(p, {"text": "", "edge_before": "", "edge_after": ""})
            group_rows.append(row)
        free()

    status("exporting the token table...")
    extra = "".join(c.text for c in cues) + "".join(t for texts in hyps.values() for t in texts)
    (em_dir / "tokens.json").write_text(json.dumps(al.export_token_table(extra), ensure_ascii=False),
                                        encoding="utf-8")

    if req.get("diarize"):
        status("diarizing...")
        from cantocaptions_ai.pipeline.diarize import load_diarization
        from cantocaptions_ai.utils.model_utils import load_with_offline_fallback
        dia = load_with_offline_fallback(load_diarization, device="cuda", scope="file")
        turns = dia.process(audio)["turns"]
        del dia
        free()
        for c in cues:
            best, best_ov = None, 0.0
            for t in turns:
                ov = min(c.end, t["end"]) - max(c.start, t["start"])
                if ov > best_ov:
                    best, best_ov = t["speaker"], ov
            by_cue[c.pos]["speaker"] = best
        for g in groups:
            for a, b in zip(g.cues, g.cues[1:]):
                sa, sb = by_cue[a].get("speaker"), by_cue[b].get("speaker")
                if sa and sb and sa != sb:
                    by_cue[b]["speaker_change"] = True

    if particle_rows is not None:
        (out_dir / "particle_model.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in particle_rows), encoding="utf-8")
    (out_dir / "evidence.jsonl").write_text(
        "".join(json.dumps(by_cue[c.pos], ensure_ascii=False) + "\n" for c in cues), encoding="utf-8")
    (out_dir / "groups.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in group_rows), encoding="utf-8")
    done(result_path, {"cues": len(cues), "groups": len(groups), "models": list(hyps),
                       "particles_scored": len(particle_rows) if particle_rows is not None else None,
                       "diarized": bool(req.get("diarize")), "seconds": round(time.time() - t0, 1)})


if __name__ == "__main__":
    main()
