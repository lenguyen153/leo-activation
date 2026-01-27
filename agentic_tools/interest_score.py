import logging
from typing import Dict, Any, List

import datetime
from psycopg.rows import dict_row
import psycopg
import os

from data_utils.arango_client import get_arango_db
from data_utils.settings import DatabaseSettings

logger = logging.getLogger("agentic_tools.data_enrichment")

HALF_LIFE_DAYS = 7.0
SCORE_THRESHOLD = 0.01 # Delete if score drops below this
TARGET_SEGMENT = "Active in last 1 months"

# CONSTANT: The "Half-Way" Point.
# At 100 raw points, the user has a 0.5 (50%) interest score.
# At 1000 raw points, the user has a 0.9 (90%) interest score.
SCORING_K_FACTOR = 100.0

# --- 4. ARANGODB FETCHING LOGIC ---
def get_batch_scoring_data(settings: DatabaseSettings, start_time_iso: str, end_time_iso: str) -> List[Dict[str, Any]]:
    """
    Fetches events and resolves them to the Profile _key (profile_id).
    """
    db = get_arango_db(settings)
    if not db:
        return []
    
    try:
        # A. Resolve Segment Name to ID
        segment_query = "FOR s IN cdp_segment FILTER s.name == @segment_name RETURN s._key"
        cursor_seg = db.aql.execute(segment_query, bind_vars={'segment_name': TARGET_SEGMENT})
        found_ids = [s for s in cursor_seg]

        if not found_ids:
            logger.warning(f"⚠️ Segment '{TARGET_SEGMENT}' not found in ArangoDB.")
            return []
        
        target_segment_id = found_ids[0]
        
        # B. Main Query: Event -> Profile (Get _key) -> Metric
        scoring_query = """
        FOR event IN cdp_trackingevent
            // 1. Time Window Filter
            FILTER event.createdAt >= @start_time
            FILTER event.createdAt < @end_time
            
            // 2. Data Validation
            FILTER HAS(event.eventData, 'instrument_id') 
            FILTER event.eventData.instrument_id != null 
            FILTER event.eventData.instrument_id != ""

            // 3. Join Profile (Link via fingerprintId, but select _key)
            FOR profile IN cdp_profile
                FILTER profile.fingerprintId == event.fingerprintId
                FILTER @segment_id IN profile.inSegments[*].id
                
                // 4. Get Weight
                FOR metric IN cdp_eventmetric
                    FILTER metric.eventName == event.metricName
                    
                    // 5. Aggregate by Profile Key + Ticker
                    COLLECT 
                        pid = profile._key, 
                        ticker = event.eventData.instrument_id
                    AGGREGATE 
                        total_points = SUM(metric.score),
                        last_seen = MAX(event.createdAt)
                        
                    RETURN {
                        "profile_id": pid,
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
        
        logger.info(f"📥 ArangoDB: Found {len(results)} Profile-Ticker pairs to update.")
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
    conn = settings.get_pg_connection()
    try:
        with conn.cursor() as cur:
            for entry in batch_data:
                profile_id = entry['profile_id']
                ticker = entry['ticker']
                incoming_points = entry['points'] # Raw points (e.g. 5.0)
                
                last_event_time = datetime.datetime.fromisoformat(entry['last_seen'].replace("Z", "+00:00"))

                # 1. Fetch Existing RAW Score
                cur.execute("SELECT raw_score, last_interaction FROM user_ticker_affinity WHERE profile_id = %s AND ticker = %s", (profile_id, ticker))
                record = cur.fetchone()
                
                final_raw_score = 0.0
                
                if record:
                    # UPDATE path
                    current_raw = record['raw_score']
                    prev_interaction = record['last_interaction']
                    
                    if prev_interaction.tzinfo is None:
                        prev_interaction = prev_interaction.replace(tzinfo=datetime.timezone.utc)
                    
                    # 2. Apply Time Decay to RAW Score
                    time_diff = last_event_time - prev_interaction
                    days_elapsed = max(time_diff.total_seconds() / 86400.0, 0)
                    decay_factor = 0.5 ** (days_elapsed / HALF_LIFE_DAYS)
                    
                    decayed_raw = current_raw * decay_factor
                    
                    # 3. Add New Points
                    final_raw_score = decayed_raw + incoming_points
                else:
                    # INSERT path
                    final_raw_score = incoming_points

                # 4. Calculate Normalized Interest Score (0 to 1)
                # Formula: Raw / (Raw + K)
                final_interest_score = final_raw_score / (final_raw_score + SCORING_K_FACTOR)
                
                # 5. Upsert Both Scores
                if record:
                    cur.execute("""
                        UPDATE user_ticker_affinity 
                        SET raw_score = %s, interest_score = %s, last_interaction = %s, updated_at = NOW()
                        WHERE profile_id = %s AND ticker = %s
                    """, (final_raw_score, final_interest_score, last_event_time, profile_id, ticker))
                else:
                    cur.execute("""
                        INSERT INTO user_ticker_affinity 
                        (profile_id, ticker, raw_score, interest_score, last_interaction)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (profile_id, ticker, final_raw_score, final_interest_score, last_event_time))
            
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
    conn = settings.get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_ticker_affinity (
                    profile_id VARCHAR(100) NOT NULL,
                    ticker VARCHAR(20) NOT NULL,
                    raw_score FLOAT DEFAULT 0,       -- The actual accumulated points (e.g., 500.0)
                    interest_score FLOAT DEFAULT 0,  -- The normalized 0-1 score (e.g., 0.83)
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (profile_id, ticker)
                )
            """)
            
            # Create Index for fast lookups
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
    conn = settings.get_pg_connection()
    try:
        # Math: If CurrentScore < Threshold, Delete.
        # We calculate the decay directly in SQL to be efficient.
        # 604800.0 is the number of seconds in 7 days (Half-Life reference)
        
        query = """
            DELETE FROM user_ticker_affinity
            WHERE interest_score < %s;
        """
        
        with conn.cursor() as cur:
            cur.execute(query, (SCORE_THRESHOLD,))
            deleted_count = cur.rowcount

        conn.commit()
            
        logger.info(f"🧹 Garbage Collection: Removed {deleted_count} rows (Score < {SCORE_THRESHOLD}).")
    except Exception as e:
        conn.rollback()
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
    window_start = window_end - datetime.timedelta(hours=1)
    
    start_str = window_start.isoformat()
    end_str = window_end.isoformat()
    
    logger.info(f"🚀 Starting Batch Job for Window: {start_str} to {end_str}")
    
    # 4. Run Job
    run_batch_scoring_job(settings, start_str, end_str)