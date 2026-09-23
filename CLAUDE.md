# BrightLearn — CLAUDE.md

Personal learning platform: Brightspace course files → local course folder → NotebookLM (grounded intelligence) → Claude Code / Codex (reasoning) → SQLite + Markdown learner memory. V1 is a one-student prototype with zero metered LLM API spend. Tickets: `TICKETS-2.md`.

## Principles (every change must respect these)

1. **No dependency that charges per request.** Free official APIs and session-cookie endpoints (Brightspace) are fine. Claude, Codex, NotebookLM run on subscription quota.
2. **Every external dependency lives behind an interface in `core/providers/`.** Nothing outside that directory imports `playwright` or `notebooklm`, or makes subprocess calls to `claude` or `codex`.
3. **Don't delete anything; retrieve selectively.** Archive everything; send models a compiled package of a few thousand tokens.
4. **Mastery needs evidence.** No score without the `evidence` rows that justify it.
5. **Infer learning from normal interaction.** No forced quizzes.
6. **Teaching and evaluation run on different models.**
7. **Bounded deliberation.** One model, one task by default; cross-model rounds capped at two.
8. **Measure model strengths; never hardcode them.** Routing reads the `benchmarks` table.
9. **Course coverage and learner coverage are separate tables.**
10. **Our ledger (`model_runs`) is the source of truth for usage.**
11. **Subscriptions power the prototype, not a product.** `ModelProvider` exists so an API swap costs nothing later.

## Repo layout

```
brightlearn/
├── core/
│   ├── config.py
│   ├── providers/
│   │   ├── lms/          # base.py, session.py, brightspace.py
│   │   ├── storage/      # base.py, local.py
│   │   ├── knowledge/    # base.py, gemini_notebook.py (Phase 2)
│   │   └── models/       # base.py, claude_code.py, codex.py, ollama.py (Phase 5+)
│   ├── memory/           # schema.py, db.py, learner.py, vault.py
│   ├── sync/             # classify.py, engine.py, link.py
│   ├── context/          # Context Compiler (Phase 5)
│   ├── tutor.py          # tutoring session (BL-026)
│   ├── router/           # v0 fixed order (BL-026); benchmarks-driven in Phase 10
│   └── ledger/
├── personas/             # Markdown skill files, shared by Claude Code and Codex
├── cli/                  # app.py (typer root), sync.py, exam.py, tutor.py, dev.py
├── dashboard/
├── scripts/              # throwaway spikes
├── tests/                # fixtures/, fakes/
└── memory/               # the vault
```

Secrets live under `~/.brightlearn/` only: browser profile, `storage_state.json` (Brightspace), and notebooklm-py's `master_token.json` + `storage_state.json` under `~/.brightlearn/notebooklm/` (set `NOTEBOOKLM_HOME` there when running `notebooklm login`). All gitignored. Never write them into the repo, tests, or logs.

## Config

| Key | Default | Notes |
| --- | --- | --- |
| `home` | `~/.brightlearn` | Secrets directory, mode 700 |
| `brightspace_base_url` | `https://mycourses.stonybrook.edu` | |
| `term` | from the date | Overridable per run |
| `storage_root` | `~/.brightlearn/courses` | Canonical course files |
| `tmp_dir` | `/tmp/brightlearn` | Download staging; always emptied |
| `db_path` | `~/.brightlearn/brightlearn.db` | |
| `vault_dir` | `<repo>/memory` | Markdown vault; `BRIGHTLEARN_VAULT` overrides |

## Provider interfaces

```python
class LMSProvider(ABC):
    def ensure_session(self) -> None                 # headless if valid; headed login + Duo pause if not
    def list_courses(self) -> list[Course]
    def list_resources(self, org_unit_id: int) -> list[Resource]
    def download(self, resource: Resource, dest: Path) -> DownloadResult   # filename from Content-Disposition

class StorageBackend(ABC):
    def ensure_folder(self, path: str) -> Path                            # absolute path of storage_root/path
    def store(self, src: Path, rel_dir: str, name: str) -> StoreResult    # StoreResult(path, sha256, size); hash computed on write
    def exists(self, rel_path: str) -> bool
    def list(self, rel_dir: str) -> list[Path]

class KnowledgeProvider(ABC):
    def ensure_notebook(self, course: str) -> str
    def add_file(self, notebook_id: str, path: Path) -> str                # file upload; returns source_id
    def remove_source(self, source_id: str) -> None
    def list_sources(self, notebook_id: str) -> list[SourceMeta]
    def refresh_source(self, source_id: str) -> None
    def query(self, notebook_id: str, question: str, source_ids=None) -> GroundedAnswer
    def source_fulltext(self, source_id: str) -> str
    def generate_quiz(self, notebook_id: str, spec) -> dict
    def generate_audio(self, notebook_id: str, instructions_md: str, format: str, length: str) -> Path
    def generate(self, notebook_id: str, kind: str, options: dict) -> Path
    def health(self) -> ProviderState

class ModelProvider(ABC):
    def run(self, task: TaskPackage) -> ModelResult
    def health(self) -> ProviderState
    def usage_hint(self) -> UsageHint | None
```

