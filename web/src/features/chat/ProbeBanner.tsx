// Shown while a Challenger probe waits for its answer: the next message answers it, or Skip defers it (`/skip`).
import { Swords } from "lucide-react"

import type { Probe } from "@/api/queries.chat"
import { Button } from "@/components/ui/button"

type ProbeBannerProps = {
  probe: Probe
  /** "Sources only" is on: the next message asks the sources and leaves the probe waiting. */
  sourcesOnly: boolean
  disabled: boolean
  onSkip: () => void
}

export function ProbeBanner({ probe, sourcesOnly, disabled, onSkip }: ProbeBannerProps) {
  return (
    <div role="status" className="shrink-0 border-b bg-muted/40">
      <div className="mx-auto flex w-full max-w-3xl items-center gap-3 px-4 py-2">
        <Swords aria-hidden="true" className="size-4 shrink-0 text-pending" />
        <p className="min-w-0 flex-1 text-sm">
          <span className="font-medium">Challenger question on {probe.concept}.</span>{" "}
          {sourcesOnly
            ? "Sources only is on, so your next message asks the sources; turn it off to answer."
            : "Your next message is your answer."}
        </p>
        <Button variant="outline" size="sm" disabled={disabled} onClick={onSkip}>
          Skip
        </Button>
      </div>
    </div>
  )
}
