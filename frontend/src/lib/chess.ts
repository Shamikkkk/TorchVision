import { Chess } from 'chess.js'
import type { Square } from 'chess.js'

/** Returns all squares the piece on `square` can legally move to. */
export function getLegalTargets(fen: string, square: Square): Square[] {
  const chess = new Chess(fen)
  return chess
    .moves({ square, verbose: true })
    .map((m) => m.to as Square)
}

export function isGameOver(fen: string): boolean {
  return new Chess(fen).isGameOver()
}

export function fenToTurn(fen: string): 'w' | 'b' {
  return fen.split(' ')[1] as 'w' | 'b'
}
