import type { GameState, GameStatus } from '../types/game'

interface Props {
  game: GameState
}

const STATUS_LABEL: Record<GameStatus, string> = {
  ongoing: '',
  checkmate: 'Checkmate',
  stalemate: 'Stalemate',
  draw: 'Draw',
  resigned: 'Resigned',
  timeout: 'Timeout',
}

export default function GameInfo({ game }: Props) {
  const { turn, status, history } = game
  const isOngoing = status === 'ongoing'

  return (
    <div className="bg-gray-800 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span
          className={`w-4 h-4 rounded-full border-2 border-gray-400 ${
            turn === 'w' ? 'bg-white' : 'bg-gray-900'
          }`}
        />
        <span className="text-sm font-medium">
          {isOngoing
            ? turn === 'w'
              ? 'White to move'
              : 'Black to move'
            : STATUS_LABEL[status]}
        </span>
      </div>

      <div className="text-xs font-mono overflow-y-auto max-h-48">
        {history.length === 0 ? (
          <span className="italic text-gray-500">No moves yet</span>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {Array.from({ length: Math.ceil(history.length / 2) }, (_, i) => (
                <tr key={i} className="hover:bg-gray-700/40">
                  <td className="text-gray-500 pr-2 w-6 select-none">{i + 1}.</td>
                  <td className="text-gray-200 pr-3 w-20">{history[i * 2]}</td>
                  <td className="text-gray-400 w-20">{history[i * 2 + 1] ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
