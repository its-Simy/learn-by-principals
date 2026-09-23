# BrightLearn — Build Backlog 3

Everything here builds against fakes and needs no accounts. Work in order. Read `CLAUDE.md` and `problems.md` first. First action: merge `tickets-2` into `main` and branch `tickets-3` from it.

## Hand-off prompt for Opus

```
You are working on BrightLearn. Read CLAUDE.md, problems.md, then TICKETS-3.md.
Work ONLY on ticket BL-0XX. Do not start the next ticket.
Rules: providers stay in core/providers/; no network in tests; secrets never enter the repo;
commit as "BL-0XX: <title>" and stop. Conflicts with CLAUDE.md → CLAUDE.md wins; say so and stop.
Log anything unresolved in problems.md instead of guessing.
```

---

### BL-029 Session locking, seed safety, version integrity
1. **P66:** one live NotebookLM conversation per course. `ask` refuses when `sessions` has a row for that course with `ended_at IS NULL` and prints the `/ask` hint. Context Compiler queries inside a tutor session use the session's conversation handle, never the fresh-conversation default. Add `brightlearn sessions list` and `sessions close [--all | --id X]`.
2. **P65:** `concepts seed` never overwrites; writes `concepts.draft.{timestamp}.yaml` and prints a unified diff against the newest existing draft.
3. **Version integrity test:** `LocalStorageBackend` store v1 → store v2 → the `_versions` file still hashes to v1. Must fail if the write path is ever in-place rather than rename-into-place.
**Acceptance:** tests for all three; `ask` refusal covered by a test with an open fake session.

### BL-030 Challenger loop
**Goal:** Disagreement produces one probe, never an average.
**Build:** `core/analysis/challenge.py`. When the Analyzer logs `needs_challenge` (proposed level differs from current by ≥ 2), or when the tutor's end-of-session self-estimate (add a one-line `tutor_estimate` field to the session summary) differs from the Analyzer's finding by ≥ 2 levels, queue a `challenges` row: `id, concept_id, session_id, reason, question, status (pending|asked|answered|resolved), created_at`. `brightlearn tutor` opens a session with pending challenges by running the `challenger` persona on that concept first: one question, learner answers, Analyzer grades that exchange alone, writes evidence, resolves the challenge. Max one challenge per concept per session.
**Acceptance:** fakes: ±2 disagreement → exactly one row; ±1 → none; a resolved challenge is not re-asked; two pending challenges on one concept collapse to one.

### BL-031 ExamSpec and Coverage Planner
**Build:** `core/exams/spec.py` loads/validates the YAML from CLAUDE.md (`course, exam, weeks, sources, formats, difficulty, mode, include, exclude`); rejects unknown keys and formats/difficulty that don't sum sensibly. `core/exams/coverage.py`, `plan(spec, concepts, mastery) -> CoveragePlan`: concepts in the spec's weeks, minus `exclude`, plus `include`; weights by mode — `realistic`: uniform by week; `weakness`: weight ∝ (5 − level) with a floor so nothing is zero; `challenge`: only concepts at level ≥ 3, questions tagged transfer; `diagnostic`: highest weight where `confidence` is lowest. Output: ordered list of `(concept, n_questions, difficulty_mix, format_mix)` that sums to the spec's totals.
**Acceptance:** table-driven tests per mode; totals always match the spec; excluded concepts never appear; `weakness` gives the lowest-level concept the most questions.

### BL-032 Question generation and critique
**Build:** `core/exams/generate.py`: for each plan row, build a `TaskPackage` with the `questioner` persona, the coverage row, a grounded `knowledge.query` on that concept (source context), and a strict JSON output schema `{stem, options?, answer, rubric, difficulty, concept_id, format}`. Run through the router (task `question_gen`). Then one `critic` pass on a different provider with the whole draft: returns `{index, issue, fix}` items; apply fixes by regenerating only the flagged questions, once. Validate JSON strictly; invalid → regenerate that question, max 2 tries, then drop and log.
**Acceptance:** fakes: a plan of 6 produces 6 valid questions; critic flags 2 → exactly 2 regenerated; a question that fails validation twice is dropped and logged; critic provider ≠ generator provider.

### BL-033 Exam CLI, taking, grading
**Build:** `brightlearn exam create --spec exams/cse220-midterm1.yaml` → writes `vault/courses/CSE220/exams/{exam}-{timestamp}.json` and a readable `.md`. `brightlearn exam take <file>`: REPL, one question at a time, records answers with timestamps. `brightlearn exam grade <file>`: multiple choice graded locally; short answer and coding graded by the `critic` persona against the rubric on the analysis provider; each graded question → `evidence` row (`applied` on correct, `failed` on wrong, strength by difficulty); mastery changes flow through the normal Analyzer path (`set_mastery` with evidence IDs). Prints score by concept and updates `mastery_history`.
**Acceptance:** fakes: create → take (scripted answers) → grade writes N evidence rows; a wrong hard question produces `failed/strong`; running `grade` twice does not duplicate evidence.

