"""Candidate scoring from stored emissions: no GPU, no model, no server.

`ccp evidence` stores each cue group's aligner emission (log-probabilities, fp16) and a token
table resolved by the pipeline's own VocabRepair (see gpu/aligner.py: export_token_table).
This module repeats exactly what gpu/aligner.py's `score` and `force_align` do, in numpy:

  text -> numeral readings -> strip clause-final particles -> homophone canonical form ->
  tokens -> CTC log-likelihood over the cue's frames

The CTC forward pass is the same quantity as torch.nn.functional.ctc_loss(reduction="sum")
(negated), and the forced alignment for draft peaks is a port of the pipeline's
get_trellis/backtrack. tests/ and scripts/compare_score_paths.py check both against the GPU
implementation.

The cue's frames are sliced from its group's emission, so the model has heard the
surrounding speech. The one-shot GPU path instead runs the model on the cue's clip alone.
Anything this module cannot do exactly (a character missing from the table, a span outside
the stored groups) returns None, and the caller falls back to the GPU path.
"""
from __future__ import annotations

import importlib.util
import json
import math
import statistics
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import episode, paths
from .corpus import FINAL_PARTICLES
from .jyutping import is_sound

UNRELIABLE_MEDIAN_PEAK = 0.1
NEG_INF = -np.inf


# ---------------------------------------------------------------------------- text

def final_particle_mask(text: str) -> list[bool]:
    mask: list[bool] = []
    clause: list[str] = []

    def close():
        flags = [False] * len(clause)
        k = len(clause)
        while k > 0 and clause[k - 1] in FINAL_PARTICLES:
            k -= 1
            flags[k] = True
        mask.extend(flags)
        clause.clear()

    for ch in text:
        if is_sound(ch):
            clause.append(ch)
        else:
            close()
    close()
    return mask


def strip_final_particles(text: str) -> str:
    mask = iter(final_particle_mask(text))
    return "".join(ch for ch in text if not is_sound(ch) or not next(mask))


