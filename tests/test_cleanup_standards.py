"""The cleanup's standards hints (lint.style_checks) and particle changes the fine-tuned
recogniser backs (ccp clean on a hand-made draft)."""
import json

from ccp import clean, lint, render
from ccp.srtio import SrtFile


def _write(ws, texts):
    body = "".join(f"{i}\r\n00:00:{i:02d},000 --> 00:00:{i:02d},800\r\n{t}\r\n\r\n" for i, t in enumerate(texts, 1))
    ws["srt"].write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))


def _kinds(ws):
    rows = lint.style_checks(SrtFile(ws["srt"]).cues)
    return {(r["cue"], r["kind"], r["found"]) for r in rows}


def test_style_hints(workspace):
    _write(workspace, ["得返一單Sentence", "COURT", "NKCC案件", "係喇擺返埋先啊唔好唔見", "嗱你睇下喇",
                       "吖", "嗯", "無啦啦走咗", "Mark哥，Mark哥，Mark哥", "做咩啊你"])
    k = _kinds(workspace)
    assert (1, "latin_case", "Sentence") in k
    assert (2, "latin_case", "COURT") in k
    assert not any(c == 3 for c, kind, _ in k)                        # a vowel-less acronym stays
    assert (4, "particle_comma", "係喇擺") in k and (4, "particle_comma", "埋先啊唔") in k
    assert (5, "lead_comma", "嗱你") in k
    assert (6, "lone_interjection", "吖") in k and not any(c == 7 for c, _, _ in k)   # 嗯 can mean yes
    assert not any(c == 8 for c, _, _ in k)                           # 無啦啦 is a word
    assert not any(c == 9 and kind == "latin_case" for c, kind, _ in k)   # a name the file keeps capitalising
    assert not any(c == 10 for c, _, _ in k)                          # 啊你: no comma before 你


def test_quoted_passage(workspace):
    _write(workspace, ["「法官閣下」", "「本人何國權」", "「為前任財政司司長」", "「與被告結識二十餘年」", "多謝"])
    k = _kinds(workspace)
    assert {c for c, kind, _ in k if kind == "quoted_run"} == {1, 2, 3, 4}


def _model(ws, cue, slot, run, logprobs):
    p = ws["work"] / "particle_model.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"cue": cue, "slot": slot, "run": run, "group": 0, "model": "ft",
                            "logprobs": logprobs, "tokens": {}}, ensure_ascii=False) + "\n")


def _start_cleanup(ws):
    p = ws["work"] / "episode.json"
    ep = json.loads(p.read_text(encoding="utf-8"))
    ep["cleanup"] = {"edits": 0, "queries": 0, "at": "now"}
    p.write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")


def test_hand_made_draft_particle_change_backed_by_the_recogniser(workspace):
    _start_cleanup(workspace)
    # cue 4 一定得嘅啦: the recogniser clearly prefers 嘅喇 over 嘅啦
    _model(workspace, 4, 0, "嘅啦", {"嘅啦": -9.0, "嘅喇": -3.0, "㗎啦": -8.0})
    res = clean.clean(workspace["id"], clean.parse(["4|一定得嘅喇|particle: the scene announces a change"]))
    assert res["particles_changed"] and SrtFile(workspace["srt"]).cue(4).text == "一定得嘅喇"
    assert "P the fine-tuned recogniser clearly prefers 嘅喇 over 嘅啦" not in render.render(workspace["id"])  # changed now


def test_unbacked_particle_change_is_put_back(workspace):
    _start_cleanup(workspace)
    _model(workspace, 4, 0, "嘅啦", {"嘅啦": -3.0, "嘅喇": -3.5})          # it prefers the draft
    res = clean.clean(workspace["id"], clean.parse(["4|一定得嘅喇|particle: a guess from the scene"]))
    assert "particles_kept" in res and SrtFile(workspace["srt"]).cue(4).text == "一定得嘅啦"


def test_render_shows_the_recogniser_preference(workspace):
    _model(workspace, 4, 0, "嘅啦", {"嘅啦": -9.0, "嘅喇": -3.0})
    assert "P the fine-tuned recogniser clearly prefers 嘅喇 over 嘅啦" in render.render(workspace["id"])
