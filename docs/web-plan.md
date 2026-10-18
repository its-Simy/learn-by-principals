# Plan: drop Brightspace automation, import files by hand, add a NotebookLM-style web UI

## Context

Brightspace automation (Playwright login + `/d2l/api` downloads) can't be used, so Simon will add course files himself. The Brightspace code, its Chromium dependency, its doctor rows and every comment or doc line that describes it come out, and a manual import takes its place: a file is stored under the course folder, classified into a bucket, and pushed to NotebookLM by the existing link step. On top of that, a local web app replicates NotebookLM's three-pane layout (Sources | Chat | Studio) so the tutor, exams, podcasts and mastery are usable without the CLI. Stack: FastAPI wrapping the existing core with no new business logic, and a Vite + React + TypeScript SPA with Tailwind and shadcn/ui components.

Decisions already made with Simon: delete the Brightspace code rather than keep it dormant; all three panes in v1; Vite SPA + FastAPI (not Next.js); files come in through the web UI only (no CLI `import`, no drop-folder watcher).

The seven review fixes from earlier are still uncommitted in `docs/validation-log.md` and `TICKETS-3.md`. They get committed first, unchanged, as `BL-041: Validation log: review fixes`; the validation log is rewritten in the last ticket once the UI exists.

Work is ticketed in a new `TICKETS-4.md` (BL-042 … BL-050), one commit per ticket in the `BL-0XX: <title>` format, each keeping `pytest` and `ruff` green. Style throughout: dataclasses and type hints in core, short docstrings that say why (not what), tests on fakes with no network, `logging` not `print`.

Environment facts: Python 3.12 venv via uv; Node 26 and pnpm 10 installed; no web dependencies exist yet; `dist/` is already gitignored.

---

## BL-042 Manual import replaces Brightspace sync

One ticket, because the engine, classifier, manifest key and sync CLI change together; splitting would leave the tree broken between commits.

### Delete

- `core/providers/lms/` (base.py, session.py, brightspace.py, `__init__.py`), `core/sync/engine.py`.
- `tests/test_brightspace.py`, `tests/test_engine.py`, `tests/fakes/session.py`, `tests/fakes/lms.py`, `tests/fixtures/*.json` (all four are Brightspace responses; nothing else reads `tests/fixtures/`).
- `cli/dev.py` `courses` command; `cli/common.open_lms` and its three imports.
- `cli/doctor.py`: `check_chromium`, `check_brightspace`, the `chromium_executable` import, their rows in `checks()`; `test_doctor.py::test_brightspace` and the Chromium/Brightspace assertions.
- `core/config.py`: `DEFAULT_BASE_URL`, `brightspace_base_url`, `login_timeout_s`, `browser_profile_dir`, `storage_state_path`; the `tests/conftest.py` fixture and `test_config.py` lines that use them.
- `pyproject.toml`: the `playwright` dependency; description becomes "course files → NotebookLM → learner memory". `.gitignore`: drop `browser-profile/` and `brightspace_login*.json` (keep `storage_state.json`, NotebookLM uses that name too).
- `tests/test_dashboard.py` headless-Chromium render test. The HTML-content test stays. `test_principles.FORBIDDEN` keeps `"playwright"`; it simply never matches now.
- Comments and docstrings: `Manifest` ("one row per Brightspace topic" → "one row per stored course file"), `default_term` ("until the term can be read from Brightspace" → "the default term for new courses"), `doctor.py` ("never opens a login window" → "every check is read-only"), `classify.py` header, `cli/dev.py` header, `check_tmp` ("download staging" → "upload staging"). Acceptance includes `grep -rni brightspace core cli dashboard tests scripts pyproject.toml` returning nothing.

### Migration `core/memory/migrations/v013_courses_and_resource_ids.py`

Follows the v009 rebuild pattern (create `_v13`, `INSERT … SELECT`, drop, rename, recreate index). Literal SQL, no imports.

```sql
CREATE TABLE courses (
    course     TEXT PRIMARY KEY,      -- the code used in paths and notebook titles, e.g. CSE220
    name       TEXT NOT NULL,
    term       TEXT NOT NULL,         -- folder under storage_root, e.g. Fall-2026
    created_at TEXT NOT NULL
);
CREATE TABLE resources_v13 (
    resource_id        TEXT PRIMARY KEY,
    course             TEXT NOT NULL,
    title              TEXT NOT NULL,
    filename           TEXT,
    bucket             TEXT,
    local_path         TEXT,
    hash               TEXT,
    size               INTEGER,
    url                TEXT,
    notebook_id        TEXT,
    notebook_source_id TEXT,
    source_hash        TEXT,
    sync_state         TEXT NOT NULL DEFAULT 'synced'
                       CHECK (sync_state IN ('synced', 'stale', 'failed', 'link', 'deferred')),
    added_at           TEXT NOT NULL
);
INSERT INTO resources_v13 SELECT 'topic:' || topic_id, course, title, filename, bucket, local_path,
    hash, size, url, notebook_id, notebook_source_id, source_hash,
    CASE sync_state WHEN 'pending' THEN 'failed' ELSE sync_state END, last_seen FROM resources;
INSERT INTO courses SELECT course, course, <term parsed from local_path, else 'unknown'>, min(last_seen)
    FROM resources GROUP BY course;
DROP TABLE resources; ALTER TABLE resources_v13 RENAME TO resources;
CREATE INDEX resources_course ON resources (course, bucket);
```

