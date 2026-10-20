"""Each command's fallback when a sibling repository is missing: no corpus, no dataset rules,
no cantocaptions-ai (and OCR through it when it is there)."""
import json
import subprocess
from pathlib import Path

import pytest

from conftest import needs_dictionary
from ccp import cli, corpus, ctcscore, episode, gpu_bridge, lint, paths, pipeline, reference


@pytest.fixture
def bare(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LOCAL", tmp_path / "paths.local.toml")
    paths._table.cache_clear()
    none = tmp_path / "nowhere"
    paths.write_local({"subtitles": str(none / "Subtitles"), "dataset": str(none / "ds"),
                       "cantocaptions_ai": str(none / "ccai"), "cache": str(tmp_path / "cache")})
    corpus.episodes.cache_clear()
    lint.config.cache_clear()
    ctcscore._numeral_readings.cache_clear()
    yield tmp_path
    paths._table.cache_clear()
    corpus.episodes.cache_clear()
    lint.config.cache_clear()
    ctcscore._numeral_readings.cache_clear()


def test_corpus_says_unavailable(bare, capsys):
    assert not corpus.available() and corpus.episodes() == {} and corpus.lines() == []
    cli.main(["corpus", "一定"])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "unavailable" and "cite no corpus evidence" in out["instead"]


@needs_dictionary
def test_sounds_like_falls_back_to_the_dictionary(bare, capsys):
    cli.main(["sounds-like", "囉囉攣", "--source", "both", "--counts", "-n", "3"])
    out = json.loads(capsys.readouterr().out)
    assert "words.hk only" in out["note"] and out["matches"]
    assert all("strict_corpus_count" not in m for m in out["matches"])


def test_lint_uses_the_bundled_variant_rules(bare):
    assert lint.standardization_rules() == lint.STANDARDIZATION_SNAPSHOT
    assert len(lint.config()["variants"]) > 40


def test_snapshot_matches_the_dataset_when_it_is_here():
    real = paths.get("dataset") / "rules" / "standardization.toml"
    if not real.is_file():
        pytest.skip("cantocaptions-dataset not present")
    import tomllib
    snap = tomllib.loads(lint.STANDARDIZATION_SNAPSHOT.read_text(encoding="utf-8"))
    assert snap == tomllib.loads(real.read_text(encoding="utf-8")), \
        "run scripts/build_standards.py to refresh config/standardization.snapshot.toml"


def test_numerals_are_scored_as_written_without_cantocaptions_ai(bare):
    assert ctcscore._numeral_readings()("第3集") == ["第3集"]


def test_gpu_commands_point_to_the_text_only_path(bare):
    with pytest.raises(SystemExit, match="Proofread without it"):
        gpu_bridge.require_ccai("audio evidence")


def test_pipeline_refuses_without_cantocaptions_ai(bare, workspace):
    ep = episode.load(workspace["id"])
    ep["media_exists"] = True
    episode.save(ep)
    with pytest.raises(SystemExit, match="no realign or transcription"):
        pipeline.run(workspace["id"], "realign")


def _with_streams(workspace, media):
    ep = episode.load(workspace["id"])
    ep.update(media=str(media), media_exists=True, subtitle_streams=[
        {"sub_index": 0, "stream_index": 6, "codec": "hdmv_pgs_subtitle", "kind": "bitmap",
         "language": "chi", "title": "CHT PGS", "forced": False}])
    episode.save(ep)


def test_an_image_track_without_ocr_is_named_but_not_offered(bare, workspace, tmp_path):
    _with_streams(workspace, tmp_path / "ep.mkv")
    res = reference.prepare(workspace["id"])
    assert res["status"] == "needs_decision"
    assert "There is a Chinese image track" in res["message"]
    with pytest.raises(SystemExit, match="needs cantocaptions-ai with its `ocr` extra"):
        reference.prepare(workspace["id"], stream=6, ocr=True)


def test_ocr_runs_through_cantocaptions_ai(bare, workspace, tmp_path, monkeypatch):
    media = tmp_path / "ep.mkv"
    _with_streams(workspace, media)
    monkeypatch.setattr(paths, "ccai_has_ocr", lambda: True)
    calls = []

    def fake_run(cmd, cwd=None, **kw):
        calls.append(cmd)
        out = Path(cmd[cmd.index("--output_dir") + 1])
        srt = out / "ep.ref.zh-Hant.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
        (out / "ep.references.json").write_text(json.dumps({"tracks": [
            {"stream": {"index": 6}, "path": str(srt), "error": None}], "skipped": []}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(reference.subprocess, "run", fake_run)
    res = reference.prepare(workspace["id"], stream=6, ocr=True)
    assert res["status"] == "ok" and "by cantocaptions-ai" in res["source"]
    (cmd,) = calls
    assert cmd[cmd.index("--reference_tracks") + 1] == "6" and "--references_only" in cmd
    assert (workspace["work"] / "reference.srt").read_text(encoding="utf-8").endswith("你好\n")
