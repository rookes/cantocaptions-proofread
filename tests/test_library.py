"""Finding files the dataset manifest does not cover (AI-generated trees, genre folders),
matching media folders by show name, and main-area publishing paths."""
import pytest

from ccp import locate, paths
from ccp.pipeline import _library_name, main_area_path


@pytest.fixture
def library(tmp_path, monkeypatch):
    subs = tmp_path / "Subtitles"
    ai = subs / "Series" / "Original (AI-generated)"
    (ai / "Moonlight Resonance -- 家好月圓").mkdir(parents=True)
    (ai / "Moonlight Resonance -- 家好月圓" / "[CCAI] Moonlight.Resonance.E01.1080i.HDTV.srt").write_text("x", encoding="utf-8")
    anime = subs / "Series" / "Dubbed (AI-generated)" / "Anime" / "Some Show (2018)" / "S2"
    anime.mkdir(parents=True)
    (anime / "[CCAI] S02E008_Title.srt").write_text("x", encoding="utf-8")
    main = subs / "Series" / "Original" / "Journey to the West -- 西遊記 (1996)"
    main.mkdir(parents=True)
    (main / "Journey.to.the.West.E01.yue.cht.srt").write_text("x", encoding="utf-8")
    media = tmp_path / "media" / "Series" / "Original" / "Moonlight Resonance"
    media.mkdir(parents=True)
    (media / "Jade.Moonlight.Resonance.E01.1080i.HDTV.H264-NGB.mkv").write_bytes(b"")
    (media / "Jade.Moonlight.Resonance.E02.1080i.HDTV.H264-NGB.mkv").write_bytes(b"")
    real_get = paths.get
    monkeypatch.setattr(paths, "get", lambda k: {"subtitles": subs, "media_root": tmp_path / "media"}.get(k) or real_get(k))
    monkeypatch.setattr(locate, "manifest", lambda: [])
    locate.catalog.cache_clear()
    locate._is_show_dir.cache_clear()
    yield subs
    locate.catalog.cache_clear()
    locate._is_show_dir.cache_clear()


def test_catalog_skips_genre_folders(library):
    by_show = {e["show_folder"]: e for e in locate.catalog()}
    assert set(by_show) == {"Moonlight Resonance -- 家好月圓", "Some Show (2018)", "Journey to the West -- 西遊記 (1996)"}
    assert by_show["Some Show (2018)"]["ai_generated"] and by_show["Some Show (2018)"]["episodes"] == [8]
    assert by_show["Some Show (2018)"]["season"] == 2


def test_find_ai_episode_with_media_by_show_name(library):
    r = locate.find("AI subtitles for Moonlight Resonance episode 1")
    assert len(r["candidates"]) == 1
    c = r["candidates"][0]
    assert c["ai_generated"] and c["media"].endswith("E01.1080i.HDTV.H264-NGB.mkv")
    assert locate.by_id(c["episode_id"])["show_folder"] == "Moonlight Resonance -- 家好月圓"


def test_show_names_bridge_separator_styles():
    assert locate.show_names("Journey To the West - 西遊記") & locate.show_names("Journey to the West -- 西遊記 (1996)")
    assert not locate.show_names("Moonlight Resonance") & locate.show_names("Triumph in the Skies -- 衝上雲霄")


def test_main_area_path(library):
    ep = {"source_srt": str(library / "Series" / "Original (AI-generated)" / "Moonlight Resonance -- 家好月圓"
                            / "[CCAI] Moonlight.Resonance.E01.1080i.HDTV.srt"),
          "show_folder": "Moonlight Resonance -- 家好月圓"}
    target, notes = main_area_path(ep)
    assert target == library / "Series" / "Original" / "Moonlight Resonance -- 家好月圓" / "Moonlight.Resonance.E01.1080i.HDTV.yue.cht.srt"
    assert "new folder" in notes[0]
    ep2 = {"source_srt": str(library / "Series" / "Dubbed (AI-generated)" / "Anime" / "Some Show (2018)" / "S2"
                             / "[CCAI] S02E008_Title.srt"), "show_folder": "Some Show (2018)"}
    target2, _ = main_area_path(ep2)
    assert target2 == library / "Series" / "Dubbed" / "Some Show (2018)" / "S2" / "S02E008_Title.yue.cht.srt"


def test_library_name():
    assert _library_name("[CCAI] X.E01.srt") == "X.E01.yue.cht.srt"
    assert _library_name("[WIP]Re-Zero_2016.S1E03.yue.cht.srt") == "Re-Zero_2016.S1E03.yue.cht.srt"
