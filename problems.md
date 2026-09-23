# Problems — TICKETS-2 and TICKETS-3 builds

Problems that the tickets don't settle. Each one says what I did (usually the most literal reading, or nothing) so work could move on. The triage below (BL-028) records which have since been fixed.

## Triage (BL-028)

"Before real data" means the first real sync or tutoring session would otherwise do one of three things: put personal data somewhere it shouldn't be, write learner rows that can't be trusted or migrated later (evidence and mastery history are append-only), or lose course files. Everything else is "later" and is **not** fixed.

### Fixed in BL-028: your decisions
| # | Fix |
| --- | --- |
| P5 | Before a changed file is replaced, the old one is kept as `{bucket}/_versions/{name}.{old_hash[:8]}`. It's a hard link, or a copy where the filesystem has no hard links. |
| P20 | The provider sets `NOTEBOOKLM_HOME=~/.brightlearn/notebooklm` itself, and doctor checks that location. **Added:** `brightlearn dev nlm-login --account <gmail>`, which runs `notebooklm login --master-token` into that location. A plain `notebooklm login` would still write to `~/.notebooklm`; doctor detects that and says so. |
| P25 | A query with no conversation deletes the notebook's latest conversation, then asks. That is the library's documented way to start fresh. A tutor session carries one `Conversation` handle, and follow-ups reuse its id. |
| P37 | Migration v3 adds `mastery_history`, which is append-only. Every `set_mastery` writes a row with its `evidence_ids` and `changed_by` (`analyzer` or `manual`). |
| P40 | `vault_root` now defaults to `~/.brightlearn/vault/`. There was no `memory/` folder in the repo to remove. `/memory/` is gitignored as a guard, and `personas/` stays in the repo. |
| P58 | The routing order comes from `[routing]` in `~/.brightlearn/config.toml` (teaching `claude, codex`; analysis `codex, claude`). Decision-log entry added to `CLAUDE.md`. |

### Fixed in BL-028: my triage, before real data
| # | Why it couldn't wait | Fix |
| --- | --- | --- |
| P64 | Evidence rows are append-only, so a made-up excerpt, or one taken from the tutor's words, would stay in the learner model for good. | An Analyzer item is written only if its excerpt occurs in the learner's own `**Learner:**` turns. A label, quotes and ellipses are allowed around it. Otherwise it's skipped and reported. |

### Later, not fixed
| # | Why it can wait |
| --- | --- |
| P3, P4 | Harmless. `config.toml` now exists, but only for `[routing]`. |
| P10 | Real runs re-log in inside the provider. The engine's retry is only exercised by the fakes. |
| P12 | `--force` recovers a deleted local file. |
| P15 | Misfiles past terms. **Use `--course`, not `--all`, until the term is read from the course name.** |
| P23, P24 | Revisit after the spike. Duplicate NotebookLM sources are possible but rare, and don't touch BrightLearn's own data. |
| P26, P31, P32, P33 | Single user. Failures are loud but lose nothing. |
| P35, P38, P41, P44, P46, P47 | Nothing is lost: misconceptions are evidence rows, and `week` stays in the draft YAML. Tunable or re-derivable later. |
| P48, P51, P53, P54, P55, P57, P59, P60, P62 | Behaviour to tune once there's real usage. `needs_challenge` stays in session summaries until a Challenger exists. |
| ~~P65, P66~~ | Fixed in BL-029 (TICKETS-3). |

### Resolved, accepted or informational
P1, P2 (decided as done) · P6 (historical) · P7 (your cleanup, whenever) · P8, P9, P11, P13, P14, P17, P27, P28, P29, P39, P42, P43, P45, P56, P63 · P19, P21, P36 (accepted) · P30 (superseded by P20).

### Waiting on you or on data
P16, P18, P22, P34, P49, P50, P52, P61. For P50 and P52, send the three CLI outputs.

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
- **What I did:** `week` stays in the draft YAML and is dropped on apply. **Fixed in BL-031:** migration v5 adds `concepts.week`, and `apply` stores it.

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

## BL-025

