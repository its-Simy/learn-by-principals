// The chat stream's client state: messages, the request in flight, and how server replies become messages.
import type { Citation, Failure, LiveSession, Probe, TurnResult } from "@/api/queries.chat"
import { formatClock } from "@/lib/format"

/** One citation chip. In-session answers carry their citations inside the text, so these have no source id. */
export type Chip = Pick<Citation, "n" | "filename" | "bucket" | "excerpt">

export type ChatMessage =
  | { id: string; kind: "learner"; text: string; tag?: string }
  /** `answer`: a tutoring answer, the one `/rate` rates; `rating` is the server's acknowledgement once rated. */
  | { id: string; kind: "tutor"; text: string; label: string; answer: boolean; rating?: string }
  | { id: string; kind: "sources"; text: string; citations: Chip[]; scope: string; inSession: boolean }
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

export function capitalize(word: string): string {
  return word ? word[0].toUpperCase() + word.slice(1) : word
}

/** `/ask <question>` typed in a session; a bare `/ask` only gets the usage line back. */
export function isAskLine(text: string): boolean {
  return text.startsWith("/ask ")
}

/** `/rate 1`–`/rate 5`: what the rate buttons send. Anything else after `/rate` is the tutor's usage line. */
export function isRateLine(text: string): boolean {
  return /^\/rate [1-5]$/.test(text)
}

/** What the pending bubble says while `request` is in flight. */
export function pendingLabel(request: ChatRequest, persona: string): string {
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
          // WORKAROUND until `TurnOut.provider`: name the provider that answered last ("Claude is answering").
          return `${capitalize(persona)} is answering`
        case "probe":
          return "Challenger is grading your answer"
        case "rate":
          return "Saving your rating"
        case "end":
          return "Analyzer is reading the transcript"
        case "command":
          return isAskLine(request.text) ? "Asking the sources" : "Working"
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

// -- in-session grounded answers ---------------------------------------------------------------
// WORKAROUND until in-session asks return structured citations (`AskOut.citations`): the tutor's `ground`
// flattens them into the text as one line each, `[n] <filename>: <excerpt>`, after the answer
// (core/context/compiler.py), so they are lifted back out here.

const CITATION_START = /^\[(\d+)\] /

/** A citation line naming a known file. Filenames may contain ": ", so the longest `filename: ` prefix wins. */
function parseCitation(line: string, known: ReadonlyMap<string, string | null>): Chip | null {
  const match = CITATION_START.exec(line)
  if (!match) return null
  const rest = line.slice(match[0].length)
  let filename: string | null = null
  for (const name of known.keys()) {
    if (rest.startsWith(`${name}: `) && (filename === null || name.length > filename.length)) filename = name
  }
  if (filename === null) return null
  return { n: Number(match[1]), filename, bucket: known.get(filename) ?? null, excerpt: rest.slice(filename.length + 2) }
}

/**
 * Splits an in-session grounded answer into its text and citation chips. `known` maps the course's
 * filenames to their buckets. The server cuts an over-long citation block short with "…", so a
 * trailing citation line ending in "…" is skipped. With no line naming a known file, the answer is
 * left as it came.
 */
export function splitCitations(answer: string, known: ReadonlyMap<string, string | null>): { text: string; citations: Chip[] } {
  const lines = answer.split("\n")
  let start = lines.length
  const last = lines[start - 1]
  if (start > 1 && CITATION_START.test(last) && last.endsWith("…")) start -= 1
  const citations: Chip[] = []
  while (start > 0) {
    const chip = parseCitation(lines[start - 1], known)
    if (!chip) break
    citations.unshift(chip)
    start -= 1
  }
  if (citations.length === 0) return { text: answer, citations: [] }
  return { text: lines.slice(0, start).join("\n").trim(), citations }
}

// -- failures inside a 200 ---------------------------------------------------------------------

// WORKAROUND until `TurnOut.error {provider, detail, resets_at}`: a tutor turn whose model calls all
// failed is a 200 whose reply is "(no answer: …)" (core/tutor.py). Then read `out.error` into the
// same "upstream" failure, with its provider and reset time, and drop this match.
const NO_ANSWER = /^\(no answer: ([\s\S]*)\)$/

export function turnFailure(out: TurnResult): Failure | null {
  const match = out.reply === null ? null : NO_ANSWER.exec(out.reply.trim())
  return match ? { kind: "upstream", detail: match[1], provider: null, resetsAt: null } : null
}

// WORKAROUND until in-session asks return a structured answer: when NotebookLM fails, the tutor's
// `ground` answers this sentence instead (core/context/compiler.py).
const SOURCES_UNAVAILABLE = /^\(course sources unavailable: ([\s\S]*)\)$/

export function groundFailure(text: string): Failure | null {
  const match = SOURCES_UNAVAILABLE.exec(text.trim())
  return match ? { kind: "upstream", detail: match[1], provider: "notebooklm", resetsAt: null } : null
}

/** A time as `formatClock` gives it, with the date in front when it isn't today: "Oct 18, 09:05". */
export function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  if (date.toDateString() === new Date().toDateString()) return formatClock(iso)
  return `${date.toLocaleDateString([], { month: "short", day: "numeric" })}, ${formatClock(iso)}`
}
