import SectionTitle from '../components/ui/SectionTitle';

function ProfileRow({ profile, onSelect }) {
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
          {profile.base_account_id && (
            <div className="xs dim mt1">Account: {profile.base_account_id}</div>
          )}
        </div>
      </div>
      <button className="btn btn-g btn-s" onClick={() => onSelect(profile.profile_id)}>
        View Profile →
      </button>
    </div>
  );
}

export default function SearchResults({ query, results, onSelectProfile, onBack }) {
  return (
    <div>
      <div className="breadcrumb">
        <button onClick={onBack}>← Audience Pulse</button>
        <span className="dim">›</span>
        <span>Search: "{query}"</span>
      </div>

      <div className="mb5">
        <div className="lg sb mb1">Search Results</div>
        <div className="sm sub">
          {results.length} profile{results.length !== 1 ? 's' : ''} matched "{query}"
        </div>
      </div>

      <SectionTitle
        label="Matched Profiles"
        right={<span className="xs sub">email · profile ID · account ID</span>}
      />

      <div className="fc g2 mt3">
        {results.map(p => (
          <ProfileRow
            key={p.profile_id}
            profile={p}
            onSelect={id => onSelectProfile(id, `Search: "${query}"`)}
          />
        ))}
      </div>
    </div>
  );
}
