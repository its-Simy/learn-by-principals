// The system page and the top bar: the usage dashboard (which carries provider health) and doctor; and the
// server's own health, whose `term` the new-course dialog prefills.
import { useQuery } from "@tanstack/react-query"

import { api, unwrap } from "@/api/client"
import { keys } from "@/api/jobs"
import type { components } from "@/api/types"

export type Dashboard = components["schemas"]["DashboardOut"]
export type Check = components["schemas"]["CheckOut"]

/** The server's version, schema and `config.term` (the term a new course is filed under unless it names one). */
export function useHealth() {
  return useQuery({
    queryKey: keys.health(),
    queryFn: () => unwrap(api.GET("/api/health")),
  })
}

/** The top bar's HealthDots poll this; a rate limit's cooldown shows within a minute. */
export const HEALTH_POLL_MS = 60_000

export function useDashboard(options: { refetchInterval?: number } = {}) {
  return useQuery({
    queryKey: keys.dashboard(),
    queryFn: () => unwrap(api.GET("/api/dashboard")),
    refetchInterval: options.refetchInterval,
  })
}

export const MODELS_HINT = "Tutoring, mastery and exams need Claude Code or Codex (optional): see the README."

/**
 * The note for a feature that needs a model CLI, when none is installed: every model provider in
 * the polled health is disabled (or there is none), which is how a fresh NotebookLM-only setup
 * looks. Null while health is unknown or any model is usable.
 */
export function useModelsHint(): string | null {
  const health = useDashboard().data?.health
  if (!health) return null
  const models = health.filter((h) => h.provider !== "notebooklm")
  return models.every((h) => h.state.toLowerCase() === "disabled") ? MODELS_HINT : null
}

/** Read-only checks (versions, paths, the NotebookLM login); never cached, so a visit re-runs them. */
export function useDoctor() {
  return useQuery({
    queryKey: keys.doctor(),
    queryFn: () => unwrap(api.GET("/api/doctor")),
    staleTime: 0,
    gcTime: 0,
  })
}
