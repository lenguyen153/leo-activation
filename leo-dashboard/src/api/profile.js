import { apiFetch } from './client';

// GET /recommendation/profile_affinity/{id}
// Returns: { profile_id, primary_email, raw_scores, interest_scores, next_likely_actions, segments }
export async function fetchProfileAffinity(profileId) {
  return apiFetch(`/recommendation/profile_affinity/${profileId}`);
}

// Merges real API data onto a mock profile shape so the UI always has all fields.
// Real fields: interest_scores, next_likely_actions, primary_email, segments
// Mock fallback fields: name, risk, joined, stats, events
export function adaptProfileData(data, mock) {
  if (!data?.profile_id) return mock ?? null;

  const interests = Object.entries(data.interest_scores || {})
    .map(([tk, score]) => ({ tk, score }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 6);

  const nba = Object.entries(data.next_likely_actions || {}).map(([ticker, action], i) => ({
    id: i + 1,
    action,
    ticker,
    conf: data.interest_scores?.[ticker] ?? 0.75,
    channel: mock?.nba?.[i]?.channel ?? 'Email',
    pri: i === 0 ? 'High' : i < 3 ? 'Medium' : 'Low',
  }));

  return {
    name:     mock?.name     ?? data.profile_id,
    email:    data.primary_email ?? mock?.email ?? '—',
    segment:  data.segments?.[0] ?? mock?.segment ?? 'Unknown',
    risk:     mock?.risk     ?? 'Unknown',
    joined:   mock?.joined   ?? '—',
    stats:    mock?.stats    ?? { events: '—', session: '—', conv: '—', ltv: '—' },
    events:   mock?.events   ?? [],
    interests: interests.length ? interests : (mock?.interests ?? []),
    nba:       nba.length    ? nba          : (mock?.nba      ?? []),
  };
}
