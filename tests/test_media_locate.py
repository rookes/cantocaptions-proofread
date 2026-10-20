"""Finding an episode's media by name in the user's own media folders, on a machine with no
library and no dataset (locate.search_media / find), and the fallbacks of `ccp locate`."""
import json
from pathlib import Path

import pytest

from ccp import cli, locate, paths


@pytest.fixture
def media(tmp_path, monkeypatch):
    root = tmp_path / "Videos"
    show = root / "Show A -- 甲乙 (2020)" / "Season 1"
    show.mkdir(parents=True)
    (show / "03.mkv").write_bytes(b"")
    (show / "Show.A.S01E04.1080p.WEB.mkv").write_bytes(b"")
    (show / "Show.A.S01E04.1080p.WEB.yue.srt").write_text("x", encoding="utf-8")
    (show / "Show.A.S01E04.zh.srt").write_text("x", encoding="utf-8")
    (root / "Other Show").mkdir()
    (root / "Other Show" / "03.mkv").write_bytes(b"")
    (root / "[Group] Third Thing - 03 (BD 1080p) [ABCD1234].mkv").write_bytes(b"")
    monkeypatch.setattr(paths, "LOCAL", tmp_path / "paths.local.toml")
    paths._table.cache_clear()
    none = tmp_path / "nowhere"
    paths.write_local({"subtitles": str(none / "Subtitles"), "dataset": str(none / "ds"),
                       "cantocaptions_ai": str(none / "ccai"), "media_root": str(none / "m"),
                       "cache": str(tmp_path / "cache"), "work": str(tmp_path / "work"),
                       "media_dirs": [str(root)]})
    locate.manifest.cache_clear()
    locate.catalog.cache_clear()
    yield root
    paths._table.cache_clear()
    locate.manifest.cache_clear()
    locate.catalog.cache_clear()


def test_title_part():
    assert locate.title_part("[MiniMTBB] Shingeki no Kyojin - 26 (BD 1080p) [8A68A9A7]") == "Shingeki no Kyojin"
    assert locate.title_part("Ghost.in.the.Shell.S01E01.1080p-Main10") == "Ghost in the Shell"
    assert locate.title_part("Triumph.in.the.Skies.2003.DVD.E01") == "Triumph in the Skies"
    assert locate.title_part("03") == ""


def test_find_without_a_library_searches_the_media_folders(media):
    r = locate.find("Show A S1E03")
    assert r["candidates"] == [] and r["needs_confirmation"]
    (best, *rest) = r["media_candidates"]
    assert Path(best["path"]).parts[-3:] == ("Show A -- 甲乙 (2020)", "Season 1", "03.mkv")
    assert best["suggested_id"] == "show-a-2020_s01e03_local"
    assert all("Other Show" not in c["path"] for c in r["media_candidates"])


@pytest.mark.parametrize("request_text", ["甲乙 第4集", "SA S1E4", "show a season 1 episode 4"])
def test_other_ways_of_naming_the_show(media, request_text):
    (best, *_) = locate.search_media(request_text)["media_candidates"]
    assert best["path"].endswith("Show.A.S01E04.1080p.WEB.mkv")
    assert [Path(p).name for p in best["subtitles_near"]] == [
        "Show.A.S01E04.1080p.WEB.yue.srt", "Show.A.S01E04.zh.srt"]


def test_release_names_match_by_their_title(media):
    (best, *_) = locate.search_media("third thing 3")["media_candidates"]
    assert "Third Thing" in best["path"]


def test_nothing_matching_says_so(media):
    r = locate.search_media("Unknown Programme E09")
    assert r["media_candidates"] == [] and "nothing in the media folders" in r["note"]


def test_the_index_is_cached_until_a_rescan(media):
    locate.search_media("Show A S1E03")
    (media / "Show A -- 甲乙 (2020)" / "Season 1" / "Show.A.S01E05.mkv").write_bytes(b"")
    assert locate.search_media("Show A S1E05")["media_candidates"] == []
    assert locate.search_media("Show A S1E05", rescan=True)["media_candidates"]


def test_locate_never_creates_a_workspace_from_a_fuzzy_match(media, capsys):
    cli.main(["locate", "Show A S1E03"])
    out = json.loads(capsys.readouterr().out)
    assert out["needs_confirmation"] and "workspace" not in out
    assert not (paths.get("work")).exists() or not any(paths.get("work").iterdir())


def test_a_subtitle_outside_the_library_gets_media_candidates(media, tmp_path, capsys):
    srt = tmp_path / "mine" / "Show.A.S01E04.yue.srt"
    srt.parent.mkdir()
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    cli.main(["locate", "--srt", str(srt), "--id", "mine"])
    out = json.loads(capsys.readouterr().out)
    assert out["media"] is None and out["needs_confirmation"]
    assert out["media_candidates"][0]["path"].endswith("Show.A.S01E04.1080p.WEB.mkv")


def test_without_media_folders_locate_asks_for_the_files(media, capsys):
    paths.write_local({"media_dirs": []})
    r = locate.find("Show A S1E03")
    assert r["media_candidates"] == [] and "ccp setup --add-media-dir" in r["note"]
