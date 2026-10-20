"""Run GPU work inside cantocaptions-ai's venv and return its JSON result.

`evidence` runs as a one-shot script:
`uv run --project <cantocaptions-ai> --no-sync python src/ccp/gpu/<name>.py req res`.
--no-sync matters: a sync would uninstall cantocaptions-ai's locally installed flash-attn
wheel. Requests and results go through JSON files, never the command line, so CJK text and
Windows quoting cannot collide.

`listen` goes to the GPU server (gpu/server.py), which keeps the ASR models loaded across
calls. (`score` never comes here: it reads the emissions `evidence` stored, on the CPU.) Agent harnesses end a command's whole process tree when the
command returns, so the server is started outside it: on Windows through WMI
(Win32_Process.Create, which parents it to the WMI service, with a hidden window), elsewhere
in a new session. It stops itself after IDLE_S unused, and `stop_server()` ends it when a pass
is over or before other GPU work. If it cannot be started, the one-shot scripts are used.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

GPU_DIR = Path(__file__).resolve().parent / "gpu"
SERVED = {"listen"}
IDLE_S = 900                    # the server stops itself after this long unused
START_TIMEOUT_S = 60


class ServerUnavailable(Exception):
    pass


NO_CCAI = ("{what} needs cantocaptions-ai, which is not set up on this machine (looked in {path}). "
           "Proofread without it: review against the reference, lint and the conventions, and say "
           "that the audio was not checked. If the user has it, `ccp setup --set cantocaptions_ai=PATH`.")


def require_ccai(what: str) -> Path:
    """cantocaptions-ai's folder, or an error saying how to carry on without it."""
    ccai = paths.get("cantocaptions_ai")
    if not paths.has("cantocaptions_ai"):
        raise SystemExit(NO_CCAI.format(what=what, path=ccai))
    return ccai


def _ccai() -> Path:
    return require_ccai("this command")


def _state_path() -> Path:
    return paths.cache_dir() / "gpu_server.json"


def _post(state: dict, path: str, payload: dict, timeout: float) -> dict:
    body = json.dumps({**payload, "token": state["token"]}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{state['port']}{path}", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8") or "{}")


def _alive() -> dict | None:
    p = _state_path()
    if not p.exists():
        return None
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        status = _post(state, "/status", {}, timeout=5)
        return {**state, **status} if status.get("ok") else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def server_status() -> dict | None:
    """The running server's pid, loaded models and idle time, or None."""
    s = _alive()
    return {k: s[k] for k in ("pid", "loaded", "idle_s", "started") if k in s} if s else None


def _launch() -> None:
    ccai = _ccai()
    scripts = ccai / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    py = next((p for p in (scripts / "pythonw.exe", scripts / "python.exe", scripts / "python") if p.exists()), None)
    if py is None:
        raise ServerUnavailable(f"no python in {scripts}")
    state = _state_path()
    state.unlink(missing_ok=True)
    args = [str(py), str(GPU_DIR / "server.py"), str(state), str(IDLE_S)]
    if os.name == "nt":
        q = lambda s: s.replace("'", "''")        # a PowerShell single-quoted string
        ps = ("$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
              "-Property @{ShowWindow=[uint16]0}; "
              "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              f"@{{CommandLine='{q(subprocess.list2cmdline(args))}'; CurrentDirectory='{q(str(ccai))}'; "
              "ProcessStartupInformation=$si}; exit $r.ReturnValue")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ServerUnavailable(f"could not start the GPU server: {r.stderr.strip() or r.returncode}")
    else:
        subprocess.Popen(args, cwd=ccai, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ensure() -> dict:
    s = _alive()
    if s:
        return s
    lock = paths.cache_dir() / "gpu_server.starting"
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        owner = True
    except FileExistsError:
        owner = time.time() - lock.stat().st_mtime > START_TIMEOUT_S     # a stale lock
        if owner:
            lock.touch()
    try:
        if owner:
            print("  [gpu] starting the GPU server (it keeps the models loaded for this pass)",
                  file=sys.stderr, flush=True)
            _launch()
        t0 = time.time()
        while time.time() - t0 < START_TIMEOUT_S:
            s = _alive()
            if s:
                return s
            time.sleep(0.5)
        raise ServerUnavailable(f"the GPU server did not start (log: {_state_path().with_suffix('.log')})")
    finally:
        if owner:
            lock.unlink(missing_ok=True)


def stop_server(reason: str = "") -> bool:
    """Stop the GPU server if it runs (end of a pass, or before other GPU work)."""
    s = _alive()
    if not s:
        return False
    try:
        _post(s, "/stop", {}, timeout=10)
    except (OSError, urllib.error.URLError):
        pass
    print(f"  [gpu] stopped the GPU server{f' ({reason})' if reason else ''}", file=sys.stderr, flush=True)
    return True


def _served(script: str, request: dict) -> dict:
    s = _ensure()
    missing = set(request.get("models", ["ft", "qw"])) - set(s.get("loaded", []))
    if missing:
        print(f"  [gpu] loading {', '.join(sorted(missing))}; it stays loaded for later calls",
              file=sys.stderr, flush=True)
    try:
        r = _post(s, "/run", {"script": script, "request": request}, timeout=3600)
    except (OSError, urllib.error.URLError) as e:
        raise ServerUnavailable(f"the GPU server stopped answering: {e}") from e
    if not r.get("ok"):
        raise SystemExit(f"GPU {script} failed in the GPU server: {r.get('error')}\n"
                         f"(log: {_state_path().with_suffix('.log')})")
    return r["result"]


def run(script: str, request: dict, timeout: float | None = None) -> dict:
    require_ccai(f"`ccp {script}`")
    if script in SERVED and os.environ.get("CCP_GPU_SERVER", "1") != "0":
        try:
            return _served(script, request)
        except ServerUnavailable as e:
            print(f"  [gpu] {e}; running {script} on its own instead", file=sys.stderr, flush=True)
    if script not in SERVED:
        stop_server(f"{script} needs the GPU")
    return _one_shot(script, request, timeout)


def _one_shot(script: str, request: dict, timeout: float | None = None) -> dict:
    ccai = _ccai()
    if not shutil.which("uv"):
        raise SystemExit("uv is not on PATH")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="ccp_") as tmp:
        req_p, res_p = Path(tmp) / "request.json", Path(tmp) / "result.json"
        req_p.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        cmd = ["uv", "run", "--project", str(ccai), "--no-sync", "python",
               str(GPU_DIR / f"{script}.py"), str(req_p), str(res_p)]
        noise = ("Warning", "warn(", "Loading weights", "it/s]", "s/it]", "%|")
        lines: list[str] = []
        with subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace") as proc:
            for line in proc.stderr:
                line = line.rstrip()
                lines.append(line)
                if line.strip() and not any(n in line for n in noise):
                    print(f"  [{script}] {line}", file=sys.stderr, flush=True)
            proc.wait(timeout=timeout)
        if proc.returncode != 0 or not res_p.exists():
            tail = "\n".join(lines[-30:])
            raise SystemExit(f"GPU script {script} failed (exit {proc.returncode}). Is the GPU free "
                             f"(>= 8 GB) and are cantocaptions-ai's models downloaded?\n{tail}")
        return json.loads(res_p.read_text(encoding="utf-8"))
