"""One grade (fix / suggest / query / keep), a required reason, and migration of old flags."""
import json

import pytest

from ccp import apply, clean, episode, flags, report
from ccp.srtio import SrtFile

REASON = "食多都亂 makes no sense here; 實囉囉攣 (sat6 lo1 lo1 lyun1) keeps the tones"


def test_old_flags_migrate_on_load(workspace):
    old = [
        {"id": 1, "cue": 2, "severity": "essential", "confidence": "high", "proposed": "a", "draft": "b",
         "category": "mishearing", "status": "open", "note": "old note", "evidence": []},
        {"id": 2, "cue": 1, "severity": "suggested", "confidence": "medium", "proposed": "c", "draft": "d",
         "category": "standard", "status": "applied", "evidence": []},
        {"id": 3, "cue": 4, "severity": "query", "confidence": "high", "proposed": "一定得㗎喇",
         "draft": "一定得嘅啦", "category": "particle", "status": "open", "evidence": []},
    ]
    episode.write_jsonl(workspace["id"], "flags.jsonl", old)
    got = {f["id"]: f for f in flags.load(workspace["id"])}
    assert [got[i]["grade"] for i in (1, 2, 3)] == ["fix", "suggest", "query"]
    assert got[1]["reason"] == "old note" and "note" not in got[1] and "severity" not in got[1]
    assert got[3]["proposed"] is None and got[3]["alternatives"] == ["一定得㗎喇"]


def test_reason_is_required(workspace):
    with pytest.raises(ValueError, match="reason"):
        flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], "")
    with pytest.raises(ValueError, match="reason"):
        flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], "阿媽實囉囉攣瞓唔着㗎")
    f = flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], REASON)
    assert f["reason"] == REASON


def test_grade_rules(workspace):
    with pytest.raises(ValueError):
        flags.add(workspace["id"], 2, "mishearing", "suggest", None, [], REASON)      # needs a text
    with pytest.raises(ValueError):
        flags.add(workspace["id"], 2, "particle", "query", "一定得㗎喇", [], REASON)   # queries carry no text
    q = flags.add(workspace["id"], 4, "particle", "query", None, [], "R states, the draft asks", alternatives=["一定得㗎喇"])
    assert q["alternatives"] == ["一定得㗎喇"]


def test_keep_records_and_apply(workspace):
    k = flags.keep(workspace["id"], 3, "both recognisers drop 埋, but R 等等我 needs it; the draft is right")
    assert k["grade"] == "keep" and k["status"] == "kept"
    flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], REASON)
    flags.add(workspace["id"], 1, "standard", "suggest", "你畀我啦", ["lint: 俾"], "convention: 俾 → 畀 (variant)")
    assert [a["cue"] for a in apply.apply(workspace["id"])["applied"]] == [2]          # fix only
    assert [a["cue"] for a in apply.apply(workspace["id"], include_suggest=True)["applied"]] == [1]
    assert SrtFile(workspace["srt"]).cue(3).text == "-走喇\n-等埋我啊"                 # kept untouched
    # A later record on a kept cue is allowed.
    flags.add(workspace["id"], 3, "punctuation", "suggest", "-走喇！⏎-等埋我啊", [], "an exclamation, not a statement")


def test_report_shows_reason_and_kept(workspace):
    flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", [], REASON)
    flags.keep(workspace["id"], 3, "the recognisers' version means something R does not")
    page = report.build(workspace["id"]).read_text(encoding="utf-8")
    data = json.loads(page.split('<script id="data" type="application/json">')[1].split("</script>")[0])
    assert [i["grade"] for i in data["items"]] == ["fix", "keep"]
    assert data["items"][0]["reason"] == REASON
    assert "<b>Reason:</b>" in page and "Checked and kept" in page


def test_clean_holds_back_edits_without_reason(workspace):
    res = clean.clean(workspace["id"], clean.parse(["2|阿媽實囉囉攣瞓唔着㗎", f"1|你畀我啦|{REASON}"]))
    assert res["held_back"]["cues"] == [2]
    assert SrtFile(workspace["srt"]).cue(2).text == "阿媽食多都亂瞓唔着㗎"
    assert SrtFile(workspace["srt"]).cue(1).text == "你畀我啦"
    assert all(f["reason"] for f in flags.load(workspace["id"]))


def test_cli_legacy_options_still_work(workspace):
    from ccp import cli
    cli.main(["flag", "add", workspace["id"], "--cue", "2", "--category", "mishearing", "--severity",
              "essential", "--confidence", "high", "--proposed", "阿媽實囉囉攣瞓唔着㗎", "--note", REASON])
    assert flags.load(workspace["id"])[0]["grade"] == "fix"
    cli.main(["apply", workspace["id"], "--min-severity", "suggested", "--min-confidence", "medium"])
    assert SrtFile(workspace["srt"]).cue(2).text == "阿媽實囉囉攣瞓唔着㗎"


def test_particle_fix_needs_meaning_and_an_independent_signal(workspace):
    eid = workspace["id"]
    why = "一定得 states a certain fact, which 喇 laa3 says; 㗎啦 would say the listener should know it"
    with pytest.raises(ValueError, match="guide"):
        flags.add(eid, 4, "particle", "fix", "一定得㗎喇", ["corpus: 一定 ends in 喇 in most strict clauses"], why)
    with pytest.raises(ValueError, match="independent signal"):
        flags.add(eid, 4, "particle", "fix", "一定得㗎喇", ["guide: 喇 laa3, Usage 4"], why)
    f = flags.add(eid, 4, "particle", "fix", "一定得㗎喇",
                  ["guide: 喇 laa3, Usage 4: a certain fact", "particle_model: clearly prefers 喇"], why)
    assert f["grade"] == "fix"
    # Without the signal it is still fine as a suggestion for the reviewer.
    s = flags.add(eid, 1, "particle", "suggest", "你畀我吖", ["guide: 吖 aa1, Usage 1"], "a polite request: 吖 aa1")
    assert s["grade"] == "suggest"


def test_particle_model_is_not_independent_on_a_machine_draft(workspace, monkeypatch):
    from ccp import episode
    monkeypatch.setattr(episode, "machine_draft", lambda ep: True)
    with pytest.raises(ValueError, match="it wrote this draft"):
        flags.add(workspace["id"], 4, "particle", "fix", "一定得㗎喇",
                  ["guide: 喇 laa3, Usage 4", "particle_model: clearly prefers 喇"],
                  "一定得 states a certain fact, which 喇 laa3 says")
