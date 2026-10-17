// One course, chat-first: Sources rail on the left, the chat in the middle, Studio rail on the right.
import { FileText, Sparkles } from "lucide-react"
import { useParams } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { Rail } from "@/components/Rail"
import { useSourceSelection } from "@/features/sources/selection"
import { SourcesPane } from "@/features/sources/SourcesPane"

export function CoursePage() {
  // Upper-cased as the API does, so query keys match the ones a finished job refreshes.
  const course = (useParams().course ?? "").toUpperCase()
  // Here, not in the rail: a collapsed rail unmounts its pane, and the chat reads the selection.
  const [selectedSourceIds, setSelectedSourceIds] = useSourceSelection(course)
  return (
    <div className="flex h-full min-h-0">
      <Rail id="sources" title="Sources" icon={FileText} side="left" width={320}>
        <SourcesPane course={course} selected={selectedSourceIds} setSelected={setSelectedSourceIds} />
      </Rail>
      <section aria-label="Chat" className="flex min-w-0 flex-1 flex-col bg-background">
        <EmptyState className="flex-1" message="The chat arrives with BL-048." />
      </section>
      <Rail id="studio" title="Studio" icon={Sparkles} side="right" width={360}>
        <EmptyState message="The Studio pane arrives with BL-049." />
      </Rail>
    </div>
  )
}
