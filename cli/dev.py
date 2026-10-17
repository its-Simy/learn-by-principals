"""Developer helpers for trying a provider by hand."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console

from core import wiring
from core.config import load_config
from core.ledger.ledger import Ledger, ModelRun, utcnow
from core.memory.db import Manifest, connect
from core.providers.knowledge import gemini_notebook
from core.providers.models.base import ModelError, TaskPackage

SPIKE_NOTEBOOK = "BrightLearn-spike"

app = typer.Typer(no_args_is_help=True, help="Developer helpers.")
console = Console()


@app.command("nlm-test")
def nlm_test(
    file: Path | None = typer.Option(None, help="File to upload. Default: the course syllabus."),
    course: str = typer.Option("CSE220", help="Course whose uploaded syllabus to use."),
) -> None:
    """Create/find the spike notebook, add a file, query it, then remove the source."""
    config = load_config()
    conn = connect(config.db_path)
    if file is None:
        rows = [r for r in Manifest(conn).all(course) if r.bucket == "syllabus" and r.local_path]
        if not rows:
            raise typer.BadParameter(f"No uploaded syllabus for {course}; pass --file")
        file = Path(rows[0].local_path)
    try:
        with wiring.open_knowledge(config, conn) as kp:

            def step(name, fn):
                t0 = time.monotonic()
                result = fn()
                console.print(f"{name}: {time.monotonic() - t0:.1f}s, state {kp.state}")
                return result

            notebook_id = step("notebook", lambda: kp.notebook_by_title(SPIKE_NOTEBOOK))
            source_id = step("add_file", lambda: kp.add_file(notebook_id, file))
            answer = step(
                "query",
                lambda: kp.query(notebook_id, "What is the grading breakdown?", [source_id]),
            )
            console.print(answer.text)
            for c in answer.citations:
                console.print(f"  [dim]{c.source_id}[/] {c.excerpt[:120]}")
            step("remove_source", lambda: kp.remove_source(source_id))
    finally:
        conn.close()


@app.command("model-test")
def model_test(
    provider: str = typer.Argument(..., help="claude or codex"),
    prompt: str = typer.Argument("Say hi", help="What to send."),
) -> None:
    """Send one prompt through a model provider and print the reply (logged to the ledger)."""
    config = load_config()
    try:
        model = wiring.open_model(provider, config)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    task = TaskPackage("model_test", None, "", prompt, 256)
    conn = connect(config.db_path)
    ledger = Ledger(conn)
    started, t0 = utcnow(), time.monotonic()
    try:
        result = model.run(task)
    except ModelError as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        ledger.record(ModelRun.from_error(task, model.name, exc, started, duration_ms))
        conn.close()
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    ledger.record(ModelRun.from_result(task, result, started))
    conn.close()
    console.print(result.text)
    console.print(
        f"[dim]{result.provider} · {result.model or 'model unknown'} · {result.duration_ms} ms[/]"
    )


@app.command("nlm-login")
def nlm_login(
    account: str = typer.Option(..., help="The Google account for the notebooks."),
) -> None:
    """`notebooklm login --master-token` into ~/.brightlearn/notebooklm (opens a browser)."""
    config = load_config()
    if not gemini_notebook.library_installed():
        raise typer.BadParameter(f"notebooklm-py is not installed: {gemini_notebook.INSTALL_HINT}")
    code = gemini_notebook.login(config, account)
    if code:
        raise typer.Exit(code)
    console.print(f"Saved under {config.notebooklm_home}. Check with `brightlearn doctor`.")
