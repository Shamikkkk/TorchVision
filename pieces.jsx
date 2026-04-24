/* global React */
// Chess piece SVGs — using clean Staunton-style shapes.
// Color: "w" or "b". Cached path data.

const PIECE_PATHS = {
  // White/black share same path; fill changes
  // Simplified Staunton silhouettes — compact but recognizable
  k: `M22.5 11.63 V6 M20 8h5 M22.5 25s4.5-7.5 3-10.5c0 0-1-2.5-3-2.5s-3 2.5-3 2.5c-1.5 3 3 10.5 3 10.5 M11.5 37c5.5 3.5 15.5 3.5 21 0v-7s9-4.5 6-10.5c-4-6.5-13.5-3.5-16 4V27v-3.5c-3.5-7.5-13-10.5-16-4-3 6 5 10 5 10V37z`,
  q: `M9 26c8.5-1.5 21-1.5 27 0l2.5-12.5L31 25l-.3-14.1-5.2 13.6-3-14.5-3 14.5-5.2-13.6L14 25 6.5 13.5 9 26z M9 26c0 2 1.5 2 2.5 4 1 1.5 1 1 .5 3.5-1.5 1-1.5 2.5-1.5 2.5-1.5 1.5.5 2.5.5 2.5 6.5 1 16.5 1 23 0 0 0 1.5-1 0-2.5 0 0 .5-1.5-1-2.5-.5-2.5-.5-2 .5-3.5 1-2 2.5-2 2.5-4-8.5-1.5-18.5-1.5-27 0z`,
  r: `M9 39h27v-3H9v3zM12 36v-4h21v4H12zM11 14V9h4v2h5V9h5v2h5V9h4v5 M34 14l-3 3H14l-3-3 M31 17v12.5H14V17 M31 29.5l1.5 2.5h-20l1.5-2.5 M11 14h23`,
  b: `M9 36c3.39-.97 10.11.43 13.5-2 3.39 2.43 10.11 1.03 13.5 2 0 0 1.65.54 3 2-.68.97-1.65.99-3 .5-3.39-.97-10.11.46-13.5-1-3.39 1.46-10.11.03-13.5 1-1.35.49-2.32.47-3-.5 1.35-1.46 3-2 3-2z M15 32c2.5 2.5 12.5 2.5 15 0 .5-1.5 0-2 0-2 0-2.5-2.5-4-2.5-4 5.5-1.5 6-11.5-5-15.5-11 4-10.5 14-5 15.5 0 0-2.5 1.5-2.5 4 0 0-.5.5 0 2z M25 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 1 1 5 0z`,
  n: `M22 10c10.5 1 16.5 8 16 29H15c0-9 10-6.5 8-21 M24 18c.38 2.91-5.55 7.37-8 9-3 2-2.82 4.34-5 4-1.04-.94 1.41-3.04 0-3-1 0 .19 1.23-1 2-1 0-4.003 1-4-4 0-2 6-12 6-12s1.89-1.9 2-3.5c-.73-.994-.5-2-.5-3 1-1 3 2.5 3 2.5h2s.78-1.992 2.5-3c1 0 1 3 1 3 M9.5 25.5a.5.5 0 1 1-1 0 .5.5 0 1 1 1 0z M15 15.5a.5 1.5 30 1 1-.99-.26.5 1.5 30 1 1 .99.26z`,
  p: `M22.5 9c-2.21 0-4 1.79-4 4 0 .89.29 1.71.78 2.38C17.33 16.5 16 18.59 16 21c0 2.03.94 3.84 2.41 5.03-3 1.06-7.41 5.55-7.41 13.47h23c0-7.92-4.41-12.41-7.41-13.47 1.47-1.19 2.41-3 2.41-5.03 0-2.41-1.33-4.5-3.28-5.62.49-.67.78-1.49.78-2.38 0-2.21-1.79-4-4-4z`,
};

// eslint-disable-next-line no-unused-vars
const ChessPiece = ({ piece, size = 48, style = {} }) => {
  if (!piece) return null;
  const color = piece[0] === 'w' ? 'white' : 'black';
  const type = piece[1].toLowerCase();
  const path = PIECE_PATHS[type];
  if (!path) return null;

  const fill = color === 'white' ? '#f5ecd4' : '#1a1613';
  const stroke = color === 'white' ? '#2a1e16' : '#0a0706';

  return (
    <svg
      viewBox="0 0 45 45"
      width={size}
      height={size}
      style={{
        display: 'block',
        filter: color === 'white'
          ? 'drop-shadow(0 1px 1px rgba(0,0,0,0.4))'
          : 'drop-shadow(0 1px 0 rgba(255,200,120,0.15))',
        ...style,
      }}
    >
      <path
        d={path}
        fill={fill}
        stroke={stroke}
        strokeWidth={1.4}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
};

window.ChessPiece = ChessPiece;
