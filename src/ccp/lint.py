"""Deterministic checks against the CantoCaptions conventions. No model, no audio.

Every hit is a *candidate* flag for the agent, not an edit: some rules are heuristic
(severity "query"), and even the 1:1 variants can be wrong inside a name or a quotation.
"""
from __future__ import annotations

import re
import tomllib
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import dictionary, jyutping, paths
from .corpus import FINAL_PARTICLES
from .srtio import RE_INVISIBLE, Cue, SrtFile, clean_text, invisible_name

SENT_END = "，。？！…,.?!；;：:」』）)"


# A copy of cantocaptions-dataset's rules/standardization.toml, used when the dataset is not on
# this machine. scripts/build_standards.py refreshes it from the dataset.
STANDARDIZATION_SNAPSHOT = paths.CONFIG / "standardization.snapshot.toml"


def standardization_rules() -> Path:
    """The dataset's variant rules if it is here, else the bundled snapshot of them."""
    std_p = paths.get("dataset") / "rules" / "standardization.toml"
    return std_p if std_p.is_file() else STANDARDIZATION_SNAPSHOT


@lru_cache(maxsize=1)
def config() -> dict:
    local = tomllib.loads((paths.CONFIG / "lint.toml").read_text(encoding="utf-8"))
    std_p = standardization_rules()
    std = tomllib.loads(std_p.read_text(encoding="utf-8")) if std_p.is_file() else {}
    skip = set(local.get("skip_variants", []))
    variants = [v for v in std.get("variants", []) if v["nonstandard"] not in skip]
    variants += local.get("extra_variants", [])
    return {"variants": variants, "compounds": std.get("compounds", []),
            "particle_variants": std.get("particle_variants", []),
            "swc": local.get("swc", []), "limits": local.get("limits", {}),
            "protect": local.get("protect", []), "query_variants": set(local.get("query_variants", [])),
            "asr_fold": local.get("asr_fold", {})}


def firm(v: dict) -> bool:
    """A variant rule that is always right (a `standard` hit, fixed by `ccp clean --lint`), as
    opposed to a heuristic or query one that only raises a question."""
    return v.get("confidence") != "heuristic" and v["nonstandard"] not in config()["query_variants"]


def spelling_folds() -> dict[str, str]:
    """Nonstandard -> standard for every firm one-character variant, plus `asr_fold`: what the
    review stream folds before comparing a recogniser with the draft."""
    cfg = config()
    folds = {v["nonstandard"]: v["standard"] for v in cfg["variants"]
             if firm(v) and len(v["nonstandard"]) == 1 and len(v["standard"]) == 1}
    return {**folds, **cfg["asr_fold"]}


def display_width(text: str) -> float:
    w = 0.0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 1
        elif unicodedata.category(ch)[0] not in "MC":
            w += 0.5
    return w


def _hit(cue: Cue, kind: str, found: str, suggest: str | None, severity: str, note: str = "") -> dict:
    row = {"cue": cue.pos, "kind": kind, "found": found, "severity": severity}
    if suggest is not None:
        row["suggest"] = suggest
    if note:
        row["note"] = note
    return row


def _final_positions(text: str, ch: str) -> bool:
    """Is some occurrence of *ch* sentence-final (followed by punctuation or the end)?"""
    for m in re.finditer(re.escape(ch), text):
        nxt = text[m.end():m.end() + 1]
        if nxt == "" or nxt in SENT_END or nxt == "\n":
            return True
    return False


def occurrences(text: str, found: str) -> tuple[list[int], str | None]:
    """Start positions of *found* in *text* that are not part of a protected word (lint.toml
    `protect`), and the first protected word that covered one. 果啲 in 如果啲豬 is 如果 + 啲,
    not the demonstrative 嗰啲, so it must not be "fixed"."""
    spans = [(m.start(), m.end(), m.group()) for w in config()["protect"]
             for m in re.finditer(re.escape(w), text)]
    free, word = [], None
    for m in re.finditer(re.escape(found), text):
        i, j = m.start(), m.end()
        hit = next((w for a, b, w in spans if a < j and i < b and w != found), None)
        if hit:
            word = word or hit
        else:
            free.append(i)
    return free, word


