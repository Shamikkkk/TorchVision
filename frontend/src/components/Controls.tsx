import { useEffect, useState } from 'react'
import type { Difficulty } from '../types/game'

type Props = {
  onNewGame: (difficulty: Difficulty) => void
  onResign: () => void
  onFlip: () => void
  gameInProgress: boolean
}

const LEVELS: { id: Difficulty; label: string; sub: string }[] = [
  { id: 'beginner',     label: '😴 Sleeping', sub: '0.1s' },
  { id: 'intermediate', label: '😺 Playful',  sub: '0.5s' },
  { id: 'advanced',     label: '🔥 Awake',    sub: '2s'   },
  { id: 'expert',       label: '🗡️ Hunting',  sub: '5s'   },
  { id: 'master',       label: '💀 Feral',    sub: 'full' },
]

const STORAGE_KEY = 'pyro.difficulty'

function loadDifficulty(): Difficulty {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && LEVELS.some(l => l.id === stored)) {
      return stored as Difficulty
    }
  } catch {}
  return 'master'
}

export function Controls({ onNewGame, onResign, onFlip, gameInProgress }: Props) {
  const [difficulty, setDifficulty] = useState<Difficulty>(loadDifficulty)

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, difficulty) } catch {}
  }, [difficulty])

  return (
    <div className="space-y-3">
      {/* Difficulty picker */}
      <div className="space-y-1.5">
        <div className="text-xs uppercase tracking-wider text-zinc-500">
          Pyro's Mood
        </div>
        <div className="grid grid-cols-1 gap-1">
          {LEVELS.map(level => {
            const selected = difficulty === level.id
            return (
              <button
                key={level.id}
                type="button"
                disabled={gameInProgress}
                onClick={() => setDifficulty(level.id)}
                className={
                  'flex items-center justify-between px-3 py-1.5 rounded text-sm transition ' +
                  (selected
                    ? 'bg-violet-600 text-white'
                    : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700') +
                  (gameInProgress ? ' opacity-50 cursor-not-allowed' : '')
                }
              >
                <span>{level.label}</span>
                <span className="text-xs opacity-70">{level.sub}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Action buttons */}
      <button
        type="button"
        onClick={() => onNewGame(difficulty)}
        className="w-full px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium"
      >
        ⚐ New Game
      </button>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onResign}
          disabled={!gameInProgress}
          className="px-4 py-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 disabled:opacity-50"
        >
          ⚑ Resign
        </button>
        <button
          type="button"
          onClick={onFlip}
          className="px-4 py-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
        >
          ⇄ Flip
        </button>
      </div>
    </div>
  )
}
