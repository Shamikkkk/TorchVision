import { useMemo, useState } from 'react'
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
const HIGHLIGHT_COLOR = 'rgba(255, 170, 0, 0.8)'
const ARROW_COLOR = 'rgb(255, 170, 0)'

// Module-level constants so these object references never change between renders.
const DARK_SQ_STYLE = { backgroundColor: DARK }
const LIGHT_SQ_STYLE = { backgroundColor: LIGHT }
const NOTATION_STYLE = { fontSize: '11px', fontWeight: '600', color: 'rgba(0,0,0,0.45)' }

export default function Board({ game }: Props) {
  const { fen, boardFlipped, makeMove, status, lastMove } = game
  const gameOver = status !== 'ongoing'

  const [selectedSq, setSelectedSq] = useState<Square | null>(null)
  const [highlightedSquares, setHighlightedSquares] = useState<Record<string, { backgroundColor: string }>>({})

  const lastMoveSqs = useMemo(() => {
    const sqs: Record<string, { backgroundColor: string }> = {}
    if (lastMove && lastMove.length >= 4) {
      sqs[lastMove.slice(0, 2)] = { backgroundColor: LAST_MOVE_COLOR }
      sqs[lastMove.slice(2, 4)] = { backgroundColor: LAST_MOVE_COLOR }
    }
    return sqs
  }, [lastMove])

  const selectedHighlight = useMemo(() => {
    if (!selectedSq) return {}
    return { [selectedSq]: { backgroundColor: SELECTED_COLOR } }
  }, [selectedSq])

  const legalTargets = useMemo<Square[]>(() => {
    if (!selectedSq) return []
    try {
      const chess = new Chess(fen)
      return chess.moves({ square: selectedSq, verbose: true }).map((m) => m.to as Square)
    } catch {
      return []
    }
  }, [selectedSq, fen])

  const legalDots = useMemo(() => {
    const dots: Record<string, { background: string; borderRadius: string }> = {}
    for (const sq of legalTargets) {
      dots[sq] = {
        background: 'radial-gradient(circle, rgba(0,0,0,0.18) 29%, transparent 30%)',
        borderRadius: '0',
      }
    }
    return dots
  }, [legalTargets])

  const customSquareStyles = useMemo(
    () => ({ ...lastMoveSqs, ...selectedHighlight, ...legalDots, ...highlightedSquares }),
    [lastMoveSqs, selectedHighlight, legalDots, highlightedSquares],
  )

  function clearAnnotations() {
    setHighlightedSquares({})
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
    clearAnnotations()
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

  function onSquareRightClick(sq: Square) {
    setHighlightedSquares((prev) => {
      const next = { ...prev }
      if (next[sq]) {
        delete next[sq]
      } else {
        next[sq] = { backgroundColor: HIGHLIGHT_COLOR }
      }
      return next
    })
  }

  function onDrop(source: Square, target: Square, piece: string): boolean {
    if (gameOver) return false
    clearAnnotations()
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
      onSquareRightClick={onSquareRightClick}
      boardOrientation={boardFlipped ? 'black' : 'white'}
      arePiecesDraggable={!gameOver}
      areArrowsAllowed
      customArrowColor={ARROW_COLOR}
      customDarkSquareStyle={DARK_SQ_STYLE}
      customLightSquareStyle={LIGHT_SQ_STYLE}
      customSquareStyles={customSquareStyles}
      animationDuration={150}
      showBoardNotation
      customNotationStyle={NOTATION_STYLE}
    />
  )
}