- Brightspace-only columns go: `org_unit_id`, `module_path`, `type_identifier`, `last_modified`; `last_seen` becomes `added_at`. Old rows keep their files, hashes and NotebookLM links (principle 3); `link` rows (URL topics) copy as they are.
- The term backfill takes the path segment before `/{course}/` in `local_path` (the SQLite `rtrim(x, replace(x, '/', ''))` last-segment trick, commented), else `'unknown'`. No real database has Brightspace rows today (every validation step is "not run"), but the migration must be safe regardless.
- `core/memory/schema.py`: `SYNC_STATES` loses `pending`; `SCHEMA_VERSION = 13`. `tests/test_migrations.py`: v13 checksum in `COMMITTED`, `courses` in `TABLES`, and a test that a v12 database with two file rows and one `link` row migrates to `topic:N` ids with a backfilled course.

### Code

- `core/memory/db.py`
  - `ResourceRow(resource_id, course, title, added_at, filename=None, bucket=None, local_path=None, hash=None, size=None, url=None, notebook_id=None, notebook_source_id=None, source_hash=None, sync_state="synced")`.
  - `Manifest.get(resource_id)`, `upsert` (conflict on `resource_id`), `find(course, bucket, filename) -> ResourceRow | None` (replaces `name_owner`), `all(course=None, states=None)` ordered by `added_at, resource_id`.
  - New `CourseRow(course, name, term, created_at)` with `root(storage_root: Path) -> Path` (`storage_root/term/course`), and `Courses(conn)` with `add(course, name, term) -> CourseRow` (refuses a duplicate or a code outside `[A-Za-z0-9_-]{1,32}`), `get(course)`, `all()`.
- `core/sync/importer.py` (new, replaces `engine.py`)
  ```python
  @dataclass(frozen=True)
  class ImportResult:
      row: ResourceRow
      outcome: str  # new | changed | unchanged

  class Importer:
      def __init__(self, storage: StorageBackend, db: Manifest, courses: Courses,
                   now: Callable[[], str] = utcnow, classify_fallback: Fallback | None = None) -> None
      def import_file(self, src: Path, course: str, name: str, bucket: str | None = None) -> ImportResult
  ```
  `import_file` consumes `src` (callers stage it under `config.tmp_dir/{uuid}` and unlink in `finally`, as today). Steps: the course must exist (`UnknownCourse`); `bucket = bucket or classify(name, fallback)`; `existing = db.find(course, bucket, name)`; `stored = storage.store(src, f"{term}/{course}/{bucket}", name)` (old version kept in `_versions/`); outcome from the hash; `sync_state` is `stale` when a linked file changed, else `synced`; `resource_id = uuid4().hex` for a new row. Same name in the same bucket means "a new version of that file", which is what re-uploading a corrected lecture should do.
- `core/sync/classify.py`: `classify(title: str, filename: str | None = None, fallback=None) -> str`, `Fallback = Callable[[str, str | None], str | None]`, `ModelClassifier.__call__(title, filename)`; rules unchanged.
- `core/sync/link.py`: `row.topic_id` → `row.resource_id` in `_rank` and `_fail`. Nothing else changes.
- `cli/sync.py`: link-only. `sync [--course CODE | --all] [--include-code]` runs `LinkStep.run` per course from `Courses.all()` and prints the NotebookLM table. `--term`, `--dry-run`, `--force` go. Docstring: "Push stored course files to NotebookLM."
- `cli/courses.py` (new): `courses list`, `courses add [CODE] --name TEXT [--term Fall-2026]` (default `config.term`; since BL-051 the code is derived from the name when left out). `tutor`, `concepts` and `exam` need a course row, so this stays in the CLI even though uploads are web-only.
- `cli/generate.py`, `cli/podcast.py`: `_generated` lives under `CourseRow.root(config.storage_root)`, not `config.term`.
- `scripts/spike_c.py`: `ORDER BY added_at`; docstring says "after uploading the syllabus".
- Tests: `tests/test_importer.py` ports the storage/manifest cases from `test_engine.py` (bucket tree, re-import unchanged, changed file → `stale` plus `_versions`, same bytes unchanged, explicit bucket, unknown course refused, store failure leaves no row); `test_cli_sync.py` becomes link-only; `test_db.py` covers `Courses` and `find`; `test_classify.py`, `test_ollama.py`, `test_link.py`, `test_cli_ask.py`, `test_dashboard.py`, `test_exam_generate.py`, `test_gemini_notebook.py`, `test_seeding.py` build `ResourceRow` with the new fields (every call site uses keywords, so it is a rename per site).

### Docs in the same ticket

- `CLAUDE.md`: intro line; principle 1 drops "session-cookie endpoints (Brightspace)"; principle 2 drops `playwright`; repo layout (no `lms/`; `sync/` = `classify.py, importer.py, link.py`; `cli/` adds `courses.py`); secrets line; config table (remove `brightspace_base_url`; `term` = "default term for new courses"; move the six decision-log rows that sit inside the table at lines 56-61 into the decision log where they belong); provider interfaces (remove `LMSProvider` and the implementations line); delete "Brightspace facts"; data model (`resources` and `courses`); conventions (no fixtures line; "uploads stage in `tmp_dir/{uuid}`"); decision-log row: "Brightspace automation removed; files are uploaded by hand. `LMSProvider` is gone; the storage tree, buckets and link step are unchanged."
- `BrightLearn — Master Spec.md`: one decision-log row (newest first); the body stays as history.
- `problems.md`: a `## BL-042` section noting P10, P15, P16 and P17 are moot and why.

