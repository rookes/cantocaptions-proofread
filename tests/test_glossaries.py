"""Finding a show's glossary without the shell: `ccp status` (its path, whether it exists, other
glossaries of the same show under another slug) and `ccp glossaries` (all of them)."""
import json
from pathlib import Path

import pytest

from ccp import cli, paths

TABLE = "| Correct | Jyutping | Avoid | Notes / source |\n|---|---|---|---|\n"


@pytest.fixture
def glossaries(tmp_path, monkeypatch):
    d = tmp_path / "glossaries"
    d.mkdir()
    (d / "README.md").write_text("# Show glossaries\n", encoding="utf-8")
    (d / "triumph-in-the-skies-2003.md").write_text(
        "# Triumph in the Skies (2003) glossary\n\n" + TABLE + "| 森 | sam1 | | pilot |\n| 細細粒 | sai3 sai3 nap1 | | |\n",
        encoding="utf-8")
    (d / "other-show.md").write_text("# Other Show glossary\n\n" + TABLE, encoding="utf-8")
    real = paths.get
    monkeypatch.setattr(paths, "get", lambda k: d if k == "glossaries" else real(k))
    return d


def test_status_names_the_path_and_similar_glossaries(glossaries):
    g = cli._glossary_status("triumph-in-the-skies")
    assert g["exists"] is False and Path(g["path"]).name == "triumph-in-the-skies.md"
    assert [Path(p).name for p in g["similar"]] == ["triumph-in-the-skies-2003.md"]
    g = cli._glossary_status("triumph-in-the-skies-2003")
    assert g["exists"] and g["names"] == 2 and "similar" not in g


def test_glossaries_lists_every_show(glossaries, capsys):
    cli.main(["glossaries"])
    rows = json.loads(capsys.readouterr().out)["glossaries"]
    assert [(r["show"], r["names"]) for r in rows] == [("Other Show", 0), ("Triumph in the Skies (2003)", 2)]
