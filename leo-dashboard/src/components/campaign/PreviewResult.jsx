import { SEGMENT_SIZE } from '../../data/segments';

export default function PreviewResult({ preview, name, channels, seg, freqCap }) {
  if (!preview) return null;

  const convRate = ((preview.convs / preview.reach) * 100).toFixed(1);

  return (
    <div className="prev-box">
      <div className="f ac jb mb4">
        <div>
          <div className="stitle mb2">Preview Results</div>
          <div className="sm sub">{name} • {channels.join(', ')}</div>
        </div>
        <span className="bdg bdg-ok">✓ Dry-Run Complete</span>
      </div>

      <div className="g3-col mb4">
        <div>
          <div className="lbl mb2">Projected Reach</div>
          <div className="big-num">{preview.reach.toLocaleString()}</div>
          <div className="xs sub mt2">of {(SEGMENT_SIZE[seg] || 0).toLocaleString()} in segment</div>
        </div>
        <div>
          <div className="lbl mb2">Est. Conversions</div>
          <div className="big-num" style={{ color: 'var(--ok)' }}>{preview.convs.toLocaleString()}</div>
          <div className="xs sub mt2">{convRate}% conv. rate</div>
        </div>
        <div>
          <div className="lbl mb2">Projected Revenue</div>
          <div className="big-num" style={{ color: 'var(--warn)' }}>{preview.revenue}</div>
          <div className="xs sub mt2">@ $48 avg. order value</div>
        </div>
      </div>

      <hr className="dvdr" />

      <div className="f g5 fw">
        <span className="xs sub">
          📅 Optimal send:&nbsp;
          <span className="sm" style={{ color: 'var(--tx)' }}>{preview.time}</span>
        </span>
        <span className="xs sub">
          📡 Freq cap:&nbsp;
          <span className="sm" style={{ color: 'var(--tx)' }}>{freqCap}</span>
        </span>
        <span className="xs sub">
          🎯 Model confidence:&nbsp;
          <span className="xs ok">{Math.round(preview.conf * 100)}%</span>
        </span>
      </div>

      <div className="f g3 mt4 je fw">
        <button className="btn btn-g btn-s">Save Draft</button>
        <button className="btn btn-p btn-s" style={{ opacity: .5, cursor: 'not-allowed' }}>
          Launch (requires approval)
        </button>
      </div>
    </div>
  );
}
