const STAT_META = [
  { key: 'events',  label: 'Total Events', color: 'var(--pri)' },
  { key: 'session', label: 'Avg. Session',  color: 'var(--sec)' },
  { key: 'conv',    label: 'Conv. Rate',    color: 'var(--ok)' },
  { key: 'ltv',     label: 'Est. LTV',      color: 'var(--warn)' },
];

export default function StatRow({ stats }) {
  return (
    <div className="stats-row mb4">
      {STAT_META.map(({ key, label, color }) => (
        <div key={key} className="card p4">
          <div className="lbl mb2">{label}</div>
          <div className="stat-v" style={{ color }}>{stats[key]}</div>
        </div>
      ))}
    </div>
  );
}
