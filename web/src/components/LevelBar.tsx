// A concept's mastery level, 0–5, as five segments plus the number.
import { cn } from "@/lib/utils"

const LEVELS = [1, 2, 3, 4, 5] as const

type LevelBarProps = {
  level: number
  /** Accessible name; the visible text is always "n/5". */
  label?: string
  className?: string
}

export function LevelBar({ level, label = "Mastery level", className }: LevelBarProps) {
  const value = Math.min(5, Math.max(0, Math.round(level)))
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={5}
      aria-valuenow={value}
      aria-valuetext={`${value} of 5`}
      className={cn("flex items-center gap-2", className)}
    >
      <div aria-hidden="true" className="flex gap-0.5">
        {LEVELS.map((n) => (
          <span key={n} className={cn("h-1.5 w-4 rounded-full", n <= value ? "bg-foreground/80" : "bg-border")} />
        ))}
      </div>
      <span aria-hidden="true" className="text-xs tabular-nums text-muted-foreground">
        {value}/5
      </span>
    </div>
  )
}
