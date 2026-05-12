import { apiFetch } from './client';

// Maps UI channel labels → backend channel strings
const CHANNEL_MAP = { Email: 'email', Zalo: 'zalo', Facebook: 'push', Push: 'push' };

// Two-step flow:
//   1. POST /campaigns/rules        → { rule_id }
//   2. POST /campaigns/rules/:id/preview → { matched_profiles, sample_profiles }
export async function previewCampaign({ name, seg, channels }) {
  const channel = CHANNEL_MAP[channels[0]] || 'email';

  const { rule_id } = await apiFetch('/campaigns/rules', {
    body: {
      rule_name: name,
      conditions: {
        operator: 'AND',
        conditions: [{ field: 'segments', op: 'contains', value: seg }],
      },
      channel,
      frequency_cap: { cooldown_days: 7, max_per_day: 1 },
      schedule_cron: '0 9 * * 2',
    },
  });

  return apiFetch(`/campaigns/rules/${rule_id}/preview`, { method: 'POST' });
  // Returns: { rule_id, matched_profiles, sample_profiles }
}
