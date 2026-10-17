# BrightLearn

BrightLearn is a personal learning tool for one student. You upload your course files; it keeps them in a local course folder, sends them to NotebookLM for grounded answers, and uses Claude Code and Codex on your own subscriptions to tutor you, write and grade practice exams, and plan audio overviews of what you're weakest at. What you learn is recorded as mastery backed by evidence, in a local SQLite database and a Markdown vault.

## Setup

From the repo root, with Python 3.12, `uv` and `pnpm`:

```sh
uv venv .venv && env -u CONDA_PREFIX uv pip install --python .venv/bin/python -e . pytest ruff httpx
chflags nohidden .venv/lib/python3.12/site-packages/*.pth
env -u CONDA_PREFIX uv pip install --python .venv/bin/python "notebooklm-py[android,browser]"
pnpm --dir web install && pnpm --dir web build
brightlearn dev nlm-login --account <gmail>
brightlearn doctor
brightlearn web
```

- `env -u CONDA_PREFIX` and `--python` keep the install in `.venv`: with `CONDA_PREFIX` set, a bare `uv pip install` lands in the conda base env.
- `chflags` is for macOS, which marks the venv's `.pth` files hidden; Python 3.12 then skips them.
- `brightlearn` is `.venv/bin/brightlearn`: activate the venv, or use the path.
- The tutor, exams and the Analyzer need the `claude` and `codex` CLIs on PATH, logged in to their subscriptions. `ANTHROPIC_API_KEY` must be unset, or Claude Code would bill the API; `doctor` checks it.
- `brightlearn web` serves the app on `http://127.0.0.1:8765/` and opens it. There is no login, so it listens on localhost only.

## Where your data lives

Everything personal is under `~/.brightlearn/` (`BRIGHTLEARN_HOME` moves it). Nothing personal lives in the repo.

- `courses/{term}/{course}/{bucket}/`: the files you uploaded. A replaced file's old version is kept in its bucket's `_versions/`; podcasts and other NotebookLM artifacts go in the course's `_generated/`.
- `vault/`: Markdown session transcripts and summaries, concept drafts, and exams.
- `brightlearn.db`: SQLite with courses, sources, concepts, mastery, evidence, sessions and the ledger of model runs.
- `notebooklm/`: the NotebookLM login. It's a secret: never copy it into the repo.
- `config.toml`: optional, the `[routing]` order of model providers.
- `dashboard.html`: what `brightlearn dashboard` writes.

## Commands

The web app covers the everyday flow, and it's the only way to upload files. The CLI does the rest of that flow too, plus a few commands for maintenance. `brightlearn <command> --help` lists every option.

| Command | What it does |
| --- | --- |
| `brightlearn web [--port 8765] [--no-open]` | The web app: Sources, Chat and Studio |
| `brightlearn courses list` · `courses add CODE --name TEXT [--term T]` | List or add courses |
| `brightlearn sync --course CODE \| --all [--include-code]` | Send stored files to NotebookLM (an upload in the web app does this itself) |
| `brightlearn ask "QUESTION" --course CODE [--sources syllabus,lectures]` | A grounded answer with citations |
| `brightlearn tutor --course CODE [--persona simplifier]` | A tutoring session in the terminal |
| `brightlearn sessions list` · `sessions close --id ID \| --all` | Past sessions; close a crashed one without running the Analyzer |
| `brightlearn concepts seed --course CODE` · `concepts apply --course CODE [--draft NAME]` | Draft the course's concepts from NotebookLM, then load the reviewed draft |
| `brightlearn exam create --spec FILE` · `exam take FILE` · `exam grade FILE` | Practice exams |
| `brightlearn podcast --course CODE [--exam NAME] [--format F] [--length L]` | An Audio Overview aimed at your weakest concepts |
| `brightlearn generate quiz\|audio\|flashcards\|report --course CODE` | Any other NotebookLM artifact |
| `brightlearn dashboard` | Usage, provider health and mastery as one HTML file |
| `brightlearn maintain` | Retention decay and session archiving; it also runs daily on its own |
| `brightlearn doctor` | Read-only health checks |
| `brightlearn dev nlm-login --account EMAIL` · `dev nlm-test` · `dev model-test claude\|codex` · `dev openapi` | Developer helpers |

## Development

Read `CLAUDE.md` first: the principles, the repo layout, the conventions and the decision log. `TICKETS-4.md` is the current backlog, `docs/web-plan.md` the web app's design, and `web/README.md` the web dev loop, including `scripts/dev_server.py`, which serves the API on the test fakes so the UI runs with no accounts. `docs/validation-log.md` records the first runs against real accounts.

Before committing: `.venv/bin/pytest -q` and `.venv/bin/ruff check .`, and for a web change `pnpm --dir web typecheck && pnpm --dir web build`.