Provider states: `AVAILABLE → LIMITED → RATE_LIMITED → AUTH_EXPIRED → BROKEN → DISABLED`.

Implementations (V1): `BrightspaceSessionProvider` (Playwright session + `/d2l/api` calls; DOM scraping only as fallback) · `LocalStorageBackend` · `GeminiNotebookProvider` (Android/gRPC transport primary, web fallback) · `ClaudeCodeProvider`, `CodexProvider`, `OllamaProvider` (housekeeping tasks only).

## Brightspace facts (verified Sept 23, 2026 on mycourses.stonybrook.edu)

- Session cookies authenticate `/d2l/api/...` calls directly. No OAuth app needed.
- `GET /d2l/api/lp/1.0/users/whoami` → 200 when logged in.
- `GET /d2l/api/versions/` → pick `ProductCode == "le"`, `LatestVersion` (currently `1.97`). Never hardcode the version.
- `GET /d2l/api/lp/1.0/enrollments/myenrollments/` → courses.
- `GET /d2l/api/le/{ver}/{orgUnitId}/content/toc` → nested `Modules[]` each with `Topics[]` (`TopicId`, `TypeIdentifier`, `Title`, `Url`, `LastModifiedDate`) and nested `Modules[]`.
- `GET /d2l/api/le/{ver}/{orgUnitId}/content/topics/{topicId}/file` → the file bytes (200 `application/pdf` confirmed).
- Topic titles are not filenames; use `Content-Disposition`. `Link` topics have a URL, not a file: record, don't download.
- Duo gates login only. Persistent browser profile + headed login pause when `whoami` fails.

## Data model (SQLite)

Versioned migrations in `core/memory/schema.py`, tracked in `PRAGMA user_version`.

```
resources:   course, org_unit_id, topic_id (PK), module_path, title, type_identifier, url,
             filename, size, last_modified, hash, local_path, bucket,
             notebook_id, notebook_source_id, source_hash,
             sync_state (pending|synced|stale|failed|link|deferred), last_seen
             -- hash: sha256 of the local file; source_hash: hash of the file currently in NotebookLM
model_runs:  run_id, provider, model, task_type, persona, started_at, duration_ms, success,
             input_tokens_est, output_tokens_est, fallback_from, error
concepts:    concept_id (PK), course, name, module, prerequisites, exam_tags            (Phase 4)
mastery:     concept_id, level 0-5, confidence, evidence_count, last_evidence_at,
             retention_confidence, last_reviewed                                         (Phase 4)
evidence:    evidence_id, concept_id, session_id, type, strength, source_provider,
             excerpt_ref, recorded_at   (append-only)                                    (Phase 4)
sessions:    session_id, course, started_at, ended_at, tutor_provider, analyzer_provider,
             summary_path                                                                (Phase 4)
benchmarks:  provider, task_type, accuracy, groundedness, format_compliance,
             latency_ms, learner_rating, sample_count                                    (Phase 10)
```

Storage tree: `storage_root/{term}/{course_code}/{bucket}/{filename}` with buckets `syllabus | lectures | assignments | labs | readings | exams | code | other`. A stored file is identified by `local_path` + `hash`.

## Conventions

- Python 3.12, `ruff`, `pytest`. Type hints everywhere. Dataclasses for models.
- Tests use fakes in `tests/fakes/` and JSON fixtures in `tests/fixtures/`; no network in tests.
- Temp downloads go to `config.tmp_dir/{uuid}` and are always deleted in a `finally`.
- Log with `logging`, never `print`, except in CLI output via `rich`.
- Commit message format: `BL-0XX: <ticket title>`.

## Not in V1

- Drive automation (can return via StorageBackend)
