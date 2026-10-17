// A graded attempt, read only: per concept, then per question with the learner's answer, the verdict, feedback and the reference answer.
import type { ReactNode } from "react"

import { useResults, type ConceptScore, type ExamResults, type QuestionResult } from "@/api/queries.studio"
import { Markdown } from "@/components/Markdown"
import { Pending } from "@/components/Pending"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { letter, withLetter } from "@/features/studio/format"
import { ErrorNote } from "@/features/studio/StudioCard"
import { formatWhen } from "@/lib/format"

type ResultsDialogProps = {
  course: string
  examId: string
  examName: string
  /** The trigger; defaults to an outline "Results" button. */
  trigger?: ReactNode
}

export function ResultsDialog({ course, examId, examName, trigger }: ResultsDialogProps) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm" variant="outline">
            Results
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] grid-rows-[auto_minmax(0,1fr)] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Results: {examName}</DialogTitle>
          <DialogDescription>The latest graded attempt, with the reference answers.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto pr-1">
          <ResultsBody course={course} examId={examId} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ResultsBody({ course, examId }: { course: string; examId: string }) {
  const results = useResults(course, examId)
  if (results.isPending) return <Pending label="Loading the results" />
  if (results.isError) return <ErrorNote error={results.error} />
  return <Results results={results.data} />
}

function Results({ results }: { results: ExamResults }) {
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm">
        Attempt {results.attempt}: <span className="font-medium">{results.correct} of {results.graded} correct</span>
        <span className="text-muted-foreground"> · handed in {formatWhen(results.finished_at)}</span>
      </p>
      <section aria-label="By concept" className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">By concept</h3>
        <ScoreTable scores={results.scores} />
      </section>
      <section aria-label="By question" className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">By question</h3>
        <ol className="flex flex-col divide-y">
          {results.questions.map((q) => (
            <QuestionResultItem key={q.index} q={q} />
          ))}
        </ol>
      </section>
    </div>
  )
}

function levelChange(s: ConceptScore): string {
  if (s.level_before === null || s.level_after === null) return "not yet"
  return s.level_before === s.level_after ? `${s.level_after} (no change)` : `${s.level_before} → ${s.level_after}`
}

function ScoreTable({ scores }: { scores: ConceptScore[] }) {
  if (scores.length === 0) return <p className="text-sm text-muted-foreground">No concept was graded.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">Concept</th>
            <th scope="col" className="py-1 pr-3 font-medium">Correct</th>
            <th scope="col" className="py-1 font-medium">Level</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {scores.map((s) => (
            <tr key={s.concept_id}>
              <td className="py-1.5 pr-3">{s.name}</td>
              <td className="py-1.5 pr-3 tabular-nums">
                {s.correct} of {s.total}
              </td>
              <td className="py-1.5 tabular-nums">{levelChange(s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Verdict({ q }: { q: QuestionResult }) {
  if (q.skipped) return <StateBadge state="disabled" label="skipped" />
  if (q.correct === null) return <StateBadge state="pending" label="not graded" />
  return q.correct ? <StateBadge state="done" label="correct" /> : <StateBadge state="failed" label="incorrect" />
}

function AnswerText({ text, format }: { text: string; format: QuestionResult["format"] }) {
  if (format === "coding") {
    return <pre className="overflow-x-auto rounded-md border bg-background p-2 font-mono text-xs">{text}</pre>
  }
  return <p className="text-sm break-words whitespace-pre-wrap">{text}</p>
}

function QuestionResultItem({ q }: { q: QuestionResult }) {
  return (
    <li className="flex flex-col gap-2 py-4 first:pt-0">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-medium">Question {q.index + 1}</h4>
        <Verdict q={q} />
      </div>
      <Markdown className="text-sm">{q.stem}</Markdown>
      {q.options && (
        <ol className="flex flex-col gap-0.5 text-sm text-muted-foreground">
          {q.options.map((option, i) => (
            <li key={i}>
              {letter(i)}. {option}
            </li>
          ))}
        </ol>
      )}
      <dl className="grid gap-2">
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Your answer</dt>
          <dd>
            {q.your_answer === null ? (
              <span className="text-sm text-muted-foreground">{q.skipped ? "Skipped" : "No answer"}</span>
            ) : (
              <AnswerText text={withLetter(q.your_answer, q.options)} format={q.format} />
            )}
          </dd>
        </div>
        {q.feedback && (
          <div>
            <dt className="text-xs font-medium text-muted-foreground">Feedback</dt>
            <dd className="text-sm break-words whitespace-pre-wrap">{q.feedback}</dd>
          </div>
        )}
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Reference answer</dt>
          <dd>
            <AnswerText text={withLetter(q.reference_answer, q.options)} format={q.format} />
          </dd>
        </div>
      </dl>
    </li>
  )
}
