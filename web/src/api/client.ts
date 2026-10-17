// The one typed client for the BrightLearn API: every call is checked against `paths` by path and method.
import createClient from "openapi-fetch"

import type { paths } from "@/api/types"

// Same origin: `brightlearn web` serves the app and /api together; in dev, Vite proxies /api to 8765.
export const api = createClient<paths>({ baseUrl: "" })

/**
 * A non-2xx answer. `body` is the parsed error body: every error carries `detail`, and every 409 a
 * `code` too (`session_open`, `job_running`, ...), with the fields that code names in the contract.
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
  const detail = typeof body === "object" && body !== null && "detail" in body ? body.detail : undefined
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((d: { msg?: unknown }) => d?.msg).filter((m) => typeof m === "string")
    if (messages.length) return messages.join("; ")
  }
  return `The server answered ${status}`
}

/** A call's data, or its ApiError thrown: what a react-query `queryFn` or `mutationFn` wants. */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw new ApiError(response.status, error)
  return data as T
}
