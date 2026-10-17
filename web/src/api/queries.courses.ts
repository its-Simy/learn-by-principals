// Courses: the home grid and the new-course dialog. Each card's sessions come from the chat's `useSessions`.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, unwrap } from "@/api/client"
import { keys } from "@/api/jobs"
import type { components } from "@/api/types"

export type Course = components["schemas"]["CourseOut"]
export type CourseIn = components["schemas"]["CourseIn"]

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
