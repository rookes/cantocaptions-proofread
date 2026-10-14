from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccp import paths

HERE = Path(__file__).resolve().parent


def _exists(key: str) -> bool:
    try:
        return paths.get(key).exists()
    except Exception:
        return False


needs_dictionary = pytest.mark.skipif(not _exists("dictionary"), reason="words.hk dictionary not present")
needs_corpus = pytest.mark.skipif(
    not (_exists("dataset") and (paths.get("dataset") / "data" / "std" / "episodes.json").exists()
         and _exists("subtitles")),
    reason="cantocaptions-dataset tiers or CantoCaptions not present")
needs_cantocaptions = pytest.mark.skipif(not _exists("subtitles"), reason="CantoCaptions not present")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A throwaway episode workspace with a small SRT (BOM + CRLF), no media."""
    work = tmp_path / "work"
    monkeypatch.setattr(paths, "work_dir", lambda eid: (work / eid).mkdir(parents=True, exist_ok=True) or work / eid)
    srt = tmp_path / "ep.srt"
    body = ("1\r\n00:00:01,000 --> 00:00:02,500\r\n你俾我啦\r\n\r\n"
            "2\r\n00:00:03,000 --> 00:00:04,000\r\n阿媽食多都亂瞓唔着㗎\r\n\r\n"
            "3\r\n00:00:04,200 --> 00:00:06,000\r\n-走喇\r\n-等埋我啊\r\n\r\n"
            "4\r\n00:00:09,000 --> 00:00:10,000\r\n一定得嘅啦")
    srt.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    ep = {"episode_id": "t", "srt": str(srt), "media": None, "media_exists": False,
          "tier": "unknown", "show_slug": "test-show", "reference_files": []}
    (work / "t").mkdir(parents=True)
    (work / "t" / "episode.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    return {"id": "t", "srt": srt, "work": work / "t"}
