# BrightLearn — Build Backlog 2

Supersedes the Drive-dependent parts of `TICKETS.md`. BL-001 through BL-006 and BL-008 are unchanged; everything else is here. Read `CLAUDE.md` first, then apply BL-000 before any other ticket.

## Hand-off prompt for Opus

```
You are working on BrightLearn. Read CLAUDE.md first, then TICKETS-2.md.
Work ONLY on ticket BL-0XX. Do not start the next ticket.
Rules:
- Nothing outside core/providers/ imports playwright, notebooklm, or subprocess calls to `claude`/`codex`.
- Tests use fakes in tests/fakes/ and fixtures in tests/fixtures/. No network in tests.
- Secrets live under ~/.brightlearn/ and never enter the repo, tests, or logs.
- When acceptance passes, commit as "BL-0XX: <title>" and stop.
- If the ticket conflicts with CLAUDE.md, CLAUDE.md wins; say so and stop.
```

Tickets marked **(you)** end with a manual step for Simon.

---

## Architecture change (why this file exists)

Google Drive automation is out. Consequences:

| Before | Now |
| --- | --- |
| Drive = canonical storage, files identified by `drive_file_id` | Local folder `storage_root/{term}/{course}/{bucket}/{filename}` = canonical storage, identified by `local_path` + `hash` |
| NotebookLM sources added by Drive file ID, auto-sync | NotebookLM sources added by file upload; the sync engine replaces a source when the file's hash changes |
| `StorageBackend` = `GoogleDriveBackend` | `StorageBackend` = `LocalStorageBackend` (same interface, so Drive can return later) |
| Zero persistent local storage | Files live locally (optionally inside a Drive for Desktop folder) |

### BL-000 Apply CLAUDE.md amendments
**Goal:** Keep the spec file truthful before any code changes.
**Build:** edit `CLAUDE.md`:
- Layout: `providers/storage/` → `base.py, local.py`; remove `gdrive.py`.
- Interfaces: `StorageBackend.ensure_folder(path) -> Path`, `store(src: Path, rel_dir: str, name: str) -> StoreResult(path, sha256, size)`, `exists(rel_path) -> bool`, `list(rel_dir) -> list[Path]`. Drop `verify` (hash is computed on write).
- `KnowledgeProvider`: replace `add_drive_source` with `add_file(notebook_id, path) -> source_id`, add `remove_source(source_id)`, add `list_sources(notebook_id) -> list[SourceMeta]`.
- `resources` table: replace `drive_file_id, drive_bucket` with `local_path, bucket`; keep `notebook_id, notebook_source_id`; add `source_hash` (hash of the file currently uploaded to NotebookLM).
- Config: replace Drive keys with `storage_root = "~/.brightlearn/courses"`.
- Principle 2: add `notebooklm` and subprocess calls to `claude`/`codex` to the import-ban list.
**Acceptance:** `CLAUDE.md` has no mention of Drive except one line under "Not in V1: Drive automation (can return via StorageBackend)".

---

## Phase 1 (revised) — Brightspace → local storage

### BL-007R Local storage backend
**Goal:** A `StorageBackend` that writes to disk and reports hashes.
**Build:** `core/providers/storage/base.py` (interface from BL-000) and `core/providers/storage/local.py`, `LocalStorageBackend(root)`:
- `ensure_folder(rel_dir)` creates `root/rel_dir`, returns absolute path.
- `store(src, rel_dir, name)` moves `src` into place (atomic rename when same filesystem, copy+delete otherwise), computes sha256, returns `StoreResult`. If `name` exists with a different hash, overwrite; if same hash, no-op.
- Filenames sanitized: strip path separators, collapse whitespace, keep extension.
**Acceptance:** tests: store, re-store identical (no-op), re-store changed (overwritten), bad filename sanitized, atomic move leaves no partial file on simulated failure.

