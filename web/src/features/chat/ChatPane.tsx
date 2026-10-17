// The chat (BL-048): one message stream driven by session state. With no live session every message is a
// grounded ask scoped to the selected sources; with one, messages are tutor turns (or asks, with "Sources only").
// The stream is client state rebuilt from the session's turns on load; asks and command replies are not kept
// (a reload, or the take view replacing the chat for an exam, drops them), the transcript is the record, as on
// the CLI.
import { useEffect, useRef, useState } from "react"

import {
  failureOf,
  useAsk,
  useCloseSession,
  useEndSession,
  useLiveSession,
  useStartSession,
  useTeachingPersonas,
  useTurn,
  type AskResult,
  type Failure,
} from "@/api/queries.chat"
import { useSources } from "@/api/queries.sources"
import { EmptyState } from "@/components/EmptyState"
import { plural } from "@/lib/format"

import { Composer } from "./Composer"
import { MessageList } from "./MessageList"
import {
  askedQuestion,
  isRateLine,
  messagesFrom,
  newId,
  pendingLabel,
  probeMessage,
  turnFailure,
  tutorLabel,
  type ChatMessage,
  type ChatRequest,
  type TurnPurpose,
} from "./model"
import { ProbeBanner } from "./ProbeBanner"
import { SessionBanner } from "./SessionBanner"

const DEFAULT_PERSONA = "simplifier"

type ChatPaneProps = {
  course: string
  /** The Sources pane's checked sources, as NotebookLM source ids. None, or all of them, asks every source. */
  selectedSourceIds: string[]
}

export function ChatPane(props: ChatPaneProps) {
  // The course page stays mounted when the course changes: another course starts its own stream.
  return <ChatStream key={props.course} {...props} />
}

function sourcesMessage(out: AskResult, scope: string): ChatMessage {
  return { id: newId(), kind: "sources", text: out.text, citations: out.citations, scope, inSession: out.in_session }
}

function errorMessage(failure: Failure, retry?: ChatRequest): ChatMessage {
  return { id: newId(), kind: "error", failure, retry }
}

