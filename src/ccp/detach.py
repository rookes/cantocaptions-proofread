"""Start a process that outlives the command that started it.

Agent harnesses end a command's whole process tree when the command returns (Antigravity
does), so a server started as an ordinary child would die with the `ccp` call that started
it. On Windows the process is created through WMI (Win32_Process.Create), which parents it to
the WMI service, with a hidden window; elsewhere it gets a session of its own.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


# Said whenever a detached server cannot start. Antigravity runs an agent's commands in a
# terminal sandbox by default, which blocks starting a process that outlives the command (and
# reaching it on localhost); the same command run outside the sandbox works.
SANDBOX_HINT = ("If this command ran in a sandboxed terminal (Antigravity runs commands in one by "
                "default), a server cannot start from it: run the same command again outside the "
                "sandbox (in Antigravity, with BypassSandbox).")


def windowless_python(python: Path) -> Path:
    """pythonw.exe beside *python* when there is one (no console window on Windows)."""
    w = python.with_name("pythonw.exe")
    return w if os.name == "nt" and w.exists() else python


def launch(args: list[str], cwd: Path) -> None:
    """Start *args* in *cwd*, detached. Raises RuntimeError when it cannot be started."""
    if os.name == "nt":
        q = lambda s: s.replace("'", "''")        # a PowerShell single-quoted string
        ps = ("$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
              "-Property @{ShowWindow=[uint16]0}; "
              "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              f"@{{CommandLine='{q(subprocess.list2cmdline(args))}'; CurrentDirectory='{q(str(cwd))}'; "
              "ProcessStartupInformation=$si}; exit $r.ReturnValue")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"exit {r.returncode}")
    else:
        subprocess.Popen(args, cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
