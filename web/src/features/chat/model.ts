// The chat stream's client state: messages, the request in flight, and how server replies become messages.
import type { Citation, Failure, LiveSession, Probe, TurnResult } from "@/api/queries.chat"

export type ChatMessage =
  | { id: string; kind: "learner"; text: string; tag?: string }
  /** `answer`: a tutoring answer, the one `/rate` rates; `rating` is the server's acknowledgement once rated. */
  | { id: string; kind: "tutor"; text: string; label: string; answer: boolean; rating?: string }
  | { id: string; kind: "sources"; text: string; citations: Citation[]; scope: string; inSession: boolean }
  | { id: string; kind: "note"; text: string }
  /** `handled`: its way out (close the session, retry, reload) has been taken. */
  | { id: string; kind: "error"; failure: Failure; retry?: ChatRequest; handled?: boolean }

/** What the pane can send; kept as data so a failed one can be retried from its error message. */
export type ChatRequest =
  | { op: "ask"; question: string; sourceIds?: string[]; scope: string }
  /** `messageId`: for a rating, the answer it rates. */
  | { op: "turn"; text: string; purpose: TurnPurpose; messageId?: string }
  | { op: "start"; persona: string }
  | { op: "end" }
  | { op: "close"; sessionId: string; then?: ChatRequest }
  | { op: "reload" }

/** How a turn's reply is shown: a tutoring answer, a Challenger answer, a typed command, a rating. */
export type TurnPurpose = "answer" | "probe" | "command" | "rate" | "end"

let counter = 0
export function newId(): string {
  counter += 1
  return `m${counter}`
}

function capitalize(word: string): string {
  return word ? word[0].toUpperCase() + word.slice(1) : word
}

const PROVIDER_NAMES: Record<string, string> = { notebooklm: "NotebookLM" }

/** A provider as the learner reads it: "notebooklm" -> "NotebookLM", "claude" -> "Claude". */
export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? capitalize(provider)
}

/**
 * The question of `/ask <question>` typed in a session, which the pane sends as an ask so its citations come
 * back as chips; null for any other line (a bare `/ask` goes to the tutor, which answers with its usage line).
 */
export function askedQuestion(text: string): string | null {
  if (!text.startsWith("/ask ")) return null
  return text.slice("/ask ".length).trim() || null
}

/** `/rate 1`–`/rate 5`: what the rate buttons send. Anything else after `/rate` is the tutor's usage line. */
export function isRateLine(text: string): boolean {
  return /^\/rate [1-5]$/.test(text)
}

/** A tutoring answer's caption: the persona, and the provider that wrote it when that is known ("Simplifier · Claude"). */
export function tutorLabel(persona: string, provider: string | null): string {
  return provider ? `${capitalize(persona)} · ${providerName(provider)}` : capitalize(persona)
}

/**
 * What the pending bubble says while `request` is in flight. `provider` answered the last tutoring turn, so it
 * most likely answers this one too ("Claude is answering"); before any, the persona stands in.
 */
export function pendingLabel(request: ChatRequest, persona: string, provider: string | null): string {
  switch (request.op) {
    case "ask":
      return "Asking the sources"
    case "start":
      return "Starting the session"
    case "end":
      return "Analyzer is reading the transcript"
    case "close":
      return "Closing the earlier session"
    case "reload":
      return "Loading the session"
    case "turn":
      switch (request.purpose) {
        case "answer":
          return `${provider ? providerName(provider) : capitalize(persona)} is answering`
        case "probe":
          return "Challenger is grading your answer"
        case "rate":
          return "Saving your rating"
        case "end":
          return "Analyzer is reading the transcript"
        case "command":
          return "Working"
      }
  }
}

/** A Challenger probe as the tutor shows it on the CLI. */
export function probeMessage(probe: Probe): ChatMessage {
  return { id: newId(), kind: "tutor", text: probe.question, label: `Challenger · ${probe.concept}`, answer: false }
}

/** The stream after a reload: the session's tutoring exchanges, then the probe waiting for an answer. */
export function messagesFrom(session: LiveSession | null): ChatMessage[] {
  if (!session) return []
  const messages: ChatMessage[] = session.turns.map((turn) =>
    turn.role === "learner"
      ? { id: newId(), kind: "learner", text: turn.text }
      : { id: newId(), kind: "tutor", text: turn.text, label: capitalize(session.persona), answer: true },
  )
  if (messages.length === 0) {
    messages.push({ id: newId(), kind: "note", text: `Tutoring session with the ${session.persona} persona.` })
  }
  if (session.probe) messages.push(probeMessage(session.probe))
  return messages
}

/** A line the tutor couldn't answer is a 200 with `error`: shown like a 502, naming the provider and its reset time. */
export function turnFailure(out: TurnResult): Failure | null {
  if (!out.error) return null
  const { provider, detail, resets_at } = out.error
  return { kind: "upstream", detail, provider, resetsAt: resets_at }
}
