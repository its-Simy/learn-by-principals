// The 56 px bar on every page: the app's name, the open course, status (HealthDots, JobsIndicator) and the theme toggle.
import { Activity } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router"

import { ThemeToggle } from "@/components/ThemeToggle"
import { Button } from "@/components/ui/button"

type TopBarProps = {
  /** The open course's name, shown after the app's name. */
  courseTitle?: string
  /** Status slot: HealthDots and JobsIndicator. */
  children?: ReactNode
}

export function TopBar({ courseTitle, children }: TopBarProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
      {/* The name alone, as NotebookLM's bar: no mark, and visible at every width so the home link is never empty. */}
      <Link to="/" aria-label="BrightLearn home" className="shrink-0 rounded-md font-semibold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
        BrightLearn
      </Link>
      {courseTitle && (
        <>
          <span aria-hidden="true" className="text-muted-foreground">
            /
          </span>
          <h1 className="min-w-0 truncate text-sm font-medium">{courseTitle}</h1>
        </>
      )}
      <div className="ml-auto flex shrink-0 items-center gap-1">
        {children}
        <Button variant="ghost" size="icon" asChild>
          <Link to="/system" aria-label="System status">
            <Activity />
          </Link>
        </Button>
        <ThemeToggle />
      </div>
    </header>
  )
}
