"""``brightlearn setup``: everything after the shell script, idempotent and safe to re-run.

The minimum product needs the web build and a NotebookLM login; Claude Code and Codex are
optional and only reported, with the install and login steps for this OS.
"""

from __future__ import annotations

import os

import typer
from rich.console import Console

from cli.doctor import print_checks
from core import doctor, wiring
from core.config import ensure_home, load_config, write_default_config
from core.doctor import Check, Status
from core.providers.knowledge import gemini_notebook
from core.setup import (
    LOGIN_HINTS,
    PLATFORM,
    UNLOCKS,
    blocking,
    check_model_cli_install,
    check_web_build,
    default_browser,
    install_hint,
)

console = Console()

MODEL_CLIS = (("claude", "Claude Code"), ("codex", "Codex"))


def setup(
    account: str | None = typer.Option(None, help="Google account for NotebookLM (email)."),
    skip_login: bool = typer.Option(False, "--skip-login", help="Don't log in to NotebookLM."),
    relogin: bool = typer.Option(False, "--relogin", help="Log in again even if a login works."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Never prompt; skip what needs one."),
    browser: str | None = typer.Option(
        None, help="Browser for the Google login: chrome or msedge (default: what is installed)."
    ),
    probe: bool = typer.Option(
        False, "--probe", help="Confirm each model CLI's login with one tiny call (spends quota)."
    ),
) -> None:
    """Finish setting up: home folder, web build, NotebookLM login, optional model CLIs, doctor."""
    config = load_config()
    ensure_home(config)
    created = write_default_config(config)
    console.print(f"Home: {config.home}" + ("  (config.toml written)" if created else ""))

    from api.static import DIST  # here, so the other commands don't import the web stack

    results = [
        doctor.check_config(config),
        doctor.check_db(config),
        doctor.check_storage(config),
        doctor.check_tmp(config),
        check_web_build(DIST),
        notebooklm_step(config, account, skip_login, relogin, yes, browser),
    ]
    hints: dict[str, list[str]] = {}
    for name, label in MODEL_CLIS:
        provider = wiring.open_model(name, config)
        check = check_model_cli_install(label, provider)
        if check.status is Status.OK and probe:
            check = Check(label, check.status, f"{check.detail.split(';')[0]}; {provider.health()}")
        if provider.executable() is None:
            hints[label] = [f"install: {install_hint(name)}", f"then {LOGIN_HINTS[name]}"]
        results.append(check)
    results += [doctor.check_api_key(os.environ), doctor.check_openai_key(os.environ)]

    print_checks(results)
    for name, label in MODEL_CLIS:
        if label in hints:
            console.print(f"[yellow]{label}[/] (optional; unlocks {UNLOCKS[name]}):")
            for line in hints[label]:
                console.print(f"  {line}")
    if blocking(results):
        console.print("[red]Not ready yet:[/] fix the failed rows, then run `brightlearn setup`.")
        raise typer.Exit(1)
    if PLATFORM == "windows":
        start = "start.cmd"
    else:
        start = "./start.sh (or double-click BrightLearn.command)"
    console.print(f"[green]Ready.[/] Start it with: {start}")


def notebooklm_step(
    config, account: str | None, skip_login: bool, relogin: bool, yes: bool, browser: str | None
) -> Check:
    """Check the login and, unless told not to, make one: the library opens Chrome or Edge."""
    if not gemini_notebook.library_installed():
        return Check("NotebookLM", Status.FAIL, f"not installed: {gemini_notebook.INSTALL_HINT}")
    ok, detail = gemini_notebook.auth_check(config)
    if ok and not relogin:
        return Check("NotebookLM", Status.OK, detail)
    if skip_login:
        return Check("NotebookLM", Status.WARN, f"{detail} (skipped: --skip-login)")
    if account is None:
        if yes:
            return Check("NotebookLM", Status.WARN, f"{detail} (pass --account EMAIL to log in)")
        account = typer.prompt("Google account for NotebookLM (email)")
    chosen = browser or default_browser()
    console.print(f"Opening {chosen} for the Google login of {account}…")
    code = gemini_notebook.login(config, account, chosen)
    if code:
        return Check("NotebookLM", Status.FAIL, f"login exited with code {code}")
    ok, detail = gemini_notebook.auth_check(config)
    return Check("NotebookLM", Status.OK if ok else Status.FAIL, detail)
