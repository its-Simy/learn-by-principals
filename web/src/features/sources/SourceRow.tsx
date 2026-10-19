// One stored file: icon, name, bucket and state; a linked file's whole row toggles its checkbox.
import { useId } from "react"

import type { Source } from "@/api/queries.sources"
import { StateBadge } from "@/components/StateBadge"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { fileIcon, isSelectable, sourceStatus } from "@/features/sources/status"
import { cn } from "@/lib/utils"

type SourceRowProps = {
  source: Source
  /** A link job is queued or running on the course, so unlinked files are on their way. */
  linking: boolean
  /** Why the last link job couldn't send this file, if it couldn't. */
  failure?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

export function SourceRow({ source, linking, failure, checked, onCheckedChange }: SourceRowProps) {
  const id = useId()
  const Icon = fileIcon(source)
  const status = sourceStatus(source, linking, failure)
  const name = source.filename ?? source.resource_id
  const selectable = isSelectable(source)
  const body = (
    <>
      <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm" title={name}>
          {name}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          {source.bucket && <Badge variant="secondary">{source.bucket}</Badge>}
          <StateBadge state={status.tone} label={status.label} hint={status.hint} />
        </span>
      </span>
    </>
  )
  const row = "flex min-h-10 items-center gap-3 rounded-lg px-2 py-2"
  if (!selectable) {
    // Keeps the checkbox column so names line up with the selectable rows.
    return (
      <li className={row}>
        {body}
        <span aria-hidden="true" className="size-4 shrink-0" />
      </li>
    )
  }
  // A <label> for a button-based checkbox: a click anywhere on the row clicks the checkbox.
  return (
    <li>
      <label htmlFor={id} className={cn(row, "cursor-pointer hover:bg-accent has-focus-visible:bg-accent")}>
        {body}
        <Checkbox
          id={id}
          checked={checked}
          onCheckedChange={(value) => onCheckedChange(value === true)}
          aria-label={`Use ${name} in questions`}
        />
      </label>
    </li>
  )
}
