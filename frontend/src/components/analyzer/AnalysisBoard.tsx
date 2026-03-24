import { useMemo } from 'react'
import { Chessboard } from 'react-chessboard'
import type { AnalyzedMove } from '../../hooks/useAnalyzer'

const LIGHT = '#EEDAB4'
const DARK = '#B58863'
const NOTATION_STYLE = { fontSize: '11px', fontWeight: '600', color: 'rgba(0,0,0,0.45)' }
const DARK_SQ = { backgroundColor: DARK }
const LIGHT_SQ = { backgroundColor: LIGHT }

const CLASSIFICATION_COLORS: Record<string, string> = {
  brilliant:  'rgba(34, 211, 238, 0.55)',
  best:       'rgba(74, 222, 128, 0.55)',
  good:       'rgba(134, 239, 172, 0.40)',
  book:       'rgba(129, 140, 248, 0.55)',
  inaccuracy: 'rgba(250, 204, 21,  0.55)',
  mistake:    'rgba(251, 146, 60,  0.55)',
  blunder:    'rgba(248, 113, 113, 0.60)',
  miss:       'rgba(248, 113, 113, 0.60)',
}

interface Props {
  currentMove: AnalyzedMove | null
  startFen: string
  boardSize: number
  playerColor: 'w' | 'b'
}

export default function AnalysisBoard({ currentMove, startFen, boardSize, playerColor }: Props) {
  const fen = currentMove ? currentMove.fen_after : startFen

  const squareStyles = useMemo(() => {
    const styles: Record<string, { backgroundColor: string }> = {}
    if (!currentMove) return styles

    const uci = currentMove.uci
    if (uci.length < 4) return styles

    const from = uci.slice(0, 2)
    const to = uci.slice(2, 4)

    styles[from] = { backgroundColor: 'rgba(246, 246, 105, 0.45)' }
    const classColor = CLASSIFICATION_COLORS[currentMove.classification]
    styles[to] = { backgroundColor: classColor ?? 'rgba(246, 246, 105, 0.55)' }

    return styles
  }, [currentMove])

  return (
    <div style={{ width: boardSize, height: boardSize }} className="rounded-sm overflow-hidden">
      <Chessboard
        position={fen}
        boardOrientation={playerColor === 'b' ? 'black' : 'white'}
        arePiecesDraggable={false}
        customDarkSquareStyle={DARK_SQ}
        customLightSquareStyle={LIGHT_SQ}
        customSquareStyles={squareStyles}
        animationDuration={100}
        showBoardNotation
        customNotationStyle={NOTATION_STYLE}
        boardWidth={boardSize}
      />
    </div>
  )
}
