import { useEffect, useRef, useState } from 'react'
import { detectOpening } from './lib/openings'
import Board from './components/Board'
import Clock from './components/Clock'
import { Controls } from './components/Controls'
import CapturedPiecesRow from './components/CapturedPieces'
import EvalBar from './components/EvalBar'
import EnginePanel from './components/EnginePanel'
import GameOverModal from './components/GameOverModal'
import MoveList from './components/MoveList'
import AnalyzerPanel from './components/analyzer/AnalyzerPanel'
import { useGameSocket } from './hooks/useGameSocket'
import { playGameEnd } from './lib/sounds'

const BOARD_SIZE = 520

type Tab = 'play' | 'analyze'

function PlayerRow({
  color,
  captured,
  materialAdv,
  side,
}: {
  color: 'white' | 'black'
  captured: import('./types/game').CapturedPieces
  materialAdv: { white: number; black: number }
  side: 'white' | 'black'
}) {
  return (
    <div className="flex items-center justify-between h-7">
      <div className="flex items-center gap-2">
        <span
          className={[
            'w-3.5 h-3.5 rounded-full border shrink-0',
            color === 'white'
              ? 'bg-zinc-100 border-zinc-400'
              : 'bg-zinc-900 border-zinc-500',
          ].join(' ')}
        />
        <span className="text-sm font-semibold text-white">
          {color === 'white' ? 'White' : 'Black'}
        </span>
      </div>
      <CapturedPiecesRow captured={captured} materialAdv={materialAdv} side={side} />
    </div>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('play')
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
    newGame,
    resign,
    flipBoard,
  } = game

  const prevStatus = useRef(status)
  useEffect(() => {
    if (prevStatus.current === 'ongoing' && status !== 'ongoing') playGameEnd()
    prevStatus.current = status
  }, [status])

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

  return (
    <div className="min-h-screen bg-zinc-900 text-white flex flex-col items-center p-6 gap-4">
      {/* Header: title + tab switcher */}
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center gap-3">
          <p className="text-zinc-500 text-xs font-semibold uppercase tracking-widest select-none">
            ♟ Pyro Chess
          </p>
          {activeTab === 'play' && (
            <span className="text-zinc-600 text-xs select-none">
              Playing as {humanColor === 'w' ? 'White' : 'Black'}
            </span>
          )}
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 rounded-lg bg-zinc-800 p-0.5">
          {(['play', 'analyze'] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={[
                'px-4 py-1.5 rounded-md text-sm font-medium transition-colors',
                activeTab === tab
                  ? 'bg-zinc-700 text-white'
                  : 'text-zinc-500 hover:text-zinc-300',
              ].join(' ')}
            >
              {tab === 'play' ? '♟ Play' : '🔍 Analyze'}
            </button>
          ))}
        </div>
      </div>

      {/* ── PLAY TAB ─────────────────────────────────────────────────────── */}
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
                color={topColor}
                captured={capturedPieces}
                materialAdv={materialAdv}
                side={topCaptures}
              />

              {clockStarted && (
                <Clock
                  ms={topMs}
                  active={turn !== bottomSide}
                  label={topColor === 'black' ? 'Black' : 'White'}
                />
              )}

              <div style={{ width: BOARD_SIZE, height: BOARD_SIZE }} className="rounded-sm overflow-hidden">
                <Board game={game} />
              </div>

              {clockStarted && (
                <Clock
                  ms={bottomMs}
                  active={turn === bottomSide}
                  label={bottomColor === 'white' ? 'White' : 'Black'}
                />
              )}

              <PlayerRow
                color={bottomColor}
                captured={capturedPieces}
                materialAdv={materialAdv}
                side={bottomCaptures}
              />

              <div className="h-7 flex items-center justify-center">
                {openingName && (
                  <span className="text-zinc-300 italic text-sm">
                    {openingName}
                  </span>
                )}
              </div>
            </div>

            {/* Right panel */}
            <div
              className="flex flex-col gap-3 rounded-2xl border border-zinc-700/50 bg-zinc-900 p-4"
              style={{ width: 280 }}
            >
              <MoveList history={history} moveSymbols={moveSymbols} />
              <EnginePanel evalMove={evalMove} evalScore={evalScore} bestWas={bestWas} />
              <Controls
                onNewGame={newGame}
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
            onRematch={newGame}
            onMenu={newGame}
          />
        </>
      )}

      {/* ── ANALYZE TAB ──────────────────────────────────────────────────── */}
      {activeTab === 'analyze' && (
        <div className="w-full max-w-5xl">
          <AnalyzerPanel />
        </div>
      )}
    </div>
  )
}
