import SectionTitle from '../ui/SectionTitle';
import { CH_CFG } from '../../data/channels';

const PRI_CLS = { High: 'bdg-e', Medium: 'bdg-w', Low: 'bdg-gy' };

export default function NBAList({ nba }) {
  return (
    <div className="card">
      <SectionTitle
        label="Next-Best Actions"
        right={<span className="bdg bdg-p">NBA Engine</span>}
      />
      <div className="fc g3">
        {nba.map(({ id, action, ticker, conf, channel, pri }) => {
          const chColor = CH_CFG[channel]?.color || 'var(--pri)';
          return (
            <div key={id} className="card2 f ac jb g3">
              <div className="f ac g3 mw0">
                <div className="ring" style={{ color: chColor, borderColor: chColor }}>
                  {Math.round(conf * 100)}%
                </div>
                <div className="mw0">
                  <div className="sm m trunc">{action}</div>
                  {ticker && <div className="xs dim mt2">Ticker: {ticker}</div>}
                </div>
              </div>
              <div className="f ac g2 fs0">
                <span className="bdg bdg-gy">{CH_CFG[channel]?.icon} {channel}</span>
                <span className={`bdg ${PRI_CLS[pri]}`}>{pri}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
