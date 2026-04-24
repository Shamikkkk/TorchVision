import { useState } from 'react'
import type { Difficulty } from '../types/game'

const MOODS: { id: Difficulty; label: string; emoji: string; sub: string }[] = [
  { id: 'beginner',     label: 'Sleeping', emoji: '😴', sub: '0.1s'  },
  { id: 'intermediate', label: 'Playful',  emoji: '😺', sub: '0.5s'  },
  { id: 'advanced',     label: 'Awake',    emoji: '🔥', sub: '2s'    },
  { id: 'expert',       label: 'Hunting',  emoji: '🗡️', sub: '5s'    },
  { id: 'master',       label: 'Feral',    emoji: '💀', sub: 'full'  },
]

type Props = {
  currentMood: Difficulty
  onMoodChange: (mood: Difficulty) => void
  onStart: () => void
}

export default function LobbyScreen({ currentMood, onMoodChange, onStart }: Props) {
  const [side, setSide] = useState<'White' | 'Random' | 'Black'>('White')

  return (
    <div className="min-h-screen bg-pyro-bg text-pyro-text font-sans flex flex-col relative overflow-hidden">
      {/* Ambient ember glow */}
      <div
        className="absolute w-[600px] h-[600px] -bottom-48 -right-48 rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, rgba(255,122,42,0.13) 0%, transparent 60%)' }}
      />
      <div
        className="absolute w-[400px] h-[400px] -top-24 -left-24 rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, rgba(255,122,42,0.07) 0%, transparent 60%)' }}
      />

      {/* Top bar */}
      <div className="flex items-center justify-between px-10 py-5 border-b border-pyro-border-subtle z-10">
        <div className="flex items-center gap-2">
          <span className="text-xl animate-pyro-flicker">🔥</span>
          <span className="font-display text-lg text-ember-500 italic">Pyro</span>
        </div>
        <div className="flex gap-6 text-xs tracking-widest uppercase text-pyro-text-dim">
          <span className="text-pyro-text font-semibold border-b border-ember-500 pb-0.5">Play</span>
          <span>Analyze</span>
        </div>
      </div>

      {/* Hero */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-10 px-10 lg:px-14 py-12 z-10">
        {/* Left: headline */}
        <div className="flex flex-col justify-center">
          <div className="font-mono text-[11px] text-ember-500 tracking-[0.3em] uppercase mb-4">
            Engine · v1.0 · ~1800 Elo
          </div>
          <h1 className="font-display text-6xl lg:text-8xl font-normal leading-[0.95] text-pyro-cream tracking-tight mb-6">
            I burn<br />
            <span
              className="italic text-ember-500"
              style={{ textShadow: '0 0 30px rgba(255,122,42,0.5)' }}
            >
              brightest
            </span><br />
            when you're<br />
            <span className="italic">losing.</span>
          </h1>
          <p className="text-sm text-pyro-text-dim max-w-md leading-relaxed mb-10">
            Pyro is a hand-built Tal-style chess engine. Alpha-beta search,
            aggressive sacrifices, zero patience for positional play.
            Trained to hunt kings, not to win endgames.
          </p>
          <div className="flex gap-3">
            <button
              onClick={onStart}
              className="px-7 py-3.5 bg-ember-500 text-pyro-bg rounded font-bold text-xs tracking-[0.14em] uppercase hover:brightness-110 transition-all"
              style={{ boxShadow: '0 0 40px rgba(255,122,42,0.3)' }}
            >
              Wake Pyro →
            </button>
            <button className="px-7 py-3.5 bg-transparent text-pyro-text border border-pyro-cream/20 rounded font-semibold text-xs tracking-[0.14em] uppercase hover:brightness-110 transition-all">
              Analyze a Game
            </button>
          </div>
        </div>

        {/* Right: mood selector */}
        <div className="flex flex-col gap-5 bg-ember-500/[0.03] border border-ember-500/[0.12] rounded p-6">
          <div>
            <div className="text-[10px] font-semibold tracking-[0.18em] uppercase text-pyro-text-muted mb-3">
              Pyro's Mood
            </div>
            <div className="flex flex-col gap-1.5">
              {MOODS.map(m => (
                <button
                  key={m.id}
                  onClick={() => onMoodChange(m.id)}
                  className={[
                    'flex items-center justify-between px-3 py-2.5 rounded text-sm font-medium transition-all border',
                    currentMood === m.id
                      ? 'bg-ember-500/10 border-ember-500/35 text-ember-400'
                      : 'bg-transparent border-white/5 text-pyro-text-dim hover:text-pyro-text',
                  ].join(' ')}
                >
                  <span>{m.emoji} {m.label}</span>
                  <span className="font-mono text-xs">{m.sub}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-dashed border-ember-500/15 pt-5">
            <div className="text-[10px] font-semibold tracking-[0.18em] uppercase text-pyro-text-muted mb-3">
              Play as
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {(['White', 'Random', 'Black'] as const).map((c) => (
                <button
                  key={c}
                  onClick={() => setSide(c)}
                  className={[
                    'py-2.5 rounded text-xs font-semibold transition-all border',
                    side === c
                      ? 'bg-pyro-cream/[0.08] border-pyro-cream/30 text-pyro-cream'
                      : 'bg-transparent border-white/5 text-pyro-text-dim hover:text-pyro-text',
                  ].join(' ')}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
