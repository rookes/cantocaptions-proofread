"""Regrouping cues (ccp segment) and lines the draft lacks (ccp missing, flag add --missing):
checks, provisional times, applying with renumbering, removing an inserted line again."""
import json

import pytest

from ccp import apply, flags, missing, render, segment
from ccp.srtio import SrtFile

# The workspace fixture's cues:
#   1  1.0-2.5  你俾我啦
#   2  3.0-4.0  阿媽食多都亂瞓唔着㗎
#   3  4.2-6.0  -走喇⏎-等埋我啊
#   4  9.0-10.0 一定得嘅啦


def _machine(ws):
    p = ws["work"] / "episode.json"
    ep = json.loads(p.read_text(encoding="utf-8"))
    ep["ai_generated"] = True
    p.write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")


def _cues(ws):
    return SrtFile(ws["srt"]).cues


def _realigned(ws):
    p = ws["work"] / "episode.json"
    ep = json.loads(p.read_text(encoding="utf-8"))
    ep["draft_origin"] = {"kind": "realign", "mode": "adjust"}
    p.write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")


def test_parse_and_checks(workspace):
    cues = _cues(workspace)
    [e] = segment.parse(["2|阿媽食多都亂， // 瞓唔着㗎|a long cue with two clauses"])
    assert (e["first"], e["last"], e["pieces"]) == (2, 2, ["阿媽食多都亂，", "瞓唔着㗎"])
    assert segment.tidy(e["pieces"][0]) == "阿媽食多都亂"                 # no comma left at a cue's end
    assert segment.problems(cues, e) == []
    changed = segment.parse(["2|阿媽實囉囉攣 // 瞓唔着㗎|words changed too"])[0]
    assert any("spell out" in p for p in segment.problems(cues, changed))
    one_dash = segment.parse(["1-2|-你俾我啦⏎阿媽食多都亂瞓唔着㗎|two speakers"])[0]
    assert any("two speakers take two lines" in p for p in segment.problems(cues, one_dash))
    no_reason = segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎"])[0]
    assert any("reason" in p for p in segment.problems(cues, no_reason))
    broken = segment.parse(["2|阿媽食多都亂⏎瞓唔着㗎|a long line broken in two"])[0]
    assert any("fits on one line" in p for p in segment.problems(cues, broken))
    joined = segment.parse(["1-2|-你俾我啦⏎-阿媽食多都亂瞓唔着㗎|two speakers"])[0]
    assert any("only after the realign" in p for p in segment.problems(cues, joined))
    with pytest.raises(ValueError):
        segment.parse(["two|x|y"])


def test_proportional_split_times(workspace):
    cues = _cues(workspace)
    src = cues[1:2]
    pc = segment.proposed_cues(src, ["阿媽食多都亂", "瞓唔着㗎"], segment._proportional(src))
    assert pc[0]["start"] == 3.0 and pc[-1]["end"] == 4.0          # outer edges kept
    assert pc[0]["end"] == pytest.approx(3.6) and pc[1]["start"] == pytest.approx(3.6)


def test_cleanup_regroups_apply_at_once_and_shift_later_flags(workspace):
    _machine(workspace)
    later = flags.add(workspace["id"], 4, "particle", "query", None, [], "is 嘅啦 right here? test")
    res = segment.segment(workspace["id"], segment.parse([
        "3|走喇， // 等埋我啊|two speakers in one cue: one cue each",
    ]))
    assert res["applied"] == 1 and res["cues_now"] == 5
    cues = _cues(workspace)
    assert [c.text for c in cues] == ["你俾我啦", "阿媽食多都亂瞓唔着㗎", "走喇", "等埋我啊", "一定得嘅啦"]
    assert [c.number for c in cues] == ["1", "2", "3", "4", "5"]
    rows = {f["id"]: f for f in flags.load(workspace["id"])}
    assert rows[later["id"]]["cue"] == 5                             # moved down by the split
    seg = next(f for f in rows.values() if f.get("pass") == "segmentation")
    assert seg["status"] == "applied" and seg["span"] == [3, 4] and seg["grade"] == "fix"


