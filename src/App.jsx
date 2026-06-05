import { useState } from 'react';
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import EmptyState from './components/EmptyState.jsx';
import LoadingState from './components/LoadingState.jsx';
import ResultsPanel from './components/ResultsPanel.jsx';
import { fetchGameSlate } from './services/espnApi.js';
import { fetchOdds } from './services/oddsApi.js';
import { fetchInjuryContext } from './services/injuryApi.js';
import { fetchRosterContext } from './services/rosterApi.js';
import { analyzeSlate } from './services/groqApi.js';
import { getTomorrow, fmtDate } from './utils/dateUtils.js';
import { ENV_GROQ_KEY, ENV_ODDS_KEY } from './config/index.js';
import { ANALYSIS_MESSAGES } from './constants/index.js';

// Phases: 'idle' | 'fetching' | 'odds' | 'injuries' | 'analyzing' | 'done' | 'error'

export default function App() {
  // ── Sport / Date ──────────────────────────────────────────────────────────
  const [sport, setSport] = useState('NBA');
  const [date,  setDate]  = useState(getTomorrow());

  // ── UI controls ──────────────────────────────────────────────────────────
  const [filter, setFilter] = useState('All');
  const [notes,  setNotes]  = useState('');

  // ── API keys ──────────────────────────────────────────────────────────────
  const [groqKey,   setGroqKey]   = useState(ENV_GROQ_KEY);
  const [oddsKey,   setOddsKey]   = useState(ENV_ODDS_KEY);
  const [oddsUsage, setOddsUsage] = useState(null);

  // ── Async state ──────────────────────────────────────────────────────────
  const [phase,      setPhase]      = useState('idle');
  const [loadingMsg, setLoadingMsg] = useState('');
  const [games,      setGames]      = useState(null);
  const [result,     setResult]     = useState(null);
  const [error,      setError]      = useState(null);

  const reset = () => {
    setGames(null);
    setResult(null);
    setError(null);
    setPhase('idle');
  };

  const handleSportChange = (s) => { setSport(s); reset(); };
  const handleDateChange  = (d) => { setDate(d);  reset(); };

  // ── Main analysis flow ────────────────────────────────────────────────────
  const analyze = async () => {
    reset();

    try {
      // Step 1: ESPN game slate
      setPhase('fetching');
      setLoadingMsg('Fetching game schedule from ESPN...');
      const fetchedGames = await fetchGameSlate(sport, date);
      setGames(fetchedGames);

      if (!fetchedGames.length) {
        throw new Error(
          `No ${sport} games found on ${fmtDate(date)}. ` +
          'The sport may be out of season, or games haven\'t been scheduled yet for that date.'
        );
      }

      // Step 2: Live odds (optional)
      let oddsData = null;
      if (oddsKey && oddsKey.trim()) {
        setPhase('odds');
        setLoadingMsg('Fetching live odds from The Odds API...');
        oddsData = await fetchOdds(sport, oddsKey.trim());
        if (oddsData) setOddsUsage(oddsData.length + ' games with odds');
      }

      // Step 3: ESPN rosters + injury/news feed (free, non-fatal, run in parallel)
      setPhase('injuries');
      setLoadingMsg('Fetching rosters and injury reports...');
      let rosterContext  = '';
      let injuryContext  = '';
      try {
        [rosterContext, injuryContext] = await Promise.all([
          fetchRosterContext(sport, fetchedGames),
          fetchInjuryContext(sport, fetchedGames),
        ]);
      } catch {
        // Non-fatal — continue without enrichment data
      }

      // Step 4: Groq analysis
      setPhase('analyzing');
      let msgIdx = 0;
      setLoadingMsg(ANALYSIS_MESSAGES[0]);
      const ticker = setInterval(() => {
        msgIdx = (msgIdx + 1) % ANALYSIS_MESSAGES.length;
        setLoadingMsg(ANALYSIS_MESSAGES[msgIdx]);
      }, 2700);

      try {
        const analysis = await analyzeSlate({
          sport,
          date,
          games:  fetchedGames,
          odds:   oddsData,
          rosterContext,
          injuryContext,
          notes,
          apiKey: groqKey,
        });
        setResult(analysis);
        setPhase('done');
      } finally {
        clearInterval(ticker);
      }

    } catch (err) {
      setError(err.message || 'Analysis failed. Please try again.');
      setPhase('error');
    }
  };

  const isLoading = ['fetching', 'odds', 'injuries', 'analyzing'].includes(phase);

  return (
    <div className="app">
      <Header
        sport={sport}
        onSportChange={handleSportChange}
        dateLabel={fmtDate(date)}
      />

      <div className="app-body">
        <Sidebar
          date={date}            onDateChange={handleDateChange}
          filter={filter}        onFilterChange={setFilter}
          notes={notes}          onNotesChange={setNotes}
          groqKey={groqKey}      onGroqKeyChange={setGroqKey}
          oddsKey={oddsKey}      onOddsKeyChange={setOddsKey}
          oddsUsage={oddsUsage}
          onAnalyze={analyze}
          loading={isLoading}
          sport={sport}
        />

        <main className="app-main">
          {phase === 'idle' && <EmptyState />}

          {isLoading && (
            <LoadingState message={loadingMsg} phase={phase} sport={sport} />
          )}

          {phase === 'error' && (
            <div className="error-panel">
              <div className="error-msg">⚠ {error}</div>
              <button className="btn-primary" onClick={analyze}>Try Again</button>
            </div>
          )}

          {phase === 'done' && result && (
            <ResultsPanel
              result={result}
              games={games}
              filter={filter}
              sport={sport}
              date={date}
              onRegenerate={analyze}
            />
          )}
        </main>
      </div>
    </div>
  );
}
