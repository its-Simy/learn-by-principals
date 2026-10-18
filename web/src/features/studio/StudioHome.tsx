// The Studio's first screen, after NotebookLM's: a tile per tool, the jobs in progress, then what has been made.
// Every row here is a shortcut into a tool's view; the actions live there.
import { useQuery } from "@tanstack/react-query"
import { AudioLines, ChevronRight, ClipboardList, Gauge, ListTree, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { fetchJobs, isActive, keys, POLL_MS, type Job } from "@/api/jobs"
import { useConcepts, useDrafts, useExams, usePodcasts } from "@/api/queries.studio"
import { EmptyState } from "@/components/EmptyState"
import { JobRow } from "@/components/JobRow"
import { Pending } from "@/components/Pending"
import { PODCAST_TYPICAL } from "@/features/studio/AudioOverviewView"
import { ReviewedBadge } from "@/features/studio/ConceptsView"
import { draftLabel, draftTime } from "@/features/studio/format"
import { ErrorNote } from "@/features/studio/notes"
import { CREATE_TYPICAL } from "@/features/studio/PracticeExamView"
import { StudioTile } from "@/features/studio/StudioTile"
import { AUDIO, CONCEPTS, EXAMS, MASTERY, sameCourse, useCardJob } from "@/features/studio/store"
import { formatWhen, plural } from "@/lib/format"

/** The home lists this many of the newest outputs; the tiles carry the full counts. */
const RECENT = 10

const TYPICAL: Partial<Record<Job["kind"], string>> = { exam_create: CREATE_TYPICAL, podcast: PODCAST_TYPICAL }

type StudioHomeProps = { course: string; onOpen: (view: string) => void }

export function StudioHome({ course, onOpen }: StudioHomeProps) {
  const concepts = useConcepts(course)
  const exams = useExams(course)
  const podcasts = usePodcasts(course)
  const drafts = useDrafts(course)
  const jobs = useJobsInProgress(course)

  const count = (n: number, word: string, none: string) => (n === 0 ? none : plural(n, word))
  const toReview = drafts.data?.filter((d) => !d.reviewed).length ?? 0
  const tiles = (
    <div className="grid grid-cols-2 gap-2">
      <StudioTile
        icon={Gauge}
        title="Mastery"
        status={concepts.data && count(concepts.data.length, "concept", "No concepts yet")}
        view={MASTERY}
        onOpen={onOpen}
      />
      <StudioTile
        icon={ClipboardList}
        title="Practice exam"
        status={exams.data && count(exams.data.length, "exam", "No exams yet")}
        view={EXAMS}
        onOpen={onOpen}
      />
      <StudioTile
        icon={AudioLines}
        title="Audio Overview"
        status={podcasts.data && count(podcasts.data.length, "episode", "No episodes yet")}
        view={AUDIO}
        onOpen={onOpen}
      />
      <StudioTile
        icon={ListTree}
        title="Concepts"
        status={
          drafts.data && concepts.data
            ? toReview > 0
              ? `${plural(toReview, "draft")} to review`
              : concepts.data.length === 0
              ? "Nothing seeded yet"
              : `${concepts.data.length} active`
            : undefined
        }
        view={CONCEPTS}
        onOpen={onOpen}
      />
    </div>
  )

  return (
    <div className="flex flex-col gap-5">
      {tiles}
      {jobs.length > 0 && (
        <section aria-labelledby="studio-jobs" className="flex flex-col gap-2">
          <h3 id="studio-jobs" className="text-xs font-medium text-muted-foreground">
            Jobs
          </h3>
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} typical={TYPICAL[job.kind]} />
          ))}
        </section>
      )}
      <Outputs course={course} jobs={jobs.length} onOpen={onOpen} />
    </div>
  )
}

/**
 * The jobs the home shows: the ones the tool views remember (so a result row stays until the next job of
 * that kind) and any grading in flight on the course. The grade slots are per exam, so those come from the
 * jobs list; it is the watcher's query, so a job submitted anywhere in the app shows within a poll.
 */
