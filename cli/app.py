from __future__ import annotations

import logging
import os
import shutil

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from cli import dev
from cli.sync import sync
from core.config import load_config
from core.providers.state import ProviderState

app = typer.Typer(no_args_is_help=True, help="BrightLearn personal learning platform.")
app.command()(sync)
app.add_typer(dev.app, name="dev")
console = Console()


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=Console(stderr=True), show_path=False)],
    )


@app.command()
def doctor() -> None:
    """Report every provider's health. Never opens a login window."""
    from core.providers.lms.brightspace import BrightspaceSessionProvider
    from core.providers.lms.session import PlaywrightSession
    from core.providers.storage.gdrive import GoogleDriveBackend

    config = load_config()
    rows: list[tuple[str, ProviderState, str]] = []

    session = PlaywrightSession(
        config.brightspace_base_url, config.browser_profile_dir, config.storage_state_path
    )
    try:
        state = BrightspaceSessionProvider(session).health()
        hints = {
            ProviderState.AVAILABLE: "whoami 200",
            ProviderState.AUTH_EXPIRED: "run `brightlearn sync` to log in",
            ProviderState.BROKEN: "browser failed; try `playwright install chromium` (see log)",
        }
        rows.append(("Brightspace", state, hints[state]))
    finally:
        session.close()

    try:
        drive = GoogleDriveBackend.from_config(config, interactive=False)
        rows.append(("Google Drive", drive.health(), "files.list ok"))
    except Exception as exc:
        rows.append(("Google Drive", ProviderState.AUTH_EXPIRED, str(exc)))

    rows.append(("NotebookLM", ProviderState.DISABLED, "not built yet (Phase 2)"))
    for name, binary in (("Claude Code", "claude"), ("Codex", "codex")):
        found = shutil.which(binary)
        rows.append(
            (
                name,
                ProviderState.DISABLED,
                f"{binary} on PATH; auth not checked (Phase 5)"
                if found
                else f"{binary} not on PATH",
            )
        )
    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    rows.append(
        (
            "ANTHROPIC_API_KEY",
            ProviderState.BROKEN if api_key_set else ProviderState.AVAILABLE,
            "set: Claude Code would bill the API; unset it" if api_key_set else "unset",
        )
    )

    table = Table("Provider", "State", "Detail")
    for name, state, detail in rows:
        colour = "green" if state is ProviderState.AVAILABLE else "yellow"
        table.add_row(name, f"[{colour}]{state}[/]", detail)
    console.print(table)
    required = [s for n, s, _ in rows if n in ("Brightspace", "Google Drive", "ANTHROPIC_API_KEY")]
    if any(s is not ProviderState.AVAILABLE for s in required):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
