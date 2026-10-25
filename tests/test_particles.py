"""Particle slots and alternatives, model-style text, collocations and the scan's checks."""
from types import SimpleNamespace

import pytest

from ccp import colloc, dictionary, particle_scan, particles
from ccp.srtio import Cue


def test_slots_find_clause_final_runs_with_their_clauses():
    s = particles.slots("一定係佢喇，你知唔知㗎喇？")
    assert [(x.run, x.clause, x.after) for x in s] == [("喇", "一定係佢", "，"), ("㗎喇", "你知唔知", "？")]
    assert s[1].question and not s[0].question


def test_a_wrapped_line_continues_the_clause_but_a_speaker_line_does_not():
    wrapped = particles.slots("我哋一齊\n食飯啦")
    assert wrapped[0].clause == "我哋一齊\n食飯"
    dialog = particles.slots("-走喇\n-等埋我啊")
    assert [(x.run, x.clause) for x in dialog] == [("喇", "走"), ("啊", "等埋我")]


def test_a_lone_particle_is_not_a_slot():
    assert particles.slots("呀？") == []


def test_alternatives_cover_set_question_form_pairs_and_compounds():
    alts = particles.alternatives("喇")
    assert {"啦", "囖", "嗱", "啊"} <= set(alts)
    assert "喇" not in alts
    assert set(particles.alternatives("呀")) >= {"啊", "吖"}            # aa set; 啊 is also its statement form
    assert "㗎啦" in particles.alternatives("㗎喇")                       # the compound group
    assert len(particles.alternatives("喇")) <= particles.config()["candidates"]["max"]


def test_swap_and_candidates():
    text = "我走先喇，拜拜"
    s = particles.slots(text)[0]
    assert particles.swap(text, s, "啊") == "我走先啊，拜拜"
    assert particles.candidates(text, s)[0] == ("喇", text)


def test_model_text_joins_cues_the_way_the_recogniser_writes():
    text, maps = particles.model_text(["走喇", "-你呢？\n-我唔去啦", "我哋一齊\n食飯啦"])
    assert text == "走喇，你呢？我唔去啦，我哋一齊食飯啦"
    assert text[maps[0][1]] == "喇"
    assert text[maps[1][len("-你呢？\n-我唔去")]] == "啦"
    assert text[maps[2][len("我哋一齊\n食飯")]] == "啦"


def test_group_items_place_each_slot_in_the_joined_text():
    cues = [Cue(1, "1", 0.0, 1.0, lines=["好啦"]), Cue(2, "2", 1.2, 2.0, lines=["我走先喇"])]
    items = particles.group_items(cues, [SimpleNamespace(index=0, start=0.0, end=2.5, cues=[1, 2])])
    (item,) = items
    assert item["text"] == "好啦，我走先喇"
    spots = {(s["cue"], s["run"]): s for s in item["spots"]}
    assert item["text"][spots[(2, "喇")]["start"]] == "喇"
    assert "啊" in spots[(2, "喇")]["alts"]


def test_z_score_rises_with_the_share_above_base():
    base = {"喇": 500, "啦": 500}
    assert colloc.z_score({"喇": 90, "啦": 10}, base, "喇") > 3
    assert abs(colloc.z_score({"喇": 50, "啦": 50}, base, "喇")) < 1


def test_distinct_keeps_one_pull_per_idea():
    mk = lambda f, z: colloc.Pull(f, "laa", 100, 10, {"喇": 90}, "喇", z, 0.9)
    out = colloc._distinct([mk("已", 44.0), mk("已經", 43.7), mk("經", 41.0), mk("太", 57.0)])
    assert [p.feature for p in out] == ["太", "已經"]


def test_recorded_note_matching():
    n = colloc.Note("一定", "laa", "certain fact", prefer="喇")
    assert n.applies("一定係佢", "啦") and n.wants_other("啦") and not n.wants_other("㗎喇")
    assert not n.applies("係佢", "啦")
    runs = colloc.Note("我都話咗", "嚛|㗎啦|㗎喇", "told you so")
    assert runs.applies("-我都話咗", "㗎啦") and not runs.applies("我都話咗", "啊")


def test_add_note_writes_proposed_entries_and_protects_confirmed(tmp_path, monkeypatch):
    path = tmp_path / "collocations.toml"
    path.write_text('# header kept\n\n[[colloc]]\ntrigger = "一定"\namong = "laa"\nprefer = "喇"\n'
                    'note = "x"\nsource = "guide"\nstatus = "confirmed"\nadded = "2026-10-25"\n', encoding="utf-8")
    monkeypatch.setattr(colloc, "NOTES", path)
    monkeypatch.setattr(colloc, "note_counts", lambda *a, **k: {"total": 0, "counts": []})
    r = colloc.add_note("梗係", "laa", "obviously: 啦 (particle-usage: 啦 laa1)", prefer="啦",
                        source="agent:ep1", examples=["ep1#3  梗係啦"])
    assert r["recorded"] and r["action"] == "added"
    again = colloc.add_note("梗係", "laa", "updated", prefer="啦", source="agent:ep2", examples=["ep2#9  梗係啦"])
    assert again["action"] == "updated"
    notes = {n.trigger: n for n in colloc.notes()}
    assert notes["梗係"].status == "proposed" and notes["梗係"].note == "updated"
    assert notes["梗係"].examples == ["ep1#3  梗係啦", "ep2#9  梗係啦"]
    assert not colloc.add_note("一定", "laa", "changed", prefer="啦")["recorded"]
    assert notes["一定"].note == "x"
    assert path.read_text(encoding="utf-8").startswith("# header kept")
    with pytest.raises(ValueError):
        colloc.add_note("(", "laa", "bad regex")
    with pytest.raises(ValueError):
        colloc.add_note("好", "laa", "x", prefer="啊")


