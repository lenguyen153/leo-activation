import { apiFetch } from './client';

// Fixed watchlist of popular VN tickers to surface in the Audience Pulse view.
// Sorted by viewer count (from the real DB) on load.
const WATCH_TICKERS = ['HPG', 'VNM', 'FPT', 'VCB', 'SSI', 'VHM', 'MWG', 'BID'];

export async function fetchSurgingTickers() {
  const settled = await Promise.allSettled(
    WATCH_TICKERS.map(tk =>
      apiFetch(`/recommendation/interested/${tk}?min_score=0.3`).then(users => ({
        tk,
        count: users.length,
        avgScore: users.length
          ? users.reduce((s, u) => s + u.score, 0) / users.length
          : 0,
      }))
    )
  );
  return settled
    .filter(r => r.status === 'fulfilled')
    .map(r => r.value)
    .sort((a, b) => b.count - a.count);
}
