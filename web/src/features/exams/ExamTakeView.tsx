// Taking a practice exam, one question at a time. Every answer is saved by the API as it is given, so
// leaving or reloading never loses the place: the view reads where the attempt stands (GET take) and
// opens an attempt (POST take) only when the learner clicks Start.
import { useQueryClient } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react"
import { Link, useParams } from "react-router"

import { ApiError, conflictCode } from "@/api/client"
import { isActive, keys, useJob } from "@/api/jobs"
import { useExam, useGrade, useTakeState, useTakeSteps, type Exam, type Question, type TakeState } from "@/api/queries.studio"
import { JobRow } from "@/components/JobRow"
import { Markdown } from "@/components/Markdown"
import { Pending } from "@/components/Pending"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { fullyGraded, gradeJobFor } from "@/features/exams/grading"
import { ResultsDialog } from "@/features/exams/ResultsDialog"
import { letter } from "@/features/studio/format"
import { ErrorNote, Note } from "@/features/studio/StudioCard"
import { isUnprocessable, useCardJob, useStudioState } from "@/features/studio/store"

const FORMAT_LABEL: Record<Question["format"], string> = {
  multiple_choice: "Multiple choice",
  short_answer: "Short answer",
  coding: "Coding",
}

/** A status line that takes the focus as it appears, so keyboard and screen-reader users land on what changed. */
function FocusLine({ children }: { children: ReactNode }) {
  const line = useRef<HTMLParagraphElement>(null)
  useEffect(() => line.current?.focus(), [])
  return (
    <p ref={line} tabIndex={-1} className="text-sm outline-none">
      {children}
    </p>
  )
}

/** The job a 409 `job_running` names, if it names one. */
function blockingJobId(error: unknown): string | undefined {
  if (conflictCode(error) !== "job_running" || !(error instanceof ApiError)) return undefined
  const body = error.body
  if (typeof body !== "object" || body === null || !("job_id" in body)) return undefined
  return typeof body.job_id === "string" ? body.job_id : undefined
}

export function ExamTakeView() {
  const params = useParams()
  // Upper-cased as the API returns courses, so the jobs watcher's invalidation (by job.course) matches these keys.
  const course = (params.course ?? "").toUpperCase()
  const id = params.id ?? ""
  const exam = useExam(course, id)
  const state = useTakeState(course, id)
  const coursePath = `/courses/${encodeURIComponent(course)}`

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6">
        <div className="flex flex-col gap-2">
          <div>
            <Button variant="ghost" size="sm" className="-ml-2" asChild>
              <Link to={coursePath}>
                <ArrowLeft />
                Back to course
              </Link>
            </Button>
          </div>
          <h2 className="text-lg font-semibold">{exam.data?.exam ?? "Practice exam"}</h2>
          {state.data && <Progress state={state.data} />}
        </div>
        {state.isPending ? (
          <Pending label="Loading the exam" />
        ) : state.isError ? (
          <ErrorNote error={state.error} />
        ) : (
          <Attempt course={course} id={id} state={state.data} exam={exam.data} coursePath={coursePath} />
        )}
      </div>
    </div>
  )
}

function Progress({ state }: { state: TakeState }) {
  if (state.attempt === null) return <p className="text-sm text-muted-foreground">{state.total} questions · not taken yet</p>
  const done = state.answered + state.skipped
  const unreached = state.total - done // handed in early: graded as skipped
  const text = state.finished
    ? `Attempt ${state.attempt} handed in · ${state.answered} answered, ${state.skipped} skipped` +
      (unreached > 0 ? `, ${unreached} not reached` : "")
    : state.question
      ? `Attempt ${state.attempt} · ${done + 1} of ${state.total}`
      : `Attempt ${state.attempt} · all ${state.total} done`
  return (
    <p aria-live="polite" className="text-sm text-muted-foreground">
      {text}
    </p>
  )
}

type AttemptProps = { course: string; id: string; state: TakeState; exam: Exam | undefined; coursePath: string }

