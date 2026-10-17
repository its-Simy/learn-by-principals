// Doctor checks and the usage dashboard: what `brightlearn doctor` and `brightlearn dashboard` show.
import { RefreshCw } from "lucide-react"
import type { ReactNode } from "react"

import { useDashboard, useDoctor, type Dashboard } from "@/api/queries.system"
import { EmptyState } from "@/components/EmptyState"
import { LevelBar } from "@/components/LevelBar"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { formatClock, humanize } from "@/lib/format"
import { cn } from "@/lib/utils"

function Section({
  title,
  description,
  action,
  className,
  children,
}: {
  title: string
  description?: string
  action?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <Card className={cn("gap-4 py-5 shadow-none", className)}>
      <CardHeader className="px-5">
        <CardTitle className="text-base">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className="px-5">{children}</CardContent>
    </Card>
  )
}

/** A table that scrolls sideways on a phone rather than widening the page. */
function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            {head.map((h, i) => (
              <th key={i} scope="col" className="py-2 pr-4 font-medium whitespace-nowrap last:pr-0">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_td]:py-2 [&_td]:pr-4 [&_td]:align-top [&_td:last-child]:pr-0 [&_tr]:border-b [&_tr:last-child]:border-0">
          {children}
        </tbody>
      </table>
    </div>
  )
}