### BL-009R Sync engine
**Goal:** Download only what changed; store locally; record it.
**Build:** `core/sync/engine.py`, `SyncEngine(lms, storage, db, config).sync_course(course, term, dry_run=False) -> SyncReport`. Per resource:
- `type_identifier != "File"` → upsert `sync_state="link"`, store `url`; continue.
- manifest row exists, `sync_state="synced"`, `last_modified` unchanged → skipped.
- else: download to `tmp_dir/{uuid}` → `bucket = classify(...)` → `storage.store(tmp, f"{term}/{course.code}/{bucket}", filename)` → upsert `local_path, bucket, hash, size, last_modified, sync_state="synced", last_seen`. If the old row's `hash` differs from the new one, set `sync_state="stale"` instead of `"synced"` so BL-015 knows the NotebookLM source needs replacing.
- `SessionExpired` → `lms.ensure_session()`, retry once. Other errors → `sync_state="failed"`, continue. `tmp` deleted in `finally`.
**Acceptance:** with fakes: first run N new; second run 0 new / N skipped; one changed `last_modified` + changed bytes → 1 row `stale`; changed `last_modified` but identical bytes → row stays `synced`; `SessionExpired` once → retried; tmp empty after every run; `dry_run` touches nothing.

### BL-010R Sync CLI
**Build:** `brightlearn sync --course CSE220 | --all`, `--term` (auto from date), `--dry-run`, `--force`. Rich summary: new / changed / skipped / links / failed per course, failures listed.
**Acceptance:** **(you)** CSE220 lands under `~/.brightlearn/courses/Fall-2026/CSE220/{bucket}/`; second run all skipped.

### BL-011R Doctor
**Build:** `brightlearn doctor` checks: config, DB schema version, Brightspace `whoami`, `storage_root` writable, tmp dir empty, `ANTHROPIC_API_KEY` unset, Playwright Chromium installed, `notebooklm` importable and `notebooklm auth status` OK (from BL-014 onward), `claude --version` and `codex --version` on PATH (from BL-022 onward).
**Acceptance:** all green after BL-010R except the not-yet-built checks, which print "not configured" in grey.

---

## Phase 2 — NotebookLM provider

### BL-012R KnowledgeProvider interface
**Build:** `core/providers/knowledge/base.py` with the interface from BL-000 plus dataclasses `SourceMeta(source_id, title, kind, added_at)`, `GroundedAnswer(text, citations: list[Citation])`, `Citation(source_id, excerpt)`, `ProviderState` enum. `tests/fakes/fake_knowledge.py` storing sources in memory and answering queries with canned text.
**Acceptance:** imports; fake smoke test.

### BL-013R notebooklm-py spike script
**Goal:** Learn the real library behavior before writing the provider. Throwaway.
**Build:** `scripts/spike_c.py`, Android backend:
1. create notebook `BrightLearn-spike`
2. `add_file` the local syllabus PDF from the manifest
3. list sources, print IDs
4. ask "What is the grading breakdown?" and print answer + citations
5. write `spike_prompt.md` ("Cover only grading policy and exam dates") → generate Audio Overview `--format brief --length short` → download MP3 to tmp
6. remove the source, re-add the same file, confirm a new source_id
7. print timing per step and every exception
Setup **(you)**: `pip install "notebooklm-py[android,browser]"`; `notebooklm login --master-token --account <gmail>`.
**Acceptance:** output pasted into `docs/spike_c_results.md`, including exact method names/signatures used and any quirks (rate limits, delays before a new source is queryable, artifact polling time).

### BL-014 GeminiNotebookProvider
**Goal:** Real `KnowledgeProvider` over notebooklm-py.
**Build:** `core/providers/knowledge/gemini_notebook.py`:
- Transport selection: `AndroidTransport` then `WebTransport`; a failed call on Android retries once on Web and marks state `LIMITED`; both failing → `BROKEN`.
- `ensure_notebook(course)`: find by title `BrightLearn/{course}`, else create; cache ID in a `notebooks` table (`course, notebook_id, created_at`).
- `add_file`, `remove_source`, `list_sources`, `query` (map citations), `source_fulltext`, `generate_quiz` (return parsed JSON), `generate_audio(instructions_md, format, length)` (poll until ready, download, return path), `generate(kind, options)` for slides/report/flashcards/mind map.
- Every call wrapped with timing and appended to `model_runs` with `provider="notebooklm"`, `task_type` = method name.
- Politeness: minimum 1.5 s between calls; configurable.
**Acceptance:** unit tests with a mocked client covering transport fallback and state transitions; **(you)** manual: `brightlearn dev nlm-test` runs create → add → query → remove against the spike notebook.

