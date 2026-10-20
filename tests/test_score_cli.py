"""Scoring and listening many cues from one file, and the saved review stream. The scorer and
the GPU are stood in for: these tests check the file handling and the output, not the CTC."""
import json

import pytest

from ccp import cli, ctcscore, render


@pytest.fixture
def scorer(monkeypatch):
    calls = []

    def score_item(store, start, end, draft, candidates):
        calls.append((start, end, draft, candidates))
        cands = [{"text": c, "delta": d} for c, d in zip(candidates, (4.2, -0.8, -7.5))]
        if any(c.endswith("喇") for c in candidates):
            cands[-1] = {"text": candidates[-1], "delta": 0.0, "abstain": "differs only in sentence-final particles"}
        return {"draft": draft, "draft_peaks": "", "reliable": "等埋" not in draft, "candidates": cands}

    monkeypatch.setattr(ctcscore, "Store", lambda eid: object())
    monkeypatch.setattr(ctcscore, "score_item", score_item)
    return calls


def _write(path, items, bom=False):
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(items, ensure_ascii=False).encode("utf-8"))
    return str(path)


def test_file_of_cues_scores_each_and_reports_bad_items(workspace, scorer, capsys):
    f = _write(workspace["work"] / "score.json", [
        {"cue": 2, "candidates": ["阿媽實囉囉攣瞓唔着㗎", "阿媽實囉攣瞓唔着㗎", "阿媽瞓唔着㗎"]},
        {"cue": 3, "candidates": "-走喇⏎-等我啊"},                    # one string is fine
        {"cue": 9, "candidates": ["x"]},                             # no such cue
        {"cue": 1, "candidates": ["你俾我啦"]},                      # only the draft itself
        {"cue": 4, "candidates": ["一定得嘅喇"], "pad": 1.0},
    ], bom=True)                                                     # PowerShell writes a BOM
    cli.main(["score", "t", "--json-file", f])
    out = capsys.readouterr().out
    assert "+4.2  favours" in out and "-0.8  undecided" in out and "-7.5  against" in out
    assert "cue 3  -走喇⏎-等埋我啊  (the aligner barely hears this cue: no verdict)" in out
    assert "cue 9  error: no cue 9" in out
    assert "cue 1  error: no candidate texts other than the draft's own" in out
    assert "abstains   一定得嘅喇  (differs only in sentence-final particles)" in out
    assert len(scorer) == 3
    assert scorer[1][3] == ["-走喇\n-等我啊"]                          # ⏎ read as a line break
    assert scorer[2][:2] == (8.0, 11.0)                              # an explicit pad is not clamped


def test_single_cue_and_old_batch_flag(workspace, scorer, capsys):
    cli.main(["score", "t", "--cue", "2", "阿媽實囉囉攣瞓唔着㗎"])
    assert "cue 2  阿媽食多都亂瞓唔着㗎" in capsys.readouterr().out
    f = _write(workspace["work"] / "s.json", {"cue": 2, "candidates": ["阿媽實囉囉攣瞓唔着㗎"]})
    cli.main(["score", "t", "--batch", f, "--json"])
    assert json.loads(capsys.readouterr().out)["items"][0]["candidates"][0]["delta"] == 4.2


def test_all_items_bad_exits_nonzero(workspace, scorer, capsys):
    f = _write(workspace["work"] / "s.json", [{"cue": 99, "candidates": ["x"]}])
    with pytest.raises(SystemExit):
        cli.main(["score", "t", "--json-file", f])
    assert "error: no cue 99" in capsys.readouterr().out


def test_listen_file_items_become_spans(workspace, monkeypatch, capsys):
    seen = {}

    def run(script, req):
        seen["items"] = req["items"]
        return {"items": [{"key": i["key"], "asr": {"ft": "阿媽"}} for i in req["items"]]}
    monkeypatch.setattr("ccp.gpu_bridge.run", run)
    ep = json.loads((workspace["work"] / "episode.json").read_text(encoding="utf-8"))
    ep["media"] = "x.mkv"
    (workspace["work"] / "episode.json").write_text(json.dumps(ep), encoding="utf-8")
    f = _write(workspace["work"] / "l.json", [{"cue": 2}, {"cue": 4, "pad": 0.5}, {"cue": 0}])
    cli.main(["listen", "t", "--json-file", f])
    res = json.loads(capsys.readouterr().out)
    assert [i["cue"] for i in seen["items"]] == [2, 4]
    assert seen["items"][1]["start"] == 8.5 and seen["items"][1]["end"] == 10.5
    assert any("error" in i for i in res["items"])


def test_render_save_writes_the_stream(workspace, capsys):
    cli.main(["render", "t", "--save"])
    info = json.loads(capsys.readouterr().out)
    text = (workspace["work"] / "review.txt").read_text(encoding="utf-8")
    head, body = text.split("\n", 1)
    assert info["cues"] == "1-4 of 4" and head.startswith("# saved") and body.rstrip("\n") == render.render("t")
    assert any(line.startswith("2|阿媽食多都亂瞓唔着㗎") for line in text.splitlines())
