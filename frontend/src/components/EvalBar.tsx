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

  const displayScore =
    score === null ? null : `${score > 0 ? '+' : ''}${(score / 100).toFixed(1)}`

  // Standard orientation: dark (black) on top, light (white) on bottom.
  // Flipped: light (white) on top, dark (black) on bottom.
  // darkTopPct = how much of the bar (from the top) is the dark section.
  const darkTopPct = boardFlipped ? whitePct : 100 - whitePct

  // The score label sits just inside the winning side, near the dividing line.
  // "Winning side" = the section that is larger.
  // White winning (score > 0): light section is larger → label near its top edge.
  // Black winning (score < 0): dark section is larger → label near its bottom edge.
  const whiteWinning = score !== null && score > 0
  const blackWinning = score !== null && score < 0

  // In standard orientation, dark is on top:
  //   - black winning → dark section > 50% → label at bottom of dark section
  //   - white winning → light section > 50% → label at top of light section
  // After flip, the sections swap positions but the same logic applies.
  const labelInDark = boardFlipped ? whiteWinning : blackWinning

  return (
    <div className="w-5 h-full select-none" style={{ position: 'relative' }}>
      {/* Score label above bar (losing side) */}
      <div className="h-4" />

      {/* Bar — plain block so percentage heights resolve correctly */}
      <div
        className="rounded overflow-hidden"
        style={{
          position: 'absolute',
          top: 16,
          bottom: 16,
          left: 0,
          right: 0,
        }}
      >
        {/* Top section */}
        <div
          className="transition-all duration-300 ease-in-out"
          style={{
            height: `${darkTopPct}%`,
            backgroundColor: boardFlipped ? '#f4f4f5' : '#18181b',
            position: 'relative',
          }}
        >
          {displayScore && labelInDark && (
            <span
              className="absolute bottom-0.5 left-1/2 text-[9px] font-mono leading-none"
              style={{
                transform: 'translateX(-50%)',
                color: '#a1a1aa',
              }}
            >
              {displayScore}
            </span>
          )}
        </div>

        {/* Bottom section */}
        <div
          className="transition-all duration-300 ease-in-out"
          style={{
            height: `${100 - darkTopPct}%`,
            backgroundColor: boardFlipped ? '#18181b' : '#f4f4f5',
            position: 'relative',
          }}
        >
          {displayScore && !labelInDark && score !== null && (
            <span
              className="absolute top-0.5 left-1/2 text-[9px] font-mono leading-none"
              style={{
                transform: 'translateX(-50%)',
                color: '#52525b',
              }}
            >
              {displayScore}
            </span>
          )}
        </div>
      </div>

      {/* Spacer for bottom label row */}
      <div className="h-4" style={{ position: 'absolute', bottom: 0, width: '100%' }} />
    </div>
  )
}
