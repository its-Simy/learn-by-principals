// The bubble for a request in flight: what is happening and for how long ("Simplifier is answering · 14 s").
import { Pending } from "@/components/Pending"

type PendingMessageProps = {
  label: string
  /** Epoch ms when the request was sent. */
  since: number
}

export function PendingMessage({ label, since }: PendingMessageProps) {
  return (
    <div className="w-fit max-w-[92%] rounded-2xl rounded-bl-md bg-muted px-4 py-3">
      <Pending label={label} since={since} />
    </div>
  )
}
