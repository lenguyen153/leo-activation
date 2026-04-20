import sys
import os
import json
import psycopg
from typing import Dict, Any, List, Tuple

# --- Imports ---
from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

# REUSE: Import strict logic from the existing worker
from agentic_tools.recommendation_system.interest_score import resolve_ids

# Import the separated logic engines
from agentic_tools.recommendation_system.predictive_engine import predict_user_event
from agentic_tools.recommendation_system.prescriptive_engine import recommend_system_action

configure_logging()
logger = get_logger("agentic_tools.nba_engine")

# --- Configuration ---
# Threshold matches the 'Consideration' zone start in Predictive Engine (0.1), 
# below the threshold is considered 'Cold' and we won't send any NBA (WAIT).
SCORE_THRESHOLD_WARM = 0.1

# Context
TARGET_TENANT = os.getenv("TARGET_TENANT", "master")
TARGET_SEGMENT = os.getenv("TARGET_SEGMENT", "Active in last 3 months")

# --- CORE PIPELINE LOGIC ---
def run_hybrid_pipeline(score: float, segment_names: list) -> Dict[str, Any]:
    """
    Orchestrates the flow: 
    1. Ask Predictive Engine: "What will they do?" (NLA)
    2. Ask Prescriptive Engine: "What should we do?" (NBA)
    """
    # Step A: Prediction (NLA)
    pred_event, pred_prob = predict_user_event(score, segment_names)

    # Step B: Prescription (NBA)
    nba_action, channel, nba_conf, reason = recommend_system_action(score, pred_event)

    return {
        "predicted_user_event": pred_event,
        "prediction_probability": pred_prob,
        "next_best_action": nba_action,
        "nba_confidence": nba_conf,
        "channel": channel,
        "reason": reason
    }

# --- BATCH PROCESSOR (Writes Action to DB) ---
def run_batch_nba_update(settings: DatabaseSettings):
    """
    1. Scans Tenant for top prospects.
    2. Calculates Hybrid Recommendation (NLA + NBA).
    3. UPDATES all 4 columns in 'product_recommendations'.
    """
    conn = settings.get_pg_connection()
    updated_count = 0
    
    try:
        # 1. Resolve Context
        tenant_uuid, _ = resolve_ids(conn, TARGET_TENANT, TARGET_SEGMENT)
        
        logger.info("🚀 Starting NBA batch update for tenant: %s", TARGET_TENANT)

        # 2. Bulk Fetch Query (Top 1 Product Per User)
        batch_query = """
            SELECT
                r.profile_id,
                r.product_id, 
                r.journey_map_id,
                r.journey_stage_id,
                r.recommendation_model,
                r.interest_score, 
                p.segments
            FROM product_recommendations r
            JOIN cdp_profiles p ON r.profile_id = p.profile_id 
                               AND r.tenant_id = p.tenant_id
            WHERE r.tenant_id = %s 
              AND r.interest_score >= %s
            ORDER BY r.profile_id, r.interest_score DESC;
        """

        # 3. Prepared Update Statement (Hybrid Schema)
        update_sql = """
            UPDATE product_recommendations
            SET next_best_action = %s,
                nba_confidence = %s,
                predicted_user_event = %s,
                prediction_probability = %s,
                updated_at = NOW()
            WHERE tenant_id = %s
              AND profile_id = %s
              AND product_id = %s
              AND journey_map_id = %s
              AND journey_stage_id = %s
              AND recommendation_model = %s;
        """

        with conn.cursor() as cur:
            # A. Fetch Candidates (Using corrected threshold 0.3)
            cur.execute(batch_query, (str(tenant_uuid), SCORE_THRESHOLD_WARM))
            rows = cur.fetchall()
            
            logger.info("🔍 Found %d candidates for NBA assignment.", len(rows))

            # B. Iterate & Update
            for row in rows:
                # Unpack
                if isinstance(row, dict):
                    p_id = row['profile_id']
                    prod_id = row['product_id']
                    j_map = row['journey_map_id']
                    j_stage = row['journey_stage_id']
                    rec_model = row['recommendation_model']
                    score = float(row['interest_score'])
                    raw_segments = row['segments']
                else:
                    p_id, prod_id, j_map, j_stage, rec_model, score, raw_segments = row

                # Parse Segments
                segment_names = []
                if raw_segments:
                    data = raw_segments if isinstance(raw_segments, list) else json.loads(raw_segments)
                    segment_names = [s.get('name') for s in data if isinstance(s, dict)]

                # Run Pipeline
                result = run_hybrid_pipeline(score, segment_names)
                
                # C. Execute Update (Always, even if NBA is WAIT)
                cur.execute(update_sql, (
                    result["next_best_action"],
                    result["nba_confidence"],
                    result["predicted_user_event"],
                    result["prediction_probability"],
                    str(tenant_uuid),
                    p_id,
                    prod_id,
                    j_map,
                    j_stage,
                    rec_model
                ))
                updated_count += 1
            
            conn.commit()
        
        log_event(logger, "✅ nba_batch_update_complete",
                  candidates=len(rows), updated=updated_count)

    except Exception as e:
        conn.rollback()
        logger.error("❌ Batch NBA Update Failed: %s", e)
    finally:
        conn.close()


