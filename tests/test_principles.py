"""Principle 2: nothing outside core/providers/ imports an external SDK directly. And the layers
point one way: the CLI and the API both sit on core, and neither core nor the API needs the CLI."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FORBIDDEN = ("playwright", "googleapiclient", "google_auth_oauthlib", "notebooklm")
SCANNED = ("core", "cli", "dashboard", "api")  # tests may use SDK test doubles (see questions.md)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _calls_model_cli(path: Path) -> bool:
    """Imports subprocess and mentions the claude/codex binaries as string literals."""
    tree = ast.parse(path.read_text())
    strings = {
        n.value.strip().lower()
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    return "subprocess" in _imports(path) and bool(strings & {"claude", "codex"})


def test_model_clis_are_only_run_inside_providers():
    providers = ROOT / "core" / "providers"
    offenders = [
        str(path.relative_to(ROOT))
        for top in SCANNED
        for path in (ROOT / top).rglob("*.py")
        if providers not in path.parents and _calls_model_cli(path)
    ]
    assert offenders == []


def test_sdks_are_only_imported_inside_providers():
    providers = ROOT / "core" / "providers"
    offenders = [
        f"{path.relative_to(ROOT)} imports {name}"
        for top in SCANNED
        for path in (ROOT / top).rglob("*.py")
        if providers not in path.parents
        for name in _imports(path) & set(FORBIDDEN)
    ]
    assert offenders == []


def test_api_never_imports_cli():
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "api").rglob("*.py")
        if "cli" in _imports(path)
    ]
    assert offenders == []


def test_core_and_api_load_without_the_cli_stack():
    """In a fresh interpreter, so modules other tests imported can't hide a stray import."""
    modules = ("core.wiring", "core.doctor", "core.sessions", "api.app")
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in modules)
        + "print(sorted({m.split('.')[0] for m in sys.modules} & {'cli', 'typer', 'rich'}))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"
