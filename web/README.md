# BrightLearn web

The local web app (Sources | Chat | Studio) over the BrightLearn API. Vite, React 19, TypeScript strict, Tailwind v4 and shadcn/ui.

Run everything from the repo root with `pnpm --dir web <script>`, or from `web/` with `pnpm <script>`.

- **Install:** `pnpm --dir web install`
- **Dev:** start the API with `brightlearn web --no-open` (it listens on 127.0.0.1:8765), then `pnpm --dir web dev`. Vite serves the app with hot reload and forwards `/api` to 8765.
- **Build:** `pnpm --dir web build` type-checks and writes `web/dist/`, which `brightlearn web` serves on its own, so no Node is needed at run time.
- **Typecheck:** `pnpm --dir web typecheck` checks the app and `vite.config.ts`.
- **Gen:** `pnpm --dir web gen` regenerates `src/api/types.ts` from `web/openapi.json`, the pinned API contract. Whenever a route or schema changes, run `brightlearn dev openapi --out web/openapi.json`, then `gen`, and commit both. `tests/test_api_openapi.py` fails until `web/openapi.json` matches the app.

Run `typecheck` and `build` before committing a web change.

## Developing without NotebookLM or the model CLIs

`scripts/dev_server.py` serves the same API on the test fakes (`tests/fakes/`), against a scratch home of its own, so every pane works with no accounts and no quota:

```sh
uv run python scripts/dev_server.py --home /tmp/brightlearn-dev --port 8801
VITE_API_PORT=8801 pnpm --dir web dev            # macOS/Linux
$env:VITE_API_PORT = 8801; pnpm --dir web dev    # PowerShell
```

- `--home` (required) holds the database, course files, vault and temp dir; nothing under `~/.brightlearn` is read or written, and a home inside it is refused. Delete the folder to start over.
- The first start seeds CSE220 with three linked files (syllabus, a lecture, a homework), five concepts at mastery levels 0–4 and one pending Challenger probe on Pointers, plus provider health and a few ledger rows for `/system`. Later starts keep whatever the home holds.
- NotebookLM is an in-memory fake that links every upload, answers in Markdown citing up to two sources, and returns a concept list to a seed. Both models are fakes: a Markdown tutor answer, a Challenger probe, exam questions, an empty critique, grading, and an Analyzer that quotes the learner and proposes a two-level jump on the weakest concept, so every session that had a tutoring turn queues a probe for the next one (answering it upholds the jump; `/skip` defers it).
- `--delay` (seconds, default 1) slows every fake call, so pending rows and elapsed times can be seen.
- The fake refuses to link a file whose name contains `fail`, so a link job's failure, its warning and Retry can be seen.
- A tutor question that says "rate limit" gets a usage limit from both fake models, resetting 20 s later, so a turn's error bubble (the provider and the reset time) can be seen; until then every tutor turn has no provider left.
- `VITE_API_PORT` points the Vite proxy at the server's port; without it the proxy uses 8765, `brightlearn web`'s port.

## Conventions

- **API calls:** go through `api` in `src/api/client.ts`, typed by path and method from the generated `paths`. Wrap a call in `unwrap(...)` inside a `queryFn` or `mutationFn`: it returns the data or throws an `ApiError` with the `status` and the parsed `body`. Every 409 body carries a `code` (`session_open`, `job_running`, ...) to act on in place, and so does a 422 the UI handles by kind (`nothing_linked`, `invalid_course_code`, `invalid_term`). Read them with `errorCode`, `conflictCode` (409s only) and `blockingJob` (the `job_id` of a 409 `job_running`) from `client.ts`, never by matching `detail`.
- **Query keys:** key every query with the `keys` factory in `src/api/jobs.ts` (`keys.sources(course)`, `keys.drafts(course)`, ...), extending it for sub-resources (`[...keys.drafts(course), name]`). A finished job refreshes exactly those keys, so a query keyed any other way is never refreshed.
- **Jobs:** `useJobsWatcher` (mounted once in the app layout) does the refresh and the toast for every finished job. After a submit route returns its job, call `trackJob(queryClient, job)`. `useJob(id)` only feeds an inline `JobRow`.
- **Cross-pane state:** collapsing a `Rail`, closing its sheet, or resizing across `lg` unmounts the rail's children. Source selection and any other state that must survive that, or that another pane reads, lives in `CoursePage` state and is passed down, never inside a rail's children. The chat area between the rails is a route outlet (the chat, or an exam's take view at `/courses/:course/exams/:id/take`), so it gets that state through the outlet context, and the rails stay mounted while a view replaces the chat. A pane's own state that only it reads (an open editor and its unsaved text, the job a view started) may instead live in a module-level store keyed by course, as `features/studio/store.ts` does.
- **`cn`:** import it from `@/lib/utils`. `shadcn add` writes `import { cn } from "cn"` in new `ui/` files; switch those to `@/lib/utils`.
