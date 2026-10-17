from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from cli import concepts, courses, dev, exam, sessions
from cli.ask import ask
from cli.dashboard import dashboard
from cli.doctor import doctor
from cli.generate import generate
from cli.maintain import auto_maintain, maintain_cmd
from cli.podcast import podcast
from cli.sync import sync
from cli.tutor import tutor
from cli.web import web

app = typer.Typer(no_args_is_help=True, help="BrightLearn personal learning platform.")
app.command()(sync)
app.command()(doctor)
app.command()(ask)
app.command()(generate)
app.command()(tutor)
app.command()(podcast)
app.command()(dashboard)
app.command("maintain")(maintain_cmd)
app.command()(web)
app.add_typer(courses.app, name="courses")
app.add_typer(dev.app, name="dev")
app.add_typer(concepts.app, name="concepts")
app.add_typer(sessions.app, name="sessions")
app.add_typer(exam.app, name="exam")


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=Console(stderr=True), show_path=False)],
    )
    auto_maintain(ctx.invoked_subcommand)


if __name__ == "__main__":
    app()