**Acceptance:** `pytest` green with no `playwright` installed; `brightlearn courses add CSE220 --name "Systems Fundamentals"` then an `Importer.import_file` test stores `Fall-2026/CSE220/lectures/x.pdf`, a second identical import is `unchanged`, a changed one is `stale` with the old bytes in `_versions/`; `brightlearn sync --course CSE220` with the fake knowledge provider links the stored rows; `doctor` has no Chromium or Brightspace row; the Brightspace grep is empty.

---

## BL-043 Core wiring and the session guard

The API must not import `cli/`, so the provider factories move out of it.

- `core/wiring.py` (new; `cli/common.py` deleted): `MODEL_PROVIDERS`, `open_model`, `model_providers`, `knowledge(config, conn) -> GeminiNotebookProvider` (plain factory), `open_knowledge` (the existing context manager over it), `router`, `session_end_hook`, `challenge_runner`, plus `tutor(config, conn, knowledge, providers, course, persona) -> Tutor`, which is `cli/tutor.py` lines 37-50 lifted verbatim. A straight move, not a re-export shim: `model_providers` resolves `open_model` through its own module globals, so the eight tests that monkeypatch `common.open_model` would silently stop working under a shim. The eleven test files patch `core.wiring` instead (mechanical; ruff `I` reorders imports).
- `core/sessions.py` (new): `SessionOpen(session, stale)` and `guard(learner, course, now=None)`, the one-live-conversation-per-course rule (P66) as a pure function. `cli/sessions.refuse_if_session_open` becomes `try: guard(...) except SessionOpen: <existing Rich lines>; raise typer.Exit(1)` with the same messages and tests.
- `core/doctor.py` (new): `Status`, `Check`, every `check_*`, `checks`, `run_checks` move here; `cli/doctor.py` keeps `doctor()` and `COLOURS`.
- `core/exams/spec.py`: `find_spec(vault_root, course, name) -> ExamSpec` (the body of `cli/podcast._find_spec`, raising `SpecError`).

**Acceptance:** no `cli/common.py`; `grep -rn "from cli" core` is empty; the full suite is green.

---

## BL-044 API skeleton, system routes and `brightlearn web`

Package `api/` (added to hatch `packages`). Dependencies: `fastapi`, `uvicorn`, `python-multipart`; dev `httpx` (TestClient). Localhost only, no auth; the module docstring says so.

### Threading model (`api/engine.py`)

Exactly three things are not thread-safe: a `GeminiNotebookProvider` (private asyncio loop, pacing state), a `Router` (in-process failure map), and a live `Tutor`. Each gets one owner thread. SQLite is not why: reads and DB-only writes use a per-request connection, as one CLI command does, so list views never wait behind a five-minute tutor turn.

- **Per-request connection** (`api/deps.py: db()`): every list/get route, course create, session close, concept apply, draft read/write, exam take/answer/skip/finish (file only), markdown, podcast list/audio. Opened with `core.memory.db.connect`, closed in `finally`.
- **`interactive` worker**: tutor start/get/turn/end and grounded `ask`. Serialises every NotebookLM conversation action in the process.
- **`jobs` worker**: `link`, `seed`, `exam_create`, `exam_grade`, `podcast`, FIFO one at a time. A 20-minute podcast delays a later grade; one user, so no second long worker.

Routes are plain `def`, so FastAPI runs them in its threadpool and a 300 s model call never blocks uvicorn's loop; the worker threads run no loop of their own, which is what makes the provider's `run_until_complete` safe.

```python
@dataclass
class Resources:
    """What one worker thread owns. Nothing here is thread-safe, so nothing here is shared."""
    config: Config; conn: sqlite3.Connection; knowledge: KnowledgeProvider
    providers: dict[str, ModelProvider]; router: Router
    # properties learner, manifest, courses, vault; close()

def open_resources(config: Config) -> Resources   # real wiring, run on the worker's own thread

class Worker:        # one daemon thread + queue.Queue; submit(fn) -> Future, call(fn) -> T, close()
class Job:           # id, kind, course, status queued|running|done|failed, timestamps, result: dict | None, error
class Jobs:          # in-memory registry over the jobs worker: submit(kind, course, fn) -> Job, get, all(course), running(course, kinds)
CONVERSATION_JOBS = frozenset({"exam_create", "seed"})   # start fresh NotebookLM conversations (P66)
class JobRunning(Exception): ...

class Engine:
    def __init__(self, config: Config, open_resources=open_resources) -> None   # interactive + jobs workers, Jobs, tutors: dict[str, Tutor]
    def start(self) -> None     # start both workers; a bad [routing] fails here, like the CLI
    def close(self) -> None
    def live_sessions(self) -> dict[str, str]   # {course: session_id} for list views
    def drain(self) -> None     # tests: wait until every queued job has run
```

Daemon threads rather than an executor so Ctrl-C on `brightlearn web` exits at once, even mid-podcast, like Ctrl-C on the CLI. Jobs are lost on restart; the files and rows they wrote are not.

**P66 across threads:** `start_session` runs `guard(r.learner, course)` and refuses if `jobs.running(course, CONVERSATION_JOBS)` (409 `job_running`); `exam_create` and `seed` job functions call `guard` as their first statement on the job thread; `ask` uses the live tutor's `ground` when one exists, else `guard` then a fresh `knowledge.query`. Every 409 carries `{code: "session_open", session_id, stale}` so the UI can offer "close stale session" in place.

