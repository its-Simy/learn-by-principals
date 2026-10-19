// A new practice exam: its spec as YAML, prefilled from the server's template; Create queues the generation job.
import { useId } from "react"

import { conflictCode } from "@/api/client"
import { useCreateExam, useExamTemplate } from "@/api/queries.studio"
import { Pending } from "@/components/Pending"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ErrorNote, Note } from "@/features/studio/notes"
import { StudioView } from "@/features/studio/StudioView"
import { isUnprocessable, useCardJob, useStudioState } from "@/features/studio/store"

type ExamEditorProps = { course: string; onBack: () => void }

export function ExamEditor({ course, onBack }: ExamEditorProps) {
  const template = useExamTemplate(course)
  // The spec being written outlives the rail closing; null means "the template".
  const [edited, setEdited] = useStudioState<string | null>(`${course}:exam-spec`, null)
  const create = useCreateExam(course)
  const [, start] = useCardJob(course, "exam_create", "exam_create")
  const id = useId()

  const text = edited ?? template.data?.text ?? ""
  const error = create.error

  return (
    <StudioView
      title="New practice exam"
      backLabel="Back to Practice exams"
      description="Which weeks, sources, formats and difficulty to cover. Generating takes a few minutes; the exam appears in Practice exams when it is ready."
      onBack={onBack}
    >
      {template.isPending ? (
        <Pending label="Loading the template" />
      ) : template.isError ? (
        <ErrorNote error={template.error} />
      ) : (
        <div className="flex flex-col gap-2">
          <label htmlFor={`${id}-spec`} className="text-xs font-medium">
            Exam spec (YAML)
          </label>
          <Textarea
            id={`${id}-spec`}
            value={text}
            onChange={(e) => {
              setEdited(e.target.value)
              create.reset()
            }}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            aria-invalid={isUnprocessable(error) || undefined}
            aria-describedby={error ? `${id}-error` : undefined}
            className="max-h-[60dvh] min-h-56 font-mono text-xs leading-relaxed md:text-xs"
          />
          {error && (
            <div id={`${id}-error`}>
              {conflictCode(error) ? <Note>{error.message}</Note> : <ErrorNote error={error} />}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={create.isPending || !text.trim()}
              onClick={() =>
                create.mutate(text, {
                  onSuccess: (job) => {
                    start(job)
                    onBack() // the Practice exams view shows the job, then the exam
                  },
                })
              }
            >
              {create.isPending ? "Checking…" : "Create"}
            </Button>
            {edited !== null && edited !== template.data.text && (
              <Button size="sm" variant="ghost" onClick={() => setEdited(null)}>
                Reset to template
              </Button>
            )}
          </div>
        </div>
      )}
    </StudioView>
  )
}
