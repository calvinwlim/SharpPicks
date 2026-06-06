import MMAFightCard from './MMAFightCard.jsx';
import { fmtDate } from '../utils/dateUtils.js';

function DataFreshness({ label, time }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--green)' }} />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>
        {label} as of <span style={{ color: 'var(--green)' }}>{time}</span>
      </span>
    </div>
  );
}

function ParlayCard({ parlay }) {
  if (!parlay || !parlay.picks || !parlay.picks.length) return null;
  return (
    <div style={{
      background: 'rgba(74,158,255,0.06)', border: '1px solid rgba(74,158,255,0.2)',
      borderRadius: 12, padding: '14px 18px', marginBottom: 20,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>🎯</span>
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 800,
            letterSpacing: '1.5px', textTransform: 'uppercase', color: '#4a9eff',
          }}>Parlay Suggestion</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {parlay.combined_line && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: 'var(--green)' }}>
              {parlay.combined_line}
            </span>
          )}
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 800, color: 'var(--gold)' }}>
            {parlay.units || 0.5}u
          </span>
          {parlay.risk && (
            <span style={{
              fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
              textTransform: 'uppercase', color: 'var(--muted)',
            }}>{parlay.risk} risk</span>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
        {parlay.picks.map((leg, i) => (
          <span key={i} style={{
            fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 700,
            textTransform: 'uppercase', letterSpacing: '0.3px',
            background: 'rgba(74,158,255,0.12)', color: '#4a9eff',
            border: '1px solid rgba(74,158,255,0.25)',
            padding: '5px 11px', borderRadius: 6,
          }}>
            {i > 0 && <span style={{ color: 'rgba(74,158,255,0.5)', marginRight: 4 }}>+</span>}
            {leg}
          </span>
        ))}
      </div>

      {parlay.reasoning && (
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-3)', lineHeight: 1.65 }}>
          {parlay.reasoning}
        </p>
      )}
    </div>
  );
}

export default function MMAResultsPanel({ result, games, oddsTimestamp, onRegenerate }) {
  if (!result || !result.fights) return null;

  const fights = result.fights || [];

  // Summary stats
  const allMLs   = fights.filter((f) => f.moneyline);
  const allProps  = fights.flatMap((f) => f.props || []);
  const totalUnits = parseFloat(
    [...allMLs.map((f) => parseFloat(f.moneyline.units || 1)),
     ...allProps.map((p) => parseFloat(p.units || 0.5))]
    .reduce((a, b) => a + b, 0).toFixed(1)
  );
  const avgConf = allMLs.length
    ? Math.round(allMLs.reduce((a, f) => a + (f.moneyline.confidence || 70), 0) / allMLs.length)
    : 0;
  const confColor = avgConf >= 75 ? 'var(--green)' : 'var(--gold)';

  return (
    <div style={{ animationName: 'fadeUp', animationDuration: '0.3s', animationFillMode: 'both' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 30, fontWeight: 800,
            textTransform: 'uppercase', letterSpacing: '0.5px', color: '#fff', lineHeight: 1,
          }}>
            {result.event_name || 'UFC Fight Card'}
          </div>
          {result.venue && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)', marginTop: 3 }}>
              {result.venue}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end' }}>
          {[
            { v: fights.length,  l: 'Fights' },
            { v: `${avgConf}%`,  l: 'Avg ML Conf', c: confColor },
            { v: `${totalUnits}u`, l: 'Total Units', c: 'var(--gold)' },
          ].map(({ v, l, c }) => (
            <div key={l} style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 800, color: c || '#fff', lineHeight: 1 }}>{v}</div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 3 }}>{l}</div>
            </div>
          ))}
          <button className="btn-ghost" onClick={onRegenerate}>↺ Regen</button>
        </div>
      </div>

      {/* ── Data freshness + card info ── */}
      <div style={{
        background: 'var(--surface-2)', border: '1px solid var(--border)',
        borderRadius: 10, padding: '10px 16px', marginBottom: 18,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)' }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-3)' }}>
            {fights.length} fight{fights.length !== 1 ? 's' : ''} · ESPN (confirmed) · sorted by confidence
          </span>
        </div>
        {oddsTimestamp ? (
          <DataFreshness label="Odds" time={oddsTimestamp} />
        ) : (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)' }}>
            No live lines — add Odds API key for real-time data
          </span>
        )}
      </div>

      {/* ── Card summary ── */}
      {result.card_summary && (
        <div style={{
          background: 'var(--surface-2)', border: '1px solid var(--border)',
          borderLeft: '3px solid var(--green)', borderRadius: 10,
          padding: '14px 18px', marginBottom: 20,
        }}>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
            letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--green)', marginBottom: 7,
          }}>Card Overview</div>
          <p style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-2)', lineHeight: 1.7 }}>
            {result.card_summary}
          </p>
        </div>
      )}

      {/* ── Parlay suggestion ── */}
      <ParlayCard parlay={result.parlay} />

      {/* ── Fight cards (sorted by ML confidence desc) ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {fights.map((fight, i) => (
          <MMAFightCard
            key={fight.id || i}
            fight={fight}
            bestBet={result.best_bet}
            animDelay={i * 0.08}
          />
        ))}
      </div>

      {fights.length === 0 && (
        <div style={{ textAlign: 'center', padding: 70, color: 'var(--text-3)', fontSize: 15 }}>
          No fights found for this card.
        </div>
      )}
    </div>
  );
}
