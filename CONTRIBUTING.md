# Contributing

Read `CLAUDE.md` first: the principles every change must respect, the repo layout, the conventions and the decision log. This file is the dev loop.

## Setup

```sh
./setup.sh --dev --skip-login        # macOS / Linux
.\setup.cmd --dev --skip-login       # Windows
```

`--dev` installs the test tools (`pytest`, `ruff`, `httpx`) from the `dev` group in `pyproject.toml`; `--skip-login` leaves NotebookLM for later (the tests run on fakes and need no account). The script creates the Python environment with uv's own Python 3.12, exactly as `uv.lock` says, builds the web app, and prints doctor's table.

Everything runs through `uv run`, with no environment to activate:

```sh
uv run pytest -q                         # the suite, on fakes, no network
uv run ruff check . && uv run ruff format --check .
pnpm --dir web typecheck && pnpm --dir web build
```

Run all three before committing; for a Python-only change the first two are enough. The CI workflow (`.github/workflows/ci.yml`) runs them on macOS, Windows and Ubuntu, plus the setup scripts themselves, and is the gate for merging.

## The web app

`web/README.md` has the loop: `scripts/dev_server.py` serves the API on the test fakes against a scratch home (add `--no-models` to see the NotebookLM-only state), and `pnpm --dir web dev` serves the app with hot reload against it.

## Changing dependencies

- Python: edit `pyproject.toml`, then `uv lock` and `./setup.sh --dev` (or `uv sync`). Commit `uv.lock` and the refreshed `requirements.txt` (`uv export --no-dev --format requirements.txt --no-hashes --no-emit-project -o requirements.txt`); CI diffs both.
- Web: `pnpm --dir web add <pkg>`; commit `web/pnpm-lock.yaml`.
- A dependency that charges per request is never added (principle 1), and every external service stays behind an interface in `core/providers/` (principle 2).

## The API contract

Whenever a route or schema changes:

```sh
uv run brightlearn dev openapi --out web/openapi.json && pnpm --dir web gen
```

and commit both `web/openapi.json` and `web/src/api/types.ts`. `tests/test_api_openapi.py` fails until the committed contract matches the app. Use `--out`, never a shell redirect: PowerShell's `>` writes UTF-16.

## Migrations

One file per schema change under `core/memory/migrations/vNNN_<name>.py`, sequential, literal SQL. Never renumber or edit a committed one; `tests/test_migrations.py` checksums each and applies them all from v0.

## Windows

The suite is the same on every OS. Keep it that way: name the encoding on every text read and write (ruff's `PLW1514` enforces it), compare paths with `as_posix()` or `Path`, and send a CLI its prompt on stdin, never on the command line. A POSIX-only test (`chmod`, a 255-byte filename) is skipped on Windows with `pytest.mark.skipif(os.name == "nt")`, not deleted.

## Commits

One ticket per branch, commit messages `BL-0XX: <ticket title>`, and a row in `CLAUDE.md`'s decision log whenever a principle is bent or a provider choice changes.
