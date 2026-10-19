// Practice exams: write a spec and generate one, take it (its own view), grade it, read the results and the paper.
import { Link } from "react-router"

import { isActive } from "@/api/jobs"
import { useConcepts, useExams, useGrade, useLinkedSourceCount, usePaper, type Exam } from "@/api/queries.studio"
import { useModelsHint } from "@/api/queries.system"
import { EmptyState } from "@/components/EmptyState"
import { JobRow } from "@/components/JobRow"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { fullyGraded, gradeJobFor } from "@/features/exams/grading"
import { ResultsDialog } from "@/features/exams/ResultsDialog"
import { attemptsSummary } from "@/features/studio/format"
import { ErrorNote, TextBody } from "@/features/studio/notes"
import { NEW_EXAM, openerProps, useCardJob } from "@/features/studio/store"
import { StudioView } from "@/features/studio/StudioView"
import { formatWhen } from "@/lib/format"

export const CREATE_TYPICAL = "2–5 minutes"

export function takePath(course: string, examId: string): string {
  return `/courses/${encodeURIComponent(course)}/exams/${encodeURIComponent(examId)}/take`
}

type PracticeExamViewProps = { course: string; onNewExam: () => void; onBack: () => void }

export function PracticeExamView({ course, onNewExam, onBack }: PracticeExamViewProps) {
  const exams = useExams(course)
  const concepts = useConcepts(course)
  const linked = useLinkedSourceCount(course)
  const [createJob] = useCardJob(course, "exam_create", "exam_create")

  // An exam is planned from the concepts and grounded in the linked sources: without both it can't be good.
  const ready = (concepts.data?.length ?? 0) > 0 && linked > 0
  const modelsHint = useModelsHint()
  const list = exams.data ?? []
  const status = exams.data
    ? list.length === 0
      ? "No exams yet"
      : `${list.length} ${list.length === 1 ? "exam" : "exams"}`
    : undefined

  return (
    <StudioView
      title="Practice exams"
      description={modelsHint ? `${status ?? ""}${status ? " · " : ""}${modelsHint}` : status}
      action={
        <Button size="sm" disabled={!ready || isActive(createJob)} onClick={onNewExam} {...openerProps(NEW_EXAM)}>
          New exam
        </Button>
      }
      onBack={onBack}
    >
      {createJob && <JobRow job={createJob} typical={CREATE_TYPICAL} />}
      {exams.isPending ? (
        <Pending label="Loading exams" />
      ) : exams.isError ? (
        <ErrorNote error={exams.error} />
      ) : list.length === 0 ? (
        <EmptyState
          className="py-4"
          message={
            ready
              ? "No practice exams yet. New exam starts one from a template."
              : "Add sources and concepts before generating an exam."
          }
        />
      ) : (
        <ul aria-label="Practice exams" className="flex flex-col divide-y">
          {list.map((exam) => (
            <ExamRow key={exam.id} course={course} exam={exam} />
          ))}
        </ul>
      )}
    </StudioView>
  )
}

function ReviewBadge({ review }: { review: string | null }) {
  if (review === "critiqued") {
    return <StateBadge state="done" label="critiqued" hint="A second model reviewed every question" />
  }
  if (review === "uncritiqued") {
    return <StateBadge state="warn" label="uncritiqued" hint="Only one model was available, so no second model reviewed the questions" />
  }
  return null
}

function ExamRow({ course, exam }: { course: string; exam: Exam }) {
  const grade = useGrade(course, exam.id)
  const [remembered, startGrade] = useCardJob(course, `grade:${exam.id}`)
  const latest = exam.attempts.at(-1)
  const gradeJob = gradeJobFor(remembered, exam.id, latest)
  const anyGraded = exam.attempts.some((a) => a.graded > 0)
  const grading = grade.isPending || isActive(gradeJob)

  // Grade needs a handed-in attempt with answers still to grade.
  const gradeBlocked = !latest
    ? "Take the exam before grading it"
    : !latest.finished_at
      ? `Finish attempt ${latest.attempt} before grading it`
      : fullyGraded(latest)
        ? `Attempt ${latest.attempt} is graded`
        : null
  const takeLabel = !latest ? "Take" : latest.finished_at ? "Retake" : "Resume"
  const gradeReasonId = `grade-reason-${exam.id}`
  const resultsReasonId = `results-reason-${exam.id}`
  // Never taken: the summary line already says so.
  const showGradeReason = gradeBlocked !== null && !grading && latest !== undefined
  const showResultsReason = !anyGraded && latest !== undefined

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{exam.exam}</p>
          <p className="text-xs text-muted-foreground">
            {exam.questions} questions · {formatWhen(exam.created_at)}
          </p>
        </div>
        <ReviewBadge review={exam.review} />
      </div>
      <p className="text-xs">{attemptsSummary(exam.attempts, exam.questions)}</p>
      {/* Four actions on one line in a 360 px rail and a phone's sheet. */}
      <div className="flex flex-wrap gap-1.5 [&_[data-slot=button]]:px-2.5">
        <Button size="sm" asChild>
          <Link to={takePath(course, exam.id)}>{takeLabel}</Link>
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={gradeBlocked !== null || grading}
          aria-describedby={showGradeReason ? gradeReasonId : undefined}
          onClick={() => grade.mutate(undefined, { onSuccess: startGrade })}
        >
          Grade
        </Button>
        {anyGraded ? (
          <ResultsDialog course={course} examId={exam.id} examName={exam.exam} />
        ) : (
          <Button size="sm" variant="outline" disabled aria-describedby={showResultsReason ? resultsReasonId : undefined}>
            Results
          </Button>
        )}
        <PaperDialog course={course} exam={exam} />
      </div>
      {(showGradeReason || showResultsReason) && (
        <p className="text-xs text-muted-foreground">
          {showGradeReason && <span id={gradeReasonId}>{gradeBlocked}. </span>}
          {showResultsReason && <span id={resultsReasonId}>Results appear once an attempt is graded.</span>}
        </p>
      )}
      {grade.error && <ErrorNote error={grade.error} />}
      {gradeJob && <JobRow job={gradeJob} />}
    </li>
  )
}

function PaperDialog({ course, exam }: { course: string; exam: Exam }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost">
          Paper
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] grid-rows-[auto_minmax(0,1fr)] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Paper with answer key</DialogTitle>
          <DialogDescription>
            {exam.exam}: the questions, then the answer key and rubrics after a rule. Reading the key spoils the exam.
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto pr-1">
          <PaperBody course={course} examId={exam.id} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function PaperBody({ course, examId }: { course: string; examId: string }) {
  return <TextBody query={usePaper(course, examId)} label="Loading the paper" />
}
