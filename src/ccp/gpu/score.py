"""ccp score: CTC log-likelihood of candidate texts against a cue's audio.

Request: {"media", "audio_track",
          "items": [{"key", "start", "end", "draft", "candidates": [...]}]}
Result per item: the draft's per-character peaks, a reliability verdict, and for each
candidate its log-likelihood relative to the draft (delta, nats), abstentions and any
substitutions or unscorable characters. How to read the numbers is documented once, in the
investigate-line skill's tool guide, not repeated in every result.

This is the GPU fallback. `ccp score` normally scores from the emissions `ccp evidence`
stored (ccp.ctcscore, same steps in numpy) and only sends here what it cannot score from them.
"""
from __future__ import annotations

import statistics

from _common import done, io
from aligner import final_particle_mask

UNRELIABLE_MEDIAN_PEAK = 0.1


def handle(req: dict, al, clip_for, emission_for=None) -> dict:
    """*clip_for(start, end)* returns 16 kHz audio; *emission_for(start, end, clip)*, if
    given, supplies the emission instead of running the model on the clip."""
    out = []
    for it in req["items"]:
        clip = clip_for(it["start"], it["end"])
        if emission_for is not None:
            em = emission_for(it["start"], it["end"], clip)
        else:
            (em, _rate), = al.emissions([clip], batch_size=1)
        draft = it["draft"]
        aln = al.force_align(em, draft)
        mask = final_particle_mask(draft)
        content = [a["peak"] for a, fin in zip(aln, mask) if not fin]
        median = statistics.median(content) if content else 0.0
        scores = al.score(em, [draft, *it["candidates"]])
        base = scores[0].loglik
        cands = []
        for s in scores[1:]:
            row = {"text": s.text, "delta": None if s.loglik == float("-inf") or base == float("-inf")
                   else round(s.loglik - base, 2)}
            if s.abstain:
                row["abstain"] = s.abstain
            if s.substituted:
                row["substituted"] = s.substituted
            if s.unscorable:
                row["unscorable"] = s.unscorable
            if s.spoken != s.text and any(ch.isdigit() for ch in s.text):
                row["scored_as"] = s.spoken
            cands.append(row)
        result = {"key": it.get("key"), "draft": draft,
                  "draft_peaks": "  ".join(f"{a['char']} {a['peak']:.2f}" for a in aln),
                  "reliable": median >= UNRELIABLE_MEDIAN_PEAK,
                  "candidates": cands}
        if scores[0].unscorable:
            result["draft_unscorable"] = scores[0].unscorable
        if not result["reliable"]:
            result["warning"] = f"aligner barely hears this span (median peak {median:.2f}); ignore these deltas"
        out.append(result)
    return {"items": out}


def main():
    from _common import load_media_audio
    from aligner import Aligner
    req, result_path = io()
    al = Aligner()
    audio = load_media_audio(req["media"], req["audio_track"])
    clip_for = lambda s, e: audio[int(s * 16000):int(e * 16000)]
    done(result_path, handle(req, al, clip_for))


if __name__ == "__main__":
    main()
