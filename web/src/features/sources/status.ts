// What a source row says about its file: the badge, the explanation behind it, and its icon.
import { BookOpen, File, FileCode, FileSpreadsheet, FileText, Link2, Presentation, type LucideIcon } from "lucide-react"

import { isActive, type Job } from "@/api/jobs"
import type { Source } from "@/api/queries.sources"

// core/sync/classify.py BUCKETS, in the same order.
export const BUCKETS = ["syllabus", "lectures", "assignments", "labs", "readings", "exams", "code", "other"] as const

// What NotebookLM takes; files in the code bucket are stored too (CODE_BUCKETS in core/sync/link.py) but never sent.
export const ACCEPTED = [".pdf", ".md", ".txt", ".docx", ".pptx", ".csv", ".epub"] as const

/**
 * `tone` is a StateBadge state picked for its colour; `label` is what the badge says. `synced`
 * means stored, not linked, so the badge comes from `linked` first.
 */
export type SourceStatus = { tone: string; label: string; hint: string }

export function sourceStatus(source: Source, linking: boolean, failure?: string): SourceStatus {
  if (source.sync_state === "link") {
    return { tone: "link", label: "link", hint: "A web link, not a file: recorded, never sent to NotebookLM." }
  }
  if (failure !== undefined && !linking) {
    return { tone: "failed", label: "failed", hint: `The last link failed: ${failure}. Retry sends it again.` }
  }
  if (source.linked) {
    if (source.sync_state === "stale") {
      return linking
        ? { tone: "running", label: "replacing", hint: "NotebookLM is getting the new version now." }
        : { tone: "stale", label: "changed", hint: "Changed since NotebookLM got it; linking again replaces it." }
    }
    if (source.sync_state === "failed") {
      return { tone: "failed", label: "failed", hint: "The last link failed; Retry sends it again." }
    }
    return { tone: "linked", label: "linked", hint: "In NotebookLM: questions and the tutor can cite it." }
  }
  if (source.bucket === "code") {
    return { tone: "stored", label: "stored", hint: "Files in the code bucket are stored but not sent to NotebookLM." }
  }
  if (source.sync_state === "deferred") {
    return {
      tone: "deferred",
      label: "deferred",
      hint: "Over NotebookLM's 50-source cap for this course: stored, not sent.",
    }
  }
  if (source.sync_state === "failed") {
    return { tone: "failed", label: "failed", hint: "Linking failed; Retry sends it again." }
  }
  return linking
    ? { tone: "running", label: "linking", hint: "Being sent to NotebookLM now." }
    : { tone: "warn", label: "not linked", hint: "Stored, but not in NotebookLM yet; linking again sends it." }
}

/** A finished link job's `failures`: free-form strings, one per file or a reason it stopped. */
export function linkFailures(job: Job | undefined): string[] {
  const value = job && !isActive(job) ? job.result?.failures : undefined
  return Array.isArray(value) ? value.filter((f): f is string => typeof f === "string") : []
}

/**
 * A file's failure reads "{resource_id} 'title': error". Maps each failed file's resource id to
 * the rest, which is what the learner reads; failures naming no file (the notebook) are left out.
 */
export function failedSources(job: Job | undefined, sources: Source[]): Map<string, string> {
  const ids = new Set(sources.map((s) => s.resource_id))
  const failed = new Map<string, string>()
  for (const failure of linkFailures(job)) {
    const [id, ...rest] = failure.split(" ")
    if (ids.has(id) && rest.length) failed.set(id, rest.join(" "))
  }
  return failed
}

/** A row NotebookLM will take on the next link: not linked, not code, not a URL, not over the cap. */
export function awaitsLink(source: Source): boolean {
  return (
    (!source.linked || source.sync_state === "stale") &&
    source.bucket !== "code" &&
    source.sync_state !== "link" &&
    source.sync_state !== "deferred"
  )
}

/** Only linked files can be selected: the selection scopes questions to NotebookLM sources. */
export function isSelectable(source: Source): source is Source & { notebook_source_id: string } {
  return source.linked && source.notebook_source_id !== null
}

const ICONS: Record<string, LucideIcon> = {
  pdf: FileText,
  md: FileText,
  txt: FileText,
  docx: FileText,
  doc: FileText,
  pptx: Presentation,
  ppt: Presentation,
  csv: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  epub: BookOpen,
}

export function fileIcon(source: Source): LucideIcon {
  if (source.sync_state === "link") return Link2
  if (source.bucket === "code") return FileCode
  const extension = source.filename?.split(".").pop()?.toLowerCase() ?? ""
  return ICONS[extension] ?? File
}
