import { useEffect, useRef, useState } from 'react'

interface Props {
  text: string | null
  event: string | null
  enabled: boolean
}

const HOLD_MS = 4500
const FADE_MS = 700

/**
 * G13 — Pyro's speech bubble, anchored near Pyro's side of the board.
 * Fades in on a new line, holds ~5s, fades out. An incoming taunt replaces
 * the current one. Game-end lines persist until dismissed.
 */
export default function PyroSpeech({ text, event, enabled }: Props) {
  const [shown, setShown] = useState<string | null>(null)
  const [fading, setFading] = useState(false)
  const timersRef = useRef<number[]>([])
  const isGameEnd = event?.startsWith('game_end') ?? false

  useEffect(() => {
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
    if (!text || !enabled) {
      setShown(null)
      return
    }
    setShown(text)
    setFading(false)
    if (!isGameEnd) {
      timersRef.current.push(window.setTimeout(() => setFading(true), HOLD_MS))
      timersRef.current.push(window.setTimeout(() => setShown(null), HOLD_MS + FADE_MS))
    }
    return () => {
      timersRef.current.forEach(clearTimeout)
      timersRef.current = []
    }
  }, [text, event, enabled, isGameEnd])

  return (
    <div className="h-9 flex items-center">
      {shown && (
        <div
          className={[
            'inline-flex items-center gap-2 max-w-full px-3 py-1 rounded-full rounded-bl-sm',
            'bg-ember-500/10 border border-ember-500/30',
            'animate-pyro-taunt-in transition-opacity',
            fading ? 'opacity-0' : 'opacity-100',
          ].join(' ')}
          style={{ transitionDuration: `${FADE_MS}ms` }}
          role="status"
        >
          <span className="font-display text-sm italic text-pyro-taunt truncate">
            &ldquo;{shown}&rdquo;
          </span>
          {isGameEnd && (
            <button
              type="button"
              onClick={() => setShown(null)}
              className="text-pyro-text-dim hover:text-pyro-text text-xs leading-none shrink-0"
              aria-label="Dismiss"
            >
              ×
            </button>
          )}
        </div>
      )}
    </div>
  )
}
