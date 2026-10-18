// Studio state that must outlive the pane: collapsing the rail, closing its sheet or crossing `lg`
// unmounts it, and an open editor, its unsaved text or the job a view started shouldn't go with
// it. Kept per tab in memory; a reload starts the pane afresh (the server holds what matters).
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useSyncExternalStore } from "react"

import { ApiError } from "@/api/client"
import { fetchJobs, isActive, keys, POLL_MS, useJob, type Job, type JobKind } from "@/api/jobs"

/** The attribute on the control that opens a Studio view, so Back returns the focus to it. */
export const OPENER = "data-studio-opener"

/** Spread onto the control that opens `view`: a tile ("exams"), New exam ("exams:new"), a draft row. */
export function openerProps(view: string): Record<typeof OPENER, string> {
  return { [OPENER]: view }
}

/**
 * The Studio's views, kept per course in `useStudioState`: the home of tiles, one view per tool,
 * and the two editors nested under Practice exams and Concepts.
 */
export const HOME = "home"
export const MASTERY = "mastery"
export const EXAMS = "exams"
export const AUDIO = "audio"
export const CONCEPTS = "concepts"
export const NEW_EXAM = "exams:new"
const DRAFT = "concepts:draft:"

export function draftView(name: string): string {
  return `${DRAFT}${name}`
}

/** The draft a `concepts:draft:{name}` view edits, or null for any other view. */
export function draftOf(view: string): string | null {
  return view.startsWith(DRAFT) ? view.slice(DRAFT.length) : null
}

/** Where Back goes: an editor to its tool, a tool to home, home nowhere. */
export function parentView(view: string): string | null {
  if (view === HOME) return null
  if (view === NEW_EXAM) return EXAMS
  if (draftOf(view) !== null) return CONCEPTS
  return HOME
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

export const sameCourse = (a: string, b: string) => a.toUpperCase() === b.toUpperCase()

/**
 * The job a view shows in its JobRow: the one it started, remembered while the rail is closed,
 * or else, given `kind`, one of that kind already queued or running on the course (started in
 * another tab, or before a reload). `start` records a job the view just submitted.
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
