// Courses: the home grid, the new-course dialog, and each card's session state.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, unwrap } from "@/api/client"
import { keys } from "@/api/jobs"
import type { components } from "@/api/types"

export type Course = components["schemas"]["CourseOut"]
export type CourseIn = components["schemas"]["CourseIn"]
export type Session = components["schemas"]["SessionOut"]

export function useCourses() {
  return useQuery({
    queryKey: keys.courses(),
    queryFn: () => unwrap(api.GET("/api/courses")),
  })
}

/** One course from the list, for titles; undefined until the list has loaded. */
export function useCourse(course: string | undefined): Course | undefined {
  const { data } = useCourses()
  return course === undefined ? undefined : data?.find((c) => c.course === course.toUpperCase())
}

/** A duplicate code is a 409 `duplicate_course`, a bad code or term a 422: both for the dialog to show. */
export function useCreateCourse() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CourseIn) => unwrap(api.POST("/api/courses", { body })),
    onSuccess: (created) => {
      queryClient.setQueryData<Course[]>(keys.courses(), (courses = []) =>
        [...courses.filter((c) => c.course !== created.course), created].sort((a, b) =>
          a.course.localeCompare(b.course),
        ),
      )
      void queryClient.invalidateQueries({ queryKey: keys.courses() })
    },
  })
}

/**
 * A course's sessions, newest first. CourseOut names only the session this server holds, so a
 * card reads this to also show one left open by the CLI or gone stale. Keyed under the courses so
 * it refreshes with them.
 */
export function useCourseSessions(course: string) {
  return useQuery({
    queryKey: [...keys.courses(), course, "sessions"],
    queryFn: () => unwrap(api.GET("/api/courses/{course}/sessions", { params: { path: { course } } })),
  })
}

/** Today's term as core.config.default_term guesses it (the API doesn't expose config.term). */
export function defaultTerm(today: Date = new Date()): string {
  const month = today.getMonth() + 1
  const season = month <= 5 ? "Spring" : month <= 7 ? "Summer" : "Fall"
  return `${season}-${today.getFullYear()}`
}
