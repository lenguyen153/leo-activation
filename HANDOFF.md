# Session Handoff — LEO Activation Dashboard

## 1. Goal

Build a high-fidelity React dashboard prototype for the LEO Activation platform that:
- Gives marketing teams a visual interface for the CDP/agentic backend
- Has two primary views: **Audience 360** (profile inspector) and **Campaign Engine** (rule builder + dry-run)
- Has a persistent **LEO Agent chat panel** on the right that talks to the real `POST /chat` endpoint
- Runs as a Docker service alongside the existing backend stack

The dashboard is a *prototype* — not a production UI. The priority is demonstrating the backend capabilities visually, not building a polished product.

---

## 2. Current State of the Code

### What exists

`leo-dashboard/` is a complete, runnable Vite + React 18 project. It is integrated into the root `docker-compose.yml` as the `dashboard` service on port **5173**.

```
leo-dashboard/
├── Dockerfile               # multi-stage: node:20 build → nginx:alpine serve
├── nginx.conf               # proxies /api/* → http://api:8000/ (strips prefix)
├── vite.config.js           # dev proxy: /api/* → http://localhost:8000
├── package.json
├── src/
│   ├── api/                 # ← Real backend integration layer
│   │   ├── client.js        # base apiFetch() — infers GET/POST from body presence
│   │   ├── chat.js          # POST /chat  { prompt } → { answer }
│   │   ├── profile.js       # GET /recommendation/profile_affinity/{id} + adaptProfileData()
│   │   └── campaign.js      # create rule + preview rule (two-step flow)
│   ├── data/                # Mock data (used as fallback when API is unreachable)
│   │   ├── profiles.js      # USR001, USR002, USR003
│   │   ├── channels.js      # CH_CFG, EV_CFG
│   │   ├── segments.js      # SEGMENT_SIZE
│   │   └── chat.js          # CHAT_INIT, SUGGESTIONS
│   ├── utils/mockReply.js   # Keyword-matched fallback responses for chat
│   ├── styles/index.css     # Single global stylesheet (CSS vars + utility classes)
│   ├── components/
│   │   ├── layout/          # Header, AppLayout
│   │   ├── ui/              # Badge, Typing, SectionTitle, EmptyState
│   │   ├── chatbot/         # AgentPanel
│   │   ├── audience/        # ProfileSearch, ProfileCard, StatRow, AffinityChart, NBAList, EventTimeline
│   │   └── campaign/        # RuleBuilder, ChannelSelector, PreviewResult
│   ├── pages/
│   │   ├── Audience360.jsx  # Calls GET /recommendation/profile_affinity/{id}
│   │   └── CampaignEngine.jsx # Calls POST /campaigns/rules → POST /campaigns/rules/{id}/preview
│   └── App.jsx
```

### API wiring status

| UI action | Real endpoint called | Fallback |
|---|---|---|
| Profile search | `GET /recommendation/profile_affinity/{id}` | `PROFILES[id]` mock object |
| Chat message | `POST /chat` `{ prompt: string }` | `mockReply()` keyword matcher |
| Campaign dry-run | `POST /campaigns/rules` → `POST /campaigns/rules/{id}/preview` | Local reach estimate |

### Mock vs real data per profile view

| Field | Source |
|---|---|
| `interest_scores` (affinity chart) | **Real** — from `data.interest_scores` |
| `next_likely_actions` (NBA list) | **Partial real** — from `data.next_likely_actions`; channel/confidence are mock |
| `primary_email` | **Real** |
| `segments` | **Real** (first entry shown as segment badge) |
| `name`, `risk`, `joined`, `stats`, `events` | **Mock only** — not returned by affinity endpoint |

### To run

```bash
# Full stack (API + dashboard + all services)
docker compose up --build

# Dashboard only (with mock data)
cd leo-dashboard && docker compose up --build

# Dev mode with hot reload
cd leo-dashboard && npm install && npm run dev
```

