# Session Handoff — Audience 360 Dashboard

## 1. Goal

Rebuild the **Audience 360** tab from a single profile-search input into a two-level, data-driven interface:

- **Macro view (Audience Pulse / AudienceHub):** Live interest signals across the user base + clickable high-value segment cards.
- **Micro view (ProfileDetail):** Full 360° view of a single profile — affinity radar, AI prescriptions (NBA + NLA), omnichannel event timeline.
- All read views in Audience 360 hit the **production DB** (`PGSQL_DB_HOST_PROD=172.60.1.6`).
- Campaign Engine remains on the **default (UAT) DB** — no prod writes ever.

---

## 2. Current State of the Code

### Navigation state machine (`Audience360.jsx`)

```
hub  →  [search]          →  search-results  →  profile-detail
     →  [ticker card]     →  ticker-profiles →  profile-detail
     →  [segment card]    →  segment-profiles→  profile-detail
```

Back navigation is context-aware: the "← Back" button in `ProfileDetail` returns to whichever list the user came from (search results, ticker list, or segment list).

### Backend — new & changed files

| File | What changed |
|---|---|
| `data_utils/settings.py` | Added `PGSQL_DB_HOST_PROD` field + `pg_dsn_prod` property + `get_pg_connection_prod()` method. Falls back to default host if env var not set. |
| `api/recommendation_system.py` | `get_db()` dependency switched to `get_pg_connection_prod()`. |
| `api/user_events.py` | `_get_pg_connection()` helper switched to `get_pg_connection_prod()`. |
| `api/portfolio.py` | `get_db()` dependency switched to `get_pg_connection_prod()`. |
| `api/audience.py` | **New file.** 4 dedicated audience segment endpoints (see below). |
| `api/handlers.py` | Registered `audience_router` from `api/audience.py`. |

### `api/audience.py` — segment endpoints

| Endpoint | Logic |
|---|---|
| `GET /audience/high-affinity` | `product_recommendations JOIN cdp_profiles WHERE segment = 'No Traded Profiles'`. Up to 200 results. |
| `GET /audience/churn-risk` | `portfolios GROUP BY profile_id HAVING MAX(cash_total) > 10,000,000`, sorted by cash desc. Returns `cash_total` in response. |
| `GET /audience/new-investors` | `cdp_profiles WHERE segments @> 'New Investors'`. |
| `GET /audience/active-traders` | `cdp_profiles WHERE segments @> 'Active Traders'`. |

All 4 use the `AudienceProfileResponse` model (`profile_id`, `primary_email`, optional `cash_total`) and are Redis-cached.

### `api/recommendation_system.py` — added endpoint

`GET /recommendation/segment-profiles?segment=<name>` — exposes the existing private `_get_profiles_for_segment` SQL helper as a public endpoint. Used as a generic fallback for CDP segment name lookups.

### Frontend — new & changed files

