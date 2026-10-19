// The sources an answer cites, as `[1] lec3.pdf` buttons; each opens its excerpt in a popover (click, Enter or Space).
import { FileText } from "lucide-react"

import type { Citation } from "@/api/queries.chat"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

export function CitationChips({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null
  return (
    <ul aria-label="Cited sources" className="flex flex-wrap gap-1.5">
      {citations.map((c) => {
        const name = c.filename ?? "unknown source"
        return (
          <li key={c.n}>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="inline-flex h-7 max-w-56 items-center gap-1 rounded-full border bg-background px-2.5 text-xs text-foreground outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=open]:bg-accent"
                >
                  <span className="tabular-nums text-muted-foreground">[{c.n}]</span>
                  <span className="truncate">{name}</span>
                </button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-80 text-sm">
                <p className="flex items-center gap-1.5 font-medium">
                  <FileText aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 break-words">
                    [{c.n}] {name}
                    {c.bucket && <span className="font-normal text-muted-foreground"> ({c.bucket})</span>}
                  </span>
                </p>
                <blockquote className="mt-2 border-l-2 pl-3 leading-relaxed text-muted-foreground">
                  {c.excerpt || "No excerpt was returned for this citation."}
                </blockquote>
              </PopoverContent>
            </Popover>
          </li>
        )
      })}
    </ul>
  )
}
