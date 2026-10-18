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
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": args, "stdin": stdin, "cwd": os.getcwd(),
        "api_key": "ANTHROPIC_API_KEY" in os.environ}}) + "\\n")
if args == ["--version"]:
    print("9.9.9 (fake)")
    sys.exit(0)
if mode == "sleep":
    time.sleep(10)
for flag in ("-o", "--output-last-message"):
    if flag in args and "FAKE_LAST_MESSAGE" in os.environ:
        with open(args[args.index(flag) + 1], "w", encoding="utf-8") as out:
            out.write(os.environ["FAKE_LAST_MESSAGE"])
print(os.environ.get("FAKE_STDOUT", ""), end="")
print(os.environ.get("FAKE_STDERR", ""), end="", file=sys.stderr)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""

# Windows can't run a shebang script and `shutil.which` wants a PATHEXT suffix, so the fake is a
# .cmd that hands its arguments and stdin to the script.
WRAPPER = '@"{python}" "%~dp0{name}.py" %*\r\n'


def install(bin_dir: Path, name: str, monkeypatch, log: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (bin_dir / f"{name}.py").write_text(SCRIPT.format(python=sys.executable), encoding="utf-8")
        exe = bin_dir / f"{name}.cmd"
        exe.write_text(WRAPPER.format(python=sys.executable, name=name), encoding="utf-8")
    else:
        exe = bin_dir / name
        exe.write_text(SCRIPT.format(python=sys.executable), encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    log.write_text("", encoding="utf-8")
    return exe
