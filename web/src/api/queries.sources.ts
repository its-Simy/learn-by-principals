// Sources: a course's stored files, uploads, and the link job that sends them to NotebookLM.
import { hashKey, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { useCallback, useSyncExternalStore } from "react"

import { api, ApiError, unwrap } from "@/api/client"
import { fetchJob, fetchJobs, isActive, keys, trackJob, type Job } from "@/api/jobs"
import type { components } from "@/api/types"

export type Source = components["schemas"]["SourceOut"]
export type UploadOut = components["schemas"]["UploadOut"]
type UploadBody = components["schemas"]["Body_upload_api_courses__course__sources_upload_post"]

// The multipart field names, checked against the contract: a renamed field fails typecheck.
const FIELD = { files: "files", bucket: "bucket" } as const satisfies { [K in keyof UploadBody]-?: K }

export function useSources(course: string) {
  return useQuery({
    queryKey: keys.sources(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/sources", { params: { path: { course } } })),
  })
}

/** `POST sources/link`: links whatever isn't linked yet; while a link job is active it returns that one. */
export function useRetryLink(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/courses/{course}/sources/link", { params: { path: { course } } })),
    onSuccess: (job) => trackJob(queryClient, job),
  })
}

/**
 * The course's link job to show, read from the watcher's list (which does the polling): the
 * active one (there is at most one per course), else the newest. Not by position: the server
 * lists oldest first, but `trackJob` puts a just-submitted job at the front.
 */
export function useLatestLinkJob(course: string): Job | undefined {
  const select = useCallback(
    (jobs: Job[]) => {
      const links = jobs.filter((j) => j.kind === "link" && j.course === course)
      const newest = (a: Job | undefined, b: Job) => (!a || b.created_at >= a.created_at ? b : a)
      return links.find(isActive) ?? links.reduce(newest, undefined)
    },
    [course],
  )
  return useQuery({ queryKey: keys.jobs(), queryFn: fetchJobs, select }).data
}

// -- uploads ---------------------------------------------------------------------------------

export type UploadPhase = "uploading" | "waiting" | "failed"

/** One drop or file pick: one multipart request with every file in it. */
export type UploadBatch = {
  id: number
  course: string
  files: File[]
  bucket: string | null
  phase: UploadPhase
  /** When this phase began (epoch ms), for the Pending rows' elapsed time. */
  since: number
  /** What the learner should know: why it waits, or why it failed. */
  note: string | null
  /** Set once the automatic retry after a 409 `job_running` has been used. */
  retried: boolean
}

// Batches live outside React: collapsing the Sources rail unmounts the pane, and an upload that
// is waiting to retry must not be dropped with it. One list per course, replaced on every change
// so useSyncExternalStore sees a new snapshot.
const NO_BATCHES: UploadBatch[] = []
const batches = new Map<string, UploadBatch[]>()
const listeners = new Set<() => void>()
let nextId = 1

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function update(course: string, change: (list: UploadBatch[]) => UploadBatch[]): void {
  batches.set(course, change(batches.get(course) ?? NO_BATCHES))
  for (const listener of listeners) listener()
}

function patch(batch: UploadBatch, changes: Partial<UploadBatch>): UploadBatch {
  const next = { ...batch, ...changes }
  update(batch.course, (list) => list.map((b) => (b.id === batch.id ? next : b)))
  return next
}

function remove(batch: UploadBatch): void {
  update(batch.course, (list) => list.filter((b) => b.id !== batch.id))
}

function send(batch: UploadBatch): Promise<UploadOut> {
  return unwrap(
    api.POST("/api/courses/{course}/sources/upload", {
      params: { path: { course: batch.course } },
      // The contract types the parts as strings; the browser sends the File objects themselves.
      body: { files: batch.files.map((f) => f.name), bucket: batch.bucket },
      bodySerializer: () => {
        const form = new FormData()
        for (const file of batch.files) form.append(FIELD.files, file, file.name)
        if (batch.bucket) form.append(FIELD.bucket, batch.bucket)
        return form
      },
    }),
  )
}

