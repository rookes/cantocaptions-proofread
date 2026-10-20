"""See and test the convention rules behind `ccp`'s lint (the `L` lines, `ccp clean --lint`).

    uv run python scripts/lint_rules.py --list               # every rule in effect, and where it comes from
    uv run python scripts/lint_rules.py "我地去咗街"           # what lint says about a line (or several)
    uv run python scripts/lint_rules.py --survey 喐 姐係      # what a form's rule does on the strict corpus

Rules live in config/lint.toml (this repo) on top of cantocaptions-dataset's
rules/standardization.toml (read at run time). After editing lint.toml, `--survey` the forms
you touched: a firm rule that fires on correct strict-tier lines needs a `protect` word, or
belongs in `query_variants`. Maintainer tool only: the agent does not use it.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from collections import Counter

from ccp import lint, paths
from ccp.srtio import Cue


def _cue(text: str) -> Cue:
    return Cue(pos=1, number="1", start=0.0, end=1.0, lines=text.replace("⏎", "\n").split("\n"))


def _show(hits: list[dict]) -> str:
    return "; ".join(f"{h['kind']} {h['found']}" + (f"→{h['suggest']}" if h.get("suggest") else "")
                     + (" (query)" if h["severity"] == "query" else "") for h in hits) or "no hits"


def list_rules() -> None:
    cfg = lint.config()
    local = tomllib.loads((paths.CONFIG / "lint.toml").read_text(encoding="utf-8"))
    mine = {v["nonstandard"] for v in local.get("extra_variants", [])}
    rows = {"firm": [], "query": []}
    for v in cfg["variants"]:
        src = "lint.toml" if v["nonstandard"] in mine else "dataset"
        rows["firm" if lint.firm(v) else "query"].append(f"{v['nonstandard']}→{v['standard']} [{src}]")
    print(f"Firm variants ({len(rows['firm'])}; flagged as errors, fixed by `ccp clean --lint`):")
    print("  " + "  ".join(rows["firm"]))
    print(f"Query variants ({len(rows['query'])}; a question for the reviewer, never fixed mechanically):")
    print("  " + "  ".join(rows["query"]))
    print(f"Skipped dataset variants: {' '.join(local.get('skip_variants', [])) or '-'}")
    print("Compound particles [dataset]:")
    print("  " + "  ".join(f"{'/'.join(c['loose'])}→{c['standard']}" for c in cfg["compounds"]))
    print("Particle variants, sentence-final only [dataset]:")
    print("  " + "  ".join(f"{p['nonstandard']}→{p['standard']}" for p in cfg["particle_variants"]))
    print("Standard Written Chinese (query) [lint.toml]:")
    print("  " + "  ".join(f"{s['form']}→{s['cantonese']}" for s in cfg["swc"]))
    print(f"Protected words ({len(cfg['protect'])}): {' '.join(cfg['protect'])}")
    print(f"Spellings folded when comparing recognisers: {' '.join(a + b for a, b in lint.spelling_folds().items())}")
    print(f"Limits: {cfg['limits']}")


def survey(forms: list[str], examples: int) -> None:
    from ccp import corpus
    seen = {f: Counter() for f in forms}
    shown = {f: {} for f in forms}
    for ln in corpus.lines("strict"):
        for f in forms:
            if f not in ln.text:
                continue
            hits = [h for h in lint.check_cue(_cue(ln.text)) if f in h["found"] or h["found"] in f]
            word = lint.occurrences(ln.text, f)[1]
            key = (", ".join(sorted({f"{h['kind']}→{h.get('suggest', '')}"
                                     + (" (query)" if h["severity"] == "query" else "") for h in hits}))
                   or (f"not flagged: inside protected {word}" if word else "not flagged"))
            seen[f][key] += 1
            shown[f].setdefault(key, [])
            if len(shown[f][key]) < examples:
                shown[f][key].append(f"{ln.text.replace(chr(10), '⏎')}  ({ln.episode} #{ln.pos})")
    for f in forms:
        total = sum(seen[f].values())
        print(f"{f}: {total} strict-tier lines contain it")
        for key, n in seen[f].most_common():
            print(f"  {n:>5}  {key}")
            for ex in shown[f][key]:
                print(f"         {ex}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("text", nargs="*", help="lines to lint (⏎ for a line break)")
    ap.add_argument("--list", action="store_true", help="print every rule in effect")
    ap.add_argument("--survey", nargs="+", metavar="FORM", help="run the rules for these forms over the strict corpus")
    ap.add_argument("--examples", type=int, default=3)
    a = ap.parse_args()
    if a.list:
        list_rules()
    if a.survey:
        survey(a.survey, a.examples)
    for t in a.text:
        print(f"{t}: {_show(lint.check_cue(_cue(t)))}")
    if not (a.list or a.survey or a.text):
        ap.print_help()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