**Errors** (`api/app.py: register_errors`): `SessionOpen` → 409; `JobRunning` → 409; `DuplicateCourse` → 409 (registered before the generic handler); `LearnerError, SeedingError, SpecError, ExamFileError, GradeError, PersonaError, StorageError, ValueError` (which covers `ImportRefused`) → 422; `KnowledgeError, ModelError` (incl. `NoProvider`) → 502 `{detail, provider, resets_at}`, where `resets_at` comes from a `ModelRateLimited` hint so the chat can say when to retry; `FileNotFoundError` → 404. The top bar's `HealthDots` read the `health` records (state, cooldown) already in `/api/dashboard`.

### Files

- `api/app.py`: `create_app(config=None, engine=None) -> FastAPI`; lifespan starts/closes the engine; routers under `/api`; `register_errors`; `mount_web` last.
- `api/deps.py`: `config`, `engine`, `db` (per-request connection), `course_code` (404 unless the course exists).
- `api/schemas/` package, one module per router (`system.py`, `courses.py`, `sources.py`, `chat.py`, `studio.py`): pydantic models live only here, each with a `from_core(...)` classmethod as the sole glue from core dataclasses. Pydantic because FastAPI needs it for OpenAPI, which drives the generated TS types; core stays dataclasses. One module per router so BL-045 and BL-046 can be built in parallel without touching the same file.
- `api/static.py`: `DIST = repo/web/dist`; `mount_web(app)` serves `/assets`, existing files under `dist` (path checked with `resolve().is_relative_to(dist)`), else `index.html` for SPA deep links; without a build, `/` returns one plain line telling you to run `pnpm --dir web build`. `/api/*` never falls through.
- `api/routes/system.py`: `GET /api/health`, `/api/personas`, `/api/dashboard` (`dashboard.data.collect`), `/api/doctor` (`core.doctor.run_checks`), `/api/jobs?course=`, `/api/jobs/{id}`.
- `cli/web.py`: `web(port=8765, --open/--no-open)` runs `uvicorn.run("api.app:create_app", factory=True, host="127.0.0.1")` and opens the browser after a second. `cli/dev.py` gains `openapi` (prints `create_app(config).openapi()`; building the app has no side effects, the engine starts only under a server).

**Tests:** `tests/conftest.py` `api` fixture builds `Engine(config, open_resources=fake_resources)` where `fake_resources` opens its own connection on the worker thread and shares one `FakeKnowledge` and two `FakeModel`s; `with TestClient(create_app(config, engine))`. No monkeypatching, no network. `tests/test_api_engine.py` (one thread per worker, failed job carries its error, `drain`, idempotent `close`); `tests/test_api_system.py` (health, personas, dashboard from seeded data, doctor, static mount with and without a tmp `dist`). `tests/test_principles.py` scans `api/`.

**Acceptance:** those tests pass; `brightlearn web --no-open` serves `/api/health` and the "not built" line at `/`.

---

## BL-045 Courses, sources and chat routes

Thread column: req = per-request connection; int = interactive worker; job = jobs worker.

