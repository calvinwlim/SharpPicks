import { useState, Component } from 'react';

// Catches render errors so a bad odds payload can't produce a black screen
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(err) { console.error('[VisualizationPanel] render error:', err); }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-3)', marginBottom: 14 }}>
            Display error: {this.state.error.message}
          </div>
          <button className="btn-primary" onClick={() => { this.setState({ error: null }); this.props.onRetry?.(); }}>
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import EmptyState from './components/EmptyState.jsx';
import LoadingState from './components/LoadingState.jsx';
import VisualizationPanel from './components/VisualizationPanel.jsx';
import MMAVisualizationPanel from './components/MMAVisualizationPanel.jsx';
import ResultsPanel from './components/ResultsPanel.jsx';
import MMAResultsPanel from './components/MMAResultsPanel.jsx';
import { fetchGameSlate } from './services/espnApi.js';
import { fetchOdds, fetchPlayerProps } from './services/oddsApi.js';
import { fetchInjuryContext } from './services/injuryApi.js';
import { fetchRosterContext } from './services/rosterApi.js';
import { fetchFighterData } from './services/mmaStatsApi.js';
import { analyzeSlate } from './services/groqApi.js';
import { getTomorrow, fmtDate } from './utils/dateUtils.js';
import { ENV_GROQ_KEY, ENV_ODDS_KEY, ENV_RAPIDAPI_KEY } from './config/index.js';
import { ANALYSIS_MESSAGES, PROP_MARKETS } from './constants/index.js';

/**
 * Two-phase flow:
 * Phase 1 — VISUALIZE (no AI): fetch all data, display it so user understands matchups
 * Phase 2 — AI PICKS: user reviews data, clicks "Generate AI Picks", Groq analyzes
 *
 * Phases:
 *  idle → fetching → fighters? → odds → props? → injuries → visualized
 *  visualized → analyzing → done
 *  any → error
 */

