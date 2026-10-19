// Grading rules the Studio card and the take view share, so they never disagree about an attempt.
import { isActive, type Job } from "@/api/jobs"
import type { Attempt } from "@/api/queries.studio"

/** Every answer graded (skips are never graded, so an attempt of skips only has nothing left to grade). */
export function fullyGraded(attempt: Attempt): boolean {
  return attempt.answered === 0 || attempt.graded >= attempt.answered
}

/** True for a field of a free-form job result that equals `value`. */
function resultIs(job: Job, key: string, value: string | number): boolean {
  return job.result?.[key] === value
}

/**
 * The remembered grade job, if it belongs to the exam's latest attempt; otherwise undefined, so
 * attempt 2 never shows attempt 1's grade. A running job is shown; a finished one names its exam
 * and attempt in its result; a failed one has no result, so it counts if it was submitted after
 * the attempt was handed in.
 */
export function gradeJobFor(job: Job | undefined, examId: string, latest: Attempt | undefined): Job | undefined {
  if (!job) return undefined
  if (isActive(job)) return job
  if (!latest) return undefined
  if (job.status === "done") {
    return resultIs(job, "exam_id", examId) && resultIs(job, "attempt", latest.attempt) ? job : undefined
  }
  const handedIn = latest.finished_at ? Date.parse(latest.finished_at) : Number.NaN
  return Date.parse(job.created_at) >= handedIn ? job : undefined
}
