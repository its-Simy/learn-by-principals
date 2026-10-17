// Adding files: the drop zone with its Upload button and bucket choice, and a Pending row per file in flight.
import { CloudUpload } from "lucide-react"
import { useEffect, useId, useRef, useState, type DragEvent } from "react"

import type { UploadBatch } from "@/api/queries.sources"
import { Pending } from "@/components/Pending"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ACCEPTED, BUCKETS } from "@/features/sources/status"
import { cn } from "@/lib/utils"

const AUTO = "auto" // a Select item can't have an empty value

function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes("Files")
}

/**
 * Drag-and-drop handlers for a whole pane, and whether files are over it. Entering and leaving
 * child elements fires on the pane too, so a counter tells a real leave from moving between rows.
 */
export function useFileDrop(onFiles: (files: File[]) => void) {
  const depth = useRef(0)
  const [dragging, setDragging] = useState(false)
  const handlers = {
    onDragEnter: (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      depth.current += 1
      setDragging(true)
    },
    onDragOver: (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      event.dataTransfer.dropEffect = "copy"
    },
    onDragLeave: (event: DragEvent) => {
      if (!carriesFiles(event)) return
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setDragging(false)
    },
    onDrop: (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      depth.current = 0
      setDragging(false)
      onFiles(Array.from(event.dataTransfer.files))
    },
  }
  return { dragging, handlers }
}

/**
 * For the app layout: a file dropped anywhere but a drop zone (on Home, System, a collapsed
 * rail) would make the browser open it in place of the app. Outside a zone, which has already
 * handled the event, the drag shows "not allowed" and the drop is swallowed.
 */
export function useNoStrayDrops(): void {
  useEffect(() => {
    const block = (event: globalThis.DragEvent) => {
      if (event.defaultPrevented || !event.dataTransfer?.types.includes("Files")) return
      event.preventDefault()
      if (event.type === "dragover") event.dataTransfer.dropEffect = "none"
    }
    window.addEventListener("dragover", block)
    window.addEventListener("drop", block)
    return () => {
      window.removeEventListener("dragover", block)
      window.removeEventListener("drop", block)
    }
  }, [])
}

type UploadDropzoneProps = {
  /** Files are being dragged over the pane. */
  dragging: boolean
  /** The bucket every file of the next upload goes to; null lets the server pick from each name. */
  bucket: string | null
  onBucketChange: (bucket: string | null) => void
  onFiles: (files: File[]) => void
}

export function UploadDropzone({ dragging, bucket, onBucketChange, onFiles }: UploadDropzoneProps) {
  const input = useRef<HTMLInputElement>(null)
  const bucketLabel = useId()
  const hint = useId()
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border border-dashed bg-card p-3 transition-colors",
        dragging && "border-primary bg-accent",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" aria-describedby={hint} onClick={() => input.current?.click()}>
          <CloudUpload />
          Upload
        </Button>
        {/* No `accept`: any file can be stored; only the code bucket is kept out of NotebookLM. */}
        <input
          ref={input}
          type="file"
          multiple
          tabIndex={-1}
          aria-hidden="true"
          className="sr-only"
          onChange={(event) => {
            onFiles(Array.from(event.target.files ?? []))
            event.target.value = "" // so choosing the same file again still uploads it
          }}
        />
        <span id={bucketLabel} className="sr-only">
          Bucket for these files
        </span>
        <Select value={bucket ?? AUTO} onValueChange={(value) => onBucketChange(value === AUTO ? null : value)}>
          <SelectTrigger size="sm" aria-labelledby={bucketLabel} className="min-w-0 flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={AUTO}>Auto bucket</SelectItem>
            {BUCKETS.map((b) => (
              <SelectItem key={b} value={b}>
                {b}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div id={hint} className="space-y-1 text-xs text-muted-foreground">
        <p>{dragging ? "Drop to upload." : "Or drop files here."} NotebookLM reads {ACCEPTED.join(" ")}.</p>
        <p>Files in the code bucket are stored but not sent to NotebookLM; choose code for source files.</p>
      </div>
    </div>
  )
}

type UploadBatchesProps = {
  batches: UploadBatch[]
  onRetry: (batch: UploadBatch) => void
  onDismiss: (batch: UploadBatch) => void
}

/** Every file of every upload still in flight, then any upload that failed, with what to do. */
export function UploadBatches({ batches, onRetry, onDismiss }: UploadBatchesProps) {
  if (batches.length === 0) return null
  return (
    <ul className="flex flex-col gap-2" aria-label="Uploads">
      {batches.map((batch) =>
        batch.phase === "failed" ? (
          <li key={batch.id} role="alert" className="rounded-xl border bg-card p-3 text-sm">
            {/* The server stores files in order, so some may have landed before the error: they are in the list. */}
            <p className="wrap-anywhere">Upload stopped: {batch.note}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Files stored before it are in the list below; Try again sends all {batch.files.length}.
            </p>
            <div className="mt-2 flex gap-2">
              <Button size="xs" variant="outline" onClick={() => onRetry(batch)}>
                Try again
              </Button>
              <Button size="xs" variant="ghost" onClick={() => onDismiss(batch)}>
                Dismiss
              </Button>
            </div>
          </li>
        ) : (
          <li key={batch.id} className="flex flex-col gap-1.5 rounded-lg px-2 py-1">
            {batch.note && <p className="text-xs text-muted-foreground">{batch.note}</p>}
            {batch.files.map((file, index) => (
              <Pending
                key={`${file.name}-${index}`}
                className="min-h-8 wrap-anywhere"
                label={file.name}
                since={batch.since}
                detail={batch.phase === "waiting" ? "waiting for the link job" : "uploading"}
              />
            ))}
          </li>
        ),
      )}
    </ul>
  )
}
