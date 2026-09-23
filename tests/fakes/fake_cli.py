"""Fake ``claude`` / ``codex`` executables for provider tests. Behaviour comes from env vars."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

SCRIPT = """#!{python}
import json, os, sys, time
mode = os.environ.get("FAKE_MODE", "success")
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
        "api_key": "ANTHROPIC_API_KEY" in os.environ}}) + "\\n")
if args == ["--version"]:
    print("9.9.9 (fake)")
    sys.exit(0)
if mode == "sleep":
    time.sleep(10)
print(os.environ.get("FAKE_STDOUT", ""), end="")
print(os.environ.get("FAKE_STDERR", ""), end="", file=sys.stderr)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def install(bin_dir: Path, name: str, monkeypatch, log: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / name
    exe.write_text(SCRIPT.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    log.write_text("")
    return exe
