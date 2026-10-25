"""The local report server: serving a workspace's report and clips, saving the reviewer's
decisions into it, refusing anything else; and `ccp apply --reviewed` reading them back."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ccp import cli, episode, flags, report_server


@pytest.fixture
def server(workspace, monkeypatch):
    monkeypatch.setattr(report_server, "_work", lambda: workspace["work"].parent)
    (workspace["work"] / "report.html").write_text("<!doctype html><p>report</p>", encoding="utf-8")
    (workspace["work"] / "clips").mkdir()
    (workspace["work"] / "clips" / "flag_1.m4a").write_bytes(bytes(range(256)) * 4)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), report_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def _post(url, body, origin=None, ctype="application/json"):
    headers = {"Content-Type": ctype}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_serves_the_report_and_clips_with_ranges(server):
    status, body, _ = _get(server + "/r/t/")
    assert status == 200 and b"report" in body
    status, body, headers = _get(server + "/r/t/clips/flag_1.m4a", {"Range": "bytes=10-19"})
    assert status == 206 and body == bytes(range(10, 20)) and headers["Content-Range"] == "bytes 10-19/1024"
    assert _get(server + "/r/t/episode.json")[0] == 404           # only the report and its clips
    assert _get(server + "/r/t/..%2F..%2Fpaths.toml")[0] == 404
    assert _get(server + "/r/nope/")[0] == 404
    assert b"/r/t/" in _get(server + "/")[1]                       # the index lists it


def test_saves_decisions_from_the_page_only(server, workspace):
    from ccp import flags
    flags.add("t", 1, "standard", "fix", "你畀我啦", ["lint: 俾"], "convention: 俾 → 畀 (variant)")
    good = {"episode_id": "t", "decisions": [{"flag": 1, "decision": "accepted", "text": "你畀我啦"}]}
    stray = {"episode_id": "t", "decisions": good["decisions"] + [{"flag": 99, "decision": "rejected"}]}
    assert _post(server + "/r/t/decisions", stray, origin=server)[1]["saved"] == 1   # not this round's
    status, reply = _post(server + "/r/t/decisions", good, origin=server)
    assert status == 200 and reply["ok"] and reply["saved"] == 1
    saved = json.loads((workspace["work"] / "decisions.json").read_text(encoding="utf-8"))
    assert saved["decisions"] == good["decisions"] and saved["saved"]
    assert _post(server + "/r/t/decisions", good, origin="http://evil.example")[0] == 403
    assert _post(server + "/r/t/decisions", good, origin=server, ctype="text/plain")[0] == 403
    # A second save keeps the first as decisions.previous.json; GET returns the latest.
    _post(server + "/r/t/decisions", {"decisions": []}, origin=server)
    assert (workspace["work"] / "decisions.previous.json").exists()
    assert json.loads(_get(server + "/r/t/decisions")[1])["decisions"] == []


def test_apply_reviewed_uses_the_saved_decisions(workspace, capsys):
    f = flags.add(workspace["id"], 1, "standard", "fix", "你畀我啦", [], "俾 is not the convention: 畀")
    with pytest.raises(SystemExit, match="no saved decisions yet"):
        cli.main(["apply", workspace["id"], "--reviewed"])
    episode.path(workspace["id"], "decisions.json").write_text(json.dumps(
        {"decisions": [{"flag": f["id"], "decision": "accepted", "text": "你畀我啦"}]}), encoding="utf-8")
    cli.main(["apply", workspace["id"], "--reviewed"])
    out = json.loads(capsys.readouterr().out)
    assert [a["to"] for a in out["applied"]] == ["你畀我啦"]


def test_report_link_without_the_server(workspace):
    page = workspace["work"] / "report.html"
    page.write_text("x", encoding="utf-8")
    link = cli._report_link(workspace["id"], page, serve=False, open_browser=False)
    assert link["open"].startswith("file:") and "Export decisions" in link["tell_the_user"]
    assert "--decisions <path>" in link["saves_decisions"]


def test_stops_when_nobody_is_looking():
    rs, t0 = report_server, 1_000_000.0
    # Never opened: kept for UNOPENED_S, in case the user opens the link later.
    assert rs.should_stop(t0 + 60, t0, t0, None) is None
    assert rs.should_stop(t0 + rs.UNOPENED_S + 1, t0, t0, None) == "the report was never opened"
    # Opened: kept while a page checks in, stopped CLOSED_S after the last one.
    beat = t0 + 3600
    assert rs.should_stop(beat + 60, t0, beat, beat) is None
    assert rs.should_stop(beat + rs.CLOSED_S + 1, t0, beat, beat) == "every report page has been closed"


def test_heartbeat_and_stop_endpoints(server):
    report_server.Handler.last_heartbeat = None
    assert _get(server + "/api/heartbeat")[0] == 200
    assert report_server.Handler.last_heartbeat is not None
    assert _post(server + "/api/stop", {}, origin="http://evil.example")[0] == 403
    status, reply = _post(server + "/api/stop", {})
    assert status == 200 and reply["stopping"]


def test_a_server_that_cannot_start_says_to_leave_the_sandbox(tmp_path, monkeypatch):
    from ccp import cli, report_server
    def fail():
        raise RuntimeError("it did not answer within 20 s")
    monkeypatch.setattr(report_server, "ensure", fail)
    page = tmp_path / "report.html"
    page.write_text("<html></html>", encoding="utf-8")
    out = cli._report_link("t", page, serve=True, open_browser=False)
    assert "outside the sandbox" in out["server"] and out["open"].startswith("file:")


def test_the_gpu_server_fallback_is_reported(monkeypatch):
    from ccp import gpu_bridge
    def unavailable(script, request):
        raise gpu_bridge.ServerUnavailable("the GPU server did not start")
    monkeypatch.setattr(gpu_bridge, "require_ccai", lambda what: None)
    monkeypatch.setattr(gpu_bridge, "_served", unavailable)
    monkeypatch.setattr(gpu_bridge, "_one_shot", lambda script, request, timeout=None: {"items": []})
    monkeypatch.setattr(gpu_bridge, "NOTES", [])
    assert gpu_bridge.run("listen", {}) == {"items": []}
    assert "outside the sandbox" in gpu_bridge.NOTES[0]