Dashboard available at `http://localhost:5173`.

---

## 3. Files Actively Being Edited (last touched this session)

- `leo-dashboard/src/pages/Audience360.jsx`
- `leo-dashboard/src/pages/CampaignEngine.jsx`
- `leo-dashboard/src/components/chatbot/AgentPanel.jsx`
- `leo-dashboard/src/api/client.js`
- `leo-dashboard/src/api/chat.js`
- `leo-dashboard/src/api/profile.js`
- `leo-dashboard/src/api/campaign.js`
- `leo-dashboard/nginx.conf`
- `leo-dashboard/vite.config.js`
- `leo-dashboard/Dockerfile`
- `docker-compose.yml` (root — added `dashboard` service)

The old `dashboard.html` in the project root is **superseded** and can be deleted once the modular project is verified working.

---

## 4. Everything Tried That Failed / Known Issues

### Channel mapping gap
The backend `CampaignRuleCreate` only accepts `channel: "email" | "zalo" | "push" | "sms"`. The UI allows selecting **Facebook**, which has no backend equivalent. It is currently mapped to `push` as a silent workaround. This should either be removed from the UI or backed by a real Facebook channel integration.

### Campaign preview creates orphan rules
`CampaignEngine.jsx` calls `POST /campaigns/rules` to create a rule, then immediately previews it. Each "Dry-Run" button click inserts a new row in the `campaign_rules` table with `status = 'active'` (the default). There is no cleanup call after preview. Over time this pollutes the table with stale draft rules.

**Fix needed:** Either call `PATCH /campaigns/rules/{id}/status` with `{ status: "archived" }` after preview, or the backend should add a dedicated stateless preview endpoint that doesn't persist.

### NBA data is incomplete from the affinity endpoint
`GET /recommendation/profile_affinity/{id}` returns `next_likely_actions: {ticker: str}` — just the action label per ticker. It does **not** return channel recommendations or confidence scores. The real NBA data (with channel + confidence) lives at `GET /recommendation/nba/{profile_id}` which is not yet called.

### Profile metadata not available from affinity endpoint
`name`, `risk`, `joined`, `stats (events/session/conv/ltv)`, and `events timeline` have no real API source yet. They are always shown from mock data. A real user will see their real `interest_scores` but a fake name/email unless their profile ID happens to match USR001/002/003.

### No end-to-end Docker test was run
The Docker build was written and the `docker-compose.yml` was updated, but a full `docker compose up --build` was not executed to verify the nginx proxy routing works against a live API container.

---

## 5. Next Steps (in priority order)

1. **Verify Docker build end-to-end**
   ```bash
   docker compose up --build dashboard
   # then test: profile search, chat, campaign dry-run
   ```

2. **Wire up real NBA endpoint** (`src/api/profile.js`)
   Add a second call in `Audience360.jsx`:
   ```js
   GET /recommendation/nba/{profile_id}
   // Returns: { next_best_actions: { ticker: { action, channel, confidence_score, reason } } }
   ```
   This gives real `channel` and `confidence_score` for the NBA list cards.

3. **Wire up event timeline** (`src/api/events.js`)
   ```js
   GET /user-events/top?profile_id=X&limit=10
   ```
   Replace mock `events` array with real behavioral events from the CDC pipeline.

4. **Fix orphan campaign rules** (`src/api/campaign.js`)
   After preview, archive the rule:
   ```js
   await apiFetch(`/campaigns/rules/${rule_id}/status`, {
     method: 'PATCH',
     body: { status: 'archived' },
   });
   ```

5. **Delete `dashboard.html`** from project root — it is fully superseded by `leo-dashboard/`.

6. **Add a `CORS` check** — if the API doesn't have `allow_origins=["*"]` or the dashboard's origin, the nginx proxy may still hit CORS errors. Verify in `main_app.py` that `CORSMiddleware` is configured to allow requests from the dashboard.
