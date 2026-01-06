import json
import logging
from datetime import datetime, timezone
import redis
from celery import shared_task
from database import get_pg_connection, get_arango_db
import os

# Setup Logger
logger = logging.getLogger(__name__)

# Redis for storing the "Last Sync Timestamp" state
redis_client = redis.from_url(os.getenv("REDIS_URL"))
LAST_SYNC_KEY = "leo_cdp:last_sync_time"
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID")

@shared_task
def sync_profiles_task():
    """
    Incremental Sync: Fetches updated profiles from ArangoDB and Upserts to Postgres.
    """
    logger.info("Starting ArangoDB -> PGSQL Sync...")
    
    # 1. Get Last Sync Time from Redis (or default to epoch if first run)
    last_sync_ts = redis_client.get(LAST_SYNC_KEY)
    if last_sync_ts:
        last_sync_ts = last_sync_ts.decode('utf-8')
    else:
        last_sync_ts = "1970-01-01T00:00:00Z"

    # Capture current time for the next checkpoint
    current_run_time = datetime.now(timezone.utc).isoformat()

    # 2. Fetch Data from ArangoDB (Incremental)
    # Assuming your Arango collection is 'profiles' and has an 'updated_at' field
    arango_db = get_arango_db()
    aql_query = """
    FOR doc IN profiles
        FILTER doc.updated_at >= @last_sync
        LIMIT 1000
        RETURN doc
    """
    
    # Execute AQL query
    cursor = arango_db.aql.execute(aql_query, bind_vars={'last_sync': last_sync_ts})
    batch_data = [doc for doc in cursor]

    if not batch_data:
        logger.info("No new data found in ArangoDB.")
        return "No updates"

    logger.info(f"Fetched {len(batch_data)} records to sync.")

    # 3. Upsert into PostgreSQL
    upsert_sql = """
    INSERT INTO cdp_profiles (
        tenant_id, 
        ext_id, 
        email, 
        first_name, 
        last_name, 
        mobile_number, 
        raw_attributes,
        updated_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (tenant_id, ext_id) 
    DO UPDATE SET
        email = EXCLUDED.email,
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name,
        mobile_number = EXCLUDED.mobile_number,
        raw_attributes = EXCLUDED.raw_attributes,
        updated_at = NOW();
    """

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                # Enable RLS context
                cur.execute("SET app.current_tenant_id = %s", (DEFAULT_TENANT_ID,))

                for doc in batch_data:
                    # Map ArangoDB fields to PG Schema
                    # '_key' in Arango is usually the best candidate for 'ext_id'
                    ext_id = doc.get('_key') 
                    
                    # Extract typed fields
                    email = doc.get('email')
                    first_name = doc.get('firstName')
                    last_name = doc.get('lastName')
                    phone = doc.get('phone') or doc.get('mobile')

                    # Dump the ENTIRE doc into raw_attributes so we don't lose data
                    raw_attributes = json.dumps(doc)

                    # Execute Upsert
                    cur.execute(upsert_sql, (
                        DEFAULT_TENANT_ID,
                        ext_id,
                        email,
                        first_name,
                        last_name,
                        phone,
                        raw_attributes
                    ))
            
            conn.commit()
            
        # 4. Update Checkpoint in Redis
        redis_client.set(LAST_SYNC_KEY, current_run_time)
        logger.info(f"Sync complete. Next run will fetch data after {current_run_time}")
        return f"Synced {len(batch_data)} records"

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise e