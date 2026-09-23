# Problems — TICKETS-2 build

Problems that the tickets don't settle. Each one says what I did (usually the most literal reading, or nothing) so work could move on. Nothing here is solved; each needs a decision from Simon.

## Setup

### P1. `CLAUDE.md` and `TICKETS.md` didn't exist
`backlog.md` held CLAUDE.md's content (its title was "BrightLearn — CLAUDE.md"). `TICKETS.md`, which holds BL-001–BL-006 and BL-008, isn't in the repo.
- **What I did:** renamed `backlog.md` to `CLAUDE.md` and saved the pasted backlog as `TICKETS-2.md`. The old tickets are still missing.

### P2. None of the Phase 0–1 work was committed
- **What I did:** worked on branch `tickets-2`. The first commit is the existing work as-is ("Phase 0–1 baseline"), so each ticket's commit shows only that ticket's diff. That baseline commit doesn't use the `BL-0XX:` format. `.claude/` is left uncommitted.

## BL-000

### P3. `refresh_source` is still in `KnowledgeProvider`
The ticket replaces `add_drive_source` and adds `remove_source`/`list_sources`, but says nothing about `refresh_source`. That method only made sense for Drive-backed sources that auto-sync.
- **What I did:** kept it in the interface.

### P4. There is no config file
"Replace Drive keys with `storage_root = "~/.brightlearn/courses"`" reads like a config file, but config is environment variables only (`BRIGHTLEARN_*`), and `CLAUDE.md` had no config section.
- **What I did:** added a Config table to `CLAUDE.md`. `storage_root` is overridden with `BRIGHTLEARN_STORAGE_ROOT`.

## BL-007R

### P5. Overwriting a changed file breaks principle 3
The ticket says a changed file overwrites the old one. Principle 3 says "Don't delete anything". On Drive, old revisions were kept forever; on disk, the previous version of a re-uploaded lecture is gone.
- **What I did:** overwrite, as the ticket says. A possible fix is to move the old file to a `.versions/` folder before overwriting. Not built.

### P6. `sync` is broken between the BL-007R and BL-009R commits
Changing the `StorageBackend` interface broke the old Drive-based engine. It is rewritten in BL-009R, so at the BL-007R commit the engine tests are replaced by a skip.

### P7. Leftover Google OAuth setup
`gdrive.py`, its tests and the Google libraries in `pyproject.toml` are removed. `~/.brightlearn/client_secret.json` is no longer used. The OAuth client in the Google Cloud console can be deleted if Drive isn't coming back. The Google packages are still installed in `.venv` until the next `uv sync`.

## BL-009R

### P8. The `resources` table had no `url` column
BL-009R says to store a Link topic's `url`, but BL-000's table has no column for it.
- **What I did:** added `url` to the table and to `CLAUDE.md`.

### P9. "Stale" can be lost, and stale rows would re-download every run
Taken literally, only `synced` rows are skipped. A `stale` row, one whose NotebookLM copy is out of date, is then downloaded again on every run. If those bytes match the last download, the row goes back to `synced` and the NotebookLM source is never replaced.
- **What I did:** rows that are `synced` or `stale` with the same `last_modified` are skipped. A `stale` row stays `stale` until BL-015 relinks it.

### P10. The Brightspace provider never raises `SessionExpired`
The engine now catches `SessionExpired`, calls `ensure_session()` and retries once, as the ticket says. But `BrightspaceSessionProvider` still handles expiry itself: it re-logs in inside `_get`, and if that fails it raises `LMSError`. So in real runs the engine's retry path never fires. Only the fakes use it.
- **What I did:** added `SessionExpired` to `core/providers/lms/base.py` and left the provider alone.

### P11. Schema versioning and your existing database
Nothing tracked schema versions, but BL-011R checks one and BL-018 asks for "migration v2". Your `~/.brightlearn/brightlearn.db` has the old Drive-era `resources` table, with no rows.
- **What I did:** added numbered migrations tracked in `PRAGMA user_version`; v1 is the new `resources` table plus `model_runs`. On an unversioned database, an **empty** Drive-era table is dropped and recreated. A **non-empty** one is refused with an error, because there's no migration for Drive rows.

### P12. Deleting a local file doesn't trigger a re-download
The skip check reads only the manifest. If a file is deleted from `storage_root` by hand, its row still says `synced`, so it's skipped. `--force` gets it back.

### P13. `--force` isn't defined
The ticket lists `--force` without saying what it does.
- **What I did:** it re-downloads every file, even ones the manifest says are current. `sync_course` takes `force=`.

## BL-010R

### P14. Term label format changed to `Fall-2026`
The acceptance path is `~/.brightlearn/courses/Fall-2026/CSE220/…`, but the date-based default made `2026-Fall`.
- **What I did:** `default_term` now returns `{Season}-{Year}`. Reading the term from Brightspace (questions.md items 6 and 25) is still open.

### P15. `--all` still files past courses under the current term
`myenrollments` returns Summer 2025 through Fall 2026, plus non-course offerings (questions.md items 25–26). `--all` syncs every one of them into the current term's folder.
- **What I did:** nothing. Use `--course` until the term is parsed from the course name.

### P16. Manual acceptance pending (you)
Run `brightlearn sync --course CSE220` twice. Check that files land in `~/.brightlearn/courses/Fall-2026/CSE220/{bucket}/` and that the second run shows everything skipped. CLI tests with a fake LMS pass.

## BL-011R

### P17. "All green" needs one sync first
Doctor shows `DB schema` as a yellow warning (v0, migrates on next run) until `brightlearn sync` has run once. Everything else on this machine is green: Chromium is installed and Brightspace `whoami` returns 200. NotebookLM, Claude Code and Codex show "not configured" in grey until their tickets land.

## BL-013R

### P18. Spike not run (you)
`scripts/spike_c.py` is written. `docs/spike_c_results.md` holds the API as read from the notebooklm-py 0.8.2 wheel, but not the output of a live run. Setup steps:
1. `uv pip install "notebooklm-py[android,browser]"`. The venv has no `pip`, so plain `pip install` won't work.
2. `NOTEBOOKLM_HOME=~/.brightlearn/notebooklm notebooklm login --master-token --account <gmail>`.
3. Run `brightlearn sync --course CSE220`, then the spike. Paste its output into `docs/spike_c_results.md`.

### P19. The spike imports `notebooklm` outside `core/providers/`
Principle 2 bans that, but the ticket asks for a spike against the raw library. `tests/test_principles.py` doesn't scan `scripts/`.
- **What I did:** built it as the ticket says.

### P20. NotebookLM credentials land outside `~/.brightlearn/` by default
`notebooklm login` writes `master_token.json` and `storage_state.json` to `~/.notebooklm/profiles/default/`. `CLAUDE.md` says secrets live under `~/.brightlearn/` only.
- **What I did:** documented `NOTEBOOKLM_HOME=~/.brightlearn/notebooklm` in the spike and in `CLAUDE.md`. Don't use `NOTEBOOKLM_HOME=~/.brightlearn` itself: the library falls back to `$NOTEBOOKLM_HOME/storage_state.json`, which there is Brightspace's cookie file.

### P21. Things the tickets assume that the library doesn't do
- **`notebooklm auth status`** doesn't exist. The nearest command is `notebooklm auth check`.
- **Audio downloads** are `.m4a` (AAC), not MP3.
- **Find-by-title** doesn't exist; the code filters `notebooks.list()`.
- **Removing a source** needs the notebook id. The ticket's `remove_source(source_id)` doesn't take one.
- **Only some file types upload:** `.pdf .docx .pptx .txt .md .csv .epub`. Code files (`.c`, `.s`) and other extensions can't be added, which is one more reason BL-015 skips `code`.

