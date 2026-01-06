# ⚙️ Data Workers & Automation Engine

This module contains the background workers responsible for the heavy lifting of the LEO CDP platform. 
It uses **Celery** (orchestration) and **Redis** (broker) to handle data synchronization, AI embedding generation, and campaign execution asynchronously.

## 🚀 Capabilities

1. **🔄 Data Sync (ArangoDB → PostgreSQL)**
* Runs incrementally every **15 minutes**.
* Fetches modified documents from the ArangoDB Source.
* Upserts data into the PostgreSQL Warehouse while preserving schema flexibility via JSONB.
* Maintains strict Multi-tenant isolation.


2. **🧠 AI Embeddings (Vectorization)**
* Monitors the `embedding_job` queue in PostgreSQL.
* Generates vector embeddings (e.g., via OpenAI/HuggingFace) for:
* **Marketing Events:** For semantic search and recommendation.
* **CDP Profiles:** For audience lookalike modeling and clustering.


* Updates the `vector` columns in Postgres automatically.


3. **📢 Campaign Activation**
* Triggers scheduled marketing campaigns.
* Handles audience segmentation queries at runtime.
* Dispatches execution events to delivery channels (Email, SMS, etc.).


---

## 🔧 Configuration

Update `.env` file (or strictly ensure these variables are loaded in your environment):

```ini
# --- Broker Settings ---
REDIS_URL=redis://localhost:6379/0

# --- Database Connections ---
# Target (Warehouse)
DB_HOST=localhost
DB_NAME=leo_cdp
DB_USER=postgres
DB_PASSWORD=secret

# Source (Raw Data)
ARANGO_HOST=http://localhost:8529
ARANGO_DB=leo_cdp_source
ARANGO_USER=root
ARANGO_PASSWORD=secret

# --- System Defaults ---
DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000000

```

---

## 🏃 Usage

You need to run two separate processes for the system to function correctly.

### 1. Start the Task Scheduler (Beat)

The scheduler is responsible for triggering periodic tasks (like the 15-minute sync).

```bash
# Run from inside the 'data-workers' directory
celery -A celery_app beat --loglevel=info

```

### 2. Start the Worker Nodes

The workers execute the actual logic (Syncing, Embedding, Campaigning).

```bash
# Run from inside the 'data-workers' directory
# You can scale this by running multiple instances or adding --concurrency=4
celery -A celery_app worker --loglevel=info

```

---

## 📂 Task Reference

### `tasks.sync_profiles_task`

* **Trigger:** Scheduled (Every 15 mins).
* **Action:** Queries ArangoDB for `profiles` modified since `last_sync_time`. Upserts them into Postgres `cdp_profiles`.

### `tasks.process_embeddings_task`

* **Trigger:** Database Trigger (Postgres `NOTIFY`) or Scheduled Polling (Every 1 min).
* **Action:** Reads from `embedding_job` table.
* **Logic:**
1. Fetches text content from `marketing_event` or `cdp_profiles`.
2. Calls Embedding API (e.g., OpenAI `text-embedding-3-small`).
3. Writes the vector back to the `embedding` column.
4. Updates job status to `completed`.
 
 


### `tasks.start_campaign_task`

* **Trigger:** Scheduled (Based on `marketing_event.start_at`).
* **Action:** 1.  Loads the Target Audience Segment for the campaign.
2.  Resolves profile IDs.
3.  Pushes entry events to the delivery system.

---

## 🧪 Manual Testing (Python Shell)

You can manually trigger tasks to test without waiting for the schedule:

```python
from tasks import sync_profiles_task, process_embeddings_task

# Force a generic data sync immediately
sync_profiles_task.delay()

# Force processing of pending embedding jobs
process_embeddings_task.delay()

```

## 🔍 Monitoring

* **Logs:** Check `stdout` of the worker terminal for real-time success/fail logs.
* **Redis:** Keys `leo_cdp:last_sync_time` store the checkpoint state.