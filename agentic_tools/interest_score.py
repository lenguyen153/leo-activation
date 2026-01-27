import logging
from typing import Dict, Any, List

import datetime
from psycopg.rows import dict_row
import psycopg
import os

from data_utils.arango_client import get_arango_db
from data_utils.pg_client import get_pg_connection
from data_utils.settings import DatabaseSettings

logger = logging.getLogger("agentic_tools.data_enrichment")

HALF_LIFE_DAYS = 7.0
SCORE_THRESHOLD = 1.0 # Delete if score drops below this


# --- 4. ARANGODB FETCHING LOGIC ---
def get_batch_scoring_data(settings: DatabaseSettings, start_time_iso: str, end_time_iso: str) -> List[Dict[str, Any]]:
    """
    Fetches aggregated event scores for users in the target segment.
    """
    db = get_arango_db(settings)
    if not db:
        return []
    
    TARGET_SEGMENT = "Active in last 1 months"

    try:
        # 1. Resolve Segment ID
        segment_query = "FOR s IN cdp_segment FILTER s.name == @segment_name RETURN s._key"
        cursor_seg = db.aql.execute(segment_query, bind_vars={'segment_name': TARGET_SEGMENT})
        found_ids = [s for s in cursor_seg]

        if not found_ids:
            logger.warning(f"⚠️ Segment '{TARGET_SEGMENT}' not found in ArangoDB.")
            return []
        
        target_segment_id = found_ids[0]
        
        # 2. Main Aggregation Query
        # STRICTLY filters out events without tickers (login, page-view, etc)
        scoring_query = """
        FOR event IN cdp_trackingevent
            // 1. Filter by Time Window FIRST (Uses Index on createdAt)
            FILTER event.createdAt >= @start_time
            FILTER event.createdAt < @end_time
            
            // 2. Strict Data Validation (Filter noise early)
            FILTER HAS(event.eventData, 'instrument_id') 
            FILTER event.eventData.instrument_id != null 
            FILTER event.eventData.instrument_id != ""

            // 3. Join with Profile to check Segment membership
            // We use the 'fingerprintId' from the event to look up the profile directly
            FOR profile IN cdp_profile
                FILTER profile.fingerprintId == event.fingerprintId
                FILTER @segment_id IN profile.inSegments[*].id
                
                // 4. Get Weight from Metric
                FOR metric IN cdp_eventmetric
                    FILTER metric.eventName == event.metricName
                    
                    // 5. Aggregate
                    COLLECT 
                        user_id = profile.fingerprintId, 
                        ticker = event.eventData.instrument_id
                    AGGREGATE 
                        total_points = SUM(metric.score),
                        last_seen = MAX(event.createdAt)
                        
                    RETURN {
                        "user_id": user_id,
                        "ticker": ticker,
                        "points": total_points,
                        "last_seen": last_seen
                    }
            """
        
        bind_vars = {
            'segment_id': target_segment_id,
            'start_time': start_time_iso,
            'end_time': end_time_iso
        }
        
        cursor = db.aql.execute(scoring_query, bind_vars=bind_vars)
        results = [r for r in cursor]
        
        logger.info(f"📥 ArangoDB: Found {len(results)} User-Ticker pairs to update.")
        return results

    except Exception as e:
        logger.error(f"❌ ArangoDB Query failed: {e}")
        return []

