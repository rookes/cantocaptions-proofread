"""Shared plumbing for the GPU scripts (runs in cantocaptions-ai's interpreter)."""
from __future__ import annotations

import gc
import json
import logging
import sys
import unicodedata
import warnings
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

SAMPLE_RATE = 16000
DEVICE = "cuda"

# Model tags -> cantocaptions-ai registered model names.
ASR_MODELS = {"ft": "cantocaptions-cantonese-ASR", "qw": "Qwen3-ASR"}


def io() -> tuple[dict, Path]:
    req = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    return req, Path(sys.argv[2])


def done(result_path: Path, result) -> None:
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def status(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def free() -> None:
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def load_media_audio(media: str, track: int, start: float | None = None, end: float | None = None):
    from cantocaptions_ai.utils.audio import load_audio
    return load_audio(media, audio_track=track, audio_start=start, audio_end=end)


def load_asr(tag: str):
    from cantocaptions_ai.pipeline.asr import load_model
    return load_model(ASR_MODELS[tag], DEVICE, language="yue")


def asr_texts(tag: str, clips: list, stage=None) -> list[str]:
    """Transcribe each 16 kHz mono clip with one model; returns texts in order. With *stage*
    (an ASR model the GPU server keeps loaded) it is used and kept; otherwise the model is
    loaded for this call and unloaded after it."""
    own = stage is None
    if own:
        stage = load_asr(tag)
    segs = [{"start": 0.0, "end": len(c) / SAMPLE_RATE, "audio": c} for c in clips]
    out = stage.process(segs)["segments"]
    texts = [s.get("text", "") for s in out]
    if own:
        del stage
        free()
    return texts


def is_sound(ch: str) -> bool:
    return unicodedata.category(ch)[0] not in "PZSC"
