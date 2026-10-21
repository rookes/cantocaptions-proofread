"""A small local web server for review reports, so the reviewer's decisions save straight into
the workspace instead of being downloaded and moved by hand.

    http://127.0.0.1:<port>/            the workspaces that have a report
    http://127.0.0.1:<port>/r/<id>/     work/<id>/report.html, with its audio clips
    GET/POST  /r/<id>/decisions         the reviewer's decisions: work/<id>/decisions.json

Standard library only, bound to 127.0.0.1. One server serves every workspace. `ccp report`
starts it when it is not running (detached: see detach.py) and reuses it when it is; it stops
itself after IDLE_S without a request. The report page still works as a plain file
(file://), downloading decisions.json, when the server is not running.

A save must be a same-origin JSON POST: a page on another site cannot send one (a JSON body
needs a CORS preflight this server never grants), and the Origin header is checked as well.

    python -m ccp.report_server STATE_FILE [IDLE_S]
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

PORTS = range(8765, 8785)          # the first free one: a stable address across restarts
IDLE_S = 6 * 3600
APP = "ccp-report"
ID_RX = re.compile(r"^[\w.\-]+$")
SERVABLE = re.compile(r"^(report\.html|clips/[\w.\-]+\.(m4a|mp4))$")


def _work() -> Path:
    from . import paths
    return paths.get("work")


class Handler(BaseHTTPRequestHandler):
    server_version = "ccp-report"
    last_request = time.time()

    def log_message(self, fmt, *args):          # quiet: no console to write to
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _workspace(self, eid: str) -> Path | None:
        if not ID_RX.match(eid):
            return None
        d = _work() / eid
        return d if (d / "episode.json").is_file() else None

    def _file(self, path: Path) -> None:
        """A static file, with byte ranges (audio players seek with them)."""
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        with path.open("rb") as f:
            if m and size:
                start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2) or 0))
                end = min(int(m.group(2)), size - 1) if m.group(1) and m.group(2) else size - 1
                if start > end or start >= size:
                    return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
                f.seek(start)
                return self._send(206, f.read(end - start + 1), ctype,
                                  {"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes"})
            self._send(200, f.read(), ctype, {"Accept-Ranges": "bytes"})

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        return origin is None or origin == f"http://{host}"

    # ---------------------------------------------------------------- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        Handler.last_request = time.time()
        path = unquote(self.path.split("?", 1)[0])
        if path == "/api/ping":
            return self._json(200, {"ok": True, "app": APP, "pid": os.getpid()})
        if path == "/":
            return self._index()
        m = re.match(r"^/r/([^/]+)(/.*)?$", path)
        if not m:
            return self._json(404, {"error": "not found"})
        d = self._workspace(m.group(1))
        if d is None:
            return self._json(404, {"error": "no such workspace"})
        rest = (m.group(2) or "/").lstrip("/") or "report.html"
        if m.group(2) is None:                       # /r/<id> -> /r/<id>/ so relative links work
            self.send_response(301)
            self.send_header("Location", f"/r/{m.group(1)}/")
            self.end_headers()
            return
        if rest == "decisions":
            f = d / "decisions.json"
            return self._json(200, json.loads(f.read_text(encoding="utf-8")) if f.exists() else {})
        if not SERVABLE.match(rest) or not (d / rest).is_file():
            return self._json(404, {"error": "not found"})
        self._file(d / rest)

    def do_POST(self):
        Handler.last_request = time.time()
        path = unquote(self.path.split("?", 1)[0])
        m = re.match(r"^/r/([^/]+)/decisions$", path)
        d = self._workspace(m.group(1)) if m else None
        if d is None:
            return self._json(404, {"error": "not found"})
        if not self._same_origin() or not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(403, {"error": "only the report page can save decisions"})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
            decisions = [x for x in data.get("decisions", []) if isinstance(x, dict) and "flag" in x]
        except (ValueError, AttributeError):
            return self._json(400, {"error": "not a decisions file"})
        out = d / "decisions.json"
        if out.exists():
            out.replace(d / "decisions.previous.json")
        tmp = d / "decisions.json.tmp"
        tmp.write_text(json.dumps({"episode_id": d.name, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "decisions": decisions}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out)
        self._json(200, {"ok": True, "saved": len(decisions), "at": time.strftime("%H:%M")})

    def _index(self):
        rows = []
        work = _work()
        reports = sorted(work.glob("*/report.html"), key=lambda p: p.stat().st_mtime, reverse=True) if work.is_dir() else []
        for p in reports:
            eid = p.parent.name
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            rows.append(f'<li><a href="/r/{eid}/">{eid}</a> <span>{when}</span></li>')
        body = ("<!doctype html><meta charset='utf-8'><title>Proofreading reports</title>"
                "<style>body{font:15px system-ui,sans-serif;max-width:720px;margin:32px auto;padding:0 16px}"
                "li{margin:6px 0}span{color:#888;font-size:13px;margin-left:8px}</style>"
                "<h1>Proofreading reports</h1><ul>" + ("".join(rows) or "<li>No reports yet.</li>") + "</ul>")
        self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")


def serve(state_file: Path, idle_s: float = IDLE_S) -> None:
    httpd = None
    for port in PORTS:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"no free port in {PORTS.start}-{PORTS.stop - 1}")
    state_file.write_text(json.dumps({"pid": os.getpid(), "port": httpd.server_address[1],
                                      "started": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")

    def watch():
        while True:
            time.sleep(60)
            if time.time() - Handler.last_request > idle_s:
                httpd.shutdown()
                return
    threading.Thread(target=watch, daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        try:
            if json.loads(state_file.read_text(encoding="utf-8")).get("pid") == os.getpid():
                state_file.unlink()
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------------------- client side

def _state_path() -> Path:
    from . import paths
    return paths.cache_dir() / "report_server.json"


def running() -> dict | None:
    """{"pid", "port", "url"} of the running server, or None."""
    import urllib.request
    p = _state_path()
    if not p.exists():
        return None
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{state['port']}"
        with urllib.request.urlopen(url + "/api/ping", timeout=2) as r:
            if json.loads(r.read().decode("utf-8")).get("app") == APP:
                return {**state, "url": url}
    except (OSError, ValueError, KeyError):
        pass
    return None


def ensure(timeout_s: float = 20) -> dict:
    """The running server, started (detached) when there is none. Raises RuntimeError."""
    s = running()
    if s:
        return s
    from . import paths
    from .detach import launch, windowless_python
    state = _state_path()
    state.unlink(missing_ok=True)
    launch([str(windowless_python(Path(sys.executable))), "-m", "ccp.report_server", str(state)], paths.ROOT)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        s = running()
        if s:
            return s
        time.sleep(0.3)
    raise RuntimeError("the report server did not start")


def report_url(episode_id: str) -> str | None:
    s = running()
    return f"{s['url']}/r/{episode_id}/" if s else None


if __name__ == "__main__":
    serve(Path(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else IDLE_S)
