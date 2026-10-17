// The Sources rail: upload, the link job, and the course's files, with which ones questions use.
import { useState } from "react"

import { isActive } from "@/api/jobs"
import { useLatestLinkJob, useSources, useUpload } from "@/api/queries.sources"
import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { LinkJobBar } from "@/features/sources/LinkJobBar"
import { SourceRow } from "@/features/sources/SourceRow"
import { failedSources, isSelectable } from "@/features/sources/status"
import { UploadBatches, UploadDropzone, useFileDrop } from "@/features/sources/UploadDropzone"

type SourcesPaneProps = {
  course: string
  /** NotebookLM ids of the checked sources; CoursePage owns them, since this rail can unmount. */
  selected: string[]
  setSelected: (ids: readonly string[]) => void
}

export function SourcesPane({ course, selected, setSelected }: SourcesPaneProps) {
  const sources = useSources(course)
  const job = useLatestLinkJob(course)
  const { batches, upload, retry, dismiss } = useUpload(course)
  const [bucket, setBucket] = useState<string | null>(null)
  const onFiles = (files: File[]) => upload(files, bucket)
  const drop = useFileDrop(onFiles)

  const rows = sources.data ?? []
  const selectable = rows.filter(isSelectable)
  const chosen = new Set(selected)
  const count = selectable.filter((s) => chosen.has(s.notebook_source_id)).length
  const all = count > 0 && count === selectable.length ? true : count > 0 ? "indeterminate" : false
  const linking = isActive(job)
  const failed = failedSources(job, rows)

  return (
    <div {...drop.handlers} className="flex flex-col gap-3">
      <UploadDropzone dragging={drop.dragging} bucket={bucket} onBucketChange={setBucket} onFiles={onFiles} />
      <UploadBatches batches={batches} onRetry={retry} onDismiss={dismiss} />
      {sources.isSuccess && <LinkJobBar course={course} sources={rows} job={job} />}

      {sources.isPending ? (
        <div className="flex flex-col gap-2" aria-label="Loading sources">
          {[0, 1, 2].map((n) => (
            <Skeleton key={n} className="h-12" />
          ))}
        </div>
      ) : sources.isError ? (
        <EmptyState
          message={sources.error.message}
          action={
            <Button variant="outline" size="sm" onClick={() => void sources.refetch()}>
              Try again
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        batches.length === 0 && <EmptyState message="Upload the syllabus to start." />
      ) : (
        <div className="flex flex-col">
          {selectable.length > 0 && (
            <label className="flex min-h-10 cursor-pointer items-center justify-between gap-3 border-b px-2 pb-1 text-sm text-muted-foreground">
              <span>
                Select all sources
                <span className="ml-1 tabular-nums">
                  ({count}/{selectable.length})
                </span>
              </span>
              <Checkbox
                checked={all}
                onCheckedChange={(value) =>
                  setSelected(value === true ? selectable.map((s) => s.notebook_source_id) : [])
                }
              />
            </label>
          )}
          <ul className="mt-1 flex flex-col gap-0.5" aria-label="Course files">
            {rows.map((source) => (
              <SourceRow
                key={source.resource_id}
                source={source}
                linking={linking}
                failure={failed.get(source.resource_id)}
                checked={source.notebook_source_id !== null && chosen.has(source.notebook_source_id)}
                onCheckedChange={(on) => {
                  const id = source.notebook_source_id
                  if (id === null) return
                  setSelected(on ? [...selected, id] : selected.filter((s) => s !== id))
                }}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
