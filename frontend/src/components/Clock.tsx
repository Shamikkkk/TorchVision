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
  return (
    <div
      className={[
        'flex items-center justify-between px-3 py-2 rounded-lg text-sm font-mono font-semibold transition-colors',
        active
          ? low
            ? 'bg-red-900 text-red-200'
            : 'bg-zinc-700 text-white'
          : 'bg-zinc-800 text-zinc-400',
      ].join(' ')}
    >
      <span className="text-xs font-sans font-normal text-zinc-400">{label}</span>
      <span className={low && active ? 'text-red-300' : ''}>{format(ms)}</span>
    </div>
  )
}
