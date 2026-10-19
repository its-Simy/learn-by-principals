// The course's link job (stored files -> NotebookLM): running, its result, its failures, and Retry.
import { RotateCw } from "lucide-react"
import { useEffect, useReducer } from "react"

import { isActive, jobOutcome, type Job } from "@/api/jobs"
import { useRetryLink, type Source } from "@/api/queries.sources"
import { JobRow } from "@/components/JobRow"
import { Button } from "@/components/ui/button"
import { awaitsLink, failedSources, linkFailures } from "@/features/sources/status"

// A clean result stays in view this long after the job ends; a failure stays until it is retried.
const SHOW_DONE_MS = 5 * 60_000

/** Whether `iso` is less than `ms` ago; re-renders once when that stops being true. */
function useWithin(iso: string | null | undefined, ms: number): boolean {
  const [, expire] = useReducer((n: number) => n + 1, 0)
  const end = iso ? Date.parse(iso) + ms : Number.NaN
  useEffect(() => {
    const left = end - Date.now()
    if (!(left > 0)) return
    const timer = window.setTimeout(expire, left + 50)
    return () => window.clearTimeout(timer)
  }, [end])
  return end > Date.now()
}

type LinkJobBarProps = {
  course: string
  sources: Source[]
  /** The course's newest link job, if this server has run one. */
  job: Job | undefined
}

export function LinkJobBar({ course, sources, job }: LinkJobBarProps) {
  const retry = useRetryLink(course)
  const waiting = sources.filter(awaitsLink).length
  const active = isActive(job)
  const outcome = job && !active ? jobOutcome(job) : null
  const recent = useWithin(job?.finished_at, SHOW_DONE_MS)

  const retryButton = (label: string) => (
    <Button size="xs" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}>
      <RotateCw />
      {label}
    </Button>
  )
  const retryError = retry.isError && (
    <p role="alert" className="text-xs text-destructive">
      {retry.error.message}
    </p>
  )

  if (job && (active || outcome !== "success" || recent)) {
    // A file's failure starts with its resource id, which means nothing to the learner.
    const byFile = failedSources(job, sources)
    const other = linkFailures(job).filter((f) => !byFile.has(f.split(" ")[0]))
    const listed = [...byFile.values(), ...other]
    return (
      <div className="flex flex-col gap-2 rounded-xl border bg-card p-3">
        <JobRow
          job={job}
          label="Linking to NotebookLM"
          typical="a few seconds a file"
          action={outcome !== null && outcome !== "success" ? retryButton("Retry") : undefined}
        />
        {listed.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-xs break-words text-muted-foreground">
            {listed.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}
        {retryError}
      </div>
    )
  }

  // No job this server remembers (it restarted, or linking stopped early), but files still wait.
  if (waiting > 0) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border bg-card p-3">
        <div className="flex items-center gap-2 text-sm">
          <p className="min-w-0 flex-1">
            {waiting === 1 ? "1 file isn't" : `${waiting} files aren't`} in NotebookLM yet.
          </p>
          {retryButton("Link now")}
        </div>
        {retryError}
      </div>
    )
  }
  return null
}
