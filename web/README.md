# BrightLearn web

The local web app (Sources | Chat | Studio) over the BrightLearn API. Vite, React 19, TypeScript strict, Tailwind v4 and shadcn/ui.

Run everything from the repo root with `pnpm --dir web <script>`, or from `web/` with `pnpm <script>`.

- **Install:** `pnpm --dir web install`
- **Dev:** start the API with `brightlearn web --no-open` (it listens on 127.0.0.1:8765), then `pnpm --dir web dev`. Vite serves the app with hot reload and forwards `/api` to 8765.
- **Build:** `pnpm --dir web build` type-checks and writes `web/dist/`, which `brightlearn web` serves on its own, so no Node is needed at run time.
- **Typecheck:** `pnpm --dir web typecheck` checks the app and `vite.config.ts`.
- **Gen:** `pnpm --dir web gen` regenerates `src/api/types.ts` from `web/openapi.json`, the pinned API contract. Whenever a route or schema changes, run `brightlearn dev openapi > web/openapi.json`, then `gen`, and commit both. `tests/test_api_openapi.py` fails until `web/openapi.json` matches the app.

Run `typecheck` and `build` before committing a web change.

## Conventions

- **API calls:** go through `api` in `src/api/client.ts`, typed by path and method from the generated `paths`. Wrap a call in `unwrap(...)` inside a `queryFn` or `mutationFn`: it returns the data or throws an `ApiError` with the `status` and the parsed `body`. Every 409 body carries a `code` (`session_open`, `job_running`, ...) to act on in place.
- **Query keys:** key every query with the `keys` factory in `src/api/jobs.ts` (`keys.sources(course)`, `keys.drafts(course)`, ...), extending it for sub-resources (`[...keys.drafts(course), name]`). A finished job refreshes exactly those keys, so a query keyed any other way is never refreshed.
- **Jobs:** `useJobsWatcher` (mounted once in the app layout) does the refresh and the toast for every finished job. After a submit route returns its job, call `trackJob(queryClient, job)`. `useJob(id)` only feeds an inline `JobRow`.
- **Cross-pane state:** collapsing a `Rail`, closing its sheet, or resizing across `lg` unmounts the rail's children. Source selection and any other state that must survive that, or that another pane reads, lives in `CoursePage` state and is passed down, never inside a rail's children.
- **`cn`:** import it from `@/lib/utils`. `shadcn add` writes `import { cn } from "cn"` in new `ui/` files; switch those to `@/lib/utils`.
