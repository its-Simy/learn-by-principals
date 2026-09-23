# BrightLearn — CLAUDE.md

Personal learning platform: Brightspace course files → Google Drive → NotebookLM (grounded intelligence) → Claude Code / Codex (reasoning) → SQLite + Markdown learner memory. V1 is a one-student prototype with zero metered LLM API spend. Current work: Phase 0–1 (sync). See `TICKETS.md`.

## Principles (every change must respect these)

1. **No dependency that charges per request.** Free official APIs (Drive) and session-cookie endpoints (Brightspace) are fine. Claude, Codex, NotebookLM run on subscription quota.
2. **Every external dependency lives behind an interface in `core/providers/`.** Nothing outside that directory imports `playwright`, `googleapiclient`, `google_auth_oauthlib`, or `notebooklm`.
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
│   │   ├── storage/      # base.py, gdrive.py
│   │   ├── knowledge/    # base.py, gemini_notebook.py (Phase 2)
│   │   └── models/       # base.py, claude_code.py, codex.py, ollama.py (Phase 5+)
│   ├── memory/           # schema.py, db.py, vault.py
│   ├── sync/             # classify.py, engine.py
│   ├── context/          # Context Compiler (Phase 5)
│   ├── router/           # routing, health, fallback, benchmarks (Phase 10)
│   └── ledger/
├── personas/             # Markdown skill files, shared by Claude Code and Codex
├── cli/                  # app.py (typer root), sync.py, exam.py, tutor.py, dev.py
├── dashboard/
├── scripts/              # throwaway spikes
├── tests/                # fixtures/, fakes/
└── memory/               # the vault
```

Secrets live under `~/.brightlearn/` only: browser profile, Drive OAuth token + client secret, `storage_state.json`, `master_token.json`. All gitignored. Never write them into the repo, tests, or logs.

## Provider interfaces

```python
class LMSProvider(ABC):
    def ensure_session(self) -> None                 # headless if valid; headed login + Duo pause if not
    def list_courses(self) -> list[Course]
    def list_resources(self, org_unit_id: int) -> list[Resource]
    def download(self, resource: Resource, dest: Path) -> DownloadResult   # filename from Content-Disposition

class StorageBackend(ABC):
    def ensure_folder(self, path: str) -> str
    def upload(self, local: Path, folder_id: str, name: str) -> UploadResult
    def verify(self, file_id: str, expected_md5: str) -> bool
    def list(self, folder_id: str) -> list[FileMeta]

class KnowledgeProvider(ABC):
    def ensure_notebook(self, course: str) -> str
    def add_drive_source(self, notebook_id: str, drive_file_id: str) -> str   # NO local-path variant
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

Implementations (V1): `BrightspaceSessionProvider` (Playwright session + `/d2l/api` calls; DOM scraping only as fallback) · `GoogleDriveBackend` · `GeminiNotebookProvider` (Android/gRPC transport primary, web fallback) · `ClaudeCodeProvider`, `CodexProvider`, `OllamaProvider` (housekeeping tasks only).

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

```
resources:   course, org_unit_id, topic_id (PK), module_path, title, type_identifier,
             filename, size, last_modified, hash, drive_file_id, drive_bucket,
             notebook_id, notebook_source_id, sync_state (pending|synced|stale|failed|link), last_seen
model_runs:  run_id, provider, model, task_type, persona, started_at, duration_ms, success,
             input_tokens_est, output_tokens_est, fallback_from, error
concepts:    concept_id (PK), course, name, module, prerequisites, exam_tags            (Phase 4)
mastery:     concept_id, level 0-5, confidence, evidence_count, last_evidence_at,
             retention_confidence, last_reviewed                                         (Phase 4)
evidence:    evidence_id, concept_id, session_id, type, strength, source_provider,
             excerpt_ref, recorded_at   (append-only)                                    (Phase 4)
benchmarks:  provider, task_type, accuracy, groundedness, format_compliance,
             latency_ms, learner_rating, sample_count                                    (Phase 10)
```

Drive tree: `BrightLearn/{term}/{course_code}/{bucket}/` with buckets `syllabus | lectures | assignments | labs | readings | exams | code | other`.

## Conventions

- Python 3.12, `ruff`, `pytest`. Type hints everywhere. Dataclasses for models.
- Tests use fakes in `tests/fakes/` and JSON fixtures in `tests/fixtures/`; no network in tests.
- Temp downloads go to `config.tmp_dir/{uuid}` and are always deleted in a `finally`.
- Log with `logging`, never `print`, except in CLI output via `rich`.
- Commit message format: `BL-0XX: <ticket title>`.