// The Studio rail: four cards ordered by what matters to the learner, or one editor view in their place.
// The rail's body is already a ScrollArea, so the pane is a plain column inside it.
import { useEffect, useRef } from "react"

import { AudioOverviewCard } from "@/features/studio/AudioOverviewCard"
import { ConceptsCard } from "@/features/studio/ConceptsCard"
import { DraftEditor } from "@/features/studio/DraftEditor"
import { ExamEditor } from "@/features/studio/ExamEditor"
import { MasteryCard } from "@/features/studio/MasteryCard"
import { PracticeExamCard } from "@/features/studio/PracticeExamCard"
import { OPENER, useStudioState } from "@/features/studio/store"

const CARDS = "cards"
const NEW_EXAM = "new-exam"
const DRAFT = "draft:"

export function StudioPane({ course }: { course: string }) {
  // Which view is open, kept while the rail is collapsed: "cards", "new-exam" or "draft:{name}".
  const [view, setView] = useStudioState(`${course}:view`, CARDS)
  const closed = useRef<string | null>(null)
  const back = () => {
    closed.current = view
    setView(CARDS)
  }
  useEffect(() => {
    if (view !== CARDS || closed.current === null) return
    const opener = document.querySelector<HTMLElement>(`[${OPENER}="${CSS.escape(closed.current)}"]`)
    closed.current = null
    // New exam is disabled while the exam it just queued is generating: its card's heading instead.
    if (opener?.matches(":disabled")) opener.closest('[role="region"]')?.querySelector<HTMLElement>("h3")?.focus()
    else opener?.focus()
  }, [view])

  if (view === NEW_EXAM) return <ExamEditor course={course} onBack={back} />
  if (view.startsWith(DRAFT)) return <DraftEditor course={course} name={view.slice(DRAFT.length)} onBack={back} />
  return (
    <div className="flex flex-col gap-4">
      <MasteryCard course={course} />
      <PracticeExamCard course={course} onNewExam={() => setView(NEW_EXAM)} />
      <AudioOverviewCard course={course} />
      <ConceptsCard course={course} onOpenDraft={(name) => setView(`${DRAFT}${name}`)} />
    </div>
  )
}
