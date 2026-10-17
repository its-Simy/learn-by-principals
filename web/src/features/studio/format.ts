// Display text for the Studio cards and the take view.
import type { Attempt, Concept, Draft } from "@/api/queries.studio"

/** "A", "B", ...: how a multiple-choice option is named and answered. */
export function letter(i: number): string {
  return String.fromCharCode(65 + i)
}

/** An option with its letter, when `answer` is one of `options`: "B. 0xFF". */
export function withLetter(answer: string, options: string[] | null): string {
  const i = options?.indexOf(answer) ?? -1
  return i >= 0 ? `${letter(i)}. ${answer}` : answer
}

/** Weakest first: lowest level, then least retained (no evidence counts as none), then by name. */
export function weakestFirst(a: Concept, b: Concept): number {
  return a.level - b.level || (a.retention_confidence ?? 0) - (b.retention_confidence ?? 0) || a.name.localeCompare(b.name)
}

export function retentionText(concept: Concept): string {
  if (concept.evidence_count === 0) return "no evidence yet"
  if (concept.retention_confidence === null) return "retention unknown"
  return `retention ${Math.round(concept.retention_confidence * 100)}%`
}

/**
 * When a draft was seeded, from its name: `concepts.draft.20261017-191518.yaml` -> "17 Oct, 19:15:18"
 * (seconds, so two seeds a minute apart differ). Any other name is returned as is.
 */
export function draftWhen(draft: Draft | string): string {
  const name = typeof draft === "string" ? draft : draft.name
  const m = /^concepts\.draft\.(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(?:-(\d+))?\.yaml$/.exec(name)
  if (!m) return name
  const [, y, mo, d, h, mi, s, n] = m
  const when = new Date(+y, +mo - 1, +d, +h, +mi, +s).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
  return n ? `${when} (${n})` : when
}

/** "Draft of 17 Oct, 19:15:18", or the name itself when it carries no time. */
export function draftLabel(draft: Draft | string): string {
  const name = typeof draft === "string" ? draft : draft.name
  const when = draftWhen(name)
  return when === name ? name : `Draft of ${when}`
}

/** One line on where an exam's attempts stand. */
export function attemptsSummary(attempts: Attempt[], questions: number): string {
  const latest = attempts.at(-1)
  if (!latest) return "Not taken yet"
  const done = latest.answered + latest.skipped
  if (!latest.finished_at) return `Attempt ${latest.attempt} in progress · ${done} of ${questions} done`
  if (latest.graded > 0) return `Attempt ${latest.attempt}: ${latest.correct} of ${latest.graded} correct`
  return `Attempt ${latest.attempt} handed in, not graded`
}
