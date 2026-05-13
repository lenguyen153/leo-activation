import { useState } from 'react';
import AudienceHub     from './AudienceHub';
import TickerProfiles  from './TickerProfiles';
import SegmentProfiles from './SegmentProfiles';
import ProfileDetail   from './ProfileDetail';

// view: 'hub' | 'ticker' | 'segment' | 'profile'

export default function Audience360() {
  const [view,          setView]          = useState('hub');
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [selectedSeg,   setSelectedSeg]   = useState(null);
  const [profileId,     setProfileId]     = useState(null);
  const [backLabel,     setBackLabel]     = useState(null);  // breadcrumb label shown in ProfileDetail
  const [searchLoading, setSearchLoading] = useState(false);

  // ── Navigation helpers ──────────────────────────────────────────────────────

  const goHub = () => {
    setView('hub');
    setSelectedTicker(null);
    setSelectedSeg(null);
    setProfileId(null);
    setBackLabel(null);
  };

  const goTicker = () => {
    setView('ticker');
    setProfileId(null);
    setBackLabel(null);
  };

  const goSegment = () => {
    setView('segment');
    setProfileId(null);
    setBackLabel(null);
  };

  // ── Entry points ────────────────────────────────────────────────────────────

  const handleSearch = (id) => {
    setProfileId(id);
    setBackLabel(null);
    setSelectedTicker(null);
    setSelectedSeg(null);
    setView('profile');
  };

  const openTicker = (tk) => {
    setSelectedTicker(tk);
    setSelectedSeg(null);
    setView('ticker');
  };

  const openSegment = (seg) => {
    setSelectedSeg(seg);
    setSelectedTicker(null);
    setView('segment');
  };

  const openProfile = (id, label = null) => {
    setProfileId(id);
    setBackLabel(label);
    setView('profile');
  };

  // ── Determine back destination from ProfileDetail ──────────────────────────

  const profileBack = selectedTicker
    ? goTicker
    : selectedSeg
    ? goSegment
    : goHub;

  // ── Render ──────────────────────────────────────────────────────────────────

  if (view === 'profile') {
    return (
      <ProfileDetail
        profileId={profileId}
        backLabel={backLabel}
        onBack={profileBack}
      />
    );
  }

  if (view === 'ticker' && selectedTicker) {
    return (
      <TickerProfiles
        ticker={selectedTicker}
        onSelectProfile={openProfile}
        onBack={goHub}
      />
    );
  }

  if (view === 'segment' && selectedSeg) {
    return (
      <SegmentProfiles
        segment={selectedSeg}
        onSelectProfile={openProfile}
        onBack={goHub}
      />
    );
  }

  return (
    <AudienceHub
      onSearch={handleSearch}
      searchLoading={searchLoading}
      onSelectTicker={openTicker}
      onSelectSegment={openSegment}
    />
  );
}
