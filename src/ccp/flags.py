"""The agent's findings: work/<episode_id>/flags.jsonl.

One record per suspect cue the agent looked at, whatever it decided:

    grade     fix      confident correction (applied by `ccp apply` when edits were asked for)
              suggest  likely correction; the reviewer decides (`apply --include-suggest`)
              query    something is wrong, no confident fix (alternatives allowed)
              keep     checked and found correct; nothing to change
    reason    required: one or two plain sentences on what is wrong (or why the line stands)
              and why the proposal is right, naming sounds and meaning where they matter
    proposed  the cue's complete new text (⏎ or \\n between lines); fix and suggest only
    evidence  the witnesses, as "source: detail"

Records written before the single grade existed (severity + confidence, note) are migrated on
load; see _migrate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import episode
from .srtio import from_display

CATEGORIES = ["mishearing", "standard", "particle", "punctuation", "name", "missing", "extra",
              "segmentation", "timing", "other"]
GRADES = ["fix", "suggest", "query", "keep"]
STATUSES = ["open", "investigated", "accepted", "rejected", "applied", "kept"]
SOURCES = ["reference", "asr_ft", "asr_qwen", "sounds_like", "dict", "corpus", "ctc", "lint",
           "context", "glossary", "listen"]
FILE = "flags.jsonl"
MIN_REASON = 6          # characters; a reason is a sentence, not a word


def _migrate(f: dict) -> dict:
    """severity + confidence → grade; note → reason."""
    if "grade" not in f:
        sev, conf = f.pop("severity", "suggested"), f.pop("confidence", "medium")
        f["grade"] = ("query" if sev == "query" or conf == "low" or (f.get("proposed") is None
                                                                       and not f.get("proposed_cues"))
                      else "fix" if conf == "high" else "suggest")
    f.pop("severity", None)
    f.pop("confidence", None)
    if f["grade"] == "query" and f.get("proposed") is not None and f.get("status") in ("open", "investigated"):
        # Old queries could carry a proposal; a query now offers candidates as alternatives.
        f["alternatives"] = [f["proposed"]] + [a for a in f.get("alternatives", []) if a != f["proposed"]]
        f["proposed"] = None
    if "reason" not in f:
        f["reason"] = f.pop("note", "") or ""
    f.pop("note", None)
    return f


def load(episode_id: str) -> list[dict]:
    return [_migrate(f) for f in episode.read_jsonl(episode_id, FILE)]


def save(episode_id: str, flags: list[dict]) -> None:
    episode.write_jsonl(episode_id, FILE, flags)


def _parse_evidence(items: list) -> list[dict]:
    out = []
    for it in items or []:
        if isinstance(it, dict):
            src, detail = it.get("source", "context"), it.get("detail", "")
        else:
            src, _, detail = str(it).partition(":")
            src, detail = src.strip(), detail.strip()
            if src not in SOURCES:
                src, detail = "context", str(it)
        if src not in SOURCES:
            raise ValueError(f"evidence source {src!r} not in {SOURCES}")
        out.append({"source": src, "detail": detail})
    return out


def check_reason(reason: str | None, proposed: str | None = None, draft: str | None = None) -> str:
    r = (reason or "").strip()
    if len(r) < MIN_REASON or r in {proposed, draft}:
        raise ValueError(
            "every record needs a reason (--reason / \"reason\"): one or two plain sentences saying what "
            "is wrong, or why the line stands, and why the proposal is right, naming the sounds and the "
            "meaning where they matter. Example: \"係 hai6 is the copula, but the line needs the "
            "location verb 喺 hai2 (R 在那裏): a tone-2/tone-6 mishearing.\"")
    return r


def validate(flag: dict, n_cues: int) -> None:
    if not isinstance(flag.get("cue"), int) or not 1 <= flag["cue"] <= n_cues:
        raise ValueError(f"cue must be a cue position 1..{n_cues}, got {flag.get('cue')!r}")
    for key, allowed in (("category", CATEGORIES), ("grade", GRADES), ("status", STATUSES)):
        if flag.get(key) not in allowed:
            raise ValueError(f"{key} must be one of {allowed}, got {flag.get(key)!r}")
    has_text = flag.get("proposed") is not None
    pc = flag.get("proposed_cues")
    if has_text and flag["proposed"] == flag.get("draft"):
        raise ValueError("proposed text is identical to the draft: record a keep instead")
    if flag["grade"] in ("fix", "suggest") and not (has_text or pc):
        raise ValueError(f"a {flag['grade']} needs a proposed text (or proposed cues); with no "
                         "confident text, record a query")
    if flag["grade"] in ("query", "keep") and (has_text or pc):
        raise ValueError(f"a {flag['grade']} carries no proposed text: use fix or suggest for a "
                         "correction, or put candidate texts in alternatives (query)")
    if pc and has_text:
        raise ValueError("a flag carries a text fix or a timing proposal, not both: apply the text "
                         "fix first, then time the corrected cue")
    if pc is not None:
        if not isinstance(pc, list) or not pc:
            raise ValueError("proposed_cues must be a non-empty list of {start, end, text}")
        last_end = -1.0
        for c in pc:
            if not str(c.get("text", "")).strip():
                raise ValueError("every proposed cue needs text")
            if not float(c["start"]) < float(c["end"]):
                raise ValueError(f"proposed cue {c} ends before it starts")
            if float(c["start"]) < last_end - 1e-6:
                raise ValueError("proposed cues overlap or are out of order")
            last_end = float(c["end"])


def add(episode_id: str, cue: int, category: str, grade: str, proposed: str | None, evidence: list,
        reason: str, related: list[int] = (), alternatives: list[str] = (), replace: bool = False,
        proposed_cues: list[dict] | None = None, extra: dict | None = None) -> dict:
    """*proposed_cues* (a retime or a split: [{start, end, text}]) replaces the cue's timing
    and may turn it into several cues; *proposed* alone changes only its text. A cue whose
    earlier flag was already applied (or kept) can take a new record."""
    ep = episode.load(episode_id)
    srt = episode.srt(ep)
    flags = load(episode_id)
    existing = [f for f in flags if f["cue"] == cue and f["status"] not in ("rejected", "applied", "kept")]
    if existing and not replace:
        raise ValueError(f"cue {cue} already has flag {existing[0]['id']}; use `ccp flag update` "
                         "or pass --replace")
    if existing and replace:
        flags = [f for f in flags if f not in existing]
    c = srt.cue(cue)
    prop = from_display(proposed) if proposed is not None else None
    flag = {
        "id": max([f["id"] for f in load(episode_id)] + [0]) + 1,
        "cue": cue, "related": sorted(set(related)),
        "start": c.start, "end": c.end,
        "draft": c.text,
        "proposed": prop,
        "alternatives": [from_display(a) for a in alternatives],
        "category": category, "grade": grade,
        "reason": check_reason(reason, prop, c.text),
        "evidence": _parse_evidence(evidence),
        "status": "kept" if grade == "keep" else "open",
        **({"proposed_cues": [{"start": round(float(x["start"]), 3), "end": round(float(x["end"]), 3),
                               "text": from_display(str(x["text"]))} for x in proposed_cues]}
           if proposed_cues else {}),
        **(extra or {}),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    validate(flag, len(srt.cues))
    _check_meaning(episode_id, srt, flag)
    flags.append(flag)
    flags.sort(key=lambda f: (f["cue"], f["id"]))
    save(episode_id, flags)
    return flag


def keep(episode_id: str, cue: int, reason: str, evidence: list = (), category: str = "other") -> dict:
    """Record a suspect that was checked and found correct."""
    return add(episode_id, cue, category, "keep", None, list(evidence), reason)


MEANING_CATEGORIES = ("mishearing", "missing", "extra", "other")


def _check_meaning(episode_id: str, srt, flag: dict) -> None:
    """A fix that changes what a line says must be checked against the reference's meaning.
    The recognisers can share a mishearing (唔抵可憐 heard as 唔使可憐 by both, where the
    reference says 不值得可憐), so their agreement alone never decides what was meant.
    Cleanup-pass edits are exempt: they come from reading the reference in the first place."""
    if (flag.get("proposed") is None or flag["grade"] not in ("fix", "suggest")
            or flag["category"] not in MEANING_CATEGORIES or flag.get("pass") == "cleanup"
            or any(e["source"] == "reference" for e in flag["evidence"])):
        return
    from .render import _ref_placement
    refs = _ref_placement(srt.cues, episode.reference_cues(episode_id)).get(flag["cue"])
    if refs:
        raise ValueError(
            f"cue {flag['cue']} has a reference line (R {' / '.join(refs)}). A fix that changes what the "
            "line says must mean what the reference means; the recognisers show how it was said, not "
            "what was meant. Add --evidence \"reference: <how the proposed text's meaning matches R>\". "
            "If it contradicts R and the draft fits R, the draft is probably right: record a keep. If R "
            "belongs to another line or is a loose translation, say so in that evidence line.")


def update(episode_id: str, flag_id: int, **changes) -> dict:
    ep = episode.load(episode_id)
    n = len(episode.srt(ep).cues)
    flags = load(episode_id)
    for f in flags:
        if f["id"] == flag_id:
            for k, v in changes.items():
                if v is None:
                    continue
                if k == "evidence":
                    f["evidence"] = f["evidence"] + _parse_evidence(v)
                elif k == "proposed":
                    f["proposed"] = None if v == "" else from_display(v)
                elif k == "alternatives":
                    f["alternatives"] = [from_display(a) for a in v]
                else:
                    f[k] = v
            if f["grade"] == "keep" and f["status"] == "open":
                f["status"] = "kept"
            f["reason"] = check_reason(f.get("reason"), f.get("proposed"), f["draft"])
            validate(f, n)
            save(episode_id, flags)
            return f
    raise ValueError(f"no flag {flag_id}")


def add_many(episode_id: str, items: list[dict]) -> list[dict]:
    """Batch add from JSON objects with the same keys as `add` (cue, category, grade, proposed,
    evidence, reason, related, alternatives, proposed_cues). "timing": true attaches the
    suggestion `ccp timing` saved for that cue. Valid items are recorded even when others fail;
    the error lists the failures."""
    done, failed = [], []
    for it in items:
        try:
            pc = it.get("proposed_cues")
            if it.get("timing") and not pc:
                pc = saved_timing(episode_id, int(it["cue"]))
            done.append(add(episode_id, int(it["cue"]), it.get("category", "other"), it["grade"],
                            it.get("proposed"), it.get("evidence", []), it.get("reason", ""),
                            it.get("related", []), it.get("alternatives", []),
                            bool(it.get("replace", False)), pc))
        except (ValueError, KeyError) as err:
            failed.append(f"cue {it.get('cue')}: {err if isinstance(err, ValueError) else f'missing {err}'}")
    if failed:
        raise ValueError(f"{len(done)} records added (cues {', '.join(str(f['cue']) for f in done) or 'none'}); "
                         f"{len(failed)} not added. Fix these and add only them again:\n" + "\n".join(failed))
    return done


def saved_timing(episode_id: str, cue: int) -> list[dict]:
    from . import timing
    s = timing.load_saved(episode_id, cue)
    if not s:
        raise ValueError(f"no saved timing suggestion for cue {cue}; run `ccp timing {episode_id} {cue}` first")
    return s["proposed_cues"]


def summary(flags: list[dict]) -> dict:
    out = {"total": len(flags)}
    for key in ("grade", "category", "status"):
        out[key] = {}
        for f in flags:
            out[key][f[key]] = out[key].get(f[key], 0) + 1
    return out


def fmt(f: dict) -> str:
    from .srtio import short_time
    if f.get("proposed_cues"):
        arrow = " → " + " | ".join(f"[{short_time(c['start'])}–{short_time(c['end'])}] {c['text']}"
                                   for c in f["proposed_cues"])
    elif f["grade"] == "keep":
        arrow = " (kept)"
    else:
        arrow = f" → {f['proposed']}" if f.get("proposed") is not None else " (no fix proposed)"
    ev = "; ".join(f"{e['source']}: {e['detail']}" for e in f["evidence"])
    return (f"#{f['id']} cue {f['cue']} [{f['grade']}/{f['category']}/{f['status']}] "
            f"{f['draft']}{arrow}".replace("\n", "⏎")
            + (f"\n    reason: {f['reason']}" if f.get("reason") else "")
            + (f"\n    evidence: {ev}" if ev else ""))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
