/* global React */

// ════════════════════════════════════════════════════════════════════
// PyroMark — typographic wordmark with flicker driven by mood intensity
// ════════════════════════════════════════════════════════════════════
const PyroMark = ({ size = 'md', mood = 4, palette = 'ember' }) => {
  // mood: 0..4 (Sleeping → Feral) — drives flicker + glow intensity
  const intensity = Math.max(0, Math.min(4, mood)) / 4;
  const sizes = {
    sm: { font: 14, letterSpacing: '0.14em' },
    md: { font: 20, letterSpacing: '0.18em' },
    lg: { font: 56, letterSpacing: '0.22em' },
    xl: { font: 120, letterSpacing: '0.24em' },
  };
  const s = sizes[size] || sizes.md;

  const colors = {
    ember: { base: '#ff7a2a', glow: 'rgba(255, 120, 40, 0.6)' },
    cold: { base: '#b7c7e0', glow: 'rgba(120, 180, 255, 0.5)' },
    paper: { base: '#2a1a10', glow: 'rgba(120, 60, 20, 0.25)' },
  };
  const c = colors[palette] || colors.ember;

  const animName = intensity > 0.6 ? 'pyroFlickerHot' : intensity > 0.3 ? 'pyroFlicker' : 'none';

  return (
    <span
      style={{
        fontFamily: '"Instrument Serif", "Fraunces", Georgia, serif',
        fontSize: s.font,
        letterSpacing: s.letterSpacing,
        fontWeight: 400,
        color: c.base,
        fontStyle: 'italic',
        textShadow: intensity > 0.1
          ? `0 0 ${4 + intensity * 16}px ${c.glow}, 0 0 ${2 + intensity * 8}px ${c.glow}`
          : 'none',
        animation: `${animName} ${2.5 - intensity * 1.5}s ease-in-out infinite`,
        display: 'inline-block',
        textTransform: 'lowercase',
      }}
    >
      pyro
    </span>
  );
};

