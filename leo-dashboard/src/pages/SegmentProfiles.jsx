import { useState, useEffect } from 'react';
import { apiFetch } from '../api/client';
import SectionTitle from '../components/ui/SectionTitle';
import Typing from '../components/ui/Typing';

function fmt(n) {
  return new Intl.NumberFormat('vi-VN').format(n);
}

function ProfileRow({ profile, isChurnRisk, onSelect }) {
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
          {profile.primary_email && (
            <div className="xs sub mt1">{profile.primary_email}</div>
          )}
          {isChurnRisk && profile.cash_total != null && (
            <div className="xs mt1" style={{ color: 'var(--warn)' }}>
              Cash: {fmt(profile.cash_total)} VND
            </div>
          )}
        </div>
      </div>
      <button className="btn btn-g btn-s" onClick={() => onSelect(profile.profile_id)}>
        View Profile →
      </button>
    </div>
  );
}

export default function SegmentProfiles({ segment, onSelectProfile, onBack }) {
  const [profiles, setProfiles] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);

  const isChurnRisk = segment.id === 'churn-risk-high-value';

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(segment.apiEndpoint)
      .then(setProfiles)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [segment.apiEndpoint]);

  return (
    <div>
      <div className="breadcrumb">
        <button onClick={onBack}>← Audience Pulse</button>
        <span className="dim">›</span>
        <span>{segment.name}</span>
      </div>

      <div className="f ac jb mb5 fw g3">
        <div>
          <div className="lg sb mb1">{segment.icon} {segment.name}</div>
          <div className="sm sub">{segment.desc}</div>
        </div>
        <span className={`bdg ${segment.badgeCls} fs0`}>{segment.typeLabel}</span>
      </div>

      <SectionTitle
        label="Matched Profiles"
        right={
          loading
            ? <Typing />
            : <span className="xs sub">{profiles.length} profiles</span>
        }
      />

      {loading && <div className="xs sub mt3">Fetching profiles from production CDP…</div>}

      {error && (
        <div className="xs mt3" style={{ color: 'var(--err)' }}>
          Failed to load: {error}
        </div>
      )}

      {!loading && !error && profiles.length === 0 && (
        <div className="xs sub mt3">No profiles matched this segment.</div>
      )}

      {!loading && !error && profiles.length > 0 && (
        <div className="fc g2 mt3">
          {profiles.map(p => (
            <ProfileRow
              key={p.profile_id}
              profile={p}
              isChurnRisk={isChurnRisk}
              onSelect={id => onSelectProfile(id, segment.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
