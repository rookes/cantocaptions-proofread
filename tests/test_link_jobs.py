"""Link jobs: reference choice from yt-dlp metadata, review after auto-applied fixes, export."""
import json

from ccp import apply, export, flags
from ccp.fetch import choose_subs
from ccp.srtio import SrtFile


def test_choose_subs_prefers_manual_cantonese_then_chinese():
    info = {"subtitles": {"zh-Hant": [{}], "en": [{}], "yue-HK": [{}], "live_chat": [{}], "ja": [{}]},
            "automatic_captions": {"zh-HK": [{}]}}
    langs = [(s["lang"], s["kind"]) for s in choose_subs(info)]
    assert langs[:3] == [("yue-HK", "manual"), ("zh-Hant", "manual"), ("en", "manual")]
    assert ("zh-HK", "auto") in langs and ("ja", "manual") not in langs


def test_choose_subs_skips_auto_translations():
    auto = {f"{l}": [{}] for l in ["af", "ar", "de", "en", "es", "fr", "it", "ja", "ko", "zh-Hans", "zh-Hant"]}
    auto["zh-HK-orig"] = [{}]
    langs = [s["lang"] for s in choose_subs({"subtitles": {}, "automatic_captions": auto, "language": "yue"})]
    assert langs == ["zh-HK-orig"]


def test_review_after_auto_apply_can_revert_and_reword(workspace, tmp_path):
    f1 = flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", ["context: t"], "the draft does not fit the scene; test reason")
    f2 = flags.add(workspace["id"], 1, "standard", "fix", "你畀我啦", ["lint: 俾"], "the draft does not fit the scene; test reason")
    apply.apply(workspace["id"])                                    # the agent applies both
    srt = SrtFile(workspace["srt"])
    assert srt.cue(1).text == "你畀我啦" and srt.cue(2).text == "阿媽實囉囉攣瞓唔着㗎"
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps({"decisions": [
        {"flag": f1["id"], "decision": "rejected"},                                  # undo
        {"flag": f2["id"], "decision": "accepted", "text": "你畀咗我啦"}]}), encoding="utf-8")  # reword
    res = apply.apply(workspace["id"], dec)
    assert [r["flag"] for r in res["reverted"]] == [f1["id"]]
    srt = SrtFile(workspace["srt"])
    assert srt.cue(2).text == "阿媽食多都亂瞓唔着㗎" and srt.cue(1).text == "你畀咗我啦"
    status = {f["id"]: f["status"] for f in flags.load(workspace["id"])}
    assert status == {f1["id"]: "rejected", f2["id"]: "applied"}


def test_export_bundle(workspace, tmp_path):
    flags.add(workspace["id"], 1, "standard", "fix", "你畀我啦", ["lint: 俾"], "the draft does not fit the scene; test reason")
    apply.apply(workspace["id"])
    (workspace["work"] / "reference.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n你給我吧\n", encoding="utf-8")
    (workspace["work"] / "reference.json").write_text(json.dumps({"language": "zh-Hant", "kind": "manual"}), encoding="utf-8")
    res = export.export(workspace["id"], to=str(tmp_path / "out"), name="Test: video?")
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert "Test video.yue.srt" in names and "Test video.reference.zh-Hant.srt" in names
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["corrections"]["applied"] == 1
    assert SrtFile(tmp_path / "out" / "Test video.yue.srt").cue(1).text == "你畀我啦"
