import json

import pytest

from ccp import apply, flags, report
from ccp.srtio import SrtFile


def _add(ws, cue, **kw):
    args = dict(category="mishearing", grade="fix", proposed=None, evidence=["reference: test"],
                reason="the draft does not fit the scene; test reason")
    args.update(kw)
    return flags.add(ws["id"], cue, args["category"], args["grade"], args["proposed"],
                     args["evidence"], args["reason"])


def test_flag_validation(workspace):
    with pytest.raises(ValueError):
        _add(workspace, 2, proposed=None)                        # a fix needs a proposal
    with pytest.raises(ValueError):
        _add(workspace, 2, proposed="阿媽食多都亂瞓唔着㗎")         # identical to the draft
    with pytest.raises(ValueError):
        _add(workspace, 9, proposed="x")                         # no such cue
    f = _add(workspace, 2, proposed="阿媽實囉囉攣瞓唔着㗎", evidence=["asr_qwen: 食攞攞攣", "free text"])
    assert f["draft"] == "阿媽食多都亂瞓唔着㗎"
    assert f["evidence"] == [{"source": "asr_qwen", "detail": "食攞攞攣"},
                             {"source": "context", "detail": "free text"}]
    with pytest.raises(ValueError):
        _add(workspace, 2, proposed="另一個")                     # one flag per cue


def test_apply_default_selection_and_text_only(workspace):
    raw_before = workspace["srt"].read_bytes()
    f1 = _add(workspace, 2, proposed="阿媽實囉囉攣瞓唔着㗎")
    _add(workspace, 4, category="particle", proposed="一定得㗎喇")                 # never by default
    _add(workspace, 1, category="standard", grade="suggest", proposed="你畀我啦")  # needs --include-suggest
    res = apply.apply(workspace["id"])
    assert [a["cue"] for a in res["applied"]] == [2]
    after = SrtFile(workspace["srt"])
    assert after.cue(2).text == "阿媽實囉囉攣瞓唔着㗎"
    assert after.cue(4).text == "一定得嘅啦"
    raw_after = workspace["srt"].read_bytes()
    assert raw_after.replace("阿媽實囉囉攣瞓唔着㗎".encode(), "阿媽食多都亂瞓唔着㗎".encode()) == raw_before
    assert next(f for f in flags.load(workspace["id"]) if f["id"] == f1["id"])["status"] == "applied"


def test_apply_decisions_and_stale(workspace, tmp_path):
    f1 = _add(workspace, 1, category="standard", proposed="你畀我啦")
    f2 = _add(workspace, 4, category="particle", grade="suggest", proposed="一定得㗎喇")
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps({"decisions": [
        {"flag": f1["id"], "decision": "accepted", "text": "你畀我啦"},
        {"flag": f2["id"], "decision": "rejected"}]}), encoding="utf-8")
    # the file changes under cue 1 before applying: that flag must be skipped
    srt = SrtFile(workspace["srt"])
    srt.set_text(1, "你俾咗我啦")
    srt.save()
    res = apply.apply(workspace["id"], dec)
    assert res["applied"] == []
    assert res["skipped"][0]["reason"].startswith("cue changed")
    assert {f["id"]: f["status"] for f in flags.load(workspace["id"])}[f2["id"]] == "rejected"


def test_report_builds_without_media(workspace):
    _add(workspace, 2, proposed="阿媽實囉囉攣瞓唔着㗎")
    _add(workspace, 3, category="segmentation", grade="query", proposed=None)
    out = report.build(workspace["id"])
    page = out.read_text(encoding="utf-8")
    assert "<ins>實囉囉攣</ins>" in page.replace("\\u", "") or "實囉囉攣" in page
    data = json.loads(page.split('<script id="data" type="application/json">')[1].split("</script>")[0])
    assert [i["cue"] for i in data["items"]] == [2, 3]
    assert data["items"][0]["clip"] is None


def test_cue_compact_output(workspace, capsys):
    from ccp import cli
    cli.main(["cue", workspace["id"], "2", "3", "--context", "0"])
    out = capsys.readouterr().out
    assert "── cue 2" in out and "── cue 3" in out
    assert "draft  -走喇⏎-等埋我啊" in out
