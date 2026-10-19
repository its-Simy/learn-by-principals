// One message: the learner's on the right; tutor and source answers on the left as Markdown; notes small and quiet.
import { Info } from "lucide-react"
import type { ReactNode } from "react"

import { Markdown } from "@/components/Markdown"

import { CitationChips } from "./CitationChips"
import type { ChatMessage } from "./model"

type Shown = Exclude<ChatMessage, { kind: "error" }>

function Left({ caption, children, footer }: { caption: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex max-w-[92%] min-w-0 flex-col gap-1.5 self-start">
      <p className="px-1 text-xs text-muted-foreground">{caption}</p>
      <div className="min-w-0 rounded-2xl rounded-bl-md bg-muted px-4 py-3">{children}</div>
      {footer && <div className="px-1">{footer}</div>}
    </div>
  )
}

const IN_SESSION_NOTE =
  "Scoping is off during a session: this asked every source, in the session's own NotebookLM conversation."

/** `footer` goes under the bubble: the rate buttons under the last tutoring answer. */
export function Message({ message, footer }: { message: Shown; footer?: ReactNode }) {
  switch (message.kind) {
    case "learner":
      return (
        <div className="flex max-w-[85%] flex-col items-end gap-1 self-end">
          {message.tag && <p className="px-1 text-xs text-muted-foreground">{message.tag}</p>}
          <p className="rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[15px] leading-relaxed break-words whitespace-pre-wrap text-primary-foreground">
            {message.text}
          </p>
        </div>
      )
    case "tutor":
      return (
        <Left caption={message.label} footer={footer}>
          <Markdown>{message.text}</Markdown>
        </Left>
      )
    case "sources":
      return (
        <Left caption={`Sources · ${message.scope}`}>
          <Markdown>{message.text}</Markdown>
          {message.citations.length > 0 && (
            <div className="mt-3">
              <CitationChips citations={message.citations} />
            </div>
          )}
          {message.inSession && <p className="mt-3 text-xs text-muted-foreground">{IN_SESSION_NOTE}</p>}
        </Left>
      )
    case "note":
      return (
        <p className="flex max-w-[92%] items-start gap-2 self-start px-1 text-sm text-muted-foreground">
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span className="min-w-0 break-words whitespace-pre-line">{message.text}</span>
        </p>
      )
  }
}
