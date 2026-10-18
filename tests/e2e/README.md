# The browser tour (e2e)

A Playwright tour of the web app (Sources | Chat | Studio, `/system`, a phone-width window) against `scripts/dev_server.py`, which serves the real API and the built SPA on the test fakes. No account, no network and no quota: everything a page shows comes from the fakes in `tests/fakes/` and the data the dev server seeds.

The default `uv run pytest` leaves these tests out (`addopts = "-m 'not e2e'"`); `-m e2e` brings them in.

## Before the first run

- `./setup.sh --dev` (or `setup.cmd --dev`) installs `pytest-playwright` from the `dev` group and builds `web/dist`. After a web change, rebuild with `pnpm --dir web build`: the tour drives the build, not Vite. Without `web/dist/index.html` the tour is skipped, or fails when `CI` is set.
- A browser: `uv run playwright install chromium` downloads Playwright's Chromium. Without it, the harness uses the installed Google Chrome (`channel="chrome"`); `BRIGHTLEARN_E2E_CHANNEL=chrome` (or `msedge`, ...) forces a channel either way.

## Running it

```sh
uv run pytest -m e2e tests/e2e                                   # the whole tour, headless Chromium
uv run pytest -m e2e tests/e2e --browser-channel chrome          # in the installed Chrome
uv run pytest -m e2e tests/e2e/test_chat_session.py --headed --slowmo 300   # watch one module
uv run pytest -m e2e tests/e2e --tracing retain-on-failure --screenshot only-on-failure
```

The whole tour takes under a minute. Every module also passes on its own.

## How it is put together

- `conftest.py` starts one `scripts/dev_server.py --delay 0` per test module, on a free port with a scratch home of its own, so a module's tests share its state and no module sees another's. It waits for `GET /api/health`, and stops the server (SIGTERM, then SIGKILL) at the module's end. A module that needs a different server overrides `server` itself, as `test_no_models.py` does with `--no-models`.
- Each test gets a fresh browser context (1400×900, `en-US`, `America/New_York`) whose `base_url` is the module's server, so tests go to relative URLs: `page.goto("/courses/CSE220")`.
- `helpers.py` holds the shared locators and actions: `studio(page)`, `tiles(...)`, `upload(page, name, text)`, `send(page, text)`, `choose(scope, combobox, option)` and `system_section(page, title)`.

| Module | What it walks through |
| --- | --- |
| `test_home.py` | Light by default, the course card, the dark theme across a reload, New course (name only, derived code, `-2` on a repeat) and its empty panes, the not-found page |
| `test_sources.py` | The seeded files and the selection, an upload that links, one that fails (Retry fails again), a file in the `code` bucket |
| `test_chat_ask.py` | An ask with no session: Markdown, citation chips and their excerpts, scoping to the checked sources |
| `test_chat_session.py` | One ordered tour: the seeded Challenger probe upheld, a tutor turn, a rating, "Sources only", End and the Analyzer's note, Mastery, a second session's probe skipped, History and a transcript |
| `test_chat_errors.py` | A rate-limited turn: the error bubble and its reset time, the health dots, Try again, `/system` |
| `test_studio_concepts.py` | The tiles and where Back puts the focus; Seed, review, Save, Apply, and the Mastery view after it |
| `test_studio_exams.py` | One ordered tour: a spec, generation, taking an attempt through a reload, Finish, Grade, Results, Paper, the mastery it moved |
| `test_studio_audio.py` | A Brief audio overview: its episode, the audio route, the brief |
| `test_system.py` | Doctor's nine checks (rows, not statuses) and every dashboard section |
| `test_phone.py` | 390 px wide: the rails as sheets, and no page scrolls sideways |
| `test_no_models.py` | `--no-models`: the hints, a turn's error naming the install step, providers "disabled" |

## What the fakes do

`scripts/dev_server.py`'s docstring and `web/README.md` have the details. What the tour relies on:

- CSE220 ("Systems Fundamentals I") is seeded with three linked files (`CSE220 Syllabus.md`, `Lecture 3 - Pointers.md`, `HW1 Bit Manipulation.txt`), five concepts at levels 0–4 (Dynamic memory allocation 0, Bitwise operators 1, Recursion 2, Pointers 3, Data representation 4), one pending Challenger probe on Pointers, healthy providers, ledger rows and benchmark samples.
- NotebookLM answers in Markdown citing up to two of the asked sources, and a seed returns six concepts (it adds "Stack frames"). A file whose name contains `fail` is refused at link time.
- Both models answer tutor turns with the same Markdown (a table included). A question saying "rate limit" makes both rate-limited for 20 s, recorded in the server's database: that is why `test_chat_errors.py` has a server of its own.
- The Analyzer quotes the learner and proposes a two-level jump on the weakest concept, so every session with a tutoring turn queues a probe for the next; answering a probe upholds its jump, Skip defers it.
- Exams: a multiple-choice answer is always "B", and an open answer is correct when it contains "correct". An audio overview is a short `audio/mp4` file.

## Writing a test

- Find things by role and accessible name (`get_by_role`, `get_by_label`), scoped to a rail, a dialog or a section; read the component in `web/src/` for a name.
- Assert end states with `expect(...)`, which retries for 10 s. Jobs are polled every 2 s, so a pending row may never be seen.
- A `role=status` or `role=alert` text is often repeated in a toast: scope it to its pane, or `.filter(has_text=...)`.
- Times are local and change: match draft and episode titles and reset times with a regex (`^Draft of `, `Resets at \d`), and never assert the term.
- A Radix Select is no `<select>`: use `choose()`, never `select_option()`. The file input is hidden: `upload()` sets its files.
- When steps need the state the last one left, write one ordered tour test per module rather than tests that depend on their order.

## When a test fails

With `--tracing retain-on-failure --screenshot only-on-failure`, the failed test's folder under `test-results/` holds `trace.zip`, `test-failed-1.png` and `server.log` (the dev server's log, copied by the harness). Open the trace, a step-by-step replay with the DOM, the network and the console:

```sh
uv run playwright show-trace test-results/<test folder>/trace.zip
```

`test-results/` is gitignored and emptied at the start of every run.
