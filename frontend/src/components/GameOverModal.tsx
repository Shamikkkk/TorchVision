import { useEffect, useState } from 'react'
import type { GameStatus, Side } from '../types/game'

interface Props {
  status: GameStatus
  winner: Side | null
  moveCount: number
  humanColor: Side
  onRematch: () => void
  onMenu: () => void
  pyroSays?: string | null
}

export default function GameOverModal({
  status,
  winner,
  moveCount,
  humanColor,
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

  const isDraw = winner === null || status === 'stalemate' || status === 'draw'
  const pyroWon = !isDraw && winner !== humanColor

  // Score in standard notation (white wins = 1-0, black wins = 0-1)
  const scoreStr = isDraw ? '½–½' : winner === 'w' ? '1–0' : '0–1'

  const kicker = isDraw
    ? 'Draw'
    : status === 'checkmate'
      ? 'Checkmate'
      : status === 'resigned'
        ? 'Resigned'
        : status === 'timeout'
          ? "Time's Up"
          : 'Game Over'

  const headline = isDraw
    ? 'Acceptable. Barely.'
    : pyroWon
      ? 'That was never going to end any other way.'
      : 'I let my guard down.'

  const fallbackTaunt = isDraw ? 'Coward.' : pyroWon ? 'Burn.' : '...'
  const taunt = pyroSays || fallbackTaunt

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-700 ${
        visible ? 'bg-black/85 backdrop-blur-sm' : 'bg-black/0 pointer-events-none'
      }`}
    >
      <div
        className={`flex flex-col items-center max-w-lg px-8 transition-all duration-700 ${
          visible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'
        }`}
      >
        {/* Kicker */}
        <div className="font-mono text-xs text-ember-500 tracking-[0.4em] uppercase mb-4 animate-pyro-fade-up">
          {kicker}
        </div>

        {/* Score */}
        <div
          className="font-display text-7xl text-ember-500 mb-2 animate-pyro-fade-up"
          style={{
            textShadow: '0 0 40px rgba(255, 122, 42, 0.5)',
            animationDelay: '100ms',
            animationFillMode: 'both',
          }}
        >
          {scoreStr}
        </div>

        {/* Flame */}
        <div
          className={`my-4 animate-pyro-fade-up ${isDraw ? 'text-4xl opacity-50' : 'text-6xl'}`}
          style={{ animationDelay: '200ms', animationFillMode: 'both' }}
        >
          🔥
        </div>

        {/* Headline */}
        <h1
          className="font-display text-3xl sm:text-4xl text-pyro-cream text-center leading-tight mb-6 animate-pyro-fade-up"
          style={{ animationDelay: '300ms', animationFillMode: 'both' }}
        >
          {headline}
        </h1>

        {/* Pyro's taunt */}
        {taunt && (
          <div
            className="border-l-2 border-ember-500 pl-4 mb-8 animate-pyro-fade-up"
            style={{ animationDelay: '500ms', animationFillMode: 'both' }}
          >
            <div className="font-mono text-[10px] text-ember-500 tracking-[0.2em] uppercase mb-1">
              pyro says
            </div>
            <div className="font-display text-xl sm:text-2xl italic text-pyro-taunt">
              &ldquo;{taunt}&rdquo;
            </div>
          </div>
        )}

        {/* Stats */}
        <div
          className="grid grid-cols-2 gap-8 mb-8 pt-6 border-t border-dashed border-ember-500/20 w-full animate-pyro-fade-up"
          style={{ animationDelay: '600ms', animationFillMode: 'both' }}
        >
          <div>
            <div className="text-[10px] text-pyro-text-muted tracking-widest uppercase mb-1">
              Moves
            </div>
            <div className="font-display text-2xl text-pyro-cream">
              {Math.ceil(moveCount / 2)}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-pyro-text-muted tracking-widest uppercase mb-1">
              Result
            </div>
            <div className="font-display text-2xl text-pyro-cream">{scoreStr}</div>
          </div>
        </div>

        {/* Buttons */}
        <div
          className="flex gap-3 animate-pyro-fade-up"
          style={{ animationDelay: '700ms', animationFillMode: 'both' }}
        >
          <button
            type="button"
            onClick={onRematch}
            className="px-7 py-3 bg-ember-500 text-pyro-bg rounded font-bold text-xs tracking-widest uppercase hover:brightness-110 transition-all"
            style={{ boxShadow: '0 0 32px rgba(255, 122, 42, 0.35)' }}
          >
            🔥 Rematch
          </button>
          <button
            type="button"
            onClick={onMenu}
            className="px-6 py-3 bg-transparent text-pyro-text border border-pyro-cream/20 rounded font-semibold text-xs tracking-widest uppercase hover:brightness-110 transition-all"
          >
            Menu
          </button>
        </div>
      </div>
    </div>
  )
}
