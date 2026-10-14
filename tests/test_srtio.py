from pathlib import Path

import pytest

from ccp import paths
from ccp.srtio import SrtFile
from conftest import needs_cantocaptions


def test_roundtrip_bom_crlf_no_trailing_newline(workspace):
    raw = workspace["srt"].read_bytes()
    srt = SrtFile(workspace["srt"])
    assert srt.to_bytes() == raw
    assert [c.text for c in srt.cues][:2] == ["你俾我啦", "阿媽食多都亂瞓唔着㗎"]
    assert srt.cues[2].text == "-走喇\n-等埋我啊"


def test_set_text_changes_only_that_cue(workspace):
    srt = SrtFile(workspace["srt"])
    before = srt.to_bytes().decode("utf-8-sig").split("\r\n")
    srt.set_text(2, "阿媽實囉囉攣瞓唔着㗎")
    srt.set_text(3, "-走喇⏎-等等我啊")          # ⏎ is a line break
    srt.set_text(4, "一定得㗎喇")               # last cue, file has no trailing newline
    after = srt.to_bytes().decode("utf-8-sig").split("\r\n")
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert changed == [("阿媽食多都亂瞓唔着㗎", "阿媽實囉囉攣瞓唔着㗎"), ("-等埋我啊", "-等等我啊"),
                       ("一定得嘅啦", "一定得㗎喇")]
    assert srt.to_bytes().startswith(b"\xef\xbb\xbf")
    assert not srt.to_bytes().endswith(b"\n")


def test_set_text_line_count_change_keeps_later_cues(workspace):
    srt = SrtFile(workspace["srt"])
    srt.set_text(1, "你畀我⏎啦")
    srt.set_text(3, "走喇")
    reparsed = SrtFile.__new__(SrtFile)
    workspace["srt"].write_bytes(srt.to_bytes())
    reparsed = SrtFile(workspace["srt"])
    assert [c.text for c in reparsed.cues] == ["你畀我\n啦", "阿媽食多都亂瞓唔着㗎", "走喇", "一定得嘅啦"]


def test_an8_tag_is_kept(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:02,000\n{\\an8}吓？做咩啊\n", encoding="utf-8")
    srt = SrtFile(p)
    assert srt.cues[0].an8 and srt.cues[0].text == "吓？做咩啊"
    srt.set_text(1, "吓？你做咩啊")
    assert "{\\an8}吓？你做咩啊" in srt.to_bytes().decode()


@needs_cantocaptions
def test_roundtrip_real_library_files():
    files = sorted(paths.get("subtitles").glob("Series/Dubbed/*/*/*.srt"))[:40]
    if not files:
        pytest.skip("no library files found")
    for f in files:
        assert SrtFile(f).to_bytes() == f.read_bytes(), f