# --- 5. POSTGRES UPSERT LOGIC ---
def run_batch_scoring_job(settings: DatabaseSettings, start_time: str, end_time: str):
    """
    Orchestrates the fetch from Arango and the Upsert to Postgres.
    """
    
    # A. Fetch Data
    batch_data = get_batch_scoring_data(settings, start_time, end_time)
    
    if not batch_data:
        logger.info("✅ Job finished: No relevant events found in this window.")
        return

    # B. Process Upserts
    conn = get_pg_connection(settings)
    try:
        with conn.cursor() as cur:
            for entry in batch_data:
                user_id = entry['user_id']
                ticker = entry['ticker']
                incoming_points = entry['points']
                
                # 1. Parse Arango Time (Timezone Aware - UTC)
                # Arango returns "2023-10-27T10:00:00Z" -> Python datetime with timezone
                last_event_time = datetime.datetime.fromisoformat(entry['last_seen'].replace("Z", "+00:00"))

                # 2. Fetch Existing
                cur.execute("""
                    SELECT accumulated_weight, last_interaction 
                    FROM user_ticker_affinity 
                    WHERE user_id = %s AND ticker = %s
                """, (user_id, ticker))
                
                record = cur.fetchone() # Returns Dict or None
                
                if record:
                    # UPDATE path
                    current_weight = record['accumulated_weight']
                    prev_interaction = record['last_interaction']
                    
                    # Ensure Postgres time is Timezone Aware ---
                    # Postgres returns naive datetime by default. We assume it was stored as UTC.
                    if prev_interaction.tzinfo is None:
                        prev_interaction = prev_interaction.replace(tzinfo=datetime.timezone.utc)
                    # --- FIX END ---
                    
                    # Calculate Decay
                    time_diff = last_event_time - prev_interaction
                    days_elapsed = max(time_diff.total_seconds() / 86400.0, 0)
                    
                    decay_factor = 0.5 ** (days_elapsed / HALF_LIFE_DAYS)
                    new_weight = (current_weight * decay_factor) + incoming_points
                    
                    cur.execute("""
                        UPDATE user_ticker_affinity 
                        SET accumulated_weight = %s, last_interaction = %s, updated_at = NOW()
                        WHERE user_id = %s AND ticker = %s
                    """, (new_weight, last_event_time, user_id, ticker))
                    
                else:
                    # INSERT path
                    cur.execute("""
                        INSERT INTO user_ticker_affinity 
                        (user_id, ticker, accumulated_weight, last_interaction)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, ticker, incoming_points, last_event_time))
            
            # Commit transaction for the whole batch
            conn.commit()
            logger.info("✅ Batch Upsert Complete.")
            
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Batch Job Failed: {e}")
    finally:
        conn.close()

def init_affinity_table(settings: DatabaseSettings):
    """
    Creates the PostgreSQL table if it does not exist.
    """
    conn = get_pg_connection(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_ticker_affinity (
                    user_id VARCHAR(100) NOT NULL,
                    ticker VARCHAR(20) NOT NULL,
                    accumulated_weight FLOAT DEFAULT 0,
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, ticker)
                )
            """)
            # Create Index for fast dispatch queries
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_affinity_ticker 
                ON user_ticker_affinity(ticker)
            """)
        conn.commit()
        logger.info("✅ Table 'user_ticker_affinity' verified.")
    except Exception as e:
        logger.error(f"❌ Failed to init table: {e}")
    finally:
        conn.close()

def run_garbage_collection(settings: DatabaseSettings):
    """
    Deletes rows where the calculated time-decayed score is below the threshold.
    """
    conn = get_pg_connection(settings)
    try:
        # Math: If CurrentScore < Threshold, Delete.
        # We calculate the decay directly in SQL to be efficient.
        # 604800.0 is the number of seconds in 7 days (Half-Life reference)
        
        query = """
            DELETE FROM user_ticker_affinity
            WHERE (
                accumulated_weight * POWER(0.5, EXTRACT(EPOCH FROM (NOW() - last_interaction)) / (86400.0 * %s))
            ) < %s;
        """
        
        with conn.cursor() as cur:
            cur.execute(query, (HALF_LIFE_DAYS,SCORE_THRESHOLD))
            deleted_count = cur.rowcount
            
        logger.info(f"🧹 Garbage Collection: Removed {deleted_count} rows (Score < {SCORE_THRESHOLD}).")
    except Exception as e:
        logger.error(f"❌ Garbage collection failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 1. Initialize Settings
    settings = DatabaseSettings()
    
    print("--- 1. Initializing Database Tables ---")
    # 2. Run Init (Now with commit!)
    init_affinity_table(settings)
    
    print("--- 2. Running Garbage Collection ---")
    run_garbage_collection(settings)
    
    # 3. Calculate "Previous Hour" Window
    # Logic: If now is 10:45, window is 09:00:00 -> 10:00:00
    now = datetime.datetime.now(datetime.timezone.utc)
    window_end = now.replace(minute=0, second=0, microsecond=0)
    window_start = window_end - datetime.timedelta(hours=150)
    
    start_str = window_start.isoformat()
    end_str = window_end.isoformat()
    
    logger.info(f"🚀 Starting Batch Job for Window: {start_str} to {end_str}")
    
    # 4. Run Job
    run_batch_scoring_job(settings, start_str, end_str)