/** The link job a 409 `job_running` names, if that is what this error is. */
function blockingJob(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.body as { code?: unknown; job_id?: unknown } | null
  return body?.code === "job_running" && typeof body.job_id === "string" ? body.job_id : null
}

/**
 * Resolves once job `id` is no longer queued or running. It hands the job to the watcher
 * (`trackJob`), which polls it and toasts its end, and listens to the watcher's list rather than
 * polling a second time. A job the server no longer knows (a restart) counts as ended.
 */
async function jobEnded(queryClient: QueryClient, id: string): Promise<void> {
  let job: Job
  try {
    job = await fetchJob(id)
  } catch {
    return
  }
  if (!isActive(job)) return
  trackJob(queryClient, job)
  const ended = () => {
    const seen = queryClient.getQueryData<Job[]>(keys.jobs())?.find((j) => j.id === id)
    return seen === undefined || !isActive(seen)
  }
  if (ended()) return
  const jobsHash = hashKey(keys.jobs())
  await new Promise<void>((resolve) => {
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event.query.queryHash === jobsHash && ended()) {
        unsubscribe()
        resolve()
      }
    })
  })
}

function merge(rows: Source[] | undefined, imported: Source[]): Source[] {
  const fresh = new Map(imported.map((r) => [r.resource_id, r]))
  const kept = (rows ?? []).filter((r) => !fresh.has(r.resource_id))
  return [...kept, ...imported]
}

async function run(queryClient: QueryClient, batch: UploadBatch): Promise<void> {
  try {
    const out = await send(batch)
    // The rows show at once; the link job's end (via the watcher) refreshes them again as linked.
    queryClient.setQueryData<Source[]>(keys.sources(batch.course), (rows) => merge(rows, out.imported))
    trackJob(queryClient, out.job)
    void queryClient.invalidateQueries({ queryKey: keys.courses() })
    remove(batch)
  } catch (error) {
    const job = blockingJob(error)
    if (job === null || batch.retried) {
      const message = error instanceof Error ? error.message : String(error)
      patch(batch, { phase: "failed", since: Date.now(), note: message })
      // A 422 can come after some files were stored (a later name too long, say), with no link
      // job queued: refresh, so they show, with the bar's "Link now".
      void queryClient.invalidateQueries({ queryKey: keys.sources(batch.course) })
      void queryClient.invalidateQueries({ queryKey: keys.courses() })
      return
    }
    // A link job writes back the rows it read when it started, so the server refuses uploads
    // until it ends; wait for it and send the same files once more.
    batch = patch(batch, {
      phase: "waiting",
      since: Date.now(),
      retried: true,
      note: "NotebookLM is still linking earlier files. These upload as soon as it finishes.",
    })
    await jobEnded(queryClient, job)
    await run(queryClient, patch(batch, { phase: "uploading", since: Date.now(), note: null }))
  }
}

/**
 * Upload batches for one course, and `upload(files, bucket)`, which sends them as one request.
 * A 409 `job_running` waits for that link job and retries once by itself; a second refusal, or
 * any other error, leaves the batch `failed` with the reason, for `retry` or `dismiss`.
 */
export function useUpload(course: string) {
  const queryClient = useQueryClient()
  const list = useSyncExternalStore(subscribe, () => batches.get(course) ?? NO_BATCHES)
  const upload = useCallback(
    (files: File[], bucket: string | null) => {
      if (files.length === 0) return
      const batch: UploadBatch = {
        id: nextId++,
        course,
        files,
        bucket,
        phase: "uploading",
        since: Date.now(),
        note: null,
        retried: false,
      }
      update(course, (current) => [...current, batch])
      void run(queryClient, batch)
    },
    [course, queryClient],
  )
  const retry = useCallback(
    (batch: UploadBatch) =>
      void run(queryClient, patch(batch, { phase: "uploading", since: Date.now(), note: null, retried: false })),
    [queryClient],
  )
  return { batches: list, upload, retry, dismiss: remove }
}