function Attempt({ course, id, state, exam, coursePath }: AttemptProps) {
  const queryClient = useQueryClient()
  const steps = useTakeSteps(course, id)
  const [error, setError] = useState<unknown>(null)
  const busy = steps.open.isPending || steps.answer.isPending || steps.skip.isPending || steps.finish.isPending
  const handlers = {
    onSuccess: () => setError(null),
    onError: (e: unknown) => {
      setError(e)
      // Handed in elsewhere (another tab, the CLI): show where the attempt really stands.
      if (conflictCode(e) === "no_open_attempt") void queryClient.invalidateQueries({ queryKey: keys.take(course, id) })
    },
  }
  const open = () => steps.open.mutate(undefined, handlers)
  const finish = () => steps.finish.mutate(undefined, handlers)
  // A grading refusal lasts only as long as the grade job: once it leaves the active state the note goes.
  const blocking = useJob(blockingJobId(error))
  const shown = blocking.data && !isActive(blocking.data) ? null : error

  // A 422 belongs under the answer; a 409 says why the step waits; anything else is a failure.
  const code = conflictCode(shown)
  const notice =
    code === "job_running" ? (
      <Note>Grading is in progress on this course. Your answers are saved; carry on once it has finished.</Note>
    ) : code && shown instanceof Error ? (
      <Note>{shown.message}</Note>
    ) : shown && !isUnprocessable(shown) ? (
      <ErrorNote error={shown} />
    ) : null

  if (state.attempt === null) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-sm">
          {state.total} questions, one at a time. Each answer is saved as you give it, so you can leave and come back to where you were.
        </p>
        {notice}
        <div>
          <Button disabled={busy} onClick={open}>
            {steps.open.isPending ? "Starting…" : "Start"}
          </Button>
        </div>
      </div>
    )
  }

  if (state.finished) {
    return (
      <HandedIn course={course} id={id} state={state} exam={exam} coursePath={coursePath}>
        {notice}
        <div>
          <Button variant="outline" disabled={busy} onClick={open}>
            {steps.open.isPending ? "Starting…" : `Take again (attempt ${state.attempt + 1})`}
          </Button>
        </div>
      </HandedIn>
    )
  }

  if (!state.question) {
    return (
      <div className="flex flex-col gap-4">
        <FocusLine>Every question has an answer or was skipped. Finish to hand the attempt in for grading.</FocusLine>
        {notice}
        <div>
          <Button disabled={busy} onClick={finish}>
            {steps.finish.isPending ? "Handing in…" : "Finish"}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <QuestionForm
      key={`${state.attempt}:${state.question.index}`}
      draftKey={`${course}:take:${id}:${state.attempt}:${state.question.index}`}
      question={state.question}
      later={state.total - state.answered - state.skipped - 1}
      busy={busy}
      error={isUnprocessable(shown) ? shown : null}
      notice={notice}
      onAnswer={(reply) => steps.answer.mutate(reply, handlers)}
      onSkip={() => steps.skip.mutate(undefined, handlers)}
      onFinish={finish}
    />
  )
}

type QuestionFormProps = {
  /** Where the typed but unsent answer is kept, so leaving the view and coming back keeps it. */
  draftKey: string
  question: Question
  /** Questions after this one not yet answered or skipped. */
  later: number
  busy: boolean
  /** This answer's 422: a multiple-choice reply that picks no option, or an empty one. */
  error: Error | null
  notice: ReactNode
  onAnswer: (reply: string) => void
  onSkip: () => void
  onFinish: () => void
}