def test_segment_only_in_the_cleanup(workspace):
    with pytest.raises(SystemExit, match="cleanup pass"):
        segment.segment(workspace["id"], segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎|two clauses in one cue"]))
    # A hand-made messy file is in the cleanup once `ccp clean` has run on it.
    p = workspace["work"] / "episode.json"
    ep = json.loads(p.read_text(encoding="utf-8"))
    ep["cleanup"] = {"edits": 1, "queries": 0, "at": "now"}
    p.write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    res = segment.segment(workspace["id"], segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎|two clauses in one cue"]))
    assert res["applied"] == 1 and len(_cues(workspace)) == 5


def test_after_the_realign_only_quick_exchanges_join(workspace):
    _machine(workspace)
    srt = SrtFile(workspace["srt"])
    srt.replace_cues(3, 3, [(4.2, 4.6, "走喇"), (4.8, 6.0, "等埋我啊")])     # starts 0.6 s apart
    srt.save()
    _realigned(workspace)
    split = segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎|two clauses"])
    res = segment.segment(workspace["id"], split)
    assert res["applied"] == 0 and "only re-cut is joining" in res["refused"][0]["problems"][0]
    far = segment.parse(["1-2|-你俾我啦⏎-阿媽食多都亂瞓唔着㗎|two speakers"])
    assert "each can be read on its own" in segment.segment(workspace["id"], far)["refused"][0]["problems"][0]
    sig = segment.signals(_cues(workspace), after_realign=True)
    assert any("quick exchange" in n for n in sig[3])
    res = segment.segment(workspace["id"], segment.parse(["3-4|-走喇⏎-等埋我啊|quick exchange, two speakers"]))
    assert res["applied"] == 1
    assert [(c.start, c.end, c.text) for c in _cues(workspace)][2] == (4.2, 6.0, "-走喇" + chr(10) + "-等埋我啊")


def test_clean_removes_a_line_and_the_reviewer_can_put_it_back(workspace, tmp_path):
    from ccp import clean
    _machine(workspace)
    later = flags.add(workspace["id"], 4, "particle", "query", None, [], "is 嘅啦 right here? test")
    res = clean.clean(workspace["id"], clean.parse(["1|-|a lone interjection with no meaning of its own",
                                                    "2|阿媽實囉囉攣瞓唔着㗎|mishearing: R says restless"]))
    assert res["removals"] == 1 and res["applied"] == 2
    assert [c.text for c in _cues(workspace)] == ["阿媽實囉囉攣瞓唔着㗎", "-走喇" + chr(10) + "-等埋我啊", "一定得嘅啦"]
    rows = {f["id"]: f for f in flags.load(workspace["id"])}
    gone = next(f for f in rows.values() if f.get("remove"))
    assert gone["status"] == "applied" and gone["draft"] == "你俾我啦" and rows[later["id"]]["cue"] == 3
    dec = tmp_path / "d.json"
    dec.write_text(json.dumps({"decisions": [{"flag": gone["id"], "decision": "rejected"}]}), encoding="utf-8")
    res = apply.apply(workspace["id"], dec)
    assert res["restored"][0]["text"] == "你俾我啦"
    cues = _cues(workspace)
    assert (cues[0].start, cues[0].end, cues[0].text) == (1.0, 2.5, "你俾我啦")
    rows = {f["id"]: f for f in flags.load(workspace["id"])}
    assert rows[later["id"]]["cue"] == 4 and rows[gone["id"]]["status"] == "rejected"


def _reference(ws, lines):
    body = "".join(f"{i}\n{a} --> {b}\n{t}\n\n" for i, (a, b, t) in enumerate(lines, 1))
    (ws["work"] / "reference.srt").write_text(body, encoding="utf-8")


def test_orphans_listing_and_render(workspace):
    _reference(workspace, [("00:00:01,000", "00:00:02,500", "你給我吧"),
                           ("00:00:07,000", "00:00:08,000", "你去哪裏？"),
                           ("00:00:11,000", "00:00:12,000", "（三年後）")])
    cues, rows = missing.orphans(workspace["id"])
    assert [(r["n"], r["after"], r["on_screen"]) for r in rows] == [(2, 3, False), (3, 4, True)]
    out = missing.listing(workspace["id"])
    assert out["count"] == 2 and out["spoken"] == 1 and out["missing"][0]["before"].startswith("3|")
    text = render.render(workspace["id"])
    assert "+R#2 你去哪裏？" in text and "(on-screen text)" in text
    assert "R 你給我吧" in text                                        # a covered line stays with its cue
    only = render.render(workspace["id"], only={"missing"})
    assert "+R#2" in only and "阿媽" not in only


def _heard(ws, n, ft, qw):
    d = ws["work"] / "missing"
    d.mkdir(exist_ok=True)
    row = {"ref": "x", "at": "0:07.0", "heard": {"close": {"ft": ft, "qw": qw}, "isolated": {"ft": ft, "qw": ""},
                                                 "wider": {"ft": "x" + ft, "qw": qw}, "hinted": {"ft": "你去哪裏", "qw": ""}}}
    (d / f"{n}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")


def test_insert_missing_line_then_remove_it(workspace, tmp_path):
    _reference(workspace, [("00:00:07,000", "00:00:08,000", "你去哪裏？")])
    with pytest.raises(ValueError):                                    # a reference line is required
        missing.record(workspace["id"], 1, "fix", "你去邊度啊？", "heard after the pause, test", [])
    _heard(workspace, 1, "你去邊度啊？", "你去邊度呀")
    f = missing.record(workspace["id"], 1, "fix", "你去邊度啊？", "both recognisers hear it in the pause",
                       ["reference: 你去哪裏 = 你去邊度"])
    assert f["insert"] and f["cue"] == 3 and f["proposed_cues"][0]["start"] == 7.0
    later = flags.add(workspace["id"], 4, "particle", "query", None, [], "is 嘅啦 right here? test")
    res = apply.apply(workspace["id"], structure=True)
    assert len(res["applied"]) == 1
    cues = _cues(workspace)
    assert [c.text for c in cues][3:] == ["你去邊度啊？", "一定得嘅啦"] and (cues[3].start, cues[3].end) == (7.0, 8.0)
    rows = {r["id"]: r for r in flags.load(workspace["id"])}
    assert rows[f["id"]]["cue"] == 4 and rows[later["id"]]["cue"] == 5
    assert missing.orphans(workspace["id"])[1] == []                   # covered now
    dec = tmp_path / "d.json"
    dec.write_text(json.dumps({"decisions": [{"flag": f["id"], "decision": "rejected"}]}), encoding="utf-8")
    res = apply.apply(workspace["id"], dec)
    assert res["removed"][0]["text"] == "你去邊度啊？"
    assert [c.text for c in _cues(workspace)] == ["你俾我啦", "阿媽食多都亂瞓唔着㗎", "-走喇\n-等埋我啊", "一定得嘅啦"]
    rows = {r["id"]: r for r in flags.load(workspace["id"])}
    assert rows[f["id"]]["status"] == "rejected" and rows[later["id"]]["cue"] == 4


def test_segment_signals(workspace):
    srt = SrtFile(workspace["srt"])
    srt.replace_cues(1, 1, [(1.0, 1.4, "你俾"), (1.45, 1.9, "我啦")])
    srt.save()
    sig = segment.signals(SrtFile(workspace["srt"]).cues)
    # Short cues are no signal before the realign: a transcriber who pads tightly makes them.
    assert not any("inside a word" in n or "short" in n for n in sig.get(1, []))   # 俾|我: two words
    assert any("two speakers in one cue" in n for n in sig[4])          # -走喇⏎-等埋我啊
    srt = SrtFile(workspace["srt"])
    srt.replace_cues(1, 2, [(1.0, 1.9, "我哋返學"), (1.95, 3.0, "校先啦")])
    srt.save()
    sig = segment.signals(SrtFile(workspace["srt"]).cues)
    assert any("cut inside a word: 學校" in n for n in sig[1])


def test_srtio_insert_and_delete_round_trip(workspace):
    raw = workspace["srt"].read_bytes()
    srt = SrtFile(workspace["srt"])
    srt.insert_after(4, [(11.0, 12.0, "最後")])
    srt.insert_after(0, [(0.1, 0.5, "最先")])
    assert [c.text for c in srt.cues][0] == "最先" and srt.cues[-1].text == "最後"
    srt.delete_cue(6)
    srt.delete_cue(1)
    assert srt.to_bytes() == raw


def test_records_follow_the_draft_through_a_realign(workspace, tmp_path):
    from ccp import pipeline
    _machine(workspace)
    _reference(workspace, [("00:00:07,000", "00:00:08,000", "你去哪裏？")])
    edit = flags.add(workspace["id"], 1, "standard", "fix", "你畀我啦", [], "畀 is the standard form, test")
    apply.apply(workspace["id"], only=[edit["id"]])
    segment.segment(workspace["id"], segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎|two clauses, a clear pause"]))
    _heard(workspace, 1, "你去邊度啊？", "你去邊度呀")
    ins = missing.record(workspace["id"], 1, "fix", "你去邊度啊？", "heard in the pause, test",
                         ["reference: 你去哪裏 = 你去邊度"])
    apply.apply(workspace["id"], only=[ins["id"]])
    old = SrtFile(workspace["srt"]).cues
    assert [c.text for c in old] == ["你畀我啦", "阿媽食多都亂", "瞓唔着㗎", "-走喇\n-等埋我啊", "你去邊度啊？", "一定得嘅啦"]
    # The realign moves every cue a little and drops 「-走喇⏎-等埋我啊」 (the recording lacks it).
    out = tmp_path / "realigned.srt"
    keep = [c for c in old if not c.text.startswith("-")]
    out.write_text("".join(f"{i}\n00:00:0{int(c.start)},{int((c.start % 1) * 1000) + 50:03d} --> "
                           f"00:00:{int(c.end):02d},{int((c.end % 1) * 1000):03d}\n{c.text}\n\n"
                           for i, c in enumerate(keep, 1)), encoding="utf-8")
    new = SrtFile(out).cues
    res = pipeline.carry_records(workspace["id"], old, new, flags.load(workspace["id"]), {})
    rows = {f["id"]: f for f in flags.load(workspace["id"])}
    assert res["records"] == 3 and "not_carried" not in res
    assert rows[edit["id"]]["cue"] == 1 and rows[edit["id"]]["start"] == new[0].start
    assert rows[ins["id"]]["cue"] == 4 and rows[ins["id"]]["applied_text"] == "你去邊度啊？"
    seg = next(f for f in rows.values() if f.get("span"))
    assert seg["cue"] == 2 and seg["realigned"]


def test_report_shows_added_and_recut_lines(workspace):
    from ccp import report
    _machine(workspace)
    _reference(workspace, [("00:00:07,000", "00:00:08,000", "你去哪裏？")])
    segment.segment(workspace["id"], segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎|two clauses, a clear pause"]))
    waiting = missing.record(workspace["id"], 1, "query", None, "something is said here, unclear what",
                             ["reference: 你去哪裏"], ["你去邊度？", "你去邊啊？"])
    page = report.build(workspace["id"]).read_text(encoding="utf-8")
    raw = page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
    data = json.loads(raw.replace("<\\/", "</"))
    assert "addedRow" in page
    by = {i["id"]: i for i in data["items"]}
    assert by[waiting["id"]]["insert"] and by[waiting["id"]]["reference"] == ["你去哪裏？"]
    assert not any(i["span"] for i in data["items"])                    # re-cuts stay out of the report


def test_listen_span_for_a_missing_line_stays_between_its_neighbours(workspace):
    from types import SimpleNamespace
    from ccp import cli, episode
    _reference(workspace, [("00:00:05,500", "00:00:08,000", "你去哪裏？")])     # overlaps cue 3 a little
    a = SimpleNamespace(id=workspace["id"], missing=[1], pad=0.3, json_file=None, cue=None, start=None, end=None,
                        default_pad=1.0)
    ep = episode.load(workspace["id"])
    items, refused = cli._span_items(a, ep, episode.srt(ep))
    assert refused == [] and items[0]["key"] == "+R#1 close" and len(items) == 4
    assert items[0]["start"] == 6.0 and items[0]["end"] == 8.3          # from cue 3's end, padded at the end



def test_missing_line_grade_follows_the_close_hearings(workspace):
    _reference(workspace, [("00:00:07,000", "00:00:08,000", "你去哪裏？"), ("00:00:11,000", "00:00:12,000", "（三年後）")])
    ref = "reference: 你去哪裏 = 你去邊度"
    with pytest.raises(ValueError, match="not listened to yet"):
        missing.record(workspace["id"], 1, "suggest", "你去邊度啊？", "heard in the pause, test", [ref])
    _heard(workspace, 1, "你去邊度啊？", "我哋走啦")                  # only the fine-tuned one hears it
    with pytest.raises(ValueError, match="suggest at most"):
        missing.record(workspace["id"], 1, "fix", "你去邊度啊？", "heard in the pause, test", [ref])
    f = missing.record(workspace["id"], 1, "suggest", "你去邊度啊？", "heard in the pause, test", [ref])
    assert f["grade"] == "suggest"
    # The reference as a hint never counts: only the close hearings do.
    assert missing.allowed_grade(workspace["id"], 1, "你去哪裏", False)[0] == "query"
    # On-screen text is copied from the reference, no listening needed.
    g = missing.record(workspace["id"], 2, "fix", "（三年後）", "a caption on screen, test", ["reference: （三年後）"])
    assert g["proposed_cues"][0]["text"] == "（三年後）"


def test_listen_items_for_a_missing_line(workspace):
    _reference(workspace, [("00:00:07,000", "00:00:08,000", "你去哪裏？")])
    items = missing.listen_items(workspace["id"], 1)
    assert [i["way"] for i in items] == ["close", "isolated", "wider", "hinted"]
    assert items[1]["isolate"] and "你去哪裏" in items[3]["context"] and "context" not in items[0]
    assert (items[0]["start"], items[0]["end"]) == (6.7, 8.3) and (items[2]["start"], items[2]["end"]) == (6.0, 9.0)


def test_machine_draft_missing_line_goes_in_at_once(workspace):
    _machine(workspace)
    _reference(workspace, [("00:00:07,000", "00:00:08,000", "你去哪裏？")])
    _heard(workspace, 1, "你去邊度啊？", "你去邊度呀")
    f = missing.record(workspace["id"], 1, "fix", "你去邊度啊？", "both recognisers hear it in the pause",
                       ["reference: 你去哪裏 = 你去邊度"])
    assert f["status"] == "applied" and f["cue"] == 4
    assert _cues(workspace)[3].text == "你去邊度啊？"


def test_rejecting_an_applied_regroup_reports_it_stays(workspace, tmp_path):
    _machine(workspace)
    segment.segment(workspace["id"], segment.parse(["2|阿媽食多都亂 // 瞓唔着㗎|two clauses, a clear pause"]))
    seg = next(f for f in flags.load(workspace["id"]) if f.get("span"))
    dec = tmp_path / "d.json"
    dec.write_text(json.dumps({"decisions": [{"flag": seg["id"], "decision": "rejected"}]}), encoding="utf-8")
    res = apply.apply(workspace["id"], dec)
    assert res["not_undone"]["regroups"][0]["flag"] == seg["id"]
    assert len(_cues(workspace)) == 5
