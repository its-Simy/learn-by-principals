// 1–5 under the last tutoring answer while the session can rate it (`/rate n`, a benchmark sample); the acknowledgement once rated.
import { Button } from "@/components/ui/button"

const RATINGS = [1, 2, 3, 4, 5] as const

type RateButtonsProps = {
  /** The server's reply once rated, e.g. "Rated the last answer 4/5." */
  rating?: string
  disabled: boolean
  onRate: (n: number) => void
}

export function RateButtons({ rating, disabled, onRate }: RateButtonsProps) {
  if (rating) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        {rating}
      </p>
    )
  }
  return (
    <div role="group" aria-label="Rate this answer" className="flex flex-wrap items-center gap-1">
      <span aria-hidden="true" className="mr-1 text-xs whitespace-nowrap text-muted-foreground">
        Rate this answer
      </span>
      {RATINGS.map((n) => (
        <Button
          key={n}
          variant="outline"
          size="icon-xs"
          className="tabular-nums"
          aria-label={`Rate ${n} out of 5`}
          disabled={disabled}
          onClick={() => onRate(n)}
        >
          {n}
        </Button>
      ))}
    </div>
  )
}
