import { PROFILES } from '../data/profiles';

export function mockReply(msg) {
  const lo = msg.toLowerCase();

  if (/usr\d+|profile/i.test(lo)) {
    const id = (msg.match(/USR\d+/i) || ['USR001'])[0].toUpperCase();
    const p = PROFILES[id];
    if (p) {
      return `Profile **${id}** — **${p.name}** (${p.segment}).\n\nTop interest: **${p.interests[0]?.tk}** (${Math.round(p.interests[0]?.score * 100)}% affinity). Recommended action: **${p.nba[0]?.action}** via ${p.nba[0]?.channel}.\n\nEstimated open rate for this profile: ~34%.`;
    }
    return `Profile **${id}** not found in CDP. Try USR001, USR002, or USR003.`;
  }
  if (/campaign|preview|reach|launch/i.test(lo)) {
    const n = (200 + Math.floor(Math.random() * 120)).toLocaleString();
    return `Campaign dry-run complete. Estimated reach: **${n} qualified profiles** match current filters.\n\nExpected conversion lift: **+12%** vs. baseline. Optimal send window: **Tuesday 09:00 ICT** (peak engagement).`;
  }
  if (/segment|ltv|high.value|investor/i.test(lo)) {
    return `**High-Value Investors** (312 profiles) have 2.4× higher LTV vs. average.\n\nTop behaviors: stock page views, portfolio checks. Churn risk: **low (8%)**. Recommended channel: Email (38% open rate).`;
  }
  if (/zalo|channel|email|push|facebook/i.test(lo)) {
    return `Channel benchmark across 1,847 active profiles:\n\n• **Zalo OA**: 68% open rate\n• **Email**: 22% open rate\n• **Push**: 41% tap rate\n• **Facebook**: 3.1% CTR\n\nZalo outperforms significantly for this CDP cohort.`;
  }
  if (/churn|risk|inactive/i.test(lo)) {
    return `Churn risk model output (last 30 days):\n\n• **High-Value Investor**: 8% churn risk\n• **New Investor**: 34% churn risk (first-week critical)\n• **Active Trader**: 5% churn risk\n\nRecommend an onboarding re-engagement push for new investors within 72h.`;
  }
  return `Based on current CDP signals, I see strong patterns worth acting on. Would you like me to run a **campaign preview**, drill into a specific **profile**, or compare **channel performance**?`;
}
