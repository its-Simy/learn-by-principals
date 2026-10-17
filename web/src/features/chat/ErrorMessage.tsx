// A failed request in the stream: who failed and why, with the way out in place (close the stale session, retry later, reload).
import { CircleAlert, Info, RefreshCw, RotateCcw } from "lucide-react"
import { useState, type ReactNode } from "react"

import { JOB_LABELS } from "@/api/jobs"
import type { Failure } from "@/api/queries.chat"
import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { formatWhen } from "@/lib/format"
import { cn } from "@/lib/utils"

import { providerName } from "./model"

type ErrorMessageProps = {
  failure: Failure
  /** Its way out was taken; the buttons go. */
  handled?: boolean
  /** "Try again" (or "Reload" for a session the server no longer holds) when the request can be repeated. */
  onRetry?: () => void
  /** For `session_open`: close that session, then repeat the request. */
  onCloseSession?: (sessionId: string) => void
  disabled: boolean
}

function Shell({ tone, title, children }: { tone: "alert" | "note"; title: string; children: ReactNode }) {
  const Icon = tone === "alert" ? CircleAlert : Info
  return (
    <div
      role={tone === "alert" ? "alert" : "status"}
      className={cn(
        "w-fit max-w-[92%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm",
        tone === "alert" ? "border-destructive/40 bg-background" : "bg-muted",
      )}
    >
      <p className="flex items-center gap-2 font-medium">
        <Icon aria-hidden="true" className={cn("size-4 shrink-0", tone === "alert" ? "text-destructive" : "text-muted-foreground")} />
        {title}
      </p>
      <div className="mt-1 space-y-2 break-words text-muted-foreground">{children}</div>
    </div>
  )
}

type SessionOpenProps = {
  failure: Extract<Failure, { kind: "session_open" }>
  handled?: boolean
  disabled: boolean
  onCloseSession?: (sessionId: string) => void
}

/**
 * A stale session closes in one click. A recent one closes too (after a server restart nothing else can),
 * but only past a confirm, because a CLI tutor may still be using it.
 */
function SessionOpen({ failure, handled, disabled, onCloseSession }: SessionOpenProps) {
  const [confirming, setConfirming] = useState(false)
  const close = onCloseSession && !handled ? () => onCloseSession(failure.sessionId) : undefined
  if (failure.stale) {
    return (
      <Shell tone="note" title="A stale session is still open on this course">
        <p>
          It has had no turn for over 2 hours, so it probably crashed or was left open. Closing it keeps its
          transcript and skips the Analyzer.
        </p>
        {close && (
          <Button size="sm" disabled={disabled} onClick={close}>
            Close stale session
          </Button>
        )}
      </Shell>
    )
  }
  return (
    <Shell tone="note" title="A session is open on this course elsewhere">
      <p>It had a turn in the last 2 hours, so it may still be in use, for example by a CLI tutor (brightlearn tutor).</p>
      {close && !confirming && (
        <Button variant="outline" size="sm" disabled={disabled} onClick={() => setConfirming(true)}>
          Close that session
        </Button>
      )}
      {close && confirming && (
        <div role="group" aria-label="Confirm closing the session" className="space-y-2 rounded-lg border bg-background p-3">
          <p className="text-foreground">
            Was this server restarted while that session was live here? Then nothing is using it and closing it is
            safe. If a CLI tutor is still running it, keep it and end it there. Closing skips the Analyzer.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="destructive" size="sm" disabled={disabled} onClick={close}>
              Yes, close it
            </Button>
            {/* The safe choice takes focus, since the button that opened this is gone. */}
            <Button variant="outline" size="sm" autoFocus onClick={() => setConfirming(false)}>
              Keep it
            </Button>
          </div>
        </div>
      )}
    </Shell>
  )
}

export function ErrorMessage({ failure, handled, onRetry, onCloseSession, disabled }: ErrorMessageProps) {
  const retry =
    onRetry && !handled ? (
      <Button variant="outline" size="sm" disabled={disabled} onClick={onRetry}>
        <RotateCcw />
        Try again
      </Button>
    ) : null

  switch (failure.kind) {
    case "nothing_linked":
      return (
        <div role="status" className="rounded-xl border bg-card">
          <EmptyState message="Upload course files to ask about them." />
        </div>
      )
    case "session_open":
      return <SessionOpen failure={failure} handled={handled} disabled={disabled} onCloseSession={onCloseSession} />
    case "session_gone":
      return (
        <Shell tone="alert" title="This server no longer holds the session">
          <p>It was probably restarted. Reload to see what it holds now; the transcript keeps everything said so far.</p>
          {onRetry && !handled && (
            <Button variant="outline" size="sm" disabled={disabled} onClick={onRetry}>
              <RefreshCw />
              Reload
            </Button>
          )}
        </Shell>
      )
    case "job_running": {
      const job = failure.job ? JOB_LABELS[failure.job] : "A job"
      return (
        <Shell tone="note" title={`${job} is running on this course`}>
          <p>It starts its own NotebookLM conversation, so this has to wait until it finishes.</p>
          {retry}
        </Shell>
      )
    }
    case "upstream":
      return (
        <Shell tone="alert" title={failure.provider ? `${providerName(failure.provider)} couldn't answer` : "No provider could answer"}>
          <p>{failure.detail}</p>
          {failure.resetsAt && <p className="font-medium text-foreground">Resets at {formatWhen(failure.resetsAt)}.</p>}
          {retry}
        </Shell>
      )
    case "conflict":
      return (
        <Shell tone="note" title="Not now">
          <p>{failure.detail}</p>
          {retry}
        </Shell>
      )
    case "other":
      return (
        <Shell tone="alert" title="Something went wrong">
          <p>{failure.detail}</p>
          {retry}
        </Shell>
      )
  }
}
