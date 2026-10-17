// The one typed client for the BrightLearn API: every call is checked against `paths` by path and method.
import createClient from "openapi-fetch"

import type { paths } from "@/api/types"

// Same origin: `brightlearn web` serves the app and /api together; in dev, Vite proxies /api to 8765.
export const api = createClient<paths>({ baseUrl: "" })

/**
 * A non-2xx answer. `body` is the parsed error body: every error carries `detail`, and every 409 a
 * `code` too (`session_open`, `job_running`, ...), with the fields that code names in the contract.
 * So does a 422 the UI acts on by kind (`nothing_linked`, `invalid_course_code`, `invalid_term`).
 */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(errorMessage(status, body))
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

// Our own errors send `detail` as a sentence; FastAPI's request validation sends a list of `{msg}`.
function errorMessage(status: number, body: unknown): string {
  const detail = bodyField(body, "detail")
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((d: { msg?: unknown }) => d?.msg).filter((m) => typeof m === "string")
    if (messages.length) return messages.join("; ")
  }
  return `The server answered ${status}`
}

/** One field of an error body (`session_id`, `job_id`, ...), unchecked; undefined when it has none. */
export function bodyField(body: unknown, key: string): unknown {
  return typeof body === "object" && body !== null && key in body ? (body as Record<string, unknown>)[key] : undefined
}

/** The `code` of an error body, whatever its status; null when it carries none (or isn't an ApiError). */
export function errorCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  const code = bodyField(error.body, "code")
  return typeof code === "string" ? code : null
}

/** The `code` of a 409 body (`job_running`, `ask_running`, ...); null for any other error. */
export function conflictCode(error: unknown): string | null {
  return error instanceof ApiError && error.status === 409 ? errorCode(error) : null
}

/** The job a 409 `job_running` names by its `job_id`; null for any other error. */
export function blockingJob(error: unknown): string | null {
  if (!(error instanceof ApiError) || conflictCode(error) !== "job_running") return null
  const id = bodyField(error.body, "job_id")
  return typeof id === "string" ? id : null
}

/** A call's data, or its ApiError thrown: what a react-query `queryFn` or `mutationFn` wants. */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw new ApiError(response.status, error)
  return data as T
}
