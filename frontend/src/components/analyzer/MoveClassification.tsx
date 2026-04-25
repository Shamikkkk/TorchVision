import type { AnalyzedMove } from '../../hooks/useAnalyzer'

interface Props {
  move: AnalyzedMove | null
}

const BADGE: Record<string, { bg: string; text: string; border: string; label: string }> = {
  book:       { bg: 'bg-indigo-950', text: 'text-indigo-300', border: 'border-indigo-700', label: '📖 Book move' },
  brilliant:  { bg: 'bg-cyan-950',   text: 'text-cyan-300',   border: 'border-cyan-700',   label: '!! Brilliant!' },
  best:       { bg: 'bg-green-950',  text: 'text-green-300',  border: 'border-green-700',  label: '! Best move' },
  good:       { bg: 'bg-green-950/60', text: 'text-green-400', border: 'border-green-800', label: 'Good move' },
  inaccuracy: { bg: 'bg-yellow-950', text: 'text-yellow-300', border: 'border-yellow-700', label: '?! Inaccuracy' },
  mistake:    { bg: 'bg-orange-950', text: 'text-orange-300', border: 'border-orange-700', label: '? Mistake' },
  blunder:    { bg: 'bg-red-950',    text: 'text-red-300',    border: 'border-red-700',    label: '?? Blunder!' },
  miss:       { bg: 'bg-red-950',    text: 'text-red-300',    border: 'border-red-700',    label: 'Missed mate!' },
}

export default function MoveClassification({ move }: Props) {
  if (!move) {
    return (
      <div className="h-16 flex items-center justify-center text-xs text-pyro-text-faint italic">
        Select a move to see analysis
      </div>
    )
  }

  const badge = BADGE[move.classification]
  if (!badge) return null

  const showComparison =
    !move.is_best &&
    move.classification !== 'book' &&
    move.classification !== 'brilliant'

  return (
    <div className="animate-fade-in">
      <div className={`rounded-lg border px-3 py-2 ${badge.bg} ${badge.border} flex items-center justify-between gap-3`}>
        <span className={`text-sm font-bold ${badge.text}`}>{badge.label}</span>
        {move.cp_loss > 20 && move.classification !== 'book' && move.classification !== 'miss' && (
          <span className="font-mono text-xs text-red-400 tabular-nums shrink-0">
            −{move.cp_loss} cp
          </span>
        )}
      </div>

      {showComparison && (
        <div className="flex gap-4 mt-1.5 px-0.5">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-pyro-text-dim">Played</span>
            <span className="font-mono text-sm text-pyro-text">{move.san}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-pyro-text-dim">Best</span>
            <span className="font-mono text-sm text-green-400 font-semibold">{move.best_move}</span>
          </div>
        </div>
      )}
    </div>
  )
}