// ════════════════════════════════════════════════════════════════════
// EvalBar — vertical bar with flame silhouette when Pyro is winning
// ════════════════════════════════════════════════════════════════════
const EvalBar = ({ score = 0, height = 520, flipped = false, palette = 'ember' }) => {
  // score in centipawns, positive = white winning. Pyro = black in most shots.
  // We convert to "Pyro advantage" for flame effect.
  const clamp = Math.max(-1000, Math.min(1000, score));
  const pct = 50 - (clamp / 1000) * 50; // white % from top
  // Sigmoid-ish for bar display
  const sig = 1 / (1 + Math.exp(-clamp / 250));
  const whitePct = sig * 100;

  const palettes = {
    ember: { white: '#f5ecd4', black: '#1a0f0a', ember: '#ff7a2a' },
    cold: { white: '#e8ecf2', black: '#0a0f18', ember: '#6a9cff' },
    paper: { white: '#f5ecd4', black: '#2a1a10', ember: '#a0542a' },
  };
  const pal = palettes[palette];

  const topIsWhite = !flipped;
  const emberSide = score < -100 ? (topIsWhite ? 'bottom' : 'top') : null; // Pyro = black
  const emberIntensity = Math.min(1, Math.max(0, -score / 600));

  const formatScore = (cp) => {
    if (Math.abs(cp) > 9000) return cp > 0 ? 'M' + Math.ceil((9999 - cp) / 10) : '-M' + Math.ceil((9999 + cp) / 10);
    const v = (cp / 100).toFixed(1);
    return cp >= 0 ? '+' + v : v;
  };

  return (
    <div style={{
      width: 28,
      height,
      position: 'relative',
      background: pal.black,
      borderRadius: 3,
      overflow: 'hidden',
      boxShadow: emberIntensity > 0.2
        ? `0 0 ${12 + emberIntensity * 20}px rgba(255, 90, 20, ${emberIntensity * 0.6})`
        : '0 1px 3px rgba(0,0,0,0.3)',
    }}>
      {/* White portion (top if not flipped) */}
      <div style={{
        position: 'absolute',
        top: topIsWhite ? 0 : `${100 - whitePct}%`,
        left: 0, right: 0,
        height: topIsWhite ? `${whitePct}%` : undefined,
        bottom: topIsWhite ? undefined : 0,
        background: pal.white,
        transition: 'all 500ms ease-out',
      }} />

      {/* Flame lick at Pyro's side when winning */}
      {emberIntensity > 0.15 && (
        <div style={{
          position: 'absolute',
          left: 0, right: 0,
          [emberSide]: 0,
          height: `${20 + emberIntensity * 40}%`,
          background: `linear-gradient(to ${emberSide === 'bottom' ? 'top' : 'bottom'}, ${pal.ember} 0%, rgba(255,80,20,0) 100%)`,
          opacity: 0.5 + emberIntensity * 0.5,
          mixBlendMode: 'screen',
          animation: 'pyroFlicker 1.8s ease-in-out infinite',
        }} />
      )}

      {/* Score number overlay */}
      <div style={{
        position: 'absolute',
        [score >= 0 ? 'bottom' : 'top']: 4,
        left: 0, right: 0,
        textAlign: 'center',
        fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
        fontSize: 10,
        fontWeight: 700,
        color: score >= 0 ? pal.black : pal.white,
        textShadow: score < 0 && emberIntensity > 0.3 ? `0 0 4px ${pal.ember}` : 'none',
      }}>
        {formatScore(score)}
      </div>
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════
// Clock
// ════════════════════════════════════════════════════════════════════
const Clock = ({ ms, active, label, isPyro = false, palette = 'ember', low = false }) => {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  const cs = Math.floor((ms % 1000) / 10);
  const display = totalSec < 20
    ? `${m}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;

  const bg = active
    ? (isPyro ? 'linear-gradient(90deg, #2a0f06 0%, #3a1408 100%)' : '#f5ecd4')
    : '#181510';
  const color = active
    ? (isPyro ? '#ff9a5a' : '#1a100a')
    : '#6a5e50';
  const border = active && isPyro
    ? '1px solid rgba(255, 120, 40, 0.5)'
    : active
      ? '1px solid rgba(245, 236, 212, 0.2)'
      : '1px solid rgba(255,255,255,0.05)';

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '8px 14px',
      background: bg,
      border,
      borderRadius: 4,
      transition: 'all 200ms',
      boxShadow: active && low ? 'inset 0 0 16px rgba(255, 60, 40, 0.5)' : 'none',
    }}>
      <span style={{
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: active ? (isPyro ? '#ff9a5a' : '#6a5e50') : '#4a4238',
      }}>
        {label}
      </span>
      <span style={{
        fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
        fontSize: 22,
        fontWeight: 600,
        color,
        fontVariantNumeric: 'tabular-nums',
        letterSpacing: '-0.02em',
      }}>
        {display}
      </span>
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════
// MoveList — SAN scoresheet style
// ════════════════════════════════════════════════════════════════════
const MoveList = ({ moves, currentPly = null, highlights = {} }) => {
  // moves: array of {san, symbol?} — symbol: '!', '??', 'book', etc.
  const pairs = [];
  for (let i = 0; i < moves.length; i += 2) {
    pairs.push({ n: i / 2 + 1, w: moves[i], b: moves[i + 1] });
  }

  const symbolColor = {
    '!!': '#6ee7b7', // brilliant - green
    '!': '#86efac',
    '?!': '#fbbf24',
    '?': '#fb923c',
    '??': '#ef4444',
    'book': '#a78bfa',
  };

  return (
    <div style={{
      fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
      fontSize: 12,
      lineHeight: 1.8,
      color: '#d4c8b0',
      maxHeight: 240,
      overflowY: 'auto',
      padding: '4px 2px',
    }}>
      {pairs.map(({ n, w, b }) => {
        const wPly = (n - 1) * 2;
        const bPly = wPly + 1;
        return (
          <div key={n} style={{ display: 'grid', gridTemplateColumns: '28px 1fr 1fr', gap: 8 }}>
            <span style={{ color: '#5a5048', fontSize: 11 }}>{n}.</span>
            <span style={{
              color: currentPly === wPly ? '#ff9a5a' : '#d4c8b0',
              background: currentPly === wPly ? 'rgba(255, 120, 40, 0.08)' : 'transparent',
              padding: '0 4px',
              borderRadius: 2,
            }}>
              {w && w.san}
              {w && w.symbol && (
                <span style={{ color: symbolColor[w.symbol] || '#999', marginLeft: 2, fontWeight: 700 }}>
                  {w.symbol}
                </span>
              )}
            </span>
            <span style={{
              color: currentPly === bPly ? '#ff9a5a' : '#d4c8b0',
              background: currentPly === bPly ? 'rgba(255, 120, 40, 0.08)' : 'transparent',
              padding: '0 4px',
              borderRadius: 2,
            }}>
              {b && b.san}
              {b && b.symbol && (
                <span style={{ color: symbolColor[b.symbol] || '#999', marginLeft: 2, fontWeight: 700 }}>
                  {b.symbol}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════
// MoodSelector
// ════════════════════════════════════════════════════════════════════
const MOODS = [
  { id: 'sleeping', label: 'Sleeping', glyph: '◦', sub: '0.1s', idx: 0 },
  { id: 'playful', label: 'Playful', glyph: '◊', sub: '0.5s', idx: 1 },
  { id: 'awake', label: 'Awake', glyph: '◈', sub: '2s', idx: 2 },
  { id: 'hunting', label: 'Hunting', glyph: '▲', sub: '5s', idx: 3 },
  { id: 'feral', label: 'Feral', glyph: '★', sub: 'full', idx: 4 },
];

const MoodSelector = ({ current = 'feral', onSelect }) => (
  <div>
    <div style={{
      fontFamily: 'Inter, system-ui, sans-serif',
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      color: '#6a5e50',
      marginBottom: 8,
    }}>
      Pyro's Mood
    </div>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {MOODS.map(m => {
        const selected = m.id === current;
        return (
          <button
            key={m.id}
            onClick={() => onSelect && onSelect(m.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '7px 12px',
              border: selected ? '1px solid rgba(255,120,40,0.4)' : '1px solid transparent',
              background: selected ? 'rgba(255, 120, 40, 0.08)' : 'transparent',
              borderRadius: 3,
              cursor: 'pointer',
              transition: 'all 150ms',
              fontFamily: 'Inter, system-ui, sans-serif',
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{
                fontSize: 14,
                color: selected ? '#ff7a2a' : '#5a5048',
                width: 14,
                textAlign: 'center',
              }}>{m.glyph}</span>
              <span style={{
                fontSize: 13,
                fontWeight: 500,
                color: selected ? '#f0e4c8' : '#a89b84',
              }}>{m.label}</span>
            </span>
            <span style={{
              fontSize: 10,
              fontFamily: 'ui-monospace, monospace',
              color: '#5a5048',
              letterSpacing: '0.04em',
            }}>{m.sub}</span>
          </button>
        );
      })}
    </div>
  </div>
);

// ════════════════════════════════════════════════════════════════════
// TauntBubble — animated chat bubble
// ════════════════════════════════════════════════════════════════════
const TauntBubble = ({ text, show = true, variant = 'default' }) => {
  if (!text || !show) return null;
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '8px 14px',
      borderRadius: '14px 14px 14px 2px',
      background: variant === 'strong'
        ? 'linear-gradient(135deg, #2a0f06 0%, #3a1408 100%)'
        : 'rgba(20, 14, 10, 0.9)',
      border: '1px solid rgba(255, 120, 40, 0.3)',
      boxShadow: variant === 'strong'
        ? '0 0 20px rgba(255, 80, 20, 0.25)'
        : '0 2px 8px rgba(0,0,0,0.4)',
      fontFamily: '"Instrument Serif", Georgia, serif',
      fontStyle: 'italic',
      fontSize: 14,
      color: '#ffb080',
      maxWidth: 260,
      lineHeight: 1.35,
      position: 'relative',
      animation: 'pyroTauntIn 400ms ease-out',
    }}>
      <span style={{
        position: 'absolute',
        left: -6, top: 8,
        fontSize: 11,
        color: 'rgba(255, 120, 40, 0.5)',
      }}>▸</span>
      “{text}”
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════
// CapturedRow
// ════════════════════════════════════════════════════════════════════
const CAPTURE_VALUES = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
const CapturedRow = ({ captured = [], materialAdv = 0 }) => {
  // captured: array of piece chars lowercase (that color was captured from)
  const sorted = [...captured].sort((a, b) => CAPTURE_VALUES[b] - CAPTURE_VALUES[a]);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 3, minHeight: 20 }}>
      {sorted.map((p, i) => (
        <span key={i} style={{
          fontSize: 14,
          color: 'rgba(230, 200, 160, 0.65)',
          marginLeft: i > 0 ? -4 : 0,
          filter: 'drop-shadow(0 1px 0 rgba(0,0,0,0.4))',
        }}>
          {PIECE_GLYPH[p]}
        </span>
      ))}
      {materialAdv > 0 && (
        <span style={{
          fontSize: 11,
          fontFamily: 'ui-monospace, monospace',
          color: '#8a7c68',
          marginLeft: 6,
          fontWeight: 600,
        }}>+{materialAdv}</span>
      )}
    </div>
  );
};
const PIECE_GLYPH = { p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚' };

// ════════════════════════════════════════════════════════════════════
// EnginePanel — depth/nodes telemetry (the "training flex" readout)
// ════════════════════════════════════════════════════════════════════
const EnginePanel = ({ depth = 14, nodes = 2_450_000, nps = 1_820_000, pv = 'Nxf7 Kxf7 Qh5+ g6 Qxh7+', bestMove = 'Nxf7', thinking = false }) => (
  <div style={{
    border: '1px solid rgba(255, 120, 40, 0.15)',
    borderRadius: 4,
    padding: '10px 12px',
    background: 'rgba(10, 7, 5, 0.4)',
    fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
  }}>
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      marginBottom: 8,
    }}>
      <span style={{
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: '0.18em',
        textTransform: 'uppercase',
        color: '#6a5e50',
      }}>
        Engine · Rust + Tal eval
      </span>
      {thinking && (
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: '#ff7a2a',
          animation: 'pyroPulse 0.8s ease-in-out infinite',
        }} />
      )}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, fontSize: 11 }}>
      <div>
        <div style={{ color: '#5a5048', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em' }}>depth</div>
        <div style={{ color: '#f0e4c8', fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{depth}</div>
      </div>
      <div>
        <div style={{ color: '#5a5048', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em' }}>nodes</div>
        <div style={{ color: '#f0e4c8', fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
          {(nodes / 1e6).toFixed(2)}M
        </div>
      </div>
      <div>
        <div style={{ color: '#5a5048', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em' }}>nps</div>
        <div style={{ color: '#f0e4c8', fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
          {(nps / 1e6).toFixed(2)}M
        </div>
      </div>
    </div>
    <div style={{
      marginTop: 10,
      paddingTop: 8,
      borderTop: '1px dashed rgba(255, 120, 40, 0.15)',
      fontSize: 11,
      color: '#ffb080',
    }}>
      <span style={{ color: '#5a5048' }}>pv › </span>
      <span style={{ fontWeight: 600 }}>{bestMove}</span>
      <span style={{ color: '#a89b84' }}> {pv.split(' ').slice(1).join(' ')}</span>
    </div>
  </div>
);

Object.assign(window, {
  PyroMark, EvalBar, Clock, MoveList, MoodSelector, TauntBubble, CapturedRow, EnginePanel, MOODS,
});
