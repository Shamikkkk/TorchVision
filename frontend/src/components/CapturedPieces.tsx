import type { CapturedPieces } from '../types/game'

interface Props {
  captured: CapturedPieces
  materialAdv: { white: number; black: number }
  /** Which side's captures to show (the side that made the captures) */
  side: 'white' | 'black'
}

export default function CapturedPiecesRow({ captured, materialAdv, side }: Props) {
  const pieces = side === 'white' ? captured.byWhite : captured.byBlack
  const adv = side === 'white' ? materialAdv.white : materialAdv.black

  if (pieces.length === 0 && adv === 0) {
    return <div className="h-6" />
  }

  return (
    <div className="flex items-center gap-0.5 h-6">
      <span className="text-lg leading-none tracking-tight">{pieces.join('')}</span>
      {adv > 0 && (
        <span className="text-sm text-zinc-400 ml-1 font-mono">+{adv}</span>
      )}
    </div>
  )
}
