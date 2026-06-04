### Tool Registry (`agentic_tools/tools.py`)

All 9 registered tools are explicit — no hidden prompt magic:

- `get_date`, `get_current_weather` — Utilities
- `get_marketing_events`, `get_alert_types` — Data retrieval
- `manage_cdp_segment`, `analyze_segment`, `show_all_segments` — Segment management (operates on Apache AGE graph)
- `activate_channel` — Sends to Email/Zalo OA/Facebook/Mobile Push/Web Push
- `sync_segment_to_db` — Incremental sync from ArangoDB → PostgreSQL

### Activation Channels (`agentic_tools/channels/`)

Strategy-based channel implementations:
- **Email**: SMTP or SendGrid (configured via `EMAIL_PROVIDER` env var)
- **Zalo OA**: Vietnamese OA messaging API
- **Facebook Page**: Messenger/Page API
- **Mobile Push**: Firebase Cloud Messaging (FCM)
- **Web Push**: pywebpush