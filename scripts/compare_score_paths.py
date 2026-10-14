"""Check stored-emission scoring against the GPU scorer (needs cantocaptions-ai's env + GPU).

    uv run --project ../cantocaptions-ai --no-sync python scripts/compare_score_paths.py [CASES.json]

For every candidate set in tests/fixtures/score_cases.json (the candidates an agent actually
scored in real sessions), three ways of scoring the same span:

  A  old:    the GPU aligner run on the cue's clip alone (what `ccp score` used to do)
  B  torch:  the GPU scorer's own code on the *stored* group emission, sliced to the span
  C  numpy:  ccp.ctcscore on the same stored slice (what `ccp score` does now)

B vs C is implementation parity: the numpy port must reproduce the torch code on identical
input. A vs C is the change of method (the cue now scored inside its group's context): how
far deltas move, and whether verdicts change at the documented thresholds (> +3 clear
preference; < -6 word not supported; in between: audio does not decide).
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ccp" / "gpu"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import torch  # noqa: E402

import _common  # noqa: E402,F401
from _common import load_media_audio  # noqa: E402
from aligner import Aligner, final_particle_mask  # noqa: E402
from ccp import ctcscore, episode  # noqa: E402
from ccp.groups import listen_span  # noqa: E402


def band(d):
    if d is None:
        return "n/a"
    return "+" if d > 3 else "-" if d < -6 else "0"


def gpu_scores(al, em, draft, cands):
    em = em if isinstance(em, torch.Tensor) else torch.from_numpy(np.asarray(em, dtype=np.float32))
    sc = al.score(em, [draft, *cands])
    base = sc[0].loglik
    deltas = [None if s.loglik == float("-inf") or base == float("-inf") else round(s.loglik - base, 2)
              for s in sc[1:]]
    aln = al.force_align(em, draft)
    mask = final_particle_mask(draft)
    content = [a["peak"] for a, fin in zip(aln, mask) if not fin]
    median = statistics.median(content) if content else 0.0
    return deltas, [s.abstain for s in sc[1:]], median >= 0.1, [a["peak"] for a in aln]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cases = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tests/fixtures/score_cases.json")
                       .read_text(encoding="utf-8"))
    al = Aligner()
    rows, parity, peak_diff, fallbacks = [], [], [], 0
    for eid, by_cue in cases.items():
        if eid.startswith("_"):
            continue
        ep = episode.load(eid)
        srt = episode.srt(ep)
        store = ctcscore.Store(eid)
        audio = load_media_audio(ep["media"], ep.get("audio_track", 0))
        from ccp import flags as flagstore
        # Ground truth: for a fix the reviewer approved and applied, the old draft is wrong
        # and the cue's current text is right.
        approved = {f["cue"]: f["draft"] for f in flagstore.load(eid) if f["status"] == "applied"}
        for cue_s, cand_list in by_cue.items():
            pos = int(cue_s)
            draft = srt.cue(pos).text
            cands = [c for c in cand_list if c != draft]
            if not cands:
                continue
            start, end = listen_span(srt.cues, pos, 0.3)
            # A: clip alone
            clip = audio[int(start * 16000):int(end * 16000)]
            (em_a, _), = al.emissions([clip], batch_size=1)
            a_d, a_abs, a_rel, _ = gpu_scores(al, em_a, draft, cands)
            # B: torch on the stored slice
            sl = store.slice(start, end)
            b_d, b_abs, b_rel, b_peaks = gpu_scores(al, sl, draft, cands)
            # C: numpy
            c = ctcscore.score_item(store, start, end, draft, cands)
            if c is None:
                fallbacks += 1
                print(f"  fallback (GPU path): {eid} cue {pos}")
                continue
            c_d = [x["delta"] for x in c["candidates"]]
            c_peaks = [float(x.split(" ")[1]) for x in c["draft_peaks"].split("  ") if x]
            for b, cc in zip(b_d, c_d):
                if b is not None and cc is not None:
                    parity.append(abs(b - cc))
            peak_diff += [abs(x - y) for x, y in zip(b_peaks, c_peaks)]
            if b_rel != c["reliable"]:
                print(f"  reliability mismatch B/C: {eid} cue {pos}")
            for cand, ad, cd, aab in zip(cands, a_d, c_d, a_abs):
                rows.append({"ep": eid[-7:], "cue": pos, "cand": cand, "A": ad, "C": cd,
                             "abstain": bool(aab), "relA": a_rel, "relC": c["reliable"],
                             "known_wrong": approved.get(pos) == cand})

    print(f"\n== Parity (B torch vs C numpy, identical stored emission)")
    print(f"  candidate deltas compared: {len(parity)};  max |diff| = {max(parity):.4f};  "
          f"mean = {statistics.mean(parity):.4f}")
    print(f"  draft peaks compared: {len(peak_diff)};  max |diff| = {max(peak_diff):.4f}")
    print(f"  items needing the GPU fallback: {fallbacks}")

    scored = [r for r in rows if not r["abstain"] and r["A"] is not None and r["C"] is not None]
    a = np.array([r["A"] for r in scored]); c = np.array([r["C"] for r in scored])
    agree = sum(band(r["A"]) == band(r["C"]) for r in scored)
    print(f"\n== Method (A clip alone vs C stored group slice), {len(scored)} non-abstaining candidates")
    print(f"  correlation of deltas: {np.corrcoef(a, c)[0, 1]:.3f}")
    print(f"  |A - C|: median {np.median(np.abs(a - c)):.2f}, p90 {np.percentile(np.abs(a - c), 90):.2f}, "
          f"max {np.max(np.abs(a - c)):.2f}")
    print(f"  same sign: {sum(np.sign(x) == np.sign(y) for x, y in zip(a, c))}/{len(scored)}")
    print(f"  same verdict band (>+3 / -6..+3 / <-6): {agree}/{len(scored)}")
    rel = [r for r in rows]
    print(f"  reliability verdict agrees: {sum(r['relA'] == r['relC'] for r in rel)}/{len(rel)} "
          f"(unreliable: A {sum(not r['relA'] for r in rel)}, C {sum(not r['relC'] for r in rel)})")
    wrong = [r for r in scored if r["known_wrong"]]
    if wrong:
        aw = np.array([r["A"] for r in wrong]); cw = np.array([r["C"] for r in wrong])
        print(f"\n== Against approved fixes: {len(wrong)} candidates that are the old (wrong) draft of a "
              f"fix the reviewer approved; the right answer is a negative delta")
        for name, v in (("A clip alone", aw), ("C group slice", cw)):
            print(f"  {name:14}: prefers the approved text {int((v < 0).sum())}/{len(v)}, "
                  f"clearly (< -3) {int((v < -3).sum())}, rejects (< -6) {int((v < -6).sum())}, "
                  f"median delta {np.median(v):.2f}")
        for r in wrong:
            print(f"    {r['ep']} cue {r['cue']:>3}  A {r['A']:>7}  C {r['C']:>7}   {r['cand']}")
    print("\n  band changes:")
    for r in scored:
        if band(r["A"]) != band(r["C"]):
            print(f"    {r['ep']} cue {r['cue']:>3}  A {r['A']:>7}  C {r['C']:>7}   {r['cand']}")


if __name__ == "__main__":
    main()
