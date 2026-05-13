import { useState, useEffect } from 'react';
import { PROFILES } from '../data/profiles';
import { CH_CFG, EV_CFG } from '../data/channels';
import {
  fetchProfileAffinity, fetchNBA, fetchNLA, fetchTopEvents,
  adaptProfileData, adaptNBA, adaptNLA, adaptEvents,
} from '../api/profile';
import ProfileCard   from '../components/audience/ProfileCard';
import StatRow       from '../components/audience/StatRow';
import SectionTitle  from '../components/ui/SectionTitle';
import Typing        from '../components/ui/Typing';

// ── Radar Chart ──────────────────────────────────────────────────────────────

function RadarChart({ interests }) {
  if (!interests || interests.length < 3) return null;

  const N = interests.length;
  const cx = 110, cy = 110, R = 75;
  const RINGS = [0.25, 0.5, 0.75, 1.0];

  const toXY = (i, scale) => {
    const angle = (2 * Math.PI * i / N) - Math.PI / 2;
    return { x: cx + scale * R * Math.cos(angle), y: cy + scale * R * Math.sin(angle) };
  };

  const dataPts  = interests.map((it, i) => toXY(i, it.score));
  const polyline = dataPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

  return (
    <svg viewBox="0 0 220 220" style={{ width: '100%', maxWidth: 220, display: 'block', margin: '0 auto' }}>
      {RINGS.map(r => (
        <polygon
          key={r}
          points={interests.map((_, i) => { const p = toXY(i, r); return `${p.x.toFixed(1)},${p.y.toFixed(1)}`; }).join(' ')}
          fill="none" stroke="rgba(148,163,184,0.1)" strokeWidth="1"
        />
      ))}
      {interests.map((_, i) => {
        const end = toXY(i, 1);
        return <line key={i} x1={cx} y1={cy} x2={end.x.toFixed(1)} y2={end.y.toFixed(1)} stroke="rgba(148,163,184,0.15)" strokeWidth="1" />;
      })}
      <polygon points={polyline} fill="rgba(99,102,241,0.18)" stroke="var(--pri)" strokeWidth="2" />
      {dataPts.map((p, i) => (
        <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r="4" fill="var(--pri)" />
      ))}
      {interests.map((it, i) => {
        const lp = toXY(i, 1.28);
        return (
          <text key={i} x={lp.x.toFixed(1)} y={lp.y.toFixed(1)}
            textAnchor="middle" dominantBaseline="middle"
            fill="var(--tx-sub)" fontSize="11" fontWeight="600">
            {it.tk}
          </text>
        );
      })}
    </svg>
  );
}

// ── AI Prescriptions ──────────────────────────────────────────────────────────

const PRI_CLS = { High: 'bdg-e', Medium: 'bdg-w', Low: 'bdg-gy' };

function NBACard({ item }) {
  const ch = CH_CFG[item.channel] || { icon: '📡', color: 'var(--pri)' };
  return (
    <div className="prx-card prx-nba mb2">
      <div className="f ac jb mb2">
        <div className="f ac g2">
          <span style={{ color: ch.color }}>{ch.icon}</span>
          <span className="sm sb">{item.action}</span>
        </div>
        <div className="f ac g2">
          <span className="bdg bdg-gy xs">{item.channel}</span>
          <span className={`bdg ${PRI_CLS[item.pri]} xs`}>{item.pri}</span>
        </div>
      </div>
      {item.ticker && <div className="xs dim mb1">Ticker: {item.ticker}</div>}
      <div className="f ac jb">
        {item.reason && <div className="xs sub" style={{ maxWidth: '75%' }}>{item.reason}</div>}
        <span className="xs" style={{ color: 'var(--pri)', fontWeight: 600, flexShrink: 0 }}>
          {Math.round(item.conf * 100)}% conf
        </span>
      </div>
    </div>
  );
}

function NLACard({ item }) {
  return (
    <div className="prx-card prx-nla mb2">
      <div className="f ac jb">
        <div className="f ac g2">
          <span>🔮</span>
          <div>
            <div className="xs sub">Likely next action</div>
            <div className="sm sb mt1">{item.action}</div>
            {item.ticker && <div className="xs dim mt1">Ticker: {item.ticker}</div>}
          </div>
        </div>
        <span className="xs" style={{ color: 'var(--sec)', fontWeight: 600, flexShrink: 0 }}>
          {Math.round(item.conf * 100)}% prob
        </span>
      </div>
    </div>
  );
}

// ── Omnichannel Timeline ──────────────────────────────────────────────────────

const FALLBACK_EV = { icon: '•', color: 'var(--tx-sub)' };

