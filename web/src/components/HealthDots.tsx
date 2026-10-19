// One dot per model or knowledge provider in the top bar; state, detail and reset time show on hover and on click.
import type { components } from "@/api/types"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatClock, humanize } from "@/lib/format"
import { stateTone, TONE_DOT } from "@/lib/state"
import { cn } from "@/lib/utils"

/** From the contract, so a renamed field fails typecheck instead of dropping the reset time. */
export type ProviderHealth = Pick<
  components["schemas"]["ProviderHealthOut"],
  "provider" | "state" | "detail" | "cooldown_until"
>

/** A rate limit's reset time while it is still ahead; one already past is history. */
function resetsAt(h: ProviderHealth): string | null {
  return h.cooldown_until && Date.parse(h.cooldown_until) > Date.now() ? formatClock(h.cooldown_until) : null
}

function HealthText({ h }: { h: ProviderHealth }) {
  return (
    <>
      <p className="font-medium">
        {h.provider}: {humanize(h.state)}
      </p>
      {h.detail && <p>{h.detail}</p>}
      {resetsAt(h) && <p>resets at {resetsAt(h)}</p>}
    </>
  )
}

// The tooltip serves mouse and keyboard; the popover serves touch, where tooltips never open.
export function HealthDots({ health }: { health: ProviderHealth[] }) {
  if (health.length === 0) return null
  return (
    <ul className="flex items-center" aria-label="Provider health">
      {health.map((h) => (
        <li key={h.provider}>
          <Popover>
            <Tooltip>
              <TooltipTrigger asChild>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    aria-label={`${h.provider}: ${humanize(h.state)}`}
                    className="flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  >
                    <span aria-hidden="true" className={cn("size-2 rounded-full", TONE_DOT[stateTone(h.state)])} />
                    <span aria-hidden="true" className="hidden xl:inline">
                      {h.provider}
                    </span>
                  </button>
                </PopoverTrigger>
              </TooltipTrigger>
              <TooltipContent>
                <HealthText h={h} />
              </TooltipContent>
            </Tooltip>
            <PopoverContent align="end" className="w-64 text-sm">
              <HealthText h={h} />
            </PopoverContent>
          </Popover>
        </li>
      ))}
    </ul>
  )
}
