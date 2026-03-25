import type { BestWasMessage } from '../types/game'

interface Props {
  evalMove: string | null
  evalScore: number | null
  bestWas: BestWasMessage | null
}

const BADGE: Record<
  BestWasMessage['classification'],
  { bg: string; text: string; border: string; label: string; tagline: string }
> = {
  book: {
    bg: 'bg-indigo-950',
    text: 'text-indigo-300',
    border: 'border-indigo-700',
    label: '📖 Book move',
    tagline: 'Theory',
  },
  brilliant: {
    bg: 'bg-cyan-950',
    text: 'text-cyan-300',
    border: 'border-cyan-700',
    label: '!! Brilliant!',
    tagline: 'Best move — a genuine sacrifice',
  },
  best: {
    bg: 'bg-green-950',
    text: 'text-green-300',
    border: 'border-green-700',
    label: '! Best move!',
    tagline: "Engine's top choice",
  },
  good: {
    bg: 'bg-green-950/60',
    text: 'text-green-400',
    border: 'border-green-800',
    label: 'Good move',
    tagline: 'Within engine range',
  },
  inaccuracy: {
    bg: 'bg-yellow-950',
    text: 'text-yellow-300',
    border: 'border-yellow-700',
    label: '?! Inaccuracy',
    tagline: 'A better move was available',
  },
  mistake: {
    bg: 'bg-orange-950',
    text: 'text-orange-300',
    border: 'border-orange-700',
    label: '? Mistake',
    tagline: 'Gave up a significant advantage',
  },
  blunder: {
    bg: 'bg-red-950',
    text: 'text-red-300',
    border: 'border-red-700',
    label: '?? Blunder!',
    tagline: 'A serious error',
  },
  miss: {
    bg: 'bg-red-950',
    text: 'text-red-300',
    border: 'border-red-700',
    label: 'Missed checkmate!',
    tagline: 'A forced mate was available',
  },
}

export default function EnginePanel({ evalMove, evalScore, bestWas }: Props) {
  const scoreStr =
    evalScore === null
      ? null
      : `${evalScore > 0 ? '+' : ''}${(evalScore / 100).toFixed(2)}`

  const badge = bestWas ? BADGE[bestWas.classification] : null
  const showMoveComparison =
    bestWas &&
    !bestWas.is_best &&
    bestWas.classification !== 'brilliant' &&
    bestWas.classification !== 'good'

  return (
    <div className="rounded-xl border border-zinc-700/50 overflow-hidden">
      <div className="px-3 py-2 border-b border-zinc-700">
        <div className="text-xs font-semibold text-zinc-500 uppercase tracking-widest">Pyro</div>
        <div className="text-xs text-zinc-600">Tal Style ⚔️</div>
      </div>

      {/* Section 1 — Last Move Analysis */}
      {bestWas && badge && (
        <div className="px-3 py-2.5 border-b border-zinc-700/60 animate-fade-in">
          <div className="text-xs text-zinc-500 uppercase tracking-widest mb-2">Last move</div>

          {/* Classification badge */}
          <div className={`rounded-lg border px-2.5 py-1.5 mb-2 ${badge.bg} ${badge.border}`}>
            <div className="flex items-center justify-between gap-2">
              <span className={`text-sm font-bold ${badge.text}`}>{badge.label}</span>
              {bestWas.cp_loss > 20 && bestWas.classification !== 'miss' && (
                <span className="font-mono text-xs text-red-400 tabular-nums">
                  −{bestWas.cp_loss} cp
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-500 mt-0.5">{badge.tagline}</p>
          </div>

          {/* Move comparison for inaccuracy / mistake / blunder / miss */}
          {showMoveComparison && (
            <div className="space-y-0.5 pl-0.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-zinc-500">You played</span>
                <span className="font-mono text-sm text-zinc-300">{bestWas.human_move}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-zinc-500">Best was</span>
                <span className="font-mono text-sm text-green-400 font-semibold">
                  {bestWas.best_move}
                </span>
              </div>
            </div>
          )}

          {/* Good move: show engine alternative when different */}
          {bestWas.classification === 'good' && !bestWas.is_best && (
            <p className="text-xs text-zinc-500 pl-0.5">
              Engine also liked:{' '}
              <span className="font-mono text-green-400">{bestWas.best_move}</span>
            </p>
          )}
        </div>
      )}

      {/* Section 2 — Engine suggestion for next move */}
      <div className="px-3 py-2.5">
        <div className="text-xs text-zinc-500 uppercase tracking-widest mb-1">Suggests</div>
        <div className="flex items-center justify-between gap-2">
          {evalMove ? (
            <>
              <span className="font-mono text-sm text-green-400 font-semibold">{evalMove}</span>
              {scoreStr && (
                <span className="font-mono text-xs text-zinc-500 tabular-nums">{scoreStr}</span>
              )}
            </>
          ) : (
            <span className="text-xs text-zinc-600 italic">thinking…</span>
          )}
        </div>
      </div>
    </div>
  )
}