| Route | Thread | Core call | Response |
|---|---|---|---|
| `GET /api/courses` | req | `Courses.all()` + source/concept counts + `engine.live_sessions()` | `list[CourseOut{course, name, term, created_at, sources, linked, concepts, open_session_id}]` |
| `POST /api/courses` `{course, name, term?}` | req | `Courses.add` (term defaults to `config.term`; 409 on duplicate) | `CourseOut` |
| `GET /api/courses/{c}/sources` | req | `Manifest.all(course)` | `list[SourceOut{resource_id, filename, bucket, size, sync_state, notebook_source_id, linked, added_at}]` |
| `POST /api/courses/{c}/sources/upload` multipart `files[]`, form `bucket?` | req → job | 409 `job_running` while a `link` job for this course is running (the link step writes back the row it read at the start, so a concurrent re-upload would be overwritten); then per file: write to `tmp_dir/{uuid}/{sanitize_filename(name)}`, `Importer.import_file`; `shutil.rmtree` in `finally`; then a `link` job running `LinkStep.run(course)` | `UploadOut{imported: list[SourceOut], job: JobOut}` |
| `POST /api/courses/{c}/sources/link` | job | `LinkStep.run(course)` (retries un-linked rows by construction) | `JobOut` |
| `POST /api/courses/{c}/session` `{persona="simplifier"}` | int | `guard`; `jobs.running` check; `wiring.tutor(...)`; `start()`, `opening()`; `engine.tutors[course] = t` | `LiveSessionOut{session_id, persona, started_at, turns: [{role, text}], probe, ended, ratable}` |
| `GET /api/courses/{c}/session` | int | `engine.tutors.get(course)` | `LiveSessionOut \| null` |
| `POST /api/courses/{c}/session/turn` `{text}` | int | `tutor.handle(text)` (the REPL's lines: plain text, `/persona x`, `/rate n`, `/skip`, `/ask q`); drop from registry if ended | `TurnOut{reply, ended, persona, probe, ratable}` |
| `POST /api/courses/{c}/session/end` | int | `tutor.end()` (runs the Analyzer; minutes) | `TurnOut` |
| `POST /api/courses/{c}/ask` `{question, source_ids?}` | int | live tutor → `tutor.ground(q)`; else `guard`, `source_ids ⊆ linked` (422), `knowledge.query(...)`; citations mapped to filename/bucket via the manifest (what `cli/ask.py` prints) | `AskOut{text, citations: [{n, source_id, filename, bucket, excerpt}], in_session}` |
| `GET /api/courses/{c}/sessions` | req | `learner.sessions(course)`, `idle_for` vs `STALE_AFTER`, live set | `list[SessionOut{…, state: open\|stale\|ended, live}]` |
| `GET /api/sessions/{id}/transcript` | req | the vault transcript file (404) | `TextOut{text}` |
| `POST /api/sessions/{id}/close` | req | 409 if live ("end it instead"); `learner.close_session` | `SessionOut` |

**Concurrency rules (from the BL-044 review):** one `Engine.lock` closes the check-then-register gap between the two workers. Session start holds it over `guard` + `jobs.running(course, CONVERSATION_JOBS)` + `wiring.tutor` + `Tutor.start()` + the registry insert, and releases it before `opening()`. The `seed` and `exam_create` routes hold it over `guard` (on the request connection) + `jobs.submit`. Nothing ever calls `worker.call` while holding it, and the job functions keep their own `guard` (it covers a CLI session in another process). A no-session `ask` also returns 409 `job_running` while a conversation job is queued or running on the course, because the jobs worker has its own NotebookLM provider and two fresh conversations on one notebook would interleave. `ask` and session start return 422 when the course has nothing linked, so only the link job ever creates the notebook (an `ensure_notebook` race would otherwise create two). `core.sessions` gains `state(session, now) -> "open" | "stale" | "ended"` used by `sessions list`, the API and the guard, so the stale rule exists once. A callable handed to the engine never captures the request connection.

**Tests:** `tests/test_api_courses_sources.py` (create/list, duplicate 409, upload two files with and without `bucket` → rows via the Importer, staging dir gone, link job → `drain` → two `add_file` calls on the fake; unknown bucket 422; retry link). `tests/test_api_chat.py` (start; turn grows the transcript; `/ask` in session uses `ground` with the session's conversation id and `in_session` true; ask with no session cites `lec3.pdf (lectures)`; second start → 409 `session_open`; start while a job is parked on a `threading.Event` → 409 `job_running`; `exam_create` with an open session → job `failed` naming the session; stale row close; live close → 409; end sets `ended_at` and empties the registry).

**Acceptance:** both files pass; an uploaded file lands under `storage_root/{term}/{course}/{bucket}/` and is linked by the job.

---

## BL-046 Studio routes

| Route | Thread | Core call |
|---|---|---|
| `GET /api/courses/{c}/concepts` | req | `learner.concepts` + `get_mastery` each → `ConceptOut{…, level, confidence, evidence_count, retention_confidence, last_evidence_at}` |
| `GET /api/courses/{c}/concepts/evidence?concept_id=` | req | `learner.evidence` |
| `POST /api/courses/{c}/concepts/seed` | job | `guard`; `seeding.seed` → result `{draft, count, diff}` |
| `GET /api/courses/{c}/concepts/drafts`, `GET/PUT …/drafts/{name}` `{text}` | req | list/read/write the draft YAML (name validated by the seeding module's pattern; 404 otherwise) |
| `POST /api/courses/{c}/concepts/apply` `{draft?}` | req | `seeding.apply` (`DraftNotReviewed` → 422) → `ApplyOut{added, updated, unchanged, retired, retired_names, unknown_prerequisites}` |
| `GET /api/courses/{c}/exams`, `GET …/exams/{id}` | req | glob `exams_dir` + `paper.load` → `ExamOut{id, exam, course, created_at, mode, questions, review, attempts: [{attempt, started_at, finished_at, answered, graded}]}` |
| `POST /api/courses/{c}/exams` `{spec_yaml}` | req → job | `parse_spec` now (422; `spec.course` must match); job: `guard`, then the body of `cli/exam.py create` (plan, generate, `new_paths/new_exam/save`, write `.md`) → result `{exam_id, questions, planned, generator_providers, critic_provider, regenerated, dropped, critiqued}` |
| `GET …/exams/{id}/markdown` | req | `paper.to_markdown` (includes the key; UI labels it "Paper with answer key") |
| `POST …/exams/{id}/take`, `…/take/answer` `{reply}`, `…/take/skip`, `…/take/finish` | req | `ExamTaker`; `answer/skip/finish` return 409 unless the latest attempt is unfinished (otherwise `ExamTaker` would silently open attempt N+1) → `TakeOut{attempt, resumed, total, answered, question: QuestionOut \| null}` where `QuestionOut{index, stem, options, format, difficulty, concept_id}` is built from an explicit key list so `answer`/`rubric` can never leak |
| `POST …/exams/{id}/grade` | job | `ExamGrader(...).grade(path)` → result with `correct, graded, new_evidence, scores[...]` |
| `POST /api/courses/{c}/podcast` `{exam?, format="deep-dive", length?}` | job | `find_spec` if `exam`; `build_podcast_context`; `knowledge.generate_audio`; move into `CourseRow.root/_generated`; `PodcastStore.record` (the body of `cli/podcast.py`) |
| `GET /api/courses/{c}/podcasts`, `GET /api/podcasts/{id}/audio` (FileResponse `audio/mp4`), `GET /api/podcasts/{id}/brief` | req | `PodcastStore.all`, the files |

`exam_id` and draft names must match `[A-Za-z0-9._-]+` and exist, else 404.

**Tests:** `tests/test_api_studio.py` (concepts with mastery; seed job writes a draft; PUT `reviewed: true` then apply counts; exam create with `FakeQuestioner`/`FakeCritic` → 6 questions `critiqued`; `take` has no `answer`/`rubric` keys; bad MC letter 422; answer after finish 409; grade → 6 evidence rows; markdown has the answer key; podcast job → row and `/audio` returns the fake bytes; `..` exam id → 404).

**Acceptance:** tests pass.

**Contract (integration step after BL-045 and BL-046 merge):** `brightlearn dev openapi > web/openapi.json` is committed; `tests/test_api_openapi.py` asserts `create_app(config).openapi()` equals the file, with a message that says how to regenerate it and the TS types. This lands with BL-047 so the web tickets build on a pinned contract.

---

## BL-047 Web scaffold, shell and Sources pane

### Tooling (`web/`)

`pnpm create vite web --template react-ts` (React 19, TS strict); Tailwind v4 via `@tailwindcss/vite` and `@import "tailwindcss"`; shadcn/ui via `pnpm dlx shadcn@latest init` (new-york, neutral, CSS variables; it writes `components.json`, `src/lib/utils.ts`, the token block and the `dark` custom variant). Runtime deps: `react-router` (v7, `BrowserRouter`), `@tanstack/react-query`, `openapi-fetch`, `react-markdown` + `remark-gfm`, `lucide-react`, `sonner`. Dev: `openapi-typescript`, `@types/node`. shadcn components, and only these: `button, card, badge, checkbox, input, textarea, select, dialog, sheet, popover, scroll-area, tooltip, skeleton, sonner`.

`index.css` adds three semantic tokens next to shadcn's, defined for both themes and checked for 4.5:1 on `bg-muted`: `--success`, `--warning`, `--pending`. They are the only colours any state badge or health dot uses, and every badge and dot also carries text, so state is never colour alone.

`src/api/types.ts` is generated by `pnpm gen` (`openapi-typescript openapi.json -o src/api/types.ts`) and committed, so `pnpm build` needs no Python. `src/api/client.ts` is `createClient<paths>({ baseUrl: "" })`: every call typed by path and method, no hand-written fetch wrappers. Scripts: `dev`, `build` (`tsc -b && vite build`), `typecheck`, `gen`. `vite.config.ts` proxies `/api` to `127.0.0.1:8765`. `.gitignore` += `web/node_modules/`.

### Layout

```
web/src/
  main.tsx  App.tsx (routes "/", "/courses/:course", "/system")  index.css
  api/        client.ts  types.ts (generated)  queries.ts (hooks)  jobs.ts (useJob polling + per-kind invalidation map)
  lib/        utils.ts (cn)  theme.ts (.dark on <html>, localStorage, default prefers-color-scheme)  format.ts
  components/ui/   (shadcn)
  components/      TopBar  ThemeToggle  JobsIndicator  HealthDots  Markdown  LevelBar  StateBadge  Pending  EmptyState  Rail
  features/sources/  SourcesPane  SourceRow  UploadDropzone  LinkJobBar
  features/chat/     ChatPane  SessionBanner  ProbeBanner  MessageList  Message  PendingMessage  ErrorMessage  CitationChips  Composer  RateButtons
  features/studio/   StudioPane  MasteryCard  PracticeExamCard  AudioOverviewCard  ConceptsCard  DraftEditor  JobRow
  features/exams/    ExamTakeView
  pages/      HomePage  CoursePage  SystemPage
```

### The NotebookLM look

56 px top bar with the app's name (no mark since BL-051), the course's name, `HealthDots` (one per provider, text in a tooltip, including a rate-limit reset time), `JobsIndicator` (running/queued count with a recent-jobs popover) and `ThemeToggle`. `CoursePage` is chat-first: the chat fills the page on `bg-background`, and Sources and Studio are `Rail`s on `bg-muted/30` that collapse to a 48 px icon strip at any width and remember their state; below `lg` both start collapsed and open as `sheet`s. Open rails are 320 px (Sources) and 360 px (Studio). Each rail has one quiet header row (title plus one icon button), 1 px `border-border` dividers, 16 px padding, `rounded-xl bg-card` cards. Badges: bucket `secondary`; state through `StateBadge` only. Chat: learner bubbles right in `bg-primary text-primary-foreground`, tutor and source answers left in `bg-muted` with rendered Markdown at 15–16 px `leading-relaxed`, code blocks scrolling horizontally; citation chips `[1] lec3.pdf` are buttons that open a `popover` with the excerpt, so they work by keyboard and touch. Studio (since BL-051) opens on tiles, each an icon, a title and one status line; a tile's view has a title, a one-line status, one primary action and a short list. Light and dark come entirely from the tokens; no ad-hoc `dark:` classes.

Shared pieces every feature reuses: `StateBadge` (text plus semantic colour for source, session, job and health states), `Pending` (spinner, label, elapsed time, `aria-live="polite"`), `EmptyState` (one sentence and the next action), `JobRow` (a `Pending` plus typical duration inside the card that started the job, then the one-line result or error). Dialogs are for read-only text only (transcript, paper, brief); anything edited or taken gets a view.

### This ticket's components

`HomePage`: `CourseGrid` → `CourseCard` (name, "n sources · m linked · k concepts", last activity, open/stale session badge; the code and term stayed off the card from BL-051) and `NewCourseDialog` (a name only since BL-051; the server derives the code); `EmptyState` "Create your first course". `CoursePage` shell with the two rails and the chat area, Chat and Studio as placeholders. `SystemPage`: `DoctorTable` with status badges and a Re-run button; dashboard sections from `/api/dashboard`. `SourcesPane`: header with Upload button and select-all checkbox → `SourceRow` (whole row toggles, at least 40 px tall; checkbox only when linked; file icon, filename, bucket badge, `StateBadge` with a tooltip explaining the state, e.g. deferred = over the 50-source cap, code/other = stored but not sent to NotebookLM) → `UploadDropzone` (drag-drop, plus a button and file input; lists accepted types; optional bucket select; each file shows a `Pending` row until its import returns) → `LinkJobBar` (a `JobRow` for the link job, Retry). `EmptyState` "Upload the syllabus to start." `useJob(id)` polls every 2 s while queued/running and, on done, invalidates `{link: sources, seed: drafts, exam_create: exams, exam_grade: exams+concepts, podcast: podcasts}` and toasts the one-line result or error; the originating `JobRow` shows the same.

**Acceptance:** `pnpm typecheck && pnpm build`; `brightlearn web` serves the built app; the home grid lists courses from the API in light and dark; rails collapse and reopen, and open as sheets at phone width; dropping two PDFs shows them pending then linked within one poll cycle; a new course shows the empty states.

---

## BL-048 Chat pane

One message stream, driven by session state rather than tabs. `ChatPane`: `SessionBanner` (no session: "Asking the course sources. Start a tutoring session to get coaching and track mastery" with persona select and Start; live: persona, started time, End, and a History popover listing past sessions with state badges, Close for a stale one, and a Transcript dialog) → `ProbeBanner` when a Challenger probe is pending ("Challenger question. Your next message is your answer." with Skip) → `MessageList` (`ScrollArea`; `Message` kinds learner | tutor (Markdown) | sources (Markdown + `CitationChips`) | note; `PendingMessage` while a call is in flight, with the step and elapsed time: "Claude is answering · 14 s", "Analyser is reading the transcript · 1 m 20 s"; `ErrorMessage` for a failed turn naming the provider, the reason and the reset time when there is one; `RateButtons` 1–5 under the last ratable tutor answer) → `Composer` (Enter sends, Shift+Enter newline, disabled while a request is in flight; a small "sources only" toggle that maps to `/ask` while a session is live).

State: messages are client state built from `GET /session` turns on mount, plus ad-hoc ask answers and command replies as they happen; a reload drops the ad-hoc ones, the transcript file is the record, as on the CLI. With no session, every message is a grounded ask scoped to the checked `notebook_source_id`s. With a live session, messages are tutor turns; "sources only" sends `/ask`, and the reply shows `in_session` with a note that scoping is off during a session. End shows a `PendingMessage` until the Analyzer returns, then its summary as a note. A 409 `session_open` renders a "close stale session" button in place. `EmptyState` with no linked sources: "Upload course files to ask about them."

**Acceptance:** start → turn → rate → probe → skip → end completes in the browser against the fakes-backed dev server; the pending bubble shows elapsed time while a turn is in flight and the composer is disabled; a forced provider error shows an error bubble with the reset time; citation chips open their excerpt by click and by keyboard.

---

## BL-049 Studio pane

As built: `StudioPane` was a `ScrollArea` of four cards, ordered by what matters to the learner. Sessions live in the chat's `SessionBanner` (BL-048) and usage lives on `/system` with only `HealthDots` in the top bar, so the column stays short.

Since BL-051 it opens on a home after NotebookLM's: a 2-column grid of `StudioTile`s (Mastery, Practice exam, Audio Overview, Concepts, each an icon, a title and one short count), then the course's jobs (`JobRow`s from the same `useCardJob` slots the views read, plus any grading in flight), then "Made so far", a compact newest-first list of the latest ten exams, episodes and drafts whose rows open the tool's view. A tile opens its view (`StudioView`: Back, title, one action, status, the body below), and the editors under Practice exams and Concepts go Back to their view; Back returns the focus to what opened the view. The four views keep the bodies described here:

1. `MasteryCard` (now `MasteryView`, every concept weakest-first with an "Include retired" checkbox): weakest five by level with `LevelBar` and retention, a count of concepts at each level, and a link to the full list. `EmptyState` "Seed concepts from the syllabus" with the Seed action when there are none.
2. `PracticeExamCard` (now `PracticeExamView`): New exam opens a `DraftEditor`-style view with a YAML textarea prefilled from a template and the parser's 422 message inline under it; rows with name, question count, review badge and attempts; Take → `ExamTakeView`; Grade → `JobRow`; Paper → Markdown dialog. `EmptyState` "Add sources and concepts before generating an exam."
3. `AudioOverviewCard` (now `AudioOverviewView`): format, length and exam selects; Generate → `JobRow` with "typically 5–15 minutes"; episode list with `<audio controls>` and a Brief dialog. `EmptyState` "Add sources first."
4. `ConceptsCard` (now `ConceptsView`): active/retired counts, Seed → `JobRow`, drafts list with reviewed badge → `DraftEditor` (a view, not a dialog: textarea, the seed diff beside it, Save with the server's YAML error inline, Apply with its added/updated/retired counts).

`ExamTakeView` at `/courses/:course/exams/:id/take` replaces the chat area for the attempt: one question at a time, progress "3 of 10", multiple choice as radio buttons, short answers in a textarea, coding answers in a monospace textarea, Skip and Finish, and Resume on return (answers are saved per question by the API already). Closing the view never loses the place.

**Acceptance:** seed → edit draft → apply, create → take → grade, and podcast generate → play each complete from the browser, each job showing an inline `JobRow` with elapsed time and then its result; empty states appear on a fresh course; the take view resumes after a reload.

---

## BL-050 Docs and validation for the new workflow

- `CLAUDE.md`: repo layout adds `api/` and `web/`; conventions add the contract step (`brightlearn dev openapi > web/openapi.json && pnpm --dir web gen` whenever a route changes) and `pnpm typecheck && pnpm build`; a decision-log row for the web architecture (two worker threads, one NotebookLM provider per thread, per-request SQLite connections, localhost only, no auth).
- `docs/validation-log.md` rewritten for the manual flow: (1) NotebookLM login + doctor; (2) `brightlearn web`, create CSE220, upload the syllabus and two lectures, check the Sources pane and `~/.brightlearn/courses/Fall-2026/CSE220/`; (3) spike C + `nlm-test`; (4) capture the model CLI outputs; (5) model-test; (6) concepts seed/apply from Studio; (7) a tutor session in Chat; (8) an exam from Studio; (9) a podcast.
- `README.md`: what it is, setup (`uv sync`, `pnpm --dir web install && pnpm --dir web build`, `brightlearn dev nlm-login`, `brightlearn web`), where data lives.
- `TICKETS-4.md` "Still not ticketed" carries the leftovers (Zoom links, PDF export, WAL if "database is locked" ever appears, a second long-job worker).

**Acceptance:** every command named in the log exists; `/code-review` on the docs diff is clean.

---

## Execution with parallel Opus 5.5 agents

This session orchestrates; Opus 5.5 agents (`Agent` tool, `model: "opus"`, `isolation: "worktree"`, `subagent_type: general-purpose`) build the tickets. Each agent gets one ticket, its own worktree and branch, and a brief that points at `CLAUDE.md`, the ticket in `TICKETS-4.md`, and the matching section of this plan. An agent commits on its branch as `BL-0XX: <title>` and reports back; this session merges into `tickets-3` in wave order and resolves any conflict itself.

**Before the first agent:** commit the pending review fixes (`BL-041: Validation log: review fixes`) and write `TICKETS-4.md` from this plan (BL-042 … BL-050, with the "Still not ticketed" list), committed as `TICKETS-4: web backlog`. The tickets file is the brief; the plan sections are the detail.

**Per-worktree setup** (in every agent's brief): first `git reset --hard <tickets-3 HEAD>` so the branch starts at the merged tip. `.venv` is gitignored, so each worktree runs `uv venv .venv && env -u CONDA_PREFIX uv pip install --python .venv/bin/python -e . pytest ruff` (never a bare `uv pip install`: with `CONDA_PREFIX` set it lands in the conda base env), then `chflags nohidden .venv/lib/python3.12/site-packages/*.pth` (macOS flags them hidden and Python 3.12.9 then skips them), and `pnpm --dir web install` once `web/` exists. Agents run `.venv/bin/pytest -q` and `.venv/bin/ruff check .` (and `pnpm --dir web typecheck && pnpm --dir web build` for web tickets) in their own worktree before committing. No agent touches `~/.brightlearn`; tests use `tmp_path` homes.

**Waves** (an agent starts only when its inputs are merged):

| Wave | Agents in parallel | Depends on |
|---|---|---|
| 1 | BL-042 import replaces Brightspace | BL-041 commit |
| 2 | BL-043 core wiring and guard | 042 |
| 3 | BL-044 API skeleton and `brightlearn web` | 043 |
| 4 | BL-045 courses/sources/chat routes · BL-046 studio routes · BL-047a web scaffold and shell | 044 (047a needs only the repo; it builds `web/` tooling, theme, `TopBar`, `Rail`, `StateBadge`, `Pending`, `EmptyState`, `JobRow`, `HomePage`, `CoursePage` shell with placeholder panes, `SystemPage` against the system routes) |
| 5 | BL-047b sources pane · BL-048 chat pane · BL-049 studio pane | 047b: 045 + 047a · 048: 045 + 047a · 049: 046 + 047a. Integration step first: regenerate `web/openapi.json`, add `tests/test_api_openapi.py`, `pnpm gen`, commit as part of 047a's merge |
| 6 | BL-050 docs and validation | everything merged |

Waves 1–3 are sequential because each rewrites files the next one depends on (`cli/common.py`, `core/wiring.py`, `api/engine.py`). Waves 4 and 5 are three agents each, on disjoint files: separate route modules and schema modules in wave 4; separate `features/` folders in wave 5, each swapping only its own placeholder in `CoursePage`. The one shared file in wave 5 is `src/api/queries.ts`; the brief assigns each agent its own hooks file (`queries.sources.ts`, `queries.chat.ts`, `queries.studio.ts`) re-exported from `queries.ts` at merge.

**Review before merge:** after each wave, one reviewer agent (`model: "opus"`) reviews the branch diff against the ticket's acceptance line and CLAUDE.md's principles with the `code-review` skill's recipe, and a `/code-review` pass runs on the merged result. Findings go back to the ticket's agent by `SendMessage`; the agent fixes on its branch. Merge only on a green suite in the merged tree.

**What this session does itself:** the two commits before wave 1, every merge, conflict resolution, the wave-5 integration step, the final browser walk-through in BL-050, and reporting progress to Simon after each wave with what landed and what's running.

## Verification (whole plan)

1. `.venv/bin/pytest -q` and `.venv/bin/ruff check .` after every ticket; `pnpm --dir web typecheck && pnpm --dir web build` from BL-047 on.
2. After BL-042: with `BRIGHTLEARN_HOME` pointed at a scratch home, `brightlearn courses add CSE220 --name X`, `brightlearn doctor` (no Chromium/Brightspace rows), the importer tests, and the Brightspace grep.
3. After BL-046: `brightlearn web --no-open`, then `curl` `/api/health`, `/api/courses`, an upload with `-F files=@syllabus.pdf`, and `/api/jobs/{id}` until done; `tests/test_api_openapi.py` green.
4. After BL-049: full walk-through in the browser against real NotebookLM once logged in (course → upload → ask → tutor session → seed/apply → exam → podcast), recording results in the validation log in BL-050. Design checks on the same pass: every wait shows elapsed time; every empty pane states the next action; rails collapse and the page works at phone width; keyboard-only citation chips and exam taking; badge contrast in dark mode at 4.5:1.
5. `/code-review` on each ticket's diff before committing.
