// The course's concept list and its drafts: seed a draft from the sources, review it, apply it.
import { ChevronRight } from "lucide-react"

import { useConcepts, useDrafts, type Draft } from "@/api/queries.studio"
import { EmptyState } from "@/components/EmptyState"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { draftWhen } from "@/features/studio/format"
import { SeedButton, SeedStatus, useSeedAction } from "@/features/studio/seed"
import { ErrorNote, StudioCard } from "@/features/studio/StudioCard"
import { openerProps } from "@/features/studio/store"

/** `hint` adds the explanation in a focusable tooltip; leave it off inside a button. */
export function ReviewedBadge({ reviewed, hint = false }: { reviewed: boolean; hint?: boolean }) {
  return reviewed ? (
    <StateBadge state="done" label="reviewed" hint={hint ? "Marked reviewed: true, so it can be applied" : undefined} />
  ) : (
    <StateBadge
      state="warn"
      label="needs review"
      hint={hint ? "Still reviewed: false; apply refuses it until you set it to true" : undefined}
    />
  )
}

export function ConceptsCard({ course, onOpenDraft }: { course: string; onOpenDraft: (name: string) => void }) {
  const concepts = useConcepts(course, true)
  const drafts = useDrafts(course)
  const seed = useSeedAction(course)

  const retired = concepts.data?.filter((c) => c.status === "retired").length ?? 0
  const active = (concepts.data?.length ?? 0) - retired
  const status = concepts.data ? `${active} active · ${retired} retired` : undefined

  return (
    <StudioCard title="Concepts" status={status} action={<SeedButton action={seed} variant="outline" />}>
      {concepts.isError && <ErrorNote error={concepts.error} />}
      <SeedStatus action={seed} />
      {drafts.isPending ? (
        <Pending label="Loading drafts" />
      ) : drafts.isError ? (
        <ErrorNote error={drafts.error} />
      ) : drafts.data.length === 0 ? (
        <EmptyState className="py-4" message="No drafts yet. Seed one from the syllabus and lectures, review it, then apply it." />
      ) : (
        <ul aria-label="Concept drafts" className="-mx-2 flex flex-col">
          {drafts.data.map((d) => (
            <li key={d.name}>
              <DraftRow draft={d} onOpen={() => onOpenDraft(d.name)} />
            </li>
          ))}
        </ul>
      )}
    </StudioCard>
  )
}

function DraftRow({ draft, onOpen }: { draft: Draft; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      {...openerProps(`draft:${draft.name}`)}
      className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate">{draftWhen(draft)}</span>
        {draft.latest && <span className="block text-xs text-muted-foreground">latest</span>}
      </span>
      <ReviewedBadge reviewed={draft.reviewed} />
      <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
    </button>
  )
}
