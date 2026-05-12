export const PROFILES = {
  USR001: {
    name: 'Nguyen Van An',
    email: 'vanan@example.com',
    segment: 'High-Value Investor',
    risk: 'Medium',
    joined: '2023-04-12',
    stats: { events: 312, session: '4m 22s', conv: '18.4%', ltv: '$4,280' },
    nba: [
      { id: 1, action: 'Send Stock Alert',   ticker: 'VNM', conf: 0.92, channel: 'Email',    pri: 'High' },
      { id: 2, action: 'Promote LEO Fund A', ticker: null,  conf: 0.87, channel: 'Zalo',     pri: 'High' },
      { id: 3, action: 'Re-engagement Push', ticker: null,  conf: 0.74, channel: 'Push',     pri: 'Medium' },
    ],
    interests: [
      { tk: 'VNM', score: 0.93 }, { tk: 'HPG', score: 0.87 },
      { tk: 'VCB', score: 0.76 }, { tk: 'FPT', score: 0.71 }, { tk: 'MWG', score: 0.62 },
    ],
    events: [
      { ts: '2026-05-12 09:14', type: 'page_view',  text: 'Viewed VNM stock detail page' },
      { ts: '2026-05-12 08:55', type: 'click',       text: 'Clicked "Buy" on HPG order book' },
      { ts: '2026-05-11 16:30', type: 'email_open',  text: 'Opened: Weekly Market Brief' },
      { ts: '2026-05-11 14:02', type: 'login',       text: 'App login — Mobile iOS' },
      { ts: '2026-05-11 10:20', type: 'search',      text: 'Searched: "dividend stocks"' },
      { ts: '2026-05-10 09:45', type: 'page_view',   text: 'Viewed VCB stock detail page' },
      { ts: '2026-05-09 15:12', type: 'click',       text: 'Clicked portfolio performance chart' },
    ],
  },
  USR002: {
    name: 'Tran Thi Bich',
    email: 'bich.tran@example.com',
    segment: 'New Investor',
    risk: 'Low',
    joined: '2026-05-01',
    stats: { events: 12, session: '7m 01s', conv: '0%', ltv: '$0' },
    nba: [
      { id: 1, action: 'Onboarding Welcome Email', ticker: null, conf: 0.96, channel: 'Email', pri: 'High' },
      { id: 2, action: 'Tutorial Nudge',           ticker: null, conf: 0.88, channel: 'Push',  pri: 'High' },
    ],
    interests: [
      { tk: 'VCB', score: 0.55 }, { tk: 'BID', score: 0.48 },
    ],
    events: [
      { ts: '2026-05-12 11:05', type: 'page_view', text: 'Viewed Getting Started guide' },
      { ts: '2026-05-12 11:00', type: 'signup',    text: 'Account created via web' },
    ],
  },
  USR003: {
    name: 'Le Minh Khoa',
    email: 'khoa.le@example.com',
    segment: 'Active Trader',
    risk: 'High',
    joined: '2022-11-08',
    stats: { events: 1240, session: '12m 45s', conv: '42.1%', ltv: '$28,600' },
    nba: [
      { id: 1, action: 'Flash Sale Alert',      ticker: 'HPG', conf: 0.94, channel: 'Zalo',     pri: 'High' },
      { id: 2, action: 'Premium Tier Upsell',   ticker: null,  conf: 0.82, channel: 'Email',    pri: 'Medium' },
      { id: 3, action: 'Daily Briefing Push',   ticker: null,  conf: 0.79, channel: 'Push',     pri: 'Medium' },
      { id: 4, action: 'Facebook Re-targeting', ticker: null,  conf: 0.65, channel: 'Facebook', pri: 'Low' },
    ],
    interests: [
      { tk: 'HPG', score: 0.97 }, { tk: 'VNM', score: 0.88 },
      { tk: 'SSI', score: 0.83 }, { tk: 'VHM', score: 0.75 }, { tk: 'FPT', score: 0.68 },
    ],
    events: [
      { ts: '2026-05-12 10:02', type: 'trade',      text: 'Bought 500 HPG @ 28,500 VND' },
      { ts: '2026-05-12 09:55', type: 'click',      text: 'Viewed HPG order book depth' },
      { ts: '2026-05-12 08:01', type: 'login',      text: 'App login — Android' },
      { ts: '2026-05-11 16:45', type: 'trade',      text: 'Sold 200 VNM @ 71,200 VND' },
      { ts: '2026-05-11 14:30', type: 'page_view',  text: 'Viewed portfolio analytics dashboard' },
      { ts: '2026-05-10 11:00', type: 'email_open', text: 'Opened: Market Morning Brief' },
    ],
  },
};
