import logging
from typing import Any, Dict, List
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Initialize logger for this module
logger = logging.getLogger(__name__)


def get_user_contact_from_cdp(db_connection: Any, segment_name: str) -> List[Dict[str, str]]:
    """
    Fetches a list of user contact information belonging to a specific segment.
    Returns: [{ 'email':'...', 'phone': '...', 'firstName': '...', 'lastName': '...'}, ...]
    """
    if not db_connection:
        logger.error("[EmailHelper] Database connection is not available.")
        return []

    try:
        # 1. Resolve Segment Name to ID
        segment_query = "FOR s IN cdp_segment FILTER s.name == @segment_name RETURN s._key"
        cursor_seg = db_connection.aql.execute(segment_query, bind_vars={'segment_name': segment_name})
        found_ids = [s for s in cursor_seg]

        if not found_ids:
            logger.warning(f"[ArangoDB] Segment '{segment_name}' not found.")
            return []
        
        target_segment_id = found_ids[0]
        logger.info(f"[ArangoDB] Resolving recipients for Segment ID: {target_segment_id}")

        # 2. Fetch Profile Data (Email + First Name)
        profile_query = """
        FOR p IN cdp_profile
            FILTER @segment_id IN p.inSegments[*].id
            FILTER (p.primaryPhone != null AND p.primaryPhone != "") OR (p.primaryEmail != null AND p.primaryEmail != "")
            RETURN {
                "email": p.primaryEmail,
                "phone": p.primaryPhone,
                "firstName": p.firstName,
                "lastName": p.lastName
            }
        """
        
        cursor_prof = db_connection.aql.execute(profile_query, bind_vars={'segment_id': target_segment_id})
        recipients = [r for r in cursor_prof]
        
        logger.info(f"[ArangoDB] Found {len(recipients)} profiles for personalization.")
        return recipients

    except Exception as e:
        logger.error(f"[ArangoDB] Query failed: {e}")
        return []
    
def get_subscription_from_cdp(db_connection: Any, segment_name: str) -> List[Dict[str, Any]]:
    """
    Fetches profiles in a segment that have valid Web Push Subscriptions.
    
    Target Field: p.web_push_subscriptions (Array of Objects)
    Returns: [{ '_key': '...', 'firstName': '...', 'subscriptions': [...] }, ...]
    """
    if not db_connection:
        logger.error("[CDPUtils] Database connection is not available.")
        return []

    try:
        # 1. Resolve Segment Name to ID
        # (Identical logic to get_user_contact_from_cdp)
        segment_query = "FOR s IN cdp_segment FILTER s.name == @segment_name RETURN s._key"
        cursor_seg = db_connection.aql.execute(segment_query, bind_vars={'segment_name': segment_name})
        found_ids = [s for s in cursor_seg]

        if not found_ids:
            logger.warning(f"[ArangoDB] Segment '{segment_name}' not found.")
            return []
        
        target_segment_id = found_ids[0]
        logger.info(f"[ArangoDB] Resolving Web Push subscribers for Segment ID: {target_segment_id}")

        # 2. Fetch Profile Data
        # We filter for profiles that actually have subscriptions to avoid processing empty users.
        profile_query = """
        FOR p IN cdp_profile
            FILTER @segment_id IN p.inSegments[*].id
            FILTER LENGTH(
                FOR i IN p.identities[*] 
                FILTER LIKE(i, 'fcm_tokens:%') 
                RETURN i
            ) > 0
            RETURN {
                "_key": p._key,
                "firstName": p.firstName,
                "identities": p.identities
            }
        """
        
        cursor_prof = db_connection.aql.execute(profile_query, bind_vars={'segment_id': target_segment_id})
        recipients = [r for r in cursor_prof]
        
        logger.info(f"[ArangoDB] Found {len(recipients)} subscribers in segment '{segment_name}'.")
        return recipients

    except Exception as e:
        logger.error(f"[ArangoDB] Subscription Query failed: {e}")
        return []
    

def get_users_by_ticker_interest(
    conn: psycopg.Connection, 
    ticker: str, 
    min_score: float
) -> List[Dict[str, Any]]:
    """
    Fetches all profiles interested in a specific ticker with a score above min_score.
    
    Args:
        ticker: The stock symbol (e.g., AAPL)
        min_score: The threshold (0.0 to 1.0) for the interest_score.
    """
    # ### MODIFIED: Updated columns to match new schema ###
    query = """
        SELECT 
            profile_id, 
            interest_score, 
            raw_score, 
            last_interaction
        FROM user_ticker_affinity
        WHERE ticker = %s 
        AND interest_score >= %s
        ORDER BY interest_score DESC;
    """
    
    try:
        with conn.cursor() as cur:
            cur.execute(query, (ticker, min_score))
            results = cur.fetchall()
            return results
            
    except Exception as e:
        print(f"❌ Error fetching interested users: {e}")
        return []
    
def get_ticker_scores_by_profile(conn: psycopg.Connection, profile_id: str) -> List[Dict[str, Any]]:
    """
    Fetches all affinity records for a specific profile_id.
    Returns: [{'ticker': 'AAPL', 'raw_score': 500.0, 'interest_score': 0.83}, ...]
    """
    query = """
        SELECT 
            ticker, 
            raw_score, 
            interest_score
        FROM user_ticker_affinity
        WHERE profile_id = %s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (profile_id,))
            return cur.fetchall()
    except Exception as e:
        print(f"❌ Error fetching user interests: {e}")
        return []