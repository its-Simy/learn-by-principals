// Which linked sources a question is scoped to. Called by CoursePage, which owns the state.
import { useCallback, useMemo, useState } from "react"

import { useSources } from "@/api/queries.sources"
import { isSelectable } from "@/features/sources/status"

/**
 * `[selectedSourceIds, setSelectedSourceIds]`, as NotebookLM ids (what `ask` takes as
 * `source_ids`). As in NotebookLM, every linked source is selected, new ones included, until
 * unchecked, so the state kept is the unchecked files, by resource id: that survives a changed
 * file being re-linked under a new NotebookLM id, and ids from another course never match.
 */
export function useSourceSelection(course: string): [string[], (ids: readonly string[]) => void] {
  const { data: sources } = useSources(course)
  const [unchecked, setUnchecked] = useState<ReadonlySet<string>>(() => new Set())
  const selectable = useMemo(() => (sources ?? []).filter(isSelectable), [sources])

  const selected = useMemo(
    () => selectable.filter((s) => !unchecked.has(s.resource_id)).map((s) => s.notebook_source_id),
    [selectable, unchecked],
  )

  const setSelected = useCallback(
    (ids: readonly string[]) => {
      const keep = new Set(ids)
      const shown = new Set(selectable.map((s) => s.resource_id))
      setUnchecked(
        (before) =>
          new Set([
            // A file that isn't selectable right now (being replaced) stays unchecked.
            ...[...before].filter((id) => !shown.has(id)),
            ...selectable.filter((s) => !keep.has(s.notebook_source_id)).map((s) => s.resource_id),
          ]),
      )
    },
    [selectable],
  )

  return [selected, setSelected]
}
