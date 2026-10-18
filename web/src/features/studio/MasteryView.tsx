// Where the learner stands: how many concepts sit at each level, then every concept weakest-first with its
// level and retention, each name opening the evidence behind it.
import { useConcepts, useEvidence, type Concept } from "@/api/queries.studio"
import { EmptyState } from "@/components/EmptyState"
import { LevelBar } from "@/components/LevelBar"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { retentionText, weakestFirst } from "@/features/studio/format"
import { ErrorNote } from "@/features/studio/notes"
import { SeedButton, SeedStatus, useSeedAction } from "@/features/studio/seed"
import { useStudioState } from "@/features/studio/store"
import { StudioView } from "@/features/studio/StudioView"
import { formatWhen } from "@/lib/format"

const LEVELS = [0, 1, 2, 3, 4, 5] as const

type MasteryViewProps = { course: string; onBack: () => void }

export function MasteryView({ course, onBack }: MasteryViewProps) {
  const [withRetired, setWithRetired] = useStudioState(`${course}:mastery:retired`, false)
  const concepts = useConcepts(course)
  const every = useConcepts(course, true)
  const seed = useSeedAction(course)

  if (concepts.isPending) {
    return (
      <StudioView title="Mastery" onBack={onBack}>
        <Pending label="Loading concepts" />
      </StudioView>
    )
  }
  if (concepts.isError) {
    return (
      <StudioView title="Mastery" onBack={onBack}>
        <ErrorNote error={concepts.error} />
      </StudioView>
    )
  }
  const active = [...concepts.data].sort(weakestFirst)
  if (active.length === 0) {
    return (
      <StudioView title="Mastery" description="No concepts yet" onBack={onBack}>
        <EmptyState className="py-4" message="Seed concepts from the syllabus." action={<SeedButton action={seed} />} />
        <SeedStatus action={seed} />
      </StudioView>
    )
  }

  const below = active.filter((c) => c.level < 3).length
  const shown = withRetired && every.data ? [...every.data].sort(weakestFirst) : active
  return (
    <StudioView title="Mastery" description={`${active.length} concepts · ${below} below level 3`} onBack={onBack}>
      <LevelCounts concepts={active} />
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={withRetired} onCheckedChange={(on) => setWithRetired(on === true)} />
        Include retired concepts
      </label>
      {withRetired && every.isPending && <Pending label="Loading retired concepts" />}
      {withRetired && every.isError && <ErrorNote error={every.error} />}
      <ConceptList course={course} concepts={shown} label="Concepts, weakest first" />
    </StudioView>
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