function Empty({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

const dash = "–"

/** A clock time today, with the date on any other day: "14:05", "Oct 15, 14:05". */
function when(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  if (date.toDateString() === now.toDateString()) return formatClock(iso)
  const day = date.toLocaleDateString([], { month: "short", day: "numeric" })
  return `${day}, ${formatClock(iso)}`
}

function seconds(ms: number | null): string {
  return ms === null ? dash : `${(ms / 1000).toFixed(1)} s`
}

function decimal(value: number | null, digits = 2): string {
  return value === null ? dash : value.toFixed(digits)
}

function percent(value: number | null): string {
  return value === null ? dash : `${Math.round(value * 100)}%`
}

/** A 0–1 score as a bar plus its value, the LevelBar look for continuous numbers. */
function ScoreBar({ value, label }: { value: number | null; label: string }) {
  if (value === null) return <span className="text-muted-foreground">{dash}</span>
  const clamped = Math.min(1, Math.max(0, value))
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={clamped} className="flex items-center gap-2">
      <span aria-hidden="true" className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
        <span className="block h-full rounded-full bg-foreground/80" style={{ width: `${clamped * 100}%` }} />
      </span>
      <span className="text-xs tabular-nums text-muted-foreground">{clamped.toFixed(2)}</span>
    </div>
  )
}

function DoctorTable() {
  const doctor = useDoctor()
  const rerun = (
    <Button variant="outline" size="sm" disabled={doctor.isFetching} onClick={() => void doctor.refetch()}>
      <RefreshCw className={cn(doctor.isFetching && "animate-spin")} />
      Re-run
    </Button>
  )
  return (
    <Section title="Doctor" description="Read-only checks: nothing here spends quota." action={rerun}>
      {doctor.isPending ? (
        <Pending label="Running checks" />
      ) : doctor.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {doctor.error.message}
        </p>
      ) : (
        <Table head={["Check", "Status", "Detail"]}>
          {doctor.data.map((check) => (
            <tr key={check.name}>
              <td className="font-medium whitespace-nowrap">{check.name}</td>
              <td>
                <StateBadge state={check.status} />
              </td>
              <td className="min-w-48 break-words text-muted-foreground">{check.detail}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

type ProviderRuns = Dashboard["today"][number]

function RunsTable({ caption, runs }: { caption: string; runs: ProviderRuns[] }) {
  return (
    <div>
      <h3 className="text-xs font-medium text-muted-foreground">{caption}</h3>
      {runs.length === 0 ? (
        <p className="py-2 text-sm text-muted-foreground">No runs.</p>
      ) : (
        <Table head={["Provider", "Calls", "Failures", "Median", "Fallbacks"]}>
          {runs.map((r) => (
            <tr key={r.provider} className="tabular-nums">
              <td className="font-medium">{r.provider}</td>
              <td>{r.calls}</td>
              <td>{r.failures}</td>
              <td className="whitespace-nowrap">{seconds(r.median_ms)}</td>
              <td>{r.fallbacks}</td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  )
}

function Runs({ data }: { data: Dashboard }) {
  return (
    <Section title="Model runs" description="From the ledger, per provider.">
      {data.week.length === 0 ? (
        <Empty>No model runs in the last 7 days.</Empty>
      ) : (
        <div className="flex flex-col gap-4">
          <RunsTable caption="Today" runs={data.today} />
          <RunsTable caption="Last 7 days" runs={data.week} />
        </div>
      )}
    </Section>
  )
}

function Health({ data }: { data: Dashboard }) {
  return (
    <Section title="Provider health" description="What the router last saw; a rate limit says when it lifts.">
      {data.health.length === 0 ? (
        <Empty>No provider has been checked yet.</Empty>
      ) : (
        <Table head={["Provider", "State", "Resets", "Checked", "Detail"]}>
          {data.health.map((h) => (
            <tr key={h.provider}>
              <td className="font-medium">{h.provider}</td>
              <td>
                <StateBadge state={h.state} />
              </td>
              <td className="whitespace-nowrap tabular-nums">{h.cooldown_until ? when(h.cooldown_until) : dash}</td>
              <td className="whitespace-nowrap tabular-nums">{when(h.checked_at)}</td>
              <td className="min-w-40 break-words text-muted-foreground">{h.detail ?? dash}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

function BenchmarksSection({ data }: { data: Dashboard }) {
  return (
    <Section title="Benchmarks" description="Measured per provider and task; routing reorders by score after 10 runs.">
      {data.benchmarks.length === 0 ? (
        <Empty>No benchmark samples yet.</Empty>
      ) : (
        <Table head={["Provider", "Task", "Score", "Accuracy", "Grounded", "Format", "Latency", "Rating", "Runs"]}>
          {data.benchmarks.map((b) => (
            <tr key={`${b.provider}-${b.task_type}`} className="tabular-nums">
              <td className="font-medium">{b.provider}</td>
              <td className="whitespace-nowrap">{humanize(b.task_type)}</td>
              <td>
                <ScoreBar value={b.score} label={`${b.provider} ${humanize(b.task_type)} score`} />
              </td>
              <td>{decimal(b.accuracy)}</td>
              <td>{decimal(b.groundedness)}</td>
              <td>{decimal(b.format_compliance)}</td>
              <td className="whitespace-nowrap">{seconds(b.latency_ms)}</td>
              <td>{b.learner_rating === null ? dash : `${b.learner_rating.toFixed(1)}/5`}</td>
              <td>{b.sample_count}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

function Artifacts({ data }: { data: Dashboard }) {
  const labels = Object.keys(data.artifacts_total)
  return (
    <Section title="NotebookLM artifacts" description={`${data.podcasts} audio overview${data.podcasts === 1 ? "" : "s"} saved.`}>
      <Table head={["Kind", "7 days", "Total"]}>
        {labels.map((label) => (
          <tr key={label} className="tabular-nums">
            <td>{label}</td>
            <td>{data.artifacts_week[label] ?? 0}</td>
            <td>{data.artifacts_total[label] ?? 0}</td>
          </tr>
        ))}
      </Table>
    </Section>
  )
}

// sync_state counts: `synced` means stored (the Sources pane shows which are in NotebookLM).
const SYNC_COLUMNS = [
  ["synced", "Stored"],
  ["stale", "Changed"],
  ["failed", "Failed"],
  ["deferred", "Deferred"],
  ["link", "Links"],
] as const

function Sync({ data }: { data: Dashboard }) {
  const courses = Object.keys(data.sync).sort()
  return (
    <Section title="Course files" description="Files per sync state; a changed file is re-sent on the next link.">
      {courses.length === 0 ? (
        <Empty>No course files yet.</Empty>
      ) : (
        <Table head={["Course", ...SYNC_COLUMNS.map(([, label]) => label)]}>
          {courses.map((course) => (
            <tr key={course} className="tabular-nums">
              <td className="font-medium">{course}</td>
              {SYNC_COLUMNS.map(([state]) => (
                <td key={state}>{data.sync[course]?.[state] ?? 0}</td>
              ))}
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

function Weakest({ data }: { data: Dashboard }) {
  return (
    <Section title="Weakest concepts" description="Lowest mastery first, across every course.">
      {data.weakest.length === 0 ? (
        <Empty>No concepts yet: seed them from a course's Studio.</Empty>
      ) : (
        <Table head={["Concept", "Course", "Level", "Confidence", "Retention"]}>
          {data.weakest.map((c) => (
            <tr key={`${c.course}-${c.name}`}>
              <td className="min-w-32">{c.name}</td>
              <td>{c.course}</td>
              <td>
                <LevelBar level={c.level} label={`${c.name} mastery`} />
              </td>
              <td className="tabular-nums">{percent(c.confidence)}</td>
              <td className="tabular-nums">{percent(c.retention)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

function DashboardSections() {
  const dashboard = useDashboard()
  if (dashboard.isPending) {
    return (
      <div className="grid gap-6 lg:grid-cols-2" aria-label="Loading the dashboard">
        {[0, 1, 2, 3].map((n) => (
          <Skeleton key={n} className="h-40 rounded-xl" />
        ))}
      </div>
    )
  }
  if (dashboard.isError) {
    return (
      <div className="rounded-xl border bg-card">
        <EmptyState
          message={dashboard.error.message}
          action={
            <Button variant="outline" size="sm" onClick={() => void dashboard.refetch()}>
              Try again
            </Button>
          }
        />
      </div>
    )
  }
  const data = dashboard.data
  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold">Dashboard</h2>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="tabular-nums">Updated {formatClock(data.generated_at)}</span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Refresh the dashboard"
            disabled={dashboard.isFetching}
            onClick={() => void dashboard.refetch()}
          >
            <RefreshCw className={cn(dashboard.isFetching && "animate-spin")} />
          </Button>
        </div>
      </div>
      <Health data={data} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Runs data={data} />
        <Artifacts data={data} />
      </div>
      <BenchmarksSection data={data} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Sync data={data} />
        <Weakest data={data} />
      </div>
    </>
  )
}

export function SystemPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8">
        <h1 className="text-xl font-semibold">System</h1>
        <DoctorTable />
        <DashboardSections />
      </div>
    </div>
  )
}
