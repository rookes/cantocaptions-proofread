"""Splits and retimes: timing proposals from a stored emission, flags with proposed cues,
apply --structure with renumbering, and the file-name parsing locate relies on."""
import json

import numpy as np
import pytest

from ccp import apply, cli, flags, locate, timing
from ccp.srtio import SrtFile


def _add(ws, cue, **kw):
    a = dict(category="segmentation", grade="suggest", proposed=None,
             evidence=["context: test"], reason="two sentences across a clear pause", proposed_cues=None)
    a.update(kw)
    return flags.add(ws["id"], cue, a["category"], a["grade"], a["proposed"], a["evidence"],
                     a["reason"], (), (), False, a["proposed_cues"])


def test_split_applies_only_with_structure_and_renumbers(workspace):
    split = [{"start": 4.2, "end": 5.0, "text": "-走喇"}, {"start": 5.1, "end": 6.0, "text": "-等埋我啊"}]
    f_split = _add(workspace, 3, proposed_cues=split)
    f_later = _add(workspace, 4, category="particle", grade="query", proposed=None)
    assert apply.apply(workspace["id"], include_suggest=True)["applied"] == []  # needs --structure
    res = apply.apply(workspace["id"], include_suggest=True, structure=True)
    assert [a["flag"] for a in res["applied"]] == [f_split["id"]]
    assert res["renumbered"] == "sequential"
    srt = SrtFile(workspace["srt"])
    assert [c.text for c in srt.cues] == ["你俾我啦", "阿媽食多都亂瞓唔着㗎", "-走喇", "-等埋我啊", "一定得嘅啦"]
    assert [c.number for c in srt.cues] == ["1", "2", "3", "4", "5"]
    assert (srt.cues[2].start, srt.cues[2].end, srt.cues[3].start) == (4.2, 5.0, 5.1)
    assert srt.to_bytes().startswith(b"\xef\xbb\xbf") and b"\r\n" in srt.to_bytes()
    later = next(f for f in flags.load(workspace["id"]) if f["id"] == f_later["id"])
    assert later["cue"] == 5                                          # moved down by the split


def test_proposed_cues_are_validated(workspace):
    with pytest.raises(ValueError):
        _add(workspace, 3, proposed_cues=[{"start": 5.0, "end": 4.0, "text": "x"}])
    with pytest.raises(ValueError):
        _add(workspace, 3, proposed_cues=[{"start": 4.2, "end": 5.5, "text": "a"},
                                         {"start": 5.0, "end": 6.0, "text": "b"}])


def _fake_store(ws, frames_per_char):
    """Group 0 covers cue 2 (阿媽食多都亂瞓唔着㗎) from 2.5 s at 25 fps; each character is
    heard clearly at the given frame, blank everywhere else."""
    text = "阿媽食多都亂瞓唔着㗎"
    vocab = {ch: k + 1 for k, ch in enumerate(text)}
    T = 60
    probs = np.full((T, len(vocab) + 1), 1e-4)
    probs[:, 0] = 1.0
    for ch, fr in zip(text, frames_per_char):
        probs[fr, 0], probs[fr, vocab[ch]] = 1e-4, 1.0
    lp = np.log(probs / probs.sum(axis=1, keepdims=True)).astype(np.float16)
    em_dir = ws["work"] / "emissions"
    em_dir.mkdir()
    np.save(em_dir / "g0000.npy", lp)
    (em_dir / "tokens.json").write_text(json.dumps(
        {"blank": 0, "tokens": {ch: [i, ""] for ch, i in vocab.items()}, "canonical": {}, "unscorable": []},
        ensure_ascii=False), encoding="utf-8")
    (ws["work"] / "groups.jsonl").write_text(json.dumps(
        {"group": 0, "start": 2.5, "end": 4.9, "cues": [2], "frames": T, "rate": 25.0}) + "\n", encoding="utf-8")


def test_timing_split_follows_the_audio(workspace):
    # Cue 2 runs 3.0-4.0 s: 阿媽食多都亂 at frames 13-18 (3.02-3.22 s), a pause, 瞓唔着㗎 at 33-36
    _fake_store(workspace, [13, 14, 15, 16, 17, 18, 33, 34, 35, 36])
    s = timing.suggest(workspace["id"], 2, split="阿媽食多都亂|瞓唔着㗎")
    a, b = s["proposed_cues"]
    assert a["text"] == "阿媽食多都亂" and b["text"] == "瞓唔着㗎"
    assert a["start"] == 3.0                         # the first piece keeps the cue's start
    assert b["start"] == pytest.approx(2.5 + 33 / 25 - timing.LEAD, abs=0.01)
    assert a["end"] <= b["start"]
    # four characters in 0.23 s: stretched to the style guide's minimum, but only up to the
    # next cue (which starts at 4.2 s)
    assert b["end"] == 4.2
    assert s["onset_gaps_s"][0] == pytest.approx((33 - 18) / 25, abs=0.01)
    assert timing.load_saved(workspace["id"], 2)["proposed_cues"] == s["proposed_cues"]
    f = flags.add(workspace["id"], 2, "segmentation", "suggest", None, [], "two sentences across a pause", (), (), False,
                  timing.load_saved(workspace["id"], 2)["proposed_cues"])
    assert len(f["proposed_cues"]) == 2
    with pytest.raises(SystemExit):
        timing.suggest(workspace["id"], 2, split="阿媽|食多都亂瞓")   # does not spell the cue


def test_timing_retime_respects_neighbours(workspace):
    _fake_store(workspace, [5, 7, 9, 11, 13, 15, 17, 19, 21, 23])
    r = timing.suggest(workspace["id"], 2)["proposed_cues"][0]
    assert r["start"] >= 2.5                          # never before the previous cue ends
    assert r["end"] <= 4.2                            # never past the next cue's start


def test_episode_numbers_from_file_names():
    assert locate.episode_of("[WIP]Re-Zero_2016.S1E03yue.cht.srt") == (1, [3])
    assert locate.episode_of("03.mkv") == (None, [3])
    assert locate.episode_of("[MiniMTBB] Shingeki no Kyojin - 03 (BD 1080p) [29006B5F].mkv") == (None, [3])
    assert locate.episode_of("Doraemon.E523-524.cht.yue.srt") == (None, [523, 524])
    assert locate.episode_of("Show 2x05.mkv") == (2, [5])


def test_passthrough_after_double_dash(workspace, monkeypatch):
    seen = {}
    monkeypatch.setattr("ccp.pipeline.run", lambda *a: seen.setdefault("args", a) or {})
    cli.main(["pipeline", workspace["id"], "realign", "--mode", "adjust", "--", "--realign_pause_gap", "0.4"])
    _, kind, mode, _input, extra, _force = seen["args"]
    assert (kind, mode, extra) == ("realign", "adjust", ["--realign_pause_gap", "0.4"])
