"""ccp particles model: the fine-tuned recogniser's likelihood for each particle alternative.

Request: {"media", "audio_track", "items": [{"key", "start", "end", "text",
          "spots": [{"start", "end", "alts", "cue", "slot", "run"}]}]}
(built by ccp.particles.group_items). Each item is a cue group's audio and its cues written
the model's way; each spot is one clause-final particle with its alternatives. The result
has one row per spot: the joint log-probability of the draft's particle and of each
alternative (each followed by the same few characters of the text), from
cantocaptions-ai's `score_alternatives`.

Runs in the GPU server (it keeps the fine-tuned model loaded) or one-shot; `evidence` calls
`score` directly while its own model is loaded.
"""
from __future__ import annotations

from _common import SAMPLE_RATE, done, free, io, load_asr, status

MODEL = "ft"


def score(stage, items: list[dict], clips: list) -> list[dict]:
    """Rows for every spot of *items*, whose audio is *clips*, with a loaded model."""
    from cantocaptions_ai.pipeline.asr_scoring import Spot
    reqs = [{"audio": clip, "text": it["text"],
             "spots": [Spot(s["start"], s["end"], list(s["alts"])) for s in it["spots"]]}
            for it, clip in zip(items, clips)]
    rows = []
    for it, scored in zip(items, stage.score_alternatives(reqs, "yue")):
        by_start = {sc.start: sc for sc in scored}
        for s in it["spots"]:
            sc = by_start.get(s["start"])
            if sc is None:
                continue
            rows.append({"cue": s["cue"], "slot": s["slot"], "run": s["run"], "group": it["key"],
                         "model": MODEL, "logprobs": {k: round(v, 3) for k, v in sc.logprobs.items()},
                         "tokens": sc.tokens})
    return rows


def handle(req: dict, clip_for, stage_for=None) -> dict:
    items = req["items"]
    clips = [clip_for(it["start"], it["end"]) for it in items]
    own = stage_for is None
    stage = load_asr(MODEL) if own else stage_for(MODEL)
    status(f"scoring particles in {len(items)} groups...")
    rows = score(stage, items, clips)
    if own:
        del stage
        free()
    return {"rows": rows}


def main():
    from _common import load_media_audio
    req, result_path = io()
    audio = load_media_audio(req["media"], req["audio_track"])
    done(result_path, handle(req, lambda s, e: audio[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)]))


if __name__ == "__main__":
    main()