function ChatStream({ course, selectedSourceIds }: ChatPaneProps) {
  const live = useLiveSession(course)
  const personas = useTeachingPersonas()
  const sources = useSources(course)
  const startSession = useStartSession(course)
  const turn = useTurn(course)
  const endSession = useEndSession(course)
  const ask = useAsk(course)
  const closeSession = useCloseSession(course)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [built, setBuilt] = useState(false)
  const [mountedAt] = useState(Date.now)
  const [inFlight, setInFlight] = useState<{ request: ChatRequest; since: number } | null>(null)
  const [persona, setPersona] = useState(DEFAULT_PERSONA)
  const [sourcesOnly, setSourcesOnly] = useState(false)
  // The provider that wrote the last tutoring answer in this stream, for the next turn's pending label.
  const [answeredBy, setAnsweredBy] = useState<string | null>(null)
  const composer = useRef<HTMLTextAreaElement>(null)

  // Rebuild the stream once, from this mount's own fetch of the session (not a cached copy from an earlier visit).
  if (!built && live.isFetchedAfterMount && !live.isFetching) {
    setBuilt(true)
    setMessages(live.isError ? [errorMessage(failureOf(live.error), { op: "reload" })] : messagesFrom(live.data ?? null))
  }
  const session = built ? (live.data ?? null) : undefined
  const busy = inFlight !== null || !built

  // Focus returns to the composer after every reply.
  const wasBusy = useRef(false)
  useEffect(() => {
    if (wasBusy.current && inFlight === null) composer.current?.focus()
    wasBusy.current = inFlight !== null
  }, [inFlight])

  const personaNames = (personas.data ?? []).map((p) => p.name)
  const startPersona = personaNames.length === 0 || personaNames.includes(persona) ? persona : personaNames[0]

  const rows = sources.data ?? []
  const linked = sources.data ? rows.filter((r) => r.linked).length : null
  const selectable = rows.flatMap((r) => (r.linked && r.notebook_source_id ? [r.notebook_source_id] : []))
  // Every selectable source checked is the same question as none checked: ask them all, unscoped.
  const coversAll = selectable.length > 0 && selectable.every((id) => selectedSourceIds.includes(id))
  const scopedIds = coversAll ? [] : selectedSourceIds
  const scope = scopedIds.length === 0 ? "all sources" : plural(scopedIds.length, "selected source")

  const append = (...added: ChatMessage[]) => setMessages((ms) => [...ms, ...added])
  const markHandled = (id: string) =>
    setMessages((ms) => ms.map((m) => (m.id === id && m.kind === "error" ? { ...m, handled: true } : m)))
  const setRating = (id: string, text: string) =>
    setMessages((ms) => ms.map((m) => (m.id === id && m.kind === "tutor" ? { ...m, rating: text } : m)))

  /** Sends one request and returns the messages its answer adds to the stream. */
  async function perform(request: ChatRequest): Promise<ChatMessage[]> {
    switch (request.op) {
      case "ask":
        return [sourcesMessage(await ask.mutateAsync(request), request.scope)]
      case "start": {
        const started = await startSession.mutateAsync(request.persona)
        setSourcesOnly(false)
        const note: ChatMessage = {
          id: newId(),
          kind: "note",
          text: `Tutoring session started with the ${started.persona} persona.`,
        }
        return started.probe ? [note, probeMessage(started.probe)] : [note]
      }
      case "end": {
        const out = await endSession.mutateAsync()
        setSourcesOnly(false)
        return [{ id: newId(), kind: "note", text: out.reply ?? "Session ended." }]
      }
      case "turn": {
        const { text, purpose } = request
        const out = await turn.mutateAsync(text)
        if (out.ended) setSourcesOnly(false)
        const failure = turnFailure(out)
        if (failure) return [errorMessage(failure, request)]
        if (out.reply === null) return []
        if (out.provider) setAnsweredBy(out.provider)
        switch (purpose) {
          case "answer":
            return [
              { id: newId(), kind: "tutor", text: out.reply, label: tutorLabel(out.persona, out.provider), answer: true },
            ]
          case "probe":
            return [{ id: newId(), kind: "tutor", text: out.reply, label: "Challenger", answer: false }]
          case "rate":
            if (request.messageId) {
              setRating(request.messageId, out.reply)
              return []
            }
            return [{ id: newId(), kind: "note", text: out.reply }]
          case "command":
            return [{ id: newId(), kind: "note", text: out.reply }]
          case "end":
            return [{ id: newId(), kind: "note", text: out.reply }]
        }
      }
      case "close": {
        await closeSession.mutateAsync(request.sessionId)
        const note: ChatMessage = { id: newId(), kind: "note", text: "Closed the earlier session." }
        if (!request.then) return [note]
        setInFlight({ request: request.then, since: Date.now() })
        append(note)
        return perform(request.then)
      }
      case "reload": {
        // Ask the server what it holds now: a live session rebuilds the stream, none leaves it as it was.
        const result = await live.refetch()
        if (result.isError) throw result.error
        if (result.data) {
          setMessages(messagesFrom(result.data))
          return []
        }
        return [{ id: newId(), kind: "note", text: "This server holds no live session on the course now." }]
      }
    }
  }

  async function run(request: ChatRequest): Promise<void> {
    setInFlight({ request, since: Date.now() })
    try {
      append(...(await perform(request)))
    } catch (error) {
      let failure = failureOf(error)
      // This server already holds the session (another tab started it): show it rather than offer to close it.
      if (failure.kind === "conflict" && failure.code === "session_live") void live.refetch()
      const sent = request.op === "close" ? request.then : request
      // A 404 on a turn or an end: the tutor is gone (a server restart). The way out is a reload, not a retry.
      if (failure.kind === "other" && failure.status === 404 && (sent?.op === "turn" || sent?.op === "end")) {
        failure = { kind: "session_gone", detail: failure.detail }
        append(errorMessage(failure, { op: "reload" }))
      } else {
        append(errorMessage(failure, sent))
      }
    } finally {
      setInFlight(null)
    }
  }

  const lastAnswer = messages.findLast((m) => m.kind === "tutor" && m.answer)
  const ratableId = session?.ratable && lastAnswer ? lastAnswer.id : null

  function send(text: string) {
    const asked = askedQuestion(text)
    if (!session) {
      append({ id: newId(), kind: "learner", text, tag: scopedIds.length ? scope : undefined })
      void run({ op: "ask", question: asked ?? text, sourceIds: scopedIds, scope })
    } else if (sourcesOnly || asked !== null) {
      // The server asks every source, in the session's conversation, and refuses source ids here. A typed
      // `/ask q` is sent the same way rather than as a turn, so its citations come back as chips.
      append({ id: newId(), kind: "learner", text, tag: sourcesOnly ? "Sources only" : undefined })
      void run({ op: "ask", question: asked ?? text, scope: "every source" })
    } else {
      append({ id: newId(), kind: "learner", text })
      if (isRateLine(text) && ratableId) {
        // Typed like the buttons send it: the answer's buttons retire the same way.
        void run({ op: "turn", text, purpose: "rate", messageId: ratableId })
        return
      }
      const purpose: TurnPurpose =
        text === "/end" ? "end" : text.startsWith("/") ? "command" : session.probe ? "probe" : "answer"
      void run({ op: "turn", text, purpose })
    }
  }

  const pending = inFlight
    ? { label: pendingLabel(inFlight.request, session?.persona ?? startPersona, answeredBy), since: inFlight.since }
    : built
      ? null
      : { label: "Loading the session", since: mountedAt }

  const empty =
    !session && linked === 0 ? (
      <EmptyState className="flex-1" message="Upload course files to ask about them." />
    ) : (
      <EmptyState
        className="flex-1"
        message={session ? "Ask the tutor anything about the course." : "Ask a question about the course sources."}
      />
    )

  const placeholder = !session
    ? "Ask the course sources…"
    : sourcesOnly
      ? "Ask the sources directly…"
      : session.probe
        ? "Answer the challenge…"
        : "Message the tutor…"

  const hint = !session
    ? scopedIds.length
      ? `Asking ${scope}.`
      : "Asking all sources. Check sources in the Sources pane to narrow the question."
    : sourcesOnly
      ? "Asking every source in the session's conversation: the source selection doesn't apply during a session."
      : "Messages go to the tutor. /ask, /persona, /rate and /skip work as on the CLI."

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SessionBanner
        course={course}
        session={session}
        personas={personas.data ?? []}
        persona={startPersona}
        onPersonaChange={setPersona}
        onStart={() => void run({ op: "start", persona: startPersona })}
        onEnd={() => void run({ op: "end" })}
        onSwitchPersona={(name) => void run({ op: "turn", text: `/persona ${name}`, purpose: "command" })}
        busy={busy}
      />
      {session?.probe && (
        <ProbeBanner
          probe={session.probe}
          sourcesOnly={sourcesOnly}
          disabled={busy}
          onSkip={() => void run({ op: "turn", text: "/skip", purpose: "command" })}
        />
      )}
      <MessageList
        messages={messages}
        pending={pending}
        ratableId={ratableId}
        onRate={(messageId, n) => void run({ op: "turn", text: `/rate ${n}`, purpose: "rate", messageId })}
        onRetry={(m) => {
          markHandled(m.id)
          if (m.retry) void run(m.retry)
        }}
        onCloseSession={(m, sessionId) => {
          markHandled(m.id)
          void run({ op: "close", sessionId, then: m.retry })
        }}
        empty={empty}
      />
      <Composer
        ref={composer}
        disabled={busy}
        placeholder={placeholder}
        onSend={send}
        sourcesOnly={session ? { on: sourcesOnly, onChange: setSourcesOnly } : undefined}
        hint={hint}
      />
    </div>
  )
}
