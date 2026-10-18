// One tile of the Studio's home, after NotebookLM's: an icon, a title and a one-line count; pressing it opens the tool's view.
import type { LucideIcon } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { openerProps } from "@/features/studio/store"

type StudioTileProps = {
  icon: LucideIcon
  title: string
  /** One short line, e.g. "3 exams"; undefined while it loads. */
  status: string | undefined
  /** The view the tile opens; Back from it returns the focus here. */
  view: string
  onOpen: (view: string) => void
}

export function StudioTile({ icon: Icon, title, status, view, onOpen }: StudioTileProps) {
  return (
    <button
      type="button"
      onClick={() => onOpen(view)}
      {...openerProps(view)}
      className="flex min-h-22 flex-col items-start gap-2 rounded-xl border bg-card p-3 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <Icon aria-hidden="true" className="size-5 text-muted-foreground" />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        {status === undefined ? (
          <Skeleton aria-hidden="true" className="mt-0.5 h-3 w-16" />
        ) : (
          <span className="line-clamp-1 text-xs text-muted-foreground">{status}</span>
        )}
      </span>
    </button>
  )
}
