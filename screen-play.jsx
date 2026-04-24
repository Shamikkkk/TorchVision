/* global React, Board, PyroMark, EvalBar, Clock, MoveList, MoodSelector, TauntBubble, CapturedRow, EnginePanel, SAMPLE_MOVES, FEN_CHECK, FEN_KILL_ZONE, FEN_LATE_ATTACK */

// ═══════════════════════════════════════════════════════════════════════
// PLAY SCREEN — main gameplay UI
// ═══════════════════════════════════════════════════════════════════════
const PlayScreen = ({
  palette = 'ember',
  state = 'attack', // 'quiet' | 'attack' | 'mate-threat'
  mood = 'feral',
  showTaunt = true,
}) => {
  const moodIdx = (window.MOODS.find(m => m.id === mood) || { idx: 4 }).idx;

  // Adjust scenario by state
  const scenario = {
    quiet: {
      fen: FEN_LATE_ATTACK,
      score: -120,
      attackGlow: 0.15,
      taunt: "I know this one.",
      tauntVariant: 'default',
      check: null,
      lastMove: { from: 'd8', to: 'a5' },
      arrow: null,
      bestMove: 'Qa5',
      pv: 'Qa5 Nd2 O-O Qc2 e5',
      depth: 14,
      nodes: 2_450_000,
      mateScreenDim: 0,
    },
    attack: {
      fen: FEN_CHECK,
      score: -340,
      attackGlow: 0.55,
      taunt: "Take it. I dare you.",
      tauntVariant: 'strong',
      check: null,
      lastMove: { from: 'a1', to: 'd1' }, // just played
      arrow: { from: 'b4', to: 'e1', color: '#ff7a2a' },
      bestMove: 'Bxe1',
      pv: 'Bxe1 Kxe1 Qxa2 Kf1 O-O-O',
      depth: 17,
      nodes: 8_210_000,
      mateScreenDim: 0,
    },
    'mate-threat': {
      fen: FEN_KILL_ZONE,
      score: -9995, // mate
      attackGlow: 1.0,
      taunt: "Two more moves. Maybe three if you stall.",
      tauntVariant: 'strong',
      check: 'e1',
      lastMove: { from: 'e7', to: 'b4' },
      arrow: { from: 'a5', to: 'e1', color: '#ff3a1a' },
      bestMove: 'Qxa2',
      pv: 'Qxa2 Kf1 Qb1+ Ke2 Qxd3#',
      depth: 22,
      nodes: 18_900_000,
      mateScreenDim: 0.5,
    },
  }[state];

  const bg = palette === 'cold' ? '#0a0d14' : palette === 'paper' ? '#1a1510' : '#0f0b08';
  const accent = palette === 'cold' ? '#6a9cff' : palette === 'paper' ? '#a0542a' : '#ff7a2a';
  const BOARD_SIZE = 560;

  return (
    <div style={{
      width: '100%', height: '100%',
      background: bg,
      color: '#e8d8b8',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Mate-threat screen dim */}
      {scenario.mateScreenDim > 0 && (
        <div style={{
          position: 'absolute', inset: 0,
          background: `radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,${scenario.mateScreenDim}) 100%)`,
          pointerEvents: 'none',
          zIndex: 2,
        }} />
      )}

      {/* Top bar */}
      <div style={{
        padding: '14px 32px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid rgba(255,120,40,0.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <PyroMark size="md" mood={moodIdx} palette={palette} />
          <span style={{ color: '#5a5048', fontSize: 11, letterSpacing: '0.1em' }}>·</span>
          <span style={{ fontSize: 12, color: '#8a7c68', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            You vs <span style={{ color: accent, fontWeight: 600 }}>Pyro</span>
          </span>
        </div>
        <div style={{ display: 'flex', gap: 24, fontSize: 11, color: '#8a7c68', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          <span style={{ color: '#e8d8b8', fontWeight: 600, borderBottom: `2px solid ${accent}`, paddingBottom: 2 }}>Play</span>
          <span>Analyze</span>
          <span>History</span>
        </div>
      </div>

      {/* Main grid */}
      <div style={{
        flex: 1,
        display: 'grid',
        gridTemplateColumns: '240px 1fr 300px',
        gap: 24,
        padding: '24px 32px',
        position: 'relative',
        zIndex: 1,
      }}>

        {/* Left rail: mood + engine telemetry */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <MoodSelector current={mood} onSelect={() => {}} />

          <div style={{ borderTop: '1px dashed rgba(255, 120, 40, 0.15)', paddingTop: 16 }}>
            <EnginePanel
              depth={scenario.depth}
              nodes={scenario.nodes}
              nps={Math.round(scenario.nodes / 4.5)}
              pv={scenario.pv}
              bestMove={scenario.bestMove}
              thinking={state !== 'quiet'}
            />
          </div>

          {/* Sound-wave visualizer */}
          <div style={{
            border: '1px solid rgba(255, 120, 40, 0.15)',
            borderRadius: 4,
            padding: '10px 12px',
            background: 'rgba(10, 7, 5, 0.4)',
          }}>
            <div style={{
              fontFamily: 'Inter, system-ui, sans-serif',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: '#6a5e50',
              marginBottom: 8,
              display: 'flex', justifyContent: 'space-between',
            }}>
              <span>Sound</span>
              <span style={{ color: accent }}>ON</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 24 }}>
              {[6, 12, 4, 18, 22, 14, 8, 20, 16, 6, 10, 14, 20, 8, 4, 12, 18, 10, 6, 14].map((h, i) => (
                <div key={i} style={{
                  flex: 1,
                  height: state !== 'quiet' ? h : h * 0.3,
                  background: i < 3 ? accent : `rgba(255, 120, 40, ${0.2 + (i % 3) * 0.1})`,
                  borderRadius: 1,
                  transition: 'height 200ms',
                }} />
              ))}
            </div>
            <div style={{ fontSize: 10, color: '#5a5048', fontFamily: 'ui-monospace, monospace', marginTop: 4 }}>
              move · capture · check
            </div>
          </div>
        </div>

        {/* Center: board + eval bar + clocks + player rows */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', justifyContent: 'center' }}>
          <EvalBar score={scenario.score} height={BOARD_SIZE} palette={palette} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: BOARD_SIZE }}>

            {/* Top player (Pyro) */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minHeight: 28 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <PyroMark size="sm" mood={moodIdx} palette={palette} />
                <span style={{ fontSize: 11, color: '#6a5e50', fontStyle: 'italic' }}>
                  burns brightest when you're losing
                </span>
              </div>
              <CapturedRow captured={['p', 'p', 'b']} materialAdv={2} />
            </div>

            {/* Pyro taunt — just above clock */}
            {showTaunt && (
              <div style={{ minHeight: 36, display: 'flex', alignItems: 'center' }}>
                <TauntBubble
                  text={scenario.taunt}
                  variant={scenario.tauntVariant}
                />
              </div>
            )}

            <Clock ms={183_420} active={false} label="Pyro" isPyro palette={palette} />

            {/* The board */}
            <Board
              fen={scenario.fen}
              size={BOARD_SIZE}
              lastMove={scenario.lastMove}
              check={scenario.check}
              attackGlow={scenario.attackGlow}
              arrow={scenario.arrow}
              palette={palette}
            />

            {/* Human clock */}
            <Clock
              ms={state === 'mate-threat' ? 4_200 : 121_050}
              active={true}
              label="You"
              low={state === 'mate-threat'}
              palette={palette}
            />

            {/* Bottom player (Human) */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minHeight: 28 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{
                  width: 12, height: 12, borderRadius: '50%',
                  background: '#f5ecd4', border: '1px solid #2a1a10',
                }} />
                <span style={{ fontSize: 13, color: '#d4c8b0', fontWeight: 500 }}>You</span>
                <span style={{ fontSize: 11, color: '#5a5048', fontFamily: 'ui-monospace, monospace' }}>· 1450</span>
              </div>
              <CapturedRow captured={['p']} materialAdv={0} />
            </div>

            {/* Opening name */}
            <div style={{ textAlign: 'center', marginTop: 4 }}>
              <span style={{
                fontSize: 12,
                color: '#8a7c68',
                fontStyle: 'italic',
                fontFamily: '"Instrument Serif", Georgia, serif',
              }}>
                Sicilian Defense, Najdorf Variation · B90
              </span>
            </div>
          </div>
        </div>

        {/* Right rail: move list + controls */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{
            background: 'rgba(10, 7, 5, 0.4)',
            border: '1px solid rgba(255, 120, 40, 0.1)',
            borderRadius: 4,
            padding: '14px 16px',
          }}>
            <div style={{
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: '#6a5e50',
              marginBottom: 10,
              display: 'flex', justifyContent: 'space-between',
            }}>
              <span>Scoresheet</span>
              <span style={{ fontFamily: 'ui-monospace, monospace', color: '#8a7c68' }}>
                move {Math.ceil(SAMPLE_MOVES.length / 2)}
              </span>
            </div>
            <MoveList moves={SAMPLE_MOVES} currentPly={SAMPLE_MOVES.length - 1} />
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <button style={{
              padding: '10px 14px',
              background: accent,
              color: '#1a0a04',
              border: 'none',
              borderRadius: 3,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              cursor: 'pointer',
            }}>
              ⚐ New Game
            </button>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <button style={{
                padding: '10px 14px',
                background: 'rgba(255, 255, 255, 0.04)',
                color: '#d4c8b0',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: 3,
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                cursor: 'pointer',
              }}>Resign</button>
              <button style={{
                padding: '10px 14px',
                background: 'rgba(255, 255, 255, 0.04)',
                color: '#d4c8b0',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: 3,
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                cursor: 'pointer',
              }}>⇄ Flip</button>
            </div>
          </div>

          {/* Threat meter */}
          <div style={{
            background: 'rgba(10, 7, 5, 0.4)',
            border: '1px solid rgba(255, 120, 40, 0.15)',
            borderRadius: 4,
            padding: '12px 14px',
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: '#6a5e50',
              marginBottom: 8,
            }}>
              <span>Threat Level</span>
              <span style={{ color: accent, fontFamily: 'ui-monospace, monospace' }}>
                {(scenario.attackGlow * 100).toFixed(0)}%
              </span>
            </div>
            <div style={{ position: 'relative', height: 6, background: 'rgba(255, 255, 255, 0.04)', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{
                position: 'absolute', left: 0, top: 0, bottom: 0,
                width: `${scenario.attackGlow * 100}%`,
                background: `linear-gradient(90deg, ${accent}, #ff3a1a)`,
                boxShadow: `0 0 12px ${accent}`,
                transition: 'width 400ms',
              }} />
            </div>
            <div style={{ fontSize: 10, color: '#5a5048', marginTop: 6, fontFamily: 'ui-monospace, monospace' }}>
              king_attack · {Math.round(scenario.attackGlow * 240)}cp bonus
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

window.PlayScreen = PlayScreen;