# --- SINGLE LOOKUP (Read-Only for API) ---
def get_next_best_action(conn, tenant_uuid: str, profile_id: str) -> Dict[str, Any]:
    """
    Fetches ALL valid interest scores for a user and calculates NBA for EACH.
    """

    # Query gets ALL rows for this user, not just the top 1
    query = """
        SELECT 
            r.product_id, 
            r.interest_score, 
            p.segments
        FROM product_recommendations r
        JOIN cdp_profiles p ON r.profile_id = p.profile_id 
                           AND r.tenant_id = p.tenant_id
        WHERE r.tenant_id = %s 
          AND r.profile_id = %s
        ORDER BY r.interest_score DESC;
    """
    
    actions_map = {}

    with conn.cursor() as cur:
        cur.execute(query, (str(tenant_uuid), profile_id))
        rows = cur.fetchall()

        if not rows:
            return {
                "profile_id": profile_id,
                "next_best_actions": {}
            }

        for row in rows:
            # Unpack Row
            if isinstance(row, dict):
                ticker = row['product_id']
                score = float(row['interest_score'])
                raw_segments = row['segments']
            else:
                ticker = row[0]
                score = float(row[1])
                raw_segments = row[2]

            # Parse Segments (needed for Persona logic)
            segment_names = []
            if raw_segments:
                data = raw_segments if isinstance(raw_segments, list) else json.loads(raw_segments)
                segment_names = [s.get('name') for s in data if isinstance(s, dict)]

            # Run Pipeline for THIS specific ticker
            result = run_hybrid_pipeline(score, segment_names)

            # Add to map
            actions_map[ticker] = {
                "action": result["next_best_action"],
                "channel": result["channel"],
                "confidence_score": result["nba_confidence"],
                "reason": result["reason"]
            }

    return {
        "profile_id": profile_id,
        "next_best_actions": actions_map
    }

def get_next_likely_action(conn, tenant_uuid: str, profile_id: str) -> Dict[str, Any]:
    """
    Fetches ALL valid interest scores for a user and calculates NLA for EACH.
    """
    # Query gets ALL rows for this user
    query = """
        SELECT 
            r.product_id, 
            r.interest_score, 
            p.segments
        FROM product_recommendations r
        JOIN cdp_profiles p ON r.profile_id = p.profile_id 
                           AND r.tenant_id = p.tenant_id
        WHERE r.tenant_id = %s 
          AND r.profile_id = %s
        ORDER BY r.interest_score DESC;
    """
    
    actions_map = {}

    with conn.cursor() as cur:
        cur.execute(query, (str(tenant_uuid), profile_id))
        rows = cur.fetchall()

        if not rows:
            return {
                "profile_id": profile_id,
                "next_likely_actions": {}
            }

        for row in rows:
            # Unpack Row
            if isinstance(row, dict):
                ticker = row['product_id']
                score = float(row['interest_score'])
                raw_segments = row['segments']
            else:
                ticker = row[0]
                score = float(row[1])
                raw_segments = row[2]

            # Parse Segments (needed for Persona logic)
            segment_names = []
            if raw_segments:
                data = raw_segments if isinstance(raw_segments, list) else json.loads(raw_segments)
                segment_names = [s.get('name') for s in data if isinstance(s, dict)]

            # Run Pipeline for THIS specific ticker
            result = run_hybrid_pipeline(score, segment_names)

            # Add to map
            actions_map[ticker] = {
                "action": result["predicted_user_event"],
                "confidence_score": result["prediction_probability"]
            }

    return {
        "profile_id": profile_id,
        "next_likely_actions": actions_map
    }


if __name__ == "__main__":
    settings = DatabaseSettings()
    
    if len(sys.argv) > 1:
        target_profile_id = sys.argv[1]
        conn = settings.get_pg_connection()
        try:
            tenant_uuid, _ = resolve_ids(conn, TARGET_TENANT, TARGET_SEGMENT)
            result = get_next_best_action(conn, tenant_uuid, target_profile_id)
            print(json.dumps(result, indent=2))
        finally:
            conn.close()
    else:
        run_batch_nba_update(settings)