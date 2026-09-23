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
