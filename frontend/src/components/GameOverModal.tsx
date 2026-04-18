import { useEffect, useState } from 'react'
import type { GameStatus, Side } from '../types/game'

interface Props {
  status: GameStatus
  winner: Side | null
  moveCount: number
  onRematch: () => void
  onMenu: () => void
  pyroSays?: string | null
}

export default function GameOverModal({
  status,
  winner,
  moveCount,
  onRematch,
  onMenu,
  pyroSays,
}: Props) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 100)
    return () => clearTimeout(t)
  }, [])

  if (status === 'ongoing') return null

  const isDraw = !winner || status === 'stalemate' || status === 'draw'

  const resultText = isDraw
    ? 'Draw'
    : status === 'checkmate'
      ? 'Checkmate'
      : status === 'resigned'
        ? 'Resigned'
        : status === 'timeout'
          ? "Time's Up"
          : 'Game Over'

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-700 ${
        visible ? 'bg-black/80 backdrop-blur-sm' : 'bg-black/0'
      }`}
    >
      <div
        className={`flex flex-col items-center gap-6 p-10 max-w-sm transition-all duration-700 ${
          visible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'
        }`}
      >
        {/* Pyro's flame */}
        <div
          className={`transition-all duration-1000 ${
            isDraw ? 'text-4xl opacity-50' : 'text-6xl opacity-100'
          }`}
        >
          🔥
        </div>

        {/* Pyro's taunt — the centerpiece */}
        {pyroSays && (
          <p className="text-orange-400 text-lg italic text-center leading-relaxed">
            "{pyroSays}"
          </p>
        )}

        {/* Result */}
        <div className="text-center">
          <p className="text-zinc-300 text-xl font-semibold">{resultText}</p>
          <p className="text-zinc-500 text-sm mt-1">
            {Math.ceil(moveCount / 2)}{' '}
            {Math.ceil(moveCount / 2) === 1 ? 'move' : 'moves'}
          </p>
        </div>

        {/* Buttons */}
        <div className="flex gap-3 mt-2">
          <button
            type="button"
            onClick={onRematch}
            className="px-6 py-2.5 rounded bg-orange-600 hover:bg-orange-500 text-white font-medium transition-colors"
          >
            🔥 Rematch
          </button>
          <button
            type="button"
            onClick={onMenu}
            className="px-6 py-2.5 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-200 font-medium transition-colors"
          >
            Menu
          </button>
        </div>
      </div>
    </div>
  )
}
