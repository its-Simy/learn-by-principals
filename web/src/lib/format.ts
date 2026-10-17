// Small display formatters shared by the panes.

/** "14 s", "1 m 20 s", "2 h 5 m": the elapsed-time text every wait shows. */
export function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  if (s < 60) return `${s} s`
  const minutes = Math.floor(s / 60)
  if (minutes < 60) return `${minutes} m ${s % 60} s`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} m`
}

/** Seconds between an ISO timestamp (or epoch ms) and `now`. */
export function secondsSince(since: string | number, now: number = Date.now()): number {
  const start = typeof since === "number" ? since : Date.parse(since)
  return Number.isNaN(start) ? 0 : (now - start) / 1000
}

/** Local clock time for a timestamp, e.g. a rate-limit reset: "14:05". */
export function formatClock(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

/** A state string as people read it: "RATE_LIMITED" -> "rate limited". */
export function humanize(value: string): string {
  return value.replaceAll("_", " ").toLowerCase()
}
