# BrightLearn

BrightLearn is a personal learning tool. You upload the files for something you are learning, it keeps them in a local folder and sends them to Google's NotebookLM, and you ask questions that are answered from those files, with citations. With Claude Code or Codex installed on your own subscription, it also tutors you, tracks what you have mastered with evidence, and writes and grades practice exams. Everything it records lives on your machine, in a SQLite database and a Markdown vault.

## Requirements

Required for the minimum product (chat with your sources, concept lists, Audio Overviews):

| What | Why |
| --- | --- |
| A Google account with access to [NotebookLM](https://notebooklm.google.com) | Where your files are read and your questions answered |
| Google Chrome or Microsoft Edge | The one-time Google login opens in it |
| macOS, Windows 10/11, or Linux | Setup installs the rest: Python 3.12 (through `uv`), Node 22 and `pnpm` |

Optional, each unlocking more (see [Optional models](#optional-models)):

| What | Unlocks |
| --- | --- |
| [Claude Code](https://claude.com/claude-code) on a Pro or Max subscription | Tutoring sessions, mastery tracking, practice exams |
| [Codex](https://github.com/openai/codex) on a ChatGPT subscription | The same, and a second model to critique and grade |

Nothing is billed per request: NotebookLM, Claude Code and Codex all run on their subscriptions, and BrightLearn refuses to run with an `ANTHROPIC_API_KEY` set.

## Quick start

```sh
git clone <this repo> brightlearn && cd brightlearn
```

macOS or Linux, in Terminal:

```sh
./setup.sh      # once; asks for your Google account and opens the browser to log in
./start.sh      # every time; opens http://127.0.0.1:8765 (or double-click BrightLearn.command)
```

Windows, in PowerShell or by double-clicking the files:

```powershell
.\setup.cmd     # once
.\start.cmd     # every time
```

`setup` is safe to run again: finished steps are skipped, and it prints a table of what is ready and what is optional. `start` opens the app in your browser once the server answers; running it a second time just opens the page again. The app serves only your own machine (`127.0.0.1`), with no login, so nobody else can reach it.

Flags that go to `brightlearn setup` can follow the script: `./setup.sh --account you@gmail.com` skips the prompt, `--skip-login` defers the login, `--relogin` repeats it, `--browser msedge` picks Edge, `--dev` also installs the test tools.

## Optional models

Install one or both, log in once, then start BrightLearn again. Setup prints these same steps for your OS.

| | macOS / Linux | Windows |
| --- | --- | --- |
| Claude Code | `curl -fsSL https://claude.ai/install.sh \| bash`, then run `claude` once and complete the login | `irm https://claude.ai/install.ps1 \| iex`, then the same |
| Codex | `brew install codex` (or `pnpm add -g @openai/codex`), then `codex login` | The native `codex-x86_64-pc-windows-msvc.exe` from the [releases](https://github.com/openai/codex/releases), saved as `codex.exe` in `%USERPROFILE%\.local\bin`, then `codex login` |

`ANTHROPIC_API_KEY` must be unset (Claude Code would bill the API instead of the subscription); an `OPENAI_API_KEY` is ignored. On Windows, prefer the native installers to npm's `claude.cmd` / `codex.cmd` shims, which run through cmd.exe and mangle long prompts; setup warns when it finds one.

## Where your data lives

Everything personal is under `~/.brightlearn/` (`BRIGHTLEARN_HOME` moves it). Nothing personal lives in the repo.

- `courses/{term}/{course}/{bucket}/`: the files you uploaded. A replaced file's old version is kept in its bucket's `_versions/`; podcasts and other NotebookLM artifacts go in the course's `_generated/`.
- `vault/`: Markdown session transcripts and summaries, concept drafts, and exams.
- `brightlearn.db`: SQLite with courses, sources, concepts, mastery, evidence, sessions and the ledger of model runs.
- `notebooklm/`: the NotebookLM login. It's a secret: never copy it into the repo.
- `config.toml`: optional settings, written by setup with every line commented out: the `[routing]` order of model providers.
- `dashboard.html`: what `brightlearn dashboard` writes.
- `scratch/claude/`, `scratch/codex/`: the model CLIs' working directories, so a run never sees the repo.

## Commands

The web app covers the everyday flow, and it's the only way to upload files. The CLI does the rest of that flow too, plus a few commands for maintenance. `brightlearn <command> --help` lists every option. Without activating anything, run them as `uv run brightlearn <command>` from the repo.

| Command | What it does |
| --- | --- |
| `brightlearn setup [--account EMAIL] [--skip-login] [--relogin] [--yes] [--browser B] [--probe]` | Finish setting up: home folder, web build, NotebookLM login, optional model CLIs, doctor |
| `brightlearn start` · `web` `[--port 8765] [--no-open]` | The web app: Sources, Chat and Studio |
| `brightlearn courses list` · `courses add [CODE] --name TEXT [--term T]` (the code is derived from the name if left out) | List or add courses |
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
| `brightlearn dev nlm-login --account EMAIL` · `dev nlm-test` · `dev model-test claude\|codex` · `dev openapi --out FILE` | Developer helpers |

## Troubleshooting

- **"The web app isn't built"**: run `./setup.sh` (`setup.cmd`) again; it rebuilds in a few seconds.
- **"Port 8765 is in use"**: something else has it; `./start.sh --port 8766`.
- **NotebookLM row red, or answers say the login expired**: `uv run brightlearn setup --relogin`.
- **macOS: `No module named cli` after a while** (the repo sits in an iCloud-synced folder, which re-hides files inside `.venv`): run `./setup.sh` again; it keeps the Python environment under `~/.venvs/` and links `.venv` to it.
- **macOS: `BrightLearn.command` won't open by double-click**: a zip download, unlike a clone, is quarantined; right-click it and choose Open once.
- **Conda or another Python on PATH**: irrelevant, the scripts use uv's own Python 3.12. Never `pip install` into the repo by hand; `./setup.sh --dev` does the whole install.
- **Windows: PowerShell refused to run the script**: a machine policy overrides it; in an elevated PowerShell, `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then `.\setup.cmd` again.
- **pip instead of uv**: `python3.12 -m venv .venv`, activate it, `pip install -r requirements.txt -e .`, then `pnpm --dir web install && pnpm --dir web build` and `brightlearn setup`.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev loop, and `CLAUDE.md` for the principles, the repo layout, the conventions and the decision log. `TICKETS-4.md` is the backlog, `docs/web-plan.md` the web app's design, `web/README.md` the web dev loop, and `docs/validation-log.md` the first runs against real accounts.

BrightLearn is MIT licensed.
