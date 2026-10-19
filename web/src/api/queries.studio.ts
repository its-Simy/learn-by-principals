// Studio pane hooks (BL-049): concepts and their drafts, practice exams and attempts, Audio Overviews.
// Every query is keyed through `keys`, so the job that writes it refreshes it; every job a hook
// submits goes through `trackJob`, so the watcher toasts it and refreshes what it wrote.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"

import { api, unwrap } from "@/api/client"
import { keys, trackJob } from "@/api/jobs"
import { useSources } from "@/api/queries.sources"
import type { components } from "@/api/types"

type Schemas = components["schemas"]
export type Concept = Schemas["ConceptOut"]
export type Evidence = Schemas["EvidenceOut"]
export type Draft = Schemas["DraftOut"]
export type ApplyResult = Schemas["ApplyOut"]
export type Exam = Schemas["ExamOut"]
export type Attempt = Schemas["AttemptOut"]
export type TakeState = Schemas["TakeOut"]
export type Question = Schemas["QuestionOut"]
export type ExamResults = Schemas["ResultsOut"]
export type QuestionResult = Schemas["QuestionResultOut"]
export type ConceptScore = Schemas["ConceptScoreOut"]
export type Episode = Schemas["EpisodeOut"]
export type PodcastRequest = Schemas["PodcastIn"]
export type PodcastFormat = PodcastRequest["format"]
export type PodcastLength = NonNullable<PodcastRequest["length"]>

const path = (course: string) => ({ params: { path: { course } } })
const examPath = (course: string, exam_id: string) => ({ params: { path: { course, exam_id } } })

// -- concepts ------------------------------------------------------------------------------

/** Active concepts with their mastery; `includeRetired` adds the ones a reviewed draft dropped. */
export function useConcepts(course: string, includeRetired = false) {
  return useQuery({
    queryKey: includeRetired ? keys.allConcepts(course) : keys.concepts(course),
    queryFn: () =>
      unwrap(
        api.GET("/api/courses/{course}/concepts", {
          params: { path: { course }, query: { include_retired: includeRetired } },
        }),
      ),
  })
}

export function useEvidence(course: string, conceptId: string | null) {
  return useQuery({
    queryKey: keys.evidence(course, conceptId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/courses/{course}/concepts/evidence", {
          params: { path: { course }, query: { concept_id: conceptId ?? "" } },
        }),
      ),
    enabled: conceptId !== null,
  })
}

/** Queue a seed job; a 409 (`session_open`, `ask_running`) is the mutation's error. */
export function useSeed(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/courses/{course}/concepts/seed", path(course))),
    onSuccess: (job) => trackJob(queryClient, job),
  })
}

/** Newest first. */
export function useDrafts(course: string) {
  return useQuery({
    queryKey: keys.drafts(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/concepts/drafts", path(course))),
  })
}

const draftPath = (course: string, name: string) => ({ params: { path: { course, name } } })

export function useDraftText(course: string, name: string) {
  return useQuery({
    queryKey: keys.draft(course, name),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/concepts/drafts/{name}", draftPath(course, name))),
  })
}

/** The diff from the draft before this one ("" for the first), following any edits since. */
export function useDraftDiff(course: string, name: string) {
  return useQuery({
    queryKey: keys.diff(course, name),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/concepts/drafts/{name}/diff", draftPath(course, name))),
  })
}

/** Replace the draft; a draft apply couldn't load is a 422 whose message names the problem. */
export function useSaveDraft(course: string, name: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(api.PUT("/api/courses/{course}/concepts/drafts/{name}", { ...draftPath(course, name), body: { text } })),
    onSuccess: (_draft, text) => {
      queryClient.setQueryData(keys.draft(course, name), { text })
      void queryClient.invalidateQueries({ queryKey: keys.drafts(course), exact: true })
      void queryClient.invalidateQueries({ queryKey: keys.diff(course, name) })
    },
  })
}

/** Load a reviewed draft into the concepts; `reviewed: false` is a 422. */
export function useApplyDraft(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (draft: string) =>
      unwrap(api.POST("/api/courses/{course}/concepts/apply", { ...path(course), body: { draft } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.concepts(course) }),
  })
}

// -- exams ---------------------------------------------------------------------------------

