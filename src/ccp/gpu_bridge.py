"""Run a GPU script inside cantocaptions-ai's venv and return its JSON result.

`uv run --project <cantocaptions-ai> --no-sync python src/ccp/gpu/<name>.py req res`.
--no-sync matters: a sync would uninstall cantocaptions-ai's locally installed flash-attn
wheel. Requests and results go through JSON files, never the command line, so CJK text
and Windows quoting cannot collide. Progress lines from the script stream to stderr.

Only `evidence` and `listen` need this routinely. `score` reads the emissions `evidence`
stored (ccp.ctcscore) and comes here only for spans or characters outside them. There is
deliberately no resident server: agent harnesses end a command's process tree when the
command returns, so a detached server died after every call.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import paths

GPU_DIR = Path(__file__).resolve().parent / "gpu"


def run(script: str, request: dict, timeout: float | None = None) -> dict:
    ccai = paths.get("cantocaptions_ai")
    if not (ccai / "pyproject.toml").exists():
        raise SystemExit(f"cantocaptions-ai not found at {ccai} (set cantocaptions_ai in config/paths.local.toml)")
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
