import { useState, useEffect, useCallback } from 'react';
import { fetchRuns, fetchAffected } from '../../api/campaign';

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

function fmtDuration(start, end) {
  if (!start || !end) return null;
  const ms = new Date(end) - new Date(start);
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60000)}m`;
}

function sentRate(sent, matched) {
  if (!matched) return 0;
  return Math.round((sent / matched) * 100);
}

const STATUS_BADGE = {
  sent:          { cls: 'bdg-ok',  label: 'Sent' },
  failed:        { cls: 'bdg-e',   label: 'Failed' },
  pending_retry: { cls: 'bdg-w',   label: 'Retry' },
};

// ── sub-components ────────────────────────────────────────────────────────────

function StatPill({ value, label, color }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 52 }}>
      <div className="sm sb" style={{ color }}>{value.toLocaleString()}</div>
      <div className="xs dim">{label}</div>
    </div>
  );
}

function DeliveryBadge({ status }) {
  const b = STATUS_BADGE[status] ?? { cls: 'bdg-gy', label: status };
  return <span className={`bdg ${b.cls}`}>{b.label}</span>;
}

function AffectedTable({ ruleId }) {
  const [data,      setData]   = useState(null);
  const [loading,   setLoading] = useState(true);
  const [statusFilter, setFilter] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAffected(ruleId, { status: statusFilter || undefined });
      setData(res);
    } catch {
      setData({ count: 0, profiles: [] });
    } finally {
      setLoading(false);
    }
  }, [ruleId, statusFilter]);

  useEffect(() => { load(); }, [load]);

  return (
    <div style={{ marginTop: 12 }}>
      {/* filter row */}
      <div className="f ac jb mb3">
        <span className="xs sub">{data?.count ?? 0} profiles</span>
        <select
          className="sel"
          style={{ width: 140, fontSize: 11 }}
          value={statusFilter}
          onChange={e => setFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="sent">Sent</option>
          <option value="failed">Failed</option>
          <option value="pending_retry">Retry</option>
        </select>
      </div>

      {loading ? (
        <div className="xs sub" style={{ padding: '12px 0' }}>Loading…</div>
      ) : !data?.profiles?.length ? (
        <div className="xs dim" style={{ padding: '12px 0', textAlign: 'center' }}>
          No delivery records found
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--bdr)' }}>
                {['Name / Email', 'Profile ID', 'Channel', 'Status', 'Sent At'].map(h => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: 'var(--tx-sub)', fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.profiles.map((p, i) => (
                <tr
                  key={`${p.profile_id}-${i}`}
                  style={{ borderBottom: '1px solid var(--bdr)', transition: 'background .1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--s3)'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}
                >
                  <td style={{ padding: '7px 8px' }}>
                    <div className="sm" style={{ color: 'var(--tx)' }}>{p.first_name || '—'}</div>
                    <div className="xs dim trunc" style={{ maxWidth: 180 }}>{p.primary_email || '—'}</div>
                  </td>
                  <td style={{ padding: '7px 8px' }}>
                    <span className="xs" style={{ fontFamily: 'monospace', color: 'var(--tx-sub)' }}>
                      {p.profile_id?.slice(0, 12)}…
                    </span>
                  </td>
                  <td style={{ padding: '7px 8px' }}>
                    <span className="bdg bdg-gy xs">{p.channel}</span>
                  </td>
                  <td style={{ padding: '7px 8px' }}>
                    <DeliveryBadge status={p.delivery_status} />
                  </td>
                  <td style={{ padding: '7px 8px' }}>
                    <span className="xs sub">{fmtTime(p.sent_at)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RunCard({ run }) {
  const [expanded, setExpanded] = useState(false);

  // run_metadata is an array of per-rule stats: [{ rule_id, rule_name, matched, sent, skipped, errored }]
  const rules = Array.isArray(run.run_metadata) ? run.run_metadata : [];
  const duration = fmtDuration(run.started_at, run.finished_at);
  const rate = sentRate(run.sent, run.profiles_matched);

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      {/* run header */}
      <div className="f ac jb mb3">
        <div className="f ac g3">
          <div
            style={{
              width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
              background: run.errored > 0 ? 'var(--warn)' : 'var(--ok)',
              boxShadow: `0 0 6px ${run.errored > 0 ? 'var(--warn)' : 'var(--ok)'}`,
            }}
          />
          <div>
            <div className="sm sb">{fmtTime(run.started_at)}</div>
            <div className="xs dim">
              {rules.length} rule{rules.length !== 1 ? 's' : ''}
              {duration && <> · {duration}</>}
            </div>
          </div>
        </div>

        <div className="f ac g4">
          <StatPill value={run.profiles_matched} label="matched" color="var(--tx-sub)" />
          <StatPill value={run.sent}             label="sent"    color="var(--ok)" />
          <StatPill value={run.skipped}          label="skipped" color="var(--tx-dim)" />
          <StatPill value={run.errored}          label="failed"  color={run.errored > 0 ? 'var(--err)' : 'var(--tx-dim)'} />

          <div className="f ac g2">
            {/* delivery rate bar */}
            <div style={{ width: 60 }}>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${rate}%`, background: 'linear-gradient(90deg,var(--pri),var(--sec))' }} />
              </div>
              <div className="xs dim" style={{ textAlign: 'right', marginTop: 2 }}>{rate}%</div>
            </div>
            <button className="btn btn-g btn-s" onClick={() => setExpanded(e => !e)}>
              {expanded ? 'Hide' : 'View users'}
            </button>
          </div>
        </div>
      </div>

      {/* per-rule chips */}
      {rules.length > 0 && (
        <div className="f g2 fw mb3">
          {rules.map((r, i) => (
            <span key={i} className="bdg bdg-gy xs">
              {r.rule_name || `Rule ${r.rule_id?.slice(0, 8)}`}
              &nbsp;·&nbsp;{r.sent ?? 0} sent
            </span>
          ))}
        </div>
      )}

      {/* affected profiles — shown per rule when there's exactly one rule, else first rule */}
      {expanded && rules.length > 0 && (
        <div style={{ borderTop: '1px solid var(--bdr)', paddingTop: 12 }}>
          {rules.length > 1 && (
            <div className="xs sub mb3">
              Showing users for: <strong>{rules[0].rule_name}</strong>
            </div>
          )}
          <AffectedTable ruleId={rules[0].rule_id} />
        </div>
      )}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export default function OngoingCampaigns() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchRuns(20);
      setData(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div>
      <div className="f ac jb mb5">
        <div>
          <div className="xl sb mb2">Campaign Runs</div>
          <div className="sm sub">Recent executions — click "View users" to see who was reached.</div>
        </div>
        <button className="btn btn-g btn-s" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {loading && !data && (
        <div className="xs sub" style={{ padding: '32px 0', textAlign: 'center' }}>
          Loading runs…
        </div>
      )}

      {error && (
        <div className="card" style={{ borderColor: 'rgba(239,68,68,.3)', color: 'var(--err)', fontSize: 13 }}>
          {error}
        </div>
      )}

      {!loading && data?.runs?.length === 0 && (
        <div className="empty">
          <div className="empty-ic">📭</div>
          <div className="sm sub">No campaign runs yet</div>
          <div className="xs dim">Use the Build tab to create and send a campaign.</div>
        </div>
      )}

      {data?.runs?.map(run => (
        <RunCard key={run.run_id} run={run} />
      ))}
    </div>
  );
}
