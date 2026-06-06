import { useState } from 'react';
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import EmptyState from './components/EmptyState.jsx';
import LoadingState from './components/LoadingState.jsx';
import ResultsPanel from './components/ResultsPanel.jsx';
import { fetchGameSlate } from './services/espnApi.js';
import { fetchOdds, fetchPlayerProps } from './services/oddsApi.js';
import { fetchInjuryContext } from './services/injuryApi.js';
import { fetchRosterContext } from './services/rosterApi.js';
import { analyzeSlate } from './services/groqApi.js';
import { getTomorrow, fmtDate } from './utils/dateUtils.js';
import { ENV_GROQ_KEY, ENV_ODDS_KEY } from './config/index.js';
import { ANALYSIS_MESSAGES, PROP_MARKETS } from './constants/index.js';

// Phases: 'idle' | 'fetching' | 'odds' | 'props' | 'injuries' | 'analyzing' | 'done' | 'error'

export default function App() {
  // ── Sport / Date ──────────────────────────────────────────────────────────
  const [sport, setSport] = useState('NBA');
  const [date,  setDate]  = useState(getTomorrow());

  // ── UI controls ──────────────────────────────────────────────────────────
  const [filter,       setFilter]       = useState('All');
  const [notes,        setNotes]        = useState('');
  const [includeProps, setIncludeProps] = useState(false);

  // ── API keys ──────────────────────────────────────────────────────────────
  const [groqKey,   setGroqKey]   = useState(ENV_GROQ_KEY);
  const [oddsKey,   setOddsKey]   = useState(ENV_ODDS_KEY);
  const [oddsUsage, setOddsUsage] = useState(null);

  // ── Async state ──────────────────────────────────────────────────────────
  const [phase,          setPhase]          = useState('idle');
  const [loadingMsg,     setLoadingMsg]     = useState('');
  const [games,          setGames]          = useState(null);
  const [result,         setResult]         = useState(null);
  const [oddsTimestamp,  setOddsTimestamp]  = useState(null);
  const [propsTimestamp, setPropsTimestamp] = useState(null);
  const [error,          setError]          = useState(null);

  const reset = () => {
    setGames(null);
    setResult(null);
    setOddsTimestamp(null);
    setPropsTimestamp(null);
    setError(null);
    setPhase('idle');
  };

  const handleSportChange = (s) => { setSport(s); reset(); };
  const handleDateChange  = (d) => { setDate(d);  reset(); };

  // Whether this sport supports player prop lines from The Odds API
  const sportSupportsProps = !!PROP_MARKETS[sport];

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

      // Step 2: Game-level odds (spread / total / ML)
      let oddsData    = null;
      let propsResult = null;

      if (oddsKey && oddsKey.trim()) {
        setPhase('odds');
        setLoadingMsg('Fetching live game lines...');
        oddsData = await fetchOdds(sport, oddsKey.trim());
        if (oddsData) {
          setOddsTimestamp(oddsData.fetchedAt);
          setOddsUsage(oddsData.games.length + ' games');
        }

        // Step 3: Player prop lines (optional, uses more API quota)
        if (includeProps && sportSupportsProps) {
          setPhase('props');
          setLoadingMsg('Fetching player prop lines...');
          propsResult = await fetchPlayerProps(sport, date, oddsKey.trim());
          if (propsResult) setPropsTimestamp(propsResult.fetchedAt);
        }
      }

      // Step 4: Rosters + injury feed (parallel, non-fatal)
      setPhase('injuries');
      setLoadingMsg('Fetching rosters and injury reports...');
      let rosterContext = '';
      let injuryContext = '';
      try {
        [rosterContext, injuryContext] = await Promise.all([
          fetchRosterContext(sport, fetchedGames),
          fetchInjuryContext(sport, fetchedGames),
        ]);
      } catch {
        // Non-fatal
      }

      // Step 5: Groq analysis
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
          games:         fetchedGames,
          odds:          oddsData,
          propsContext:  propsResult ? propsResult.context : '',
          rosterContext,
          injuryContext,
          notes,
          apiKey:        groqKey,
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

  const isLoading = ['fetching', 'odds', 'props', 'injuries', 'analyzing'].includes(phase);

  return (
    <div className="app">
      <Header
        sport={sport}
        onSportChange={handleSportChange}
        dateLabel={fmtDate(date)}
      />

      <div className="app-body">
        <Sidebar
          date={date}              onDateChange={handleDateChange}
          filter={filter}          onFilterChange={setFilter}
          notes={notes}            onNotesChange={setNotes}
          groqKey={groqKey}        onGroqKeyChange={setGroqKey}
          oddsKey={oddsKey}        onOddsKeyChange={setOddsKey}
          oddsUsage={oddsUsage}
          includeProps={includeProps}
          onIncludePropsChange={setIncludeProps}
          sportSupportsProps={sportSupportsProps}
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
              oddsTimestamp={oddsTimestamp}
              propsTimestamp={propsTimestamp}
              onRegenerate={analyze}
            />
          )}
        </main>
      </div>
    </div>
  );
}
