// State strings (source, session, job, provider health) mapped to the semantic colour tokens in index.css.

export type Tone = "success" | "warning" | "pending" | "danger" | "neutral"

// Keys are lower case; health states arrive as "RATE_LIMITED" and are matched case-insensitively.
// `synced` is a sync_state meaning the file is stored, not that it is in NotebookLM, so SourceRow
// must derive its badge from the row's `linked` field rather than pass sync_state straight through.
const TONES: Record<string, Tone> = {
  synced: "success",
  linked: "success",
  done: "success",
  ok: "success",
  open: "success",
  available: "success",
  stale: "warning",
  deferred: "warning",
  warn: "warning",
  limited: "warning",
  rate_limited: "warning",
  pending: "pending",
  queued: "pending",
  running: "pending",
  failed: "danger",
  fail: "danger", // the doctor's FAIL status
  broken: "danger",
  auth_expired: "danger",
  ended: "neutral",
  link: "neutral",
  disabled: "neutral",
}

export function stateTone(state: string): Tone {
  return TONES[state.toLowerCase()] ?? "neutral"
}

// `danger` reuses shadcn's destructive token; `neutral` is muted text.
export const TONE_TEXT: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  pending: "text-pending",
  danger: "text-destructive",
  neutral: "text-muted-foreground",
}

export const TONE_DOT: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  pending: "bg-pending",
  danger: "bg-destructive",
  neutral: "bg-muted-foreground",
}
