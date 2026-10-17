// Reviewing a concept draft: edit the YAML, see what changed since the draft before it, save, apply.
import { useId } from "react"

import { useApplyDraft, useDraftDiff, useDrafts, useDraftText, useSaveDraft, type ApplyResult } from "@/api/queries.studio"
import { Pending } from "@/components/Pending"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ReviewedBadge } from "@/features/studio/ConceptsCard"
import { DiffBlock, EditorView } from "@/features/studio/EditorView"
import { draftLabel } from "@/features/studio/format"
import { ErrorNote } from "@/features/studio/StudioCard"
import { isUnprocessable, useStudioState } from "@/features/studio/store"

type DraftEditorProps = { course: string; name: string; onBack: () => void }

export function DraftEditor({ course, name, onBack }: DraftEditorProps) {
  const saved = useDraftText(course, name)
  const diff = useDraftDiff(course, name)
  const draft = useDrafts(course).data?.find((d) => d.name === name)
  // Unsaved edits outlive the rail closing; null means "as saved".
  const [edited, setEdited] = useStudioState<string | null>(`${course}:draft:${name}`, null)
  const save = useSaveDraft(course, name)
  const apply = useApplyDraft(course)
  const errorId = useId()
  const applyErrorId = useId()

  const text = edited ?? saved.data?.text ?? ""
  const dirty = edited !== null && edited !== saved.data?.text
  const saveError = save.error

  return (
    <EditorView
      title={draftLabel(name)}
      badge={draft && <ReviewedBadge reviewed={draft.reviewed} hint />}
      description="Edit the list, set reviewed: true, Save, then Apply. Concepts left out are retired, never deleted."
      onBack={onBack}
    >
      {saved.isPending ? (
        <Pending label="Loading the draft" />
      ) : saved.isError ? (
        <ErrorNote error={saved.error} />
      ) : (
        <div className="@container flex flex-col gap-4">
          <div className="grid gap-4 @2xl:grid-cols-2">
            <div className="flex min-w-0 flex-col gap-2">
              <label htmlFor={`${errorId}-text`} className="text-xs font-medium">
                Draft YAML
              </label>
              <Textarea
                id={`${errorId}-text`}
                value={text}
                onChange={(e) => {
                  setEdited(e.target.value)
                  save.reset()
                  apply.reset()
                }}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
                aria-invalid={isUnprocessable(saveError) || undefined}
                aria-describedby={saveError ? errorId : undefined}
                className="max-h-[45dvh] min-h-64 font-mono text-xs leading-relaxed md:text-xs"
              />
              {saveError && (
                <div id={errorId}>
                  <ErrorNote error={saveError} />
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={!dirty || save.isPending}
                  onClick={() => save.mutate(text, { onSuccess: () => setEdited(null) })}
                >
                  {save.isPending ? "Saving…" : "Save"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={dirty || apply.isPending}
                  aria-describedby={apply.error ? applyErrorId : undefined}
                  onClick={() => apply.mutate(name)}
                >
                  {apply.isPending ? "Applying…" : "Apply"}
                </Button>
                {dirty && <span className="text-xs text-muted-foreground">Save your edits before applying.</span>}
                {!dirty && save.isSuccess && <span role="status" className="text-xs text-muted-foreground">Saved.</span>}
              </div>
              {apply.error && (
                <div id={applyErrorId}>
                  <ErrorNote error={apply.error} />
                </div>
              )}
              {apply.data && <Applied result={apply.data} />}
            </div>
            <div className="flex min-w-0 flex-col gap-2">
              <p className="text-xs font-medium">Changes from the draft before</p>
              {diff.isPending ? (
                <Pending label="Loading the changes" />
              ) : diff.isError ? (
                <ErrorNote error={diff.error} />
              ) : diff.data.text ? (
                <DiffBlock text={diff.data.text} label="Changes from the draft before" />
              ) : (
                <p className="text-sm text-muted-foreground">The first draft: there is nothing before it to compare with.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </EditorView>
  )
}

function Applied({ result }: { result: ApplyResult }) {
  const counts = [
    `${result.added} added`,
    `${result.updated} updated`,
    `${result.unchanged} unchanged`,
    `${result.retired} retired`,
  ].join(" · ")
  return (
    <div role="status" className="flex flex-col gap-1 rounded-md border bg-muted/50 px-3 py-2 text-sm">
      <p className="font-medium">Applied: {counts}</p>
      {result.retired_names.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Retired (mastery and evidence kept): {result.retired_names.join(", ")}
        </p>
      )}
      {result.unknown_prerequisites.length > 0 && (
        <p className="text-xs text-warning">
          Prerequisites that name no concept: {result.unknown_prerequisites.join(", ")}
        </p>
      )}
    </div>
  )
}
