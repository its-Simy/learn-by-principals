"""Principle 2: nothing outside core/providers/ imports an external SDK directly."""

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
FORBIDDEN = ("playwright", "googleapiclient", "google_auth_oauthlib", "notebooklm")
SCANNED = ("core", "cli", "dashboard")  # tests may use SDK test doubles (see questions.md)


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