function OmnichannelTimeline({ events }) {
  if (!events.length) return (
    <div className="xs sub mt3">No recent events found in CDP.</div>
  );
  return (
    <div className="fc">
      {events.map((ev, i) => {
        const cfg = EV_CFG[ev.type] || FALLBACK_EV;
        return (
          <div key={i} className="tl-item">
            <div className="tl-dot" style={{ background: cfg.color }} />
            <div className="f1 mw0">
              <div className="sm" style={{ color: cfg.color }}>{ev.text}</div>
              <div className="f ac g2 mt2">
                <span className="xs dim">{ev.ts}</span>
                <span className="bdg bdg-gy">{cfg.icon} {ev.type}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── ProfileDetail ─────────────────────────────────────────────────────────────

export default function ProfileDetail({ profileId, backLabel, onBack }) {
  const [profile,  setProfile]  = useState(null);
  const [nba,      setNBA]      = useState([]);
  const [nla,      setNLA]      = useState([]);
  const [events,   setEvents]   = useState([]);
  const [loading,  setLoading]  = useState(true);

  useEffect(() => {
    if (!profileId) return;
    setLoading(true);
    const mock = PROFILES[profileId.toUpperCase()] ?? null;

    Promise.allSettled([
      fetchProfileAffinity(profileId),
      fetchNBA(profileId),
      fetchNLA(profileId),
      fetchTopEvents(profileId, 10),
    ]).then(([affRes, nbaRes, nlaRes, evRes]) => {
      // Affinity → base profile shape
      if (affRes.status === 'fulfilled') {
        setProfile(adaptProfileData(affRes.value, mock));
      } else {
        setProfile(mock ? { ...mock, profileId: profileId.toUpperCase() } : null);
      }

      // NBA — real endpoint; fall back to mock.nba if API unavailable
      if (nbaRes.status === 'fulfilled') {
        const adapted = adaptNBA(nbaRes.value);
        setNBA(adapted.length ? adapted : (mock?.nba ?? []));
      } else {
        setNBA(mock?.nba ?? []);
      }

      // NLA — real endpoint; fall back to mock.nla if API unavailable
      if (nlaRes.status === 'fulfilled') {
        setNLA(adaptNLA(nlaRes.value));
      } else {
        setNLA(mock?.nla ?? []);
      }

      // Events — real endpoint; fall back to mock.events if API unavailable
      if (evRes.status === 'fulfilled') {
        const adapted = adaptEvents(evRes.value);
        setEvents(adapted.length ? adapted : (mock?.events ?? []));
      } else {
        setEvents(mock?.events ?? []);
      }
    }).finally(() => setLoading(false));
  }, [profileId]);

  return (
    <div>
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <button onClick={onBack}>
          {backLabel ? `← ${backLabel}` : '← Audience Pulse'}
        </button>
        {profile && <><span className="dim">›</span><span>{profile.name}</span></>}
      </div>

      {loading && (
        <div className="empty">
          <Typing />
          <div className="sm sub">Loading full profile from CDP…</div>
        </div>
      )}

      {!loading && !profile && (
        <div className="empty">
          <div className="empty-ic">🔍</div>
          <div className="sm sub">Profile not found in CDP.</div>
        </div>
      )}

      {!loading && profile && (
        <>
          {/* Identity & Portfolio */}
          <ProfileCard profile={profile} />
          <StatRow stats={profile.stats} />

          <div className="g2-col">
            <div>
              {/* Affinity Radar */}
              <div className="card mb4">
                <SectionTitle
                  label="Affinity Radar"
                  right={<span className="bdg bdg-c">360° View</span>}
                />
                <div className="radar-wrap mt4 mb3">
                  <RadarChart interests={profile.interests} />
                </div>
                {profile.interests.length > 0 && (
                  <div className="fc g2 mt3">
                    {profile.interests.slice(0, 5).map(({ tk, score }) => (
                      <div key={tk} className="f jb xs">
                        <span className="sub">{tk}</span>
                        <span style={{ color: score > 0.8 ? 'var(--ok)' : score > 0.6 ? 'var(--warn)' : 'var(--tx-sub)' }}>
                          {Math.round(score * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* AI Prescriptions */}
              <div className="card">
                <SectionTitle
                  label="AI Prescriptions"
                  right={<span className="bdg bdg-p">LEO Engine</span>}
                />
                {nba.length > 0 && (
                  <div className="mt3">
                    <div className="xs sub mb2" style={{ textTransform: 'uppercase', letterSpacing: '.06em' }}>
                      Next-Best-Actions
                    </div>
                    {nba.map(item => <NBACard key={item.id} item={item} />)}
                  </div>
                )}
                {nla.length > 0 && (
                  <div className="mt3">
                    <div className="xs sub mb2" style={{ textTransform: 'uppercase', letterSpacing: '.06em' }}>
                      Next-Likely-Actions
                    </div>
                    {nla.map(item => <NLACard key={item.id} item={item} />)}
                  </div>
                )}
                {!nba.length && !nla.length && (
                  <div className="xs sub mt3">No AI prescriptions available.</div>
                )}
              </div>
            </div>

            {/* Omnichannel Timeline */}
            <div className="card">
              <SectionTitle
                label="Omnichannel Timeline"
                right={<span className="xs sub">{events.length} events</span>}
              />
              <div className="mt3">
                <OmnichannelTimeline events={events} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
