/* global React, Board, PyroMark, MoveList, SAMPLE_MOVES, FEN_KILL_ZONE, FEN_CHECK */

// ═══════════════════════════════════════════════════════════════════════
// ANALYZE SCREEN — post-game review
// ═══════════════════════════════════════════════════════════════════════
const AnalyzeScreen = ({ palette = 'ember' }) => {
  const bg = palette === 'cold' ? '#0a0d14' : palette === 'paper' ? '#1a1510' : '#0f0b08';
  const accent = palette === 'cold' ? '#6a9cff' : palette === 'paper' ? '#a0542a' : '#ff7a2a';

  // Mock accuracy data
  const acc = { you: 72.4, pyro: 94.1 };
  const classifications = [
    { label: 'Brilliant', symbol: '!!', count: 1, color: '#6ee7b7' },
    { label: 'Best', symbol: '★', count: 12, color: '#86efac' },
    { label: 'Good', symbol: '✓', count: 18, color: '#a7e3a7' },
    { label: 'Book', symbol: '📖', count: 8, color: '#a78bfa' },
    { label: 'Inaccuracy', symbol: '?!', count: 4, color: '#fbbf24' },
    { label: 'Mistake', symbol: '?', count: 2, color: '#fb923c' },
    { label: 'Blunder', symbol: '??', count: 2, color: '#ef4444' },
  ];

  // Eval sparkline data — game flow from 0 to -1000cp
  const evalCurve = [0, 10, -5, 20, 15, -30, -40, -20, -60, -80, -120, -180, -140, -200, -260, -340, -420, -500, -680, -820, -9999];

  return (
    <div style={{
      width: '100%', height: '100%',
      background: bg,
      color: '#e8d8b8',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Top bar */}
      <div style={{
        padding: '14px 32px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid rgba(255,120,40,0.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <PyroMark size="md" mood={4} palette={palette} />
          <span style={{ color: '#5a5048', fontSize: 11 }}>·</span>
          <span style={{ fontSize: 12, color: '#8a7c68', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Post-Mortem
          </span>
        </div>
        <div style={{ display: 'flex', gap: 24, fontSize: 11, color: '#8a7c68', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          <span>Play</span>
          <span style={{ color: '#e8d8b8', fontWeight: 600, borderBottom: `2px solid ${accent}`, paddingBottom: 2 }}>Analyze</span>
          <span>History</span>
        </div>
      </div>

      {/* Game header */}
      <div style={{ padding: '20px 32px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
          <h2 style={{
            margin: 0,
            fontFamily: '"Instrument Serif", Georgia, serif',
            fontSize: 28,
            fontWeight: 400,
            color: '#f5ecd4',
          }}>
            You <span style={{ color: '#5a5048' }}>vs.</span> <span style={{ color: accent, fontStyle: 'italic' }}>Pyro</span>
          </h2>
          <span style={{
            fontFamily: 'ui-monospace, monospace',
            fontSize: 18,
            color: accent,
            fontWeight: 700,
          }}>0–1</span>
          <span style={{
            fontSize: 12, color: '#6a5e50',
            fontStyle: 'italic',
            fontFamily: '"Instrument Serif", Georgia, serif',
          }}>
            Sicilian Najdorf · 42 moves · 5+0 · mood: Feral
          </span>
        </div>
      </div>

      {/* Main grid */}
      <div style={{
        flex: 1,
        display: 'grid',
        gridTemplateColumns: '520px 1fr',
        gap: 24,
        padding: '0 32px 24px',
      }}>
        {/* Left: board + eval graph */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Board
            fen={FEN_KILL_ZONE}
            size={520}
            lastMove={{ from: 'a5', to: 'd3' }}
            attackGlow={0.9}
            palette={palette}
          />

          {/* Eval graph */}
          <div style={{
            background: 'rgba(10, 7, 5, 0.4)',
            border: '1px solid rgba(255, 120, 40, 0.12)',
            borderRadius: 4,
            padding: '12px 14px',
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600,
              letterSpacing: '0.18em', textTransform: 'uppercase',
              color: '#6a5e50', marginBottom: 8,
              display: 'flex', justifyContent: 'space-between',
            }}>
              <span>Evaluation over time</span>
              <span style={{ fontFamily: 'ui-monospace, monospace', color: accent }}>
                final: −M1
              </span>
            </div>
            <svg width="100%" height="80" viewBox="0 0 500 80" preserveAspectRatio="none">
              <line x1="0" y1="40" x2="500" y2="40" stroke="rgba(255,255,255,0.1)" strokeDasharray="2,3" />
              {(() => {
                const pts = evalCurve.map((v, i) => {
                  const x = (i / (evalCurve.length - 1)) * 500;
                  const clamped = Math.max(-1000, Math.min(1000, v));
                  const y = 40 - (clamped / 1000) * 38;
                  return [x, y];
                });
                const d = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ',' + p[1]).join(' ');
                const area = d + ` L 500,80 L 0,80 Z`;
                return (
                  <>
                    <path d={area} fill={`${accent}33`} />
                    <path d={d} fill="none" stroke={accent} strokeWidth="2" />
                    {/* Blunder markers */}
                    <circle cx="248" cy="44" r="4" fill="#ef4444" stroke="#0f0b08" strokeWidth="2" />
                    <circle cx="352" cy="56" r="4" fill="#ef4444" stroke="#0f0b08" strokeWidth="2" />
                    <circle cx="430" cy="70" r="5" fill="#6ee7b7" stroke="#0f0b08" strokeWidth="2" />
                  </>
                );
              })()}
            </svg>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#5a5048', fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>
              <span>move 1</span>
              <span>13 ?? Bxb3</span>
              <span>move 42</span>
            </div>
          </div>
        </div>

        {/* Right: accuracy, classification breakdown, moves with pyro commentary */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Accuracy card */}
          <div style={{
            background: 'rgba(10, 7, 5, 0.4)',
            border: '1px solid rgba(255, 120, 40, 0.12)',
            borderRadius: 4,
            padding: '16px 18px',
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600,
              letterSpacing: '0.18em', textTransform: 'uppercase',
              color: '#6a5e50', marginBottom: 14,
            }}>Accuracy</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div>
                <div style={{ fontSize: 11, color: '#a89b84', marginBottom: 4 }}>You</div>
                <div style={{
                  fontFamily: '"Instrument Serif", Georgia, serif',
                  fontSize: 42, fontWeight: 400,
                  color: '#f5ecd4', lineHeight: 1,
                }}>{acc.you}<span style={{ fontSize: 20, color: '#5a5048' }}>%</span></div>
                <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2, marginTop: 8, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${acc.you}%`, background: '#d4c8b0' }} />
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: accent, marginBottom: 4, fontStyle: 'italic' }}>pyro</div>
                <div style={{
                  fontFamily: '"Instrument Serif", Georgia, serif',
                  fontSize: 42, fontWeight: 400,
                  color: accent, lineHeight: 1,
                  textShadow: `0 0 16px ${accent}66`,
                  fontStyle: 'italic',
                }}>{acc.pyro}<span style={{ fontSize: 20, opacity: 0.5 }}>%</span></div>
                <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2, marginTop: 8, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${acc.pyro}%`, background: accent, boxShadow: `0 0 8px ${accent}` }} />
                </div>
              </div>
            </div>
          </div>

          {/* Classification breakdown */}
          <div style={{
            background: 'rgba(10, 7, 5, 0.4)',
            border: '1px solid rgba(255, 120, 40, 0.12)',
            borderRadius: 4,
            padding: '16px 18px',
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600,
              letterSpacing: '0.18em', textTransform: 'uppercase',
              color: '#6a5e50', marginBottom: 12,
              display: 'flex', justifyContent: 'space-between',
            }}>
              <span>Move Classification (you)</span>
              <span style={{ color: '#8a7c68' }}>47 moves</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {classifications.map(c => (
                <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 24, fontSize: 11, fontFamily: 'ui-monospace, monospace', color: c.color, fontWeight: 700 }}>{c.symbol}</span>
                  <span style={{ width: 90, fontSize: 12, color: '#d4c8b0' }}>{c.label}</span>
                  <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.04)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${(c.count / 20) * 100}%`, background: c.color, opacity: 0.8 }} />
                  </div>
                  <span style={{ width: 24, textAlign: 'right', fontSize: 12, color: '#d4c8b0', fontFamily: 'ui-monospace, monospace' }}>{c.count}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Critical moments with Pyro commentary */}
          <div style={{
            background: 'rgba(10, 7, 5, 0.4)',
            border: '1px solid rgba(255, 120, 40, 0.12)',
            borderRadius: 4,
            padding: '16px 18px',
            flex: 1,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600,
              letterSpacing: '0.18em', textTransform: 'uppercase',
              color: '#6a5e50', marginBottom: 12,
            }}>Critical Moments</div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                { ply: '13. exd5 ??', classify: 'Blunder', cp: '−240cp', remark: 'You opened the diagonal. I'+'was going to sac the bishop anyway.', color: '#ef4444' },
                { ply: '13... Bxb3 !!', classify: 'Brilliant', cp: '+420cp', remark: 'Not my move — yours. But I saw it coming fourteen plies ago.', color: '#6ee7b7' },
                { ply: '21. Kf1 ?', classify: 'Mistake', cp: '−180cp', remark: 'Running. Cute.', color: '#fb923c' },
              ].map((m, i) => (
                <div key={i} style={{
                  borderLeft: `3px solid ${m.color}`,
                  paddingLeft: 12,
                  paddingTop: 4,
                  paddingBottom: 4,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13, color: '#f0e4c8', fontWeight: 600 }}>
                      {m.ply}
                    </span>
                    <span style={{ fontSize: 10, color: m.color, fontFamily: 'ui-monospace, monospace', fontWeight: 600 }}>
                      {m.cp}
                    </span>
                  </div>
                  <div style={{
                    fontSize: 12,
                    color: '#ffb080',
                    fontFamily: '"Instrument Serif", Georgia, serif',
                    fontStyle: 'italic',
                    marginTop: 2,
                  }}>
                    “{m.remark}”
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

window.AnalyzeScreen = AnalyzeScreen;
