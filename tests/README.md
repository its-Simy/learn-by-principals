# Tests

Every test runs on fakes: no network, no NotebookLM account, no model quota. Each one sits in exactly one of three tiers, given by its path in `tests/conftest.py`, and `tests/test_tiers.py` fails if a collected test has no tier or two.

| Tier | Marker | Files | What it proves |
| --- | --- | --- | --- |
| Unit | `unit` | every other `tests/test_*.py` | Each core module does what its ticket says: memory and migrations, the router, the Context Compiler, the tutor, the Analyzer and Challenger, exams, podcasts, and the provider adapters against fake `claude`/`codex` executables and a mocked notebooklm-py client. |
| Integration | `integration` | `test_api_*.py`, `test_cli_*.py`, `test_exam_cli.py` | The routes and commands a user reaches work end to end over the core: FastAPI's `TestClient` on the `api` fixture (both worker threads, a real SQLite file, fake providers) and Typer's `CliRunner`. |
| End to end | `e2e` | `tests/e2e/` | The built web app works in a real browser: a Playwright tour in Chromium against `scripts/dev_server.py`. |

A new test file needs no marker: its name and folder decide its tier.

## Running

```sh
uv run pytest -q                    # unit + integration: the default run
uv run pytest -q -m unit
uv run pytest -q -m integration
uv run pytest -m e2e tests/e2e      # the Playwright tour
```

The default run leaves the tour out (`addopts = "-m 'not e2e'"` in `pyproject.toml`); a `-m` on the command line replaces that one, and `-m ""` collects all three tiers.

The tour needs two things the other tiers don't:

- `web/dist`, built with `pnpm --dir web build` (the dev server serves it).
- A browser: `uv run playwright install chromium` once, or add `--browser-channel chrome` to use an installed Chrome.

`--headed` shows the browser. `--tracing retain-on-failure --screenshot only-on-failure` keeps a trace and a screenshot of each failed test under `test-results/`; open a trace with `uv run playwright show-trace test-results/<test>/trace.zip`.

## Fakes and fixtures

- `tests/fakes/fake_knowledge.py`: `FakeKnowledge`, an in-memory NotebookLM. It holds sources, answers a query with set text that cites the first source, and follows the real provider's conversation rule (a fresh conversation unless a tutor session passes its own).
- `tests/fakes/fake_models.py`: `FakeModel`, which answers every task with a set reply (or the next of several), records the tasks it got, and can report any provider state or hit a usage limit on its next run.
- `tests/fakes/fake_exam.py`: `FakeQuestioner` writes valid questions for whatever slots an exam task lists; `FakeCritic` flags nothing and grades an answer correct when it contains "correct".
- `tests/fakes/fake_cli.py`: fake `claude` and `codex` executables whose behaviour comes from environment variables, for the provider adapter tests. `tests/fixtures/cli/` holds a real `claude` reply that one of them prints, so the parser is checked against the live CLI's shape.
- `tests/conftest.py`: `isolated_home` (automatic, so no test reads or writes `~/.brightlearn`), `config` (a `Config` under the test's `tmp_path`) and `api` (the web API on fakes, yielding the client, the fake NotebookLM, the fake models and the engine).

`scripts/dev_server.py` serves the same API on these fakes against a scratch `--home`; the tour runs on it, and so can you (`web/README.md`). Its first start seeds course CSE220 with three linked files (a syllabus, a lecture, a homework), five concepts at mastery levels 0 to 4 with the evidence behind each, one pending Challenger probe on Pointers, healthy providers, a few ledger rows and benchmark samples. Its fakes answer every task a route can send, a file whose name contains `fail` is refused at link time, and a tutor question that says "rate limit" gets a usage limit from both models.

## Coverage

```sh
uv run pytest -q --cov --cov-report=term    # one row per file and the total
uv run pytest -q --cov --cov-report=html    # then open htmlcov/index.html
```

`[tool.coverage.run]` in `pyproject.toml` measures `core`, `api`, `cli` and `dashboard` with branch coverage, leaving out the frozen migrations under `core/memory/migrations/`. In the terminal table `Miss` counts statements never run, `BrPart` branches taken only one way, and `Cover` combines both. The HTML report marks missed lines red and half-taken branches yellow, file by file. `.coverage` and `htmlcov/` are gitignored.

CI fails below **88%**, set on its command line (`--cov-fail-under=88`) and never in `addopts`, so a local run never fails on it. The measured total of the default run was **93.65%** on Oct 18, 2026 (macOS, 605 tests), and the threshold is five whole points under it, rounded down. When the total climbs for good, raise the threshold the same way and update both numbers here. Only the default run is measured, so the tour adds nothing to the total.

## CI

`.github/workflows/ci.yml` runs on every push to `dev` and `main` and on every pull request. Each job is a gate.

| Job | OS | Runs |
| --- | --- | --- |
| `test` | Ubuntu, macOS, Windows | `uv sync --locked`; ruff check and format; the default run (on Ubuntu with coverage and `--cov-fail-under=88`); the web install, typecheck and build; on Ubuntu, the committed API contract and generated types against the app, and `requirements.txt` against `uv.lock`. |
| `setup-scripts` | Ubuntu, macOS, Windows | `setup.sh` (or `setup.cmd`) from a fresh checkout, then a second run that must be a no-op, and `brightlearn --help`. |
| `e2e` | Ubuntu | Builds `web/dist`, installs Chromium (cached per Playwright version), then `pytest -m e2e tests/e2e` with `CI=1`. A failed run uploads `test-results/` (traces and screenshots) as the `playwright-e2e` artifact, kept 7 days. |