def check_cue(cue: Cue, glossary_avoid: dict[str, str] | None = None) -> list[dict]:
    cfg = config()
    text = cue.text
    raw = cue.raw
    out: list[dict] = []
    for v in cfg["variants"]:
        if v["nonstandard"] in text:
            heuristic = not firm(v)
            free, word = occurrences(text, v["nonstandard"])
            if not free:
                continue                     # only inside protected words (如果啲, 啤啤熊)
            out.append(_hit(cue, "variant", v["nonstandard"], v["standard"],
                            "query" if heuristic else "standard", v.get("note", "")))
    for c in cfg["compounds"]:
        for loose in c["loose"]:
            if loose in text:
                out.append(_hit(cue, "compound_particle", loose, c["standard"], "standard"))
    for pv in cfg["particle_variants"]:
        if pv["nonstandard"] in text and _final_positions(text, pv["nonstandard"]):
            out.append(_hit(cue, "particle_variant", pv["nonstandard"], pv["standard"], "standard",
                            "sentence-final position"))
    for s in cfg["swc"]:
        form = s["form"]
        if form not in text:
            continue
        masked = text
        for ex in s.get("exceptions", []):
            masked = masked.replace(ex, "□" * len(ex))
        if form in masked:
            out.append(_hit(cue, "standard_written_chinese", form, s["cantonese"], "query",
                            "Standard Written Chinese form; check what was said"))
    # punctuation and format
    stripped = text.rstrip()
    if stripped.endswith(("。", ".")) and not stripped.endswith(("...", "..")):
        out.append(_hit(cue, "punctuation", stripped[-1], "", "standard", "cues never end in a period"))
    elif "。" in text:
        out.append(_hit(cue, "punctuation", "。", "，", "standard", "the Chinese period is never used"))
    for bad, good, note in (("……", "…", "only one ellipsis character"), ("...", "…", "use the Chinese ellipsis"),
                            ("·", "", "the middle dot is never used"), ("？？", "？", ""), ("！！", "！", ""),
                            ("“", "「", "curly quotes are not used"), ("”", "」", "curly quotes are not used")):
        if bad in text:
            out.append(_hit(cue, "punctuation", bad, good, "standard", note))
    if re.search(r"[㐀-鿿][,?!:;]|[,?!:;][㐀-鿿]", text):
        out.append(_hit(cue, "punctuation", "ASCII punctuation", "full-width", "standard"))
    if re.search(r"[㐀-鿿] +[㐀-鿿]", text):
        out.append(_hit(cue, "format", "space between Chinese characters", "", "standard"))
    if re.search(r"(^|\n)- ", text):
        out.append(_hit(cue, "format", "'- ' speaker dash with a space", "-", "standard"))
    if re.search(r"</?i>", raw, re.I):
        out.append(_hit(cue, "format", "italics", "", "standard", "italics are never used"))
    for m in RE_INVISIBLE.finditer(raw):
        before = clean_text(raw[:m.start()])[-1:] or "the start"
        out.append(_hit(cue, "invisible", invisible_name(m.group()), "", "standard",
                        f"after {before}: to remove it, propose the text as shown, or run `ccp clean --lint`"))
    width = cfg["limits"].get("line_width", 17.5)
    for line in text.split("\n"):
        if display_width(line) > width:
            out.append(_hit(cue, "line_length", line, None, "query",
                            f"line width {display_width(line):g} > {width:g}"))
    for wrong, right in (glossary_avoid or {}).items():
        if wrong in text:
            out.append(_hit(cue, "glossary", wrong, right, "standard", "per the show glossary"))
    return out


