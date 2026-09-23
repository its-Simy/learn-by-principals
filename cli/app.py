from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from cli import dev
from cli.ask import ask
from cli.doctor import doctor
from cli.sync import sync

app = typer.Typer(no_args_is_help=True, help="BrightLearn personal learning platform.")
app.command()(sync)
app.command()(doctor)
app.command()(ask)
app.add_typer(dev.app, name="dev")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=Console(stderr=True), show_path=False)],
    )


if __name__ == "__main__":
    app()
