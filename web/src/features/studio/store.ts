// Studio state that must outlive the pane: collapsing the rail, closing its sheet or crossing `lg`
// unmounts it, and an open editor, its unsaved text or the job a card started shouldn't go with
// it. Kept per tab in memory; a reload starts the pane afresh (the server holds what matters).
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useSyncExternalStore } from "react"

import { ApiError } from "@/api/client"
import { fetchJobs, isActive, keys, POLL_MS, useJob, type Job, type JobKind } from "@/api/jobs"

/** The attribute on the control that opens a Studio view, so Back returns the focus to it. */
export const OPENER = "data-studio-opener"

/** Spread onto the control that opens `view` ("new-exam", "draft:{name}"). */
export function openerProps(view: string): Record<typeof OPENER, string> {
  return { [OPENER]: view }
}

const values = new Map<string, unknown>()
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Like useState, but keyed and kept outside React. `initial` must be a primitive or a constant. */
export function useStudioState<T>(key: string, initial: T): [T, (next: T) => void] {
  const value = useSyncExternalStore(subscribe, () => (values.has(key) ? (values.get(key) as T) : initial))
  const set = useCallback((next: T) => {
    values.set(key, next)
    for (const listener of listeners) listener()
  }, [key])
  return [value, set]
}

const sameCourse = (a: string, b: string) => a.toUpperCase() === b.toUpperCase()

/**
 * The job a card shows in its JobRow: the one it started, remembered while the rail is closed,
 * or else, given `kind`, one of that kind already queued or running on the course (started in
 * another tab, or before a reload). `start` records a job the card just submitted.
 */
export function useCardJob(course: string, slot: string, kind?: JobKind): [Job | undefined, (job: Job) => void] {
  const queryClient = useQueryClient()
  const [startedId, setStartedId] = useStudioState<string | null>(`${course.toUpperCase()}:job:${slot}`, null)
  // The watcher's query, read here: it keeps the list fresh while any job runs.
  const { data: jobs } = useQuery({
    queryKey: keys.jobs(),
    queryFn: fetchJobs,
    staleTime: POLL_MS,
  })
  const running = kind ? jobs?.find((j) => j.kind === kind && sameCourse(j.course, course) && isActive(j)) : undefined
  const id = running?.id ?? startedId ?? undefined
  const { data: job } = useJob(id, jobs?.find((j) => j.id === id))
  const start = useCallback(
    (submitted: Job) => {
      queryClient.setQueryData(keys.job(submitted.id), submitted)
      setStartedId(submitted.id)
    },
    [queryClient, setStartedId],
  )
  return [job, start]
}

/** A 422's message (the parser's or the checker's), shown inline under what was edited. */
export function isUnprocessable(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 422
}
