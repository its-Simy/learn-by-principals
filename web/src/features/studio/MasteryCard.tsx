// Where the learner stands: the weakest five concepts, how many sit at each level, and the full list on demand.
import { useConcepts, useEvidence, type Concept } from "@/api/queries.studio"
import { EmptyState } from "@/components/EmptyState"
import { LevelBar } from "@/components/LevelBar"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { retentionText, weakestFirst } from "@/features/studio/format"
import { SeedButton, SeedStatus, useSeedAction } from "@/features/studio/seed"
import { ErrorNote, StudioCard } from "@/features/studio/StudioCard"
import { useStudioState } from "@/features/studio/store"
import { formatWhen } from "@/lib/format"

const WEAKEST = 5
const LEVELS = [0, 1, 2, 3, 4, 5] as const

export function MasteryCard({ course }: { course: string }) {
  const [expanded, setExpanded] = useStudioState(`${course}:mastery:expanded`, false)
  const [withRetired, setWithRetired] = useStudioState(`${course}:mastery:retired`, false)
  const concepts = useConcepts(course)
  const seed = useSeedAction(course)

  if (concepts.isPending) {
    return (
      <StudioCard title="Mastery">
        <Pending label="Loading concepts" />
      </StudioCard>
    )
  }
  if (concepts.isError) {
    return (
      <StudioCard title="Mastery">
        <ErrorNote error={concepts.error} />
      </StudioCard>
    )
  }
  const all = [...concepts.data].sort(weakestFirst)
  if (all.length === 0) {
    return (
      <StudioCard title="Mastery" status="No concepts yet">
        <EmptyState className="py-4" message="Seed concepts from the syllabus." action={<SeedButton action={seed} />} />
        <SeedStatus action={seed} />
      </StudioCard>
    )
  }

  const below = all.filter((c) => c.level < 3).length
  return (
    <StudioCard
      title="Mastery"
      status={`${all.length} concepts · ${below} below level 3`}
      action={
        <Button size="sm" variant="outline" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show fewer" : "See all"}
        </Button>
      }
    >
      <LevelCounts concepts={all} />
      {expanded ? (
        <FullList course={course} active={all} withRetired={withRetired} onWithRetired={setWithRetired} />
      ) : (
        <ConceptList course={course} concepts={all.slice(0, WEAKEST)} label="Weakest concepts" />
      )}
    </StudioCard>
  )
}

function LevelCounts({ concepts }: { concepts: Concept[] }) {
  return (
    <dl aria-label="Concepts at each level" className="grid grid-cols-6 gap-1 text-center">
      {LEVELS.map((level) => (
        <div key={level} className="rounded-md bg-muted/60 py-1.5">
          <dt className="text-[11px] text-muted-foreground">Level {level}</dt>
          <dd className="text-sm font-medium tabular-nums">{concepts.filter((c) => c.level === level).length}</dd>
        </div>
      ))}
    </dl>
  )
}

function FullList(props: { course: string; active: Concept[]; withRetired: boolean; onWithRetired: (on: boolean) => void }) {
  const { course, active, withRetired, onWithRetired } = props
  const every = useConcepts(course, true)
  const shown = withRetired && every.data ? [...every.data].sort(weakestFirst) : active
  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={withRetired} onCheckedChange={(on) => onWithRetired(on === true)} />
        Include retired concepts
      </label>
      {withRetired && every.isPending && <Pending label="Loading retired concepts" />}
      {withRetired && every.isError && <ErrorNote error={every.error} />}
      <ConceptList course={course} concepts={shown} label="All concepts" />
    </div>
  )
}

function ConceptList({ course, concepts, label }: { course: string; concepts: Concept[]; label: string }) {
  return (
    <ul aria-label={label} className="flex flex-col divide-y">
      {concepts.map((c) => (
        <li key={c.concept_id} className="flex items-center gap-3 py-2">
          <div className="min-w-0 flex-1">
            <EvidenceDialog course={course} concept={c} />
            <p className="text-xs text-muted-foreground">
              {retentionText(c)}
              {c.week !== null && ` · week ${c.week}`}
            </p>
          </div>
          {c.status === "retired" && <StateBadge state="disabled" label="retired" />}
          <LevelBar level={c.level} label={`${c.name} mastery`} />
        </li>
      ))}
    </ul>
  )
}

// Mastery needs evidence (principle 4): each concept's name opens what its level rests on.
function EvidenceDialog({ course, concept }: { course: string; concept: Concept }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          className="block max-w-full truncate rounded-sm text-left text-sm font-medium outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {concept.name}
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] grid-rows-[auto_minmax(0,1fr)]">
        <DialogHeader>
          <DialogTitle>{concept.name}</DialogTitle>
          <DialogDescription>
            Level {concept.level} of 5 · {concept.evidence_count} evidence · {retentionText(concept)}
          </DialogDescription>
        </DialogHeader>
        <EvidenceList course={course} conceptId={concept.concept_id} />
      </DialogContent>
    </Dialog>
  )
}

function EvidenceList({ course, conceptId }: { course: string; conceptId: string }) {
  const evidence = useEvidence(course, conceptId)
  if (evidence.isPending) return <Pending label="Loading evidence" />
  if (evidence.isError) return <ErrorNote error={evidence.error} />
  if (evidence.data.length === 0) return <p className="text-sm text-muted-foreground">No evidence recorded yet.</p>
  return (
    <ul className="min-h-0 divide-y overflow-y-auto text-sm">
      {evidence.data.map((e) => (
        <li key={e.evidence_id} className="py-2">
          <p>
            {e.type} · {e.strength}
          </p>
          <p className="text-xs text-muted-foreground">
            {formatWhen(e.recorded_at)}
            {e.source_provider && ` · ${e.source_provider}`}
            {e.session_id && ` · ${e.session_id}`}
          </p>
        </li>
      ))}
    </ul>
  )
}
