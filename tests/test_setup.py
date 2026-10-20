"""`ccp setup`: what is missing, the first-use questions, and recording the answers in
config/paths.local.toml without losing what is already there."""
import tomllib

import pytest

from ccp import paths, setup


@pytest.fixture
def bare(tmp_path, monkeypatch):
    """A machine with none of the sibling repositories: every one points somewhere empty."""
    monkeypatch.setattr(paths, "LOCAL", tmp_path / "paths.local.toml")
    paths._table.cache_clear()
    none = tmp_path / "nowhere"
    paths.write_local({"cantocaptions": str(none / "CantoCaptions"),
                       "subtitles": str(none / "CantoCaptions" / "Subtitles"),
                       "dataset": str(none / "dataset"), "cantocaptions_ai": str(none / "ccai"),
                       "media_root": str(none / "media"), "cache": str(tmp_path / "cache"),
                       "work": str(tmp_path / "work")})
    yield tmp_path
    paths._table.cache_clear()


def test_first_run_asks_for_every_missing_resource(bare):
    st = setup.status()
    assert st["first_run"]
    assert st["ask"] == ["cantocaptions", "dataset", "cantocaptions_ai", "media_dirs"]
    caps = st["capabilities"]
    assert caps["locate_mode"] == "paths_only"
    assert not caps["audio_evidence"] and not caps["corpus"] and not caps["ocr"]
    assert caps["lint_rules"] == "snapshot"
    assert all(m["enables"] and m["without"] for m in st["missing"])


def test_answers_are_recorded_and_not_asked_again(bare):
    media = bare / "My Videos"
    media.mkdir()
    st = setup.apply([], [str(media)], [], ["cantocaptions", "dataset", "cantocaptions_ai"], done=True)
    assert not st["first_run"] and st["ask"] == [] and "problems" not in st
    assert st["capabilities"]["locate_mode"] == "media_dirs"
    local = tomllib.loads(paths.LOCAL.read_text(encoding="utf-8"))
    assert local["setup"] == {"declined": ["cantocaptions", "cantocaptions_ai", "dataset"], "completed": True}
    # The overrides that were there are kept.
    assert local["paths"]["dataset"].endswith("nowhere/dataset")
    assert [str(d) for d in paths.media_dirs()] == [str(media)]


def test_a_bad_path_is_refused_and_a_good_one_clears_its_decline(bare):
    setup.apply([], [], [], ["dataset"], done=False)
    st = setup.apply(["dataset=" + str(bare / "missing")], [], [], [], done=False)
    assert st["problems"] == [f"dataset: {bare / 'missing'} does not exist; not saved"]
    ds = bare / "ds"
    (ds / "data").mkdir(parents=True)
    st = setup.apply([f"dataset={ds}"], [], [], [], done=False)
    assert st["problems"] == [f"dataset: {ds} has no data/manifest.json (run its scan); not saved"]
    (ds / "data" / "manifest.json").write_text('{"records": []}', encoding="utf-8")
    st = setup.apply([f"dataset={ds}"], [], [], [], done=False)
    assert "problems" not in st
    assert st["capabilities"]["dataset"]
    assert "dataset" not in paths.setup_state()["declined"]


def test_media_dirs_can_be_removed_and_unknown_keys_are_reported(bare):
    a, b = bare / "a", bare / "b"
    a.mkdir(), b.mkdir()
    setup.apply([], [str(a), str(b)], [], [], done=False)
    st = setup.apply(["nonsense=x"], [], [str(a)], ["sub_convert"], done=False)
    assert [str(d) for d in paths.media_dirs()] == [str(b)]
    assert len(st["problems"]) == 2


def test_with_the_dataset_media_folders_are_not_asked_for(bare):
    ds, media = bare / "ds", bare / "media"
    (ds / "data").mkdir(parents=True)
    (ds / "data" / "manifest.json").write_text('{"records": []}', encoding="utf-8")
    media.mkdir()
    subs = bare / "cc" / "Subtitles"
    subs.mkdir(parents=True)
    setup.apply([f"dataset={ds}", f"media_root={media}", f"cantocaptions={bare / 'cc'}"], [], [], [], False)
    st = setup.status()
    assert st["capabilities"]["locate_mode"] == "dataset"
    assert "media_dirs" not in st["ask"] and "media_root" not in st["ask"]
