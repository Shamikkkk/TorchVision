/* global React, Board, PyroMark, EvalBar, Clock, MoveList, MoodSelector, TauntBubble, CapturedRow, EnginePanel */

// ═══════════════════════════════════════════════════════════════════════
// Sample game: Kasparov vs Topalov, Wijk aan Zee 1999 — the Immortal
// Used as our "Pyro vs You" scenario. Pyro plays as Kasparov (white here)
// but we'll flip: Pyro plays Black (the attacker). We've stopped mid-attack.
// ═══════════════════════════════════════════════════════════════════════

// Mid-game position: Pyro (Black) has just sac'd a piece — attack glowing.
// Position after a theatrical sacrifice by Black.
const FEN_MIDGAME = 'r3k2r/pp1nbppp/2p1pn2/3p4/3P4/2NBPN2/PPPQ1PPP/R3K2R w KQkq - 0 10';
const FEN_LATE_ATTACK = 'r1bk3r/pp1n1ppp/4p3/q7/3N4/2P5/PP3PPP/R1BQK2R b KQ - 0 12';
// Check position — white king exposed, Pyro (Black) threatening mate
const FEN_CHECK = 'r1b2rk1/pp3ppp/2n1p3/q2pP3/3P1B2/2PB1N2/P4PPP/R3K2R w KQ - 0 14';
// Just before the kill — Pyro about to deliver mate in 2
const FEN_KILL_ZONE = 'r4rk1/pp3ppp/2n1p3/q2pP3/1b1P1B2/2PB1N2/P4PPP/R3K2R w - - 0 15';

const SAMPLE_MOVES = [
  { san: 'e4', symbol: 'book' }, { san: 'c5', symbol: 'book' },
  { san: 'Nf3', symbol: 'book' }, { san: 'd6', symbol: 'book' },
  { san: 'd4', symbol: 'book' }, { san: 'cxd4', symbol: 'book' },
  { san: 'Nxd4' }, { san: 'Nf6' },
  { san: 'Nc3' }, { san: 'a6' },
  { san: 'Be2' }, { san: 'e5' },
  { san: 'Nb3' }, { san: 'Be7' },
  { san: 'O-O' }, { san: 'O-O' },
  { san: 'Be3' }, { san: 'Be6' },
  { san: 'Qd3', symbol: '?!' }, { san: 'Nbd7' },
  { san: 'Nd5' }, { san: 'Nxd5', symbol: '!' },
  { san: 'exd5', symbol: '?' }, { san: 'Bxb3!!', symbol: '!!' },
  { san: 'axb3' },
];

const TAUNTS = {
  opening: "I know this one.",
  trap_set: "You walked right into it.",
  sacrifice: "Take it. I dare you.",
  brilliant: "Did you see that coming?",
  blunder_human: "Oh. That was careless.",
  near_mate: "I can see the end from here.",
  mate_in_2: "Two more moves. Maybe three if you stall.",
  game_start: "Let's see what you've got.",
  winning: "This ends soon.",
};

