// The chat's mode: asking the sources (persona select and Start) or a live tutoring session (persona, start time, End).
import { GraduationCap } from "lucide-react"

import type { LiveSession, Persona } from "@/api/queries.chat"
import { useModelsHint } from "@/api/queries.system"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { formatWhen } from "@/lib/format"

import { SessionHistory } from "./SessionHistory"

type PersonaSelectProps = {
  personas: Persona[]
  value: string
  disabled: boolean
  onChange: (name: string) => void
}

function PersonaSelect({ personas, value, disabled, onChange }: PersonaSelectProps) {
  // The current value stays listed even before the personas load, so the trigger never goes blank.
  const names = personas.map((p) => p.name)
  if (!names.includes(value)) names.unshift(value)
  return (
    <Select value={value} disabled={disabled} onValueChange={onChange}>
      <SelectTrigger size="sm" aria-label="Persona" className="min-w-28">
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="end">
        {names.map((name) => (
          <SelectItem key={name} value={name}>
            {name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

type SessionBannerProps = {
  course: string
  /** `undefined` while the session is loading. */
  session: LiveSession | null | undefined
  personas: Persona[]
  /** The persona Start will use. */
  persona: string
  onPersonaChange: (name: string) => void
  onStart: () => void
  onEnd: () => void
  /** During a session: switch with `/persona x`. */
  onSwitchPersona: (name: string) => void
  busy: boolean
}

export function SessionBanner(props: SessionBannerProps) {
  const { course, session, personas, busy } = props
  const modelsHint = useModelsHint()
  return (
    <div className="shrink-0 border-b">
      <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
        {session === undefined ? (
          <Skeleton className="h-5 w-64" />
        ) : session === null ? (
          <>
            <p className="min-w-0 flex-1 basis-64 text-sm text-muted-foreground">
              Asking the course sources. Start a tutoring session to get coaching and track mastery.
              {/* Start stays enabled: a CLI installed later works after a restart, and the turn's error says what is missing. */}
              {modelsHint && <span className="block text-xs text-warning">{modelsHint}</span>}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <PersonaSelect personas={personas} value={props.persona} disabled={busy} onChange={props.onPersonaChange} />
              <Button size="sm" disabled={busy} onClick={props.onStart}>
                <GraduationCap />
                Start session
              </Button>
              <SessionHistory course={course} />
            </div>
          </>
        ) : (
          <>
            <div className="flex min-w-0 flex-1 basis-64 flex-wrap items-center gap-2 text-sm">
              <StateBadge state="open" label="live session" />
              <PersonaSelect personas={personas} value={session.persona} disabled={busy} onChange={props.onSwitchPersona} />
              <span className="text-muted-foreground">started {formatWhen(session.started_at)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SessionHistory course={course} />
              <Button variant="outline" size="sm" disabled={busy} onClick={props.onEnd}>
                End session
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