### BL-015 Sync → NotebookLM linking
**Goal:** Every synced file is a NotebookLM source; changed files replace their source.
**Build:** `core/sync/link.py`, `LinkStep(knowledge, db).run(course)`:
- rows with `sync_state="synced"` and `notebook_source_id IS NULL` → `add_file`, store `notebook_source_id`, `source_hash = hash`.
- rows with `sync_state="stale"` → `remove_source(old)`, `add_file(new)`, update IDs, `source_hash`, set `sync_state="synced"`.
- rows with `sync_state="link"` → skip (Zoom URLs handled later).
- Skip buckets `code` and `other` unless `--include-code`. Respect NotebookLM's per-notebook source cap (read from config, default 50): if exceeded, prioritize `syllabus, exams, lectures, readings, labs, assignments` in that order and mark the rest `sync_state="deferred"`.
- Wire into `brightlearn sync` as a final step, `--no-link` to skip.
**Acceptance:** with fakes: N synced rows → N add_file calls; 1 stale → remove + add; cap of 3 → correct 3 chosen by priority, rest deferred; second run → 0 calls.

### BL-016 Ask CLI
**Build:** `brightlearn ask --course CSE220 "How are pointers introduced in lecture 3?"` → `knowledge.query`, prints answer and citations with source titles from the manifest. `--sources syllabus,lectures` filters by bucket.
**Acceptance:** **(you)** a real question about CSE220 returns a grounded answer with citations.

### BL-017 Generate CLI
**Build:** `brightlearn generate quiz|audio|flashcards|report --course CSE220 [--prompt-file x.md] [--format ...] [--length ...] [--out path]`. Writes artifact to `storage_root/{term}/{course}/_generated/{timestamp}-{kind}.{ext}`; quiz/flashcards also saved as JSON.
**Acceptance:** **(you)** one quiz JSON and one short MP3 land in `_generated/`.

---

## Phase 4 — Learner memory

### BL-018 Learner tables
**Build:** migration v2 adding `concepts`, `mastery`, `evidence`, `sessions(session_id, course, started_at, ended_at, tutor_provider, analyzer_provider, summary_path)` exactly as in CLAUDE.md. `core/memory/learner.py` with typed accessors: `upsert_concept`, `get_mastery`, `add_evidence(...) -> evidence_id`, `set_mastery(concept_id, level, confidence, evidence_ids)` (refuses if `evidence_ids` is empty — principle 4), `weakest(course, n, exam_tag=None)`, `decay_retention(now)`.
**Acceptance:** tests: set_mastery without evidence raises; weakest returns correct order; decay lowers `retention_confidence` for stale rows and leaves fresh ones.

### BL-019 Markdown vault I/O
**Build:** `core/memory/vault.py`: `write_concept_note(concept, mastery, misconceptions, evidence)` → `memory/concepts/{slug}.md` with YAML front matter mirroring the SQLite row; `write_session_summary(session)`; `read_front_matter(path)`; `vault_check()` reports notes whose front matter disagrees with SQLite.
**Acceptance:** round-trip test: write note → read front matter → equals the row; `vault_check` flags a hand-edited mismatch.

### BL-020 Concept seeding from the syllabus
**Goal:** Populate `concepts` for a course without hand-typing.
**Build:** `brightlearn concepts seed --course CSE220`: query NotebookLM with a fixed prompt asking for a JSON list of `{name, module, week, prerequisites, exam_tags}` derived from the syllabus and lecture titles; write to `memory/courses/CSE220/concepts.draft.yaml`; print it; `brightlearn concepts apply` loads the (hand-reviewed) YAML into `concepts`. Never applies without the review step.
**Acceptance:** with fake knowledge returning canned JSON: draft written, apply inserts rows, re-apply is idempotent.

---

## Phase 5 — Models and personas

