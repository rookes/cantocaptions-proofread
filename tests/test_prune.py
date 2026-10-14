"""ccp prune removes only bulky, regenerable files, and finds finished workspaces."""
import json

from ccp import flags, prune


def _bulk(ws):
    w = ws["work"]
    for rel in ["emissions/g0000.npy", "clips/flag_1.m4a", "output/clips/flag_1.m4a",
                "pipeline/transcribe-1/debug/03/vad/segment_0001.wav", "previous/20260101/emissions/g0000.npy",
                "source/audio.webm"]:
        p = w / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 2_000_000)
    for rel in ["pipeline/transcribe-1/audio.srt", "pipeline/transcribe-1/run.log", "output/x.yue.srt",
                "report.html", "evidence.jsonl", "previous/20260101/flags.jsonl"]:
        p = w / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("keep", encoding="utf-8")
    return w


def test_prune_removes_bulk_and_keeps_records(workspace):
    w = _bulk(workspace)
    dry = prune.prune(workspace["id"], dry_run=True)
    assert dry["frees_mb"] == 10.0 and (w / "emissions").exists()
    res = prune.prune(workspace["id"])
    for gone in ["emissions", "clips", "output/clips", "pipeline/transcribe-1/debug", "previous/20260101/emissions"]:
        assert not (w / gone).exists(), gone
    for kept in ["source/audio.webm", "pipeline/transcribe-1/audio.srt", "pipeline/transcribe-1/run.log",
                 "output/x.yue.srt", "report.html", "evidence.jsonl", "previous/20260101/flags.jsonl", "episode.json"]:
        assert (w / kept).exists(), kept
    assert json.loads((w / "episode.json").read_text(encoding="utf-8"))["pruned"]["freed_mb"] == res["frees_mb"]
    assert prune.prune(workspace["id"], downloads=True)["remove"] == {"source\\audio.webm": 2.0} or \
        not (w / "source/audio.webm").exists()
    assert not (w / "source/audio.webm").exists()


def test_finished_means_no_open_flags_or_exported(workspace):
    from ccp import episode
    ep = episode.load(workspace["id"])
    f = flags.add(workspace["id"], 2, "mishearing", "fix", "阿媽實囉囉攣瞓唔着㗎", ["context: t"], "the draft does not fit the scene; test reason")
    assert not prune.finished(ep, flags.load(workspace["id"]))
    flags.update(workspace["id"], f["id"], status="applied")
    assert prune.finished(ep, flags.load(workspace["id"]))
