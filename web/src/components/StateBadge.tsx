// Text plus a semantic colour for any source, session, job or health state, so state is never colour alone.
import { Badge } from "@/components/ui/badge"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { humanize } from "@/lib/format"
import { stateTone, TONE_TEXT } from "@/lib/state"
import { cn } from "@/lib/utils"

type StateBadgeProps = {
  state: string
  /** Shown instead of the humanized state, e.g. "linked" for `synced`. */
  label?: string
  /**
   * What the state means: a tooltip on hover and focus, and a popover on click or tap, where
   * tooltips never open. The badge is then a button, so don't put a hinted badge inside a link.
   */
  hint?: string
  className?: string
}

export function StateBadge({ state, label, hint, className }: StateBadgeProps) {
  // bg-background keeps the measured text contrast on every surface (cards, rails, chat bubbles).
  const classes = cn("gap-1.5 bg-background", TONE_TEXT[stateTone(state)], className)
  const content = (
    <>
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {label ?? humanize(state)}
    </>
  )
  if (!hint) {
    return (
      <Badge variant="outline" className={classes}>
        {content}
      </Badge>
    )
  }
  // As HealthDots: the tooltip serves mouse and keyboard, the popover touch. A click on a button
  // inside a <label> (a source row) opens the popover without toggling the row's checkbox.
  return (
    <Popover>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Badge asChild variant="outline" className={cn("cursor-help outline-none", classes)}>
              <button type="button">{content}</button>
            </Badge>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{hint}</TooltipContent>
      </Tooltip>
      <PopoverContent align="start" className="w-64 text-sm">
        {hint}
      </PopoverContent>
    </Popover>
  )
}
