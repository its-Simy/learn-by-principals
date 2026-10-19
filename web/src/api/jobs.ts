// Long-running jobs (link, seed, exams, podcasts): the Job shape, query keys, the app-wide watcher and inline polling.
import { useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { toast } from "sonner"

import { api, unwrap } from "@/api/client"
import type { components } from "@/api/types"

export type Job = components["schemas"]["JobOut"]
export type JobKind = Job["kind"]
export type JobStatus = Job["status"]

export const POLL_MS = 2000

/**
 * Every course-scoped query is keyed through here, so a finished job's invalidation always matches.
 * Sub-resources extend a key, e.g. `[...keys.drafts(course), name]`, and are refreshed with it.
 */
export const keys = {
  sources: (course: string) => ["sources", course] as const,
  drafts: (course: string) => ["drafts", course] as const,
  exams: (course: string) => ["exams", course] as const,
  concepts: (course: string) => ["concepts", course] as const,
  podcasts: (course: string) => ["podcasts", course] as const,
  jobs: (course?: string) => (course === undefined ? (["jobs"] as const) : (["jobs", course] as const)),
  job: (id: string) => ["job", id] as const,
  // Not course-scoped, so no job refreshes them: they refetch when their page mounts.
  courses: () => ["courses"] as const,
  dashboard: () => ["dashboard"] as const,
  doctor: () => ["doctor"] as const,
  health: () => ["health"] as const,
  // Studio (BL-049). Each extends the key of what writes it, so the job that changes it refreshes it.
  allConcepts: (course: string) => ["concepts", course, "with-retired"] as const,
  evidence: (course: string, conceptId: string) => ["concepts", course, "evidence", conceptId] as const,
  draft: (course: string, name: string) => ["drafts", course, name] as const,
  diff: (course: string, name: string) => ["drafts", course, name, "diff"] as const,
  template: (course: string) => ["exams", course, "template"] as const,
  exam: (course: string, id: string) => ["exams", course, id] as const,
  paper: (course: string, id: string) => ["exams", course, id, "markdown"] as const,
  take: (course: string, id: string) => ["exams", course, id, "take"] as const,
  results: (course: string, id: string) => ["exams", course, id, "results"] as const,
  brief: (course: string, podcastId: number) => ["podcasts", course, podcastId, "brief"] as const,
  session: (course: string) => ["session", course] as const,
  sessions: (course: string) => ["sessions", course] as const,
  personas: () => ["personas"] as const,
}

/** What each kind's job writes, refreshed for the job's course when it finishes. */
export const INVALIDATES: Record<JobKind, readonly ((course: string) => QueryKey)[]> = {
  link: [keys.sources],
  seed: [keys.drafts],
  exam_create: [keys.exams],
  exam_grade: [keys.exams, keys.concepts],
  podcast: [keys.podcasts],
}

export const JOB_LABELS: Record<JobKind, string> = {
  link: "Linking sources",
  seed: "Seeding concepts",
  exam_create: "Generating exam",
  exam_grade: "Grading exam",
  podcast: "Generating audio overview",
}

export function isActive(job: Job | undefined): boolean {
  return job?.status === "queued" || job?.status === "running"
}

// A job's result is a free-form object in the contract (`dict[str, Any]`, one shape per kind), so its fields are read defensively.
function count(result: Job["result"], key: string): number | null {
  const value = result?.[key]
  return typeof value === "number" ? value : null
}

/** A finished job's outcome: a done job that reports failures (a link job's `failed`) is a warning. */
export function jobOutcome(job: Job): "success" | "warning" | "failed" {
  if (job.status === "failed") return "failed"
  return (count(job.result, "failed") ?? 0) > 0 ? "warning" : "success"
}

function linkSummary(result: Job["result"]): string {
  const parts = (["added", "replaced", "deferred", "failed"] as const)
    .map((key) => [count(result, key) ?? 0, key === "added" ? "linked" : key] as const)
    .filter(([n]) => n > 0)
    .map(([n, word]) => `${n} ${word}`)
  return parts.length ? `Sources: ${parts.join(", ")}` : "Sources already up to date"
}

/** The one-line result or error shown in the toast and in the JobRow that started the job. */
export function jobSummary(job: Job): string {
  if (job.status === "failed") return `${JOB_LABELS[job.kind]} failed: ${job.error ?? "no error message"}`
  const r = job.result
  switch (job.kind) {
    case "link":
      return linkSummary(r)
    case "seed": {
      const n = count(r, "count")
      return n === null ? "Concept draft ready" : `Concept draft ready: ${n} concepts`
    }
    case "exam_create": {
      const n = count(r, "questions")
      return n === null ? "Exam ready" : `Exam ready: ${n} questions`
    }
    case "exam_grade": {
      const [correct, graded] = [count(r, "correct"), count(r, "graded")]
      return correct === null || graded === null ? "Exam graded" : `Graded: ${correct} of ${graded} correct`
    }
    case "podcast":
      return "Audio overview ready"
  }
}

export function fetchJobs(): Promise<Job[]> {
  return unwrap(api.GET("/api/jobs"))
}

export function fetchJob(id: string): Promise<Job> {
  return unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }))
}

/** Call with a submit route's job so the watcher sees it queued, even if it finishes before the next poll. */
export function trackJob(queryClient: QueryClient, job: Job): void {
  queryClient.setQueryData<Job[]>(keys.jobs(), (jobs = []) => [job, ...jobs.filter((j) => j.id !== job.id)])
}

function finish(queryClient: QueryClient, job: Job): void {
  // Refresh on failure too: a job can write some rows (a partly linked batch) before it fails.
  for (const key of INVALIDATES[job.kind]) void queryClient.invalidateQueries({ queryKey: key(job.course) })
  const notify = { success: toast.success, warning: toast.warning, failed: toast.error }[jobOutcome(job)]
  notify(jobSummary(job), { id: `job-${job.id}` })
}

const NO_JOBS: Job[] = []

/**
 * Mounted once, in the app layout: polls every job while any is queued or running and, when one
 * finishes, refreshes what it wrote and toasts its summary, once per job. It lives above the panes
 * because a collapsed rail or closed sheet unmounts its contents. A job first seen already finished
 * (an old one) is not announced. Returns the jobs for JobsIndicator.
 */
export function useJobsWatcher(): Job[] {
  const queryClient = useQueryClient()
  const { data: jobs = NO_JOBS } = useQuery({
    queryKey: keys.jobs(),
    queryFn: fetchJobs,
    refetchInterval: (q) => (q.state.data?.some(isActive) ? POLL_MS : false),
  })
  const seen = useRef(new Map<string, JobStatus>())

  useEffect(() => {
    for (const job of jobs) {
      const before = seen.current.get(job.id)
      seen.current.set(job.id, job.status)
      if ((before === "queued" || before === "running") && !isActive(job)) finish(queryClient, job)
    }
  }, [jobs, queryClient])

  return jobs
}

/**
 * One job for inline display (JobRow), polled every 2 s while queued or running. Display only:
 * refreshing and toasting belong to useJobsWatcher, which outlives any pane.
 */
export function useJob(id: string | null | undefined, initial?: Job) {
  return useQuery({
    queryKey: keys.job(id ?? ""),
    queryFn: () => fetchJob(id ?? ""),
    enabled: Boolean(id),
    initialData: initial && initial.id === id ? initial : undefined,
    refetchInterval: (q) => (isActive(q.state.data) ? POLL_MS : false),
  })
}
