import type { GameSummary } from '../../hooks/useAnalyzer'

interface Props {
  summary: GameSummary
  totalMoves: number
}

const CATS: Array<{ key: keyof GameSummary; label: string; color: string }> = [
  { key: 'brilliant',  label: '!!',         color: 'bg-cyan-500' },
  { key: 'best',       label: '!',          color: 'bg-green-500' },
  { key: 'good',       label: 'Good',       color: 'bg-green-700' },
  { key: 'book',       label: '📖',         color: 'bg-indigo-500' },
  { key: 'inaccuracy', label: '?!',         color: 'bg-yellow-500' },
  { key: 'mistake',    label: '?',          color: 'bg-orange-500' },
  { key: 'blunder',    label: '??',         color: 'bg-red-500' },
  { key: 'miss',       label: 'miss #',     color: 'bg-red-700' },
]

function AccuracyColor(pct: number) {
  if (pct >= 80) return 'text-green-400'
  if (pct >= 60) return 'text-yellow-400'
  return 'text-red-400'
}

export default function AccuracySummary({ summary }: Props) {
  const playerMoves = CATS.reduce((s, c) => s + (summary[c.key] as number), 0)

  return (
    <div className="space-y-2">
      {/* Accuracy */}
      <div className="flex items-end gap-2">
        <span className={`font-display text-3xl font-bold tabular-nums ${AccuracyColor(summary.accuracy)}`}>
          {summary.accuracy.toFixed(1)}%
        </span>
        <span className="text-xs text-pyro-text-dim pb-1">
          accuracy · {playerMoves} moves analysed
        </span>
      </div>

      {/* Classification counts */}
      <div className="grid grid-cols-4 gap-1">
        {CATS.map(({ key, label, color }) => {
          const count = summary[key] as number
          if (count === 0) return null
          return (
            <div
              key={key}
              className="flex items-center gap-1.5 rounded-md bg-pyro-surface/60 px-2 py-1"
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} />
              <span className="font-mono text-xs text-pyro-text-dim">{label}</span>
              <span className="font-mono text-xs font-bold text-pyro-text ml-auto">{count}</span>
            </div>
          )
        })}
      </div>

      {/* Mini bar */}
      <div className="flex h-1.5 rounded-full overflow-hidden gap-px">
        {CATS.map(({ key, color }) => {
          const count = summary[key] as number
          if (count === 0 || playerMoves === 0) return null
          return (
            <div
              key={key}
              className={color}
              style={{ flex: count / playerMoves }}
            />
          )
        })}
      </div>
    </div>
  )
}
