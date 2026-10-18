// Notes every Studio view shares: a failure in place, a note that isn't one, and a read-only text from the API.
import type { UseQueryResult } from "@tanstack/react-query"
import { CircleAlert } from "lucide-react"
import type { ReactNode } from "react"

import { Markdown } from "@/components/Markdown"
import { Pending } from "@/components/Pending"
import { cn } from "@/lib/utils"

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
