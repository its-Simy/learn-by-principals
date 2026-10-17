// The course list. A static placeholder until BL-047 part 2 adds the course grid and NewCourseDialog.
import { Link } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"

export function HomePage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-xl font-semibold">Courses</h1>
        <div className="mt-6 rounded-xl border bg-card">
          <EmptyState
            message="The course grid arrives with BL-047 part 2."
            action={
              <Button variant="outline" size="sm" asChild>
                <Link to="/courses/CSE220">Preview the course layout</Link>
              </Button>
            }
          />
        </div>
      </div>
    </div>
  )
}
