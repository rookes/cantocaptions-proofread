"""ccp clean: the text-only cleanup pass for machine-made or very messy drafts.

The agent reads the draft (with the reference and lint lines from `ccp render`) and writes
down the edits it is sure of, one line per cue:

    12|艾倫，快啲走|name: the reference and the glossary write 艾倫; 愛倫 is a mishearing
    40|佢實囉囉攣|食多都亂 makes no sense; R 一定坐立不安 = 實 + 囉囉攣 (sat6 lo1 lo1 lyun1)
    57|?|meaning unclear: R says 他已經走了 but nothing in the draft sounds like it

The third field, the reason, is required: why the line is wrong and why the new text is
right. It may start with a category (`name:`, `standard:`, `punctuation:` …). A line without a
reason is held back and reported, not applied.

`⏎` is a line break inside a cue. Blank lines and lines starting with # are ignored.

Sentence-final particles are never changed here: where an edit changes, adds or drops one,
the draft's particle is put back and the rest of the edit applies (keep_particles).

Each edit becomes a flag (grade fix, pass "cleanup") and is applied
to the working draft at once, so the record, the report and `ccp apply --decisions`
(reject = undo) work as for any other correction. --lint adds the mechanical lint fixes
(spelling variants outside protected words, glossary forms, punctuation) to every cue,
merged with the agent's own edit for that cue.
"""
from __future__ import annotations

import difflib
import re
import time
from pathlib import Path

from . import apply as applier, episode, flags as flagstore, lint
from .particles import BOUNDARY, final_mask as _final_mask
from .srtio import invisible_name

PUNCT = set("，。？！…,.?!；;：:、「」『』（）()\"'“”‘’-— \n")
# Particle-character rules (compound_particle, particle_variant) are left to the agent: they
# also match real words (出嫁 → 出㗎, 啊可惜 → 啊嗬惜), so each needs a reading of the line.
LINT_KINDS = ("variant", "glossary", "punctuation")


def parse(lines: list[str]) -> list[dict]:
    out, seen = [], set()
    for raw in lines:
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) < 2 or not parts[0].strip().isdigit():
            raise ValueError(f"not an edit line (N|new text|reason): {line!r}")
        cue, text = int(parts[0].strip()), parts[1].strip()
        why = parts[2].strip() if len(parts) > 2 else ""
        if not text:
            raise ValueError(f"cue {cue}: empty text (deleting a cue is not a cleanup edit; flag it instead)")
        if cue in seen:
            raise ValueError(f"cue {cue} appears twice; give one full text per cue")
        seen.add(cue)
        category = None
        head, sep, rest = why.partition(":")
        if sep and head.strip() in flagstore.CATEGORIES:
            category, why = head.strip(), rest.strip()
        out.append({"cue": cue, "text": None if text == "?" else text, "why": why, "category": category})
    return out



def _split_tail(seg: str) -> tuple[str, str]:
    k = len(seg)
    while k and seg[k - 1] in BOUNDARY:
        k -= 1
    return seg[:k], seg[k:]


def _run(seg: str, mask: list[bool], end: int) -> int:
    """Length of the clause-final particle run at the end of *seg*, which ends at *end*."""
    n = 0
    while n < len(seg) and mask[end - 1 - n]:
        n += 1
    return n


