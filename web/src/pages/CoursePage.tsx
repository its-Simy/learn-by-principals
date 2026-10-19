// One course, chat-first: Sources rail on the left, the chat area in the middle, Studio rail on the right.
// The chat area is the route's outlet: the chat itself, or an exam being taken (App.tsx).
import { FileText, Sparkles } from "lucide-react"
import { Outlet, useMatch, useOutletContext, useParams } from "react-router"

import { Rail } from "@/components/Rail"
import { ChatPane } from "@/features/chat/ChatPane"
import { useSourceSelection } from "@/features/sources/selection"
import { SourcesPane } from "@/features/sources/SourcesPane"
import { StudioPane } from "@/features/studio/StudioPane"

/** What the course page hands the view in its chat area. */
type CourseOutlet = { course: string; selectedSourceIds: string[] }

export function CoursePage() {
  // Upper-cased as the API does, so query keys match the ones a finished job refreshes.
  const course = (useParams().course ?? "").toUpperCase()
  // Here, not in the rail: a collapsed rail unmounts its pane, and the chat reads the selection.
  const [selectedSourceIds, setSelectedSourceIds] = useSourceSelection(course)
  const outlet: CourseOutlet = { course, selectedSourceIds }
  const taking = useMatch("/courses/:course/exams/:id/take") !== null
  return (
    <div className="flex h-full min-h-0">
      <Rail id="sources" title="Sources" icon={FileText} side="left" width={320}>
        <SourcesPane course={course} selected={selectedSourceIds} setSelected={setSelectedSourceIds} />
      </Rail>
      <section aria-label={taking ? "Practice exam" : "Chat"} className="flex min-w-0 flex-1 flex-col bg-background">
        <Outlet context={outlet} />
      </section>
      <Rail id="studio" title="Studio" icon={Sparkles} side="right" width={360}>
        <StudioPane course={course} />
      </Rail>
    </div>
  )
}

/** The chat area's index route: the chat, asking the sources checked in the Sources rail. */
export function CourseChat() {
  const { course, selectedSourceIds } = useOutletContext<CourseOutlet>()
  return <ChatPane course={course} selectedSourceIds={selectedSourceIds} />
}
