# BrightLearn — CLAUDE.md

Personal learning platform: course files uploaded by hand → local course folder → NotebookLM (grounded intelligence) → Claude Code / Codex (reasoning) → SQLite + Markdown learner memory. V1 is a one-student prototype with zero metered LLM API spend. Tickets: `TICKETS-4.md`.

## Principles (every change must respect these)

1. **No dependency that charges per request.** Free official APIs are fine. Claude, Codex, NotebookLM run on subscription quota.
2. **Every external dependency lives behind an interface in `core/providers/`.** Nothing outside that directory imports `notebooklm`, or makes subprocess calls to `claude` or `codex`.
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
│   │   ├── storage/      # base.py, local.py
│   │   ├── knowledge/    # base.py, gemini_notebook.py (Phase 2)
│   │   └── models/       # base.py, claude_code.py, codex.py, ollama.py (Phase 5+)
│   ├── memory/           # schema.py, db.py, learner.py, vault.py, migrations/vNNN_*.py
│   ├── sync/             # classify.py, importer.py, link.py
│   ├── context/          # Context Compiler (Phase 5)
│   ├── tutor.py          # tutoring session (BL-026)
│   ├── analysis/         # Analyzer (BL-027), Challenger loop (BL-030)
│   ├── exams/            # spec, coverage, generate, paper, take, grade (BL-031–033)
│   ├── podcast/          # compiler.py (learner state -> Audio Overview brief), episodes.py
│   ├── personas.py       # load / list / render persona files
│   ├── router/           # router.py (v1: config order, health, benchmarks), benchmarks.py, health.py
│   ├── maintenance.py    # retention decay + session archive, auto-run daily (BL-038)
│   └── ledger/
├── personas/             # Markdown skill files, shared by Claude Code and Codex
├── cli/                  # app.py (typer root), sync.py, courses.py, exam.py, tutor.py, sessions.py, dev.py
├── dashboard/            # data.py (queries), render.py (self-contained HTML, inline SVG)
├── scripts/              # throwaway spikes
└── tests/                # fakes/
```

Nothing personal lives in the repo. The vault (transcripts, concept notes, drafts) is at `~/.brightlearn/vault/`; `personas/` stays in the repo because it is code.

Secrets live under `~/.brightlearn/` only: notebooklm-py's `master_token.json` + `storage_state.json` under `~/.brightlearn/notebooklm/` (set `NOTEBOOKLM_HOME` there when running `notebooklm login`). All gitignored. Never write them into the repo, tests, or logs.

## Config

| Key | Default | Notes |
| --- | --- | --- |
| `home` | `~/.brightlearn` | Secrets directory, mode 700 |
| `term` | from the date | Default term for new courses; `courses add --term` overrides |
| `storage_root` | `~/.brightlearn/courses` | Canonical course files |
| `tmp_dir` | `/tmp/brightlearn` | Upload staging; always emptied |
| `db_path` | `~/.brightlearn/brightlearn.db` | |
| `vault_root` | `~/.brightlearn/vault` | Markdown vault; `BRIGHTLEARN_VAULT` overrides |
| `retention_half_life_days` | `21` | `BRIGHTLEARN_RETENTION_HALF_LIFE_DAYS` |
| `ollama_url` / `ollama_model` | `http://localhost:11434` / `llama3.2:3b` | `BRIGHTLEARN_OLLAMA_URL`, `BRIGHTLEARN_OLLAMA_MODEL` |
| `routing` | teaching `claude, codex`; analysis `codex, claude`; housekeeping `claude, codex, ollama`; classify `ollama, claude, codex` | `[routing]` in `~/.brightlearn/config.toml`; keys are purposes or task types (a task type's own key wins) |

Everything else is set with `BRIGHTLEARN_*` environment variables; `~/.brightlearn/config.toml` holds only `[routing]` so far.

## Provider interfaces

```python
class StorageBackend(ABC):
    def ensure_folder(self, path: str) -> Path                            # absolute path of storage_root/path
    def store(self, src: Path, rel_dir: str, name: str) -> StoreResult    # StoreResult(path, sha256, size); hash computed on write;
                                                                          # a replaced file is kept as rel_dir/_versions/{name}.{old_hash[:8]}
    def exists(self, rel_path: str) -> bool
    def list(self, rel_dir: str) -> list[Path]

class KnowledgeProvider(ABC):
    def ensure_notebook(self, course: str) -> str
    def add_file(self, notebook_id: str, path: Path) -> str                # file upload; returns source_id
    def remove_source(self, source_id: str) -> None
    def list_sources(self, notebook_id: str) -> list[SourceMeta]
    def refresh_source(self, source_id: str) -> None
    def query(self, notebook_id: str, question: str, source_ids=None, conversation=None) -> GroundedAnswer
                                                  # conversation=None: fresh NotebookLM conversation; a Conversation handle: one per tutor session
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

Implementations (V1): `LocalStorageBackend` · `GeminiNotebookProvider` (Android/gRPC transport primary, web fallback) · `ClaudeCodeProvider`, `CodexProvider`, `OllamaProvider` (housekeeping tasks only).

## Data model (SQLite)

Migrations live one per file in `core/memory/migrations/vNNN_<name>.py`, applied in order and tracked in `PRAGMA user_version` (rules under Conventions).

```
courses:     course (PK: the code in folder and notebook names), name, term, created_at  (BL-042)
resources:   resource_id (PK), course, title, filename, bucket, local_path, hash, size, url,
             notebook_id, notebook_source_id, source_hash,
             sync_state (synced|stale|failed|link|deferred), added_at                    (BL-042)
             -- hash: sha256 of the local file; source_hash: hash of the file currently in NotebookLM
             -- rows from before v13 keep their files and links, with ids `topic:{n}`
model_runs:  run_id, provider, model, task_type, persona, started_at, duration_ms, success,
             input_tokens_est, output_tokens_est, fallback_from, error
concepts:    concept_id (PK), course, name, module, prerequisites, exam_tags, week,
             status (active|retired)   -- retired, never deleted                        (Phase 4)
mastery:     concept_id, level 0-5, confidence, evidence_count, last_evidence_at,
             retention_confidence, last_reviewed                                         (Phase 4)
evidence:    evidence_id, concept_id, session_id, type, strength, source_provider,
             excerpt_ref, recorded_at   (append-only)                                    (Phase 4)
sessions:    session_id, course, started_at, ended_at, tutor_provider, analyzer_provider,
             summary_path, last_turn_at                                                  (Phase 4)
mastery_history: id, concept_id, old_level, new_level, confidence, evidence_ids (JSON),
             changed_at, changed_by (analyzer|manual|challenger)
             (append-only; one row per set_mastery)
challenges:  id, concept_id, session_id, reason, question,
             status (pending|asked|answered|resolved), created_at,
             proposed_level (the Analyzer's jump; NULL if raised by a tutor estimate),
             evidence_ids (JSON: the evidence behind that proposal)
             -- at most one unresolved challenge per concept                             (BL-030)
podcasts:    id, course, concepts (JSON concept ids), instruction_path, audio_path,
             created_at                                                                  (BL-034)
benchmarks:  provider, task_type, accuracy, groundedness, format_compliance,
             latency_ms, learner_rating, sample_count                                    (BL-035)
             -- a VIEW averaging benchmark_samples (provider, task_type, metric, value,
             -- recorded_at; append-only); sample_count = runs measured
provider_health: provider (PK), state, checked_at, cooldown_until, detail               (BL-035)
maintenance_runs: id, ran_at, trigger (manual|auto), decayed, archived, closed          (BL-038)
```

Storage tree: `storage_root/{term}/{course_code}/{bucket}/{filename}`, the term from the course's `courses` row, with buckets `syllabus | lectures | assignments | labs | readings | exams | code | other`. A stored file is identified by `local_path` + `hash`.

## Conventions

- Python 3.12, `ruff`, `pytest`. Type hints everywhere. Dataclasses for models.
- Tests use fakes in `tests/fakes/`; no network in tests.
- Uploads stage in `config.tmp_dir/{uuid}`, always deleted in a `finally`.
- Log with `logging`, never `print`, except in CLI output via `rich`.
- Commit message format: `BL-0XX: <ticket title>`.
- Migrations: sequential integers, one file each (`core/memory/migrations/vNNN_<name>.py`, literal SQL that never imports shared constants). Never renumber or edit a committed one; a schema change is a new file. `tests/test_migrations.py` checksums every committed migration and applies them all from v0 on an empty database.

## Not in V1

- Drive automation (can return via StorageBackend)

## Decision log

Newest first. Add a row whenever a principle is bent or a provider choice changes.

| Date | Decision | Why |
| --- | --- | --- |
| Oct 17, 2026 | Uploads in the `other` bucket are linked to NotebookLM; only `code` is skipped. | Every file is now chosen by hand, so `other` is not junk; names without a keyword were never reaching NotebookLM. |
| Oct 17, 2026 | Brightspace automation removed; files are uploaded by hand. `LMSProvider` is gone; the storage tree, buckets and link step are unchanged. Courses are rows of their own (`courses add`), each with its term folder; v13 keys `resources` by `resource_id` and keeps every old row as `topic:{id}`. `sync` only links stored files to NotebookLM. | BL-042. The Playwright login and `/d2l/api` downloads can't be used, so Simon adds course files himself; principles 1 and 2 no longer mention Brightspace or `playwright`. |
| Sept 24, 2026 | Migrations are sequential integers, one file each under `core/memory/migrations/`, never renumbered or edited once committed. A test checksums each one and applies them all from v0 on an empty database. | BL-040 (P70). A committed migration may already have run on a real database, so changing it would split the history. |
| Sept 24, 2026 | A tutor session with no turn for 2 hours is stale: `ask` and the other guarded commands say so and offer `sessions close`. `maintain` closes sessions idle more than 24 hours, without running the Analyzer. Sessions record `last_turn_at` (v12). | BL-040 (P67). A crashed session shouldn't block a course for long. |
| Sept 24, 2026 | One fallback per task, recorded in `fallback_from`; a preferred provider skipped as unusable counts as that fallback. The Critic and the exam grader never run on a provider that wrote the questions. With only one provider, critique is skipped and the exam is marked `"review": "uncritiqued"`. | BL-040 (P79, P80, P85). |
| Sept 24, 2026 | `concepts apply` upserts by concept id, keeping the `{course}/{slug(name)}` format. Concepts missing from the reviewed draft get `status = retired` (v11), never deleted, with mastery and evidence untouched. An optional `aliases: [...]` maps a renamed concept to its existing row. `apply` prints added / updated / retired counts. | BL-040. Requested under "P74", but this is P46 (concept ids); Simon chose to keep today's id format. P74 (weeks) is unchanged. |
| Sept 24, 2026 | A Challenger probe on an Analyzer-proposed jump, resolved in the learner's favour (its grade proposes the challenged level or more), sets mastery to the Analyzer's full proposed level, citing the original evidence plus the exchange, `changed_by = "challenger"` (v9, v10). A failed probe writes its evidence only, resolves the challenge and changes no level. A probe raised by a tutor-estimate disagreement never changes a level. Never an average. | BL-040 (P72). Simon's decisions. |
| Sept 23, 2026 | Router v1 replaces v0: the `[routing]` order per task type, minus unusable providers, re-ordered by the `benchmarks` composite once every candidate has 10+ measured runs. It falls back on any model error, not only rate limits. Principle 8's exception now covers only the config order used before there's data. | BL-035. The benchmarks are measured, not decreed, and the config order is only the cold start. |
| Sept 23, 2026 | While a course has an open tutor session, nothing else starts a NotebookLM conversation on it: `ask`, `concepts seed` and a second `tutor` refuse; `/ask` inside the session uses its conversation. `brightlearn sessions close` ends a stuck one. | A fresh conversation deletes the latest one, which is the live tutor's (P66). |
| Sept 23, 2026 | Model routing v0 is a fixed order per purpose, read from `[routing]` in `~/.brightlearn/config.toml` (teaching `claude, codex`; analysis `codex, claude`). A temporary exception to principle 8 until the benchmarks table exists (Phase 10). | The ticket asked for v0; keeping the order in config makes it data, not code. |
| Sept 23, 2026 | The vault moves out of the repo to `~/.brightlearn/vault/`; it is no longer git-versioned. | Transcripts and mastery are personal; nothing personal should be committable. |
| Sept 23, 2026 | Every NotebookLM query starts a fresh conversation (the provider deletes the notebook's latest one first); a tutor session keeps one conversation of its own. NotebookLM's chat history for BrightLearn notebooks is not kept; the ledger and transcripts are the record. | Otherwise NotebookLM carries hidden history into the Context Compiler's minimal package. |
| Sept 23, 2026 | A changed course file is kept in `_versions/` before it is replaced. | Principle 3: a corrected lecture's old version is exactly what you'd want back. |
