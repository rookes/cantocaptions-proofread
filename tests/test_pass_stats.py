"""Where the lines in a report came from (signals.py), the pass statistics (stats.py), and the
report's plain wording (report.plain)."""
import json

import pytest

from ccp import apply, clean, cli, episode, flags, report, signals, stats

REASON = "the reference says so, and the line makes no sense as written"


def _evidence(workspace, rows):
    (workspace["work"] / "evidence.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def test_signals_mark_what_the_tools_pointed_out(workspace):
    _evidence(workspace, [
        {"cue": 2, "asr": {"ft": {"text": "阿媽實囉囉攣瞓唔着㗎"}, "qw": {"text": "阿媽食攞攞攣瞓唔著嘅"}},
         "peaks": [["多", 0.01, False], ["都", 0.02, False]]},
        {"cue": 4, "asr": {"ft": {"text": "一定得嘅喇"}}, "peaks": [["定", 0.01, False]]},
    ])
    now = signals.current(workspace["id"])
    assert now[1]["kinds"] == ["lint"]                  # 俾 -> 畀
    assert now[2]["kinds"] == ["asr", "weak"]
    assert now[3]["kinds"] == []
    # Cue 4's recogniser differs only in a particle: no hint, and its weak character is not shown.
    assert now[4]["kinds"] == []


def test_a_fixed_line_keeps_the_hint_it_had(workspace):
    signals.snapshot(workspace["id"])
    clean.clean(workspace["id"], [], use_lint=True)      # fixes 俾 -> 畀 on cue 1
    assert signals.current(workspace["id"])[1]["kinds"] == []
    assert signals.snapshot(workspace["id"])[1]["kinds"] == ["lint"]


def test_statistics_split_tool_hints_from_the_agents_own_finds(workspace):
    _evidence(workspace, [{"cue": 2, "asr": {"ft": {"text": "阿媽實囉囉攣瞓唔着㗎"}}, "peaks": []}])
    signals.snapshot(workspace["id"])
    flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], REASON)
    flags.add(workspace["id"], 3, "punctuation", "suggest", "-走喇！⏎-等埋我啊", [], "an exclamation, not a statement")
    s = stats.compute(workspace["id"])
    th = s["tool_hints"]
    assert th["lines"] == 2 and th["in_report"] == 1 and th["changed"] == 1 and th["left_alone"] == 1
    assert th["by_kind"]["lint"] == {"shown": 1, "in_report": 0, "changed": 0, "kept": 0}
    assert s["found_by_agent_alone"] == {"records": 1, "changes": 1}
    assert any("on lines no tool pointed out" in line for line in s["summary"])
    assert not any("eval" in line.lower() for line in s["summary"])


def test_reviewer_verdicts_are_counted(workspace, tmp_path):
    f1 = flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], REASON)
    f2 = flags.add(workspace["id"], 3, "punctuation", "suggest", "-走喇！⏎-等埋我啊", [], "an exclamation, not a statement")
    f3 = flags.add(workspace["id"], 4, "particle", "suggest", "一定得嘅喇", [], "a promise, not a question here")
    k = flags.keep(workspace["id"], 1, "the line means what the reference means")
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({"decisions": [
        {"flag": f1["id"], "decision": "accepted", "text": "阿媽實囉囉攣瞓唔着㗎"},
        {"flag": f2["id"], "decision": "accepted", "text": "-走喇！⏎-等埋我呀"},
        {"flag": f3["id"], "decision": "rejected"},
        {"flag": k["id"], "decision": "accepted", "text": "你畀我啦"}]}, ensure_ascii=False), encoding="utf-8")
    apply.apply(workspace["id"], decisions)
    s = stats.compute(workspace["id"])
    assert s["review"] == {"accepted": 1, "edited": 1, "rejected": 1, "corrected": 1}
    assert any(line.startswith("In review: 1 of 3") for line in s["summary"])


def test_commands_are_logged_for_the_statistics(workspace, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_workspace_of", lambda a: workspace["id"] if getattr(a, "id", None) else None)
    cli.main(["render", workspace["id"], "--from", "1", "--to", "2"])
    cli.main(["status", workspace["id"]])
    capsys.readouterr()
    rows = episode.read_jsonl(workspace["id"], "activity.jsonl")
    assert [r["cmd"] for r in rows] == ["render", "status"] and all(r["ok"] for r in rows)
    assert (workspace["work"] / "signals.json").exists()        # snapshot taken before render


def test_report_carries_found_by_and_the_statistics(workspace):
    flags.add(workspace["id"], 1, "standard", "fix", "你畀我啦", [{"source": "ctc", "detail": "+12.1 nats"}],
              "俾 is not the convention; R 給我 is 畀我")
    flags.add(workspace["id"], 3, "punctuation", "suggest", "-走喇！⏎-等埋我啊", [], "an exclamation, not a statement")
    page = report.build(workspace["id"]).read_text(encoding="utf-8")
    data = json.loads(page.split('<script id="data" type="application/json">')[1].split("</script>")[0])
    by_cue = {i["cue"]: i for i in data["items"]}
    assert by_cue[1]["found_by"] == ["lint"] and by_cue[3]["found_by"] == []
    assert by_cue[1]["evidence"][0]["detail"] == "fits the audio much better than the draft"
    assert "the reference 給我" in by_cue[1]["reason"]
    assert data["meta"]["stats"]["summary"] and (workspace["work"] / "stats.json").exists()
    assert "About this proofread" in page


@pytest.mark.parametrize("raw, plain", [
    ("CTC favours the fix by +7.7", "the audio check: fits the audio better than the draft"),
    ("過 was not spoken (alignment peak 0.00, CTC +15.3)",
     "過 was not spoken (barely heard, the audio check: fits the audio much better than the draft)"),
    ("只有 has peaks 0.00 / 0.00 in draft", "只有 is barely heard in draft"),
    ("weak 王 0.00, 國 0.00", "王 barely heard, 國 barely heard"),
    ("咁遲 vs 今次 has sound_distance 0.081", "咁遲 vs 今次 sounds almost the same"),
    ("both ft and qwen hear 咬落嚟", "both the CantoCaptions recogniser and Qwen hear 咬落嚟"),
    ("the draft fits R; R&D", "the draft fits the reference; R&D"),
])
def test_plain_wording(raw, plain):
    assert report.plain(raw) == plain
