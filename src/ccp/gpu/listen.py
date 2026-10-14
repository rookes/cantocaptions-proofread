"""ccp listen: re-run ASR on chosen spans, optionally after vocal isolation.

Request: {"media", "audio_track", "models": ["ft","qw"], "isolate": false,
          "items": [{"key": "...", "start": s, "end": e}]}
Result: {"items": [{"key", "start", "end", "asr": {"ft": text, "qw": text}}]}

The ASR models are loaded for the request and unloaded after it.
"""
from __future__ import annotations

from _common import SAMPLE_RATE, asr_texts, done, free, io, status


def isolate(clips):
    from cantocaptions_ai.pipeline.vocal_isolation import load_vocal_isolation
    proc = load_vocal_isolation("mbroformer", "cuda")
    items = [{"audio_path": f"clip{i}", "vad_segments": [
        {"start": 0.0, "end": len(c) / SAMPLE_RATE, "audio": c}]} for i, c in enumerate(clips)]
    out = proc.run(items)
    del proc
    free()
    return [it["vad_segments"][0]["audio"] for it in out]


def handle(req: dict, clip_for) -> dict:
    items = req["items"]
    clips = [clip_for(it["start"], it["end"]) for it in items]
    if req.get("isolate"):
        status("isolating vocals...")
        clips = isolate(clips)
    results = [{"key": it.get("key"), "start": it["start"], "end": it["end"], "asr": {}} for it in items]
    for tag in req.get("models", ["ft", "qw"]):
        status(f"ASR {tag}...")
        for r, text in zip(results, asr_texts(tag, clips)):
            r["asr"][tag] = text
    return {"items": results, "isolated": bool(req.get("isolate"))}


def main():
    from _common import load_media_audio
    req, result_path = io()
    audio = load_media_audio(req["media"], req["audio_track"])
    done(result_path, handle(req, lambda s, e: audio[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)]))


if __name__ == "__main__":
    main()