@lru_cache(maxsize=1)
def _numeral_readings():
    """cantocaptions-ai's numeral_readings, loaded straight from its file: the module imports
    only `re`, so this keeps the exact pipeline behaviour without its package or torch."""
    src = paths.get("cantocaptions_ai") / "cantocaptions_ai" / "languages" / "yue" / "numeral_candidates.py"
    spec = importlib.util.spec_from_file_location("_ccai_numeral_candidates", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.numeral_readings


class Table:
    def __init__(self, data: dict):
        self.blank = data["blank"]
        self.tokens = data["tokens"]
        self.canonical = data["canonical"]
        self.unscorable = set(data["unscorable"])

    def known(self, ch: str) -> bool:
        lo = ch.lower()
        return lo in self.tokens or lo in self.unscorable

    def ids(self, form: str) -> tuple[list[int], list[str], list[str]] | None:
        """(ids, substitutions, unscorable) for the sound chars of *form*, or None if a
        character is not in the table at all (the caller must fall back)."""
        ids, used, missing = [], [], []
        for ch in form:
            if not is_sound(ch):
                continue
            lo = ch.lower()
            if lo in self.tokens:
                tid, note = self.tokens[lo]
                ids.append(tid)
                if note:
                    used.append(note)
            elif lo in self.unscorable:
                missing.append(lo)
            else:
                return None
        return ids, used, missing

    def phonetic(self, text: str) -> str:
        text = strip_final_particles(text)
        return "".join(self.canonical.get(c, c) if is_sound(c) else c for c in text)


# ---------------------------------------------------------------------------- CTC

def ctc_loglik(lp: np.ndarray, ids: list[int], blank: int) -> float:
    """log P(ids | emission) summed over all CTC alignments: the negated value of
    torch.nn.functional.ctc_loss(..., reduction="sum") for the same inputs."""
    if not ids:
        return float("-inf")
    T = lp.shape[0]
    ext = [blank]
    for t in ids:
        ext += [t, blank]
    S = len(ext)
    ext_a = np.array(ext)
    # A label may skip the blank before it unless it repeats the previous label.
    skip = np.zeros(S, dtype=bool)
    for s in range(2, S):
        skip[s] = ext[s] != blank and ext[s] != ext[s - 2]
    alpha = np.full(S, NEG_INF)
    alpha[0] = lp[0, blank]
    if S > 1:
        alpha[1] = lp[0, ext[1]]
    for t in range(1, T):
        prev = alpha
        a1 = np.concatenate(([NEG_INF], prev[:-1]))
        a2 = np.concatenate(([NEG_INF, NEG_INF], prev[:-2]))
        a2 = np.where(skip, a2, NEG_INF)
        alpha = np.logaddexp(np.logaddexp(prev, a1), a2) + lp[t, ext_a]
    end = np.logaddexp(alpha[-1], alpha[-2]) if S > 1 else alpha[-1]
    return float(end) if math.isfinite(end) else float("-inf")


def force_align_peaks(lp: np.ndarray, ids: list[int], blank: int) -> list[float] | None:
    """Per token, its peak probability over the frames the forced alignment gives it."""
    path = force_align_path(lp, ids, blank)
    return [p["peak"] for p in path] if path is not None else None


def force_align_path(lp: np.ndarray, ids: list[int], blank: int) -> list[dict] | None:
    """Per token: {"onset": frame where it starts, "last": last frame it holds, "peak"}.
    Port of cantocaptions-ai's get_trellis/backtrack (forced, not free-end). This trellis
    scores a held token with the blank probability, so a token's held span runs on through
    any pause after it: the *onset* is the reliable edge, and a token ends no later than
    the next token's onset."""
    T, N = lp.shape[0], len(ids)
    if N == 0 or T < N:
        return None
    trellis = np.empty((T + 1, N + 1))
    trellis[0, 0] = 0
    trellis[1:, 0] = np.cumsum(lp[:, blank])
    trellis[0, 1:] = NEG_INF
    trellis[-N:, 0] = np.inf
    tok = np.array(ids)
    for t in range(T):
        trellis[t + 1, 1:] = np.maximum(trellis[t, 1:] + lp[t, blank], trellis[t, :-1] + lp[t, tok])
    j = N
    t_start = int(np.argmax(trellis[:, j]))
    out = [{"onset": None, "last": None, "peak": 0.0} for _ in range(N)]
    for t in range(t_start, 0, -1):
        stayed = trellis[t - 1, j] + lp[t - 1, blank]
        changed = trellis[t - 1, j - 1] + lp[t - 1, ids[j - 1]]
        slot = out[j - 1]
        # aligner.force_align records the token's own probability on every frame of its span
        slot["peak"] = max(slot["peak"], float(np.exp(lp[t - 1, ids[j - 1]])))
        if slot["last"] is None:
            slot["last"] = t - 1
        slot["onset"] = t - 1
        if changed > stayed:
            j -= 1
            if j == 0:
                break
    else:
        return None
    return out


# ---------------------------------------------------------------------------- episode

class Store:
    """An episode's stored emissions."""

    def __init__(self, episode_id: str):
        self.dir = episode.path(episode_id, "emissions")
        tf = self.dir / "tokens.json"
        if not tf.exists():
            raise FileNotFoundError("no stored emissions; re-run `ccp evidence --force`")
        self.table = Table(json.loads(tf.read_text(encoding="utf-8")))
        self.groups = {g["group"]: g for g in episode.read_jsonl(episode_id, "groups.jsonl") if "rate" in g}
        if not self.groups:
            raise FileNotFoundError("groups.jsonl has no stored emissions; re-run `ccp evidence --force`")

    def group_for(self, start: float, end: float) -> dict | None:
        """The group whose stored span covers [start, end] best (most overlap)."""
        best, best_ov = None, 0.0
        for g in self.groups.values():
            ov = min(end, g["end"]) - max(start, g["start"])
            if ov > best_ov:
                best, best_ov = g, ov
        return best

    def slice(self, start: float, end: float) -> np.ndarray | None:
        g = self.group_for(start, end)
        if g is None:
            return None
        rate = g["rate"]
        f0 = max(0, int(math.floor((start - g["start"]) * rate)))
        f1 = min(g["frames"], int(math.ceil((end - g["start"]) * rate)))
        if f1 - f0 < 2:
            return None
        em = np.load(self.dir / f"g{g['group']:04d}.npy", mmap_mode="r")
        return np.asarray(em[f0:f1], dtype=np.float32)


def score_item(store: Store, start: float, end: float, draft: str, candidates: list[str]) -> dict | None:
    """Same result shape as gpu/score.py's handle(); None if this item needs the GPU path."""
    lp = store.slice(start, end)
    if lp is None:
        return None
    tb = store.table
    nr = _numeral_readings()
    texts = [draft, *candidates]
    for t in texts:
        for reading in nr(t) or [t]:
            if not all(tb.known(c) for c in tb.phonetic(reading) if is_sound(c)):
                return None
    if not all(tb.known(c) for c in draft if is_sound(c)):
        return None

    scored = []
    base_key = None
    for k, text in enumerate(texts):
        best = None
        for reading in nr(text) or [text]:
            form = tb.phonetic(reading)
            ids, used, missing = tb.ids(form)
            ll = ctc_loglik(lp, ids, tb.blank)
            if best is None or ll > best["loglik"]:
                best = {"text": text, "form": form, "loglik": ll, "substituted": used,
                        "unscorable": missing, "spoken": reading}
        key = "".join(c.lower() for c in best["form"] if is_sound(c))
        if k == 0:
            base_key = key
        elif key == base_key:
            sounds = lambda t: "".join(c for c in t if is_sound(c))
            if sounds(text) == sounds(texts[0]):
                best["abstain"] = "differs only in punctuation"
            elif sounds(strip_final_particles(text)) == sounds(strip_final_particles(texts[0])):
                best["abstain"] = "differs only in sentence-final particles"
            else:
                best["abstain"] = "differs only between homophones"
        scored.append(best)

    # Draft peaks: forced alignment of the draft as written (no canonicalisation), as
    # aligner.force_align does; characters without a token get no peak.
    chars = [c for c in draft if is_sound(c)]
    d_ids, where = [], []
    for k, c in enumerate(chars):
        if c.lower() in tb.tokens:
            d_ids.append(tb.tokens[c.lower()][0])
            where.append(k)
    peaks_tok = force_align_peaks(lp, d_ids, tb.blank) or [0.0] * len(d_ids)
    peaks = [0.0] * len(chars)
    for k, p in zip(where, peaks_tok):
        peaks[k] = round(p, 3)
    mask = final_particle_mask(draft)
    content = [p for p, fin in zip(peaks, mask) if not fin]
    median = statistics.median(content) if content else 0.0

    base = scored[0]["loglik"]
    cands = []
    for s in scored[1:]:
        row = {"text": s["text"], "delta": None if s["loglik"] == float("-inf") or base == float("-inf")
               else round(s["loglik"] - base, 2)}
        for key in ("abstain", "substituted", "unscorable"):
            if s.get(key):
                row[key] = s[key]
        if s["spoken"] != s["text"] and any(ch.isdigit() for ch in s["text"]):
            row["scored_as"] = s["spoken"]
        cands.append(row)
    result = {"draft": draft,
              "draft_peaks": "  ".join(f"{c} {p:.2f}" for c, p in zip(chars, peaks)),
              "reliable": median >= UNRELIABLE_MEDIAN_PEAK,
              "candidates": cands}
    if scored[0]["unscorable"]:
        result["draft_unscorable"] = scored[0]["unscorable"]
    if not result["reliable"]:
        result["warning"] = f"aligner barely hears this span (median peak {median:.2f}); ignore these deltas"
    return result
