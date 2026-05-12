import { useState } from 'react';
import { PROFILES } from '../data/profiles';
import { fetchProfileAffinity, adaptProfileData } from '../api/profile';
import ProfileSearch   from '../components/audience/ProfileSearch';
import ProfileCard     from '../components/audience/ProfileCard';
import StatRow         from '../components/audience/StatRow';
import AffinityChart   from '../components/audience/AffinityChart';
import NBAList         from '../components/audience/NBAList';
import EventTimeline   from '../components/audience/EventTimeline';
import EmptyState      from '../components/ui/EmptyState';
import Typing          from '../components/ui/Typing';

export default function Audience360() {
  const [pid,     setPid]   = useState(null);
  const [profile, setP]     = useState(null);
  const [loading, setLoad]  = useState(false);

  const search = async (id) => {
    setLoad(true);
    setP(null);
    setPid(id);

    const mock = PROFILES[id.toUpperCase()] ?? null;

    try {
      const data = await fetchProfileAffinity(id);
      setP(adaptProfileData(data, mock));
    } catch {
      // API unreachable or returned an error — fall back to mock data
      setP(mock);
    } finally {
      setLoad(false);
    }
  };

  return (
    <div>
      <div className="mb5">
        <div className="xl sb mb2">Audience 360°</div>
        <div className="sm sub">
          Inspect customer profiles, interest affinity scores, and behavioral timelines in real-time.
        </div>
      </div>

      <ProfileSearch onSearch={search} loading={loading} />

      {loading && (
        <div className="empty">
          <Typing />
          <div className="sm sub">Fetching profile from CDP…</div>
        </div>
      )}

      {!loading && pid && !profile && (
        <EmptyState
          icon="🔍"
          title="Profile not found"
          subtitle={`No record for "${pid}" in CDP. Try USR001, USR002, or USR003.`}
        />
      )}

      {!loading && profile && (
        <>
          <ProfileCard profile={profile} />
          <StatRow stats={profile.stats} />
          <div className="g2-col">
            <div>
              <AffinityChart interests={profile.interests} />
              <NBAList nba={profile.nba} />
            </div>
            <EventTimeline events={profile.events} />
          </div>
        </>
      )}

      {!loading && !pid && (
        <EmptyState
          icon="👤"
          title="Enter a Profile ID above"
          subtitle="Inspect NBA scores, stock affinity, and behavioral events for any CDP customer."
        />
      )}
    </div>
  );
}
