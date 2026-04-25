import { useEffect, useRef } from 'react'
import type { AnalyzedMove } from '../../hooks/useAnalyzer'
import { useAnalyzer } from '../../hooks/useAnalyzer'
import AccuracySummary from './AccuracySummary'
import AnalysisBoard from './AnalysisBoard'
import GameList from './GameList'
import MoveClassification from './MoveClassification'

const BOARD_SIZE = 480

const SYMBOL_COLORS: Record<string, string> = {
  '!!': 'text-cyan-400',
  '!':  'text-green-400',
  '?!': 'text-yellow-400',
  '?':  'text-orange-400',
  '??': 'text-red-400',
  'missed #': 'text-red-400',
  '\u{1F4D6}': 'text-indigo-400',  // 📖
}

function MoveSymbol({ symbol }: { symbol: string }) {
  if (!symbol) return null
  return <span className={`text-xs font-bold shrink-0 ${SYMBOL_COLORS[symbol] ?? 'text-pyro-text-dim'}`}>{symbol}</span>
}

export default function AnalyzerPanel() {
  const {
    state, username, setUsername, games, moves, summary, progress, error,
    currentMoveIdx, setCurrentMoveIdx, selectedGame,
    fetchGames, analyzeGame, backToGames, reset,
  } = useAnalyzer()

  const moveListRef = useRef<HTMLDivElement>(null)
  const currentRowRef = useRef<HTMLDivElement>(null)

  // Keyboard navigation
  useEffect(() => {
    if (state !== 'results') return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowLeft')  setCurrentMoveIdx(i => Math.max(-1, i - 1))
      if (e.key === 'ArrowRight') setCurrentMoveIdx(i => Math.min(moves.length - 1, i + 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [state, moves.length, setCurrentMoveIdx])

  // Auto-scroll current move into view
  useEffect(() => {
    currentRowRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [currentMoveIdx])

  const currentMove: AnalyzedMove | null = currentMoveIdx >= 0 ? (moves[currentMoveIdx] ?? null) : null
  const startFen = moves.length > 0 ? moves[0].fen_before : 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  const playerColor = summary?.player_color ?? 'w'

  // ── IDLE ───────────────────────────────────────────────────────────────────
  if (state === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-12">
        <p className="text-pyro-text-dim text-sm">Enter a chess.com username to analyse recent games</p>
        <div className="flex gap-2">
          <input
            className="rounded-lg bg-pyro-surface border border-pyro-border-accent px-3 py-2 text-sm text-pyro-text
                       placeholder:text-pyro-text-faint focus:outline-none focus:border-ember-500 w-52"
            placeholder="chess.com username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && username.trim() && fetchGames(username.trim())}
          />
          <button
            onClick={() => username.trim() && fetchGames(username.trim())}
            disabled={!username.trim()}
            className="px-4 py-2 rounded-lg bg-ember-600 hover:bg-ember-500 disabled:opacity-40
                       disabled:cursor-not-allowed text-sm font-semibold text-pyro-cream transition-colors"
          >
            Fetch games
          </button>
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
      </div>
    )
  }

  // ── LOADING GAMES ──────────────────────────────────────────────────────────
  if (state === 'loading_games') {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16">
        <div className="w-6 h-6 border-2 border-ember-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-pyro-text-dim text-sm">Fetching games for <span className="text-pyro-cream">{username}</span>…</p>
      </div>
    )
  }

  // ── GAME LIST ──────────────────────────────────────────────────────────────
  if (state === 'game_list') {
    return (
      <div className="max-w-lg mx-auto py-4 px-2">
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        <GameList
          games={games}
          username={username}
          onSelect={analyzeGame}
          onBack={reset}
        />
      </div>
    )
  }

  // ── ANALYZING ─────────────────────────────────────────────────────────────
  if (state === 'analyzing') {
    const [done, total] = progress
    const pct = total > 0 ? Math.round((done / total) * 100) : 0
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-16">
        <p className="text-pyro-text text-sm font-semibold">
          Analysing game… {done}/{total} moves
        </p>
        <div className="w-64 h-2 bg-pyro-surface rounded-full overflow-hidden">
          <div
            className="h-full bg-ember-500 transition-all duration-300 rounded-full"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-pyro-text-faint text-xs">Using Stockfish at depth 15</p>
      </div>
    )
  }

  // ── RESULTS ───────────────────────────────────────────────────────────────
  const rowCount = Math.ceil(moves.length / 2)

  return (
    <div className="flex gap-4 items-start">
      {/* Left: board + classification */}
      <div className="flex flex-col gap-2 shrink-0">
        <AnalysisBoard
          currentMove={currentMove}
          startFen={startFen}
          boardSize={BOARD_SIZE}
          playerColor={playerColor}
        />

        {/* Nav buttons */}
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={backToGames}
            className="text-xs text-pyro-text-dim hover:text-pyro-text transition-colors"
          >
            ← back to games
          </button>
          <div className="flex gap-1">
            <NavBtn onClick={() => setCurrentMoveIdx(-1)} label="⏮" title="Start" />
            <NavBtn onClick={() => setCurrentMoveIdx(i => Math.max(-1, i - 1))} label="◀" title="Previous (←)" />
            <NavBtn onClick={() => setCurrentMoveIdx(i => Math.min(moves.length - 1, i + 1))} label="▶" title="Next (→)" />
            <NavBtn onClick={() => setCurrentMoveIdx(moves.length - 1)} label="⏭" title="End" />
          </div>
        </div>

        {/* Classification for current move */}
        <div style={{ width: BOARD_SIZE }}>
          <MoveClassification move={currentMove} />
        </div>
      </div>

      {/* Right: accuracy + move list */}
      <div className="flex flex-col gap-3 min-w-0 flex-1" style={{ maxWidth: 300 }}>
        {summary && (
          <div className="rounded-xl border border-pyro-border-accent bg-pyro-surface/40 p-3">
            <div className="text-xs text-pyro-text-muted uppercase tracking-[0.18em] font-semibold mb-2">
              {selectedGame
                ? `${selectedGame.white} vs ${selectedGame.black}`
                : 'Game Summary'}
            </div>
            <AccuracySummary summary={summary} totalMoves={moves.length} />
          </div>
        )}

        {/* Move list */}
        <div className="rounded-xl border border-pyro-border-accent overflow-hidden">
          <div className="px-3 py-2 text-xs font-semibold text-pyro-text-muted uppercase tracking-[0.18em] border-b border-pyro-border-accent">
            Moves
          </div>
          <div ref={moveListRef} className="overflow-y-auto" style={{ maxHeight: 340 }}>
            {Array.from({ length: rowCount }, (_, i) => {
              const wi = i * 2
              const bi = i * 2 + 1
              const wm = moves[wi]
              const bm = moves[bi]
              const isEven = i % 2 === 0

              return (
                <div
                  key={i}
                  className={`flex items-center gap-1 px-2 py-0.5 ${isEven ? 'bg-pyro-surface/30' : 'bg-transparent'}`}
                  ref={
                    wi === currentMoveIdx || bi === currentMoveIdx ? currentRowRef : undefined
                  }
                >
                  <span className="w-6 text-right text-xs text-pyro-text-faint font-mono select-none shrink-0">
                    {i + 1}.
                  </span>
                  <MoveCell move={wm} idx={wi} currentIdx={currentMoveIdx} onClick={setCurrentMoveIdx} />
                  {bm && (
                    <MoveCell move={bm} idx={bi} currentIdx={currentMoveIdx} onClick={setCurrentMoveIdx} />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

function NavBtn({ onClick, label, title }: { onClick: () => void; label: string; title: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="w-7 h-7 flex items-center justify-center rounded bg-pyro-surface hover:bg-pyro-border
                 text-pyro-text-dim hover:text-pyro-text text-xs transition-colors border border-pyro-border-accent"
    >
      {label}
    </button>
  )
}

function MoveCell({
  move,
  idx,
  currentIdx,
  onClick,
}: {
  move: AnalyzedMove | undefined
  idx: number
  currentIdx: number
  onClick: (i: number) => void
}) {
  if (!move) return <span className="w-[110px] shrink-0" />

  const isCurrent = idx === currentIdx
  const isPlayer = move.is_player

  return (
    <button
      onClick={() => onClick(idx)}
      className={[
        'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded font-mono text-xs transition-colors w-[110px] shrink-0',
        isCurrent
          ? 'bg-ember-500/15 text-ember-400'
          : isPlayer
          ? 'text-pyro-text hover:bg-pyro-surface'
          : 'text-pyro-text-dim hover:bg-pyro-border hover:text-pyro-text',
      ].join(' ')}
    >
      <span className="truncate">{move.san}</span>
      <MoveSymbol symbol={move.symbol} />
      {move.cp_loss > 30 && !isCurrent && (
        <span className="ml-auto text-pyro-text-faint text-xs font-normal tabular-nums">
          -{move.cp_loss}
        </span>
      )}
    </button>
  )
}
