// The stream: every message and the pending bubble while a request is in flight. It follows the newest
// message while the reader is at the bottom, and after their own send; reading further up, it stays put.
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react"

import { ScrollArea } from "@/components/ui/scroll-area"

import { ErrorMessage } from "./ErrorMessage"
import { Message } from "./Message"
import type { ChatMessage } from "./model"
import { PendingMessage } from "./PendingMessage"
import { RateButtons } from "./RateButtons"

/** Within this many px of the end counts as reading the newest message. */
const AT_BOTTOM_PX = 80

type ErrorItem = Extract<ChatMessage, { kind: "error" }>

type MessageListProps = {
  messages: ChatMessage[]
  pending: { label: string; since: number } | null
  /** The tutoring answer `/rate` would rate, when the session can rate it. */
  ratableId: string | null
  onRate: (messageId: string, n: number) => void
  onRetry: (message: ErrorItem) => void
  onCloseSession: (message: ErrorItem, sessionId: string) => void
  /** Shown while there are no messages. */
  empty: ReactNode
}

export function MessageList({ messages, pending, ratableId, onRate, onRetry, onCloseSession, empty }: MessageListProps) {
  const end = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const lastLearner = useRef<string | null>(null)

  const viewport = () => end.current?.closest<HTMLElement>("[data-slot=scroll-area-viewport]") ?? null

  useEffect(() => {
    const el = viewport()
    if (!el) return
    const onScroll = () => {
      atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM_PX
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

  // Scroll the viewport itself (not the page). A new learner message is the reader's own send: follow it.
  useLayoutEffect(() => {
    const el = viewport()
    if (!el) return
    const newest = messages.findLast((m) => m.kind === "learner")?.id ?? null
    const sent = newest !== null && newest !== lastLearner.current
    lastLearner.current = newest
    if (sent || atBottom.current) {
      el.scrollTop = el.scrollHeight
      atBottom.current = true
    }
  }, [messages, pending])

  const busy = pending !== null
  return (
    // Radix wraps the content in a `display: table` div, which would let a wide code block widen the stream.
    <ScrollArea className="min-h-0 flex-1 [&_[data-slot=scroll-area-viewport]>div]:block!">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
        {messages.length === 0 && !busy && empty}
        {/* The log wraps the list so the list keeps its own semantics (n items). */}
        <div role="log" aria-label="Conversation" className="empty:hidden">
          {messages.length > 0 && (
            <ol className="flex flex-col gap-5">
              {messages.map((m) => (
                <li key={m.id} className="flex min-w-0 flex-col">
                  {m.kind === "error" ? (
                    <ErrorMessage
                      failure={m.failure}
                      handled={m.handled}
                      disabled={busy}
                      onRetry={m.retry ? () => onRetry(m) : undefined}
                      onCloseSession={(sessionId) => onCloseSession(m, sessionId)}
                    />
                  ) : (
                    <Message
                      message={m}
                      footer={
                        m.kind === "tutor" && (m.id === ratableId || m.rating) ? (
                          <RateButtons rating={m.rating} disabled={busy} onRate={(n) => onRate(m.id, n)} />
                        ) : undefined
                      }
                    />
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
        {/* Outside the log, so its own live region announces it once rather than as a log addition. */}
        {pending && <PendingMessage label={pending.label} since={pending.since} />}
        <div ref={end} />
      </div>
    </ScrollArea>
  )
}
