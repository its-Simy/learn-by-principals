// The frame every Studio card shares: a title, a one-line status, one primary action, then its list.
import type { UseQueryResult } from "@tanstack/react-query"
import { CircleAlert } from "lucide-react"
import { useId, type ReactNode } from "react"

import { Markdown } from "@/components/Markdown"
import { Pending } from "@/components/Pending"
import { Card, CardAction, CardContent, CardDescription, CardHeader } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type StudioCardProps = {
  title: string
  /** One line: where things stand. */
  status?: ReactNode
  /** The card's one primary action. */
  action?: ReactNode
  children?: ReactNode
  className?: string
}

export function StudioCard({ title, status, action, children, className }: StudioCardProps) {
  const titleId = useId()
  return (
    <Card role="region" aria-labelledby={titleId} className={cn("gap-3 py-4 shadow-none", className)}>
      <CardHeader className="gap-1 px-4">
        {/* Focusable from script: Back from an editor lands here when its opener is disabled. */}
        <h3 id={titleId} tabIndex={-1} className="text-sm leading-none font-semibold outline-none">
          {title}
        </h3>
        {status && <CardDescription className="text-xs">{status}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      {children && <CardContent className="flex flex-col gap-3 px-4">{children}</CardContent>}
    </Card>
  )
}

/** A failed load or request, in place. */
export function ErrorNote({ error, className }: { error: unknown; className?: string }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <p role="alert" className={cn("flex items-start gap-2 text-sm text-destructive", className)}>
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0 break-words">{message}</span>
    </p>
  )
}

/** Something to know that isn't a failure, e.g. a 409 explaining why an action waits. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p role="status" className={cn("rounded-md border bg-muted/50 px-3 py-2 text-sm text-muted-foreground", className)}>
      {children}
    </p>
  )
}

/** A read-only text from the API (paper, brief) as Markdown, with its loading and error states. */
export function TextBody({ query, label }: { query: UseQueryResult<{ text: string }>; label: string }) {
  if (query.isPending) return <Pending label={label} />
  if (query.isError) return <ErrorNote error={query.error} />
  return <Markdown>{query.data.text}</Markdown>
}
