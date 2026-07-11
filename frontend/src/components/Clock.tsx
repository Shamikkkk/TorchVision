interface Props {
  ms: number
  active: boolean
}

function format(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

// Compact clock chip — lives inside the player bar, right of the captures.
export default function Clock({ ms, active }: Props) {
  const low = ms < 30_000
  return (
    <div
      className={[
        'flex items-center px-3 py-1 rounded-lg border transition-colors',
        active
          ? low
            ? 'bg-pyro-surface border-red-800/50'
            : 'bg-pyro-surface border-pyro-border-accent'
          : 'bg-pyro-bg border-pyro-border',
      ].join(' ')}
    >
      <span
        className={[
          'font-mono font-semibold text-xl tabular-nums',
          low && active
            ? 'text-red-500 animate-pyro-pulse'
            : active
              ? 'text-pyro-text'
              : 'text-pyro-text-muted',
        ].join(' ')}
      >
        {format(ms)}
      </span>
    </div>
  )
}