## BL-014

### P22. Provider built before the spike ran
The provider follows the 0.8.2 source, not observed behaviour. Unit tests use mocked transports and a mocked client. **(you)** Install the library (P18), then run `brightlearn dev nlm-test`. It finds or creates `BrightLearn-spike`, adds the syllabus, queries it, and removes the source.

### P23. Fallback rules beyond the ticket
The ticket says: a failed Android call retries once on web and marks the provider `LIMITED`; both failing → `BROKEN`. I added these exceptions:
- **Rate limits:** a `RateLimitError` sets `RATE_LIMITED` and does **not** retry on web. The quota is per account, so a retry burns a call.
- **Caller errors:** not-found errors, validation errors, and a generation that NotebookLM itself failed are raised straight away. They don't fall back and the state doesn't change.
- **Auth:** if both transports fail with auth errors, the state is `AUTH_EXPIRED`, not `BROKEN`.
- **No sticky state:** every call tries Android first again, so the state goes back to `AVAILABLE` once Android works.

### P24. A web retry can create duplicates
If Android actually did the work but the response failed, retrying `add_file`, notebook creation or a generation on web creates a second source, notebook or artifact. Generating twice also costs quota twice.
- **What I did:** nothing.

### P25. Every query continues the last conversation
Without a `conversation_id`, `chat.ask` extends the notebook's most recent conversation, so each BrightLearn question is answered as a follow-up to the one before.
- **What I did:** nothing.

### P26. Downloads fetch "the latest completed artifact"
Downloads pass `artifact_id=None`. That is correct only while nothing else generates in the same notebook at the same time.

### P27. Schema v1 changed after it was committed
The `notebooks` table (BL-014) and the `deferred` sync state (BL-015) went into migration v1 after BL-009R had already committed v1. A database created between those commits would miss both and needs deleting. None exists: your database is still v0.

### P28. Ledger fields for NotebookLM calls
- `model` holds the transport (`android`/`web`), because NotebookLM doesn't report a model.
- Token estimates are recorded for queries only.
- `core/ledger/ledger.py` (`ModelRun`, `Ledger.record`) was created here, because this ticket needs it before BL-021.

### P29. Finding a source's notebook
`remove_source`, `source_fulltext` and `refresh_source` get only a source id, but the library needs the notebook too. The provider looks it up in the ids it has seen, then in `resources.notebook_source_id`. Otherwise it raises.

### P30. Doctor shows NotebookLM as a yellow warning until the library is installed
Once installed, doctor runs `python -m notebooklm --storage ~/.brightlearn/notebooklm/profiles/default/storage_state.json auth check --json`. That checks web cookies only, not the Android master token.

## BL-015

### P31. The source cap counts manifest rows, not the notebook
The cap check counts rows already linked in the manifest. Sources added some other way (the spike, or by hand in the NotebookLM UI) don't count, so the real notebook can pass 50.
- Linked sources keep their slot. A higher-priority file that arrives later (say, a new exam) is deferred rather than pushing out a linked lecture.
- With `--include-code`, `code` and then `other` rank after `assignments`.

### P32. Unsupported file types fail on every sync
NotebookLM accepts `.pdf .docx .pptx .txt .md .csv .epub` (P21). A `.zip`, `.xlsx` or `.c` in a linked bucket fails `add_file` on every run and makes `sync` exit 1.
- **What I did:** nothing. There's no file-type filter and no state for "can't link".

### P33. A rate limit stops the link step
If NotebookLM returns a rate limit, that course's link step stops, and the remaining rows are retried on the next sync. Other failures are recorded and the step carries on. The ticket doesn't cover this.

## BL-016

### P34. Manual acceptance pending (you)
After P18 and a linked sync, run `brightlearn ask --course CSE220 "How are pointers introduced in lecture 3?"`. Citations show `filename (bucket)` from the manifest. A citation to a source the manifest doesn't know, such as one added by hand, shows its raw id instead.

