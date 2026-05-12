import { CH_CFG } from '../../data/channels';

export default function ChannelSelector({ channels, toggle, freqCap, setFreq }) {
  return (
    <div className="card">
      <div className="stitle mb4">Channel Selection</div>

      <div className="ch-grid mb4">
        {Object.entries(CH_CFG).map(([ch, cfg]) => (
          <div
            key={ch}
            className={`ch-chip${channels.includes(ch) ? ' sel' : ''}`}
            onClick={() => toggle(ch)}
          >
            <div style={{ fontSize: 26, marginBottom: 4 }}>{cfg.icon}</div>
            <div className="sm m">{ch}</div>
            {channels.includes(ch) && <div className="xs pri mt2">✓ Selected</div>}
          </div>
        ))}
      </div>

      <div className="fc g3">
        <div>
          <label className="lbl">Frequency Cap</label>
          <select className="sel" value={freqCap} onChange={e => setFreq(e.target.value)}>
            <option>1x per day</option>
            <option>2x per week</option>
            <option>1x per week</option>
            <option>No cap</option>
          </select>
        </div>
        <div>
          <label className="lbl">Schedule</label>
          <input className="inp" type="datetime-local" defaultValue="2026-05-19T09:00" />
        </div>
        <div>
          <label className="lbl">Message Template</label>
          <select className="sel">
            <option>Stock Alert — VNM Spike</option>
            <option>Weekly Market Brief</option>
            <option>Portfolio Performance Update</option>
            <option>Custom (use editor)</option>
          </select>
        </div>
      </div>
    </div>
  );
}
