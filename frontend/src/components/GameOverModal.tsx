import type { GameStatus, Side } from '../types/game'

interface Props {
  status: GameStatus
  winner: Side | null
  moveCount: number
  onRematch: () => void
  onMenu: () => void
}

const STATUS_TITLE: Record<GameStatus, string> = {
  ongoing: '',
  checkmate: 'Checkmate!',
  stalemate: 'Stalemate!',
  draw: 'Draw',
  resigned: 'Resigned',
  timeout: "Time's Up!",
}

function winnerText(status: GameStatus, winner: Side | null): string {
  if (status === 'stalemate' || status === 'draw') return 'Draw'
  if (status === 'resigned') return 'You resigned — Black wins'
  if (winner === 'w') return 'White wins'
  if (winner === 'b') return 'Black wins'
  if (status === 'checkmate') return 'Checkmate'
  return ''
}

export default function GameOverModal({ status, winner, moveCount, onRematch, onMenu }: Props) {
  if (status === 'ongoing') return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-zinc-800 border border-zinc-700 rounded-2xl shadow-2xl p-8 flex flex-col items-center gap-5 min-w-72">
        <h2 className="text-3xl font-bold text-white">{STATUS_TITLE[status]}</h2>
        <p className="text-zinc-300 text-lg">{winnerText(status, winner)}</p>
        <p className="text-zinc-500 text-sm">
          {Math.ceil(moveCount / 2)} {Math.ceil(moveCount / 2) === 1 ? 'move' : 'moves'}
        </p>
        <div className="flex gap-3 mt-2">
          <button
            onClick={onRematch}
            className="px-6 py-2.5 rounded-lg bg-green-700 hover:bg-green-600 text-white font-semibold transition-colors"
          >
            Rematch
          </button>
          <button
            onClick={onMenu}
            className="px-6 py-2.5 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-white font-semibold transition-colors"
          >
            Menu
          </button>
        </div>
      </div>
    </div>
  )
}