## BL-017

### P35. "Quiz/flashcards also saved as JSON" is ambiguous
- **What I did:** quiz and flashcards are saved **only** as JSON. The library can also export Markdown or HTML, but nothing saves those.
- `--format` and `--length` apply only to audio. `--format` also sets the report type.
- Quiz and flashcard difficulty and quantity have no flags.

### P36. The audio artifact will be `.m4a`, not MP3
The acceptance asks for "one short MP3", but NotebookLM returns AAC/MP4 (P21). The file keeps the extension the provider downloads.
- **(you)** Manual acceptance is pending: `brightlearn generate quiz --course CSE220` and `brightlearn generate audio --course CSE220 --format brief --length short`.

## BL-018

### P37. `mastery` can't point at its evidence
Principle 4 (and the spec) says every mastery row points at the evidence ids that justify it, but the `mastery` table in `CLAUDE.md` only has `evidence_count` and `last_evidence_at`.
- **What I did:** `set_mastery` refuses an empty list or ids that aren't that concept's evidence. The ids themselves aren't stored. A `mastery_evidence` link table, or a JSON column, would fix it.

### P38. Values the tickets don't define
- **Retention decay:** unchanged for 2 days after the last evidence, then halving every 14 days. It's computed from `confidence`, so running it twice gives the same result.
- **`weakest` order:** level, then retention, then confidence, then name. A concept with no mastery row counts as level 0.
- **`last_reviewed`:** set whenever `set_mastery` runs.

### P39. Other schema choices
- `prerequisites` and `exam_tags` are stored as JSON arrays.
- `evidence` has triggers that block UPDATE and DELETE (append-only).
- The `sessions` table isn't in `CLAUDE.md`'s data model, so I added it there, as the ticket defines it.

## BL-019

### P40. The vault lives inside the git repo by default
`CLAUDE.md`'s layout and the spec ("Git-versioned") put the vault at `<repo>/memory/`. Session transcripts, mastery and misconceptions would then be committed with the code. If the GitHub repo is public, pushing it publishes them.
- **What I did:** `vault_dir` defaults to `<repo>/memory`, and `BRIGHTLEARN_VAULT` overrides it. Nothing is gitignored.

### P41. Misconceptions have no home
`write_concept_note` takes misconceptions as a list of strings, and BL-025 needs "misconception notes", but no table or ticket defines where misconceptions are stored. The spec's `memory/misconceptions/` folder isn't built.
- **What I did:** callers use the `excerpt_ref` of that concept's evidence rows of type `misconception`.

### P42. Transcript and summary are separate files
BL-026 appends the transcript to `memory/sessions/{id}.md`, so the BL-019 summary goes to `memory/sessions/{id}.summary.md`. `sessions.summary_path` points at the summary.

### P43. New dependency: PyYAML
PyYAML is added to `pyproject.toml` and installed in `.venv` with `uv pip install`. There's no `uv.lock` in the repo.

## BL-020

### P44. `week` has nowhere to go
The seed prompt asks for `week`, as the ticket says, but `concepts` in `CLAUDE.md` has no `week` column.
- **What I did:** `week` stays in the draft YAML and is dropped on apply.

### P45. How "never applies without review" is enforced
The draft is written with `reviewed: false`, and `concepts apply` refuses to load it until someone edits that line to `true`.

### P46. Concept ids come from names
A concept's id is `{course}/{slug(name)}`, for example `cse220/pointer-arithmetic`.
- **Renames:** renaming a concept in the draft creates a new concept. The old row is never deleted.
- **Prerequisites:** a prerequisite is linked by its name's slug. Names that aren't concepts in the draft are reported but still stored.

