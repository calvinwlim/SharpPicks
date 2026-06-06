import { useState } from 'react';
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import EmptyState from './components/EmptyState.jsx';
import LoadingState from './components/LoadingState.jsx';
import ResultsPanel from './components/ResultsPanel.jsx';
import MMAResultsPanel from './components/MMAResultsPanel.jsx';
import { fetchGameSlate } from './services/espnApi.js';
import { fetchOdds, fetchPlayerProps } from './services/oddsApi.js';
import { fetchInjuryContext } from './services/injuryApi.js';
import { fetchRosterContext } from './services/rosterApi.js';
import { fetchFighterContext } from './services/mmaStatsApi.js';
import { analyzeSlate } from './services/groqApi.js';
import { getTomorrow, fmtDate } from './utils/dateUtils.js';
import { ENV_GROQ_KEY, ENV_ODDS_KEY } from './config/index.js';
import { ANALYSIS_MESSAGES, PROP_MARKETS } from './constants/index.js';

// Phases: 'idle' | 'fetching' | 'fighters' | 'odds' | 'props' | 'injuries' | 'analyzing' | 'done' | 'error'

export default function App() {
  const [sport, setSport] = useState('NBA');
  const [date,  setDate]  = useState(getTomorrow());

  const [filter,       setFilter]       = useState('All');
  const [notes,        setNotes]        = useState('');
  const [includeProps, setIncludeProps] = useState(false);

  const [groqKey,   setGroqKey]   = useState(ENV_GROQ_KEY);
  const [oddsKey,   setOddsKey]   = useState(ENV_ODDS_KEY);
  const [oddsUsage, setOddsUsage] = useState(null);

  const [phase,          setPhase]          = useState('idle');
  const [loadingMsg,     setLoadingMsg]     = useState('');
  const [games,          setGames]          = useState(null);
  const [result,         setResult]         = useState(null);
  const [oddsTimestamp,  setOddsTimestamp]  = useState(null);
  const [propsTimestamp, setPropsTimestamp] = useState(null);
  const [error,          setError]          = useState(null);

  const reset = () => {
    setGames(null); setResult(null);
    setOddsTimestamp(null); setPropsTimestamp(null);
    setError(null); setPhase('idle');
  };

  const handleSportChange = (s) => { setSport(s); reset(); };
  const handleDateChange  = (d) => { setDate(d);  reset(); };

  const isMMA              = sport === 'UFC';
  const sportSupportsProps = !!PROP_MARKETS[sport];

  const analyze = async () => {
    reset();
    try {
      // ── Step 1: ESPN game/fight slate ─────────────────────────────────────
      setPhase('fetching');
      setLoadingMsg(isMMA ? 'Fetching fight card from ESPN...' : 'Fetching game schedule from ESPN...');
      const fetchedGames = await fetchGameSlate(sport, date);
      setGames(fetchedGames);

      if (!fetchedGames.length) {
        throw new Error(
          `No ${sport} ${isMMA ? 'events' : 'games'} found on ${fmtDate(date)}. ` +
          'The sport may be out of season, or the event hasn\'t been scheduled yet.'
        );
      }

      // ── Step 2: UFC fighter profiles (MMA only) ───────────────────────────
      let fighterContext = '';
      if (isMMA) {
        setPhase('fighters');
        setLoadingMsg('Fetching fighter profiles from ESPN...');
        try { fighterContext = await fetchFighterContext(fetchedGames); } catch { /* non-fatal */ }
      }

      // ── Step 3: Live odds ─────────────────────────────────────────────────
      let oddsData    = null;
      let propsResult = null;
      if (oddsKey && oddsKey.trim()) {
        setPhase('odds');
        setLoadingMsg('Fetching live odds...');
        oddsData = await fetchOdds(sport, oddsKey.trim());
        if (oddsData) { setOddsTimestamp(oddsData.fetchedAt); setOddsUsage(oddsData.games.length + ' games'); }

        if (!isMMA && includeProps && sportSupportsProps) {
          setPhase('props');
          setLoadingMsg('Fetching player prop lines...');
          propsResult = await fetchPlayerProps(sport, date, oddsKey.trim());
          if (propsResult) setPropsTimestamp(propsResult.fetchedAt);
        }
      }

      // ── Step 4: Rosters + injuries (team sports) / injuries only (MMA) ───
      setPhase('injuries');
      setLoadingMsg(isMMA ? 'Checking fight news...' : 'Fetching rosters and injury reports...');
      let rosterContext = '';
      let injuryContext = '';
      try {
        if (isMMA) {
          injuryContext = await fetchInjuryContext(sport, fetchedGames);
        } else {
          [rosterContext, injuryContext] = await Promise.all([
            fetchRosterContext(sport, fetchedGames),
            fetchInjuryContext(sport, fetchedGames),
          ]);
        }
      } catch { /* non-fatal */ }

      // ── Step 5: AI analysis ───────────────────────────────────────────────
      setPhase('analyzing');
      let msgIdx = 0;
      setLoadingMsg(ANALYSIS_MESSAGES[0]);
      const ticker = setInterval(() => {
        msgIdx = (msgIdx + 1) % ANALYSIS_MESSAGES.length;
        setLoadingMsg(ANALYSIS_MESSAGES[msgIdx]);
      }, 2700);

      try {
        const analysis = await analyzeSlate({
          sport, date,
          games:  fetchedGames,
          odds:   oddsData,
          rosterContext,
          injuryContext,
          propsContext:  propsResult ? propsResult.context : '',
          fighterContext,
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

  const isLoading = ['fetching', 'fighters', 'odds', 'props', 'injuries', 'analyzing'].includes(phase);

  return (
    <div className="app">
      <Header sport={sport} onSportChange={handleSportChange} dateLabel={fmtDate(date)} />

      <div className="app-body">
        <Sidebar
          date={date}             onDateChange={handleDateChange}
          filter={filter}         onFilterChange={setFilter}
          notes={notes}           onNotesChange={setNotes}
          groqKey={groqKey}       onGroqKeyChange={setGroqKey}
          oddsKey={oddsKey}       onOddsKeyChange={setOddsKey}
          oddsUsage={oddsUsage}
          includeProps={includeProps}
          onIncludePropsChange={setIncludeProps}
          sportSupportsProps={sportSupportsProps}
          onAnalyze={analyze}
          loading={isLoading}
          sport={sport}
          isMMA={isMMA}
        />

        <main className="app-main">
          {phase === 'idle' && <EmptyState />}
          {isLoading && <LoadingState message={loadingMsg} phase={phase} sport={sport} isMMA={isMMA} />}

          {phase === 'error' && (
            <div className="error-panel">
              <div className="error-msg">⚠ {error}</div>
              <button className="btn-primary" onClick={analyze}>Try Again</button>
            </div>
          )}

          {phase === 'done' && result && (
            isMMA ? (
              <MMAResultsPanel
                result={result}
                games={games}
                oddsTimestamp={oddsTimestamp}
                onRegenerate={analyze}
              />
            ) : (
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
            )
          )}
        </main>
      </div>
    </div>
  );
}
