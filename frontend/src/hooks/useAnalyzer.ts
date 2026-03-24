import { useCallback, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type AnalyzerState = 'idle' | 'loading_games' | 'game_list' | 'analyzing' | 'results'

export interface ChessComGame {
  id: string
  white: string
  black: string
  result: '1-0' | '0-1' | '1/2-1/2'
  date: string
  pgn: string
  time_control: string
}

export interface AnalyzedMove {
  move_number: number
  color: 'w' | 'b'
  san: string
  uci: string
  classification: string
  symbol: string
  best_move: string
  cp_loss: number
  eval_before: number | null
  eval_after: number | null
  fen_before: string
  fen_after: string
  is_player: boolean
  is_best: boolean
}

export interface GameSummary {
  player_color: 'w' | 'b'
  book: number
  brilliant: number
  best: number
  good: number
  inaccuracy: number
  mistake: number
  blunder: number
  miss: number
  accuracy: number
}

export function useAnalyzer() {
  const [state, setState] = useState<AnalyzerState>('idle')
  const [username, setUsername] = useState('')
  const [games, setGames] = useState<ChessComGame[]>([])
  const [moves, setMoves] = useState<AnalyzedMove[]>([])
  const [summary, setSummary] = useState<GameSummary | null>(null)
  const [progress, setProgress] = useState<[number, number]>([0, 0])
  const [error, setError] = useState<string | null>(null)
  const [currentMoveIdx, setCurrentMoveIdx] = useState(-1)
  const [selectedGame, setSelectedGame] = useState<ChessComGame | null>(null)

  const fetchGames = useCallback(async (uname: string) => {
    setState('loading_games')
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/analyze/games/${encodeURIComponent(uname)}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail ?? `Error ${res.status}`)
        setState('idle')
        return
      }
      const data = (await res.json()) as ChessComGame[]
      setGames(data)
      setState(data.length === 0 ? 'idle' : 'game_list')
      if (data.length === 0) setError('No games found for this username')
    } catch (e) {
      setError(String(e))
      setState('idle')
    }
  }, [])

  const analyzeGame = useCallback(async (game: ChessComGame) => {
    setSelectedGame(game)
    setState('analyzing')
    setMoves([])
    setSummary(null)
    setProgress([0, 0])
    setCurrentMoveIdx(-1)
    setError(null)

    try {
      const res = await fetch(`${API_URL}/api/analyze/game/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pgn: game.pgn, username }),
      })

      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail ?? 'Analysis failed')
        setState('game_list')
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const collectedMoves: AnalyzedMove[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE events are separated by \n\n
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'move') {
              collectedMoves.push(event.data)
              setMoves([...collectedMoves])
              setProgress(event.progress as [number, number])
            } else if (event.type === 'summary') {
              setSummary(event.data as GameSummary)
            } else if (event.type === 'done') {
              setState('results')
              setCurrentMoveIdx(collectedMoves.length > 0 ? 0 : -1)
            } else if (event.type === 'error') {
              setError(event.message)
              setState('game_list')
              return
            }
          } catch {
            // skip malformed line
          }
        }
      }

      // Fallback if 'done' event wasn't received
      if (collectedMoves.length > 0) {
        setState('results')
        setCurrentMoveIdx(0)
      }
    } catch (e) {
      setError(String(e))
      setState('game_list')
    }
  }, [username])

  const backToGames = useCallback(() => {
    setState('game_list')
    setMoves([])
    setSummary(null)
    setError(null)
  }, [])

  const reset = useCallback(() => {
    setState('idle')
    setGames([])
    setMoves([])
    setSummary(null)
    setError(null)
    setCurrentMoveIdx(-1)
  }, [])

  return {
    state,
    username,
    setUsername,
    games,
    moves,
    summary,
    progress,
    error,
    currentMoveIdx,
    setCurrentMoveIdx,
    selectedGame,
    fetchGames,
    analyzeGame,
    backToGames,
    reset,
  }
}
