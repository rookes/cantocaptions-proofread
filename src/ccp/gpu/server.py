"""The GPU server: keeps the ASR models loaded between `ccp listen` (and `ccp particles model`)
calls, so a proofreading pass loads each model once instead of once per call. (`ccp score` needs no GPU: it reads the
emissions `ccp evidence` stored.)

    pythonw server.py <state.json> <idle seconds>

Runs in cantocaptions-ai's interpreter. gpu_bridge starts it on the first listen call, outside the calling command's process tree (agent harnesses end that tree when a
command returns), and stops it when the pass is over (report, apply, export, publish, prune),
before anything else needs the GPU (evidence, pipeline), or after `idle` seconds unused.

Both recognisers (about 4 GB each) fit together on a 10 GB card when nothing else holds much
memory; when they do not, the server unloads the least recently used one to make room, and
`listen` runs the recogniser already loaded first, so a request swaps at most one model.

HTTP on 127.0.0.1, one request at a time; every request carries the token from the state file.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATE = Path(sys.argv[1])
IDLE = float(sys.argv[2]) if len(sys.argv) > 2 else 900.0
LOG = STATE.with_suffix(".log")
# pythonw has no console: everything printed (model loading, progress) goes to the log.
sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)

import _common  # noqa: E402  (sets up sys.path for cantocaptions_ai and ccp)
from _common import SAMPLE_RATE, free, load_asr, load_isolation, load_media_audio  # noqa: E402

NEED_MB = {"ft": 4400, "qw": 4200, "isolate": 2500}
MARGIN_MB = 300
TOKEN = secrets.token_hex(16)


def free_mb() -> float:
    import torch
    return torch.cuda.mem_get_info()[0] / 1e6


class Models:
    def __init__(self):
        self.loaded: dict[str, object] = {}
        self.used: dict[str, float] = {}

    def make_room(self, name: str) -> None:
        while free_mb() < NEED_MB[name] + MARGIN_MB:
            others = [n for n in self.loaded if n != name]
            if not others:
                return                  # nothing left to unload; try anyway
            victim = min(others, key=lambda n: self.used[n])
            self.unload(victim)

    def unload(self, name: str) -> None:
        print(f"unloading {name}", flush=True)
        del self.loaded[name]
        self.used.pop(name, None)
        free()

    def get(self, name: str):
        if name not in self.loaded:
            self.make_room(name)
            print(f"loading {name}", flush=True)
            self.loaded[name] = load_asr(name)
        self.used[name] = time.time()
        return self.loaded[name]

    def order(self, tags: list[str]) -> list[str]:
        return sorted(tags, key=lambda t: t not in self.loaded)

    def isolate(self, clips):
        """Vocal isolation is rare: loaded for the request, after making room, then dropped."""
        self.make_room("isolate")
        proc = load_isolation()
        items = [{"audio_path": f"clip{i}", "vad_segments": [
            {"start": 0.0, "end": len(c) / SAMPLE_RATE, "audio": c}]} for i, c in enumerate(clips)]
        out = proc.run(items)
        del proc
        free()
        return [it["vad_segments"][0]["audio"] for it in out]


MODELS = Models()
AUDIO: dict[tuple, object] = {}          # (media, track) -> the episode's 16 kHz audio
LAST = time.time()


def clip_fn(req: dict):
    key = (req["media"], int(req.get("audio_track", 0)))
    if key not in AUDIO:
        if len(AUDIO) >= 2:
            AUDIO.pop(next(iter(AUDIO)))
        AUDIO[key] = load_media_audio(*key)
    audio = AUDIO[key]
    return lambda s, e: audio[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)]


def run(script: str, req: dict) -> dict:
    if script == "listen":
        import listen
        return listen.handle(req, clip_fn(req), stage_for=MODELS.get, order=MODELS.order,
                             isolator=MODELS.isolate)
    if script == "particles":
        import particles
        return particles.handle(req, clip_fn(req), stage_for=MODELS.get)
    raise ValueError(f"unknown script {script!r}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{time.strftime('%H:%M:%S')} {fmt % args}", flush=True)

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global LAST
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if data.get("token") != TOKEN:
            return self._reply(403, {"ok": False, "error": "bad token"})
        if self.path == "/status":            # a status check does not count as use
            return self._reply(200, {"ok": True, "pid": os.getpid(), "loaded": list(MODELS.loaded),
                                     "idle_s": round(time.time() - LAST), "free_mb": round(free_mb())})
        LAST = time.time()
        if self.path == "/stop":
            self._reply(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path == "/run":
            t0 = time.time()
            try:
                result = run(data["script"], data["request"])
            except Exception as e:  # noqa: BLE001 - reported to the caller
                traceback.print_exc()
                if "out of memory" in str(e).lower():
                    for name in list(MODELS.loaded):
                        MODELS.unload(name)
                return self._reply(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            LAST = time.time()
            return self._reply(200, {"ok": True, "result": result, "seconds": round(time.time() - t0, 1),
                                     "loaded": list(MODELS.loaded)})
        self._reply(404, {"ok": False, "error": "unknown path"})


def watch_idle(server: HTTPServer) -> None:
    while True:
        time.sleep(15)
        if time.time() - LAST > IDLE:
            print(f"idle for {IDLE:.0f} s: stopping", flush=True)
            server.shutdown()
            return


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    STATE.write_text(json.dumps({"pid": os.getpid(), "port": server.server_address[1], "token": TOKEN,
                                 "started": time.strftime("%Y-%m-%d %H:%M:%S"), "idle_s": IDLE}),
                     encoding="utf-8")
    print(f"listening on 127.0.0.1:{server.server_address[1]} (pid {os.getpid()})", flush=True)
    threading.Thread(target=watch_idle, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
            if state.get("pid") == os.getpid():
                STATE.unlink()
        except (OSError, ValueError):
            pass
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
