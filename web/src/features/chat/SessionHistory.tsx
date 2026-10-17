// The banner's History popover: the course's sessions with their state, Close for a stale one, and each transcript in a dialog.
import { History } from "lucide-react"
import { useState } from "react"

import { failureOf, useCloseSession, useSessions, useTranscript, type PastSession } from "@/api/queries.chat"
import { Markdown } from "@/components/Markdown"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"

import { formatWhen } from "./model"

// Only a stale row explains itself: the popover focuses its first badge on open, and a tooltip on every row would be noise.
const STALE_HINT = "Still open, but no turn for over 2 hours. It blocks new sessions until closed."

// The transcript file starts with YAML front matter (session id, course, start), which isn't for reading.
function withoutFrontMatter(text: string): string {
  return text.replace(/^---\n[\s\S]*?\n---\n/, "")
}

type SessionRowProps = { course: string; session: PastSession; onTranscript: () => void }

// `course` is the page's own spelling of the code, so the close refreshes the list this popover shows.
function SessionRow({ course, session, onTranscript }: SessionRowProps) {
  const close = useCloseSession(course)
  const closable = session.state === "stale" && !session.live
  return (
    <li className="space-y-1.5 px-4 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm">{formatWhen(session.started_at)}</p>
          <p className="truncate text-xs text-muted-foreground">
            {session.tutor_provider ? `Tutor: ${session.tutor_provider}` : "No tutoring yet"}
            {session.analyzer_provider && ` · Analyzer: ${session.analyzer_provider}`}
          </p>
        </div>
        <StateBadge
          state={session.live ? "open" : session.state}
          label={session.live ? "live" : undefined}
          hint={closable ? STALE_HINT : undefined}
        />
      </div>
      <div className="flex gap-1.5">
        <Button variant="ghost" size="xs" onClick={onTranscript}>
          Transcript
        </Button>
        {closable && (
          <Button variant="outline" size="xs" disabled={close.isPending} onClick={() => close.mutate(session.session_id)}>
            {close.isPending ? "Closing…" : "Close"}
          </Button>
        )}
      </div>
      {close.isError && (
        <p role="alert" className="text-xs text-destructive">
          {failureOf(close.error).detail}
        </p>
      )}
    </li>
  )
}

function TranscriptDialog({ course, session, onClose }: { course: string; session: PastSession | null; onClose: () => void }) {
  const transcript = useTranscript(course, session?.session_id ?? null)
  return (
    <Dialog open={session !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-3 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Session transcript</DialogTitle>
          <DialogDescription>{session ? `Started ${formatWhen(session.started_at)}` : ""}</DialogDescription>
        </DialogHeader>
        {/* A plain overflow box: under a max-height dialog a ScrollArea's viewport has no definite height to fill. */}
        <div className="min-h-0 flex-1 overflow-y-auto pr-3">
          {transcript.isPending && <Pending label="Loading the transcript" />}
          {transcript.isError && (
            <p role="alert" className="text-sm text-destructive">
              {failureOf(transcript.error).detail}
            </p>
          )}
          {transcript.data && <Markdown>{withoutFrontMatter(transcript.data.text)}</Markdown>}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function SessionHistory({ course }: { course: string }) {
  const [open, setOpen] = useState(false)
  const [reading, setReading] = useState<PastSession | null>(null)
  const sessions = useSessions(course, open)
  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm">
            <History />
            <span className="sr-only sm:not-sr-only">History</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-0">
          <p className="border-b px-4 py-2 text-sm font-medium">Sessions on {course}</p>
          {sessions.isPending ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ) : sessions.isError ? (
            <p role="alert" className="px-4 py-3 text-sm text-destructive">
              {failureOf(sessions.error).detail}
            </p>
          ) : sessions.data.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">No sessions yet.</p>
          ) : (
            <ul className="max-h-80 divide-y overflow-y-auto">
              {sessions.data.map((s) => (
                <SessionRow
                  key={s.session_id}
                  course={course}
                  session={s}
                  onTranscript={() => {
                    // The dialog lives outside the popover, which closes now, so it isn't unmounted with it.
                    setOpen(false)
                    setReading(s)
                  }}
                />
              ))}
            </ul>
          )}
        </PopoverContent>
      </Popover>
      <TranscriptDialog course={course} session={reading} onClose={() => setReading(null)} />
    </>
  )
}
