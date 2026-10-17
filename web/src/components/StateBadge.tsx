// Text plus a semantic colour for any source, session, job or health state, so state is never colour alone.
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { humanize } from "@/lib/format"
import { stateTone, TONE_TEXT } from "@/lib/state"
import { cn } from "@/lib/utils"

type StateBadgeProps = {
  state: string
  /** Shown instead of the humanized state, e.g. "linked" for `synced`. */
  label?: string
  /** What the state means; shown in a tooltip and reachable by keyboard. */
  hint?: string
  className?: string
}

export function StateBadge({ state, label, hint, className }: StateBadgeProps) {
  // bg-background keeps the measured text contrast on every surface (cards, rails, chat bubbles).
  const badge = (
    <Badge
      variant="outline"
      tabIndex={hint ? 0 : undefined}
      className={cn("gap-1.5 bg-background", TONE_TEXT[stateTone(state)], className)}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {label ?? humanize(state)}
    </Badge>
  )
  if (!hint) return badge
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  )
}
