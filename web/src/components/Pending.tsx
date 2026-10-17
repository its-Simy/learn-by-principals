// Every wait in the app: a spinner, what is happening, and how long it has taken so far.
import { LoaderCircle } from "lucide-react"
import { useEffect, useState } from "react"

import { formatElapsed, secondsSince } from "@/lib/format"
import { cn } from "@/lib/utils"

type PendingProps = {
  /** What is happening, e.g. "Claude is answering". */
  label: string
  /** When the wait began (ISO timestamp or epoch ms); defaults to when this mounted. */
  since?: string | number
  /** Extra context after the time, e.g. "typically 5–15 minutes". */
  detail?: string
  className?: string
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}

export function Pending({ label, since, detail, className }: PendingProps) {
  const [mountedAt] = useState(Date.now)
  const now = useNow(1000)
  const elapsed = formatElapsed(secondsSince(since ?? mountedAt, now))
  return (
    <div role="status" aria-live="polite" className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-sm", className)}>
      <LoaderCircle aria-hidden="true" className="size-4 shrink-0 animate-spin text-pending" />
      <span>{label}</span>
      {/* The ticking time is hidden from screen readers so the live region announces the label once, not every second. */}
      <span aria-hidden="true" className="tabular-nums">
        · {elapsed}
      </span>
      {detail && <span>({detail})</span>}
    </div>
  )
}
