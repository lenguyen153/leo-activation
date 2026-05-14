import { useState, useEffect } from 'react';
import { fetchSurgingTickers } from '../api/pulse';
import { apiFetch } from '../api/client';
import { SEGMENTS } from '../data/segments';
import ProfileSearch from '../components/audience/ProfileSearch';
import SectionTitle from '../components/ui/SectionTitle';
import Typing from '../components/ui/Typing';

function SurgeCard({ item, onSelect, highlight }) {
  const pct = Math.min(100, Math.round(item.avgScore * 100));
  return (
    <div
      className="surge-card"
      onClick={() => onSelect(item.tk)}
      role="button" tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect(item.tk)}
      style={highlight ? { borderColor: 'var(--pri)', background: 'var(--pri-g)' } : undefined}
    >
      <div className="f jb ac mb2">
        <span className="surge-tk">{item.tk}</span>
        <span className="bdg bdg-gy xs">{item.count.toLocaleString()} users</span>
      </div>
      <div className="bar-track">
        <div
          className="bar-fill"
          style={{ width: `${pct}%`, background: 'linear-gradient(90deg,var(--pri),var(--sec))' }}
        />
      </div>
      <div className="f jb mt2">
        <span className="xs sub">Avg affinity {pct}%</span>
        <span className="xs pri">View profiles →</span>
      </div>
    </div>
  );
}

function SegmentCard({ seg, onSelect }) {
  return (
    <div className={`seg-card ${seg.typeCls}`} onClick={() => onSelect(seg)} role="button" tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect(seg)}>
      <div className="f ac jb mb3">
        <span className="lg">{seg.icon}</span>
        <span className={`bdg ${seg.badgeCls}`}>{seg.typeLabel}</span>
      </div>
      <div className="sm sb mb2">{seg.name}</div>
      <div className="xs sub mb4">{seg.desc}</div>
      <div className="f ac jb">
        <span className="xs pri">View profiles →</span>
      </div>
    </div>
  );
}

export default function AudienceHub({ onSearch, searchLoading, searchError, onSelectSegment, onSelectTicker }) {
  const [tickers,      setTickers]      = useState([]);
  const [surgeLoading, setSurgeLoading] = useState(true);

  const [tickerQuery,  setTickerQuery]  = useState('');
  const [tickerResult, setTickerResult] = useState(null);   // { tk, count, avgScore }
  const [tickerLoading, setTickerLoading] = useState(false);
  const [tickerError,  setTickerError]  = useState(null);

  useEffect(() => {
    fetchSurgingTickers()
      .then(setTickers)
      .catch(() => setTickers([]))
      .finally(() => setSurgeLoading(false));
  }, []);

  const searchTicker = async () => {
    const tk = tickerQuery.trim().toUpperCase();
    if (!tk) return;
    setTickerLoading(true);
    setTickerResult(null);
    setTickerError(null);
    try {
      const users = await apiFetch(`/recommendation/interested/${tk}?min_score=0.3`);
      const avgScore = users.length
        ? users.reduce((s, u) => s + u.score, 0) / users.length
        : 0;
      setTickerResult({ tk, count: users.length, avgScore });
    } catch (e) {
      setTickerError(`No data for "${tk}".`);
    } finally {
      setTickerLoading(false);
    }
  };

  return (
    <div>
      <div className="mb5">
        <div className="xl sb mb2">Audience 360°</div>
        <div className="sm sub">Search profiles, explore live interest signals, and activate segments.</div>
      </div>

      {/* Profile Search — always visible */}
      <ProfileSearch onSearch={onSearch} loading={searchLoading} error={searchError} />

      {/* Top Interest Signals */}
      <div className="mb5">
        <SectionTitle
          label="Top Interest Signals"
          right={
            surgeLoading
              ? <Typing />
              : <span className="xs sub">{tickers.length} tickers tracked</span>
          }
        />

        {/* Ticker search */}
        <div className="f ac g2 mt3 mb3">
          <input
            className="inp f1"
            placeholder="Search any ticker (e.g. VIC, MSN, TCB…)"
            value={tickerQuery}
            onChange={e => { setTickerQuery(e.target.value); setTickerResult(null); setTickerError(null); }}
            onKeyDown={e => e.key === 'Enter' && searchTicker()}
          />
          <button
            className="btn btn-p fs0"
            onClick={searchTicker}
            disabled={tickerLoading || !tickerQuery.trim()}
          >
            {tickerLoading ? <Typing /> : 'Search'}
          </button>
        </div>

        {/* Search result card */}
        {tickerError && <div className="xs sub mb3">{tickerError}</div>}
        {tickerResult && (
          <div className="mb3">
            <SurgeCard item={tickerResult} onSelect={onSelectTicker} highlight />
          </div>
        )}

        {surgeLoading && <div className="xs sub">Fetching interest counts from CDP…</div>}
        {!surgeLoading && tickers.length === 0 && (
          <div className="xs sub">API unreachable — interest data unavailable.</div>
        )}
        {!surgeLoading && tickers.length > 0 && (
          <div className="surge-grid mt3">
            {tickers.map(item => <SurgeCard key={item.tk} item={item} onSelect={onSelectTicker} />)}
          </div>
        )}
      </div>

      {/* Segment Cards */}
      <div>
        <SectionTitle
          label="High-Value Segments"
          right={<span className="bdg bdg-p">Ready to Activate</span>}
        />
        <div className="seg-grid mt3">
          {SEGMENTS.map(seg => (
            <SegmentCard key={seg.id} seg={seg} onSelect={onSelectSegment} />
          ))}
        </div>
      </div>
    </div>
  );
}
