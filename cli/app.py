from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from cli import concepts, dev, exam, sessions
from cli.ask import ask
from cli.doctor import doctor
from cli.generate import generate
from cli.sync import sync
from cli.tutor import tutor

app = typer.Typer(no_args_is_help=True, help="BrightLearn personal learning platform.")
app.command()(sync)
app.command()(doctor)
app.command()(ask)
app.command()(generate)
app.command()(tutor)
app.add_typer(dev.app, name="dev")
app.add_typer(concepts.app, name="concepts")
app.add_typer(sessions.app, name="sessions")
app.add_typer(exam.app, name="exam")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=Console(stderr=True), show_path=False)],
    )


if __name__ == "__main__":
    app()
