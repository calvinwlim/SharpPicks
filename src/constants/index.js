export const SPORTS = ['NBA', 'MLB', 'NFL', 'NHL', 'NCAAB'];

export const BET_FILTERS = ['All', 'Player Prop', 'Game Total', 'Moneyline', 'Spread'];

export const SPORT_ICONS = {
  NBA: '🏀',
  MLB: '⚾',
  NFL: '🏈',
  NHL: '🏒',
  NCAAB: '🎓',
};

// ESPN scoreboard path segments
export const ESPN_SPORT_PATHS = {
  NBA:   'basketball/nba',
  MLB:   'baseball/mlb',
  NFL:   'americanfootball/nfl',
  NHL:   'hockey/nhl',
  NCAAB: 'basketball/mens-college-basketball',
};

// ESPN sport + league for team-level endpoints (injuries/news)
export const ESPN_SPORT_LEAGUES = {
  NBA:   { sport: 'basketball',       league: 'nba' },
  MLB:   { sport: 'baseball',         league: 'mlb' },
  NFL:   { sport: 'americanfootball', league: 'nfl' },
  NHL:   { sport: 'hockey',           league: 'nhl' },
  NCAAB: { sport: 'basketball',       league: 'mens-college-basketball' },
};

// The Odds API sport keys
export const ODDS_SPORT_KEYS = {
  NBA:   'basketball_nba',
  MLB:   'baseball_mlb',
  NFL:   'americanfootball_nfl',
  NHL:   'icehockey_nhl',
  NCAAB: 'basketball_ncaab',
};

export const TAG_COLORS = {
  'Historical Pattern': '#00e87f',
  'Matchup Edge':       '#4a9eff',
  'Home Spot':          '#f0b020',
  'Away Spot':          '#a78bfa',
  'Back to Back':       '#ff4757',
  'Rest Advantage':     '#34d399',
  'Travel Spot':        '#ff6b35',
  'Injury Report':      '#ef4444',
  'Sharp Money':        '#00e87f',
  'Hot Streak':         '#fb923c',
  'Cold Streak':        '#7dd3fc',
  'Playoff Game':       '#f0b020',
  'Weather':            '#93c5fd',
  'Revenge Spot':       '#ec4899',
  'Pace Edge':          '#67e8f9',
  'Line Value':         '#4ade80',
  'Low Volume':         '#c084fc',
  'NRFI Edge':          '#fbbf24',
  'Trap Game':          '#f87171',
  'Umpire Edge':        '#fdba74',
};

export const ANALYSIS_MESSAGES = [
  'Scanning injury reports...',
  'Evaluating matchup edges...',
  'Analyzing H2H patterns...',
  'Checking situational spots...',
  'Computing +EV confidence...',
  'Ranking picks by edge size...',
];
