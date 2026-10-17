// What an empty pane says: one sentence naming the next step, and optionally the action that takes it.
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

type EmptyStateProps = {
  message: string
  action?: ReactNode
  className?: string
}

export function EmptyState({ message, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-4 py-8 text-center", className)}>
      <p className="max-w-xs text-sm text-muted-foreground">{message}</p>
      {action}
    </div>
  )
}
