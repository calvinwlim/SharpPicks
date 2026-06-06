import { SPORT_ICONS } from '../constants/index.js';

const TEAM_PHASES = [
  { key: 'fetching',  label: 'ESPN Slate' },
  { key: 'odds',      label: 'Game Lines' },
  { key: 'props',     label: 'Prop Lines' },
  { key: 'injuries',  label: 'Rosters' },
  { key: 'analyzing', label: 'AI Analysis' },
];

const MMA_PHASES = [
  { key: 'fetching',  label: 'Fight Card' },
  { key: 'fighters',  label: 'Fighter Profiles' },
  { key: 'odds',      label: 'Fight Odds' },
  { key: 'injuries',  label: 'Fight News' },
  { key: 'analyzing', label: 'AI Analysis' },
];

const PHASE_LABELS = {
  fetching:  'Fetching ESPN data...',
  fighters:  'Fetching fighter profiles...',
  odds:      'Fetching live odds...',
  props:     'Fetching player prop lines...',
  injuries:  'Fetching rosters & injury news...',
  analyzing: 'AI is analyzing...',
};

export default function LoadingState({ message, phase, sport, isMMA }) {
  const phaseList  = isMMA ? MMA_PHASES : TEAM_PHASES;
  const phaseOrder = phaseList.map((p) => p.key);
  const currentIdx = phaseOrder.indexOf(phase);
  const phaseLabel = PHASE_LABELS[phase] || 'Working...';

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', gap: 22, padding: 24,
    }}>
      <div style={{ position: 'relative' }}>
        <div style={{
          width: 60, height: 60,
          border: '3px solid rgba(255,255,255,0.06)',
          borderTopColor: 'var(--green)', borderRadius: '50%',
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

      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
        letterSpacing: '2px', textTransform: 'uppercase',
        color: 'rgba(0,232,127,0.5)',
      }}>
        {phaseLabel}
      </div>

      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--green)',
        animationName: 'blink', animationDuration: '2s',
        animationTimingFunction: 'ease', animationIterationCount: 'infinite',
      }}>
        {message}
      </div>

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center' }}>
        {phaseList.map(({ key, label }, i) => {
          const done   = currentIdx > i;
          const active = currentIdx === i;
          // Hide props step if we jumped past it (it was skipped)
          if (key === 'props' && currentIdx > i) return null;

          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 7, height: 7, borderRadius: '50%',
                background: done || active ? 'var(--green)' : 'rgba(255,255,255,0.1)',
                boxShadow: active ? '0 0 8px var(--green)' : 'none',
              }} />
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase',
                letterSpacing: '0.5px',
                color: done || active ? 'var(--green)' : 'var(--muted)',
              }}>{label}</span>
              {i < phaseList.length - 1 && (
                <span style={{ color: 'var(--muted)', fontSize: 9, marginLeft: 2 }}>→</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
