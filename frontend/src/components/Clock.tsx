interface Props {
  ms: number
  active: boolean
  label: string
}

function format(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function Clock({ ms, active, label }: Props) {
  const low = ms < 30_000
  const isPyro = label === 'Pyro'
  return (
    <div
      className={[
        'flex items-center justify-between px-3 py-2 rounded-lg border transition-colors',
        active
          ? low
            ? 'bg-pyro-surface border-red-800/50'
            : 'bg-pyro-surface border-pyro-border-accent'
          : 'bg-pyro-bg border-pyro-border',
      ].join(' ')}
    >
      <span
        className={[
          'text-xs font-sans font-medium',
          isPyro ? 'text-ember-400' : 'text-pyro-text-dim',
        ].join(' ')}
      >
        {label}
      </span>
      <span
        className={[
          'font-mono font-semibold text-sm',
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
