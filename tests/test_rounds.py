"""Review rounds: a pass after an applied review starts a fresh report; an unapplied one adds to it."""
import json

from ccp import apply, episode, flags, rounds

FIX = ("standard", "fix", "你畀我啦", ["lint: 俾"], "convention: 俾 → 畀 (variant)")


def _decide(ws, *decisions):
    (ws["work"] / "decisions.json").write_text(json.dumps({"decisions": list(decisions)}), encoding="utf-8")


def test_a_pass_on_an_open_round_adds_to_it(workspace):
    eid = workspace["id"]
    a = flags.add(eid, 1, *FIX)
    _decide(workspace, {"flag": a["id"], "decision": "accepted", "text": "你畀我啦"})
    b = flags.keep(eid, 3, "both lines are said as written; the reference agrees")
    assert a["round"] == b["round"] == 1
    assert [f["id"] for f in flags.in_round(eid)] == [a["id"], b["id"]]
    assert (workspace["work"] / "decisions.json").exists()        # the reviewer's choices stay


def test_a_pass_after_apply_starts_a_fresh_round(workspace):
    eid = workspace["id"]
    done = flags.add(eid, 1, *FIX)
    waiting = flags.add(eid, 4, "particle", "query", None, [], "R states, the draft asks",
                        alternatives=["一定得㗎喇"])
    kept = flags.keep(eid, 3, "both lines are said as written; the reference agrees")
    _decide(workspace, {"flag": done["id"], "decision": "accepted", "text": "你畀我啦"})
    apply.apply(eid, workspace["work"] / "decisions.json")
    rounds.close(eid)                                             # what `ccp apply` does

    assert rounds.summary(eid)["applied"]
    assert len(flags.in_round(eid)) == 3                          # the report still shows round 1

    new = flags.add(eid, 2, "mishearing", "suggest", "阿媽實囉囉攣瞓唔着㗎", ["reference: test"],
                    "食多都亂 makes no sense; 實囉囉攣 keeps the tones")
    assert new["round"] == 2
    ids = {f["id"] for f in flags.in_round(eid)}
    assert ids == {new["id"], waiting["id"]}                      # the undecided query comes along
    assert done["id"] not in ids and kept["id"] not in ids
    assert not (workspace["work"] / "decisions.json").exists()
    assert (workspace["work"] / "decisions.round1.json").exists()
    s = rounds.state(eid)
    assert s["history"][0]["round"] == 1 and s["history"][0]["carried_over"] == 1
    # Round 1's decisions no longer act: a stale page's decision is ignored.
    _decide(workspace, {"flag": done["id"], "decision": "rejected"})
    assert apply.select(eid, workspace["work"] / "decisions.json", False, [], False) == []


def test_a_workspace_from_before_rounds_is_inferred(workspace):
    eid = workspace["id"]
    flags.add(eid, 1, *FIX)
    episode.path(eid, rounds.FILE).unlink()
    assert not rounds.state(eid)["closed"]
    (workspace["work"] / "activity.jsonl").write_text(
        json.dumps({"at": "2999-01-01T00:00:00", "cmd": "apply", "ok": True}) + "\n", encoding="utf-8")
    assert rounds.state(eid)["closed"]                            # applied after its last record


def test_an_older_workspace_with_everything_decided_is_finished(workspace):
    eid = workspace["id"]
    flags.keep(eid, 3, "both lines are said as written; the reference agrees")
    episode.path(eid, rounds.FILE).unlink()
    assert rounds.state(eid)["closed"]
