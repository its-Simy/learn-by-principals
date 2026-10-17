// A Studio view that replaces the cards while something is edited (a draft, a new exam's spec): Back, a heading, the editor.
import { ArrowLeft } from "lucide-react"
import { useEffect, useRef, type ReactNode } from "react"

import { Button } from "@/components/ui/button"

type EditorViewProps = {
  title: string
  /** Beside the title, e.g. the draft's reviewed badge. */
  badge?: ReactNode
  description?: ReactNode
  onBack: () => void
  children: ReactNode
}

export function EditorView({ title, badge, description, onBack, children }: EditorViewProps) {
  const heading = useRef<HTMLHeadingElement>(null)
  // The cards it replaced are gone, so focus moves to what took their place.
  useEffect(() => heading.current?.focus(), [])
  return (
    <section aria-label={title} className="flex flex-col gap-4">
      <div>
        <Button variant="ghost" size="sm" className="-ml-2" onClick={onBack}>
          <ArrowLeft />
          Back to Studio
        </Button>
      </div>
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 ref={heading} tabIndex={-1} className="min-w-0 text-sm font-semibold break-words outline-none">
            {title}
          </h3>
          {badge}
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
