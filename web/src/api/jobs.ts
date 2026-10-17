// Long-running jobs (link, seed, exams, podcasts): the Job shape, query keys, the app-wide watcher and inline polling.
import { useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { toast } from "sonner"

export type JobKind = "link" | "seed" | "exam_create" | "exam_grade" | "podcast"
export type JobStatus = "queued" | "running" | "done" | "failed"

// TODO(BL-047 part 2): replace with the generated JobOut schema from src/api/types.ts.
export type Job = {
  id: string
  kind: JobKind
  course: string
  status: JobStatus
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  result?: Record<string, unknown> | null
  error?: string | null
}

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

// Result fields are read defensively until the generated types pin them (BL-047 part 2).
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

// TODO(BL-047 part 2): once /api/jobs and /api/jobs/{id} are in the generated types, these become
//   api.GET("/api/jobs") and api.GET("/api/jobs/{id}", { params: { path: { id } } })
async function fetchJobs(): Promise<Job[]> {
  throw new Error("GET /api/jobs is not wired yet (BL-047 part 2)")
}

async function fetchJob(id: string): Promise<Job> {
  throw new Error(`GET /api/jobs/${id} is not wired yet (BL-047 part 2)`)
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
