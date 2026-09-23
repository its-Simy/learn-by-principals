# Open questions — Phase 0–1 build

Each item says what I did, if anything, and what I recommend. Recommendations come from `BrightLearn — Master Spec.md` unless noted. Items 1–4 need you before anything else can move.

## Blocking / needs you

### 1. There is no ticket list
`backlog.md` is titled "BrightLearn — CLAUDE.md". It says "Current work: Phase 0–1 (sync). See `TICKETS.md`", but `TICKETS.md` doesn't exist, so there are no BL-0XX tickets to follow.
- **What I did:** built Phase 1 (sync) as `backlog.md` and the spec describe it: layout, interfaces, data model and conventions. How I'd have split that work into tickets:
  1. Project scaffold (pyproject, ruff, pytest, .gitignore)
  2. `core/config.py`
  3. `LMSProvider` + `BrightspaceSessionProvider` + Playwright session
  4. `StorageBackend` + `GoogleDriveBackend`
  5. SQLite schema (`resources`, `model_runs`) + manifest
  6. Bucket classifier
  7. Sync engine
  8. CLI: `brightlearn sync`, `brightlearn doctor`, `brightlearn dev courses`
- **Recommendation:** add `TICKETS.md`, or paste the tickets into `backlog.md`, and I'll check this work against them. Also consider renaming `backlog.md` to `CLAUDE.md`, since its content is agent instructions, not a backlog.

### 2. Nothing is committed
The commit format is `BL-0XX: <ticket title>`, but there are no ticket numbers, and you didn't ask for commits. Everything is uncommitted on `main`.
- **Recommendation:** once the tickets exist, give me the numbers and I'll commit per ticket on a branch.

### 3. Phase 0 setup only you can do
- ~~OAuth desktop client~~ Done. The JSON was moved from the repo folder to `~/.brightlearn/client_secret.json` (mode 600). It was never committed.
- ~~Install Chromium~~ Done.
- Install and log in to the `claude` and `codex` CLIs. Neither is on PATH on this machine.
- `ANTHROPIC_API_KEY` is unset. Good.
- Then run `brightlearn sync --course CSE220` twice. Phase 1 is done when files land in the bucket tree, the second run uploads 0, and `/tmp/brightlearn` is empty.

### 4. Spikes B and C: not started
Both need your Google account. Spike C also needs `notebooklm-py`, whose API I haven't verified, so I didn't guess at it.
- **Recommendation (spec):** run both as throwaway scripts in `scripts/` before Phase 2.
  - Spike B: import one PDF from Drive, replace its content in place (same file ID; `GoogleDriveBackend.upload` already does this), then query NotebookLM a few minutes later.
  - Spike C: create a notebook, add a Drive source, run a query and generate audio with `--prompt-file`, all on the Android backend.
  - Use the dedicated Google account from the risk table.

## Choices I made that you should confirm

### 5. Repo root is the `brightlearn/` in the layout
`core/`, `cli/`, `tests/` sit at the repo root, and the Python packages are `core` and `cli`. The alternative is a `brightlearn/` subfolder inside the repo.

