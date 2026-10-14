"""ccp clean: bulk text-only edits are recorded as flags, applied at once, and can be undone."""
import json

import pytest

from ccp import clean, episode, flags, report
from ccp.srtio import SrtFile


def test_parse_formats():
    rows = clean.parse(["# comment", "", "2|阿媽實囉囉攣瞓唔着㗎|reference: 一定坐立不安",
                        "3|-走喇⏎-等埋我啊|punctuation: dash lines", "4|?|meaning unclear", "1|你畀我啦"])
    assert [r["cue"] for r in rows] == [2, 3, 4, 1]
    assert rows[0]["category"] is None and rows[0]["why"] == "reference: 一定坐立不安"
    assert rows[1]["category"] == "punctuation" and rows[1]["why"] == "dash lines"
    assert rows[2]["text"] is None
    with pytest.raises(ValueError):
        clean.parse(["2|a", "2|b"])
    with pytest.raises(ValueError):
        clean.parse(["two|a"])


def test_clean_applies_records_and_can_be_undone(workspace, tmp_path):
    before = workspace["srt"].read_bytes()
    res = clean.clean(workspace["id"], clean.parse(["2|阿媽實囉囉攣瞓唔着㗎|reference: 一定坐立不安",
                                                    "4|?|meaning unclear"]))
    assert res["applied"] == 1 and res["queries"] == 1 and res["by_category"] == {"mishearing": 1}
    after = workspace["srt"].read_bytes()
    assert after.startswith(b"\xef\xbb\xbf") and b"\r\n" in after
    assert SrtFile(workspace["srt"]).cue(2).text == "阿媽實囉囉攣瞓唔着㗎"
    fl = flags.load(workspace["id"])
    fix = next(f for f in fl if f["cue"] == 2)
    assert fix["pass"] == "cleanup" and fix["status"] == "applied" and fix["evidence"][0]["source"] == "reference"
    assert next(f for f in fl if f["cue"] == 4)["severity"] == "query"
    assert episode.load(workspace["id"])["cleanup"]["edits"] == 1
    # A second pass may edit the same cue again (a new flag on the corrected text).
    clean.clean(workspace["id"], clean.parse(["2|阿媽實囉囉攣，瞓唔着㗎"]))
    assert SrtFile(workspace["srt"]).cue(2).text == "阿媽實囉囉攣，瞓唔着㗎"
    # The reviewer undoes the second edit from the report.
    second = max(f["id"] for f in flags.load(workspace["id"]) if f["cue"] == 2)
    from ccp import apply
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps({"decisions": [{"flag": second, "decision": "rejected"}]}), encoding="utf-8")
    apply.apply(workspace["id"], dec)
    assert SrtFile(workspace["srt"]).cue(2).text == "阿媽實囉囉攣瞓唔着㗎"
    assert before != workspace["srt"].read_bytes()


def test_lint_fixes_merge_with_edits(workspace):
    srt = SrtFile(workspace["srt"])
    srt.set_text(3, "-走喇。⏎-等埋我啊……")
    srt.set_text(1, "你係咪傻㗎。")
    srt.save()
    dry = clean.clean(workspace["id"], clean.parse(["4|一定唔得嘅啦。"]), use_lint=True, skip_lint=[1], dry_run=True)
    assert dry["edits"] == 2 and SrtFile(workspace["srt"]).cue(3).text == "-走喇。\n-等埋我啊……"
    res = clean.clean(workspace["id"], clean.parse(["4|一定唔得嘅啦。"]), use_lint=True, skip_lint=[1])
    s = SrtFile(workspace["srt"])
    assert s.cue(3).text == "-走喇，\n-等埋我啊…"
    assert s.cue(4).text == "一定唔得嘅啦"         # the agent's edit, then the lint fix on top
    assert s.cue(1).text == "你係咪傻㗎。"          # skipped
    by_cue = {f["cue"]: f for f in flags.load(workspace["id"])}
    assert by_cue[3]["category"] == "punctuation" and by_cue[4]["category"] == "mishearing"
    assert res["lint_remaining"].get("punctuation") == 1


def test_report_lists_cleanup_rows(workspace):
    clean.clean(workspace["id"], clean.parse(["2|阿媽實囉囉攣瞓唔着㗎"]))
    page = report.build(workspace["id"]).read_text(encoding="utf-8")
    data = json.loads(page.split('<script id="data" type="application/json">')[1].split("</script>")[0])
    item = data["items"][0]
    assert item["cleanup"] is True and item["clip"] is None and item["status"] == "applied"


def test_machine_draft():
    assert episode.machine_draft({"ai_generated": True})
    assert episode.machine_draft({"draft_origin": {"kind": "transcribe"}})
    assert episode.machine_draft({"draft_origin": {"kind": "realign", "machine": True}})
    assert not episode.machine_draft({"draft_origin": {"kind": "realign"}})


def test_lint_fix_skips_protected_words():
    from ccp import lint
    row = {"kind": "variant", "found": "果啲", "suggest": "嗰啲", "severity": "standard"}
    assert clean.lint_fix("如果啲豬太細隻", row) == "如果啲豬太細隻"
    assert clean.lint_fix("如果啲豬唔要，果啲牛要", row) == "如果啲豬唔要，嗰啲牛要"
    assert lint.occurrences("如果啲豬", "果啲") == ([], "如果")


@pytest.mark.parametrize("old, new, want", [
    ("點解出面咁嘈𠸏？", "點解出面咁嘈嘅？", "點解出面咁嘈𠸏？"),            # 𠸏 ge2 is standard
    ("乜你唔keep嘎？", "乜你唔keep㗎？", "乜你唔keep嘎？"),                # 嘎 gaa4 is standard
    ("咁大隻鑊你都孭得𠸏？", "咁大隻鑊你都孭得起嘅？", "咁大隻鑊你都孭得起𠸏？"),  # the word stays
    ("Zoe，爸，點解你咁耐唔返屋企𠸏？", "Jo飽，點解你咁耐唔返屋企嘅？", "Jo飽，點解你咁耐唔返屋企𠸏？"),
    ("點會判畀佢哋嘅唧？", "點會判畀佢哋㗎唧？", "點會判畀佢哋嘅唧？"),
    ("唔痛𠸏", "唔痛", "唔痛𠸏"),                                       # dropped particle
    ("我係超級殺啊人", "我係超級撒亞人", "我係超級撒亞人"),                 # 啊 here is no particle
    ("點解你哋嘅Sa姨唔出嚟", "點解你哋個Sa姨唔出嚟", "點解你哋個Sa姨唔出嚟"),  # possessive 嘅
    ("荷媽依然都係咁鍾意講爛嘅", "荷媽依然都係咁鍾意講爛gag", "荷媽依然都係咁鍾意講爛gag"),
    ("快啲啊，公主，唔好走", "雅典娜公主，唔好走", "雅典娜公主，唔好走"),        # phrase reheard
])
def test_keep_particles(old, new, want):
    assert clean.keep_particles(old, new)[0] == want


def test_clean_reports_kept_particles(workspace):
    srt = SrtFile(workspace["srt"])
    srt.set_text(2, "阿媽食多都亂瞓唔着𠸏")
    srt.save()
    res = clean.clean(workspace["id"], clean.parse(["2|阿媽實囉囉攣瞓唔着嘅"]))
    assert SrtFile(workspace["srt"]).cue(2).text == "阿媽實囉囉攣瞓唔着𠸏"
    assert res["particles_kept"] and res["applied"] == 1
