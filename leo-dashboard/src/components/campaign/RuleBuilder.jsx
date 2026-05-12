import { SEGMENT_SIZE } from '../../data/segments';

export default function RuleBuilder({ name, setName, seg, setSeg, trigger, setTrig, minLTV, setLTV }) {
  return (
    <div className="card">
      <div className="stitle mb4">Rule Builder</div>
      <div className="fc g4">
        <div>
          <label className="lbl">Campaign Name</label>
          <input
            className="inp"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Name your campaign"
          />
        </div>

        <div>
          <label className="lbl">Target Segment</label>
          <select className="sel" value={seg} onChange={e => setSeg(e.target.value)}>
            {Object.keys(SEGMENT_SIZE).map(s => <option key={s}>{s}</option>)}
          </select>
        </div>

        <div>
          <label className="lbl">Trigger Behavior</label>
          <select className="sel" value={trigger} onChange={e => setTrig(e.target.value)}>
            <option value="page_view">Stock Page View</option>
            <option value="trade">Executed Trade</option>
            <option value="search">Search Event</option>
            <option value="inactivity">7-Day Inactivity</option>
            <option value="portfolio_check">Portfolio Check</option>
          </select>
        </div>

        <div>
          <label className="lbl">Min. LTV Filter (USD)</label>
          <input
            className="inp"
            type="number"
            min="0"
            value={minLTV}
            onChange={e => setLTV(e.target.value)}
            placeholder="0"
          />
        </div>

        <div>
          <label className="lbl">A/B Test Split</label>
          <select className="sel">
            <option>No split (100% active)</option>
            <option>50 / 50 holdout</option>
            <option>80 / 20 holdout</option>
            <option>Custom…</option>
          </select>
        </div>
      </div>
    </div>
  );
}