/** Newest first. */
export function useExams(course: string) {
  return useQuery({
    queryKey: keys.exams(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/exams", path(course))),
  })
}

export function useExam(course: string, id: string) {
  return useQuery({
    queryKey: keys.exam(course, id),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/exams/{exam_id}", examPath(course, id))),
  })
}

/** A commented spec that the parser accepts, to start the new-exam editor from. */
export function useExamTemplate(course: string) {
  return useQuery({
    queryKey: keys.template(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/exams/template", path(course))),
    staleTime: Infinity,
  })
}

/** The spec is parsed before anything is queued: a bad one is a 422 naming the problem. */
export function useCreateExam(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (specYaml: string) =>
      unwrap(api.POST("/api/courses/{course}/exams", { ...path(course), body: { spec_yaml: specYaml } })),
    onSuccess: (job) => trackJob(queryClient, job),
  })
}

/** The printable paper, answer key included. */
export function usePaper(course: string, id: string) {
  return useQuery({
    queryKey: keys.paper(course, id),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/exams/{exam_id}/markdown", examPath(course, id))),
  })
}

/** Where the latest attempt stands, read only: it never opens an attempt. */
export function useTakeState(course: string, id: string) {
  return useQuery({
    queryKey: keys.take(course, id),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/exams/{exam_id}/take", examPath(course, id))),
  })
}

function tookStep(queryClient: QueryClient, course: string, id: string, state: TakeState): void {
  queryClient.setQueryData(keys.take(course, id), state)
  // The list's attempt summaries; not the exam's sub-keys, which would refetch the state just set.
  void queryClient.invalidateQueries({ queryKey: keys.exams(course), exact: true })
  void queryClient.invalidateQueries({ queryKey: keys.exam(course, id), exact: true })
}

/**
 * The take steps. `open` resumes the unfinished attempt or starts the next one; `answer`, `skip`
 * and `finish` act on the unfinished one (409 `no_open_attempt` otherwise). All four are 409
 * `job_running` while a grade job is queued or running on the course.
 */
export function useTakeSteps(course: string, id: string) {
  const queryClient = useQueryClient()
  const onSuccess = (state: TakeState) => tookStep(queryClient, course, id, state)
  const at = examPath(course, id)
  return {
    open: useMutation({
      mutationFn: () => unwrap(api.POST("/api/courses/{course}/exams/{exam_id}/take", at)),
      onSuccess,
    }),
    answer: useMutation({
      mutationFn: (reply: string) =>
        unwrap(api.POST("/api/courses/{course}/exams/{exam_id}/take/answer", { ...at, body: { reply } })),
      onSuccess,
    }),
    skip: useMutation({
      mutationFn: () => unwrap(api.POST("/api/courses/{course}/exams/{exam_id}/take/skip", at)),
      onSuccess,
    }),
    finish: useMutation({
      mutationFn: () => unwrap(api.POST("/api/courses/{course}/exams/{exam_id}/take/finish", at)),
      onSuccess,
    }),
  }
}

/** Queue grading of the latest attempt; one not handed in yet is a 422. */
export function useGrade(course: string, id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/courses/{course}/exams/{exam_id}/grade", examPath(course, id))),
    onSuccess: (job) => trackJob(queryClient, job),
  })
}

/** The latest graded attempt with the reference answers; 404 until one is graded. */
export function useResults(course: string, id: string) {
  return useQuery({
    queryKey: keys.results(course, id),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/exams/{exam_id}/results", examPath(course, id))),
    retry: false,
  })
}

// -- Audio Overviews -----------------------------------------------------------------------

/** Newest first. */
export function usePodcasts(course: string) {
  return useQuery({
    queryKey: keys.podcasts(course),
    queryFn: () => unwrap(api.GET("/api/courses/{course}/podcasts", path(course))),
  })
}

export function useGeneratePodcast(course: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: PodcastRequest) => unwrap(api.POST("/api/courses/{course}/podcast", { ...path(course), body })),
    onSuccess: (job) => trackJob(queryClient, job),
  })
}

/** The instructions an episode was generated from. */
export function useBrief(course: string, podcastId: number) {
  return useQuery({
    queryKey: keys.brief(course, podcastId),
    queryFn: () =>
      unwrap(api.GET("/api/podcasts/{podcast_id}/brief", { params: { path: { podcast_id: podcastId } } })),
  })
}

// -- sources, read for the cards' empty states ---------------------------------------------

/** How many of the course's sources are in NotebookLM (0 while loading). */
export function useLinkedSourceCount(course: string): number {
  return useSources(course).data?.filter((s) => s.linked).length ?? 0
}
