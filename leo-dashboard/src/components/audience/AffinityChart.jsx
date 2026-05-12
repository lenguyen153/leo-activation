import SectionTitle from '../ui/SectionTitle';

function scoreColor(score) {
  if (score > 0.8) return 'var(--ok)';
  if (score > 0.6) return 'var(--warn)';
  return 'var(--tx-sub)';
}

export default function AffinityChart({ interests }) {
  return (
    <div className="card mb4">
      <SectionTitle
        label="Interest Affinity"
        right={<span className="bdg bdg-c">Top Stocks</span>}
      />
      <div className="fc g3">
        {interests.map(({ tk, score }) => {
          const pct = Math.round(score * 100);
          const col = scoreColor(score);
          return (
            <div key={tk}>
              <div className="f jb mb2">
                <span className="sm m">{tk}</span>
                <span className="sm" style={{ color: col }}>{pct}%</span>
              </div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{ width: `${pct}%`, background: `linear-gradient(90deg,var(--pri),${col})` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
