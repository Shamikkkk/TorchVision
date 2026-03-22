export type GameStatus = 'ongoing' | 'checkmate' | 'stalemate' | 'draw' | 'resigned' | 'timeout'

export type Side = 'w' | 'b'

export interface StateMessage {
  type: 'state'
  fen: string
  turn: Side
  status: GameStatus
  last_move: string | null
  history: string[]
  white_ms: number
  black_ms: number
  winner?: Side
}

export interface TickMessage {
  type: 'tick'
  white_ms: number
  black_ms: number
}

export interface ErrorMessage {
  type: 'error'
  message: string
}

export type ServerMessage = StateMessage | TickMessage | ErrorMessage

export interface MovePayload {
  type: 'move'
  uci: string
}

export interface NewGamePayload {
  type: 'new_game'
}

export interface ResignPayload {
  type: 'resign'
}

export type ClientPayload = MovePayload | NewGamePayload | ResignPayload

export interface SuggestResponse {
  move: string
  eval: number | null
}

export interface CapturedPieces {
  byWhite: string[]
  byBlack: string[]
}

export interface GameState {
  fen: string
  turn: Side
  status: GameStatus
  history: string[]
  lastMove: string | null
  boardFlipped: boolean
  white_ms: number
  black_ms: number
  winner: Side | null
  capturedPieces: CapturedPieces
  evalScore: number | null
  evalMove: string | null
  makeMove: (uci: string) => void
  newGame: () => void
  resign: () => void
  flipBoard: () => void
}
