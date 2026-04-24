/* global React, ChessPiece */

// Parse a simple FEN position string (just the piece placement field)
// Returns 8x8 array: rows top-down (rank 8 first), files a-h
function parseFen(fen) {
  const rows = fen.split(' ')[0].split('/');
  return rows.map(row => {
    const cells = [];
    for (const ch of row) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < parseInt(ch, 10); i++) cells.push(null);
      } else {
        const color = ch === ch.toUpperCase() ? 'w' : 'b';
        cells.push(color + ch.toLowerCase());
      }
    }
    return cells;
  });
}

// Obsidian Ember palette: warm dark browns, pale cream
// lastMove = { from: 'e2', to: 'e4' }, check = 'e1' square
const Board = ({
  fen,
  size = 520,
  flipped = false,
  lastMove = null,
  check = null,
  attackGlow = 0, // 0..1 — Pyro attack intensity
  arrow = null,   // { from, to, color }
  highlights = [], // array of { square, kind: 'legal'|'threat'|'ember' }
  palette = 'ember', // 'ember' | 'cold' | 'paper'
}) => {
  const board = parseFen(fen);
  const files = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  const ranks = ['8', '7', '6', '5', '4', '3', '2', '1'];
  const cellSize = size / 8;

  const palettes = {
    ember: {
      light: '#e8d4a8',
      dark: '#8b6240',
      lastMove: 'rgba(255, 170, 60, 0.45)',
      check: 'rgba(220, 60, 40, 0.65)',
      border: '#2a1a10',
      coord: 'rgba(42, 26, 16, 0.55)',
      coordLight: 'rgba(245, 236, 212, 0.7)',
    },
    cold: {
      light: '#d4dae2',
      dark: '#4d5968',
      lastMove: 'rgba(120, 180, 255, 0.4)',
      check: 'rgba(200, 80, 100, 0.6)',
      border: '#1a2028',
      coord: 'rgba(30, 40, 55, 0.55)',
      coordLight: 'rgba(212, 218, 226, 0.7)',
    },
    paper: {
      light: '#f0e6d2',
      dark: '#b5a88a',
      lastMove: 'rgba(180, 120, 60, 0.35)',
      check: 'rgba(180, 40, 40, 0.5)',
      border: '#3c3328',
      coord: 'rgba(60, 51, 40, 0.55)',
      coordLight: 'rgba(240, 230, 210, 0.8)',
    },
  };
  const pal = palettes[palette];

  const squareAt = (row, col) => {
    const actualRow = flipped ? 7 - row : row;
    const actualCol = flipped ? 7 - col : col;
    return files[actualCol] + ranks[actualRow];
  };
  const pieceAt = (row, col) => {
    const actualRow = flipped ? 7 - row : row;
    const actualCol = flipped ? 7 - col : col;
    return board[actualRow][actualCol];
  };

  // Arrow rendering
  const arrowCoords = (sq) => {
    const f = files.indexOf(sq[0]);
    const r = ranks.indexOf(sq[1]);
    const col = flipped ? 7 - f : f;
    const row = flipped ? 7 - r : r;
    return {
      x: col * cellSize + cellSize / 2,
      y: row * cellSize + cellSize / 2,
    };
  };

  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        boxShadow: attackGlow > 0.1
          ? `0 0 ${40 + attackGlow * 60}px ${attackGlow * 12}px rgba(255, 100, 40, ${0.25 + attackGlow * 0.45}), inset 0 0 0 2px rgba(255, 130, 50, ${attackGlow * 0.8})`
          : `0 0 0 2px ${pal.border}, 0 20px 50px -20px rgba(0,0,0,0.6)`,
        borderRadius: 4,
        overflow: 'hidden',
        transition: 'box-shadow 400ms ease-out',
      }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(8, 1fr)`,
          gridTemplateRows: `repeat(8, 1fr)`,
          width: '100%',
          height: '100%',
        }}
      >
        {Array.from({ length: 64 }).map((_, i) => {
          const row = Math.floor(i / 8);
          const col = i % 8;
          const isLight = (row + col) % 2 === 0;
          const sq = squareAt(row, col);
          const piece = pieceAt(row, col);
          const isLastFrom = lastMove && sq === lastMove.from;
          const isLastTo = lastMove && sq === lastMove.to;
          const isCheck = check === sq;
          const hl = highlights.find(h => h.square === sq);

          return (
            <div
              key={i}
              style={{
                position: 'relative',
                background: isLight ? pal.light : pal.dark,
              }}
            >
              {(isLastFrom || isLastTo) && (
                <div style={{
                  position: 'absolute', inset: 0,
                  background: pal.lastMove,
                  boxShadow: palette === 'ember' && isLastTo
                    ? 'inset 0 0 18px 2px rgba(255, 130, 40, 0.55)'
                    : 'none',
                }} />
              )}
              {isCheck && (
                <div style={{
                  position: 'absolute', inset: 0,
                  background: `radial-gradient(circle, ${pal.check} 0%, transparent 70%)`,
                  animation: 'pyroPulse 1.2s ease-in-out infinite',
                }} />
              )}
              {hl && hl.kind === 'legal' && (
                <div style={{
                  position: 'absolute',
                  left: '50%', top: '50%',
                  width: 16, height: 16,
                  marginLeft: -8, marginTop: -8,
                  borderRadius: '50%',
                  background: 'rgba(0,0,0,0.25)',
                }} />
              )}
              {hl && hl.kind === 'ember' && (
                <div style={{
                  position: 'absolute', inset: 2,
                  borderRadius: 3,
                  boxShadow: 'inset 0 0 12px 2px rgba(255, 140, 50, 0.7)',
                  pointerEvents: 'none',
                }} />
              )}
              {/* Coordinate labels (bottom-left corner only) */}
              {col === 0 && (
                <div style={{
                  position: 'absolute',
                  top: 2, left: 3,
                  fontSize: 10,
                  fontWeight: 700,
                  fontFamily: 'ui-monospace, monospace',
                  color: isLight ? pal.coord : pal.coordLight,
                  pointerEvents: 'none',
                }}>
                  {sq[1]}
                </div>
              )}
              {row === 7 && (
                <div style={{
                  position: 'absolute',
                  bottom: 1, right: 3,
                  fontSize: 10,
                  fontWeight: 700,
                  fontFamily: 'ui-monospace, monospace',
                  color: isLight ? pal.coord : pal.coordLight,
                  pointerEvents: 'none',
                }}>
                  {sq[0]}
                </div>
              )}
              {piece && (
                <div style={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <ChessPiece piece={piece} size={cellSize * 0.92} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Arrow overlay */}
      {arrow && (
        <svg
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
          viewBox={`0 0 ${size} ${size}`}
        >
          <defs>
            <marker
              id={`arrowhead-${arrow.color || 'ember'}`}
              markerWidth="4" markerHeight="4"
              refX="2" refY="2"
              orient="auto"
            >
              <polygon points="0 0, 4 2, 0 4" fill={arrow.color || '#ff8844'} />
            </marker>
          </defs>
          {(() => {
            const a = arrowCoords(arrow.from);
            const b = arrowCoords(arrow.to);
            return (
              <line
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={arrow.color || '#ff8844'}
                strokeWidth={8}
                strokeLinecap="round"
                opacity={0.75}
                markerEnd={`url(#arrowhead-${arrow.color || 'ember'})`}
              />
            );
          })()}
        </svg>
      )}

      {/* Ember particles overlay when attack is strong */}
      {attackGlow > 0.3 && (
        <div style={{
          position: 'absolute', inset: 0,
          pointerEvents: 'none',
          background: `radial-gradient(circle at 50% 50%, transparent 40%, rgba(255,80,20,${attackGlow * 0.12}) 100%)`,
        }} />
      )}
    </div>
  );
};

window.Board = Board;
window.parseFen = parseFen;
