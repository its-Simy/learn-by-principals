"""The API contract the web app's types are generated from: ``web/openapi.json`` is the document
the app publishes, so a route change can't reach the browser untyped."""

import json
from pathlib import Path

from api.app import create_app
from core.config import Config

ROOT = Path(__file__).parent.parent
CONTRACT = ROOT / "web" / "openapi.json"
REGENERATE = "run `brightlearn dev openapi > web/openapi.json` and `pnpm --dir web gen`"


def test_the_committed_contract_is_the_apps(config: Config):
    """Building the app starts no engine (its workers start in the lifespan), so this opens
    nothing."""
    document = create_app(config).openapi()

    assert document == json.loads(CONTRACT.read_text()), (
        f"web/openapi.json is out of date: {REGENERATE}, and commit both files"
    )
    assert not config.db_path.exists()