### P47. Seeding relies on NotebookLM answering in raw JSON
The prompt asks for a JSON array only, and the parser tolerates code fences, prose and `[n]` citation markers. A prose-only answer fails with an error, and nothing is written. Seeding also inherits P25: the query continues the notebook's last conversation.

## BL-021

### P48. Who writes model calls to the ledger
The spec says the Model Router is the only thing that talks to models and that it logs each call. So Claude and Codex runs are recorded by the router (BL-026) with `ModelRun.from_result` / `ModelRun.from_error`. NotebookLM calls are still recorded inside that provider (BL-014), so there are two recording paths.
- `UsageHint` isn't defined anywhere. I gave it: tokens, `limit_message`, `resets_at`, `raw`.
- `today_summary()` uses the UTC date, so evening runs in New York count toward tomorrow.

## BL-022

### P49. `claude` isn't on PATH on this machine
The only copy is the one bundled with the VS Code extension, at `~/.vscode/extensions/anthropic.claude-code-2.1.280-darwin-arm64/resources/native-binary/claude`. **(you)** Install the CLI, or put it on PATH, then run `brightlearn dev model-test claude "Say hi"`. Doctor shows Claude Code as a yellow warning until then.

### P50. Claude's JSON output wasn't checked live
- **What was checked:** the flags, against the bundled `claude --help` (2.1.280).
- **What wasn't:** the output shape (`result`, `is_error`, `subtype`, `usage`, `modelUsage`) and the usage-limit wording (e.g. "Claude AI usage limit reached|<epoch>", "5-hour limit reached ∙ resets 3pm"). Both come from memory, not from a run, because a run spends your quota. The manual test will show whether the parser is right.

### P51. Claude CLI limits
- **Output length:** `claude -p` has no max-output-tokens flag, so `TaskPackage.max_output_tokens` is ignored.
- **Settings still load:** `--tools ""` disables tools. The scratch working directory keeps the repo's `CLAUDE.md` out. User-level `~/.claude` settings, hooks and plugins still load. `--bare` would skip them, but it only accepts `ANTHROPIC_API_KEY` auth, which breaks principle 1.
- **Health checks cost quota:** `health()` makes a real one-token call, at most once every 10 minutes. Doctor only runs `claude --version`.
- **Timeouts:** a timeout sets the state to `LIMITED`.

## BL-023

### P52. `codex` isn't installed, so nothing about it is verified
The ticket says to check the flags with `codex --help`, but `codex` isn't on this machine. So nothing below has been checked:
- **Flags:** `codex exec --skip-git-repo-check --sandbox read-only --color never -o <file> <prompt>`.
- **Output:** a `model: …` line in the header and a `tokens used: N` line.
- **Limit messages:** "You've hit your usage limit…" and "429 Too Many Requests".

All of these come from memory. **(you)** Install Codex, run `codex --help`, and compare. Then run `brightlearn dev model-test codex "Say hi"`. Doctor shows Codex as a yellow warning until then.

### P53. Codex quirks
- **Allowance:** I know of no way to read the `/status` allowance from `exec` mode, so only limit messages are parsed.
- **System prompt:** `codex exec` has no system-prompt flag, so the persona prompt is prepended to the user prompt with a `---` separator.
- **API keys:** `OPENAI_API_KEY` is removed from Codex's environment as well as `ANTHROPIC_API_KEY`, in case an API key would switch Codex to metered billing (principle 1). The ticket only names `ANTHROPIC_API_KEY`.

## BL-024

### P54. Persona details the spec doesn't give
- **Challenger has no task type:** none in the spec's list fits, so it uses `question_gen`.
- **Coverage isn't built:** the spec says the eighth persona is "mostly code", and the ticket doesn't list it.
- **`min_anchor_level`:** `null` for every persona except Analogist (3).
- **Wording:** the text of each file is my own, following the spec's table. Each renders to roughly 250–330 tokens.
- **Module name:** `core.personas.list` shadows the builtin, as the ticket names it. `list_personas` is the same function.
