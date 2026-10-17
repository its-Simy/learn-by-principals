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

/** Read-only checks (versions, paths, the NotebookLM login); never cached, so a visit re-runs them. */
export function useDoctor() {
  return useQuery({
    queryKey: keys.doctor(),
    queryFn: () => unwrap(api.GET("/api/doctor")),
    staleTime: 0,
    gcTime: 0,
  })
}
