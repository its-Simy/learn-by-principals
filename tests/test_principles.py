"""Principle 2: nothing outside core/providers/ imports an external SDK directly."""

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
FORBIDDEN = ("playwright", "googleapiclient", "google_auth_oauthlib", "notebooklm")
SCANNED = ("core", "cli")  # provider tests may use SDK test doubles (see questions.md)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


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
