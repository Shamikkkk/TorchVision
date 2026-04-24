/* global React, PyroMark, Board, FEN_KILL_ZONE */

// ═══════════════════════════════════════════════════════════════════════
// GAME-OVER SCREEN — dramatic full-screen takeover
// ═══════════════════════════════════════════════════════════════════════
const GameOverScreen = ({ palette = 'ember', outcome = 'loss' }) => {
  const accent = palette === 'cold' ? '#6a9cff' : palette === 'paper' ? '#a0542a' : '#ff7a2a';
  const bg = palette === 'cold' ? '#060811' : palette === 'paper' ? '#100a06' : '#080503';

  const copy = {
    loss: {
      kicker: 'Checkmate',
      result: '0–1',
      headline: 'That was never going to end any other way.',
      stat: '13 ... Bxb3!! sealed it on move thirteen.',
      pyroSays: "Burn.",
    },
    win: {
      kicker: 'Victory',
      result: '1–0',
      headline: "I let my guard down.",
      stat: 'Enjoy it. It won\'t happen twice.',
      pyroSays: "...",
    },
    draw: {
      kicker: 'Stalemate',
      result: '½–½',
      headline: "Acceptable. Barely.",
      stat: 'Fifty-move rule. You stalled me out.',
      pyroSays: "Coward.",
    },
  }[outcome];

  return (
    <div style={{
      width: '100%', height: '100%',
      background: bg,
      color: '#e8d8b8',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Ambient embers */}
      <div style={{
        position: 'absolute', inset: 0,
        background: `radial-gradient(ellipse at 30% 40%, ${accent}22 0%, transparent 50%), radial-gradient(ellipse at 80% 70%, ${accent}15 0%, transparent 60%)`,
        pointerEvents: 'none',
      }} />
      {/* Dark vignette */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.85) 100%)',
        pointerEvents: 'none',
      }} />

      {/* Left: final position — dimmed */}
      <div style={{
        flex: '0 0 55%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 48,
        position: 'relative',
        zIndex: 1,
      }}>
        <div style={{
          filter: 'saturate(0.7) brightness(0.5)',
          transform: 'scale(1)',
          transition: 'all 600ms',
        }}>
          <Board
            fen={FEN_KILL_ZONE}
            size={520}
            lastMove={{ from: 'a5', to: 'd3' }}
            check="e1"
            attackGlow={1}
            palette={palette}
          />
        </div>
      </div>

      {/* Right: the takeover */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '48px 56px 48px 0',
        position: 'relative',
        zIndex: 1,
      }}>
        <div style={{
          fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
          fontSize: 11,
          color: accent,
          letterSpacing: '0.4em',
          textTransform: 'uppercase',
          marginBottom: 16,
          animation: 'pyroFadeUp 400ms ease-out',
        }}>
          {copy.kicker}
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 24, marginBottom: 8 }}>
          <span style={{
            fontFamily: '"Instrument Serif", Georgia, serif',
            fontSize: 84,
            fontWeight: 400,
            lineHeight: 1,
            color: accent,
            textShadow: `0 0 40px ${accent}88`,
            letterSpacing: '-0.02em',
            animation: 'pyroFadeUp 600ms 100ms ease-out both',
          }}>
            {copy.result}
          </span>
          <span style={{
            fontFamily: 'Inter, sans-serif',
            fontSize: 14,
            color: '#6a5e50',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            animation: 'pyroFadeUp 600ms 200ms ease-out both',
          }}>
            You vs <PyroMark size="sm" mood={4} palette={palette} />
          </span>
        </div>

        <h1 style={{
          margin: '0 0 12px 0',
          fontFamily: '"Instrument Serif", Georgia, serif',
          fontSize: 56,
          fontWeight: 400,
          lineHeight: 1.05,
          color: '#f5ecd4',
          letterSpacing: '-0.015em',
          maxWidth: 520,
          animation: 'pyroFadeUp 700ms 300ms ease-out both',
        }}>
          {copy.headline}
        </h1>

        <div style={{
          fontSize: 14,
          color: '#8a7c68',
          fontFamily: '"Instrument Serif", Georgia, serif',
          fontStyle: 'italic',
          marginBottom: 32,
          animation: 'pyroFadeUp 700ms 450ms ease-out both',
        }}>
          {copy.stat}
        </div>

        {/* Pyro final taunt */}
        <div style={{
          borderLeft: `3px solid ${accent}`,
          paddingLeft: 16,
          marginBottom: 36,
          animation: 'pyroFadeUp 800ms 600ms ease-out both',
        }}>
          <div style={{
            fontSize: 10,
            fontFamily: 'ui-monospace, monospace',
            color: accent,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            marginBottom: 6,
          }}>
            pyro says
          </div>
          <div style={{
            fontFamily: '"Instrument Serif", Georgia, serif',
            fontSize: 28,
            fontStyle: 'italic',
            color: '#ffb080',
            lineHeight: 1.2,
          }}>
            “{copy.pyroSays}”
          </div>
        </div>

        {/* Game summary stats */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 20,
          marginBottom: 36,
          paddingTop: 24,
          borderTop: '1px dashed rgba(255,120,40,0.2)',
          animation: 'pyroFadeUp 900ms 700ms ease-out both',
        }}>
          {[
            { label: 'Moves', v: '42' },
            { label: 'Your acc.', v: '72.4%' },
            { label: 'Pyro acc.', v: '94.1%' },
            { label: 'Blunders', v: '2' },
          ].map(s => (
            <div key={s.label}>
              <div style={{ fontSize: 10, color: '#6a5e50', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 4 }}>
                {s.label}
              </div>
              <div style={{
                fontFamily: '"Instrument Serif", Georgia, serif',
                fontSize: 26, color: '#f5ecd4', fontWeight: 400,
              }}>{s.v}</div>
            </div>
          ))}
        </div>

        {/* CTAs */}
        <div style={{
          display: 'flex', gap: 10,
          animation: 'pyroFadeUp 900ms 800ms ease-out both',
        }}>
          <button style={{
            padding: '14px 28px',
            background: accent,
            color: '#1a0a04',
            border: 'none',
            borderRadius: 3,
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            cursor: 'pointer',
            boxShadow: `0 0 32px ${accent}55`,
          }}>
            ⚐ Rematch
          </button>
          <button style={{
            padding: '14px 24px',
            background: 'transparent',
            color: '#d4c8b0',
            border: '1px solid rgba(232, 216, 184, 0.2)',
            borderRadius: 3,
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            cursor: 'pointer',
          }}>
            Review game
          </button>
          <button style={{
            padding: '14px 20px',
            background: 'transparent',
            color: '#6a5e50',
            border: 'none',
            fontSize: 12,
            fontWeight: 500,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            cursor: 'pointer',
          }}>
            Home
          </button>
        </div>
      </div>
    </div>
  );
};

window.GameOverScreen = GameOverScreen;
