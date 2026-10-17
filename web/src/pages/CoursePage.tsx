// One course, chat-first: Sources rail on the left, the chat in the middle, Studio rail on the right.
import { FileText, Sparkles } from "lucide-react"

import { EmptyState } from "@/components/EmptyState"
import { Rail } from "@/components/Rail"

export function CoursePage() {
  return (
    <div className="flex h-full min-h-0">
      <Rail id="sources" title="Sources" icon={FileText} side="left" width={320}>
        <EmptyState message="The Sources pane arrives with BL-047 part 2." />
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