### P55. One NotebookLM query per tutor turn
Each compile sends the learner's raw question to NotebookLM. Every turn costs quota, and a short follow-up like "why?" is a poor grounding query. Because of P25, NotebookLM also treats every question as a follow-up to the notebook's previous one, including questions from other sessions.

### P56. Choices beyond the ticket's caps
- **Token counts:** estimated at 4 characters per token.
- **Question cap:** the learner's question is capped at 400 tokens, which keeps the 3,500 total guaranteed. The ticket doesn't cap it.
- **Citations first:** citations get up to a third of the 1,200-token source budget, and the answer text is cut before they are.
- **Concept matching:** a concept matches when every significant word of its name appears in the question. Plurals are stripped naively ("pointers" matches "Pointer").
- **Anchors:** the Analogist's anchors are the learner's five strongest concepts at level 3 or higher.

### P57. The tutor answers without sources when NotebookLM fails
If the NotebookLM query fails (rate limit, auth, broken), the package is still built. Its source section reads "(course sources unavailable: …)", so the tutor answers from the model alone. The ticket doesn't say what should happen.

## BL-026

### P58. Router v0 hardcodes Claude, which conflicts with principle 8
Principle 8 says model strengths are never hardcoded and routing reads `benchmarks`. The ticket asks for "Claude for teaching, Codex if Claude is RATE_LIMITED", and there is no `benchmarks` table yet (Phase 10). `CLAUDE.md` should win here, but that would mean not building the tutor.
- **What I did:** built the ticket's v0 order, `["claude", "codex"]`, in `cli/tutor.py`, with a comment saying it's v0.

### P59. The router only falls back on rate limits
**Superseded by BL-035:** router v1 falls back on any model error. Following the ticket, a Claude that is missing from PATH, logged out or crashing fails the turn rather than falling back to Codex.
- Once Claude is rate limited, it's skipped for the rest of the process; nothing checks when the limit resets.
- Until P49 and P52 are fixed, neither CLI is installed, so every tutor turn prints "(no answer: `claude` is not on PATH)".

### P60. A fallback mid-session leaves no model for the Analyzer
If Codex takes over partway through a session, `sessions.tutor_provider` is `"claude,codex"`. Principle 6 then leaves no different provider to run the Analyzer (see BL-027).

### P61. Manual acceptance pending (you)
Run a 5-turn session on pointers with `brightlearn tutor --course CSE220 --persona simplifier`. It needs the NotebookLM setup (P18), a linked sync, and the Claude CLI (P49).

## BL-027

### P62. `needs_challenge` has no table
Jumps of more than one level are logged, and written to the session summary (`memory/sessions/{id}.summary.md`). Nothing stores them where a later Challenger could query them.

### P63. Analyzer choices the ticket leaves open
- **Which level counts as "current":** the level at the **start** of the session. Two +1 proposals in one session can't stack into +2.
- **Confidence:** the evidence strength sets the new mastery's confidence: weak 0.4, moderate 0.6, strong 0.8.
- **What `set_mastery` cites:** all of that concept's evidence from the session.
- **Unknown concepts:** items naming a concept that isn't seeded are skipped. Until `concepts seed/apply` has run for a course, the Analyzer records nothing.
- **Transcript length:** the transcript sent is capped at its last ~6,000 tokens.

### P64. The Analyzer's output is trusted
Nothing checks that an excerpt actually appears in the transcript, or that it's the learner's words rather than the tutor's. The persona's rules ask for this, but the code doesn't verify it.

## BL-028

### P65. Re-running `concepts seed` overwrites the reviewed draft
`seed` always writes `concepts.draft.yaml`, even over one that says `reviewed: true`. Applied concepts are safe in SQLite, but the reviewed file, including its `week` values (P44), is lost.
- **What I did:** nothing (triaged as later). **Fixed in BL-029.**

### P66. Fresh conversations delete NotebookLM chat history
Starting a fresh conversation means deleting the notebook's latest one. If `brightlearn ask` runs while a tutor session is open on the same course, it deletes the tutor's live conversation, and the tutor's next follow-up fails or starts over. The NotebookLM web UI also shows no chat history for BrightLearn notebooks. The decision log records this as accepted.
- **What I did:** nothing more. **Fixed in BL-029** (see P67).