### BL-034 Adaptive podcast compiler
**Build:** `core/podcast/compiler.py`, `compile_podcast_context(course, exam_spec | None, learner) -> str` producing the Markdown instruction file from the master spec's template: skip list (concepts at level ≥ 4 with retention_confidence ≥ 0.7), focus list (weakest by coverage plan or by `weakest()`), misconceptions to confront (from vault notes), teaching preference (from `vault/learner/profile.md`), exam framing, closing thought experiments. Capped at ~400 words. `brightlearn podcast --course CSE220 [--exam midterm1] [--format deep-dive] [--length long]` → compiler → `knowledge.generate_audio` → saves `.m4a` and the instruction file side by side under `_generated/`, and writes a `podcasts` row `(id, course, concepts JSON, instruction_path, audio_path, created_at)` so later evidence can be tied back.
**Acceptance:** fakes: two different mastery states produce different focus lists; skip list never contains a concept below level 4; word cap enforced; `podcasts` row written.

### BL-035 Router v1 with health and benchmarks
**Build:** `core/router/router.py`: `route(task_type) -> ModelProvider`. Inputs: `[routing]` config order, provider `health()` state, and a `benchmarks` table (migration v4, columns from CLAUDE.md). Rule: filter to providers allowed for the task type; drop `RATE_LIMITED | AUTH_EXPIRED | BROKEN | DISABLED`; if benchmarks has ≥ 10 samples for that task, order by a composite score (accuracy 0.4, groundedness 0.3, format_compliance 0.3), else use config order. Every `ModelResult` records `format_compliance` automatically (did the output parse) into benchmarks; `accuracy` and `groundedness` are written by the critic/grader when they exist; `learner_rating` by a `/rate 1-5` command in the tutor REPL. State transitions: a rate-limit error → `RATE_LIMITED` with a cooldown from the provider's `usage_hint` (default 60 min); after cooldown → `AVAILABLE` on next successful health check.
**Acceptance:** fakes: config order used below 10 samples; benchmark order used above; rate-limited provider skipped and restored after cooldown; task with no allowed available provider raises `NoProvider` with a clear message.

### BL-036 Ollama housekeeping provider
**Build:** `core/providers/models/ollama.py` over the local HTTP API (`localhost:11434`), model from config (default `llama3.2:3b`), allowed task types `classify, extract_metadata, summarize` only; router refuses it for anything else. Used first (not last) for `classify` so the rule-based bucket classifier can hand ambiguous titles to it. `health()` = `GET /api/tags`.
**Acceptance:** tests with a mocked HTTP server; router refuses `explain` on Ollama; classifier falls back to it on an ambiguous title only when it is `AVAILABLE`.

### BL-037 Usage dashboard
**Build:** `brightlearn dashboard` writes `~/.brightlearn/dashboard.html` (self-contained, no CDN) and opens it. Sections: today and 7-day runs per provider from `model_runs` (calls, failures, median duration, fallbacks); provider health with last check time and cooldown; benchmarks table per task type; NotebookLM artifact counts; sync status per course (synced / stale / deferred / failed / links); weakest 10 concepts with retention confidence. Inline SVG bar charts, dark-mode aware.
**Acceptance:** renders from a seeded DB in a test (HTML contains expected numbers); opens without errors in a headless Chromium via Playwright.

### BL-038 Retention decay job
**Build:** `brightlearn maintain` runs `decay_retention(now)` (half-life from config, default 21 days, only on concepts with no evidence since), archives sessions older than 30 days into `vault/sessions/archive/`, and prints what changed. Every other CLI command calls it if it hasn't run in 24 h.
**Acceptance:** decay halves retention at exactly one half-life; a concept with fresh evidence is untouched; auto-run guard respects the 24 h window.

### BL-039 Claude and Codex parser fixes
**Blocked until Simon pastes the real CLI outputs.** When they arrive: fix `ClaudeCodeProvider` JSON parsing and `CodexProvider` output/allowance parsing against the real text; save the pasted outputs as `tests/fixtures/cli/claude_hi.json`, `codex_help.txt`, `codex_hi.txt`; tests use them.

---

## Still not ticketed
Zoom `Link` topics · concept extraction with a model instead of keywords (Context Compiler intent v1) · export of an exam to PDF · Drive return via `StorageBackend` · API-key `ModelProvider` for a future multi-user build.
