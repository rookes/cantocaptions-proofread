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
        flags.add(workspace["id"], 2, "mishearing", "essential", "high", "阿媽實囉囉攣瞓唔着㗎",
                  ["asr_qwen: 食攞攞攣", "asr_ft: 食多多亂"])
    f = flags.add(workspace["id"], 2, "mishearing", "essential", "high", "阿媽實囉囉攣瞓唔着㗎",
                  ["reference: 一定坐立不安 = 實囉囉攣", "asr_qwen: 食攞攞攣"])
    assert f["evidence"][0]["source"] == "reference"


def test_meaning_check_scope(workspace):
    _with_reference(workspace)
    # Conventions, queries, and cues without a reference line need no reference evidence.
    flags.add(workspace["id"], 2, "standard", "suggested", "high", "阿媽食多都亂瞓唔著㗎", ["lint: x"])
    flags.add(workspace["id"], 1, "mishearing", "suggested", "medium", "你畀我喇", ["asr_ft: 你畀我喇"])
    flags.add(workspace["id"], 4, "mishearing", "query", "low", None, ["asr_ft: 一定得㗎喇"])


def test_batch_reports_failures_and_keeps_the_rest(workspace):
    _with_reference(workspace)
    items = [{"cue": 1, "category": "mishearing", "severity": "suggested", "proposed": "你畀我喇",
              "evidence": ["asr_ft: 你畀我喇"]},
             {"cue": 2, "category": "mishearing", "severity": "essential", "confidence": "high",
              "proposed": "阿媽實囉囉攣瞓唔着㗎", "evidence": ["asr_qwen: 食攞攞攣"]}]
    with pytest.raises(ValueError, match="1 flags recorded"):
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
