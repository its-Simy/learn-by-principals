// The Studio rail, after NotebookLM's: a home of tiles, or the view of the tool a tile opened, or the editor
// that view opened (a new exam's spec, a concept draft). The rail's body is already a ScrollArea.
import { useEffect, useRef } from "react"

import { AudioOverviewView } from "@/features/studio/AudioOverviewView"
import { ConceptsView } from "@/features/studio/ConceptsView"
import { DraftEditor } from "@/features/studio/DraftEditor"
import { ExamEditor } from "@/features/studio/ExamEditor"
import { MasteryView } from "@/features/studio/MasteryView"
import { PracticeExamView } from "@/features/studio/PracticeExamView"
import {
  AUDIO,
  CONCEPTS,
  draftOf,
  draftView,
  EXAMS,
  HOME,
  MASTERY,
  NEW_EXAM,
  OPENER,
  parentView,
  useStudioState,
} from "@/features/studio/store"
import { StudioHome } from "@/features/studio/StudioHome"

export function StudioPane({ course }: { course: string }) {
  // Which view is open, kept while the rail is collapsed (store.ts names them).
  const [view, setView] = useStudioState(`${course}:view`, HOME)
  const closed = useRef<string | null>(null)
  const back = () => {
    const parent = parentView(view)
    if (parent === null) return
    closed.current = view
    setView(parent)
  }
  useEffect(() => {
    if (closed.current === null) return
    // Back lands the focus on what opened the closed view (its tile, New exam, a draft row), which the parent
    // view renders. When that control is disabled meanwhile (New exam while an exam generates) or gone, the
    // parent view's own heading keeps the focus it took on mount.
    const opener = document.querySelector<HTMLElement>(`[${OPENER}="${CSS.escape(closed.current)}"]`)
    closed.current = null
    if (opener && !opener.matches(":disabled")) opener.focus()
  }, [view])

  const draft = draftOf(view)
  if (view === NEW_EXAM) return <ExamEditor course={course} onBack={back} />
  if (draft !== null) return <DraftEditor course={course} name={draft} onBack={back} />
  if (view === MASTERY) return <MasteryView course={course} onBack={back} />
  if (view === EXAMS) return <PracticeExamView course={course} onBack={back} onNewExam={() => setView(NEW_EXAM)} />
  if (view === AUDIO) return <AudioOverviewView course={course} onBack={back} />
  if (view === CONCEPTS) return <ConceptsView course={course} onBack={back} onOpenDraft={(name) => setView(draftView(name))} />
  return <StudioHome course={course} onOpen={setView} />
}
