export const getTomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split('T')[0];
};

export const fmtDate = (s) =>
  new Date(s + 'T12:00:00').toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });

export const fmtDateShort = (s) =>
  new Date(s + 'T12:00:00').toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

// Convert ISO UTC timestamp to Eastern Time display string
export const toEasternTime = (isoString) => {
  if (!isoString) return 'TBD';
  try {
    return new Date(isoString).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: 'America/New_York',
      timeZoneName: 'short',
    });
  } catch {
    return 'TBD';
  }
};

// ESPN uses YYYYMMDD format for date params
export const toESPNDate = (isoDate) => isoDate.replace(/-/g, '');