function QuestionForm({ draftKey, question, later, busy, error, notice, onAnswer, onSkip, onFinish }: QuestionFormProps) {
  const [reply, setReply] = useStudioState(draftKey, "")
  const [confirming, setConfirming] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const ids = useId()
  // Each question takes the focus as it appears, so keyboard and screen-reader users start at its stem.
  useEffect(() => heading.current?.focus(), [])

  const send = () => {
    if (reply.trim() && !busy) onAnswer(reply)
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    send()
  }
  const coding = question.format === "coding"
  const errorId = `${ids}-err`

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-labelledby={`${ids}-q`}>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 ref={heading} id={`${ids}-q`} tabIndex={-1} className="text-sm font-medium outline-none">
            Question {question.index + 1}
          </h3>
          <Badge variant="secondary">{FORMAT_LABEL[question.format]}</Badge>
          <Badge variant="secondary">{question.difficulty}</Badge>
        </div>
        <Markdown>{question.stem}</Markdown>
      </div>

      {question.format === "multiple_choice" ? (
        <fieldset className="flex flex-col gap-2" aria-describedby={error ? errorId : undefined}>
          <legend className="sr-only">Choose one option</legend>
          {(question.options ?? []).map((option, i) => {
            const value = letter(i)
            return (
              <label
                key={value}
                className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 text-sm hover:bg-accent has-checked:border-foreground/40 has-checked:bg-accent has-focus-visible:ring-[3px] has-focus-visible:ring-ring/50"
              >
                <input
                  type="radio"
                  name={`${ids}-mc`}
                  value={value}
                  checked={reply === value}
                  onChange={() => setReply(value)}
                  className="mt-0.5 size-4 shrink-0 accent-primary outline-none"
                />
                <span className="font-medium">{value}.</span>
                <span className="min-w-0 break-words">{option}</span>
              </label>
            )
          })}
        </fieldset>
      ) : (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${ids}-reply`} className="text-xs font-medium">
            {coding ? "Your code" : "Your answer"}
          </label>
          <Textarea
            id={`${ids}-reply`}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                send()
              }
            }}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${errorId} ${ids}-hint` : `${ids}-hint`}
            spellCheck={!coding}
            autoCapitalize={coding ? "off" : undefined}
            autoCorrect={coding ? "off" : undefined}
            className={coding ? "min-h-56 font-mono text-sm md:text-sm" : "min-h-32"}
          />
          <p id={`${ids}-hint`} className="text-xs text-muted-foreground">
            Ctrl+Enter (⌘+Enter on a Mac) sends the answer.
          </p>
        </div>
      )}
      {error && (
        <div id={errorId}>
          <ErrorNote error={error} />
        </div>
      )}
      {notice}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={busy || !reply.trim()}>
          Answer
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onSkip}>
          Skip
        </Button>
        <Button type="button" variant="ghost" disabled={busy} aria-expanded={confirming} onClick={() => setConfirming(true)}>
          Finish
        </Button>
      </div>
      {confirming && (
        <div className="flex flex-col gap-2 rounded-lg border bg-muted/50 p-3 text-sm">
          <p>
            Hand the attempt in now? This question{later > 0 && ` and the ${later} after it`} will count as skipped.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" disabled={busy} onClick={onFinish}>
              Hand in
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
              Keep going
            </Button>
          </div>
        </div>
      )}
    </form>
  )
}

type HandedInProps = AttemptProps & { children: ReactNode }

/** After Finish: grade the attempt (a job), read its results, go back to the course or take it again. */
function HandedIn({ course, id, state, exam, coursePath, children }: HandedInProps) {
  const grade = useGrade(course, id)
  // The Studio card's slot for this exam, so the card shows this grade job too.
  const [remembered, start] = useCardJob(course, `grade:${id}`)
  // The exam list's summary of this attempt, once it has caught up with the take state.
  const latest = exam?.attempts.at(-1)
  const attempt = latest !== undefined && latest.attempt === state.attempt ? latest : undefined
  const job = gradeJobFor(remembered, id, attempt)
  const graded = attempt !== undefined && fullyGraded(attempt)
  const anyGraded = exam?.attempts.some((a) => a.graded > 0) ?? false
  const grading = grade.isPending || isActive(job)

  return (
    <div className="flex flex-col gap-4">
      <FocusLine>
        {!graded
          ? `Attempt ${state.attempt} is handed in. Grade it to see how you did and to update your mastery.`
          : attempt.answered === 0
            ? `Attempt ${state.attempt} is handed in with no answers, so there is nothing to grade.`
            : `Attempt ${state.attempt} is graded: ${attempt.correct} of ${attempt.graded} correct.`}
      </FocusLine>
      {grade.error && <ErrorNote error={grade.error} />}
      {job && <JobRow job={job} />}
      <div className="flex flex-wrap gap-2">
        {!graded && (
          <Button disabled={grading} onClick={() => grade.mutate(undefined, { onSuccess: start })}>
            {grading ? "Grading…" : "Grade"}
          </Button>
        )}
        {anyGraded && exam && (
          <ResultsDialog
            course={course}
            examId={id}
            examName={exam.exam}
            trigger={<Button variant={graded ? "default" : "outline"}>Results</Button>}
          />
        )}
        <Button variant="outline" asChild>
          <Link to={coursePath}>Back to course</Link>
        </Button>
      </div>
      <div className="flex flex-col gap-2 border-t pt-4">{children}</div>
    </div>
  )
}
