import { useCallback, useEffect, useRef, useState } from 'react'
import { Chess } from 'chess.js'
import type { Square } from 'chess.js'
import { WsClient } from '../lib/wsClient'
import type {
  CapturedPieces,
  GameState,
  GameStatus,
  ServerMessage,
  Side,
} from '../types/game'

const UCI_RE = /^[a-h][1-8][a-h][1-8][qrbn]?$/

function ensureSanHistory(moves: string[]): string[] {
  if (moves.length === 0) return moves
  if (!UCI_RE.test(moves[0])) return moves
  const chess = new Chess()
  const san: string[] = []
  for (const uci of moves) {
    try {
      const from = uci.slice(0, 2) as Square
      const to = uci.slice(2, 4) as Square
      const promotion = uci[4] as 'q' | 'r' | 'b' | 'n' | undefined
      const result = chess.move({ from, to, ...(promotion ? { promotion } : {}) })
      san.push(result.san)
    } catch {
      break
    }
  }
  return san
}

const PIECE_SYMBOLS: Record<string, string> = { p: '♟', n: '♞', b: '♝', r: '♜', q: '♛' }
const WHITE_SYMBOLS: Record<string, string> = { p: '♙', n: '♘', b: '♗', r: '♖', q: '♕' }
const PIECE_VALS: Record<string, number> = {
  '♟': 1, '♞': 3, '♝': 3, '♜': 5, '♛': 9,
  '♙': 1, '♘': 3, '♗': 3, '♖': 5, '♕': 9,
}
const START_COUNT: Record<string, number> = { p: 8, n: 2, b: 2, r: 2, q: 1 }

function computeCaptured(fen: string): CapturedPieces {
  const whiteCount: Record<string, number> = { p: 0, n: 0, b: 0, r: 0, q: 0 }
  const blackCount: Record<string, number> = { p: 0, n: 0, b: 0, r: 0, q: 0 }
  for (const ch of fen.split(' ')[0]) {
    const lower = ch.toLowerCase()
    if (lower in START_COUNT) {
      if (ch === lower) blackCount[lower]++
      else whiteCount[lower]++
    }
  }
  const byWhite: string[] = []
  const byBlack: string[] = []
  for (const [piece, start] of Object.entries(START_COUNT)) {
    for (let i = 0; i < start - blackCount[piece]; i++) byWhite.push(PIECE_SYMBOLS[piece])
    for (let i = 0; i < start - whiteCount[piece]; i++) byBlack.push(WHITE_SYMBOLS[piece])
  }
  return { byWhite, byBlack }
}

export function materialAdvantage(cap: CapturedPieces): { white: number; black: number } {
  const w = cap.byWhite.reduce((s, p) => s + (PIECE_VALS[p] ?? 0), 0)
  const b = cap.byBlack.reduce((s, p) => s + (PIECE_VALS[p] ?? 0), 0)
  return { white: w > b ? w - b : 0, black: b > w ? b - w : 0 }
}

export function uciToSan(fen: string, uci: string): string {
  try {
    const chess = new Chess(fen)
    const from = uci.slice(0, 2) as Square
    const to = uci.slice(2, 4) as Square
    const promotion = uci[4] as 'q' | 'r' | 'b' | 'n' | undefined
    const result = chess.move({ from, to, ...(promotion ? { promotion } : {}) })
    return result?.san ?? uci
  } catch {
    return uci
  }
}

const WS_URL = `${import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'}/ws/game`
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const STARTING_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const CLOCK_MS = 300_000

export interface ExtendedGameState extends GameState {
  materialAdv: { white: number; black: number }
}

export function useGameSocket(): ExtendedGameState {
  const chessRef = useRef(new Chess())
  const wsRef = useRef<WsClient | null>(null)

  const [fen, setFen] = useState(STARTING_FEN)
  const [turn, setTurn] = useState<Side>('w')
  const [status, setStatus] = useState<GameStatus>('ongoing')
  const [history, setHistory] = useState<string[]>([])
  const [lastMove, setLastMove] = useState<string | null>(null)
  const [boardFlipped, setBoardFlipped] = useState(false)
  const [white_ms, setWhiteMs] = useState(CLOCK_MS)
  const [black_ms, setBlackMs] = useState(CLOCK_MS)
  const [winner, setWinner] = useState<Side | null>(null)
  const [capturedPieces, setCapturedPieces] = useState<CapturedPieces>({ byWhite: [], byBlack: [] })
  const [evalScore, setEvalScore] = useState<number | null>(null)
  const [evalMove, setEvalMove] = useState<string | null>(null)

  const evalAbortRef = useRef<AbortController | null>(null)

  const fetchEval = useCallback(async (currentFen: string) => {
    evalAbortRef.current?.abort()
    const ctrl = new AbortController()
    evalAbortRef.current = ctrl
    try {
      const res = await fetch(`${API_URL}/api/suggest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fen: currentFen }),
        signal: ctrl.signal,
      })
      if (!res.ok) return
      const data = (await res.json()) as { move: string; eval: number | null }
      setEvalScore(data.eval)
      setEvalMove(uciToSan(currentFen, data.move))
    } catch {
      // aborted or network error
    }
  }, [])

  const handleMessage = useCallback(
    (msg: ServerMessage) => {
      if (msg.type === 'tick') {
        setWhiteMs(msg.white_ms)
        setBlackMs(msg.black_ms)
        return
      }
      if (msg.type === 'state') {
        chessRef.current.load(msg.fen)
        setFen(msg.fen)
        setTurn(msg.turn)
        setStatus(msg.status)
        setHistory(ensureSanHistory(msg.history))
        setLastMove(msg.last_move)
        setWhiteMs(msg.white_ms)
        setBlackMs(msg.black_ms)
        setWinner(msg.winner ?? null)
        setCapturedPieces(computeCaptured(msg.fen))
        if (msg.status === 'ongoing') fetchEval(msg.fen)
      }
    },
    [fetchEval],
  )

  useEffect(() => {
    const client = new WsClient(WS_URL, handleMessage)
    wsRef.current = client
    client.connect()
    return () => client.destroy()
  }, [handleMessage])

  const makeMove = useCallback((uci: string) => {
    wsRef.current?.send({ type: 'move', uci })
  }, [])

  const newGame = useCallback(() => {
    setEvalScore(null)
    setEvalMove(null)
    wsRef.current?.send({ type: 'new_game' })
  }, [])

  const resign = useCallback(() => {
    wsRef.current?.send({ type: 'resign' })
  }, [])

  const flipBoard = useCallback(() => setBoardFlipped((f) => !f), [])

  return {
    fen,
    turn,
    status,
    history,
    lastMove,
    boardFlipped,
    white_ms,
    black_ms,
    winner,
    capturedPieces,
    evalScore,
    evalMove,
    makeMove,
    newGame,
    resign,
    flipBoard,
    materialAdv: materialAdvantage(capturedPieces),
  }
}