def minority_spellings(cues: list[Cue], sizes=(2, 3, 4)) -> list[dict]:
    """Same sound written two ways in one file (帕克 x7 vs 柏克 x1): flag the minority form
    when it is not itself a dictionary word with a meaning of its own."""
    counts: Counter = Counter()
    where: dict[str, list[int]] = defaultdict(list)
    for c in cues:
        for run in re.findall(r"[㐀-鿿\U00020000-\U0003134f]+", c.text):
            for size in sizes:
                for i in range(len(run) - size + 1):
                    g = run[i:i + size]
                    if g[-1] in FINAL_PARTICLES or g[0] in FINAL_PARTICLES:
                        continue
                    counts[g] += 1
                    where[g].append(c.pos)
    by_sound: dict[str, list[str]] = defaultdict(list)
    for g in counts:
        syl = [jyutping.reading(ch) for ch in g]
        if all(syl):
            by_sound[" ".join(syl)].append(g)
    min_major = config()["limits"].get("minority_min_majority", 2)
    out = []
    for sound, forms in by_sound.items():
        if len(forms) < 2:
            continue
        forms.sort(key=lambda f: -counts[f])
        major = forms[0]
        if counts[major] < min_major:
            continue
        for minor in forms[1:]:
            if counts[minor] * 2 > counts[major]:
                continue
            if dictionary.has_term(minor) and dictionary.has_term(major):
                continue      # two real words that happen to sound alike
            for pos in sorted(set(where[minor])):
                out.append({"cue": pos, "kind": "minority_spelling", "found": minor, "suggest": major,
                            "severity": "query",
                            "note": f"{sound}: {major} x{counts[major]} vs {minor} x{counts[minor]} in this file"})
    # One discrepancy shows up in every overlapping n-gram (萊茵, 茵哈, 萊茵哈...): per cue,
    # keep only the longest forms.
    keep = []
    for r in out:
        if not any(o is not r and o["cue"] == r["cue"] and r["found"] in o["found"] and o["found"] != r["found"]
                   for o in out):
            keep.append(r)
    return keep


def glossary_avoid(show_slug: str | None) -> dict[str, str]:
    """'Avoid' forms from glossaries/<show>.md: table rows `| correct | jyutping | avoid | ... |`
    where avoid lists wrong forms separated by 、 or ,."""
    if not show_slug:
        return {}
    p = paths.get("glossaries") / f"{show_slug}.md"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] and not set(cells[0]) <= set("-: ") and cells[0].lower() != "correct":
            for wrong in re.split(r"[、,，/]", cells[2]):
                wrong = wrong.strip()
                if wrong and wrong != cells[0]:
                    out[wrong] = cells[0]
    return out


def timing_checks(cues: list[Cue]) -> list[dict]:
    """Style-guide timing: a cue of three or more characters lasts at least 0.75 s, and cues
    of the main track never overlap ({an8} background lines may)."""
    out = []
    prev = None
    for c in cues:
        n = sum(1 for ch in c.text if jyutping.is_cjk(ch) or ch.isalnum())
        dur = c.end - c.start
        if n >= 3 and dur < 0.75:
            out.append(_hit(c, "short_duration", f"{dur:.2f} s", None, "query",
                            f"{n} characters in {dur:.2f} s (style guide: at least 0.75 s)"))
        if dur <= 0:
            out.append(_hit(c, "bad_timing", f"{c.start:.3f}-{c.end:.3f}", None, "standard",
                            "the cue ends before it starts"))
        if not c.an8:
            if prev is not None and c.start < prev.end - 0.001:
                out.append(_hit(c, "overlap", f"starts {prev.end - c.start:.2f} s before cue {prev.pos} ends",
                                None, "standard", "main-track cues must not overlap"))
            prev = c
    return out


# Style hints a messy hand-made file needs most (all "query": the agent reads the line).
# Particles that end a clause and are almost never anything else: one followed straight by
# more words (not by 你, which the style guide lets follow without a pause) wants a comma.
CLAUSE_PARTICLES = set("喇啦吖囉囖喎㗎嘛啫咋嘞噃")
NO_COMMA_AFTER = set("你") | CLAUSE_PARTICLES | set(SENT_END) | {"\n", " "}
LEAD_INTERJECTIONS = set("嗱嘩唉咦")          # 嗱，你睇下啦
LONE_INTERJECTIONS = set("吖嗬啊呀哦噢哎唉誒呃嗯吓哈嘿")
MEANINGFUL_ALONE = {"嗯", "吓？", "哦？"}
QUOTED_RUN = 4
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def _inside_term(text: str, k: int) -> bool:
    """Is text[k] part of a dictionary word (無啦啦, 咖喇) rather than a particle on its own?"""
    for lo in range(max(0, k - 2), k + 1):
        for hi in range(k + 1, min(len(text), lo + 4) + 1):
            if hi - lo >= 2 and dictionary.has_term(text[lo:hi]):
                return True
    return False


