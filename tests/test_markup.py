"""Markup and invisible characters: shown to the agent (they are hidden from the text), fixable
through ccp, and kept (markup) or removed (invisible characters) without touching the rest."""
from ccp import apply, clean, cli, flags, lint, render
from ccp.srtio import SrtFile

R = "a zero-width space sits between 呢 and 笪; it should go"


def _prepare(ws):
    srt = SrtFile(ws["srt"])
    srt.set_text(2, "呢​笪地方已經畀女王詛咒啊")
    srt.set_text(4, '<font color="#ffff00">一定得嘅啦</font>')
    srt.save()


def test_hidden_content_is_shown(workspace, capsys):
    _prepare(workspace)
    srt = SrtFile(workspace["srt"])
    assert srt.cue(2).text == "呢笪地方已經畀女王詛咒啊"
    assert srt.cue(2).shown == "呢⟨U+200B⟩笪地方已經畀女王詛咒啊"
    assert srt.cue(4).shown == '<font color="#ffff00">一定得嘅啦</font>'
    hits = [h for h in lint.check_cue(srt.cue(2)) if h["kind"] == "invisible"]
    assert hits and hits[0]["found"] == "U+200B ZERO WIDTH SPACE" and "after 呢" in hits[0]["note"]
    cli.main(["cue", workspace["id"], "2", "4"])
    out = capsys.readouterr().out
    assert "raw    呢⟨U+200B⟩笪" in out and 'raw    <font color="#ffff00">' in out
    assert '⟨markup: <font color="#ffff00">⟩' in render.render(workspace["id"])


def test_proposing_the_visible_text_removes_the_invisible_character(workspace):
    _prepare(workspace)
    f = flags.add(workspace["id"], 2, "standard", "fix", "呢笪地方已經畀女王詛咒啊", [], R)
    assert f["strip_invisible"] and f["draft_shown"] == "呢⟨U+200B⟩笪地方已經畀女王詛咒啊"
    res = apply.apply(workspace["id"])
    assert [a["cue"] for a in res["applied"]] == [2]
    raw = workspace["srt"].read_text(encoding="utf-8-sig")
    assert "​" not in raw and "呢笪地方已經畀女王詛咒啊" in raw


def test_editing_a_coloured_line_keeps_its_colour(workspace):
    _prepare(workspace)
    flags.add(workspace["id"], 4, "mishearing", "fix", "一定唔得嘅啦", [], "the line needs 唔 to mean 'cannot'")
    apply.apply(workspace["id"])
    assert SrtFile(workspace["srt"]).cue(4).raw == '<font color="#ffff00">一定唔得嘅啦</font>'


def test_clean_lint_removes_invisible_characters_only(workspace):
    _prepare(workspace)
    srt = SrtFile(workspace["srt"])
    srt.set_text(3, '<font color="#ff00ff">-走喇​</font>⏎-等埋我啊')
    srt.save()
    clean.clean(workspace["id"], [], use_lint=True)
    s = SrtFile(workspace["srt"])
    assert not s.cue(2).invisible and not s.cue(3).invisible
    assert s.cue(3).raw == '<font color="#ff00ff">-走喇</font>\n-等埋我啊'      # markup kept
