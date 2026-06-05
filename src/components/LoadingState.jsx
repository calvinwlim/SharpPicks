import { SPORT_ICONS } from '../constants/index.js';

const PHASES = [
  { key: 'fetching',  label: 'ESPN Slate' },
  { key: 'odds',      label: 'Odds' },
  { key: 'injuries',  label: 'Injuries' },
  { key: 'analyzing', label: 'Analysis' },
];

const PHASE_LABELS = {
  fetching:  'Fetching ESPN game slate...',
  odds:      'Loading live odds...',
  injuries:  'Scanning injury reports...',
  analyzing: 'AI is analyzing...',
};

export default function LoadingState({ message, phase, sport }) {
  const phaseLabel = PHASE_LABELS[phase] || 'Working...';
  const phaseOrder = PHASES.map((p) => p.key);
  const currentIdx = phaseOrder.indexOf(phase);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', gap: 22, padding: 24,
    }}>
      {/* Spinner */}
      <div style={{ position: 'relative' }}>
        <div style={{
          width: 60, height: 60,
          border: '3px solid rgba(255,255,255,0.06)',
          borderTopColor: 'var(--green)',
          borderRadius: '50%',
          animationName: 'spin', animationDuration: '0.75s',
          animationTimingFunction: 'linear', animationIterationCount: 'infinite',
        }} />
        <div style={{
          position: 'absolute', inset: 0, display: 'flex',
          alignItems: 'center', justifyContent: 'center', fontSize: 24,
        }}>
          {SPORT_ICONS[sport] || '📊'}
        </div>
      </div>

      {/* Phase label */}
      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
        letterSpacing: '2px', textTransform: 'uppercase',
        color: 'rgba(0,232,127,0.5)',
      }}>
        {phaseLabel}
      </div>

      {/* Rotating message */}
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--green)',
        animationName: 'blink', animationDuration: '2s',
        animationTimingFunction: 'ease', animationIterationCount: 'infinite',
      }}>
        {message}
      </div>

      {/* Phase progress */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {PHASES.map(({ key, label }, i) => {
          const done   = currentIdx > i;
          const active = currentIdx === i;
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: done || active ? 'var(--green)' : 'rgba(255,255,255,0.1)',
                boxShadow: active ? '0 0 8px var(--green)' : 'none',
              }} />
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 10.5, textTransform: 'uppercase',
                letterSpacing: '0.5px',
                color: done || active ? 'var(--green)' : 'var(--muted)',
              }}>
                {label}
              </span>
              {i < PHASES.length - 1 && (
                <span style={{ color: 'var(--muted)', fontSize: 10 }}>→</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