// ═══════════════════════════════════════════════════════════════════════
// LOBBY SCREEN
// ═══════════════════════════════════════════════════════════════════════
const LobbyScreen = ({ palette = 'ember' }) => {
  const [mood, setMood] = React.useState('feral');
  const moodIdx = (window.MOODS.find(m => m.id === mood) || { idx: 4 }).idx;

  const bg = palette === 'cold' ? '#0a0d14' : palette === 'paper' ? '#1a1510' : '#0f0b08';
  const accent = palette === 'cold' ? '#6a9cff' : palette === 'paper' ? '#a0542a' : '#ff7a2a';

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
      {/* Ambient ember glow in corners */}
      <div style={{
        position: 'absolute', width: 600, height: 600,
        bottom: -200, right: -200,
        background: `radial-gradient(circle, ${accent}22 0%, transparent 60%)`,
        pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', width: 400, height: 400,
        top: -100, left: -100,
        background: `radial-gradient(circle, ${accent}11 0%, transparent 60%)`,
        pointerEvents: 'none',
      }} />

      {/* Top bar */}
      <div style={{
        padding: '18px 40px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid rgba(255,120,40,0.08)',
        zIndex: 1,
      }}>
        <PyroMark size="md" mood={moodIdx} palette={palette} />
        <div style={{ display: 'flex', gap: 24, fontSize: 12, color: '#8a7c68', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          <span style={{ color: '#e8d8b8', fontWeight: 600 }}>Play</span>
          <span>Analyze</span>
          <span>History</span>
          <span>About</span>
        </div>
      </div>

      {/* Hero */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 40, padding: '48px 56px', zIndex: 1 }}>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{
            fontFamily: 'ui-monospace, monospace',
            fontSize: 11,
            color: accent,
            letterSpacing: '0.3em',
            textTransform: 'uppercase',
            marginBottom: 16,
          }}>
            Engine · v0.9 · ~1770 Elo
          </div>
          <h1 style={{
            fontFamily: '"Instrument Serif", Georgia, serif',
            fontSize: 92,
            fontWeight: 400,
            lineHeight: 0.95,
            margin: 0,
            color: '#f5ecd4',
            letterSpacing: '-0.02em',
          }}>
            I burn<br/>
            <span style={{ fontStyle: 'italic', color: accent, textShadow: `0 0 30px ${accent}88` }}>brightest</span><br/>
            when you're<br/>
            <span style={{ fontStyle: 'italic' }}>losing.</span>
          </h1>
          <div style={{
            marginTop: 28,
            fontSize: 14,
            color: '#8a7c68',
            maxWidth: 440,
            lineHeight: 1.6,
          }}>
            Pyro is a hand-built Tal-style chess engine. Alpha-beta search, aggressive
            sacrifices, zero patience for positional play. Trained to hunt kings, not
            to win endgames.
          </div>

          <div style={{ display: 'flex', gap: 12, marginTop: 40 }}>
            <button style={{
              padding: '14px 28px',
              background: accent,
              color: '#1a0a04',
              border: 'none',
              borderRadius: 3,
              fontSize: 13,
              fontWeight: 700,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              cursor: 'pointer',
              boxShadow: `0 0 40px ${accent}44`,
            }}>
              Wake Pyro →
            </button>
            <button style={{
              padding: '14px 28px',
              background: 'transparent',
              color: '#e8d8b8',
              border: '1px solid rgba(232, 216, 184, 0.2)',
              borderRadius: 3,
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              cursor: 'pointer',
            }}>
              Analyze a Game
            </button>
          </div>
        </div>

        {/* Right: mood + settings */}
        <div style={{
          background: 'rgba(255, 120, 40, 0.03)',
          border: '1px solid rgba(255, 120, 40, 0.12)',
          borderRadius: 4,
          padding: 24,
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}>
          <MoodSelector current={mood} onSelect={setMood} />

          <div style={{ borderTop: '1px dashed rgba(255, 120, 40, 0.15)', paddingTop: 18 }}>
            <div style={{
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: '#6a5e50',
              marginBottom: 10,
            }}>
              Time control
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
              {['1+0', '3+2', '5+0', '10+0', '15+10', '∞'].map((tc, i) => (
                <button key={tc} style={{
                  padding: '10px 8px',
                  background: i === 2 ? 'rgba(255,120,40,0.08)' : 'transparent',
                  border: i === 2 ? '1px solid rgba(255,120,40,0.35)' : '1px solid rgba(255,255,255,0.05)',
                  color: i === 2 ? '#ff9a5a' : '#a89b84',
                  borderRadius: 3,
                  fontSize: 13,
                  fontFamily: 'ui-monospace, monospace',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}>{tc}</button>
              ))}
            </div>
          </div>

          <div style={{ borderTop: '1px dashed rgba(255, 120, 40, 0.15)', paddingTop: 18 }}>
            <div style={{
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: '#6a5e50',
              marginBottom: 10,
            }}>
              Play as
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
              {['White', 'Random', 'Black'].map((c, i) => (
                <button key={c} style={{
                  padding: '10px 8px',
                  background: i === 0 ? 'rgba(245, 236, 212, 0.08)' : 'transparent',
                  border: i === 0 ? '1px solid rgba(245, 236, 212, 0.3)' : '1px solid rgba(255,255,255,0.05)',
                  color: i === 0 ? '#f5ecd4' : '#a89b84',
                  borderRadius: 3,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}>{c}</button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom: recent games strip */}
      <div style={{ padding: '0 56px 32px', zIndex: 1 }}>
        <div style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color: '#6a5e50',
          marginBottom: 10,
        }}>
          Last night's hunts
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
          {[
            { res: '1-0', you: 'You', them: 'Pyro', time: '5+0', opening: 'Sicilian Najdorf', moves: 42, when: '2h' },
            { res: '0-1', you: 'You', them: 'Pyro', time: '3+2', opening: "King's Gambit", moves: 28, when: '4h' },
            { res: '0-1', you: 'You', them: 'Pyro', time: '10+0', opening: 'Italian Game', moves: 51, when: '1d' },
            { res: '½-½', you: 'You', them: 'Pyro', time: '5+0', opening: 'French Winawer', moves: 68, when: '2d' },
          ].map((g, i) => {
            const lost = g.res === '0-1';
            return (
              <div key={i} style={{
                padding: '12px 14px',
                background: 'rgba(255, 255, 255, 0.02)',
                border: `1px solid ${lost ? 'rgba(255, 80, 40, 0.2)' : 'rgba(255,255,255,0.06)'}`,
                borderLeft: `3px solid ${lost ? accent : 'rgba(100, 200, 120, 0.5)'}`,
                borderRadius: 3,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{
                    fontFamily: 'ui-monospace, monospace',
                    fontSize: 14,
                    fontWeight: 700,
                    color: lost ? accent : '#a0e0a0',
                  }}>{g.res}</span>
                  <span style={{ fontSize: 10, color: '#5a5048' }}>{g.when} ago</span>
                </div>
                <div style={{ fontSize: 12, color: '#d4c8b0', marginTop: 4 }}>{g.opening}</div>
                <div style={{ fontSize: 10, color: '#6a5e50', marginTop: 2, fontFamily: 'ui-monospace, monospace' }}>
                  {g.moves} moves · {g.time}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

window.LobbyScreen = LobbyScreen;
window.TAUNTS = TAUNTS;
window.SAMPLE_MOVES = SAMPLE_MOVES;
window.FEN_MIDGAME = FEN_MIDGAME;
window.FEN_LATE_ATTACK = FEN_LATE_ATTACK;
window.FEN_CHECK = FEN_CHECK;
window.FEN_KILL_ZONE = FEN_KILL_ZONE;
