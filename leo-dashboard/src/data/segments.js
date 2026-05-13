// Legacy export consumed by RuleBuilder's segment dropdown.
export const SEGMENT_SIZE = {
  'All Segments':                      4291,
  'High Affinity, No Recent Purchase': 312,
  'Churn Risk — High Value':           87,
  'New Investors':                     1840,
  'Active Traders':                    678,
};

// Segment definitions are business-configured activation strategies, not dynamic DB queries.
// A public "list segments" API does not exist; these are maintained here as config.
// sampleProfileId points to a real profile to demo the drill-down flow.
export const SEGMENTS = [
  {
    id: 'high-affinity-no-purchase',
    name: 'High Affinity, No Recent Purchase',
    desc: 'In product_recommendations + "No Traded Profiles" segment — high intent, never converted.',
    badgeCls: 'bdg-ok',
    icon: '🎯',
    typeLabel: 'Opportunity',
    typeCls: 'seg-opp',
    apiEndpoint: '/audience/high-affinity',
  },
  {
    id: 'churn-risk-high-value',
    name: 'Churn Risk — High Value',
    desc: 'Portfolio cash_total > 10,000,000 — high-value customers at risk of disengagement.',
    badgeCls: 'bdg-e',
    icon: '⚠️',
    typeLabel: 'Alert',
    typeCls: 'seg-alert',
    apiEndpoint: '/audience/churn-risk',
  },
  {
    id: 'new-investor-onboarding',
    name: 'New Investors',
    desc: 'In "New Investors" CDP segment — highest engagement window for habit formation.',
    badgeCls: 'bdg-c',
    icon: '🌱',
    typeLabel: 'Funnel',
    typeCls: 'seg-funnel',
    apiEndpoint: '/audience/new-investors',
  },
  {
    id: 'active-trader-upsell',
    name: 'Active Traders',
    desc: 'In "Active Traders" CDP segment — frequent traders eligible for Premium tier.',
    badgeCls: 'bdg-p',
    icon: '💎',
    typeLabel: 'Revenue',
    typeCls: 'seg-rev',
    apiEndpoint: '/audience/active-traders',
  },
];
