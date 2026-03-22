interface Props {
  score: number | null   // centipawns; positive = white advantage
  boardFlipped: boolean
}

function scoreToPct(score: number | null): number {
  if (score === null) return 50
  const clamped = Math.max(-800, Math.min(800, score))
  return 50 + (clamped / 800) * 47   // 3..97 range
}

export default function EvalBar({ score, boardFlipped }: Props) {
  const whitePct = scoreToPct(score)
  const blackPct = 100 - whitePct

  const whiteAhead = score !== null && score > 0
  const blackAhead = score !== null && score < 0
  const displayScore =
    score === null ? null : `${whiteAhead ? '+' : ''}${(score / 100).toFixed(1)}`

  // When not flipped: black on top, white on bottom
  const topPct = boardFlipped ? whitePct : blackPct
  const botPct = boardFlipped ? blackPct : whitePct
  const topColor = boardFlipped ? 'bg-zinc-100' : 'bg-zinc-900'
  const botColor = boardFlipped ? 'bg-zinc-900' : 'bg-zinc-100'

  // Score label sits at the dividing line on the winning side
  const labelOnTop = boardFlipped ? whiteAhead : blackAhead

  return (
    <div className="flex flex-col items-center w-5 select-none h-full gap-0.5">
      {/* Score label — floats at top if black is winning (not flipped) */}
      <div className="h-4 flex items-center">
        {labelOnTop && displayScore && (
          <span className="text-[9px] text-zinc-300 font-mono leading-none">{displayScore}</span>
        )}
      </div>

      {/* Bar */}
      <div className="flex-1 w-full rounded overflow-hidden flex flex-col relative" style={{ minHeight: 0 }}>
        <div
          className={`${topColor} transition-all duration-300 ease-in-out`}
          style={{ height: `${topPct}%` }}
        />
        <div
          className={`${botColor} transition-all duration-300 ease-in-out`}
          style={{ height: `${botPct}%` }}
        />
      </div>

      {/* Score label — floats at bottom if white is winning (not flipped) */}
      <div className="h-4 flex items-center">
        {!labelOnTop && displayScore && (
          <span className="text-[9px] text-zinc-300 font-mono leading-none">{displayScore}</span>
        )}
      </div>
    </div>
  )
}
