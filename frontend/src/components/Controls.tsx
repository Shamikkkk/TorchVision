import type { GameState } from '../types/game'

interface Props {
  game: GameState
}

export default function Controls({ game }: Props) {
  const { newGame, resign, flipBoard, status } = game
  const isOngoing = status === 'ongoing'

  return (
    <div className="flex flex-col gap-2">
      <button
        onClick={newGame}
        className="w-full flex items-center justify-center gap-2 bg-gradient-to-b from-green-600 to-green-700 hover:from-green-500 hover:to-green-600 shadow-lg text-white text-xs font-semibold uppercase tracking-wide py-2.5 px-4 rounded-xl transition-all duration-150 active:scale-95"
      >
        <span>♟</span> New Game
      </button>
      <div className="flex gap-2">
        <button
          onClick={resign}
          disabled={!isOngoing}
          className="flex-1 flex items-center justify-center gap-1.5 bg-zinc-700 border border-zinc-600 hover:bg-red-900/50 hover:border-red-800 disabled:opacity-30 disabled:cursor-not-allowed text-white text-xs font-semibold uppercase tracking-wide py-2.5 px-3 rounded-xl transition-all duration-150 active:scale-95"
        >
          <span>⚑</span> Resign
        </button>
        <button
          onClick={flipBoard}
          className="flex-1 flex items-center justify-center gap-1.5 bg-zinc-700 border border-zinc-600 hover:bg-zinc-600 text-white text-xs font-semibold uppercase tracking-wide py-2.5 px-3 rounded-xl transition-all duration-150 active:scale-95"
        >
          <span>⇄</span> Flip
        </button>
      </div>
    </div>
  )
}