| File | Role |
|---|---|
| `src/pages/Audience360.jsx` | Orchestrator. Owns all view state and navigation. 5-state machine: `hub`, `search-results`, `ticker`, `segment`, `profile`. |
| `src/pages/AudienceHub.jsx` | Macro view. Profile search bar + ticker search + live interest grid + segment cards. |
| `src/pages/SearchResults.jsx` | Shows multiple profiles when a portfolio lookup returns >1 match. |
| `src/pages/TickerProfiles.jsx` | Lists all profiles interested in a searched ticker, sorted by affinity score desc. |
| `src/pages/SegmentProfiles.jsx` | Lists profiles for a business segment by calling the correct `/audience/*` endpoint. Churn-risk rows display `cash_total`. |
| `src/pages/ProfileDetail.jsx` | Full profile view: affinity radar (SVG), AI Prescriptions (NBA + NLA), omnichannel timeline. Makes 4 parallel API calls on mount. |
| `src/api/profile.js` | Added `fetchNBA`, `fetchNLA`, `fetchTopEvents`, `searchProfiles` + adapters `adaptNBA`, `adaptNLA`, `adaptEvents`. Updated `adaptProfileData` to be affinity-only. |
| `src/api/pulse.js` | New. `fetchSurgingTickers()` — parallel calls to `/recommendation/interested/{tk}` for a fixed watchlist, returns sorted by real user count. |
| `src/data/segments.js` | SEGMENTS config now has `apiEndpoint` per segment (pointing to `/audience/*`). `SEGMENT_SIZE` kept for `RuleBuilder` dropdown compatibility. |
| `src/data/channels.js` | Extended `EV_CFG` with real `metricName` values from ArangoDB (`ticker-view`, `order-created`, etc.). Added `Web` and `App` to `CH_CFG`. |
| `src/styles/index.css` | Added: `.surge-grid`, `.surge-card`, `.seg-grid`, `.seg-card`, `.seg-opp/alert/funnel/rev`, `.breadcrumb`, `.radar-wrap`, `.prx-card`, `.prx-nba`, `.prx-nla`. |

### Profile search flow

`ProfileSearch` → `GET /portfolio/user?lookup=X&env=prod` matches email, profile_id, OR base_account_id:
- **0 results** → error shown inline in search bar
- **1 result** → goes directly to `ProfileDetail`
- **>1 results** → `SearchResults` list so admin picks the right profile

### ProfileDetail data sources

| Section | Real API | Fallback |
|---|---|---|
| Affinity radar + interests | `GET /recommendation/profile_affinity/{id}` | Mock `PROFILES[id].interests` |
| NBA (Next-Best-Actions) | `GET /recommendation/nba/{id}` | Mock `PROFILES[id].nba` |
| NLA (Next-Likely-Actions) | `GET /recommendation/nla/{id}` | Mock `PROFILES[id].nla` |
| Omnichannel timeline | `GET /user-events/top?profileId=X&topK=10` | Mock `PROFILES[id].events` |
| name, risk, joined, stats | **No API** — always mock for USR001-003, shows raw profile_id for others |

---

## 3. Files Actively Being Edited

**Backend**
- `api/audience.py` — primary new file; segment SQL lives here
- `data_utils/settings.py` — prod DB config
- `api/recommendation_system.py` — prod DB dependency + segment-profiles endpoint

**Frontend**
- `leo-dashboard/src/pages/Audience360.jsx` — state machine
- `leo-dashboard/src/pages/AudienceHub.jsx` — macro view with ticker search
- `leo-dashboard/src/pages/ProfileDetail.jsx` — micro view with SVG radar
- `leo-dashboard/src/api/profile.js` — all profile-related fetchers and adapters
- `leo-dashboard/src/data/segments.js` — segment config + SEGMENT_SIZE

---

## 4. Everything Tried That Failed / Known Issues

### `SEGMENT_SIZE` export removed and broke RuleBuilder
When `segments.js` was rewritten to use the new `SEGMENTS` array format, `SEGMENT_SIZE` was initially not re-exported. `RuleBuilder.jsx` (Campaign Engine) imports `{ SEGMENT_SIZE }` — the Docker build failed with a Vite `not exported` error. Fixed by re-adding `SEGMENT_SIZE` as a plain object derived from the same counts.

### Initial segment profiles used ticker-interest as a proxy
The first implementation approximated "High Affinity" by querying `/recommendation/interested/HPG?min_score=0.6`. This was replaced with dedicated `/audience/*` endpoints that use correct DB joins (`product_recommendations`, `portfolios`, CDP segment name queries).

### Mocked delta/trend data for surge cards
The original design proposed showing `+18.3%` trend deltas for ticker interest. There is no time-series comparison data in the backend — no historical interest score snapshots exist. Removed the delta concept entirely; surge cards now show real user count + avg affinity score from the live DB.