export default function App() {
  // ── Sport / Date ──────────────────────────────────────────────────────────
  const [sport, setSport] = useState('NBA');
  const [date,  setDate]  = useState(getTomorrow());

  // ── UI controls ──────────────────────────────────────────────────────────
  const [filter,       setFilter]       = useState('All');
  const [notes,        setNotes]        = useState('');
  const [includeProps, setIncludeProps] = useState(false);

  // ── API keys ──────────────────────────────────────────────────────────────
  const [groqKey,     setGroqKey]     = useState(ENV_GROQ_KEY);
  const [oddsKey,     setOddsKey]     = useState(ENV_ODDS_KEY);
  const [rapidApiKey, setRapidApiKey] = useState(ENV_RAPIDAPI_KEY);
  const [oddsUsage,   setOddsUsage]   = useState(null);

  // ── Phase ─────────────────────────────────────────────────────────────────
  const [phase,      setPhase]      = useState('idle');
  const [loadingMsg, setLoadingMsg] = useState('');
  const [error,      setError]      = useState(null);

  // ── Phase 1 results (visualization data) ─────────────────────────────────
  const [vizGames,          setVizGames]          = useState(null);
  const [vizOddsData,       setVizOddsData]       = useState(null);
  const [vizOddsTimestamp,  setVizOddsTimestamp]  = useState(null);
  const [vizPropsTimestamp, setVizPropsTimestamp] = useState(null);
  const [vizFighterProfiles,setVizFighterProfiles]= useState({});
  const [vizInjuryContext,  setVizInjuryContext]  = useState('');

  // ── Stored for AI call (built during visualize) ───────────────────────────
  const [storedFighterContext, setStoredFighterContext] = useState('');
  const [storedRosterContext,  setStoredRosterContext]  = useState('');
  const [storedPropsResult,    setStoredPropsResult]    = useState(null);

  // ── Phase 2 results (AI picks) ────────────────────────────────────────────
  const [aiResult, setAiResult] = useState(null);

  const isMMA              = sport === 'UFC';
  const sportSupportsProps = !!PROP_MARKETS[sport];

  const resetAll = () => {
    setVizGames(null); setVizOddsData(null); setVizOddsTimestamp(null);
    setVizPropsTimestamp(null); setVizFighterProfiles({});
    setVizInjuryContext(''); setStoredFighterContext('');
    setStoredRosterContext(''); setStoredPropsResult(null);
    setAiResult(null); setError(null); setPhase('idle');
  };

  const handleSportChange = (s) => { setSport(s); resetAll(); };
  const handleDateChange  = (d) => { setDate(d);  resetAll(); };

  // ── PHASE 1: Visualize (no AI) ────────────────────────────────────────────
  const visualize = async () => {
    resetAll();

    try {
      // Step 1: ESPN game/fight slate
      setPhase('fetching');
      setLoadingMsg(isMMA ? 'Fetching UFC fight card...' : 'Fetching game schedule from ESPN...');
      const fetchedGames = await fetchGameSlate(sport, date);

      if (!fetchedGames.length) {
        throw new Error(
          `No ${sport} ${isMMA ? 'events' : 'games'} found on ${fmtDate(date)}. ` +
          'The sport may be out of season or the event hasn\'t been scheduled yet.'
        );
      }
      setVizGames(fetchedGames);

      // Step 2 (UFC): Fighter profiles — needed for physical comparison bars
      let fighterContext  = '';
      let fighterProfiles = {};
      if (isMMA) {
        setPhase('fighters');
        setLoadingMsg('Fetching fighter profiles...');
        try {
          const data = await fetchFighterData(fetchedGames, rapidApiKey);
          fighterContext  = data.context;
          fighterProfiles = data.profiles;
          setVizFighterProfiles(fighterProfiles);
          setStoredFighterContext(fighterContext);
        } catch { /* non-fatal */ }
      }

      // Step 3: Live odds (optional)
      let oddsData    = null;
      let propsResult = null;
      if (oddsKey && oddsKey.trim()) {
        setPhase('odds');
        setLoadingMsg('Fetching live odds...');
        oddsData = await fetchOdds(sport, oddsKey.trim());
        if (oddsData) {
          setVizOddsData(oddsData);
          setVizOddsTimestamp(oddsData.fetchedAt);
          setOddsUsage(oddsData.games.length + ' games');
        }

        if (!isMMA && includeProps && sportSupportsProps) {
          setPhase('props');
          setLoadingMsg('Fetching player prop lines...');
          propsResult = await fetchPlayerProps(sport, date, oddsKey.trim());
          if (propsResult) {
            setVizPropsTimestamp(propsResult.fetchedAt);
            setStoredPropsResult(propsResult);
          }
        }
      }

      // Step 4: Rosters + injuries
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
          setStoredRosterContext(rosterContext);
        }
        setVizInjuryContext(injuryContext);
      } catch { /* non-fatal */ }

      setPhase('visualized');

    } catch (err) {
      setError(err.message || 'Failed to load data. Please try again.');
      setPhase('error');
    }
  };

  // ── PHASE 2: Generate AI Picks ────────────────────────────────────────────
  const generatePicks = async () => {
    if (!vizGames) return;
    setAiResult(null);
    setError(null);
    setPhase('analyzing');

    let msgIdx = 0;
    setLoadingMsg(ANALYSIS_MESSAGES[0]);
    const ticker = setInterval(() => {
      msgIdx = (msgIdx + 1) % ANALYSIS_MESSAGES.length;
      setLoadingMsg(ANALYSIS_MESSAGES[msgIdx]);
    }, 2700);

    try {
      // For UFC, limit AI to main card fights to stay within TPM limits
      const gamesForAI = isMMA && vizGames.length > 6
        ? vizGames.slice(-6)   // last 6 = main card + co-main + main event
        : vizGames;

      const analysis = await analyzeSlate({
        sport,
        date,
        games:         gamesForAI,
        odds:          vizOddsData,
        rosterContext: storedRosterContext,
        injuryContext: vizInjuryContext,
        propsContext:  storedPropsResult ? storedPropsResult.context : '',
        fighterContext: storedFighterContext,
        notes,
        apiKey:        groqKey,
      });
      setAiResult(analysis);
      setPhase('done');
    } catch (err) {
      setError(err.message || 'AI analysis failed. Please try again.');
      setPhase('error');
    } finally {
      clearInterval(ticker);
    }
  };

  const isLoadingVisualize = ['fetching', 'fighters', 'odds', 'props', 'injuries'].includes(phase);
  const isLoadingAI        = phase === 'analyzing';
  const isLoading          = isLoadingVisualize || isLoadingAI;

  return (
    <div className="app">
      <Header sport={sport} onSportChange={handleSportChange} dateLabel={fmtDate(date)} />

      <div className="app-body">
        <Sidebar
          date={date}             onDateChange={handleDateChange}
          filter={filter}         onFilterChange={setFilter}
          notes={notes}           onNotesChange={setNotes}
          groqKey={groqKey}         onGroqKeyChange={setGroqKey}
          oddsKey={oddsKey}         onOddsKeyChange={setOddsKey}
          rapidApiKey={rapidApiKey} onRapidApiKeyChange={setRapidApiKey}
          oddsUsage={oddsUsage}
          includeProps={includeProps}
          onIncludePropsChange={setIncludeProps}
          sportSupportsProps={sportSupportsProps}
          phase={phase}
          onVisualize={visualize}
          loading={isLoading}
          sport={sport}
          isMMA={isMMA}
        />

        <main className="app-main">
          {/* Idle */}
          {phase === 'idle' && <EmptyState />}

          {/* Loading */}
          {isLoading && (
            <LoadingState
              message={loadingMsg}
              phase={phase}
              sport={sport}
              isMMA={isMMA}
            />
          )}

          {/* Error */}
          {phase === 'error' && (
            <div className="error-panel">
              <div className="error-msg">⚠ {error}</div>
              <div style={{ display: 'flex', gap: 10 }}>
                <button className="btn-primary" onClick={visualize}>Try Again</button>
              </div>
            </div>
          )}

          {/* Visualization phase */}
          {phase === 'visualized' && vizGames && (
            isMMA ? (
              <ErrorBoundary key={`viz-${vizGames.length}-${vizOddsData ? 'odds' : 'no-odds'}`} onRetry={visualize}>
                <MMAVisualizationPanel
                  games={vizGames}
                  fighterProfiles={vizFighterProfiles}
                  oddsData={vizOddsData}
                  oddsTimestamp={vizOddsTimestamp}
                  onGeneratePicks={generatePicks}
                  loading={false}
                />
              </ErrorBoundary>
            ) : (
              <VisualizationPanel
                games={vizGames}
                oddsData={vizOddsData}
                injuryContext={vizInjuryContext}
                sport={sport}
                date={date}
                oddsTimestamp={vizOddsTimestamp}
                onGeneratePicks={generatePicks}
                loading={false}
              />
            )
          )}

          {/* AI picks — fallback if result missing */}
          {phase === 'done' && !aiResult && (
            <div className="error-panel">
              <div className="error-msg">⚠ Analysis returned no data. Please try again.</div>
              <button className="btn-primary" onClick={generatePicks}>Retry Analysis</button>
            </div>
          )}

          {/* AI picks phase */}
          {phase === 'done' && aiResult && (
            isMMA ? (
              <MMAResultsPanel
                result={aiResult}
                games={vizGames}
                oddsTimestamp={vizOddsTimestamp}
                propsTimestamp={vizPropsTimestamp}
                onRegenerate={generatePicks}
                onRevisualize={visualize}
              />
            ) : (
              <ResultsPanel
                result={aiResult}
                games={vizGames}
                filter={filter}
                sport={sport}
                date={date}
                oddsTimestamp={vizOddsTimestamp}
                propsTimestamp={vizPropsTimestamp}
                onRegenerate={generatePicks}
                onRevisualize={visualize}
              />
            )
          )}
        </main>
      </div>
    </div>
  );
}
