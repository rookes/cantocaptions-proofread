"""Review rounds: one proofreading pass over a workspace, with its own report and decisions.

A file can be proofread more than once. Each pass is a round: the records it makes, the report
built from them and the reviewer's decisions on that report. `ccp apply` closes the round (its
decisions have been acted on). The next record then starts a new round:

- the closed round's decisions.json, decisions.previous.json and signals.json are archived as
  decisions.round<N>.json, decisions.previous.round<N>.json and signals.round<N>.json;
- its records stay in flags.jsonl, tagged with their round, and leave the report;
- records nobody has decided yet (still open, never reviewed) move into the new round, so
  nothing waiting for a decision is lost.

While a round is open (not applied yet), another pass adds to it: the same report, with the
decisions the reviewer has already saved.

State: work/<id>/rounds.json. A workspace from before rounds has none: it is one round, closed
when an `apply` ran after its last record was made, or when none of its records still waits
for a decision.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import episode

FILE = "rounds.json"
ARCHIVED = ("decisions.json", "decisions.previous.json", "signals.json")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _local(ts: str) -> datetime | None:
    """A record's `created` (UTC, with offset) or an activity `at` (local, naive), as local naive."""
    try:
        t = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _inferred(episode_id: str) -> dict:
    from . import flags as flagstore
    records = flagstore.load(episode_id)
    made = [t for t in (_local(f.get("created", "")) for f in records) if t]
    applied = [t for t in (_local(a.get("at", "")) for a in episode.read_jsonl(episode_id, "activity.jsonl")
                           if a.get("cmd") == "apply" and a.get("ok")) if t]
    # Applied after its last record; or (older workspaces, before the activity log) nothing in
    # it still waits for a decision, so a fresh round loses nothing.
    settled = all(f["status"] in ("applied", "rejected", "kept") or "review" in f for f in records)
    closed = bool(records) and (bool(made and applied and max(applied) > max(made)) or settled)
    return {"round": 1, "closed": closed, "started": None, "history": []}


def state(episode_id: str) -> dict:
    p = episode.path(episode_id, FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return _inferred(episode_id)


def _save(episode_id: str, s: dict) -> None:
    episode.path(episode_id, FILE).write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def current(episode_id: str) -> int:
    """The round the report shows: the open one, or the last one closed until another starts."""
    return state(episode_id)["round"]


def begin(episode_id: str) -> int:
    """The round a new record belongs to, starting the next one when the current is closed.
    Call it before loading the records: starting a round moves undecided records into it."""
    from . import flags as flagstore
    s = state(episode_id)
    if not s["closed"]:
        if s.get("started") is None:
            s["started"] = _now()
            _save(episode_id, s)
        return s["round"]
    n = s["round"]
    for name in ARCHIVED:
        src = episode.path(episode_id, name)
        if src.exists():
            src.replace(episode.path(episode_id, name.replace(".json", f".round{n}.json")))
    records = flagstore.load(episode_id)
    carried = 0
    for f in records:
        if f["round"] == n and f["status"] == "open" and "review" not in f:
            f["round"] = n + 1
            carried += 1
    flagstore.save(episode_id, records)
    s["history"].append({"round": n, "started": s.get("started"), "closed": s.get("closed_at"),
                         "records": sum(1 for f in records if f["round"] == n),
                         "carried_over": carried})
    s.update(round=n + 1, closed=False, started=_now(), closed_at=None)
    _save(episode_id, s)
    return n + 1


def close(episode_id: str) -> None:
    """Its decisions have been applied: the next record starts a new round."""
    s = state(episode_id)
    s.update(closed=True, closed_at=_now())
    _save(episode_id, s)


def summary(episode_id: str) -> dict:
    s = state(episode_id)
    return {"round": s["round"], "applied": s["closed"],
            "earlier": [{"round": h["round"], "applied": h.get("closed"), "records": h.get("records")}
                        for h in s.get("history", [])]}
