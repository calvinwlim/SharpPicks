import { useState } from 'react';
import { BET_FILTERS } from '../constants/index.js';

export default function Sidebar({
  date, onDateChange,
  filter, onFilterChange,
  notes, onNotesChange,
  groqKey, onGroqKeyChange,
  oddsKey, onOddsKeyChange,
  oddsUsage,
  onAnalyze,
  loading,
  sport,
}) {
  const [settingsOpen, setSettingsOpen] = useState(!groqKey);

  return (
    <aside style={{
      width: 272, flexShrink: 0, padding: '24px 18px',
      borderRight: '1px solid var(--border)',
      background: 'var(--surface)', display: 'flex', flexDirection: 'column', gap: 24,
      overflowY: 'auto',
    }}>

      {/* ── Date ── */}
      <div>
        <div className="sidebar-label">Slate Date</div>
        <input
          type="date"
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
          style={{ width: '100%', padding: '10px 13px', fontFamily: 'var(--font-mono)', fontSize: 13.5 }}
        />
      </div>

      {/* ── Bet type filter ── */}
      <div>
        <div className="sidebar-label">Bet Type</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {BET_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => onFilterChange(f)}
              style={{
                padding: '9px 12px', borderRadius: 7, border: 'none', textAlign: 'left',
                fontFamily: 'var(--font-body)', fontSize: 14, fontWeight: 500, cursor: 'pointer',
                transition: 'all 0.12s',
                background: filter === f ? 'var(--green-dim)' : 'transparent',
                color:      filter === f ? 'var(--green)' : 'var(--text-3)',
                outline:    filter === f ? '1px solid rgba(0,232,127,0.22)' : '1px solid transparent',
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* ── Context / Notes ── */}
      <div>
        <div className="sidebar-label">Context & Intel</div>
        <textarea
          value={notes}
          onChange={(e) => onNotesChange(e.target.value)}
          rows={5}
          placeholder={
            'Add context to sharpen analysis:\n' +
            '• Injury / lineup news\n' +
            '• Lines you\'re seeing\n' +
            '• Specific props or players\n' +
            '• Weather or venue notes'
          }
          style={{ width: '100%', padding: '11px 13px', fontSize: 13, color: 'var(--text-2)' }}
        />
        <div style={{ marginTop: 7, fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.5 }}>
          Paste injury news or current odds here to improve accuracy.
        </div>
      </div>

      {/* ── API Settings ── */}
      <div>
        <button
          onClick={() => setSettingsOpen((o) => !o)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            width: '100%', background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
          }}
        >
          <span className="sidebar-label" style={{ marginBottom: 0 }}>API Settings</span>
          <span style={{ color: 'var(--muted)', fontSize: 11 }}>{settingsOpen ? '▲' : '▼'}</span>
        </button>

        {settingsOpen && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>

            {/* Groq key */}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 5 }}>
                Groq API Key <span style={{ color: 'var(--red)', fontWeight: 700 }}>*</span>
              </div>
              <input
                type="password"
                value={groqKey}
                onChange={(e) => onGroqKeyChange(e.target.value)}
                placeholder="gsk_..."
                style={{ width: '100%', padding: '9px 11px', fontSize: 12.5, fontFamily: 'var(--font-mono)' }}
              />
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.55 }}>
                Free — no credit card. Sign up at{' '}
                <a href="https://console.groq.com" target="_blank" rel="noreferrer"
                  style={{ color: 'var(--green)', textDecoration: 'none' }}>
                  console.groq.com
                </a>
                {' '}→ API Keys → Create key.
              </div>
            </div>

            {/* Odds API key */}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 5 }}>
                The Odds API Key <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(optional)</span>
              </div>
              <input
                type="password"
                value={oddsKey}
                onChange={(e) => onOddsKeyChange(e.target.value)}
                placeholder="Free key at the-odds-api.com"
                style={{ width: '100%', padding: '9px 11px', fontSize: 12.5, fontFamily: 'var(--font-mono)' }}
              />
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.5 }}>
                Adds consensus lines from 20+ books. Free: 500 req/month.
                {oddsUsage && (
                  <span style={{ color: 'var(--green)', marginLeft: 4 }}>({oddsUsage})</span>
                )}
              </div>
            </div>

          </div>
        )}
      </div>

      {/* ── Free tier notice ── */}
      <div style={{
        background: 'rgba(0,232,127,0.05)', border: '1px solid rgba(0,232,127,0.12)',
        borderRadius: 8, padding: '12px 13px',
      }}>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
          letterSpacing: '1.5px', textTransform: 'uppercase',
          color: 'rgba(0,232,127,0.5)', marginBottom: 6,
        }}>
          100% Free
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.65 }}>
          Game data from ESPN · Injury news from ESPN · AI analysis via Groq (Llama 3.3 70B) · All free, no credit card needed.
        </div>
      </div>

      {/* ── Analyze button ── */}
      <div style={{ marginTop: 'auto' }}>
        <button className="btn-primary" onClick={onAnalyze} disabled={loading} style={{ width: '100%' }}>
          {loading ? 'Analyzing...' : `Analyze ${sport} →`}
        </button>
      </div>

    </aside>
  );
}