### 6. Term folder name
`BrightLearn/{term}/...` needs a term, and nothing says where it comes from or how to format it.
- **What I did:** defaulted to a date-based label (`2026-Fall`). You can override it with `--term` or `BRIGHTLEARN_TERM`.
- **Recommendation:** read the term from Brightspace (the course's parent semester org unit) once we've seen a real response. The format is your call.

### 7. Course code for the Drive folder
- **What I did:** a regex pulls `CSE220` out of the org unit's `Code` or `Name`. If nothing matches, it falls back to the raw `Code`.
- **Recommendation:** run `brightlearn dev courses` and check the codes it shows. I haven't seen SBU's real `Code` format.

### 8. Which enrollments are synced
- **What I did:** only Course Offerings (type 3) where `IsActive` and `CanAccess` are both true.
- **Why:** past courses would be filed under the *current* term label. Archiving earlier semesters has to wait for item 6.

### 9. Enrollment and TOC fixtures aren't real responses
- **What I did:** built `tests/fixtures/*.json` from D2L's public Valence docs and the Spike A notes, not from captured SBU responses.
- **Recommendation:** capture one real response of each kind, strip personal data, and replace the fixtures.

### 10. Bucket classification rules
- **What I did:** `core/sync/classify.py` uses ordered keyword rules: syllabus → exams → labs → assignments → code (by file extension) → lectures → readings → other. For example, `Final Project` goes to assignments and lecture demo `.c` files go to code.
- **Recommendation:** review the buckets after the first real sync. Later, the router's `classify` task (Ollama) can replace these rules, as the spec intends.

### 11. How a changed file reaches Drive
- **What I did:** the file is updated **in place**: same Drive file ID, new revision, with `keepRevisionForever=true`. Drive would otherwise purge replaced revisions after 30 days, which breaks principle 3.
- If two topics in the same course bucket have the same filename, the second one gets ` [topic_id]` before its extension. The `filename` column stores the name as it appears in Drive.
- **Why:** the NotebookLM Drive-backed source only auto-syncs if the file ID stays the same (Spike B, Phase 2).
- **Open:** if a topic's filename changes, a new Drive file is created and the old one is kept. Is that OK?

### 12. Topic types other than `File` or `Link`
- **What I did:** stored as metadata only, with `sync_state = 'link'`.
- **Recommendation:** check which `TypeIdentifier` values SBU courses actually use. They may need their own state.

### 13. Topics removed from Brightspace
- **What I did:** the manifest row and the Drive file are both kept. `last_seen` stops advancing.
- **Question:** do you want an explicit state for removed topics? There's no such value in `sync_state` today.

### 14. Drive OAuth scope and account
- **What I did:** used the `drive.file` scope, which only sees files the app created.
- **Question (Phase 2):** is the Drive account the same as the dedicated NotebookLM account? If not, the files need sharing.

### 15. Where the database and secret files live
None of these paths were specified:
- SQLite: `~/.brightlearn/brightlearn.db` (override with `BRIGHTLEARN_DB`). The alternative is a gitignored file under `memory/`.
- Secrets: `~/.brightlearn/client_secret.json`, `drive_token.json`, `storage_state.json`, `browser-profile/`. The token and state files are written with mode 600.

### 16. Brightspace session handling (untested live)
- **Assumption:** D2L session cookies don't survive a browser restart. So after login, the storage state is saved and its cookies are re-applied to each new headless context.
- **Mid-run expiry:** a request that lands on the login page, or on 401/403 with a failed `whoami`, opens one headed login and retries once. A 403 while `whoami` still works raises an error instead.
- **Recommendation:** watch the first real run. This is the most likely place to need adjustment.

### 17. Large downloads are held in memory
Playwright's `APIResponse.body()` loads the whole file into memory before it's written to the temp file. That's fine for PDFs and slides. If big video `File` topics show up, switch to streaming.

### 18. Health checks aren't in the interfaces
`backlog.md`'s `LMSProvider` and `StorageBackend` have no `health()`, but `doctor` needs one.
- **What I did:** added `health()` to the implementations only, and put `ProviderState` in `core/providers/state.py`, a file the layout doesn't list.
- **Recommendation:** add `health()` to both abstract classes.
- **Also:** the spec mentions a `DEGRADED` state for NotebookLM that isn't in the state list. That's a Phase 2 question.

### 19. `doctor` can't meet the Phase 0 "all AVAILABLE" bar yet
NotebookLM (Phase 2) and the model providers (Phase 5+) don't exist yet.
- **What I did:** `doctor` shows them as `DISABLED` and exits non-zero only for Brightspace, Drive or a set `ANTHROPIC_API_KEY`. Claude and Codex are only checked for being on PATH.
- **Question:** how should `doctor` confirm Claude and Codex are logged in without using quota?

### 20. Where the spec and `backlog.md` disagree (I followed `backlog.md`)
- `upload(local, folder_id, name) -> UploadResult`, not `upload(local_path, folder_id, resumable=True) -> file_id`. Uploads are still resumable.
- `sync_state` includes `link`.
- The `model_runs` table is created now: `backlog.md` doesn't tag it with a later phase, but the spec puts it in Phase 4.
- `BrightspaceScrapeProvider` (the spec's fallback) isn't in `backlog.md`'s layout, so it isn't built. A course whose TOC request fails is recorded as an error, and the other courses carry on.

### 21. Scope of the principle 2 test
`tests/test_principles.py` fails if `core/` or `cli/` imports Playwright, the Google libraries or notebooklm outside `core/providers/`. `tests/test_gdrive.py` imports googleapiclient's offline HTTP mock to test the Drive backend without network access.
- **Question:** is that OK, or should tests be held to principle 2 too?

### 22. CLI file placement
`doctor` is in `cli/app.py`, and `cli/dev.py` holds `dev courses`. `exam.py` and `tutor.py` aren't created yet (later phases).

## Added during setup

### 23. NetID password: stored, then removed (back to the spec)
For a while the password was saved in `~/.brightlearn/brightspace_login.json` and filled in automatically. At your request, sign-in is now manual again, as the spec's decision log intended. The autofill code and the file are both gone. `.gitignore` still blocks `brightspace_login*.json` and `credentials*.json` as a precaution.
- **Still to do: change your NetID password.** It was typed into the Claude chat, so it's in that transcript.

### 24. `brightlearn` script breaks on this Mac
macOS keeps setting the `hidden` flag on `.venv/.../site-packages/*.pth`, and Python 3.12 skips hidden `.pth` files. When that happens, `.venv/bin/brightlearn` fails with `No module named 'cli'`.
- **Workaround:** run `.venv/bin/python -m cli.app <command>` from the repo root, or run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth` before using the script.
- **Recommendation:** move the venv out of `~/Desktop` (try `UV_PROJECT_ENVIRONMENT=~/.venvs/brightlearn`), since Desktop's iCloud/provenance handling is the likely cause.

## Found on the first real login (Sept 23, 2026)

### 25. `IsActive` doesn't mean "this term": past courses would land in the wrong folder
`myenrollments` returned 13 active Course Offerings, spanning Summer 2025 through Fall 2026. Since the term label comes from config (item 6), a plain `brightlearn sync` would file CHE487 (Summer 2025) under `2026-Fall/`.
- **Until this is fixed:** always sync with `--course`.
- **Recommendation:** SBU names end in the term (`-CSE 220.01 Systems Fundamentals I - Fall 2026`). Parse `{Season} {Year}` from the name, use it as the Drive term folder (`2026-Fall`), and drop the date-based default. That would also let past semesters be archived correctly (item 8).

### 26. Some Course Offerings aren't courses
`ceasmajmin` (CEAS Majors), `cse-ise-maj` (CSE + ISE Majors), `1258-ReportIt-Student-07` (training) and `SBU100` (orientation) are all type 3.
- **Recommendation:** by default, sync only offerings whose name matches `DEPT NNN.SECTION … - Season Year`. Allow others through `--course`.

### 27. Two offerings share a course code
PHY133 appears as `.L24` (section 2066520) and `.L00 (L01-L24)` (parent, 2088968). Both map to `…/PHY133/`, so their files would share folders. The ` [topic_id]` suffix prevents overwrites, but the folders mix.
- **Question:** is that acceptable, or should the section be part of the folder name (`PHY133.L24`)?

Codes derived correctly for real courses: CSE220 is org unit 2748835, matching Spike A.
