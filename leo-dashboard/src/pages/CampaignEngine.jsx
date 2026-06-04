import { useState } from 'react';
import { SEGMENT_SIZE } from '../data/segments';
import { previewCampaign } from '../api/campaign';
import RuleBuilder       from '../components/campaign/RuleBuilder';
import ChannelSelector   from '../components/campaign/ChannelSelector';
import PreviewResult     from '../components/campaign/PreviewResult';
import OngoingCampaigns  from '../components/campaign/OngoingCampaigns';
import Typing            from '../components/ui/Typing';

export default function CampaignEngine() {
  const [tab,     setTab]    = useState('build');

  // build tab state
  const [name,     setName]  = useState('Q2 Stock Alert Campaign');
  const [seg,      setSeg]   = useState('High-Value Investor');
  const [trigger,  setTrig]  = useState('page_view');
  const [minLTV,   setLTV]   = useState('1000');
  const [channels, setCh]    = useState(['Email', 'Zalo']);
  const [freqCap,  setFreq]  = useState('1x per day');
  const [preview,  setPrev]  = useState(null);
  const [ruleId,   setRuleId] = useState(null);
  const [running,  setRun]   = useState(false);

  const toggle = (ch) =>
    setCh(p => p.includes(ch) ? p.filter(c => c !== ch) : [...p, ch]);

  const dryRun = async () => {
    setRun(true);
    setPrev(null);

    try {
      const result = await previewCampaign({ name, seg, channels });
      const reach = result.matched_profiles ?? 0;
      const convs = Math.round(reach * 0.184);
      setRuleId(result.rule_id ?? null);
      setPrev({
        reach,
        convs,
        revenue:  `$${(convs * 48).toLocaleString()}`,
        time:     'Tue 2026-05-19, 09:00 ICT',
        conf:     0.88,
        sample:   result.sample_profiles ?? [],
      });
    } catch {
      // API unavailable — fall back to local estimate so the UI stays useful
      const base  = SEGMENT_SIZE[seg] || 500;
      const reach = Math.round(base * (0.65 + channels.length * 0.07));
      const convs = Math.round(reach * 0.184);
      setPrev({
        reach,
        convs,
        revenue: `$${(convs * 48).toLocaleString()}`,
        time:    'Tue 2026-05-19, 09:00 ICT',
        conf:    0.88,
      });
    } finally {
      setRun(false);
    }
  };

  return (
    <div>
      {/* page header */}
      <div className="mb5">
        <div className="xl sb mb2">Campaign Engine</div>
        <div className="sm sub">
          Build audience rules, select channels, preview reach, then send immediately.
        </div>
      </div>

      {/* tab bar */}
      <div className="tab-bar" style={{ marginBottom: 24, marginLeft: -24, marginRight: -24, paddingLeft: 24 }}>
        <button className={`tab${tab === 'build' ? ' on' : ''}`} onClick={() => setTab('build')}>
          Build
        </button>
        <button className={`tab${tab === 'ongoing' ? ' on' : ''}`} onClick={() => setTab('ongoing')}>
          Campaign Runs
        </button>
      </div>

      {/* build tab */}
      {tab === 'build' && (
        <>
          <div className="g2-col mb4">
            <RuleBuilder
              name={name}       setName={setName}
              seg={seg}         setSeg={setSeg}
              trigger={trigger} setTrig={setTrig}
              minLTV={minLTV}   setLTV={setLTV}
            />
            <ChannelSelector
              channels={channels} toggle={toggle}
              freqCap={freqCap}   setFreq={setFreq}
            />
          </div>

          <div className="f jc mb4">
            <button
              className={`btn btn-l ${running ? 'btn-g' : 'btn-ok'}`}
              onClick={dryRun}
              disabled={running || channels.length === 0}
              style={{ minWidth: 300 }}
            >
              {running
                ? <><Typing />&nbsp;Simulating…</>
                : '🚀  Dry-Run / Preview Campaign'}
            </button>
          </div>

          <PreviewResult
            preview={preview}
            name={name}
            channels={channels}
            seg={seg}
            freqCap={freqCap}
            ruleId={ruleId}
          />
        </>
      )}

      {/* ongoing tab */}
      {tab === 'ongoing' && <OngoingCampaigns />}
    </div>
  );
}