### BL-021 ModelProvider interface + ledger
**Build:** `core/providers/models/base.py`: `TaskPackage(task_type, persona: str|None, system: str, user: str, max_output_tokens: int, metadata: dict)`, `ModelResult(text, provider, model, duration_ms, usage_hint)`, `ModelProvider(run, health, usage_hint)`. `core/ledger/ledger.py`: `record(run)` → `model_runs`; `today_summary()`.
**Acceptance:** fake provider + ledger test: one run → one row with correct fields.

### BL-022 ClaudeCodeProvider
**Build:** `core/providers/models/claude_code.py`: shells out to the `claude` CLI non-interactively (verify current flags with `claude --help`; expected `claude -p "<prompt>" --output-format json`), with `ANTHROPIC_API_KEY` **removed** from the subprocess env, cwd = a scratch dir, timeout from config. Parses text and any usage/limit info from output into `UsageHint`. Detects rate-limit / usage-exhausted messages → `RATE_LIMITED`. `health()` = a one-token call cached for 10 min.
**Acceptance:** tests with a fake `claude` script on PATH covering success, rate-limit message, timeout. **(you)** `brightlearn dev model-test claude "Say hi"` works.

### BL-023 CodexProvider
**Build:** `core/providers/models/codex.py`: same shape via `codex exec "<prompt>"` (verify flags with `codex --help`); parse `/status`-style allowance if exposed. Model name read from output, never hardcoded.
**Acceptance:** same test matrix with a fake `codex`. **(you)** `brightlearn dev model-test codex "Say hi"` works.

### BL-024 Persona files
**Build:** `personas/simplifier.md`, `analogist.md`, `exemplar.md`, `challenger.md`, `analyzer.md`, `critic.md`, `questioner.md`, each with the front matter shape from the master spec (`name, group, task_types, min_anchor_level`) and sections Goal / Process / Rules / Output shape / Known failure modes, content per the spec's Personas table. `core/personas.py`: `load(name)`, `list()`, `render(persona, context) -> system prompt string`.
**Acceptance:** all seven parse; `render` includes every Rules bullet; Analogist refuses to render when no anchor concept ≥ level 3 is supplied.

### BL-025 Context Compiler v0
**Build:** `core/context/compiler.py`, `compile(question, course, persona, session) -> TaskPackage`:
1. intent: keyword match against concept names (v0; a model can replace this later)
2. `knowledge.query(question)` → grounded answer + citations (source context, capped at 1,200 tokens)
3. learner rows for matched concepts + their misconception notes (capped at 600 tokens)
4. persona rendered as system prompt
5. last 6 session turns (capped at 800 tokens)
Emits `TaskPackage` with a `context_report` (tokens per section) stored in `metadata`.
**Acceptance:** with fakes: package under 3,500 tokens for a 20-turn session; sections respect caps; unmatched question still produces a valid package with empty learner context.

### BL-026 Tutor CLI
**Build:** `brightlearn tutor --course CSE220 --persona simplifier`: REPL; each turn → compile → router (v0: Claude for teaching, Codex if Claude `RATE_LIMITED`) → print; transcript appended to `memory/sessions/{id}.md`; `/persona analogist` switches mid-session; `/end` closes the session and triggers BL-027.
**Acceptance:** **(you)** a 5-turn session on pointers stays grounded in CSE220 sources and writes a session file.

### BL-027 Analyzer v0
**Build:** `core/analysis/analyzer.py`: on session end, run the `analyzer` persona on a **different** provider than the tutor with the transcript and current mastery rows; expect JSON `[{concept, evidence_type, strength, excerpt, proposed_level}]`; write `evidence` rows; apply `set_mastery` only when `proposed_level` differs by exactly 1 from current (bigger jumps are logged as `needs_challenge` for the Challenger later).
**Acceptance:** fake analyzer output → evidence rows written; +1 applied; +3 logged not applied; provider chosen ≠ tutor provider.

---

## Not yet ticketed
Phase 6+: Challenger loop on disagreement · ExamSpec + Coverage Planner + exam CLI · adaptive podcast prompt compiler · Zoom `Link` topics (local transcription or ignore) · router with benchmarks table · HTML dashboard · Ollama housekeeping provider.
