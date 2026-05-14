import { apiFetch } from './client';

// ── Fetchers ────────────────────────────────────────────────────────────────

export async function fetchProfileAffinity(profileId) {
  return apiFetch(`/recommendation/profile_affinity/${profileId}`);
}

export async function fetchNBA(profileId) {
  return apiFetch(`/recommendation/nba/${profileId}`);
}

export async function fetchNLA(profileId) {
  return apiFetch(`/recommendation/nla/${profileId}`);
}

export async function fetchTopEvents(profileId, topK = 10) {
  return apiFetch(`/user-events/top?profileId=${encodeURIComponent(profileId)}&topK=${topK}`);
}

// GET /portfolio/user?lookup=X&env=prod
// Returns all profiles matching email, profile_id, or base_account_id.
export async function searchProfiles(lookup) {
  return apiFetch(`/portfolio/user?lookup=${encodeURIComponent(lookup)}&env=prod`);
}

// ── Adapters ────────────────────────────────────────────────────────────────

// Adapts /recommendation/profile_affinity response to a UI-ready profile shape.
// Fields not provided by the API (name, risk, joined, stats) fall back to mock.
export function adaptProfileData(data, mock) {
  if (!data?.profile_id) return mock ?? null;

  const interests = Object.entries(data.interest_scores || {})
    .map(([tk, score]) => ({ tk, score }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 8);

  return {
    profileId: data.profile_id,
    name:      mock?.name    ?? data.profile_id,
    email:     data.primary_email ?? mock?.email ?? '—',
    segment:   data.segments?.[0] ?? mock?.segment ?? 'Unknown',
    risk:      mock?.risk    ?? 'Unknown',
    joined:    mock?.joined  ?? '—',
    stats:     mock?.stats   ?? { events: '—', session: '—', conv: '—', ltv: '—' },
    interests: interests.length ? interests : (mock?.interests ?? []),
  };
}

// Adapts /recommendation/nba response → list of NBA cards for the UI.
export function adaptNBA(data) {
  return Object.entries(data?.next_best_actions || {}).map(([ticker, d], i) => ({
    id: i + 1,
    action: d.action,
    ticker,
    conf: d.confidence_score,
    channel: d.channel,
    reason: d.reason,
    pri: i === 0 ? 'High' : i < 2 ? 'Medium' : 'Low',
  }));
}

// Adapts /recommendation/nla response → list of NLA cards for the UI.
export function adaptNLA(data) {
  return Object.entries(data?.next_likely_actions || {}).map(([ticker, d], i) => ({
    id: i + 1,
    action: d.action,
    ticker,
    conf: d.confidence_score,
  }));
}

// Metric name → human-readable text builder.
const EV_TEXT = {
  'order-created':       ids => `Placed order: ${ids[0] || ''}`,
  'group-order-created': ids => `Group order: ${ids[0] || ''}`,
  'order-preview':       ids => `Previewed order: ${ids[0] || ''}`,
  'order-canceled':      ids => `Cancelled order: ${ids[0] || ''}`,
  'order-quitted':       ids => `Abandoned order: ${ids[0] || ''}`,
  'ticker-view':         ids => `Viewed ${ids[0] || 'ticker'} detail page`,
  'watchlist-add':       ids => `Added ${ids[0] || 'ticker'} to watchlist`,
  'watchlist-view':      ()  => 'Viewed watchlist',
  'search':              ids => ids[0] ? `Searched: ${ids[0]}` : 'Performed search',
};

function fmtTs(ts) {
  if (!ts) return '—';
  const ms = ts > 1e11 ? ts : ts * 1000;
  return new Date(ms).toLocaleString('en-GB', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

// Adapts /user-events/top response → list of timeline events for the UI.
export function adaptEvents(rawEvents) {
  return (rawEvents || []).map(ev => {
    const ids = ev.instrumentIds || [];
    const textFn = EV_TEXT[ev.metricName] ?? (ids => `${ev.metricName}${ids[0] ? ` — ${ids[0]}` : ''}`);
    return {
      ts:   fmtTs(ev.createdAt?.[0]),
      type: ev.metricName,
      text: textFn(ids),
    };
  });
}
