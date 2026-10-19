// Providers, the top bar and the routes.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Link, Outlet, Route, Routes, useMatch } from "react-router"

import { useJobsWatcher } from "@/api/jobs"
import { useCourse } from "@/api/queries.courses"
import { HEALTH_POLL_MS, useDashboard } from "@/api/queries.system"
import { EmptyState } from "@/components/EmptyState"
import { HealthDots, type ProviderHealth } from "@/components/HealthDots"
import { JobsIndicator } from "@/components/JobsIndicator"
import { TopBar } from "@/components/TopBar"
import { Button } from "@/components/ui/button"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useNoStrayDrops } from "@/features/sources/UploadDropzone"
import { ExamTakeView } from "@/features/exams/ExamTakeView"
import { ThemeProvider } from "@/lib/theme"
import { CourseChat, CoursePage } from "@/pages/CoursePage"
import { HomePage } from "@/pages/HomePage"
import { SystemPage } from "@/pages/SystemPage"

// One user on localhost: no refetch storms on focus, and one retry before an error shows.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

const NO_HEALTH: ProviderHealth[] = []

function Layout() {
  const course = useMatch("/courses/:course/*")?.params.course?.toUpperCase()
  const name = useCourse(course)?.name // the bar shows the name only, and nothing until it is known
  // Watches every job from here, above the panes, so a collapsed rail never loses a finished job.
  const jobs = useJobsWatcher()
  useNoStrayDrops() // a file dropped anywhere but the Sources pane never replaces the app
  // The dashboard carries each provider's health; polled so a rate limit's reset shows on every page.
  const health = useDashboard({ refetchInterval: HEALTH_POLL_MS }).data?.health ?? NO_HEALTH
  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <TopBar courseTitle={name}>
        <HealthDots health={health} />
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
                {/* The take view replaces the chat area only: the rails, and the source selection, stay. */}
                <Route path="courses/:course" element={<CoursePage />}>
                  <Route index element={<CourseChat />} />
                  <Route path="exams/:id/take" element={<ExamTakeView />} />
                </Route>
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
