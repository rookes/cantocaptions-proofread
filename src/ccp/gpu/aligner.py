"""The alignment model (alvanlii/wav2vec2-BERT-cantonese) as a forced aligner and an
acoustic scorer. Ported from cantocaptions-ai/experiments/proofread/ctc_scorer.py.

What it can and cannot do (measured in that experiment):
  * It is a CTC character model with no language model, so CTC log P(text | audio) over a
    *fixed* run of frames penalises a dropped word (its frames must then be blank). Good
    for "was this word said at all" and for choosing between candidates that *sound*
    different once the LLM has proposed them from meaning.
  * It cannot tell homophones apart (any preference is training-text habit), so scoring
    canonicalises each character to one representative per Jyutping syllable and abstains
    when candidates differ only that way.
  * It barely hears sentence-final particles, so clause-final particle runs are stripped
    before scoring and particle-only differences abstain.
  * It mishears the same way the ASR does, so it can never veto a mishearing fix.
  * On fast or noisy speech it can be close to deaf (all peaks near 0); results there are
    marked unreliable.

Characters the vocabulary lacks get a token from the pipeline's VocabRepair (variant, then
homophone); when that finds nothing (攣), the same syllable on any tone is used, via this
project's words.hk-derived readings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from _common import DEVICE, SAMPLE_RATE, is_sound  # noqa: E402  (sys.path set by _common)
from ccp import jyutping
from ccp.corpus import FINAL_PARTICLES


def final_particle_mask(text: str) -> list[bool]:
    """Per sound character: is it part of a clause-final particle run?"""
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


@dataclass
class Score:
    text: str
    reading: str
    loglik: float
    substituted: list[str] = field(default_factory=list)
    unscorable: list[str] = field(default_factory=list)
    abstain: str = ""
    spoken: str = ""


class Aligner:
    def __init__(self):
        import torch
        from cantocaptions_ai.pipeline.alignment import _get_blank_id, load_align_model
        self.torch = torch
        self.model, self.meta = load_align_model("yue", DEVICE)
        self.dictionary = self.meta["dictionary"]
        self.repair = self.meta["vocab_repair"]
        self.blank = _get_blank_id(self.dictionary)
        self.model_id = getattr(self.model, "name_or_path", None) or "align-model"
        self._fallback: dict[str, str] = {}

    # -- audio ---------------------------------------------------------------------------
    def emissions(self, clips: list[np.ndarray], batch_size: int = 4):
        """[(emission float32 (T, V) on CPU, frames per second)] for each clip."""
        from cantocaptions_ai.pipeline.alignment import compute_vad_emissions
        segs = [{"start": 0.0, "end": len(c) / SAMPLE_RATE, "audio": c.astype(np.float32)} for c in clips]
        out = compute_vad_emissions(segs, self.model, self.meta["type"], self.meta["processor"], DEVICE,
                                    batch_size=batch_size, vram_checks=False,
                                    primer=self.meta["profile"].primer)
        res = []
        for (em, _rate), c in zip(out, clips):
            em = em.float().cpu()
            res.append((em, em.shape[0] / (len(c) / SAMPLE_RATE)))
        return res

    # -- text ------------------------------------------------------------------------------
    def _near_token(self, ch: str) -> str | None:
        """Same syllable, any tone, among the model's own characters (攣 lyun1 -> 亂 lyun6)."""
        if ch in self._fallback:
            return self._fallback[ch] or None
        r = self.repair
        found = None
        if r.readings is not None:
            if r._near is None:
                r._build_index()
            for reading in jyutping.readings(ch):
                cands = r._near.get(jyutping.toneless(reading)) or []
                if cands:
                    found = cands[0]
                    break
        self._fallback[ch] = found or ""
        return found

    def tokens(self, text: str) -> tuple[list[int], list[int], list[str], list[str]]:
        """(token ids, index into the sound chars of *text* for each id, substitutions, unscorable)."""
        chars = [c.lower() for c in text if is_sound(c)]
        self.repair.augment(["".join(chars)])
        subs = self.repair.substitutions
        ids, where, used, missing = [], [], [], []
        for k, c in enumerate(chars):
            if c in self.dictionary:
                ids.append(self.dictionary[c])
                where.append(k)
                if c in subs:
                    used.append(f"{c}→{subs[c].replacement}")
            else:
                near = self._near_token(c)
                if near and near in self.dictionary:
                    ids.append(self.dictionary[near])
                    where.append(k)
                    used.append(f"{c}→{near} (other tone)")
                else:
                    missing.append(c)
        return ids, where, used, missing

    def canonical(self, ch: str) -> str:
        r = self.repair
        if r.readings is None:
            return ch
        reading = r._reading(ch) or (jyutping.reading(ch))
        if not reading:
            return ch
        if r._exact is None:
            r._build_index()
        cands = r._exact.get(reading)
        return cands[0] if cands else ch

    def export_token_table(self, extra_text: str = "") -> dict:
        """The tokenisation `score` performs, resolved for every character it is likely to
        meet: all of words.hk, every character with a known reading, ASCII letters and digits,
        and *extra_text* (the episode's draft and hypotheses). Lets ccp.ctcscore tokenise
        exactly as this class does without loading the model or the pipeline.

        tokens[c]     = [token id, substitution note or ""] for c lowercased
        canonical[c]  = the homophone representative of c, where it differs from c
        unscorable    = characters with no token even after substitution
        """
        from ccp import dictionary
        chars: set[str] = set(extra_text)
        for s in dictionary.senses():
            chars.update(s.term)
            chars.update(s.altterm)
        chars.update(jyutping._table().keys())
        chars.update("abcdefghijklmnopqrstuvwxyz0123456789")
        chars = {c for c in chars if is_sound(c)}
        tokens, canonical, unscorable = {}, {}, []
        for c in sorted(chars):
            cc = self.canonical(c)
            if cc != c:
                canonical[c] = cc
            for form in {c.lower(), cc.lower()}:
                if form in tokens or form in unscorable:
                    continue
                ids, _, used, missing = self.tokens(form)
                if ids:
                    tokens[form] = [ids[0], used[0] if used else ""]
                else:
                    unscorable.append(form)
        return {"blank": self.blank, "model": self.model_id,
                "tokens": tokens, "canonical": canonical, "unscorable": unscorable}

    # -- forced alignment ------------------------------------------------------------------
    def force_align(self, em, text: str) -> list[dict]:
        """Per sound char of *text*: {char, frames: (first, last) or None, peak}."""
        from cantocaptions_ai.pipeline.alignment import backtrack, get_trellis
        chars = [c for c in text if is_sound(c)]
        out = [{"char": c, "frames": None, "peak": 0.0} for c in chars]
        ids, where, _, _ = self.tokens(text)
        if not ids or em.shape[0] < len(ids):
            return out
        try:
            trellis = get_trellis(em, ids, self.blank)
            path = backtrack(trellis, em, ids, self.blank)
        except Exception:
            return out
        if not path:
            return out
        probs = em.exp()
        for p in path:
            k = where[p.token_index]
            slot = out[k]
            prob = float(probs[p.time_index, ids[p.token_index]])
            slot["peak"] = max(slot["peak"], prob)
            f = slot["frames"]
            slot["frames"] = (p.time_index, p.time_index) if f is None else (min(f[0], p.time_index), max(f[1], p.time_index))
        for slot in out:
            slot["peak"] = round(slot["peak"], 3)
        return out

    # -- scoring ---------------------------------------------------------------------------
    def _loglik(self, em, ids) -> float:
        torch = self.torch
        if not ids:
            return float("-inf")
        lp = em.to(DEVICE)[:, None, :]
        loss = torch.nn.functional.ctc_loss(
            lp, torch.tensor([list(ids)], device=DEVICE), torch.tensor([lp.shape[0]]),
            torch.tensor([len(ids)]), blank=self.blank, reduction="sum", zero_infinity=False)
        val = -float(loss)
        return val if math.isfinite(val) else float("-inf")

    def score(self, em, texts: list[str]) -> list[Score]:
        """texts[0] is the draft; each candidate is scored on sound only (particles stripped,
        homophones canonicalised); a candidate identical to the draft after that abstains."""
        from cantocaptions_ai.languages.yue.numeral_candidates import numeral_readings
        out, base_key = [], None
        for k, text in enumerate(texts):
            best = None
            for reading in numeral_readings(text) or [text]:
                form = strip_final_particles(reading)
                form = "".join(self.canonical(c) if is_sound(c) else c for c in form)
                ids, _, used, missing = self.tokens(form)
                s = Score(text, form, self._loglik(em, ids), used, missing, spoken=reading)
                if best is None or s.loglik > best.loglik:
                    best = s
            key = "".join(c.lower() for c in best.reading if is_sound(c))
            if k == 0:
                base_key = key
            elif key == base_key:
                sounds = lambda t: "".join(c for c in t if is_sound(c))
                plain = sounds(strip_final_particles(text))
                ref = sounds(strip_final_particles(texts[0]))
                if sounds(text) == sounds(texts[0]):
                    best.abstain = "differs only in punctuation"
                elif plain == ref:
                    best.abstain = "differs only in sentence-final particles"
                else:
                    best.abstain = "differs only between homophones"
            out.append(best)
        return out
