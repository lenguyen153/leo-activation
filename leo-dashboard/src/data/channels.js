export const CH_CFG = {
  Email:    { icon: '✉️',  color: '#6366f1' },
  Zalo:     { icon: '💬',  color: '#22d3ee' },
  Facebook: { icon: '👥',  color: '#3b82f6' },
  Push:     { icon: '🔔',  color: '#f59e0b' },
  Web:      { icon: '🌐',  color: '#22c55e' },
  App:      { icon: '📱',  color: '#a855f7' },
};

// EV_CFG covers both legacy mock event types and real metricName values from ArangoDB.
export const EV_CFG = {
  // Mock / legacy types
  page_view:  { icon: '👁',  color: 'var(--pri)' },
  click:      { icon: '🖱',  color: 'var(--sec)' },
  email_open: { icon: '✉️',  color: 'var(--ok)' },
  login:      { icon: '🔑',  color: 'var(--warn)' },
  search:     { icon: '🔍',  color: 'var(--tx-sub)' },
  signup:     { icon: '⭐',  color: 'var(--ok)' },
  trade:      { icon: '📈',  color: 'var(--pur)' },
  // Real metricName values from cdp_trackingevent
  'order-created':        { icon: '📈', color: 'var(--pur)' },
  'group-order-created':  { icon: '📈', color: 'var(--pur)' },
  'order-preview':        { icon: '🖱', color: 'var(--sec)' },
  'order-canceled':       { icon: '❌', color: 'var(--err)' },
  'order-quitted':        { icon: '⏪', color: 'var(--warn)' },
  'ticker-view':          { icon: '👁', color: 'var(--pri)' },
  'watchlist-add':        { icon: '⭐', color: 'var(--ok)' },
  'watchlist-view':       { icon: '📋', color: 'var(--tx-sub)' },
};
