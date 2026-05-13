import { useState, useEffect } from 'react';
import { apiFetch } from '../api/client';
import SectionTitle from '../components/ui/SectionTitle';
import Typing from '../components/ui/Typing';

function ProfileRow({ profile, onSelect }) {
  const pct = Math.round(profile.score * 100);
  const scoreColor = pct > 80 ? 'var(--ok)' : pct > 60 ? 'var(--warn)' : 'var(--tx-sub)';
  const initials = profile.profile_id.slice(-3).toUpperCase();

  return (
    <div className="card2 f ac jb g3">
      <div className="f ac g3">
        <div style={{
          width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
          background: 'linear-gradient(135deg,var(--pri),var(--sec))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 700, color: '#fff',
        }}>
          {initials}
        </div>
        <div>
          <div className="sm sb">{profile.profile_id}</div>
          <div className="xs mt1" style={{ color: scoreColor }}>
            Affinity {pct}%
          </div>
        </div>
      </div>
      <button className="btn btn-g btn-s" onClick={() => onSelect(profile.profile_id)}>
        View Profile →
      </button>
    </div>
  );
}

export default function TickerProfiles({ ticker, onSelectProfile, onBack }) {
  const [profiles, setProfiles] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/recommendation/interested/${ticker}?min_score=0.3`)
      .then(data => setProfiles([...data].sort((a, b) => b.score - a.score)))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [ticker]);

  return (
    <div>
      <div className="breadcrumb">
        <button onClick={onBack}>← Audience Pulse</button>
        <span className="dim">›</span>
        <span>{ticker} Interest</span>
      </div>

      <div className="f ac jb mb5 fw g3">
        <div>
          <div className="lg sb mb1">📊 {ticker} — Interested Profiles</div>
          <div className="sm sub">
            Users with affinity score ≥ 30% for {ticker}, sorted by score descending.
          </div>
        </div>
        {!loading && !error && (
          <span className="bdg bdg-c fs0">{profiles.length} profiles</span>
        )}
      </div>

      <SectionTitle
        label="Profiles by Affinity Score"
        right={loading ? <Typing /> : <span className="xs sub">sorted high → low</span>}
      />

      {loading && <div className="xs sub mt3">Fetching from production CDP…</div>}

      {error && (
        <div className="xs mt3" style={{ color: 'var(--err)' }}>Failed to load: {error}</div>
      )}

      {!loading && !error && profiles.length === 0 && (
        <div className="xs sub mt3">No profiles found for {ticker} at this threshold.</div>
      )}

      {!loading && !error && profiles.length > 0 && (
        <div className="fc g2 mt3">
          {profiles.map(p => (
            <ProfileRow
              key={p.profile_id}
              profile={p}
              onSelect={id => onSelectProfile(id, `${ticker} Interest`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