def test_example_readings_come_from_the_example_jyutping():
    e = dictionary.Example("好囉喎！", "hou2 lo3 wo3")
    assert dictionary._example_readings(e) == {0: "hou2", 1: "lo3", 2: "wo3"}
    # A Latin word upsets the count: the end of the sentence is still matched.
    e = dictionary.Example("食M記囉。", "sik6 em1 gei3 lo4")
    r = dictionary._example_readings(e)
    assert r[3] == "lo4" and r[2] == "gei3" and 0 not in r


def test_model_view_levels(monkeypatch):
    monkeypatch.setattr(particle_scan, "config", lambda: {"model": {"calibrated": True, "clear": 3.0, "lean": 1.0}})
    m = particle_scan.model_view({"logprobs": {"喇": -5.0, "啦": -1.0, "囖": -9.0}}, "喇", True)
    assert m.prefers_other and m.best == "啦" and m.level == "clear"
    assert "clearly prefers 啦 over 喇" in m.phrase("喇")
    m = particle_scan.model_view({"logprobs": {"喇": -1.0, "啦": -1.5}}, "喇", False)
    assert not m.prefers_other and m.level == "none" and "not independent" in m.phrase("喇")


def test_uncalibrated_model_is_never_clear(monkeypatch):
    monkeypatch.setattr(particle_scan, "config", lambda: {"model": {"calibrated": False, "clear": 3.0, "lean": 1.0}})
    assert particle_scan._level(10.0) == "lean"


def test_form_checks():
    s = particles.slots("你返嚟嗱")[0]
    assert any("question particle" in c for c in particle_scan._checks(s))
    s = particles.slots("你返嚟喇？")[0]
    assert any("嗱" in c for c in particle_scan._checks(s))
    s = particles.slots("你幾時返嚟喇？")[0]
    assert particle_scan._checks(s) == []


def test_force_against_the_reference():
    assert particle_scan._force("你返嚟喇", ["你回來了？"]) == "the reference asks a question, the line states"
    assert particle_scan._force("你返嚟嗱", ["你回來了"]) == "the line asks a question, the reference states"
    assert particle_scan._force("你返嚟喇", ["你回來了"]) == ""
    assert particle_scan._force("你返嚟喇", []) == ""


def test_scan_reports_each_slot_with_its_signals(workspace):
    from ccp import episode
    eid = workspace["id"]
    episode.write_jsonl(eid, "particle_model.jsonl", [
        {"cue": 4, "slot": 0, "run": "嘅啦", "group": 3, "model": "ft",
         "logprobs": {"嘅啦": -6.0, "嘅喇": -1.0}, "tokens": {}},
        {"cue": 1, "slot": 0, "run": "啦", "group": 0, "model": "ft",
         "logprobs": {"啦": -0.5, "喇": -5.0}, "tokens": {}}])
    reports = {(r.cue, r.slot.index): r for r in particle_scan.scan(eid)}
    one, four = reports[(1, 0)], reports[(4, 0)]
    assert not one.suspect and not one.model.prefers_other
    assert four.suspect and four.model.best == "嘅喇"
    assert any("一定 usually takes 喇" in why for why in four.reasons)      # the recorded collocation
    text = particle_scan.as_text(list(reports.values()), only_suspects=True)
    assert "4[0] 嘅啦" in text and "1[0]" not in text
    # A cue edited since it was scored loses its stale score.
    rows = episode.read_jsonl(eid, "particle_model.jsonl")
    rows[0]["run"] = "㗎喇"
    episode.write_jsonl(eid, "particle_model.jsonl", rows)
    assert {(r.cue, r.slot.index): r for r in particle_scan.scan(eid)}[(4, 0)].model is None


def test_form_checks_leave_continued_questions_and_question_word_runs_alone():
    assert particle_scan._checks(particles.slots("你肯定呀，")[0]) == []
    assert particle_scan._checks(particles.slots("你喺度做咩啊？")[0]) == []
    assert particle_scan._force("只不過係日出啫", ["真的是這樣嗎？  只是日出而已"]) == ""


def test_a_weak_pair_is_a_lean_at_most(monkeypatch):
    monkeypatch.setattr(particle_scan, "config", lambda: {"model": {
        "calibrated": True, "clear": 4.0, "lean": 2.0, "weak_pairs": ["吖啊"]}})
    assert particle_scan._level(9.0, "吖", "啊") == "lean"
    assert particle_scan._level(9.0, "喇", "啦") == "clear"


def test_a_tendency_is_no_reason_where_the_recogniser_hears_the_draft(workspace):
    from ccp import episode
    eid = workspace["id"]
    episode.write_jsonl(eid, "particle_model.jsonl", [
        {"cue": 4, "slot": 0, "run": "嘅啦", "group": 3, "model": "ft",
         "logprobs": {"嘅啦": -1.0, "嘅喇": -6.0}, "tokens": {}}])
    rep = {(r.cue, r.slot.index): r for r in particle_scan.scan(eid)}[(4, 0)]
    assert rep.notes and not rep.suspect          # the 一定 note is shown, but not a reason
