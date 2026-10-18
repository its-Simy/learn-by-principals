"""What ``brightlearn setup`` checks beyond doctor, kept free of typer, rich and subprocess so
the API could run it too and so the principle tests stay simple: the web build, the optional
model CLIs with their per-OS install hints, and which browser the NotebookLM login should open.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from core.doctor import Check, Status, check_model_cli
from core.providers.models.cli_base import CLIModelProvider

PLATFORM = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")

WEB_BUILD_CMD = "pnpm --dir web install --frozen-lockfile && pnpm --dir web build"

# How to install each optional model CLI. Native installers are preferred over npm on Windows:
# an npm `.cmd` shim runs through cmd.exe, which re-parses the prompt it is handed.
INSTALL_HINTS: dict[str, dict[str, str]] = {
    "claude": {
        "macos": "curl -fsSL https://claude.ai/install.sh | bash",
        "linux": "curl -fsSL https://claude.ai/install.sh | bash",
        "windows": "irm https://claude.ai/install.ps1 | iex",
    },
    "codex": {
        "macos": "brew install codex   (or: pnpm add -g @openai/codex)",
        "linux": "pnpm add -g @openai/codex",
        "windows": (
            "download codex-x86_64-pc-windows-msvc.exe from "
            "https://github.com/openai/codex/releases and save it as codex.exe in "
            "%USERPROFILE%\\.local\\bin"
        ),
    },
}
LOGIN_HINTS = {
    "claude": "run `claude` once and complete the login it offers (Pro or Max subscription)",
    "codex": "run `codex login` (ChatGPT subscription)",
}
# What each tier unlocks, for the closing summary.
UNLOCKS = {
    "claude": "tutoring sessions, mastery tracking and practice exams",
    "codex": "the same, and a second model to critique and grade",
}
SHIM_SUFFIXES = {".cmd", ".bat"}


def install_hint(name: str, platform: str = PLATFORM) -> str:
    return INSTALL_HINTS[name][platform]


def check_web_build(dist: Path) -> Check:
    """``brightlearn web`` serves ``web/dist``; without ``index.html`` it serves only the API."""
    if (dist / "index.html").is_file():
        return Check("Web app", Status.OK, f"built in {dist}")
    return Check("Web app", Status.FAIL, f"not built; run: {WEB_BUILD_CMD}")


def check_model_cli_install(name: str, provider: CLIModelProvider) -> Check:
    """Doctor's ``--version`` check, plus a warning for a cmd.exe shim on Windows."""
    check = check_model_cli(name, provider)
    exe = provider.executable()
    if check.status is Status.OK and exe and Path(exe).suffix.lower() in SHIM_SUFFIXES:
        return Check(
            name,
            Status.WARN,
            f"{check.detail}; `{Path(exe).name}` is an npm shim that runs through cmd.exe, "
            f"which mangles long prompts. Prefer the native install: "
            f"{install_hint(provider.binary)}",
        )
    return check


def chrome_installed(env: dict[str, str] | None = None, platform: str = PLATFORM) -> bool:
    """Whether Chrome is installed where its installer puts it (Windows only; elsewhere
    Playwright finds the ``chrome`` channel itself and reports a missing one clearly)."""
    if platform != "windows":
        return True
    env = os.environ if env is None else env
    roots = [env.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    return any(
        (Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe").is_file()
        for root in roots
        if root
    )


def default_browser(platform: str = PLATFORM) -> str:
    """The browser the NotebookLM login opens: Chrome, or Edge on a Windows machine without it."""
    return "chrome" if chrome_installed(platform=platform) else "msedge"


def blocking(checks: list[Check]) -> bool:
    """The two things ``brightlearn web`` can't work without: the build and a NotebookLM login."""
    return any(c.status is Status.FAIL and c.name in {"Web app", "NotebookLM"} for c in checks)
