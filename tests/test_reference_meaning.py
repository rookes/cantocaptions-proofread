"""A fix that changes what a line says must be checked against the reference's meaning."""
import json

import pytest

from ccp import flags


def _with_reference(ws):
    (ws["work"] / "reference.srt").write_text(
        "1\n00:00:03,000 --> 00:00:04,000\n媽媽一定坐立不安睡不著的\n", encoding="utf-8")
    (ws["work"] / "reference.json").write_text(json.dumps({"offset": 0.0}), encoding="utf-8")


def test_mishearing_fix_needs_reference_evidence(workspace):
    _with_reference(workspace)
    with pytest.raises(ValueError, match="reference"):
        flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎",
                  ["asr_qwen: 食攞攞攣", "asr_ft: 食多多亂"], "both recognisers hear lo-syllables")
    f = flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎",
                  ["reference: 一定坐立不安 = 實囉囉攣", "asr_qwen: 食攞攞攣"],
                  "食多都亂 is nonsense; R 一定坐立不安 = 實囉囉攣, same tones")
    assert f["evidence"][0]["source"] == "reference"


def test_meaning_check_scope(workspace):
    _with_reference(workspace)
    # Conventions, queries, and cues without a reference line need no reference evidence.
    flags.add(workspace["id"], 2, "standard", "fix", "阿媽食多都亂瞓唔著㗎", ["lint: x"], "convention: 着 → 著 test")
    flags.add(workspace["id"], 1, "mishearing", "suggest", "你畀我喇", ["asr_ft: 你畀我喇"], "no reference line on cue 1")
    flags.add(workspace["id"], 4, "mishearing", "query", None, ["asr_ft: 一定得㗎喇"], "something is off, unclear what")


def test_batch_reports_failures_and_keeps_the_rest(workspace):
    _with_reference(workspace)
    items = [{"cue": 1, "category": "mishearing", "grade": "suggest", "proposed": "你畀我喇",
              "evidence": ["asr_ft: 你畀我喇"], "reason": "no reference line on cue 1"},
             {"cue": 2, "category": "mishearing", "grade": "fix",
              "proposed": "阿媽實囉囉攣瞓唔着㗎", "evidence": ["asr_qwen: 食攞攞攣"],
              "reason": "both recognisers hear lo-syllables"}]
    with pytest.raises(ValueError, match="1 records added"):
        flags.add_many(workspace["id"], items)
    assert [f["cue"] for f in flags.load(workspace["id"])] == [1]


def test_cue_output_puts_reference_first_and_asks_for_meaning(workspace, capsys):
    _with_reference(workspace)
    (workspace["work"] / "evidence.jsonl").write_text(json.dumps(
        {"cue": 2, "asr": {"qw": {"text": "你阿媽食攞攞攣，瞓唔著嘅"}}, "peaks": []},
        ensure_ascii=False) + "\n", encoding="utf-8")
    from ccp import cli
    cli.main(["cue", workspace["id"], "2"])
    out = capsys.readouterr().out
    assert out.index("R      媽媽") < out.index("qw ≠")
    assert "check  R sets the meaning" in out


def test_untagged_image_tracks_make_ccp_ask_which_and_in_what_language(workspace, monkeypatch):
    from ccp import episode, paths, reference
    ep = episode.load(workspace["id"])
    ep.update(media="x.mkv", subtitle_streams=[
        {"stream_index": 3, "kind": "bitmap", "codec": "hdmv_pgs_subtitle", "language": "", "title": ""}])
    episode.save(ep)
    monkeypatch.setattr(paths, "ccai_has_ocr", lambda: True)
    r = reference.prepare(workspace["id"])
    assert r["status"] == "needs_decision"
    assert "stream 3" in r["ask_the_user"] and "Traditional Chinese" in r["ask_the_user"]
    assert "--ocr-lang" in r["answers"]["read stream N, in language L"] and "no reference" in r["answers"]
    assert "Do not recommend" in r["how_to_ask"]
    with pytest.raises(SystemExit, match="no language tag"):
        reference.prepare(workspace["id"], stream=3, ocr=True)          # asks before running any OCR
