import { useState } from 'react';
import { searchProfiles } from '../api/profile';
import AudienceHub     from './AudienceHub';
import SearchResults   from './SearchResults';
import TickerProfiles  from './TickerProfiles';
import SegmentProfiles from './SegmentProfiles';
import ProfileDetail   from './ProfileDetail';

// view: 'hub' | 'search-results' | 'ticker' | 'segment' | 'profile'

export default function Audience360() {
  const [view,           setView]           = useState('hub');
  const [searchQuery,    setSearchQuery]    = useState('');
  const [searchResults,  setSearchResults]  = useState([]);
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [selectedSeg,    setSelectedSeg]    = useState(null);
  const [profileId,      setProfileId]      = useState(null);
  const [backLabel,      setBackLabel]      = useState(null);
  const [searchLoading,  setSearchLoading]  = useState(false);
  const [searchError,    setSearchError]    = useState(null);

  // ── Navigation helpers ──────────────────────────────────────────────────────

  const goHub = () => {
    setView('hub');
    setSelectedTicker(null);
    setSelectedSeg(null);
    setProfileId(null);
    setBackLabel(null);
    setSearchResults([]);
    setSearchError(null);
  };

  const goTicker  = () => { setView('ticker');  setProfileId(null); setBackLabel(null); };
  const goSegment = () => { setView('segment'); setProfileId(null); setBackLabel(null); };
  const goSearch  = () => { setView('search-results'); setProfileId(null); setBackLabel(null); };

  // ── Entry points ────────────────────────────────────────────────────────────

  const handleSearch = async (query) => {
    if (!query.trim()) return;
    setSearchLoading(true);
    setSearchError(null);
    setSearchQuery(query);

    try {
      const results = await searchProfiles(query.trim());

      if (results.length === 0) {
        setSearchError(`No profiles found for "${query}".`);
      } else if (results.length === 1) {
        // Single match — go straight to profile detail
        setProfileId(results[0].profile_id);
        setBackLabel(null);
        setSelectedTicker(null);
        setSelectedSeg(null);
        setView('profile');
      } else {
        // Multiple matches — let the admin pick
        setSearchResults(results);
        setSelectedTicker(null);
        setSelectedSeg(null);
        setView('search-results');
      }
    } catch {
      setSearchError(`Lookup failed for "${query}". Check the API connection.`);
    } finally {
      setSearchLoading(false);
    }
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

  // ── Back destination from ProfileDetail ─────────────────────────────────────

  const profileBack = selectedTicker
    ? goTicker
    : selectedSeg
    ? goSegment
    : searchResults.length > 1
    ? goSearch
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

  if (view === 'search-results') {
    return (
      <SearchResults
        query={searchQuery}
        results={searchResults}
        onSelectProfile={openProfile}
        onBack={goHub}
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
      searchError={searchError}
      onSelectTicker={openTicker}
      onSelectSegment={openSegment}
    />
  );
}
