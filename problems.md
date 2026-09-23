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
