import { TAG_COLORS } from '../constants/index.js';

function BetTypeBadge({ type }) {
  const t = (type || '').toLowerCase();
  const s =
    t.includes('prop')   ? { bg: 'rgba(74,158,255,0.12)',  c: '#4a9eff',  bd: 'rgba(74,158,255,0.3)' }
    : t.includes('total') ? { bg: 'rgba(167,139,250,0.12)', c: '#a78bfa',  bd: 'rgba(167,139,250,0.3)' }
    : t.includes('money') ? { bg: 'rgba(0,232,127,0.12)',  c: 'var(--green)', bd: 'rgba(0,232,127,0.3)' }
    :                        { bg: 'rgba(255,107,53,0.12)', c: '#ff6b35',  bd: 'rgba(255,107,53,0.3)' };

  return (
    <span style={{
      background: s.bg, color: s.c, border: `1px solid ${s.bd}`,
      fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
      letterSpacing: '1px', padding: '4px 9px', borderRadius: 6,
      textTransform: 'uppercase', flexShrink: 0, lineHeight: '18px',
    }}>
      {type}
    </span>
  );
}

export default function PickCard({ pick, isBest, animDelay = 0 }) {
  const conf    = pick.confidence || 72;
  const confColor = conf >= 80 ? 'var(--green)' : conf >= 70 ? 'var(--gold)' : 'var(--red)';
  const riskColor = pick.risk_level === 'low' ? 'var(--green)' : pick.risk_level === 'high' ? 'var(--red)' : 'var(--gold)';

  return (
    <div style={{
      background: 'var(--surface-2)',
      border: `1px solid ${isBest ? 'var(--gold)' : 'var(--border)'}`,
      borderRadius: 14, overflow: 'hidden', position: 'relative',
      boxShadow: isBest ? '0 0 32px rgba(240,176,32,0.12), 0 4px 24px rgba(0,0,0,0.4)' : '0 2px 16px rgba(0,0,0,0.3)',
      animationName: 'fadeUp', animationDuration: '0.35s',
      animationTimingFunction: 'cubic-bezier(.2,.8,.3,1)',
      animationDelay: `${animDelay}s`, animationFillMode: 'both',
    }}>

      {/* Best bet banner */}
      {isBest && (
        <div style={{
          background: 'linear-gradient(90deg, rgba(240,176,32,0.15), transparent)',
          borderBottom: '1px solid rgba(240,176,32,0.2)',
          padding: '7px 17px',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 12 }}>⭐</span>
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 800,
            letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--gold)',
          }}>Best Bet of the Slate</span>
        </div>
      )}

      {/* Header — pick name + type badge */}
      <div style={{ padding: '16px 18px 12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 8 }}>
          <div style={{
            flex: 1, fontFamily: 'var(--font-display)', fontSize: 21, fontWeight: 800,
            textTransform: 'uppercase', letterSpacing: '0.3px', color: '#fff',
            lineHeight: 1.2,
          }}>
            {pick.pick}
          </div>
          <BetTypeBadge type={pick.bet_type} />
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--text-3)',
        }}>
          <span>{pick.game}</span>
          {pick.game_time && (
            <>
              <span style={{ color: 'var(--muted)' }}>·</span>
              <span>{pick.game_time}</span>
            </>
          )}
        </div>
      </div>

      {/* Confidence bar + units + risk row */}
      <div style={{
        padding: '10px 18px',
        borderTop: '1px solid var(--border)',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        {/* Confidence */}
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: 'var(--muted)' }}>Confidence</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: confColor }}>{conf}%</span>
          </div>
          <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2 }}>
            <div style={{ width: `${conf}%`, height: '100%', background: confColor, borderRadius: 2 }} />
          </div>
        </div>

        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />

        {/* Units */}
        <div style={{ textAlign: 'center', minWidth: 44 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: 'var(--gold)', lineHeight: 1 }}>{pick.units || 1}u</div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 3 }}>Units</div>
        </div>

        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />

        {/* Risk */}
        <div style={{ textAlign: 'center', minWidth: 44 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 800, letterSpacing: '0.5px', textTransform: 'uppercase', color: riskColor, lineHeight: 1 }}>{pick.risk_level || 'Med'}</div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 3 }}>Risk</div>
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: '14px 18px' }}>
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-2)', lineHeight: 1.75, marginBottom: 14 }}>
          {pick.reasoning}
        </p>

        {pick.key_stats && pick.key_stats.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 14 }}>
            {pick.key_stats.slice(0, 4).map((stat, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 9 }}>
                <span style={{ color: 'var(--green)', flexShrink: 0, fontSize: 10, marginTop: 4 }}>▶</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--text)', lineHeight: 1.5 }}>{stat}</span>
              </div>
            ))}
          </div>
        )}

        {pick.tags && pick.tags.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {pick.tags.map((tag, i) => {
              const c = TAG_COLORS[tag] || '#4a9eff';
              return (
                <span key={i} style={{
                  fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
                  letterSpacing: '0.5px', textTransform: 'uppercase', padding: '4px 10px', borderRadius: 5,
                  background: `${c}18`, color: c, border: `1px solid ${c}30`,
                }}>
                  {tag}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
