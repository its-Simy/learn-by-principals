// A Studio view in place of the tiles: a tool (Mastery, Practice exams, ...) or an editor under one.
// Back, a heading with the view's one action beside it, a line of status, then the body.
import { ArrowLeft } from "lucide-react"
import { useEffect, useRef, type ReactNode } from "react"

import { Button } from "@/components/ui/button"

type StudioViewProps = {
  title: string
  /** "Back to Studio" from a tool; an editor names the tool it returns to. */
  backLabel?: string
  /** Beside the title, e.g. the draft's reviewed badge. */
  badge?: ReactNode
  /** The view's one primary action, right of the title. */
  action?: ReactNode
  description?: ReactNode
  onBack: () => void
  children: ReactNode
}

export function StudioView({ title, backLabel = "Back to Studio", badge, action, description, onBack, children }: StudioViewProps) {
  const heading = useRef<HTMLHeadingElement>(null)
  // What it replaced is gone, so focus moves to what took its place (StudioPane hands it to the opener on Back).
  useEffect(() => heading.current?.focus(), [])
  return (
    <section aria-label={title} className="flex flex-col gap-4">
      <div>
        <Button variant="ghost" size="sm" className="-ml-2" onClick={onBack}>
          <ArrowLeft />
          {backLabel}
        </Button>
      </div>
      <div className="flex flex-col gap-1">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 ref={heading} tabIndex={-1} className="min-w-0 text-sm font-semibold break-words outline-none">
              {title}
            </h3>
            {badge}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  )
}

/** A unified diff, its added and removed lines marked by colour and by their leading + and -. */
export function DiffBlock({ text, label }: { text: string; label: string }) {
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      className="max-h-80 overflow-auto rounded-md border bg-background p-3 font-mono text-xs leading-relaxed outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      {text.split("\n").map((line, i) => (
        <span
          key={i}
          className={
            line.startsWith("+") && !line.startsWith("+++")
              ? "block text-success"
              : line.startsWith("-") && !line.startsWith("---")
                ? "block text-destructive"
                : "block"
          }
        >
          {line || " "}
        </span>
      ))}
    </pre>
  )
}
