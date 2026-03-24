import type { ChessComGame } from '../../hooks/useAnalyzer'

interface Props {
  games: ChessComGame[]
  username: string
  onSelect: (game: ChessComGame) => void
  onBack: () => void
}

function resultBadge(result: string, username: string, white: string) {
  const isWhite = username.toLowerCase() === white.toLowerCase()
  const won = (isWhite && result === '1-0') || (!isWhite && result === '0-1')
  const draw = result === '1/2-1/2'

  const label = draw ? '½-½' : result
  const cls = draw
    ? 'bg-zinc-600 text-zinc-200'
    : won
    ? 'bg-green-700 text-green-100'
    : 'bg-red-800 text-red-100'

  return (
    <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${cls}`}>{label}</span>
  )
}

function tcLabel(tc: string): string {
  const secs = parseInt(tc, 10)
  if (isNaN(secs)) return tc
  if (secs < 180) return 'Bullet'
  if (secs < 600) return 'Blitz'
  if (secs < 1800) return 'Rapid'
  return 'Classical'
}

export default function GameList({ games, username, onSelect, onBack }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-zinc-500 uppercase tracking-widest">
          Recent games · {username}
        </span>
        <button
          onClick={onBack}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          ← change user
        </button>
      </div>

      {games.map((g) => {
        const opponent =
          username.toLowerCase() === g.white.toLowerCase() ? g.black : g.white
        return (
          <button
            key={g.id}
            onClick={() => onSelect(g)}
            className="w-full text-left rounded-lg border border-zinc-700/60 bg-zinc-800/50
                       hover:bg-zinc-700/60 hover:border-zinc-600 transition-colors px-3 py-2.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-white font-medium truncate">vs {opponent}</span>
              {resultBadge(g.result, username, g.white)}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-zinc-500">{g.date}</span>
              <span className="text-zinc-700">·</span>
              <span className="text-xs text-zinc-500">{tcLabel(g.time_control)}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
