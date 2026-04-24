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
      <div className="space-y-1.5 bg-pyro-surface/40 border border-pyro-border-accent rounded p-2.5">
        <div className="text-xs font-semibold tracking-[0.18em] uppercase text-pyro-text-muted mb-2">
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
                className={[
                  'flex items-center justify-between px-3 py-1.5 rounded border text-sm transition',
                  selected
                    ? 'bg-ember-500/10 border-ember-500/35 text-ember-400'
                    : 'bg-transparent border-white/5 text-pyro-text-dim hover:text-pyro-text hover:border-white/10',
                  gameInProgress ? 'opacity-50 cursor-not-allowed' : '',
                ].join(' ')}
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
        className="w-full px-4 py-2 rounded bg-ember-500 hover:bg-ember-400 text-pyro-bg font-bold tracking-widest uppercase text-sm transition-colors"
      >
        ⚐ New Game
      </button>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onResign}
          disabled={!gameInProgress}
          className="px-4 py-2 rounded bg-white/4 hover:bg-white/8 text-pyro-text border border-white/8 disabled:opacity-50 text-sm transition-colors"
        >
          ⚑ Resign
        </button>
        <button
          type="button"
          onClick={onFlip}
          className="px-4 py-2 rounded bg-white/4 hover:bg-white/8 text-pyro-text border border-white/8 text-sm transition-colors"
        >
          ⇄ Flip
        </button>
      </div>
    </div>
  )
}
