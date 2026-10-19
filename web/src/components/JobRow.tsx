// A job's status inside the card that started it: a Pending with the typical duration, then the result or error.
import { CircleAlert, CircleCheck, TriangleAlert } from "lucide-react"
import type { ReactNode } from "react"

import { isActive, JOB_LABELS, jobOutcome, jobSummary, type Job } from "@/api/jobs"
import { Pending } from "@/components/Pending"
import { cn } from "@/lib/utils"

const OUTCOME = {
  success: { Icon: CircleCheck, className: "text-success" },
  warning: { Icon: TriangleAlert, className: "text-warning" },
  failed: { Icon: CircleAlert, className: "text-destructive" },
} as const

type JobRowProps = {
  job: Job
  /** Defaults to the kind's label, e.g. "Generating audio overview". */
  label?: string
  /** How long this kind usually takes, e.g. "5–15 minutes". */
  typical?: string
  /** Rendered beside the row whenever given, e.g. Retry; the caller decides when it applies. */
  action?: ReactNode
  className?: string
}

export function JobRow({ job, label = JOB_LABELS[job.kind], typical, action, className }: JobRowProps) {
  if (isActive(job)) {
    return (
      <div className={cn("flex items-start gap-2", className)}>
        <Pending
          className="min-w-0 flex-1"
          label={job.status === "queued" ? `${label} (waiting for the job ahead)` : label}
          since={job.started_at ?? job.created_at}
          detail={typical ? `typically ${typical}` : undefined}
        />
        {action}
      </div>
    )
  }
  const outcome = jobOutcome(job)
  const { Icon, className: tone } = OUTCOME[outcome]
  return (
    <div role={outcome === "success" ? "status" : "alert"} className={cn("flex items-start gap-2 text-sm", className)}>
      <Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0", tone)} />
      <p className="min-w-0 flex-1 break-words">{jobSummary(job)}</p>
      {action}
    </div>
  )
}
