```
 \  .---.  /     ____       _       _     _   _
   /     \      | __ ) _ __(_) __ _| |__ | |_| |    ___  __ _ _ __ _ __
--|   ~   |--   |  _ \| '__| |/ _` | '_ \| __| |   / _ \/ _` | '__| '_ \
   \  |  /      | |_) | |  | | (_| | | | | |_| |__|  __/ (_| | |  | | | |
    |===|       |____/|_|  |_|\__, |_| |_|\__|_____\___|\__,_|_|  |_| |_|
    '---'                     |___/
```

**A tutor that learns from your own course files, on the AI subscriptions you already have.**

[![CI](https://github.com/its-Simy/learn-by-principals/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/its-Simy/learn-by-principals/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Billing: none per request](https://img.shields.io/badge/billing-none%20per%20request-brightgreen.svg)](#how-it-works)

BrightLearn is a personal learning tool that runs on your own machine. You upload the files for something you are learning, it keeps them in a local folder and sends them to Google's NotebookLM, and you ask questions that are answered from those files, with citations. With Claude Code or Codex installed on your own subscription, it also tutors you, tracks what you have mastered with the evidence behind every level, and writes and grades practice exams, all recorded on your machine in a SQLite database and a Markdown vault.

## Features

### With NotebookLM alone

- **Sources**: drop in PDFs, Word and PowerPoint files, Markdown, text, CSV or EPUB. Each file is filed into a bucket (syllabus, lectures, assignments, labs, readings, exams, code, other) and added to the course's own NotebookLM notebook; uploading a changed file keeps the old version.
- **Grounded chat**: questions answered only from the sources you tick, with citations you can open.
- **Concept lists**: NotebookLM drafts the course's concepts; you review the draft, then apply it.
- **Audio Overviews**: NotebookLM podcasts, briefed on your weakest concepts or framed for an exam.
- **Every other NotebookLM artifact**: quizzes, flashcards and reports, saved beside the course's files.
- **A dashboard**: usage, provider health and mastery as one HTML file.

### With Claude Code or Codex

- **Tutoring sessions** grounded in your sources, in the browser or the terminal, with three teaching personas (simplifier, exemplar, analogist) you can switch between mid-session.
- **Mastery tracking with evidence**: after each session an Analyzer reads the transcript and records evidence for each concept. A mastery level (0 to 5) changes only with the evidence that justifies it, and its retention fades between reviews.
- **Challenger probes**: when the Analyzer proposes a big jump, your next session asks one short question to confirm it (or you skip it).
- **Practice exams** from a short YAML spec: one model writes the questions and the other critiques them; multiple-choice answers are checked against the key, open answers are graded by a model that didn't write them, and every graded answer becomes evidence.
- **With both installed**, the model that teaches you is never the one that judges you, and BrightLearn learns from measured runs which model is better at each task.

## Quick start

### What you need

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

Nothing is billed per request: NotebookLM, Claude Code and Codex all run on their subscriptions. `ANTHROPIC_API_KEY` must be unset; BrightLearn removes it from every model call, and `brightlearn doctor` flags it when it is set.

### Install and run

```sh
git clone https://github.com/its-Simy/learn-by-principals.git brightlearn && cd brightlearn
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

Setup installs uv (with its own Python 3.12), pnpm and Node when they are missing, installs the Python packages exactly as `uv.lock` says, and builds the web app. Then `brightlearn setup` makes the home folder, logs in to NotebookLM through Chrome or Edge, and prints doctor's table of what is ready, with the install lines for the optional model CLIs.

`setup` is safe to run again: finished steps are skipped. `start` opens the app in your browser once the server answers; running it a second time just opens the page again. The app serves only your own machine (`127.0.0.1`), with no login, so nobody else can reach it.

Flags that go to `brightlearn setup` can follow the script: `./setup.sh --account you@gmail.com` skips the prompt, `--skip-login` defers the login, `--relogin` repeats it, `--browser msedge` picks Edge, `--yes` never prompts, and `--dev` also installs the test tools.

## How it works

