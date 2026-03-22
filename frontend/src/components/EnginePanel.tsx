interface Props {
  evalMove: string | null
  evalScore: number | null
}

export default function EnginePanel({ evalMove, evalScore }: Props) {
  const scoreStr =
    evalScore === null
      ? null
      : `${evalScore > 0 ? '+' : ''}${(evalScore / 100).toFixed(2)}`

  return (
    <div className="rounded-xl border border-zinc-700/50 overflow-hidden">
      <div className="px-3 py-2 text-xs font-semibold text-zinc-500 uppercase tracking-widest border-b border-zinc-700">
        Engine
      </div>
      <div className="px-3 py-2.5 flex items-center justify-between gap-2">
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
  )
}
