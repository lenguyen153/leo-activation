const RISK_CLS = { Low: 'bdg-ok', Medium: 'bdg-w', High: 'bdg-e' };

export default function ProfileCard({ profile }) {
  const initials = profile.name.split(' ').map(w => w[0]).join('').slice(0, 2);

  return (
    <div className="card mb4 f ac jb g4 fw">
      <div className="f ac g4">
        <div style={{
          width: 50, height: 50, borderRadius: '50%', flexShrink: 0,
          background: 'linear-gradient(135deg,#6366f1,#22d3ee)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 16, fontWeight: 700, color: '#fff',
        }}>
          {initials}
        </div>
        <div>
          <div className="lg sb">{profile.name}</div>
          <div className="sm sub mt2">{profile.email}</div>
        </div>
      </div>

      <div className="f ac g2 fw">
        <span className="bdg bdg-p">{profile.segment}</span>
        <span className={`bdg ${RISK_CLS[profile.risk]}`}>Risk: {profile.risk}</span>
        <span className="xs sub">Joined {profile.joined}</span>
      </div>
    </div>
  );
}