function useJobsInProgress(course: string): Job[] {
  const [seed] = useCardJob(course, "seed", "seed")
  const [create] = useCardJob(course, "exam_create", "exam_create")
  const [podcast] = useCardJob(course, "podcast", "podcast")
  const { data: grading = [] } = useQuery({
    queryKey: keys.jobs(),
    queryFn: fetchJobs,
    staleTime: POLL_MS,
    select: (jobs) => jobs.filter((j) => j.kind === "exam_grade" && sameCourse(j.course, course) && isActive(j)),
  })
  const remembered = [seed, create, podcast].filter((j): j is Job => j !== undefined)
  return [...remembered, ...grading.filter((g) => !remembered.some((r) => r.id === g.id))]
}

type Output = {
  key: string
  /** Epoch ms, or null when unknown (sorted last). */
  at: number | null
  icon: LucideIcon
  title: string
  meta: ReactNode
  view: string
}

function epoch(iso: string): number | null {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

function Outputs({ course, jobs, onOpen }: { course: string; jobs: number; onOpen: (view: string) => void }) {
  const exams = useExams(course)
  const podcasts = usePodcasts(course)
  const drafts = useDrafts(course)
  const names = new Map((useConcepts(course, true).data ?? []).map((c) => [c.concept_id, c.name]))

  const error = exams.error ?? podcasts.error ?? drafts.error
  if (error) return <ErrorNote error={error} />
  if (!exams.data || !podcasts.data || !drafts.data) return <Pending label="Loading what has been made" />

  const outputs: Output[] = [
    ...exams.data.map((exam) => ({
      key: `exam:${exam.id}`,
      at: epoch(exam.created_at),
      icon: ClipboardList,
      title: exam.exam,
      meta: `${plural(exam.questions, "question")} · ${formatWhen(exam.created_at)}`,
      view: EXAMS,
    })),
    ...podcasts.data.map((episode) => {
      const targets = episode.concepts.map((id) => names.get(id) ?? id)
      return {
        key: `episode:${episode.id}`,
        at: epoch(episode.created_at),
        icon: AudioLines,
        title: `Episode of ${formatWhen(episode.created_at)}`,
        meta: targets.length ? `On ${targets.join(", ")}` : "No concepts targeted",
        view: AUDIO,
      }
    }),
    ...drafts.data.map((draft) => ({
      key: `draft:${draft.name}`,
      at: draftTime(draft),
      icon: ListTree,
      title: draftLabel(draft),
      meta: <ReviewedBadge reviewed={draft.reviewed} />,
      view: CONCEPTS,
    })),
  ]
  if (outputs.length === 0) {
    return jobs > 0 ? null : <EmptyState className="py-6" message="Nothing made yet. Pick a tile to start." />
  }
  // Newest first; anything without a time goes last, in the order its list gave.
  const recent = outputs
    .map((o, i) => ({ o, i }))
    .sort((a, b) => (b.o.at ?? -Infinity) - (a.o.at ?? -Infinity) || a.i - b.i)
    .slice(0, RECENT)
    .map(({ o }) => o)

  return (
    <section aria-labelledby="studio-made" className="flex flex-col gap-1">
      <h3 id="studio-made" className="text-xs font-medium text-muted-foreground">
        Made so far
      </h3>
      <ul aria-label="Outputs" className="-mx-2 flex flex-col">
        {recent.map((output) => (
          <OutputRow key={output.key} output={output} onOpen={onOpen} />
        ))}
      </ul>
    </section>
  )
}

function OutputRow({ output, onOpen }: { output: Output; onOpen: (view: string) => void }) {
  const { icon: Icon, title, meta, view } = output
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(view)}
        className="flex min-h-10 w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1">
          <span className="block truncate">{title}</span>
          <span className="block truncate text-xs text-muted-foreground">{meta}</span>
        </span>
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      </button>
    </li>
  )
}
