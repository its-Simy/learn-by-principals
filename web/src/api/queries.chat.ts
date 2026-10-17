// Chat hooks (BL-048): the live tutor session, grounded asks and a course's past sessions.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"

import { api, ApiError, unwrap } from "@/api/client"
import { JOB_LABELS, keys, type JobKind } from "@/api/jobs"
import type { components } from "@/api/types"

type Schemas = components["schemas"]
export type LiveSession = Schemas["LiveSessionOut"]
export type TurnResult = Schemas["TurnOut"]
export type AskResult = Schemas["AskOut"]
export type Citation = Schemas["CitationOut"]
export type Probe = Schemas["ProbeOut"]
export type PastSession = Schemas["SessionOut"]
export type Persona = Schemas["PersonaOut"]

const onCourse = (course: string) => ({ params: { path: { course } } })
const onSession = (id: string) => ({ params: { path: { session_id: id } } })

/** A session started, ended or closed: the course's session list and the course cards' `open_session_id`. */
function sessionsChanged(queryClient: QueryClient, course: string): void {
  void queryClient.invalidateQueries({ queryKey: keys.sessions(course) })
  void queryClient.invalidateQueries({ queryKey: keys.courses() })
}

/** The live session this server holds for the course, or null. Turns, start and end keep it current. */
export function useLiveSession(course: string) {
  return useQuery({
    queryKey: keys.session(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/session", onCourse(course))),
  })
}

export function useStartSession(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (persona: string) =>
      unwrap(api.POST("/api/courses/{course}/session", { ...onCourse(course), body: { persona } })),
    onSuccess: (live) => queryClient.setQueryData(keys.session(course), live),
    onSettled: () => sessionsChanged(queryClient, course),
  })
}

/** One REPL line: plain text, `/persona x`, `/rate n`, `/skip`, `/ask q`, `/end`. */
export function useTurn(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(api.POST("/api/courses/{course}/session/turn", { ...onCourse(course), body: { text } })),
    onSuccess: (out) => {
      queryClient.setQueryData<LiveSession | null>(keys.session(course), (live) =>
        out.ended || !live ? null : { ...live, persona: out.persona, probe: out.probe, ratable: out.ratable },
      )
      if (out.ended) sessionsChanged(queryClient, course)
    },
    // A 404 means the server no longer holds the tutor (a restart): learn what it does hold.
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        void queryClient.invalidateQueries({ queryKey: keys.session(course) })
      }
    },
  })
}

/** Ends the session and runs the Analyzer on its transcript: minutes, not seconds. */
export function useEndSession(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/courses/{course}/session/end", onCourse(course))),
    onSuccess: () => queryClient.setQueryData(keys.session(course), null),
    // A failed Analyzer can still have ended the session; ask the server either way.
    onError: () => queryClient.invalidateQueries({ queryKey: keys.session(course) }),
    onSettled: () => sessionsChanged(queryClient, course),
  })
}

/**
 * A grounded question. Without a live session it asks `sourceIds` (NotebookLM source ids; none
 * means every source) in a fresh conversation. Inside one the server asks every source in the
 * session's own conversation and refuses `source_ids`, so callers send none then. An empty list
 * is never sent: the server reads `[]` as a scope naming nothing.
 */
export function useAsk(course: string) {
  return useMutation({
    mutationFn: ({ question, sourceIds }: { question: string; sourceIds?: string[] }) =>
      unwrap(
        api.POST("/api/courses/{course}/ask", {
          ...onCourse(course),
          body: sourceIds?.length ? { question, source_ids: sourceIds } : { question },
        }),
      ),
  })
}

/** Past and open sessions on the course, newest first; fetched only while `enabled`. */
export function useSessions(course: string, enabled = true) {
  return useQuery({
    queryKey: keys.sessions(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/sessions", onCourse(course))),
    enabled,
  })
}

/** A session's Markdown transcript, keyed under the course's sessions so refreshing those refreshes it. */
export function useTranscript(course: string, id: string | null) {
  return useQuery({
    queryKey: [...keys.sessions(course), id, "transcript"],
    queryFn: () => unwrap(api.GET("/api/sessions/{session_id}/transcript", onSession(id ?? ""))),
    enabled: id !== null,
    // A session without a transcript file (one opened elsewhere and closed) is a 404 that a retry won't fix.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 1,
  })
}

/** Marks a session ended without the Analyzer: for one whose tutor is gone. */
export function useCloseSession(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/sessions/{session_id}/close", onSession(id))),
    onSettled: () => sessionsChanged(queryClient, course),
  })
}

/** The teaching personas a session can start with (or switch to). */
export function useTeachingPersonas() {
  return useQuery({
    queryKey: keys.personas(),
    queryFn: () => unwrap(api.GET("/api/personas")),
    select: (personas) => personas.filter((p) => p.group === "teaching"),
    staleTime: Infinity,
  })
}

// -- failures ----------------------------------------------------------------------------------

/** A failed chat request, read from the ApiError body so the pane can offer the way out in place. */
export type Failure =
  | { kind: "session_open"; detail: string; sessionId: string; stale: boolean }
  | { kind: "job_running"; detail: string; job: JobKind | null }
  | { kind: "conflict"; detail: string; code: string | null }
  | { kind: "nothing_linked"; detail: string }
  | { kind: "upstream"; detail: string; provider: string | null; resetsAt: string | null }
  /** A turn or end answered 404: this server no longer holds the tutor (it was restarted). */
  | { kind: "session_gone"; detail: string }
  | { kind: "other"; detail: string; status: number | null }

function field(body: unknown, key: string): unknown {
  return typeof body === "object" && body !== null && key in body ? (body as Record<string, unknown>)[key] : undefined
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function isJobKind(kind: string): kind is JobKind {
  return Object.hasOwn(JOB_LABELS, kind)
}

// WORKAROUND until the 422 carries `code: "nothing_linked"`: then drop this sentence match (api/routes/chat.py).
const NOTHING_LINKED = /is in NotebookLM yet/

export function failureOf(error: unknown): Failure {
  if (!(error instanceof ApiError)) {
    const detail = error instanceof Error ? error.message : String(error)
    return { kind: "other", detail: `The request didn't reach the server: ${detail}`, status: null }
  }
  const { status, body, message: detail } = error
  const code = text(field(body, "code"))
  if (status === 409) {
    if (code === "session_open") {
      return {
        kind: "session_open",
        detail,
        sessionId: text(field(body, "session_id")) ?? "",
        stale: field(body, "stale") === true,
      }
    }
    if (code === "job_running") {
      const kind = text(field(body, "kind"))
      return { kind: "job_running", detail, job: kind !== null && isJobKind(kind) ? kind : null }
    }
    return { kind: "conflict", detail, code }
  }
  if (status === 422 && (code === "nothing_linked" || NOTHING_LINKED.test(detail))) {
    return { kind: "nothing_linked", detail }
  }
  if (status === 502) {
    return {
      kind: "upstream",
      detail,
      provider: text(field(body, "provider")),
      resetsAt: text(field(body, "resets_at")),
    }
  }
  return { kind: "other", detail, status }
}
