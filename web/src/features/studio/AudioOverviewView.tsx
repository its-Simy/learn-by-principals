// Audio Overviews: a NotebookLM episode aimed at the learner's weak spots, optionally framed for an exam.
import { useId } from "react"

import { isActive } from "@/api/jobs"
import {
  useBrief,
  useConcepts,
  useExams,
  useGeneratePodcast,
  useLinkedSourceCount,
  usePodcasts,
  type Episode,
  type PodcastFormat,
  type PodcastLength,
} from "@/api/queries.studio"
import { EmptyState } from "@/components/EmptyState"
import { JobRow } from "@/components/JobRow"
import { Pending } from "@/components/Pending"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ErrorNote, TextBody } from "@/features/studio/notes"
import { useCardJob, useStudioState } from "@/features/studio/store"
import { StudioView } from "@/features/studio/StudioView"
import { formatWhen } from "@/lib/format"

export const PODCAST_TYPICAL = "5–15 minutes"

// Every value of the generated enums, each once: a Record fails the typecheck if the contract changes.
const FORMATS: Record<PodcastFormat, string> = {
  "deep-dive": "Deep dive",
  brief: "Brief",
  critique: "Critique",
  debate: "Debate",
}
const LENGTHS: Record<PodcastLength, string> = {
  default: "Default",
  short: "Short",
  long: "Long",
}
// Own keys only: `in` would also accept "toString".
const isFormat = (v: string): v is PodcastFormat => Object.hasOwn(FORMATS, v)
const isLength = (v: string): v is PodcastLength => Object.hasOwn(LENGTHS, v)
const NO_EXAM = "none" // Radix Select has no empty value

export function AudioOverviewView({ course, onBack }: { course: string; onBack: () => void }) {
  const [format, setFormat] = useStudioState<PodcastFormat>(`${course}:podcast:format`, "deep-dive")
  const [length, setLength] = useStudioState<PodcastLength>(`${course}:podcast:length`, "default")
  const [exam, setExam] = useStudioState<string>(`${course}:podcast:exam`, NO_EXAM)
  const podcasts = usePodcasts(course)
  const exams = useExams(course)
  const linked = useLinkedSourceCount(course)
  const generate = useGeneratePodcast(course)
  const [job, start] = useCardJob(course, "podcast", "podcast")
  const id = useId()

  const hasSources = linked > 0
  // Exams are looked up by name; two exams with one name frame the episode the same way.
  const examNames = [...new Set((exams.data ?? []).map((e) => e.exam))]
  const episodes = podcasts.data ?? []
  const status = podcasts.data
    ? episodes.length === 0
      ? "No episodes yet"
      : `${episodes.length} ${episodes.length === 1 ? "episode" : "episodes"}`
    : undefined

  const submit = () =>
    generate.mutate(
      { format, length, exam: exam === NO_EXAM || !examNames.includes(exam) ? null : exam },
      { onSuccess: start },
    )

  return (
    <StudioView
      title="Audio Overview"
      description={status}
      action={
        <Button size="sm" disabled={!hasSources || generate.isPending || isActive(job)} onClick={submit}>
          Generate
        </Button>
      }
      onBack={onBack}
    >
      <div className={hasSources ? "grid grid-cols-2 gap-2" : "hidden"}>
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor={`${id}-format`} className="text-xs font-medium">
            Format
          </label>
          <Select value={format} onValueChange={(v) => {
              if (isFormat(v)) setFormat(v)
            }}
          >
            <SelectTrigger id={`${id}-format`} size="sm" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(FORMATS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor={`${id}-length`} className="text-xs font-medium">
            Length
          </label>
          <Select value={length} onValueChange={(v) => {
              if (isLength(v)) setLength(v)
            }}
          >
            <SelectTrigger id={`${id}-length`} size="sm" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(LENGTHS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="col-span-2 flex min-w-0 flex-col gap-1">
          <label htmlFor={`${id}-exam`} className="text-xs font-medium">
            Frame it for an exam (optional)
          </label>
          <Select value={examNames.includes(exam) ? exam : NO_EXAM} onValueChange={setExam}>
            <SelectTrigger id={`${id}-exam`} size="sm" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_EXAM}>No exam: the weakest concepts</SelectItem>
              {examNames.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {generate.error && <ErrorNote error={generate.error} />}
      {job && <JobRow job={job} typical={PODCAST_TYPICAL} />}
      {podcasts.isPending ? (
        <Pending label="Loading episodes" />
      ) : podcasts.isError ? (
        <ErrorNote error={podcasts.error} />
      ) : episodes.length === 0 ? (
        <EmptyState
          className="py-4"
          message={hasSources ? "No episodes yet. Generate one aimed at your weakest concepts." : "Add sources first."}
        />
      ) : (
        <ul aria-label="Episodes" className="flex flex-col divide-y">
          {episodes.map((episode) => (
            <EpisodeRow key={episode.id} course={course} episode={episode} />
          ))}
        </ul>
      )}
    </StudioView>
  )
}

function EpisodeRow({ course, episode }: { course: string; episode: Episode }) {
  const names = new Map((useConcepts(course, true).data ?? []).map((c) => [c.concept_id, c.name]))
  const targets = episode.concepts.map((id) => names.get(id) ?? id)
  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{formatWhen(episode.created_at)}</p>
          <p className="line-clamp-2 text-xs text-muted-foreground">
            {targets.length ? `On ${targets.join(", ")}` : "No concepts targeted"}
          </p>
        </div>
        <BriefDialog course={course} episode={episode} />
      </div>
      <audio controls preload="none" src={episode.audio_url} className="h-10 w-full" aria-label={`Episode of ${formatWhen(episode.created_at)}`}>
        <a href={episode.audio_url}>Download the episode</a>
      </audio>
    </li>
  )
}

function BriefDialog({ course, episode }: { course: string; episode: Episode }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost">
          Brief
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] grid-rows-[auto_minmax(0,1fr)] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Episode brief</DialogTitle>
          <DialogDescription>The instructions NotebookLM was given for the episode of {formatWhen(episode.created_at)}.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto pr-1">
          <BriefBody course={course} id={episode.id} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function BriefBody({ course, id }: { course: string; id: number }) {
  return <TextBody query={useBrief(course, id)} label="Loading the brief" />
}
