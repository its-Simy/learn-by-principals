# Contributing

Read `CLAUDE.md` first: the principles every change must respect, the repo layout, the conventions and the decision log. This file is the dev loop.

## Branches

- **`dev`** is where all work lands. Branch from `dev` for a ticket and open a pull request back into it; CI runs on every pull request and on every push to `dev`.
- **`main`** is promoted from `dev` by a pull request, once CI is green on `dev` and the Playwright tour passes (`uv run pytest -m e2e tests/e2e`). Nothing is pushed to `main` directly, so it is always the last version that worked end to end.
- A pull request fills in `.github/PULL_REQUEST_TEMPLATE.md`: the ticket, what changed, how it was checked, and whether the decision log needed a row.

The author sets the protection by hand, in the repository's Settings → Branches, one rule per branch:

| Branch | Rule |
| --- | --- |
| `main` | Require a pull request before merging; require the `CI` workflow's status checks to pass: `test`, `setup-scripts` and `e2e` |
| `dev` | Require the same status checks to pass |

The matrix jobs report one check per OS (`test (ubuntu-latest)`, `test (windows-latest)`, ...), so require each of them.

## Setup

```sh
./setup.sh --dev --skip-login        # macOS / Linux
.\setup.cmd --dev --skip-login       # Windows
```

`--dev` installs the test tools (`pytest`, `ruff`, `httpx`, `pytest-playwright`, `pytest-cov`) from the `dev` group in `pyproject.toml`; `--skip-login` leaves NotebookLM for later (the tests run on fakes and need no account). The script creates the Python environment with uv's own Python 3.12, exactly as `uv.lock` says, builds the web app, and prints doctor's table.

Everything runs through `uv run`, with no environment to activate:

```sh
uv run pytest -q                         # unit + integration, on fakes, no network
uv run ruff check . && uv run ruff format --check .
pnpm --dir web typecheck && pnpm --dir web build
uv run pytest -m e2e tests/e2e           # the Playwright tour, before promoting dev to main
```

Run the first three before committing; for a Python-only change the first two are enough. Run the tour before promoting `dev` to `main`. The CI workflow (`.github/workflows/ci.yml`) runs on pushes to `dev` and `main` and on every pull request: `test` (the suite, lint and the web build) and `setup-scripts` (the setup scripts themselves) on macOS, Windows and Ubuntu, and `e2e` (the tour) on Ubuntu. It is the gate for merging.

## Tests

The suite has three tiers, each a pytest marker set from the test's path: `unit` (core logic on fakes, with no process or network boundary), `integration` (flows through the FastAPI test client or the CLI, still on fakes) and `e2e` (a Playwright tour of the built web app, driven against `scripts/dev_server.py` on the same fakes, so it needs no account and gives the same result every run). `uv run pytest -q` runs unit and integration, `uv run pytest -q -m unit` or `-m integration` runs one tier, and `uv run pytest -m e2e tests/e2e` runs the tour, which needs `web/dist` and a Playwright browser. CI also holds the suite to a coverage threshold. [tests/README.md](tests/README.md) describes the tiers and the coverage, and [tests/e2e/README.md](tests/e2e/README.md) the tour and its one-time browser install.

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

One ticket per branch, cut from `dev` and merged back by pull request, commit messages `BL-0XX: <ticket title>`, and a row in `CLAUDE.md`'s decision log whenever a principle is bent or a provider choice changes.