---

# TICKETS-3

## BL-029

### P67. The open-session guard covers more than `ask`
The ticket names `ask`, but anything that starts a fresh conversation on a course deletes a live tutor's conversation the same way.
- **What I did:** `ask`, `concepts seed` and `tutor` (a second session on the same course) all refuse while `sessions` has an open row for that course, and say how to close it. Other courses aren't blocked.
- **`/ask` added to the tutor REPL.** The ticket's "`/ask` hint" had nothing to point at, so `/ask <question>` now asks NotebookLM inside the session's own conversation and prints the grounded answer with citations. It runs no model, and its lines go into the transcript as `**Ask (NotebookLM):**`, so the Analyzer doesn't read them as learner turns.
- **A crash leaves the session open.** EOF and Ctrl-C still end the session normally. Any other crash leaves the row open, and `ask`/`seed`/`tutor` refuse until `brightlearn sessions close --id X` (or `--all`). `close` only sets `ended_at`; it doesn't run the Analyzer on that transcript.

### P68. Which draft `concepts apply` loads
`seed` now writes `concepts.draft.{YYYYmmdd-HHMMSS}.yaml` (adding `-2`, `-3` if that second is taken) and never opens an existing file for writing. The old single `concepts.draft.yaml`, if present, counts as the oldest draft.
- **What I did:** `apply` loads the newest draft by default and `--draft FILE` picks another. If the newest isn't reviewed, `apply` refuses and lists the earlier drafts, so a reviewed older draft is never applied by accident.
- The diff `seed` prints is against the newest earlier draft, reviewed or not.

### P69. The version-integrity test relies on hard links
`_versions` copies are hard links, so an in-place write would change the kept copy, and the test catches that (a second test proves it by patching in an in-place write). On a filesystem without hard links the kept copy is a real copy, and an in-place write wouldn't be caught. APFS, where the tests run, has hard links.

## BL-030

### P70. Migration numbers follow ticket order
`challenges` is migration v4. BL-035 calls `benchmarks` "migration v4", but by then v4 is taken, so each ticket takes the next free number.
- A unique partial index allows one open (unresolved) challenge per concept. A second disagreement merges its reason into the open row. That is how "two pending challenges collapse to one" and "max one per concept per session" are enforced.