1. **Your files** go into a local course folder, `~/.brightlearn/courses/{term}/{course}/{bucket}/`, uploaded by hand in the web app.
2. **NotebookLM** holds one notebook per course with every file but the `code` bucket. It answers questions from those files with citations, and makes the Audio Overviews and other artifacts.
3. **Claude Code or Codex** (optional) do the reasoning: tutoring, analysing each session, Challenger probes, and writing, critiquing and grading exams. Each call gets a compact package of a few thousand tokens (your mastery, the relevant concepts and passages), never your whole history.
4. **The learner memory** is a SQLite database (courses, concepts, mastery, evidence, sessions and a ledger of every model run) and a Markdown vault (transcripts, summaries, concept drafts and exams), both on your machine.

The web app has three panes, after NotebookLM's:

- **Sources**: upload by drag and drop, see each file's state in NotebookLM, and tick the files a question should use.
- **Chat**: with no session, a grounded answer from the ticked sources; start a session and the same box talks to your tutor ("Sources only" still sends a plain grounded question). Every wait shows its step and how long it has taken.
- **Studio**: tiles for Mastery, Practice exam, Audio Overview and Concepts, each opening its own view, with the jobs in progress and everything made listed under them.

What it promises:

- **Nothing is billed per request.** Every service runs on a subscription you already have, or is free.
- **Every outside service sits behind one interface**, so NotebookLM, a model or the storage can be swapped without touching the rest.
- **Nothing is deleted.** A replaced file keeps its old version, a dropped concept is retired with its history, and old sessions are archived; models are sent only what the task needs.
- **Mastery needs evidence.** No level is set without the recorded evidence behind it, which you can inspect.
- **Learning is inferred from normal conversation.** There are no forced quizzes; a Challenger asks one question only when a big jump needs confirming.
- **Teaching and evaluation run on different models**, so the tutor never grades its own teaching.

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

## Contributing

All work lands on the `dev` branch, so open pull requests against `dev`; CI runs the tests, lint and the web build on macOS, Windows and Ubuntu for every one. `main` is promoted from `dev` by pull request once CI is green and the Playwright tour of the web app passes, and nothing is pushed to it directly, so it is always the last version that worked end to end.

[CONTRIBUTING.md](CONTRIBUTING.md) has the setup, the test tiers and the dev loop; [CLAUDE.md](CLAUDE.md) has the principles, the repo layout, the conventions and the decision log. [TICKETS-4.md](TICKETS-4.md) is the backlog, [docs/web-plan.md](docs/web-plan.md) the web app's design, [web/README.md](web/README.md) the web dev loop, and [docs/validation-log.md](docs/validation-log.md) the first runs against real accounts.

## Roadmap

Not scheduled yet, from the backlog's [Still not ticketed](TICKETS-4.md#still-not-ticketed) list:

- An install without Node or a clone: one `uv tool install brightlearn`.
- A local model (Ollama) for small housekeeping tasks, such as filing an upload whose name doesn't say what it is.
- Working out which concepts a question is about with a model, instead of matching keywords.
- Zoom links and other link-only course items as sources.
- Uploading a whole folder of files from the command line.
- Changing a course's term.
- Exporting a practice exam to PDF.
- The quoted evidence behind each mastery level in the Mastery view, and a Markdown note per concept in the vault.
- Running two long jobs (an exam and a podcast) at once, and cancelling a queued job.
- Each Audio Overview's format and length in its list.
- A clear message when a teaching persona can't run yet on a new course, instead of "No provider could answer".
- Codex installed through npm on Windows, used without its shim's problems.
- A model provider that uses API keys, for a future multi-user version.

## License

MIT; see [LICENSE](LICENSE).

## Acknowledgements

- [NotebookLM](https://notebooklm.google.com) by Google, which reads your files and grounds every answer.
- [notebooklm-py](https://github.com/teng-lin/notebooklm-py) by Teng Lin, the unofficial Python client BrightLearn reaches NotebookLM through.
- [Claude Code](https://claude.com/claude-code) by Anthropic and [Codex](https://github.com/openai/codex) by OpenAI, the model CLIs that tutor, analyse and grade.

BrightLearn is an independent project, not affiliated with Google, Anthropic or OpenAI.
