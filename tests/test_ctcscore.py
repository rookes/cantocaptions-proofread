"""The numpy CTC scorer, checked against brute force on small cases (no GPU, no torch).
Parity with the pipeline's torch implementation on real emissions is checked by
scripts/compare_score_paths.py, which needs cantocaptions-ai's environment."""
import itertools
import math

import numpy as np

from ccp.ctcscore import Table, ctc_loglik, final_particle_mask, force_align_peaks, strip_final_particles


def _collapse(path, blank):
    out, prev = [], None
    for t in path:
        if t != prev and t != blank:
            out.append(t)
        prev = t
    return out


def _brute(lp, ids, blank):
    T, V = lp.shape
    total = -math.inf
    for path in itertools.product(range(V), repeat=T):
        if _collapse(path, blank) == list(ids):
            total = np.logaddexp(total, sum(lp[t, s] for t, s in enumerate(path)))
    return total


def _random_lp(T, V, seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(T, V))
    return x - np.log(np.exp(x).sum(axis=1, keepdims=True))


def test_ctc_matches_brute_force():
    for seed, ids in enumerate([[1], [1, 2], [2, 2], [1, 2, 1], [3, 3, 1]]):
        lp = _random_lp(6, 4, seed)
        assert math.isclose(ctc_loglik(lp, ids, 0), _brute(lp, ids, 0), rel_tol=1e-9, abs_tol=1e-9)


def test_ctc_impossible_is_minus_inf():
    lp = _random_lp(2, 4, 0)
    assert ctc_loglik(lp, [1, 1, 1], 0) == float("-inf")     # repeats need blanks between: 5 frames
    assert ctc_loglik(lp, [], 0) == float("-inf")


def test_forced_alignment_peaks_follow_the_tokens():
    # Frames clearly say: blank, 1, blank, 2, blank, blank. (The pipeline's trellis scores a
    # held token with the *blank* probability, so one frame per token is the clean case.)
    T, V = 6, 4
    probs = np.full((T, V), 0.02)
    for t, tok in enumerate([0, 1, 0, 2, 0, 0]):
        probs[t, tok] = 0.94
    lp = np.log(probs / probs.sum(axis=1, keepdims=True))
    peaks = force_align_peaks(lp, [1, 2], 0)
    assert peaks is not None and all(p > 0.9 for p in peaks)
    weak = force_align_peaks(lp, [3, 2], 0)                   # token 3 is never heard
    assert weak[0] < 0.05 and weak[1] > 0.9
    assert force_align_peaks(lp[:1], [1, 2], 0) is None       # fewer frames than tokens


def test_text_steps():
    assert strip_final_particles("好嬲喎，你走啦") == "好嬲，你走"
    assert final_particle_mask("係㗎喇") == [False, True, True]
    tb = Table({"blank": 0, "tokens": {"好": [5, ""], "a": [7, ""], "撐": [9, "撐→撐"]},
                "canonical": {"號": "好"}, "unscorable": ["攣"]})
    assert tb.phonetic("號喇") == "好"
    assert tb.ids("好A") == ([5, 7], [], [])
    assert tb.ids("好攣") == ([5], [], ["攣"])
    assert tb.ids("好嬲") == ([5], [], ["嬲"])                 # not in the table: unscorable