### P71. The tutor's estimate costs a model call
At `/end`, the provider that tutored gets one extra call (task type `tutor_estimate`, not in the spec's list) asking for one line, `Concept: level; …`. It's parsed against the course's concept names and stored as `tutor_estimate` in the session summary's front matter. It's only compared where the Analyzer also proposed a level for that concept. If the call fails, the session is analyzed without it.

### P72. A probe's grade follows the ±1 rule and is never re-challenged
The Analyzer grades the probe's exchange alone and writes evidence as usual. Only a proposal exactly one level from the current one changes mastery. A bigger jump, even one the probe confirms, is **not** applied and doesn't queue another challenge (principle 7: at most two rounds). So a probe that confirms "0 → 3" records strong evidence but leaves the level at 0. **Your call:** should a confirmed probe apply the jump?

### P73. Who asks and who grades
- The Challenger runs on the `[routing] teaching` order, and its grader on `analysis` minus the provider that wrote the question (principle 6). Its question is grounded with one NotebookLM query in the session's own conversation.
- The probe isn't tutoring. Its lines go into the transcript as `**Challenge …**` / `**Learner (challenge answer):**`, not as `**Learner:**`, so the end-of-session Analyzer can't count them twice, and the Challenger's provider isn't added to `tutor_provider`.
- **A question asked in an earlier session** (after `/skip`, or when grading failed) is asked again word for word. The table doesn't record who wrote it, so in that case the grader isn't kept off that provider.
- A challenge whose question can't be generated (model error) stays `pending`. One whose grading fails goes back to `asked`.

## BL-031

### P74. Concepts needed a week
The planner selects concepts by the spec's `weeks`, but concepts had no week (P44).
- **What I did:** migration v5 adds `concepts.week`, and `concepts apply` fills it from the draft. **(you)** Concepts applied before this have no week. Re-run `brightlearn concepts apply --course CSE220` once to fill them in. Until then, a spec with `weeks` leaves those concepts out; they're listed in `CoveragePlan.no_week` and can still be pulled in with `include`.

### P75. Spec rules the ticket leaves open
- **Required:** `course`, `exam`, `formats`, `difficulty`. `mode` defaults to `realistic`. `weeks` and `sources` default to "all". `include` and `exclude` default to none.
- **`formats`** are question counts: `multiple_choice`, `short_answer` or `coding`, with at least 1 question and at most 100.
- **`difficulty`** is `easy`/`medium`/`hard` given as either percentages summing to 100 or counts summing to the number of questions. Percentages are turned into counts by largest remainder (20/50/30 of 18 → 4/9/5).
- **`sources`** are bucket names, plus `study-guides` (study guides are filed in `exams`). Only validated here; BL-032 uses them.
- **Names in `include`/`exclude`** match a concept's name ignoring case and punctuation, or its id. A name in both is an error. Names that match nothing are reported, not errors.

### P76. How the modes weigh concepts
- **realistic:** each week weighs 1, split evenly among its concepts. An `include`d concept from outside the weeks gets the average concept weight.
- **weakness:** 5 − level, floored at 0.5.
- **diagnostic:** 1 − confidence, floored at 0.1. No mastery row counts as confidence 0.
- **challenge:** level 3+ only, weighted evenly. Rows are tagged `transfer` (target level 4). With nothing at level 3+, it's an error.
- **Rounding:** questions go to concepts by largest remainder, heaviest first. With more concepts than questions, the lightest get none and are left out. Each concept's questions are then split across formats and difficulties so every row and column sums exactly. Each row doesn't get the spec's exact mix: the heaviest concept gets its share of each column first, and later rows take what's left.

## BL-032

### P77. One Questioner call per plan row, not per question
Each plan row (one concept) is one `question_gen` call that asks for exactly that row's questions, each with its format and difficulty. That keeps quota use to one call per concept. Returned questions are matched to the requested slots. A question that is invalid, missing, or has the wrong format or difficulty is retried alone. A second failure drops it, logs a warning, and records it in `GenerationReport.dropped`. So a spec for 18 questions can produce fewer; BL-033's `exam create` says so when it happens.
- **Model errors** (no provider, auth) aren't validation failures. They stop generation with `GenerationError`, and nothing is written.

### P78. The persona files changed to match the ticket's schema
The Questioner's output shape listed `concept, level, question, answer, source`, which conflicts with the ticket's `{stem, options?, answer, rubric, difficulty, concept_id, format}`. `personas/questioner.md` now uses the ticket's schema, and a multiple-choice `answer` must be the exact text of an option. `personas/critic.md` now follows whatever format the task asks for (JSON `{index, issue, fix}` here), and falls back to its bullets otherwise.
- **"Strict"** means no extra keys, every required string non-empty, 3–6 distinct options for multiple choice (none for the other formats), and an answer key that is one of the options.

### P79. Grounding and critique details
- **Grounding:** one fresh NotebookLM query per concept, reused for that concept's retries and rewrites. It's limited to the spec's `sources` buckets (`study-guides` → `exams`); if none of those are linked, every source is used and a warning is logged. Because the query is fresh, `exam create` must refuse while a tutor session is open on the course (P66); BL-033 does this.
- **Critique:** one Critic call over the whole draft, kept off every provider that wrote a question. If no other provider is left (both tutored, or only one installed), critique is skipped and recorded in `critique_skipped`.
- **Rewrites:** each flagged question is rewritten once, off the Critic's provider. An invalid rewrite keeps the original, valid question, with a warning. Nothing is critiqued a second time (principle 7).

## BL-033

### P80. How exam grades become evidence and mastery
- **Evidence:** one row per graded answer. `session_id` is `exam:{exam id}:{attempt}`, `excerpt_ref` is `Q{n}: <the learner's answer>`, and `source_provider` is `local` for multiple choice or the grader's name. Strength: easy → weak, medium → moderate, hard → strong.
- **Skipped questions** write no evidence (principle 5: skipping isn't a demonstrated failure). The score reports them as skipped.
- **Mastery:** once every answered question on a concept is graded, its results propose a level. At least 75% correct proposes `max(current, the plan's target level)`, at most 25% proposes `current − 1`, and anything else proposes no change. The proposal then goes through the Analyzer's own rule (`apply_proposal`, now shared): exactly ±1 is applied with `set_mastery(changed_by="analyzer")`, citing that concept's exam evidence. ±2 or more queues a Challenger probe instead. A concept at level 0 answering its level-2 questions correctly therefore gets a challenge, not an instant level 2. Each concept is decided once per attempt.
- **Grader:** short-answer and coding answers go to one `critic` call (task `grade`) on the `[routing] analysis` order. It isn't kept off the providers that wrote the questions, because principle 6 separates teaching from evaluation, and writing questions isn't teaching. Answers it doesn't return, or all of them if it fails, stay ungraded until the next `grade` run.

### P81. Attempts and files
- `take` resumes an unfinished attempt. After a finished one, it starts attempt 2. `grade` refuses an unfinished attempt and grades the latest finished one. Answers are saved after each question by atomic rename.
- **Idempotent grading:** a question is graded once per attempt. That's checked in the exam file, and also against the evidence table (by `session_id` + `Q{n}:`), in case the file wasn't saved after an evidence row was written.
- **The `.md` file has the answer key and rubrics at the end**, after a rule, so the top half can be printed. Don't open it before taking the exam.
- Coding answers are typed line by line and end with a `/done` line. Multiple choice takes a letter or the option's text.
- **Spec files can live anywhere** (the ticket's example is `exams/cse220-midterm1.yaml`). No example spec is committed.

## BL-034

### P82. The podcast brief's rules
- **"The master spec's template" doesn't exist.** The spec only lists what the brief must say. My template has these sections: teaching preference, skip, dwell on, misconceptions to confront, exam framing, how to end.
- **Focus:** the five weakest concepts not on the skip list. With `--exam`, the candidates are the exam's coverage plan re-weighted as `weakness`, whatever mode the spec says, plus any in-scope concepts too light to get a question. Otherwise it's `weakest()` order over the whole course.
- **Skip:** level ≥ 4 and retention ≥ 0.7, from the same candidates.
- **Misconceptions:** misconception evidence plus the `## Misconceptions` bullets in the vault's concept notes, for the focus concepts only, at most three. The spec's `misconceptions/` folder still isn't built (P41).
- **Teaching preference:** `vault/learner/profile.md` (front matter and headings dropped, first 60 words). If the file is missing, a plain default is used. **(you)** Write that file if you want episodes shaped to you.
- **Word cap:** 400 words. The skip list, misconceptions, focus list and preference are trimmed in that order. As a last resort, whole lines past the cap are dropped.

### P83. Podcast CLI details
- `--exam` takes a spec YAML path, or the name of an exam already created (matched ignoring case and punctuation, so `midterm1` finds "Midterm 1"). The name is looked up in the newest matching exam JSON in the vault.
- `--format` defaults to `deep-dive`. `--length` defaults to NotebookLM's own default.
- The audio keeps the extension the provider downloads (`.m4a` from NotebookLM, P36). The `podcasts.concepts` column holds the focus concept ids.
- It doesn't check for an open tutor session, because generating audio doesn't touch NotebookLM chat.

## BL-035

### P84. `benchmarks` is a view over raw samples
The benchmarks row has one `sample_count`, but accuracy, groundedness and ratings arrive at different rates from format compliance. A single running mean would be wrong for them.
- **What I did:** migration v7 adds an append-only `benchmark_samples` table (one row per metric per measurement). `benchmarks` is a **view** with exactly `CLAUDE.md`'s columns, averaging each metric over its own samples. `sample_count` is the number of runs measured (format-compliance samples). Nothing is ever deleted (principle 3).
- **Who writes what:**
  - The router records `format_compliance` and `latency_ms` on every successful run. Tasks declare `output_format="json"` when their answer must be a JSON array.
  - The Analyzer's excerpt check records `groundedness` for `analyze_transcript`.
  - The exam Critic records per-question `groundedness` (a `grounding` flag) and `accuracy` (any other flag) for whoever wrote each question. Its schema gained an optional `kind` field for this.
  - `/rate 1-5` in the tutor records `learner_rating` for the last answer's provider and task type.
  - No other grader writes accuracy yet.
- **Composite score:** accuracy 0.4, groundedness 0.3, format compliance 0.3, over the metrics present, re-weighted to sum to 1. `learner_rating` and latency are stored but not scored. The ticket doesn't say how to use them.
- **"≥ 10 samples":** benchmark order applies only when **every** usable candidate has 10+ runs of that task. Otherwise it's config order, because a provider with 50 runs can't be compared fairly with one that has 3. Ties keep config order.

### P85. Health: when the router calls `health()`
`health()` on the CLI providers is a real one-token model call (P51), so the router doesn't call it on every route. It reads each provider's `state` attribute, which every run keeps up to date. It calls `health()` only when a provider has no `state`, or when a rate-limit cooldown has passed ("AVAILABLE on next successful health check").
- **Cooldowns** come from the hint's `resets_at` when it's readable (ISO, epoch seconds, or "in N minutes/hours"), else 60 minutes. They're stored in `provider_health` (migration v7), so a rate limit hit in one command still holds in the next. Claude's "resets 3pm" wording isn't parsed, so it gets the 60-minute default.
- **Other failures** (auth, crash, missing binary) drop the provider for the rest of that command only, and it is tried again in the next command. The state is still written to `provider_health` for the dashboard.
- **Fallback on any error:** v0 fell back only on rate limits (P59). v1 falls back on any `ModelError`, as the ticket's state rules imply. The ledger's `fallback_from` names the preferred provider when it failed or was skipped as unusable. `test_other_model_errors_do_not_fall_back` was replaced to match.

### P86. Routing by task type
`[routing]` keys may now be task types as well as purposes. A task type's own key wins, then its purpose (`TASK_PURPOSE`: teaching, analysis, housekeeping), then every configured provider. Each CLI command builds one router from `config.routing`; the separate teaching/analysis routers are gone. `question_gen` (Questioner and Challenger) and `tutor_estimate` count as teaching; `critique`, `grade` and `analyze_transcript` count as analysis. Unknown task types fall back to teaching. Providers can declare `task_types` to refuse others (BL-036 Ollama).

## BL-036

### P87. Ollama details
- **HTTP:** stdlib `urllib`, no new dependency. `POST /api/generate` with `stream: false`, and `num_predict` from `max_output_tokens`. Tests use a mocked Ollama server on 127.0.0.1, which is loopback only.
- **`health()`** is `GET /api/tags`, cached for 60 s. It's AVAILABLE only if the configured model is pulled. It's DISABLED when the server isn't running or the model is missing (the detail says `ollama pull …`), and BROKEN on other HTTP errors. The provider has no state until the first check, so the router's first look at it triggers a real (local, free) health check.
- **Model:** `BRIGHTLEARN_OLLAMA_MODEL`, default `llama3.2:3b`. URL: `BRIGHTLEARN_OLLAMA_URL`. Doctor shows Ollama as an optional yellow warning when it's not running. **(you)** `brew install ollama && ollama pull llama3.2:3b` if you want it; nothing requires it.

### P88. How the classifier uses it
- **"Ambiguous"** means no keyword rule matched, which used to mean `other`. Only then is `ModelClassifier` asked. A reply that isn't a bucket name is ignored.
- **Only Ollama, only when AVAILABLE.** The sync router holds Ollama alone. So an ambiguous title never spends Claude or Codex quota, even though the default `[routing] classify` order is `ollama, claude, codex` ("first, not last"). The order applies to anything else that runs `classify` through a full router; nothing does yet.
- **Housekeeping** (`extract_metadata`, `summarize`) defaults to `claude, codex, ollama`, following the master spec's "can fall all the way to Ollama". Nothing uses those task types yet.
