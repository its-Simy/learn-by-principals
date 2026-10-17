// The course list: one card per course, and the dialog that adds one.
import { Plus } from "lucide-react"
import { useId, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router"

import { ApiError } from "@/api/client"
import { defaultTerm, useCourseSessions, useCourses, useCreateCourse, type Course } from "@/api/queries.courses"
import { EmptyState } from "@/components/EmptyState"
import { StateBadge } from "@/components/StateBadge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { formatClock } from "@/lib/format"

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

/** "today 14:05", "yesterday", "Oct 15": when a course was last studied. */
function formatDay(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
  if (days === 0) return `today ${formatClock(iso)}`
  if (days === 1) return "yesterday"
  return date.toLocaleDateString([], { month: "short", day: "numeric" })
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

function CourseCard({ course }: { course: Course }) {
  // CourseOut names only this server's live session; the course's sessions also show a CLI or stale one.
  const { data: sessions } = useCourseSessions(course.course)
  const unfinished = sessions?.find((s) => s.state !== "ended")
  const state = unfinished?.state ?? (course.open_session_id ? "open" : null)
  const last = sessions?.[0]
  return (
    <li>
      <Link
        to={`/courses/${encodeURIComponent(course.course)}`}
        className="flex h-full flex-col gap-3 rounded-xl border bg-card p-4 outline-none transition-colors hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-medium tracking-wide text-muted-foreground">
              {course.course} · {course.term}
            </p>
            <h2 className="mt-1 line-clamp-2 font-medium">{course.name}</h2>
          </div>
          {/* No hint: a focusable tooltip can't sit inside a link. */}
          {state && <StateBadge state={state} label={state === "stale" ? "stale session" : "session open"} />}
        </div>
        <div className="mt-auto space-y-1 text-sm text-muted-foreground">
          <p>
            {plural(course.sources, "source")} · {course.linked} linked · {plural(course.concepts, "concept")}
          </p>
          {last && <p className="text-xs">Last session {formatDay(last.last_turn_at ?? last.started_at)}</p>}
        </div>
      </Link>
    </li>
  )
}

function CourseGrid({ courses }: { courses: Course[] }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Courses">
      {courses.map((course) => (
        <CourseCard key={course.course} course={course} />
      ))}
    </ul>
  )
}

type FieldErrors = { course?: string; term?: string; form?: string }

// Core's refusals say which field they mean: "course code 'x' must be ...", "term 'x' must be ...".
function fieldErrors(error: unknown): FieldErrors {
  if (!(error instanceof ApiError)) return { form: error instanceof Error ? error.message : String(error) }
  const message = error.message.charAt(0).toUpperCase() + error.message.slice(1)
  const code = (error.body as { code?: unknown } | null)?.code
  if (error.status === 409 && code === "duplicate_course") return { course: `${message}.` }
  if (error.status === 422 && error.message.startsWith("course code")) return { course: message }
  if (error.status === 422 && error.message.startsWith("term")) return { term: message }
  return { form: message }
}

const CODE_PATTERN = "[A-Za-z0-9_\\-]{1,32}"

// The form unmounts with the dialog's content, so every open starts empty, with no old error.
function NewCourseForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate()
  const create = useCreateCourse()
  const [course, setCourse] = useState("")
  const [name, setName] = useState("")
  const [term, setTerm] = useState(defaultTerm)
  // An untouched term is left out, so the server uses its own (config.term); the prefill is
  // only today's guess, which BRIGHTLEARN_TERM can override on the server.
  const [termEdited, setTermEdited] = useState(false)
  const ids = { course: useId(), name: useId(), term: useId(), courseError: useId(), termError: useId() }
  const errors = create.isError ? fieldErrors(create.error) : {}

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate(
      { course: course.trim(), name: name.trim(), ...(termEdited ? { term: term.trim() || null } : {}) },
      {
        onSuccess: (created) => {
          onDone()
          void navigate(`/courses/${encodeURIComponent(created.course)}`)
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>New course</DialogTitle>
        <DialogDescription>Its files are stored under the term, in a folder named by the code.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-2">
        <label htmlFor={ids.course} className="text-sm font-medium">
          Course code
        </label>
        <Input
          id={ids.course}
          value={course}
          onChange={(e) => setCourse(e.target.value.toUpperCase())}
          placeholder="CSE220"
          required
          maxLength={32}
          pattern={CODE_PATTERN}
          autoComplete="off"
          autoFocus
          aria-invalid={errors.course ? true : undefined}
          aria-describedby={errors.course ? ids.courseError : undefined}
        />
        {errors.course && (
          <p id={ids.courseError} role="alert" className="text-sm text-destructive">
            {errors.course}
          </p>
        )}
      </div>
      <div className="grid gap-2">
        <label htmlFor={ids.name} className="text-sm font-medium">
          Name
        </label>
        <Input
          id={ids.name}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Systems Fundamentals I"
          required
          autoComplete="off"
        />
      </div>
      <div className="grid gap-2">
        <label htmlFor={ids.term} className="text-sm font-medium">
          Term
        </label>
        <Input
          id={ids.term}
          value={term}
          onChange={(e) => {
            setTerm(e.target.value)
            setTermEdited(true)
          }}
          placeholder={defaultTerm()}
          maxLength={32}
          pattern={CODE_PATTERN}
          autoComplete="off"
          aria-invalid={errors.term ? true : undefined}
          aria-describedby={errors.term ? ids.termError : undefined}
        />
        {errors.term && (
          <p id={ids.termError} role="alert" className="text-sm text-destructive">
            {errors.term}
          </p>
        )}
      </div>
      {errors.form && (
        <p role="alert" className="text-sm text-destructive">
          {errors.form}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create course"}
        </Button>
      </DialogFooter>
    </form>
  )
}

function NewCourseDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <NewCourseForm onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

export function HomePage() {
  const courses = useCourses()
  const [creating, setCreating] = useState(false)
  const newCourse = (
    <Button onClick={() => setCreating(true)}>
      <Plus />
      New course
    </Button>
  )
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-semibold">Courses</h1>
          {courses.isSuccess && courses.data.length > 0 && newCourse}
        </div>
        <div className="mt-6">
          {courses.isPending ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Loading courses">
              {[0, 1, 2].map((n) => (
                <Skeleton key={n} className="h-32 rounded-xl" />
              ))}
            </div>
          ) : courses.isError ? (
            <div className="rounded-xl border bg-card">
              <EmptyState
                message={courses.error.message}
                action={
                  <Button variant="outline" size="sm" onClick={() => void courses.refetch()}>
                    Try again
                  </Button>
                }
              />
            </div>
          ) : courses.data.length === 0 ? (
            <div className="rounded-xl border bg-card">
              <EmptyState message="Create your first course." action={newCourse} />
            </div>
          ) : (
            <CourseGrid courses={courses.data} />
          )}
        </div>
      </div>
      <NewCourseDialog open={creating} onOpenChange={setCreating} />
    </div>
  )
}
