import { useEffect, useRef, useState } from 'react'
import { detectOpening } from './lib/openings'
import Board from './components/Board'
import Clock from './components/Clock'
import { Controls } from './components/Controls'
import CapturedPiecesRow from './components/CapturedPieces'
import EvalBar from './components/EvalBar'
import EnginePanel from './components/EnginePanel'
import GameOverModal from './components/GameOverModal'
import LobbyScreen from './components/LobbyScreen'
import MoveList from './components/MoveList'
import AnalyzerPanel from './components/analyzer/AnalyzerPanel'
import { useGameSocket } from './hooks/useGameSocket'
import { playGameEnd } from './lib/sounds'
import type { Difficulty } from './types/game'

const BOARD_SIZE = 520

type Tab = 'play' | 'analyze'

const STORAGE_KEY = 'pyro.difficulty'

function loadDifficulty(): Difficulty {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && ['beginner', 'intermediate', 'advanced', 'expert', 'master'].includes(stored)) {
      return stored as Difficulty
    }
  } catch {}
  return 'master'
}

function PlayerRow({
  captured,
  materialAdv,
  side,
  isEngine,
}: {
  captured: import('./types/game').CapturedPieces
  materialAdv: { white: number; black: number }
  side: 'white' | 'black'
  isEngine: boolean
}) {
  return (
    <div className="flex items-center justify-between h-8">
      <div className="flex items-center gap-2.5">
        {isEngine ? (
          <>
            <span className="text-lg animate-pyro-flicker">🔥</span>
            <span className="font-display text-sm text-ember-500 italic font-semibold">
              Pyro
            </span>
            <span className="text-pyro-text-faint text-xs italic hidden sm:inline font-display">
              burns brightest when you're losing
            </span>
          </>
        ) : (
          <>
            <span className="w-3 h-3 rounded-full bg-pyro-cream border border-pyro-border shrink-0" />
            <span className="text-sm font-medium text-pyro-text">You</span>
          </>
        )}
      </div>
      <CapturedPiecesRow captured={captured} materialAdv={materialAdv} side={side} />
    </div>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('play')
  const [showLobby, setShowLobby] = useState(true)
  const [difficulty, setDifficulty] = useState<Difficulty>(loadDifficulty)

  const game = useGameSocket()
  const {
    status,
    winner,
    history,
    turn,
    white_ms,
    black_ms,
    capturedPieces,
    evalScore,
    evalMove,
    bestWas,
    moveSymbols,
    boardFlipped,
    humanColor,
    materialAdv,
    pyroSays,
    newGame,
    resign,
    flipBoard,
  } = game

  // Persist difficulty to localStorage whenever it changes
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, difficulty) } catch {}
  }, [difficulty])

  const prevStatus = useRef(status)
  useEffect(() => {
    if (prevStatus.current === 'ongoing' && status !== 'ongoing') playGameEnd()
    prevStatus.current = status
  }, [status])

  // ── LOBBY ──────────────────────────────────────────────────────────────
  if (showLobby) {
    return (
      <LobbyScreen
        currentMood={difficulty}
        onMoodChange={setDifficulty}
        onStart={() => {
          setShowLobby(false)
          newGame(difficulty)
        }}
      />
    )
  }

  // ── PLAY / ANALYZE ─────────────────────────────────────────────────────
  const clockStarted = white_ms < 300_000 || black_ms < 300_000
  const openingName = history.length <= 30 ? detectOpening(history) : null

  const topSide = boardFlipped ? 'w' : 'b'
  const bottomSide = boardFlipped ? 'b' : 'w'
  const topMs = topSide === 'w' ? white_ms : black_ms
  const bottomMs = bottomSide === 'w' ? white_ms : black_ms
  const topColor: 'white' | 'black' = topSide === 'w' ? 'white' : 'black'
  const bottomColor: 'white' | 'black' = bottomSide === 'w' ? 'white' : 'black'
  const topCaptures: 'white' | 'black' = topSide === 'b' ? 'white' : 'black'
  const bottomCaptures: 'white' | 'black' = bottomSide === 'w' ? 'black' : 'white'
  const engineColor: 'white' | 'black' = humanColor === 'w' ? 'black' : 'white'

  return (
    <div className="min-h-screen bg-pyro-bg text-pyro-text font-sans flex flex-col">
      {/* ── Top header bar ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-8 py-3.5 border-b border-pyro-border-subtle">
        <div className="flex items-center gap-5">
          <button
            onClick={() => setShowLobby(true)}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <span className="text-xl animate-pyro-flicker">🔥</span>
            <span className="font-display text-lg text-ember-500 italic">Pyro</span>
          </button>
          <span className="text-pyro-text-faint text-xs">·</span>
          <span className="text-xs text-pyro-text-dim tracking-widest uppercase">
            You vs <span className="text-ember-500 font-semibold">Pyro</span>
          </span>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-6 text-xs tracking-widest uppercase">
          {(['play', 'analyze'] as Tab[]).map((tab) =>
            activeTab === tab ? (
              <span
                key={tab}
                className="text-pyro-text font-semibold border-b-2 border-ember-500 pb-0.5"
              >
                {tab === 'play' ? 'Play' : 'Analyze'}
              </span>
            ) : (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className="text-pyro-text-dim hover:text-pyro-text transition-colors"
              >
                {tab === 'play' ? 'Play' : 'Analyze'}
              </button>
            ),
          )}
        </div>
      </div>

      {/* ── Content ─────────────────────────────────────────────────────── */}
      <div className="flex flex-col items-center p-6 gap-4">
        {/* ── PLAY TAB ─────────────────────────────────────────────────── */}
        {activeTab === 'play' && (
          <>
            <div className="flex gap-4 items-start">
              {/* Eval bar */}
              <div className="flex" style={{ height: BOARD_SIZE + 120 }}>
                <EvalBar score={evalScore} boardFlipped={boardFlipped} />
              </div>

              {/* Board column */}
              <div className="flex flex-col gap-1.5" style={{ width: BOARD_SIZE }}>
                <PlayerRow
                  captured={capturedPieces}
                  materialAdv={materialAdv}
                  side={topCaptures}
                  isEngine={topColor === engineColor}
                />
                {topColor === engineColor && pyroSays && (
                  <div className="h-5 flex items-center -mt-0.5">
                    <span className="text-pyro-taunt text-xs italic animate-pyro-taunt-in">
                      &ldquo;{pyroSays}&rdquo;
                    </span>
                  </div>
                )}

                {clockStarted && (
                  <Clock
                    ms={topMs}
                    active={turn !== bottomSide}
                    label={topColor === engineColor ? 'Pyro' : topColor === 'white' ? 'White' : 'Black'}
                  />
                )}

                <div style={{ width: BOARD_SIZE, height: BOARD_SIZE }} className="rounded-sm overflow-hidden">
                  <Board game={game} />
                </div>

                {clockStarted && (
                  <Clock
                    ms={bottomMs}
                    active={turn === bottomSide}
                    label={bottomColor === engineColor ? 'Pyro' : bottomColor === 'white' ? 'White' : 'Black'}
                  />
                )}

                <PlayerRow
                  captured={capturedPieces}
                  materialAdv={materialAdv}
                  side={bottomCaptures}
                  isEngine={bottomColor === engineColor}
                />
                {bottomColor === engineColor && pyroSays && (
                  <div className="h-5 flex items-center -mt-0.5">
                    <span className="text-pyro-taunt text-xs italic animate-pyro-taunt-in">
                      &ldquo;{pyroSays}&rdquo;
                    </span>
                  </div>
                )}

                <div className="h-7 flex items-center justify-center">
                  {openingName && (
                    <span className="text-xs text-pyro-text-dim italic font-display text-center">
                      {openingName}
                    </span>
                  )}
                </div>
              </div>

              {/* Right panel */}
              <div
                className="flex flex-col gap-3 rounded-xl border border-pyro-border-accent bg-pyro-surface/40 p-4"
                style={{ width: 280 }}
              >
                <MoveList history={history} moveSymbols={moveSymbols} />
                <EnginePanel evalMove={evalMove} evalScore={evalScore} bestWas={bestWas} />
                <Controls
                  difficulty={difficulty}
                  onDifficultyChange={setDifficulty}
                  onNewGame={() => newGame(difficulty)}
                  onResign={resign}
                  onFlip={flipBoard}
                  gameInProgress={status === 'ongoing' && history.length > 0}
                />
              </div>
            </div>

            <GameOverModal
              status={status}
              winner={winner}
              moveCount={history.length}
              humanColor={humanColor}
              onRematch={() => newGame(difficulty)}
              onMenu={() => setShowLobby(true)}
              pyroSays={pyroSays}
            />
          </>
        )}

        {/* ── ANALYZE TAB ──────────────────────────────────────────────── */}
        {activeTab === 'analyze' && (
          <div className="w-full max-w-5xl">
            <AnalyzerPanel />
          </div>
        )}
      </div>
    </div>
  )
}