def keep_particles(old: str, new: str) -> tuple[str, list[str], list[str]]:
    """*new* with the draft's clause-final particles put back wherever the edit changed,
    added or dropped one; returns (text, kept, as_words). Other changes in the same edit
    stand: 孭得𠸏 → 孭得起嘅 becomes 孭得起𠸏. The cleanup pass does not judge particles.

    One exception: a particle character the edit turns into a plain word (爛嘅 → 爛gag,
    唔啱咯 → 唔啱路) was a mishearing of a word, not a particle choice. It is applied and
    listed in *as_words*."""
    fa, fb = _final_mask(old), _final_mask(new)
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    out, kept, as_words = [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        a_seg, b_seg = old[i1:i2], new[j1:j2]
        if op == "equal" or not a_seg:
            out.append(b_seg)            # unchanged, or new words inserted
            continue
        a_main, _ = _split_tail(a_seg)
        b_main, b_tail = _split_tail(b_seg)
        na = _run(a_main, fa, i1 + len(a_main))
        nb = _run(b_main, fb, j1 + len(b_main))
        da, db = a_main[len(a_main) - na:], b_main[len(b_main) - nb:]
        a_core, b_core = a_main[:len(a_main) - na], b_main[:len(b_main) - nb]
        if da == db or (a_core and not b_main):
            out.append(b_seg)            # no particle change, or a phrase deleted outright
        elif da and not db and b_core:
            # The edit puts words, and no particle, where the particle was: either the
            # "particle" was a misheard word (爛嘅 → 爛gag) or the whole phrase was reheard
            # (快啲啊，公主 → 雅典娜公主). Not a particle choice: applied, and listed.
            out.append(b_seg)
            as_words.append(f"{a_main}→{b_main}")
        else:
            out.append(b_core + da + b_tail)
            kept.append(f"{da or '∅'} (the edit had {db or '∅'})")
    return "".join(out), kept, as_words


def _final_only(text: str, found: str, suggest: str) -> str:
    return re.sub(re.escape(found) + r"(?=$|[" + re.escape(lint.SENT_END) + r"\n])", suggest, text)


def lint_fix(text: str, row: dict) -> str:
    """The mechanical fix for one lint hit, or the text unchanged when it has none."""
    kind, found, sug = row["kind"], row["found"], row.get("suggest")
    if kind not in LINT_KINDS or row.get("severity") != "standard" or sug is None:
        return text
    if kind == "punctuation":
        stripped = text.rstrip()
        if found in ("。", ".") and sug == "" and stripped.endswith(found):
            # An ASCII full stop after Latin letters may close an abbreviation (O.I.S.).
            if found == "." and len(stripped) > 1 and stripped[-2].isascii():
                return text
            return stripped[:-1]
        if not sug or found not in text or found == "ASCII punctuation":
            return text
        if found == "。":
            return text.replace("。", "，")
        return text.replace(found, sug)
    if found not in text or not sug:
        return text
    if kind == "particle_variant":
        return _final_only(text, found, sug)
    if kind == "variant":                    # never inside a protected word (如果啲)
        for i in reversed(lint.occurrences(text, found)[0]):
            text = text[:i] + sug + text[i + len(found):]
        return text
    return text.replace(found, sug)


def _lint_pass(text: str, cue, avoid: dict) -> tuple[str, list[str]]:
    """Apply every mechanical lint fix to *text*; returns the new text and what was fixed."""
    done = []
    for _ in range(3):                       # one fix can expose another (。。 → 。 → end)
        rows = lint.check_cue(_TextCue(cue, text), avoid)
        changed = False
        for r in rows:
            new = lint_fix(text, r)
            if new != text:
                done.append(f"{r['kind']} {r['found']}→{r.get('suggest') or '(removed)'}")
                text, changed = new, True
        if not changed:
            break
    return text, done


class _TextCue:
    """A stand-in cue with replaced text, for lint.check_cue."""

    def __init__(self, cue, text: str):
        self._cue, self.text = cue, text
        self.raw = text
        self.pos = cue.pos

    def __getattr__(self, name):
        return getattr(self._cue, name)


def _category(old: str, new: str, lint_only: str) -> str:
    strip = lambda s: "".join(ch for ch in s if ch not in PUNCT)
    if strip(old) == strip(new):
        return "punctuation"
    if new == lint_only:
        return "standard"
    return "mishearing"


def clean(episode_id: str, edits: list[dict], use_lint: bool = False, skip_lint: list[int] = (),
          dry_run: bool = False, no_apply: bool = False) -> dict:
    ep = episode.load(episode_id)
    srt = episode.srt(ep)
    n = len(srt.cues)
    for e in edits:
        if not 1 <= e["cue"] <= n:
            raise ValueError(f"cue {e['cue']} is out of range 1..{n}")
    avoid = lint.glossary_avoid(ep.get("show_slug"))
    by_cue = {e["cue"]: e for e in edits}
    lint_cues = set()
    if use_lint:
        for c in srt.cues:
            if c.pos in skip_lint:
                continue
            fixed, _ = _lint_pass(c.text, c, avoid)
            if fixed != c.text or c.invisible:
                lint_cues.add(c.pos)
    planned, queries, particles, particle_words, held = [], [], [], [], []
    for pos in sorted(set(by_cue) | lint_cues):
        c = srt.cue(pos)
        e = by_cue.get(pos)
        if e and len(e["why"].strip()) < flagstore.MIN_REASON:
            held.append(e["cue"])
            e = None                 # no reason: the agent's edit waits; lint fixes may still apply
            if pos not in lint_cues:
                continue
        if e and e["text"] is None:
            queries.append(e)
            continue
        agent_text = e["text"].replace("⏎", "\n") if e else c.text
        agent_text, kept, as_words = keep_particles(c.text, agent_text)
        if kept:
            particles.append(f"cue {pos}: kept " + "; ".join(kept))
        if as_words:
            particle_words.append(f"cue {pos}: " + "; ".join(as_words))
        text, fixes = (_lint_pass(agent_text, c, avoid) if use_lint and pos not in skip_lint
                       else (agent_text, []))
        if use_lint and pos not in skip_lint and c.invisible:
            fixes = fixes + [f"invisible {invisible_name(ch)} removed" for ch in c.invisible]
        elif text == c.text:
            continue
        lint_only = _lint_pass(c.text, c, avoid)[0]
        category = (e or {}).get("category") or ("standard" if text == c.text
                                                  else _category(c.text, text, lint_only))
        evidence = [e["why"]] if e and e["why"].split(":", 1)[0].strip() in flagstore.SOURCES else []
        evidence += [f"lint: {x}" for x in fixes]
        reason = e["why"] if e else "convention: " + "; ".join(fixes)
        planned.append({"cue": pos, "from": c.text, "to": text, "category": category,
                        "reason": reason, "evidence": evidence})
    result = {"episode_id": episode_id, "edits": len(planned), "queries": len(queries),
              "lint_fixed_cues": len([p for p in planned if any(x.startswith("lint:") for x in p["evidence"])])}
    if held:
        result["held_back"] = {"cues": held, "why": "these edit lines have no reason (N|text|reason): "
                               "add one sentence on why the line is wrong and the new text right, then "
                               "submit them again"}
    if particles:
        result["particles_kept"] = particles
        result["particles_note"] = ("the cleanup pass never changes sentence-final particles, so the draft's "
                                    "were kept and the rest of each edit applied. If a particle really is "
                                    "wrong, record a query (`N|?|particle: ...`) for the reviewer.")
    if particle_words:
        result["particles_read_as_words"] = particle_words
        result["particle_words_note"] = ("applied: a particle character replaced by a plain word is a "
                                         "mishearing of a word. Check these are not particle choices.")
    if dry_run:
        result["dry_run"] = True
        result["planned"] = [f"cue {p['cue']} [{p['category']}] {p['from']} → {p['to']}".replace("\n", "⏎")
                             for p in planned]
        return result
    made, skipped = [], []
    for p in planned:
        try:
            f = flagstore.add(episode_id, p["cue"], p["category"], "fix", p["to"], p["evidence"],
                              p["reason"], extra={"pass": "cleanup"})
            made.append(f["id"])
        except ValueError as err:
            skipped.append({"cue": p["cue"], "reason": str(err)})
    for q in queries:
        try:
            flagstore.add(episode_id, q["cue"], q["category"] or "other", "query", None, [], q["why"],
                          extra={"pass": "cleanup"})
        except ValueError as err:
            skipped.append({"cue": q["cue"], "reason": str(err)})
    by_cat: dict[str, int] = {}
    for p in planned:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    result["by_category"] = by_cat
    if skipped:
        result["skipped"] = skipped
    if no_apply:
        result["recorded_only"] = "flags recorded, nothing applied (apply with `ccp apply <id>`)"
        return result
    res = applier.apply(episode_id, only=made)
    result["applied"] = len(res["applied"])
    result["edited"] = res["edited"]
    result["file"] = res["file"]
    if res["skipped"]:
        result.setdefault("skipped", []).extend(res["skipped"])
    if res.get("new_lint_warnings"):
        result["new_lint_warnings"] = res["new_lint_warnings"]
    # Recorded in episode.json too: a later realign moves the flags to previous/.
    ep = episode.load(episode_id)
    done = ep.get("cleanup") or {"edits": 0, "queries": 0}
    ep["cleanup"] = {"edits": done["edits"] + len(res["applied"]), "queries": done["queries"] + len(queries),
                     "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    episode.save(ep)
    rows = lint.lint_file(Path(ep["srt"]), ep.get("show_slug"))
    left: dict[str, int] = {}
    for r in rows:
        left[r["kind"]] = left.get(r["kind"], 0) + 1
    result["lint_remaining"] = left
    return result
