// Providers, the top bar and the routes.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Link, Outlet, Route, Routes, useMatch } from "react-router"

import { useJobsWatcher } from "@/api/jobs"
import { EmptyState } from "@/components/EmptyState"
import { HealthDots } from "@/components/HealthDots"
import { JobsIndicator } from "@/components/JobsIndicator"
import { TopBar } from "@/components/TopBar"
import { Button } from "@/components/ui/button"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ThemeProvider } from "@/lib/theme"
import { CoursePage } from "@/pages/CoursePage"
import { HomePage } from "@/pages/HomePage"
import { SystemPage } from "@/pages/SystemPage"

// One user on localhost: no refetch storms on focus, and one retry before an error shows.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function Layout() {
  const course = useMatch("/courses/:course/*")?.params.course
  // Watches every job from here, above the panes, so a collapsed rail never loses a finished job.
  const jobs = useJobsWatcher()
  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <TopBar courseTitle={course}>
        {/* TODO(BL-047 part 2): health from /api/dashboard. */}
        <HealthDots health={[]} />
        <JobsIndicator jobs={jobs} />
      </TopBar>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}

function NotFound() {
  return (
    <EmptyState
      className="h-full"
      message="There is no page at this address."
      action={
        <Button variant="outline" size="sm" asChild>
          <Link to="/">Back to courses</Link>
        </Button>
      }
    />
  )
}

export function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <TooltipProvider delayDuration={300}>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<HomePage />} />
                <Route path="courses/:course" element={<CoursePage />} />
                <Route path="system" element={<SystemPage />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
            <Toaster />
          </TooltipProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </BrowserRouter>
  )
}
