import SectionTitle from '../ui/SectionTitle';
import { EV_CFG } from '../../data/channels';

const FALLBACK = { icon: '•', color: 'var(--tx-sub)' };

export default function EventTimeline({ events }) {
  return (
    <div className="card">
      <SectionTitle
        label="Event Timeline"
        right={<span className="xs sub">{events.length} events</span>}
      />
      {events.map((ev, i) => {
        const cfg = EV_CFG[ev.type] || FALLBACK;
        return (
          <div key={i} className="tl-item">
            <div className="tl-dot" style={{ background: cfg.color }} />
            <div className="f1 mw0">
              <div className="sm" style={{ color: cfg.color }}>{ev.text}</div>
              <div className="f ac g2 mt2">
                <span className="xs dim">{ev.ts}</span>
                <span className="bdg bdg-gy">{cfg.icon} {ev.type.replace('_', ' ')}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
