import logging
import os
import sys
from data_utils.settings import DatabaseSettings
from agentic_tools.recommendation_system.predictive_engine import predict_user_event
from agentic_tools.recommendation_system.prescriptive_engine import recommend_system_action

# SETUP
logging.basicConfig(level=logging.INFO)
settings = DatabaseSettings()
conn = settings.get_pg_connection()

# INPUTS (Replace with your actual failing IDs)
TARGET_PROFILE_ID = "wlpn8jKR3WmQejVkjvEG5" 
TARGET_PRODUCT_ID = "VIX" # e.g. AAPL

try:
    print(f"--- DEBUGGING PROFILE: {TARGET_PROFILE_ID} ---")
    
    # 1. Fetch Current State
    with conn.cursor() as cur:
        cur.execute("""
            SELECT interest_score, next_best_action, predicted_user_event 
            FROM product_recommendations 
            WHERE profile_id = %s AND product_id = %s
        """, (TARGET_PROFILE_ID, TARGET_PRODUCT_ID))
        row = cur.fetchone()
        
        if not row:
            print("❌ Row not found in DB!")
            sys.exit(1)
            
        score = float(row[0])
        print(f"1. DB Interest Score: {score}")
        print(f"2. Current NBA in DB: {row[1]}")
        print(f"3. Current NLA in DB: {row[2]}")

        # 2. Test Logic Function Directly
        # We pass a dummy segment to see raw logic output
        print("\n--- TESTING LOGIC ---")
        nla, prob = predict_user_event(score, ["High-Frequency Traders"])
        print(f"4. Logic returns NLA: {nla} (Prob: {prob})")
        
        nba, channel, conf, reason = recommend_system_action(score, nla)
        print(f"5. Logic returns NBA: {nba} (Channel: {channel})")

        # 3. Force SQL Update
        print("\n--- FORCING UPDATE ---")
        update_sql = """
            UPDATE product_recommendations
            SET next_best_action = %s, predicted_user_event = %s, updated_at = NOW()
            WHERE profile_id = %s AND product_id = %s
        """
        cur.execute(update_sql, (nba, nla, TARGET_PROFILE_ID, TARGET_PRODUCT_ID))
        conn.commit()
        print("✅ Forced Update Committed.")

except Exception as e:
    print(f"❌ Error: {e}")
finally:
    conn.close()