def style_checks(cues: list[Cue]) -> list[dict]:
    """English casing, commas after particles and openers, lone interjections, and a passage
    read aloud with every line in quotes."""
    out = []
    caps = Counter()
    for c in cues:
        for line in c.text.split("\n"):
            for m in _LATIN_WORD.finditer(line):
                if m.start() > 0 and m.group()[:1].isupper() and not m.group().isupper():
                    caps[m.group()] += 1
    for c in cues:
        text = c.text
        for line in text.split("\n"):
            body = line.lstrip("-")
            for m in _LATIN_WORD.finditer(body):
                w = m.group()
                before = body[:m.start()].rstrip()
                mid = bool(before) and not before.endswith(tuple("。？！?!.「『"))
                # A word the file capitalises mid-line twice or more is taken for a name.
                if (mid and w[:1].isupper() and not w.isupper() and caps[w] < 2
                        and not body[m.end():].startswith(".")):
                    out.append(_hit(c, "latin_case", w, w.lower(), "query",
                                    "English mid-line is lower case unless it is a name or a title"))
                elif len(w) >= 4 and w.isupper() and re.search(r"[AEIOU]", w[1:]):
                    out.append(_hit(c, "latin_case", w, w.capitalize(), "query",
                                    "all capitals: written as a normal word unless it is an acronym"))
            for k, ch in enumerate(body[:-1]):
                nxt = body[k + 1]
                particle = ch in CLAUSE_PARTICLES or (ch in "啊呀" and k > 0 and jyutping.is_cjk(body[k - 1]))
                if (particle and nxt not in NO_COMMA_AFTER and jyutping.is_cjk(nxt)
                        and not _inside_term(body, k)):
                    out.append(_hit(c, "particle_comma", body[max(0, k - 2):k + 2], None, "query",
                                    f"a comma after {ch} before more words? (not before 你)"))
            if len(body) > 1 and body[0] in LEAD_INTERJECTIONS and jyutping.is_cjk(body[1]):
                out.append(_hit(c, "lead_comma", body[:2], f"{body[0]}，{body[1]}", "query",
                                f"a comma after the opening {body[0]}?"))
        bare = text.strip().rstrip("…？！?!，").strip()
        if bare and all(ch in LONE_INTERJECTIONS for ch in bare) and text.strip() not in MEANINGFUL_ALONE:
            out.append(_hit(c, "lone_interjection", text.strip(), None, "query",
                            "an interjection on its own: take it out (ccp clean N|-|reason) or join it to its "
                            "neighbour, unless it means something here (嗯 agreeing, 吓？ asking)"))
    runs, cur = [], []
    for c in cues:
        if c.text.strip().startswith("「") and c.text.strip().endswith("」"):
            cur.append(c)
            continue
        runs.append(cur)
        cur = []
    runs.append(cur)
    for run in runs:
        if len(run) >= QUOTED_RUN:
            for c in run:
                out.append(_hit(c, "quoted_run", "「」", "", "query",
                                f"cues {run[0].pos}-{run[-1].pos} are all in quotes: a passage read aloud "
                                "goes without quotes on every line"))
    return out


def lint_file(path: Path, show_slug: str | None = None) -> list[dict]:
    cues = SrtFile(path).cues
    avoid = glossary_avoid(show_slug)
    rows = [h for c in cues for h in check_cue(c, avoid)]
    rows += minority_spellings(cues)
    rows += timing_checks(cues)
    rows += style_checks(cues)
    rows.sort(key=lambda r: r["cue"])
    return rows
