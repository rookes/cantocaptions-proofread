"""Pass statistics: how a proofread went, for the user.

Built by `ccp report` into work/<id>/stats.json and the report's last section, from what is
already in the workspace:

- signals.json: the lines the tools pointed out (signals.py);
- flags.jsonl: what was recorded on each line, and the reviewer's verdicts once their
  decisions are applied (`review`);
- activity.jsonl: the ccp commands run on the workspace.

They show how much the tools found and how much the agent found on its own, where the two
disagreed (tool hints left alone or checked and kept, changes no tool hinted at), and, after a
review, how many proposed changes the reviewer took as they were.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from . import episode, flags as flagstore, signals

CHANGE_GRADES = ("fix", "suggest")
LOOKUPS = {"listen": "re-listens", "score": "audio checks", "dict": "dictionary lookups",
           "sounds-like": "sound-alike searches", "corpus": "corpus searches", "cue": "close looks at lines"}


def _pct(a: int, b: int) -> str:
    return f"{round(100 * a / b)}%" if b else "–"


def is_change(f: dict) -> bool:
    """A record that proposes (or made) a new text or timing."""
    return f["grade"] in CHANGE_GRADES and (f.get("proposed") is not None or bool(f.get("proposed_cues")))


def found_by(f: dict, sig: dict[int, dict]) -> list[str]:
    """The tool signals the record's line carried ([] = the agent found it alone)."""
    return list(sig.get(f["cue"], {}).get("kinds", []))


def compute(episode_id: str) -> dict:
    ep = episode.load(episode_id)
    n_cues = len(episode.srt(ep).cues) if ep.get("srt") else 0
    sig = signals.snapshot(episode_id)
    records = flagstore.load(episode_id)
    by_cue: dict[int, list[dict]] = {}
    for f in records:
        by_cue.setdefault(f["cue"], []).append(f)

    tool_cues = {pos for pos, v in sig.items() if v["kinds"]}
    kinds = {}
    for k in signals.KINDS:
        shown = {pos for pos in tool_cues if k in sig[pos]["kinds"]}
        recorded = {pos for pos in shown if pos in by_cue}
        changed = {pos for pos in recorded if any(is_change(f) for f in by_cue[pos])}
        kinds[k] = {"shown": len(shown), "in_report": len(recorded), "changed": len(changed),
                    "kept": len({p for p in recorded - changed if all(f["grade"] == "keep" for f in by_cue[p])})}
    recorded_tool = {pos for pos in tool_cues if pos in by_cue}
    changed_tool = {pos for pos in recorded_tool if any(is_change(f) for f in by_cue[pos])}
    kept_tool = {pos for pos in recorded_tool - changed_tool
                 if all(f["grade"] == "keep" for f in by_cue[pos])}

    agent_records = [f for f in records if not found_by(f, sig)]
    grades = Counter(f["grade"] for f in records if f.get("pass") != "cleanup")
    cleanup = [f for f in records if f.get("pass") == "cleanup"]
    mechanical = [f for f in cleanup if any(str(e.get("source")) == "lint" for e in f.get("evidence", []))]
    review = Counter(f["review"] for f in records if f.get("review"))
    proposals = [f for f in records if is_change(f)]

    activity = episode.read_jsonl(episode_id, "activity.jsonl")
    cmds = Counter(a["cmd"] for a in activity)
    minutes = None
    if len(activity) > 1:
        t = [datetime.fromisoformat(a["at"]) for a in activity]
        minutes = round((max(t) - min(t)).total_seconds() / 60)

    out = {
        "lines": n_cues,
        "tool_hints": {"lines": len(tool_cues), "by_kind": kinds,
                       "in_report": len(recorded_tool), "changed": len(changed_tool),
                       "checked_and_kept": len(kept_tool),
                       "left_alone": len(tool_cues) - len(recorded_tool)},
        "records": {"total": len(records), "by_grade": dict(grades), "cleanup_edits": len(cleanup),
                    "cleanup_mechanical": len(mechanical)},
        "found_by_agent_alone": {"records": len(agent_records),
                                 "changes": sum(1 for f in agent_records if is_change(f))},
        "found_by_tools": {"records": len(records) - len(agent_records)},
        "review": dict(review) if review else None,
        "proposed_changes": len(proposals),
        "activity": {"commands": len(activity), "minutes": minutes,
                     **{name: cmds.get(cmd, 0) for cmd, name in LOOKUPS.items()}},
    }
    out["summary"] = summary_lines(out)
    return out


def summary_lines(s: dict) -> list[str]:
    """The statistics as a few plain sentences."""
    th, rec = s["tool_hints"], s["records"]
    names = {k: v[0].lower() for k, v in signals.KINDS.items()}
    parts = [f"{v['shown']} {names[k]}" for k, v in th["by_kind"].items() if v["shown"]]
    lines = [f"The tools pointed out {th['lines']} of {s['lines']} lines ({_pct(th['lines'], s['lines'])})"
             + (f": {', '.join(parts)}." if parts else ".")]
    if th["lines"]:
        lines.append(f"{th['in_report']} of those ({_pct(th['in_report'], th['lines'])}) are in the report: "
                     f"{th['changed']} changed, {th['checked_and_kept']} checked and kept. "
                     f"{th['left_alone']} were left alone.")
    alone = s["found_by_agent_alone"]
    if rec["total"]:
        lines.append(f"{alone['records']} of the {rec['total']} records ({_pct(alone['records'], rec['total'])}) "
                     f"are on lines no tool pointed out: the agent found them on its own "
                     f"({alone['changes']} of them propose a change).")
    if rec["cleanup_edits"]:
        lines.append(f"The cleanup pass made {rec['cleanup_edits']} edits, {rec['cleanup_mechanical']} of them "
                     "mechanical convention fixes.")
    act = s["activity"]
    looked = [f"{act[name]} {name}" for name in LOOKUPS.values() if act.get(name)]
    if looked or act["minutes"]:
        lines.append("The agent ran " + (", ".join(looked) if looked else "no lookups")
                     + (f", over {act['minutes']} minutes" if act["minutes"] else "") + ".")
    rv = s["review"]
    if rv:
        took = rv.get("accepted", 0)
        reviewed = took + rv.get("edited", 0) + rv.get("rejected", 0)
        lines.append(f"In review: {took} of {reviewed} decided changes accepted as proposed "
                     f"({_pct(took, reviewed)}), {rv.get('edited', 0)} reworded, {rv.get('rejected', 0)} turned down"
                     + (f"; {rv['corrected']} kept lines corrected by the reviewer" if rv.get("corrected") else "")
                     + ".")
    return lines


def save(episode_id: str, stats: dict) -> None:
    episode.path(episode_id, "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
