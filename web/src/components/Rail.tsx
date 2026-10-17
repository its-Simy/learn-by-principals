// A side pane of the course page (Sources, Studio): open beside the chat or a 48 px icon strip; a sheet below lg.
import type { LucideIcon } from "lucide-react"
import { PanelLeftClose, PanelRightClose } from "lucide-react"
import { useState, useSyncExternalStore, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const LARGE = "(min-width: 64rem)" // Tailwind's `lg`

function subscribeLarge(onChange: () => void): () => void {
  const query = window.matchMedia(LARGE)
  query.addEventListener("change", onChange)
  return () => query.removeEventListener("change", onChange)
}

function useIsLarge(): boolean {
  return useSyncExternalStore(subscribeLarge, () => window.matchMedia(LARGE).matches)
}

// Storage can be blocked; a rail then simply starts open and forgets.
function readOpen(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== "closed"
  } catch {
    return true
  }
}

function saveOpen(key: string, open: boolean): void {
  try {
    window.localStorage.setItem(key, open ? "open" : "closed")
  } catch {
    // Not remembered; the rail still toggles.
  }
}

// Radix wraps scroll content in a `display: table` div, which defeats `truncate` on long filenames.
function RailBody({ children }: { children: ReactNode }) {
  return (
    <ScrollArea className="min-h-0 flex-1 [&_[data-slot=scroll-area-viewport]>div]:block!">
      <div className="p-4">{children}</div>
    </ScrollArea>
  )
}

type RailProps = {
  /** Remembers this rail's state under `brightlearn.rail.{id}`. */
  id: string
  title: string
  icon: LucideIcon
  side: "left" | "right"
  /** Open width in px: 320 for Sources, 360 for Studio. */
  width: number
  children: ReactNode
}

export function Rail({ id, title, icon: Icon, side, width, children }: RailProps) {
  const key = `brightlearn.rail.${id}`
  const isLarge = useIsLarge()
  const [open, setOpenState] = useState(() => readOpen(key))
  const [sheetOpen, setSheetOpen] = useState(false)
  // Crossing `lg` closes the sheet, so it never reopens by itself when the window shrinks again.
  const [wasLarge, setWasLarge] = useState(isLarge)
  if (wasLarge !== isLarge) {
    setWasLarge(isLarge)
    setSheetOpen(false)
  }
  const setOpen = (next: boolean) => {
    saveOpen(key, next)
    setOpenState(next)
  }
  const edge = side === "left" ? "border-r" : "border-l"
  const CloseIcon = side === "left" ? PanelLeftClose : PanelRightClose

  if (isLarge && open) {
    return (
      <aside aria-label={title} style={{ width }} className={cn("flex shrink-0 flex-col bg-muted/30", edge)}>
        <div className="flex h-12 shrink-0 items-center justify-between border-b pr-2 pl-4">
          <h2 className="text-sm font-medium">{title}</h2>
          <Button variant="ghost" size="icon-sm" aria-label={`Collapse ${title}`} onClick={() => setOpen(false)}>
            <CloseIcon />
          </Button>
        </div>
        <RailBody>{children}</RailBody>
      </aside>
    )
  }

  return (
    <>
      <aside aria-label={title} className={cn("flex w-12 shrink-0 flex-col items-center bg-muted/30 py-2", edge)}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Open ${title}`}
              onClick={() => (isLarge ? setOpen(true) : setSheetOpen(true))}
            >
              <Icon />
            </Button>
          </TooltipTrigger>
          <TooltipContent side={side === "left" ? "right" : "left"}>{title}</TooltipContent>
        </Tooltip>
      </aside>
      {!isLarge && (
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent
            side={side}
            aria-describedby={undefined}
            style={{ width: `min(${width}px, 90vw)` }}
            className="gap-0 bg-background p-0 sm:max-w-none"
          >
            <SheetHeader className="border-b px-4 py-3">
              <SheetTitle className="text-sm font-medium">{title}</SheetTitle>
            </SheetHeader>
            <RailBody>{children}</RailBody>
          </SheetContent>
        </Sheet>
      )}
    </>
  )
}
