import { SPORTS, SPORT_ICONS } from '../constants/index.js';

export default function Header({ sport, onSportChange, dateLabel }) {
  return (
    <header style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 28px', height: 60,
      borderBottom: '1px solid var(--border)',
      background: 'rgba(8,12,20,0.97)',
      position: 'sticky', top: 0, zIndex: 50,
      backdropFilter: 'blur(12px)',
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 8, background: 'var(--green)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: 22, color: '#000',
        }}>S</div>
        <div>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 800,
            letterSpacing: '0.5px', textTransform: 'uppercase', color: '#fff', lineHeight: 1,
          }}>
            SHARP<span style={{ color: 'var(--green)' }}>EDGE</span>
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 9,
            color: 'var(--muted)', letterSpacing: '2px', textTransform: 'uppercase', marginTop: 2,
          }}>
            AI SPORTS ANALYSIS
          </div>
        </div>
      </div>

      {/* Sport tabs */}
      <div style={{
        display: 'flex', gap: 3,
        background: 'var(--surface-2)', padding: 4,
        borderRadius: 10, border: '1px solid var(--border)',
      }}>
        {SPORTS.map((s) => (
          <button
            key={s}
            onClick={() => onSportChange(s)}
            style={{
              padding: '6px 14px', borderRadius: 7, border: 'none',
              fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 700,
              letterSpacing: '0.8px', textTransform: 'uppercase',
              cursor: 'pointer', transition: 'all 0.15s',
              background: sport === s ? 'var(--green)' : 'transparent',
              color:      sport === s ? '#000' : 'var(--muted)',
            }}
            onMouseEnter={(e) => { if (sport !== s) { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; e.currentTarget.style.color = 'var(--text-2)'; } }}
            onMouseLeave={(e) => { if (sport !== s) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--muted)'; } }}
          >
            {SPORT_ICONS[s]} {s}
          </button>
        ))}
      </div>

      {/* Date label */}
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--muted)' }}>
        {dateLabel}
      </div>
    </header>
  );
}
