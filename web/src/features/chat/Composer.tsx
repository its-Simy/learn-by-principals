// The message box: Enter sends, Shift+Enter is a new line; disabled while a request is in flight.
import { ArrowUp, BookOpen } from "lucide-react"
import { useState, type KeyboardEvent, type Ref } from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type ComposerProps = {
  ref?: Ref<HTMLTextAreaElement>
  disabled: boolean
  placeholder: string
  onSend: (text: string) => void
  /** Only during a live session: send the next messages to the sources (`/ask`) instead of the tutor. */
  sourcesOnly?: { on: boolean; onChange: (on: boolean) => void }
  /** One quiet line under the box, e.g. which sources an ask covers. */
  hint?: string
}

export function Composer({ ref, disabled, placeholder, onSend, sourcesOnly, hint }: ComposerProps) {
  const [text, setText] = useState("")
  const ready = !disabled && text.trim().length > 0

  const send = () => {
    if (!ready) return
    onSend(text.trim())
    setText("")
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // An IME's Enter confirms a composition; it must not send.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="shrink-0 border-t bg-background">
      <form
        className="mx-auto w-full max-w-3xl px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <div className="rounded-2xl border bg-background shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50">
          <Textarea
            ref={ref}
            aria-label="Message"
            rows={1}
            value={text}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            // The box around it draws the border and focus ring; `!` beats the textarea's own dark-theme fill.
            className="max-h-48 min-h-12 resize-none border-0 bg-transparent! text-[15px] shadow-none focus-visible:ring-0"
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            {sourcesOnly && (
              <Button
                type="button"
                variant={sourcesOnly.on ? "secondary" : "ghost"}
                size="xs"
                aria-pressed={sourcesOnly.on}
                className={cn(sourcesOnly.on && "ring-1 ring-ring/40")}
                onClick={() => sourcesOnly.onChange(!sourcesOnly.on)}
              >
                <BookOpen />
                Sources only
              </Button>
            )}
            <Button type="submit" size="icon-sm" className="ml-auto rounded-full" aria-label="Send" disabled={!ready}>
              <ArrowUp />
            </Button>
          </div>
        </div>
        {hint && <p className="mt-1.5 px-1 text-xs text-muted-foreground">{hint}</p>}
      </form>
    </div>
  )
}
