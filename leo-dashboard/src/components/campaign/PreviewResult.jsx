import { useState } from 'react';
import { SEGMENT_SIZE } from '../../data/segments';
import { triggerCampaign } from '../../api/campaign';

export default function PreviewResult({ preview, name, channels, seg, freqCap, ruleId }) {
  const [sending,    setSending]    = useState(false);
  const [sendResult, setSendResult] = useState(null);
  const [sendError,  setSendError]  = useState(null);

  if (!preview) return null;

  const convRate = ((preview.convs / preview.reach) * 100).toFixed(1);

  const handleSend = async () => {
    setSending(true);
    setSendResult(null);
    setSendError(null);
    try {
      const res = await triggerCampaign(ruleId);
      setSendResult(res);
    } catch (e) {
      setSendError(e.message || 'Send failed');
    } finally {
      setSending(false);
    }
  };

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

      <div className="f g3 mt4 je fw ac">
        <button className="btn btn-g btn-s">Save Draft</button>

        {sendResult ? (
          <span className="xs ok">
            ✓&nbsp;
            {sendResult.status === 'queued'
              ? 'Campaign queued — check Runs for results'
              : `${sendResult.sent ?? 0} sent · ${sendResult.failed ?? 0} failed · ${sendResult.skipped ?? 0} skipped`}
          </span>
        ) : (
          <button
            className="btn btn-p btn-s"
            onClick={handleSend}
            disabled={sending || !ruleId}
          >
            {sending ? 'Sending…' : '🚀 Send Now'}
          </button>
        )}

        {sendError && (
          <span className="xs" style={{ color: 'var(--err)' }}>{sendError}</span>
        )}
      </div>
    </div>
  );
}
