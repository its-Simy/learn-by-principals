// Seeding concepts from the syllabus and lectures, shared by the Mastery card's empty state and the Concepts card.
import { conflictCode } from "@/api/client"
import { isActive } from "@/api/jobs"
import { useSeed } from "@/api/queries.studio"
import { JobRow } from "@/components/JobRow"
import { Button } from "@/components/ui/button"
import { ErrorNote, Note } from "@/features/studio/StudioCard"
import { useCardJob } from "@/features/studio/store"

export function useSeedAction(course: string) {
  const seed = useSeed(course)
  const [job, start] = useCardJob(course, "seed", "seed")
  return {
    job,
    error: seed.error,
    busy: seed.isPending || isActive(job),
    run: () => seed.mutate(undefined, { onSuccess: start }),
  }
}

export function SeedButton({ action, variant = "default" }: { action: ReturnType<typeof useSeedAction>; variant?: "default" | "outline" }) {
  return (
    <Button size="sm" variant={variant} disabled={action.busy} onClick={action.run}>
      Seed
    </Button>
  )
}

/** The seed job's row, or why the server wouldn't start one (a 409 is a note, not a failure). */
export function SeedStatus({ action }: { action: ReturnType<typeof useSeedAction> }) {
  if (action.error) {
    return conflictCode(action.error) ? <Note>{action.error.message}</Note> : <ErrorNote error={action.error} />
  }
  return action.job ? <JobRow job={action.job} /> : null
}
