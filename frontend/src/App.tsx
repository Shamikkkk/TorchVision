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
import PyroSpeech from './components/PyroSpeech'
import AnalyzerPanel from './components/analyzer/AnalyzerPanel'
import { useGameSocket } from './hooks/useGameSocket'
import { playGameEnd } from './lib/sounds'
import type { Difficulty } from './types/game'

type Tab = 'play' | 'analyze'

// Board column width: capped by viewport height minus the vertical chrome
// (header + player bars + speech row + opening row + paddings ≈ 300px) so the
// board never forces vertical scroll on desktop; flex shrinks it to fit the
// row when width is the tighter constraint.
const BOARD_MAX_W = 'min-[900px]:max-w-[max(360px,calc(100dvh-300px))]'

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
  voiceEnabled,
  onToggleVoice,
  clockMs,
  clockActive,
  showClock,
}: {
  captured: import('./types/game').CapturedPieces
  materialAdv: { white: number; black: number }
  side: 'white' | 'black'
  isEngine: boolean
  voiceEnabled?: boolean
  onToggleVoice?: () => void
  clockMs: number
  clockActive: boolean
  showClock: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-3 h-10">
      <div className="flex items-center gap-2.5 min-w-0">
        {isEngine ? (
          <>
            <span className="text-xl animate-pyro-flicker">🔥</span>
            <span className="font-display text-base text-ember-500 italic font-semibold">
              Pyro
            </span>
            <span className="text-pyro-text-faint text-sm italic hidden sm:inline font-display truncate">
              burns brightest when you're losing
            </span>
            {onToggleVoice && (
              <button
                type="button"
                onClick={onToggleVoice}
                title={voiceEnabled ? 'Mute Pyro' : 'Unmute Pyro'}
                className={`text-sm leading-none transition-opacity ${
                  voiceEnabled ? 'opacity-90 hover:opacity-100' : 'opacity-40 hover:opacity-70 grayscale'
                }`}
              >
                {voiceEnabled ? '🔥' : '🧯'}
              </button>
            )}
          </>
        ) : (
          <>
            <span className="w-3 h-3 rounded-full bg-pyro-cream border border-pyro-border shrink-0" />
            <span className="text-[15px] font-medium text-pyro-text">You</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <CapturedPiecesRow captured={captured} materialAdv={materialAdv} side={side} />
        {showClock && <Clock ms={clockMs} active={clockActive} />}
      </div>
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
    voiceEvent,
    heat,
    voiceEnabled,
    toggleVoice,
    coachEnabled,
    toggleCoach,
    newGame,
    resign,
    flipBoard,
  } = game

  // G15 — heat glow warms in slowly, downgrades instantly.
  const effectiveHeat = voiceEnabled ? heat : 0
  const prevHeatRef = useRef(0)
  const heatDropping = effectiveHeat < prevHeatRef.current
  useEffect(() => {
    prevHeatRef.current = effectiveHeat
  }, [effectiveHeat])

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
      <div className="flex-1 flex flex-col items-center px-4 py-4 gap-4 min-h-0">
        {/* ── PLAY TAB ─────────────────────────────────────────────────── */}
        {activeTab === 'play' && (
          <>
            {/* Row at ≥900px (eval bar + board | panel), stacked below. */}
            <div className="w-full flex-1 min-h-0 flex flex-col items-center min-[900px]:flex-row min-[900px]:items-stretch min-[900px]:justify-center gap-4 min-[900px]:gap-5">
              {/* Eval bar + board — always side by side so the bar tracks board height */}
              <div className="w-full min-[900px]:w-auto min-[900px]:flex-1 min-w-0 flex justify-center gap-3">
                {/* Eval bar — live analysis, only with Coach on */}
                {coachEnabled && (
                  <div className="flex self-stretch">
                    <EvalBar score={evalScore} boardFlipped={boardFlipped} />
                  </div>
                )}

                {/* Board column — fills width up to the viewport-height cap */}
                <div className={`w-full min-w-0 flex flex-col gap-2 max-w-[560px] ${BOARD_MAX_W}`}>
                  <PlayerRow
                    captured={capturedPieces}
                    materialAdv={materialAdv}
                    side={topCaptures}
                    isEngine={topColor === engineColor}
                    voiceEnabled={voiceEnabled}
                    onToggleVoice={topColor === engineColor ? toggleVoice : undefined}
                    clockMs={topMs}
                    clockActive={turn !== bottomSide}
                    showClock={clockStarted}
                  />
                  {topColor === engineColor && (
                    <PyroSpeech text={pyroSays} event={voiceEvent} enabled={voiceEnabled} />
                  )}

                  <div
                    style={{
                      ['--heat-transition' as string]: heatDropping ? '150ms' : '1400ms',
                    } as React.CSSProperties}
                    className={`w-full aspect-square rounded-sm overflow-hidden board-heat board-heat-${effectiveHeat}`}
                  >
                    <Board game={game} />
                  </div>

                  <PlayerRow
                    captured={capturedPieces}
                    materialAdv={materialAdv}
                    side={bottomCaptures}
                    isEngine={bottomColor === engineColor}
                    voiceEnabled={voiceEnabled}
                    onToggleVoice={bottomColor === engineColor ? toggleVoice : undefined}
                    clockMs={bottomMs}
                    clockActive={turn === bottomSide}
                    showClock={clockStarted}
                  />
                  {bottomColor === engineColor && (
                    <PyroSpeech text={pyroSays} event={voiceEvent} enabled={voiceEnabled} />
                  )}

                  <div className="h-7 flex items-center justify-center">
                    {openingName && (
                      <span className="text-sm text-pyro-text-dim italic font-display text-center">
                        {openingName}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Right panel — fixed-width column, full height beside the board */}
              <div className="w-full max-w-[560px] min-[900px]:w-[320px] min-[900px]:max-w-none shrink-0 flex flex-col gap-3 rounded-xl border border-pyro-border-accent bg-pyro-surface/40 p-4 min-h-0">
                <MoveList history={history} moveSymbols={moveSymbols} />
                {/* Live suggestion / best-move panel — only with Coach on */}
                {coachEnabled && (
                  <EnginePanel evalMove={evalMove} evalScore={evalScore} bestWas={bestWas} />
                )}
                <Controls
                  difficulty={difficulty}
                  onDifficultyChange={setDifficulty}
                  onNewGame={() => newGame(difficulty)}
                  onResign={resign}
                  onFlip={flipBoard}
                  gameInProgress={status === 'ongoing' && history.length > 0}
                  coachEnabled={coachEnabled}
                  onToggleCoach={toggleCoach}
                />
              </div>
            </div>

            {Math.abs(evalScore ?? 0) > 9000 && (
              <div
                className="pointer-events-none fixed inset-0 z-10"
                style={{
                  background: 'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.5) 100%)',
                }}
              />
            )}

            <GameOverModal
              status={status}
              winner={winner}
              turn={turn}
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
