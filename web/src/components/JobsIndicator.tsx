// Top-bar count of running and queued jobs, with a popover listing the recent ones.
import { ListChecks, LoaderCircle } from "lucide-react"

import { isActive, JOB_LABELS, type Job } from "@/api/jobs"
import { useCourseName } from "@/api/queries.courses"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { formatElapsed, secondsSince } from "@/lib/format"

const RECENT = 8

function timing(job: Job): string {
  const start = job.started_at ?? job.created_at
  if (isActive(job) || !job.finished_at) return `${formatElapsed(secondsSince(start))} so far`
  return `took ${formatElapsed(secondsSince(start, Date.parse(job.finished_at)))}`
}

export function JobsIndicator({ jobs }: { jobs: Job[] }) {
  const active = jobs.filter(isActive).length
  const recent = [...jobs].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, RECENT)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={`Jobs: ${active} running or queued`}>
          {active > 0 ? <LoaderCircle className="animate-spin text-pending" /> : <ListChecks />}
          <span className="tabular-nums">{active}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <p className="border-b px-4 py-2 text-sm font-medium">Recent jobs</p>
        {recent.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">No jobs yet.</p>
        ) : (
          <ul className="max-h-80 divide-y overflow-y-auto">
            {recent.map((job) => (
              <RecentJob key={job.id} job={job} />
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}

function RecentJob({ job }: { job: Job }) {
  const course = useCourseName(job.course)
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm">{JOB_LABELS[job.kind]}</p>
        <p className="truncate text-xs text-muted-foreground">
          {course} · {timing(job)}
        </p>
      </div>
      <StateBadge state={job.status} />
    </li>
  )
}