### `_get_profiles_for_segment` was private
The SQL helper and segment-profiles logic existed in `recommendation_system.py` but was not exposed as an endpoint. Added `GET /recommendation/segment-profiles?segment=<name>` to expose it. However, the CDP segment names in the DB (`"Production 1invest Users"`, `"UAT 1invest Users"`) do not map to the business segment names — so this generic endpoint is available but not used by the 4 business segments (they use `/audience/*` instead).

### `fromSegment` / `selectedSeg` prop coupling in ProfileDetail
Early versions passed a full `selectedSeg` object into `ProfileDetail` to build the breadcrumb. This created an implicit coupling between `ProfileDetail` and the segment config shape. Replaced with a simple `backLabel: string` prop — ProfileDetail doesn't need to know anything about what called it.

### Portfolio API was on UAT DB
`portfolio.py` was using `get_pg_connection()` (UAT). Profile search via `GET /portfolio/user` would return UAT-only profiles. Switched to `get_pg_connection_prod()` since the endpoint is read-only.

### Docker rebuild required after every backend change
No volume mounts — code is baked into the image. Any Python file change requires `docker compose up --build api`. Any frontend change requires `docker compose up --build dashboard`.

### Redis cache may serve stale UAT data after prod switch
After switching `recommendation_system.py`, `user_events.py`, and `portfolio.py` to prod, existing Redis cache entries (keyed without a `prod` discriminator) will serve whatever was cached from UAT runs until TTL expires. To get immediate prod data: `docker exec my_redis_cache redis-cli FLUSHDB`.

---

## 5. Next Steps (in priority order)

### 1. Docker rebuild + smoke test
```bash
docker compose up --build api dashboard
docker exec my_redis_cache redis-cli FLUSHDB   # clear stale UAT cache
```
Test the full flow:
- Profile search by email → multi-result list → pick one → ProfileDetail
- Click ticker in surge grid → TickerProfiles list → click profile → ProfileDetail
- Click segment card → SegmentProfiles → click profile → ProfileDetail
- Back-nav from each profile view returns to the correct parent

### 2. Verify segment SQL returns data
The 4 `/audience/*` endpoints depend on:
- `product_recommendations` table having rows in prod
- `portfolios.cash_total > 10,000,000` rows existing
- CDP segment names `"No Traded Profiles"`, `"New Investors"`, `"Active Traders"` matching exactly what is stored in `cdp_profiles.segments[].name` in prod

If any segment returns 0 profiles, check the exact segment name strings in prod:
```sql
SELECT DISTINCT s->>'name' FROM cdp_profiles, jsonb_array_elements(segments) AS s LIMIT 50;
```

### 3. Wire real `name` / `stats` / `joined` for non-demo profiles
Currently, any profile that isn't USR001/002/003 shows `name = profile_id`, `stats = "—"`. The real data exists in the portfolio (`nav`, `cash_total`, `pnl`) and in `cdp_profiles.ext_data`. A `ProfileDetail` enrichment pass could:
- Call `GET /portfolio/accounts?baseAccountId=X` to get real nav/cash/pnl as stats
- Use `primary_email` for display name fallback
- Pull `created_at` from cdp_profiles for the "Joined" date

### 4. Fix orphan campaign rules (pre-existing issue)
`CampaignEngine.jsx` creates a real `campaign_rules` row on every Dry-Run click (status = `active`) and never cleans it up. After preview, archive the rule:
```js
await apiFetch(`/campaigns/rules/${rule_id}/status`, {
  method: 'PATCH',
  body: { status: 'archived' },
});
```

### 5. Delete `dashboard.html` from project root
The old single-file prototype at `/dashboard.html` is fully superseded by `leo-dashboard/`. Safe to delete.

### 6. Add CORS check
If `CORSMiddleware` in `main_app.py` doesn't include the dashboard origin, nginx proxy requests will hit CORS errors in the browser. Verify `allow_origins` includes `"*"` or the dashboard host.
