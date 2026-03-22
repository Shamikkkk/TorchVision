import { useState } from 'react'
import { Chessboard } from 'react-chessboard'
import type { Square } from 'chess.js'
import { Chess } from 'chess.js'
import type { GameState } from '../types/game'
import { playMove, playCapture, playCheck } from '../lib/sounds'

interface Props {
  game: GameState
}

const LIGHT = '#EEDAB4'
const DARK = '#B58863'
const LAST_MOVE_COLOR = 'rgba(246,246,105,0.5)'
const SELECTED_COLOR = 'rgba(32,178,170,0.5)'

export default function Board({ game }: Props) {
  const { fen, boardFlipped, makeMove, status, lastMove } = game
  const gameOver = status !== 'ongoing'

  const [selectedSq, setSelectedSq] = useState<Square | null>(null)

  const lastMoveSqs: Record<string, { backgroundColor: string }> = {}
  if (lastMove && lastMove.length >= 4) {
    lastMoveSqs[lastMove.slice(0, 2)] = { backgroundColor: LAST_MOVE_COLOR }
    lastMoveSqs[lastMove.slice(2, 4)] = { backgroundColor: LAST_MOVE_COLOR }
  }

  const selectedHighlight: Record<string, { backgroundColor: string }> = {}
  if (selectedSq) {
    selectedHighlight[selectedSq] = { backgroundColor: SELECTED_COLOR }
  }

  const legalTargets: Square[] = selectedSq
    ? (() => {
        try {
          const chess = new Chess(fen)
          return chess.moves({ square: selectedSq, verbose: true }).map((m) => m.to as Square)
        } catch {
          return []
        }
      })()
    : []

  const legalDots: Record<string, { background: string; borderRadius: string }> = {}
  for (const sq of legalTargets) {
    legalDots[sq] = {
      background: 'radial-gradient(circle, rgba(0,0,0,0.18) 29%, transparent 30%)',
      borderRadius: '0',
    }
  }

  function sendMove(from: Square, to: Square, promotion?: string) {
    const chess = new Chess(fen)
    const move = chess.move({ from, to, promotion: (promotion ?? 'q') as 'q' | 'r' | 'b' | 'n' })
    if (move) {
      if (move.captured) playCapture()
      else playMove()
      if (move.san.includes('+')) playCheck()
    }
    makeMove(`${from}${to}${promotion ?? ''}`)
  }

  function onSquareClick(sq: Square) {
    if (gameOver) return
    if (selectedSq && legalTargets.includes(sq)) {
      sendMove(selectedSq, sq)
      setSelectedSq(null)
      return
    }
    const chess = new Chess(fen)
    const piece = chess.get(sq)
    if (piece && piece.color === chess.turn()) {
      setSelectedSq(sq)
    } else {
      setSelectedSq(null)
    }
  }

  function onDrop(source: Square, target: Square, piece: string): boolean {
    if (gameOver) return false
    const isPromotion =
      piece.toLowerCase().includes('p') &&
      ((piece[0] === 'w' && target[1] === '8') || (piece[0] === 'b' && target[1] === '1'))
    sendMove(source, target, isPromotion ? 'q' : undefined)
    setSelectedSq(null)
    return true
  }

  return (
    <Chessboard
      position={fen}
      onPieceDrop={onDrop}
      onSquareClick={onSquareClick}
      boardOrientation={boardFlipped ? 'black' : 'white'}
      arePiecesDraggable={!gameOver}
      customDarkSquareStyle={{ backgroundColor: DARK }}
      customLightSquareStyle={{ backgroundColor: LIGHT }}
      customSquareStyles={{ ...lastMoveSqs, ...selectedHighlight, ...legalDots }}
      animationDuration={150}
      showBoardNotation
      customNotationStyle={{
        fontSize: '11px',
        fontWeight: '600',
        color: 'rgba(0,0,0,0.45)',
      }}
    />
  )
}
