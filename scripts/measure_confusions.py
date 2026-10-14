"""Measure how speech is misheard, in Jyutping terms, to calibrate config/confusions.toml.

    uv run python scripts/measure_confusions.py [EPISODE_ID ...] [--markdown]

For every workspace with `evidence.jsonl` whose subtitle is strict-tier (so the subtitle is
close to the truth), each recogniser's per-cue text is aligned to the subtitle character by
character. Every same-length substitution of a CJK character is a "mishearing" of one
syllable; for each, the pair of readings that sounds closest is taken (a character with
several readings is given the benefit of the doubt), and the initial, final and tone changes
are tallied.

What this measures is how *the recognisers* mishear, which is a proxy for how human
transcribers mishear: both confuse sounds that are acoustically close. Homophone
substitutions (same syllable and tone, different character) are counted separately; they
are spelling, not hearing. Spelling a recogniser does not distinguish (stock Qwen writes 咁
for both gam2 and gam3) is folded first, exactly as `ccp render` does.

The output is evidence for editing config/confusions.toml by hand. Nothing is rewritten.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ccp import episode, jyutping, paths, sound  # noqa: E402
from ccp.corpus import FINAL_PARTICLES  # noqa: E402
from ccp.render import FOLDS  # noqa: E402
from ccp.srtio import SrtFile  # noqa: E402


def cjk(text: str) -> str:
    return "".join(c for c in text if jyutping.is_cjk(c))


def closest_pair(a: str, b: str) -> tuple[str, str] | None:
    ra, rb = jyutping.readings(a), jyutping.readings(b)
    if not ra or not rb:
        return None
    return min(((x, y) for x in ra[:4] for y in rb[:4]), key=lambda p: sound.syllable_cost(*p))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes", nargs="*")
    ap.add_argument("--markdown", action="store_true", help="print tables for sound-alikes.md")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    work = paths.get("work")
    ids = args.episodes or sorted(p.name for p in work.iterdir() if (p / "evidence.jsonl").exists())

    init, final, tone, whole = Counter(), Counter(), Counter(), Counter()
    homophones = Counter()
    subs = same = 0
    used = []
    for eid in ids:
        ep = json.loads((work / eid / "episode.json").read_text(encoding="utf-8"))
        if ep.get("tier") != "strict":
            continue
        used.append(eid)
        cues = {c.pos: c for c in SrtFile(Path(ep["srt"])).cues}
        for row in episode.read_jsonl(eid, "evidence.jsonl"):
            for tag, hyp in row.get("asr", {}).items():
                # Same per-model spelling folds as the review stream: stock Qwen's 咁 for 噉
                # is its spelling habit, not a gam2/gam3 mishearing.
                fold = FOLDS.get(tag, FOLDS["ft"])
                truth = cjk(cues[row["cue"]].text.translate(fold))
                h = cjk(hyp.get("text", "").translate(fold))
                sm = difflib.SequenceMatcher(a=truth, b=h, autojunk=False)
                for op, i1, i2, j1, j2 in sm.get_opcodes():
                    if op == "equal":
                        same += i2 - i1
                    if op != "replace" or (i2 - i1) != (j2 - j1):
                        continue
                    for a, b in zip(truth[i1:i2], h[j1:j2]):
                        if a in FINAL_PARTICLES or b in FINAL_PARTICLES:
                            continue
                        pair = closest_pair(a, b)
                        if pair is None:
                            continue
                        x, y = pair
                        if x == y:
                            homophones[(a, b)] += 1
                            continue
                        subs += 1
                        ia, fa, ta = sound.split(x)
                        ib, fb, tb = sound.split(y)
                        whole[(f"{a} {x}", f"{b} {y}")] += 1
                        if ia != ib:
                            init[tuple(sorted((ia or "∅", ib or "∅")))] += 1
                        if fa != fb:
                            final[tuple(sorted((fa, fb)))] += 1
                        if ta != tb:
                            tone[tuple(sorted((ta, tb)))] += 1

    def table(title, counter, n):
        rows = counter.most_common(n)
        if args.markdown:
            # One compact line per list (pair count · pair count …): what sound-alikes.md holds.
            print(f"\n**{title}** ({sum(counter.values())} changes)\n")
            print(" · ".join(f"{' ↔ '.join(k)} {v}" for k, v in rows))
        else:
            print(f"\n{title} ({sum(counter.values())} changes)")
            for k, v in rows:
                print(f"  {' <-> '.join(k):<18} {v}")

    print(f"episodes: {', '.join(used) or 'none (need strict-tier workspaces with evidence)'}")
    print(f"characters matched: {same}; one-syllable mishearings: {subs}; homophone swaps: {sum(homophones.values())}")
    table("Initials", init, args.top)
    table("Finals", final, args.top)
    table("Tones", tone, args.top)
    table("Most common syllable mishearings (truth, heard)", whole, args.top)
    table("Homophone swaps (spelling, not hearing)", Counter({(a, b): v for (a, b), v in homophones.items()}), 15)


if __name__ == "__main__":
    main()
