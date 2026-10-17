// Doctor checks and the usage dashboard. A static placeholder until BL-047 part 2 wires /api/doctor and /api/dashboard.
import { EmptyState } from "@/components/EmptyState"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const SECTIONS = [
  { title: "Doctor", message: "The doctor table arrives with BL-047 part 2." },
  { title: "Dashboard", message: "Usage, health and mastery sections arrive with BL-047 part 2." },
] as const

export function SystemPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8">
        <h1 className="text-xl font-semibold">System</h1>
        {SECTIONS.map((section) => (
          <Card key={section.title} className="shadow-none">
            <CardHeader>
              <CardTitle className="text-base">{section.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <EmptyState message={section.message} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
