import { useEffect, useRef } from 'react'

interface Props {
  history: string[]
  moveSymbols?: Record<number, string>
}

const SYMBOL_COLORS: Record<string, string> = {
  '!!': 'text-cyan-400',
  '!': 'text-green-400',
  '?!': 'text-yellow-400',
  '?': 'text-orange-400',
  '??': 'text-red-400',
  'missed #': 'text-red-400',
}

function MoveChip({
  move,
  isCurrent,
  symbol,
}: {
  move: string
  isCurrent: boolean
  symbol?: string
}) {
  return (
    <span className="inline-flex items-center gap-0.5">
      <span
        className={[
          'inline-block px-2 py-0.5 rounded font-mono text-sm cursor-pointer transition-colors duration-100',
          isCurrent
            ? 'bg-ember-500/15 text-ember-400'
            : 'text-pyro-text hover:bg-pyro-surface hover:text-pyro-cream',
        ].join(' ')}
      >
        {move}
      </span>
      {symbol && (
        <span
          className={`text-xs font-bold ${SYMBOL_COLORS[symbol] ?? 'text-pyro-text-dim'}`}
          title={symbol}
        >
          {symbol}
        </span>
      )}
    </span>
  )
}

export default function MoveList({ history, moveSymbols = {} }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history])

  const currentIdx = history.length - 1
  const rowCount = Math.ceil(history.length / 2)

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-pyro-border-accent bg-pyro-surface/40">
      <div className="px-3 py-2 text-xs font-semibold text-pyro-text-muted uppercase tracking-widest border-b border-pyro-border">
        Scoresheet
      </div>
      <div className="overflow-y-auto" style={{ maxHeight: 220 }}>
        {history.length === 0 ? (
          <p className="text-pyro-text-faint italic text-sm px-3 py-3">No moves yet</p>
        ) : (
          Array.from({ length: rowCount }, (_, i) => {
            const whiteIdx = i * 2
            const blackIdx = i * 2 + 1
            const isEven = i % 2 === 0
            return (
              <div
                key={i}
                className={[
                  'flex items-center gap-1 px-2 py-0.5',
                  isEven ? 'bg-pyro-surface/60' : 'bg-transparent',
                ].join(' ')}
              >
                <span className="w-7 text-right text-xs text-pyro-text-faint font-mono select-none shrink-0 pr-1">
                  {i + 1}.
                </span>
                <span className="w-[100px] shrink-0">
                  <MoveChip
                    move={history[whiteIdx]}
                    isCurrent={whiteIdx === currentIdx}
                    symbol={moveSymbols[whiteIdx]}
                  />
                </span>
                <span className="w-[100px] shrink-0">
                  {history[blackIdx] !== undefined && (
                    <MoveChip
                      move={history[blackIdx]}
                      isCurrent={blackIdx === currentIdx}
                      symbol={moveSymbols[blackIdx]}
                    />
                  )}
                </span>
              </div>
            )
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
