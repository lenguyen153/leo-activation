### Data Layer (Three Systems)

| System | Technology | Purpose |
|---|---|---|
| **System of Truth** | PostgreSQL + Apache AGE | Customer graph, segments, behavioral edges (Cypher over PostgreSQL) |
| **System of Meaning** | PostgreSQL + PGVector | Semantic embeddings for RAG agent reasoning |
| **Source CDP** | ArangoDB | Upstream customer data; synced to PostgreSQL via Celery workers |

### Database Schema

PostgreSQL schema is in `sql-scripts/schema.sql`. Key tables: `cdp_profiles`, `segment_snapshot`, `segment_snapshot_member`, `marketing_event`, `delivery_log`, `alert_rules`, `news_feed` (with embeddings), `agent_task`. SQLAlchemy ORM models live in `data_models/`.

Performance features: hash partitioning for `marketing_event` (16 partitions), time partitioning for behavioral events, HNSW indexes for PGVector, GIN indexes for JSONB.